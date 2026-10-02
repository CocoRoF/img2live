// SPDX-License-Identifier: Apache-2.0
/**
 * img2live puppet runtime: pure logic, no DOM and no WebGL (importable in Node).
 *
 *   PuppetModel      parses puppet.json, evaluates vertex positions / opacity exactly like
 *                    src/img2live/rig/runtime_py.py (see docs/puppet-format.md)
 *   PhysicsSim       damped second-order response driven by the acceleration of a weighted input
 *   IdleController   idle tracks, blink scheduler (incl. double blink) and saccades
 *   PuppetController user values + idle + blink + follow + physics -> final, clamped parameter values
 *
 * Parameter values are passed around as Float64Array indexed by `model.paramIndex.get(id)`.
 */

export const SCHEMA = "img2live-puppet/1";

export const clamp = (v, lo, hi) => (v < lo ? lo : v > hi ? hi : v);
const smoothstep = (x) => {
  x = x < 0 ? 0 : x > 1 ? 1 : x;
  return x * x * (3 - 2 * x);
};

/** Small deterministic PRNG so tests can seed the idle motion. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function rand() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** numpy.interp semantics: piecewise linear, clamped at both ends (keys ascending). */
export function interp1(keys, values, x) {
  const n = keys.length;
  if (n === 0) return 0;
  if (x <= keys[0]) return values[0];
  if (x >= keys[n - 1]) return values[n - 1];
  for (let i = 0; i < n - 1; i++) {
    if (keys[i] <= x && x <= keys[i + 1]) {
      const span = keys[i + 1] - keys[i];
      const t = span > 0 ? (x - keys[i]) / span : 0;
      return values[i] * (1 - t) + values[i + 1] * t;
    }
  }
  return values[n - 1];
}

const KIND_FIELD = 0;
const KIND_ROTATE = 1;
const KIND_SHIFT = 2;

/* ===================================================================================================== */
/* PuppetModel                                                                                           */
/* ===================================================================================================== */

export class PuppetModel {
  /** @param {object} puppet parsed puppet.json */
  constructor(puppet) {
    if (!puppet || typeof puppet !== "object" || !Array.isArray(puppet.meshes) || !Array.isArray(puppet.params)) {
      throw new Error("not an img2live puppet: expected an object with `params` and `meshes`");
    }
    if (puppet.schema && puppet.schema !== SCHEMA) {
      throw new Error(`unsupported puppet schema "${puppet.schema}" (this viewer reads ${SCHEMA})`);
    }
    this.json = puppet;
    this.schema = puppet.schema || SCHEMA;
    this.canvas = { w: puppet.canvas?.w ?? 1024, h: puppet.canvas?.h ?? 1024 };
    this.warnings = [];

    // ---- parameters -------------------------------------------------------------------------
    this.params = puppet.params.map((p, index) => ({
      id: p.id,
      name: p.name || p.id,
      min: Number(p.min ?? 0),
      max: Number(p.max ?? 1),
      default: Number(p.default ?? 0),
      driven: !!p.driven,
      index,
    }));
    this.paramIndex = new Map(this.params.map((p) => [p.id, p.index]));
    const np = this.params.length;
    this.defaults = new Float64Array(np);
    this.mins = new Float64Array(np);
    this.maxs = new Float64Array(np);
    this.params.forEach((p, i) => {
      this.defaults[i] = p.default;
      this.mins[i] = p.min;
      this.maxs[i] = p.max;
    });

    // ---- meshes (stable-sorted by draw order) ---------------------------------------------------
    const idx = puppet.meshes.map((_, i) => i).sort((a, b) => (puppet.meshes[a].order ?? 100) - (puppet.meshes[b].order ?? 100) || a - b);
    this.meshes = idx.map((src) => this._compileMesh(puppet.meshes[src]));
    this.meshIndex = new Map(this.meshes.map((m, i) => [m.id, i]));
    for (const m of this.meshes) {
      m.clipIndex = m.clip != null ? (this.meshIndex.has(m.clip) ? this.meshIndex.get(m.clip) : -1) : -1;
      if (m.clip != null && m.clipIndex < 0) this.warnings.push(`mesh ${m.id}: clip mesh "${m.clip}" not found, drawn unclipped`);
    }
    this.maxVertices = this.meshes.reduce((a, m) => Math.max(a, m.vertexCount), 0);
    this._scratch = new Float64Array(this.maxVertices * 2);
    this._tmpValues = new Float64Array(np);

    // ---- pass-through sections --------------------------------------------------------------------
    this.bounds = puppet.bounds || this._computeBounds();
    this.headBounds = puppet.headBounds || this.bounds;
    this.physics = Array.isArray(puppet.physics) ? puppet.physics : [];
    this.motions = puppet.motions || {};
    this.groups = puppet.groups || {};
    this.meta = puppet.meta || {};
    this.vertexCount = this.meshes.reduce((a, m) => a + m.vertexCount, 0);
    this.triangleCount = this.meshes.reduce((a, m) => a + m.indices.length / 3, 0);
  }

  _compileMesh(m) {
    const pos = Float64Array.from(m.positions);
    const n = pos.length / 2;
    if (!Number.isInteger(n)) throw new Error(`mesh ${m.id}: odd number of position values`);
    const uvs = Float32Array.from(m.uvs || []);
    if (uvs.length !== pos.length) throw new Error(`mesh ${m.id}: uvs (${uvs.length}) do not match positions (${pos.length})`);
    const indices = n < 65536 ? Uint16Array.from(m.indices) : Uint32Array.from(m.indices);
    for (let k = 0; k < indices.length; k++) {
      if (indices[k] >= n) throw new Error(`mesh ${m.id}: index ${indices[k]} out of range (${n} vertices)`);
    }
    const deps = new Set();
    const deform = [];
    for (const d of m.deform || []) {
      const p = this.paramIndex.has(d.param) ? this.paramIndex.get(d.param) : -1;
      if (p < 0) this.warnings.push(`mesh ${m.id}: deform uses unknown parameter ${d.param} (treated as 0)`);
      else deps.add(p);
      if (d.fields) {
        const keys = Float64Array.from(d.keys);
        if (d.fields.length !== keys.length) throw new Error(`mesh ${m.id}: ${d.param} keys/fields length mismatch`);
        const fields = d.fields.map((f) => {
          if (f == null) return null;
          if (f.length !== pos.length) throw new Error(`mesh ${m.id}: ${d.param} field has ${f.length} values, expected ${pos.length}`);
          return Float64Array.from(f);
        });
        deform.push({ kind: KIND_FIELD, p, keys, fields });
      } else if (d.kind === "rotate") {
        deform.push({ kind: KIND_ROTATE, p, px: d.pivot[0], py: d.pivot[1], degPerUnit: d.degPerUnit });
      } else if (d.kind === "shift") {
        deform.push({ kind: KIND_SHIFT, p, sx: d.perUnit[0], sy: d.perUnit[1] });
      } else {
        this.warnings.push(`mesh ${m.id}: unknown deform entry ignored (${JSON.stringify(d).slice(0, 60)})`);
      }
    }
    let opacityBind = null;
    if (m.opacityBind) {
      const b = m.opacityBind;
      const p = this.paramIndex.has(b.param) ? this.paramIndex.get(b.param) : -1;
      if (p >= 0) deps.add(p);
      opacityBind = { p, param: b.param, keys: Float64Array.from(b.keys), values: Float64Array.from(b.values) };
    }
    const depList = Int32Array.from([...deps].sort((a, b) => a - b));
    return {
      id: m.id,
      tag: m.tag || "",
      order: m.order ?? 100,
      texture: m.texture,
      texSize: m.texSize || [0, 0],
      clip: m.clip ?? null,
      clipIndex: -1,
      opacity: m.opacity ?? 1,
      opacityBind,
      positions: pos,
      uvs,
      indices,
      vertexCount: n,
      deform,
      deps: depList,
      _last: new Float64Array(depList.length).fill(NaN),
      _evaluated: false,
    };
  }

  _computeBounds() {
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const m of this.meshes) {
      for (let k = 0; k < m.positions.length; k += 2) {
        x0 = Math.min(x0, m.positions[k]); x1 = Math.max(x1, m.positions[k]);
        y0 = Math.min(y0, m.positions[k + 1]); y1 = Math.max(y1, m.positions[k + 1]);
      }
    }
    return [x0, y0, x1, y1];
  }

  /** Accept either an indexed value array or a plain {id: value} object (missing ids use the defaults). */
  _asValues(params) {
    if (params && typeof params.length === "number") return params;
    const v = this._tmpValues;
    v.set(this.defaults);
    if (params) {
      for (const id in params) {
        const i = this.paramIndex.get(id);
        if (i !== undefined) v[i] = params[id];
      }
    }
    return v;
  }

  /** A fresh value array holding the default of every parameter. */
  makeValues() {
    return Float64Array.from(this.defaults);
  }

  /**
   * Evaluate mesh `i` (index in draw order) into `out` (2 * vertexCount numbers, x/y interleaved, canvas px).
   * Accumulates in float64 so float32 output differs from the Python reference by < 1e-3 px.
   */
  evaluateMesh(i, params, out) {
    const vals = this._asValues(params);
    const m = this.meshes[i];
    const n2 = m.positions.length;
    const s = this._scratch;
    s.set(m.positions);
    const deform = m.deform;
    for (let di = 0; di < deform.length; di++) {
      const d = deform[di];
      const v = d.p >= 0 ? vals[d.p] : 0;
      if (d.kind === KIND_FIELD) {
        const keys = d.keys;
        const K = keys.length;
        if (v <= keys[0]) {
          addField(s, d.fields[0], 1, n2);
        } else if (v >= keys[K - 1]) {
          addField(s, d.fields[K - 1], 1, n2);
        } else {
          for (let k = 0; k < K - 1; k++) {
            if (keys[k] <= v && v <= keys[k + 1]) {
              const t = (v - keys[k]) / (keys[k + 1] - keys[k]);
              addField(s, d.fields[k], 1 - t, n2);
              addField(s, d.fields[k + 1], t, n2);
              break;
            }
          }
        }
      } else if (d.kind === KIND_ROTATE) {
        const a = (d.degPerUnit * v * Math.PI) / 180;
        const c = Math.cos(a);
        const sn = Math.sin(a);
        const px = d.px;
        const py = d.py;
        for (let k = 0; k < n2; k += 2) {
          const x = s[k] - px;
          const y = s[k + 1] - py;
          s[k] = px + c * x - sn * y;
          s[k + 1] = py + sn * x + c * y;
        }
      } else {
        const sx = d.sx * v;
        const sy = d.sy * v;
        for (let k = 0; k < n2; k += 2) {
          s[k] += sx;
          s[k + 1] += sy;
        }
      }
    }
    for (let k = 0; k < n2; k++) out[k] = s[k];
    return out;
  }

  /** Evaluate only when one of the parameters this mesh depends on changed since the last call. */
  evaluateMeshIfChanged(i, params, out) {
    const vals = this._asValues(params);
    const m = this.meshes[i];
    const deps = m.deps;
    const last = m._last;
    let changed = !m._evaluated; // meshes without any deformation still need one initial evaluation
    for (let k = 0; k < deps.length; k++) {
      const v = vals[deps[k]];
      if (v !== last[k]) {
        last[k] = v;
        changed = true;
      }
    }
    if (changed) {
      this.evaluateMesh(i, vals, out);
      m._evaluated = true;
    }
    return changed;
  }

  /** Forget the change cache (forces the next evaluateMeshIfChanged to recompute, e.g. after a GL context restore). */
  invalidate() {
    for (const m of this.meshes) {
      m._last.fill(NaN);
      m._evaluated = false;
    }
  }

  /** Mesh opacity for the given parameters (opacityBind, else the static `opacity`, else 1). */
  opacityOf(i, params) {
    const m = this.meshes[i];
    const b = m.opacityBind;
    if (!b) return m.opacity;
    const vals = this._asValues(params);
    return interp1(b.keys, b.values, b.p >= 0 ? vals[b.p] : 0);
  }

  /** Evaluate everything for a {id:value} object: {meshId: Float64Array}. Convenience for tests/tools. */
  evaluateAll(params) {
    const vals = Float64Array.from(this._asValues(params));
    const out = {};
    for (let i = 0; i < this.meshes.length; i++) {
      out[this.meshes[i].id] = this.evaluateMesh(i, vals, new Float64Array(this.meshes[i].positions.length));
    }
    return out;
  }

  /**
   * Which way does the mesh geometry move on screen when `paramId` goes from min to max?
   * Returns sign(mean displacement along `axis`) over every keyform field that uses the parameter
   * (axis 0 = x, 1 = y; y is down).  Lets the viewer cope with sign conventions without hard-coding them.
   */
  fieldDirection(paramId, axis) {
    const p = this.paramIndex.get(paramId);
    if (p === undefined) return 0;
    let sum = 0;
    let count = 0;
    for (const m of this.meshes) {
      for (const d of m.deform) {
        if (d.kind !== KIND_FIELD || d.p !== p) continue;
        const lo = d.fields[0];
        const hi = d.fields[d.fields.length - 1];
        const n = m.positions.length / 2;
        for (let k = 0; k < n; k++) {
          sum += (hi ? hi[2 * k + axis] : 0) - (lo ? lo[2 * k + axis] : 0);
          count++;
        }
      }
    }
    if (!count || Math.abs(sum) < 1e-9) return 0;
    return sum > 0 ? 1 : -1;
  }
}

function addField(s, f, w, n2) {
  if (f === null || w === 0) return;
  if (w === 1) for (let k = 0; k < n2; k++) s[k] += f[k];
  else for (let k = 0; k < n2; k++) s[k] += f[k] * w;
}

/* ===================================================================================================== */
/* ParamStore                                                                                            */
/* ===================================================================================================== */

/** Parameter values with defaults and ranges: `values` is indexed like `model.params`, writes are clamped. */
export class ParamStore {
  constructor(model) {
    this.model = model;
    this.values = Float64Array.from(model.defaults);
  }
  has(id) {
    return this.model.paramIndex.has(id);
  }
  get(id) {
    const i = this.model.paramIndex.get(id);
    return i === undefined ? undefined : this.values[i];
  }
  /** Clamp to [min, max] and store; returns false for an unknown id. */
  set(id, v) {
    const i = this.model.paramIndex.get(id);
    if (i === undefined) return false;
    const x = Number(v);
    this.values[i] = Number.isFinite(x) ? clamp(x, this.model.mins[i], this.model.maxs[i]) : this.model.defaults[i];
    return true;
  }
  reset() {
    this.values.set(this.model.defaults);
  }
  toObject() {
    const o = {};
    const ps = this.model.params;
    for (let i = 0; i < ps.length; i++) o[ps[i].id] = this.values[i];
    return o;
  }
}

/* ===================================================================================================== */
/* PhysicsSim                                                                                            */
/* ===================================================================================================== */

/**
 * For every `physics` entry:  u = sum(w_i * param_i);  o'' = -(2 pi f)^2 o - 2 zeta (2 pi f) o' - gain * u''
 * u'' is the finite-difference acceleration of a slightly low-passed u.  Integrated with fixed sub-steps
 * (semi-implicit Euler, 1/120 s) so the result does not depend on the frame rate; dt is clamped.
 */
export class PhysicsSim {
  /**
   * @param {object[]} entries puppet.physics
   * @param {PuppetModel} model
   */
  constructor(entries, model, { subStep = 1 / 120, maxDt = 1 / 20, inputSmoothing = 0.04 } = {}) {
    this.subStep = subStep;
    this.maxDt = maxDt;
    this.inputSmoothing = inputSmoothing;
    this.time = 0;
    this.items = [];
    (entries || []).forEach((e, n) => {
      const out = model.paramIndex.has(e.out) ? model.paramIndex.get(e.out) : -1;
      if (out < 0) return;
      const ins = [];
      const ws = [];
      for (const [pid, w] of e.in || []) {
        const i = model.paramIndex.get(pid);
        if (i !== undefined) {
          ins.push(i);
          ws.push(w);
        }
      }
      this.items.push({
        out,
        ins: Int32Array.from(ins),
        ws: Float64Array.from(ws),
        omega: 2 * Math.PI * (e.freq ?? 1),
        zeta: e.damping ?? 0.3,
        gain: e.gain ?? 1,
        limit: e.limit ?? 1,
        wind: e.wind ?? 0,
        phase: e.phase ?? n * 2.17,
        o: 0,
        vel: 0,
        uf: 0,
        vPrev: 0,
        primed: false,
      });
    });
  }

  reset() {
    this.time = 0;
    for (const it of this.items) {
      it.o = 0;
      it.vel = 0;
      it.vPrev = 0;
      it.primed = false;
    }
  }

  /** Reads the inputs from `values`, writes each physics output back into `values` (unclamped to the param range). */
  step(dt, values) {
    if (!(dt > 0)) dt = 0;
    if (dt > this.maxDt) dt = this.maxDt;
    this.time += dt;
    for (let n = 0; n < this.items.length; n++) {
      const it = this.items[n];
      let u = 0;
      for (let k = 0; k < it.ins.length; k++) u += it.ws[k] * values[it.ins[k]];
      if (!it.primed) {
        it.uf = u;
        it.vPrev = 0;
        it.primed = true;
      } else if (dt > 0) {
        const alpha = this.inputSmoothing > 0 ? 1 - Math.exp(-dt / this.inputSmoothing) : 1;
        const ufNew = it.uf + (u - it.uf) * alpha;
        const v = (ufNew - it.uf) / dt;
        let acc = (v - it.vPrev) / dt;
        if (acc > 4000) acc = 4000;
        else if (acc < -4000) acc = -4000;
        it.uf = ufNew;
        it.vPrev = v;
        const n = Math.max(1, Math.ceil(dt / this.subStep));
        const h = dt / n;
        const w2 = it.omega * it.omega;
        const c = 2 * it.zeta * it.omega;
        for (let s = 0; s < n; s++) {
          const a = -w2 * it.o - c * it.vel - it.gain * acc;
          it.vel += a * h;
          it.o += it.vel * h;
          if (it.o > it.limit) {
            it.o = it.limit;
            if (it.vel > 0) it.vel = 0;
          } else if (it.o < -it.limit) {
            it.o = -it.limit;
            if (it.vel < 0) it.vel = 0;
          }
        }
      }
      let out = it.o;
      if (it.wind) out += it.wind * Math.sin(this.time * 0.9 + it.phase);
      values[it.out] = out;
    }
  }
}

/* ===================================================================================================== */
/* IdleController                                                                                        */
/* ===================================================================================================== */

/**
 * Produces additive (`add`) and multiplicative (`mul`) parameter modifiers:
 *   idle tracks   add  w * (offset + amp * sin(2 pi t / period + phase))
 *   blink         mul  1 -> 0 -> 1 on the blink params (user open value x factor)
 *   saccade       add  small random gaze jumps on EyeBallX/Y
 * Each modifier fades out (and back in) per parameter while that parameter is `active`
 * (the user is dragging it / the cursor is steering it), so the idle never fights the user.
 */
export class IdleController {
  constructor(model, { seed = 1 } = {}) {
    this.model = model;
    const n = model.params.length;
    this.add = new Float64Array(n);
    this.mul = new Float64Array(n).fill(1);
    this.time = 0;
    this.rand = mulberry32(seed);

    const motions = model.motions || {};
    this.tracks = [];
    for (const t of motions.idle?.tracks || []) {
      const i = model.paramIndex.get(t.param);
      if (i !== undefined) {
        this.tracks.push({ i, amp: t.amp ?? 0, period: Math.max(t.period ?? 5, 1e-3), phase: t.phase ?? 0, offset: t.offset ?? 0 });
      }
    }
    this.hasIdle = this.tracks.length > 0;
    this._trackParams = Int32Array.from(new Set(this.tracks.map((t) => t.i)));
    this.hasSaccade = !!motions.idle?.saccade;
    this._wIdle = new Float64Array(n);

    const b = motions.blink || {};
    this.blinkCfg = {
      enabled: b.enabled !== false && !!motions.blink,
      min: b.intervalMin ?? 2.4,
      max: b.intervalMax ?? 6,
      duration: Math.max(b.duration ?? 0.2, 0.04),
      doubleProb: b.doubleBlinkProb ?? 0.15,
      params: (b.params || model.groups?.EyeBlink || []).map((id) => model.paramIndex.get(id)).filter((i) => i !== undefined),
    };
    this.hasBlink = this.blinkCfg.params.length > 0;
    this._wBlink = new Float64Array(n).fill(1); // blink is allowed from the start; the weight only drops while the user steers an eye param
    this._blink = { running: false, start: 0, second: false, nextAt: this._nextBlinkDelay(0.6) };

    this.ex = model.paramIndex.has("ParamEyeBallX") ? model.paramIndex.get("ParamEyeBallX") : -1;
    this.ey = model.paramIndex.has("ParamEyeBallY") ? model.paramIndex.get("ParamEyeBallY") : -1;
    this._gaze = { x: 0, y: 0, tx: 0, ty: 0, nextAt: 0.8 + this.rand() * 1.5, wx: 0, wy: 0 };
  }

  _nextBlinkDelay(scale = 1) {
    const c = this.blinkCfg;
    return (c.min + this.rand() * Math.max(c.max - c.min, 0)) * scale;
  }

  /** Start a blink now (no-op while one is running). */
  triggerBlink() {
    if (this._blink.running) return;
    this._blink.nextAt = this.time;
    this._blink.second = true; // a manual blink never chains into a double blink
  }

  reset() {
    this.time = 0;
    this.add.fill(0);
    this.mul.fill(1);
    this._wIdle.fill(0);
    this._wBlink.fill(1);
    this._blink = { running: false, start: 0, second: false, nextAt: this._nextBlinkDelay(0.6) };
    Object.assign(this._gaze, { x: 0, y: 0, tx: 0, ty: 0, nextAt: 0.8 + this.rand() * 1.5, wx: 0, wy: 0 });
  }

  /**
   * @param {number} dt seconds
   * @param {Uint8Array} active per-parameter flag: 1 while the user/cursor steers it
   * @param {{idle:boolean, blink:boolean}} opt
   */
  update(dt, active, opt) {
    this.time += dt;
    const t = this.time;
    const add = this.add;
    const mul = this.mul;
    add.fill(0);
    mul.fill(1);

    // ---- idle tracks
    const kIn = 1 - Math.exp(-dt / 0.5);
    const kOut = 1 - Math.exp(-dt / 0.12);
    const wI = this._wIdle;
    const idleOn = opt.idle && this.hasIdle;
    const tp = this._trackParams;
    for (let k = 0; k < tp.length; k++) {
      const i = tp[k];
      const target = idleOn && !active[i] ? 1 : 0;
      wI[i] += (target - wI[i]) * (target > wI[i] ? kIn : kOut);
    }
    const tracks = this.tracks;
    for (let k = 0; k < tracks.length; k++) {
      const tr = tracks[k];
      add[tr.i] += wI[tr.i] * (tr.offset + tr.amp * Math.sin((2 * Math.PI * t) / tr.period + tr.phase));
    }

    // ---- blink
    const bc = this.blinkCfg;
    const bl = this._blink;
    let factor = 1;
    if (!bl.running && opt.blink && this.hasBlink && t >= bl.nextAt) {
      bl.running = true;
      bl.start = t;
    }
    if (bl.running) {
      const p = (t - bl.start) / bc.duration;
      if (p >= 1) {
        bl.running = false;
        if (!bl.second && this.rand() < bc.doubleProb) {
          bl.second = true;
          bl.nextAt = t + 0.07;
        } else {
          bl.second = false;
          bl.nextAt = t + this._nextBlinkDelay();
        }
      } else {
        factor = p < 0.4 ? 1 - smoothstep(p / 0.4) : smoothstep((p - 0.4) / 0.6);
      }
    }
    if (this.hasBlink) {
      const wB = this._wBlink;
      for (let k = 0; k < bc.params.length; k++) {
        const i = bc.params[k];
        const target = active[i] ? 0 : 1;
        wB[i] += (target - wB[i]) * (target > wB[i] ? kIn : kOut);
        mul[i] *= 1 - wB[i] * (1 - factor);
      }
    }

    // ---- saccades (small gaze jumps), only while idle motion is on
    const g = this._gaze;
    if (this.hasSaccade && (this.ex >= 0 || this.ey >= 0)) {
      if (idleOn && t >= g.nextAt) {
        const back = this.rand() < 0.4;
        g.tx = back ? 0 : (this.rand() * 2 - 1) * 0.35;
        g.ty = back ? 0 : (this.rand() * 2 - 1) * 0.2;
        g.nextAt = t + 0.7 + this.rand() * 2.6;
      }
      const kg = 1 - Math.exp(-dt / 0.035);
      g.x += (g.tx - g.x) * kg;
      g.y += (g.ty - g.y) * kg;
      if (this.ex >= 0) {
        g.wx += ((idleOn && !active[this.ex] ? 1 : 0) - g.wx) * (idleOn && !active[this.ex] ? kIn : kOut);
        add[this.ex] += g.wx * g.x;
      }
      if (this.ey >= 0) {
        g.wy += ((idleOn && !active[this.ey] ? 1 : 0) - g.wy) * (idleOn && !active[this.ey] ? kIn : kOut);
        add[this.ey] += g.wy * g.y;
      }
    }
  }
}

/* ===================================================================================================== */
/* PuppetController                                                                                      */
/* ===================================================================================================== */

/**
 * Ties everything together.
 *   user values  (setParam)   what the sliders / API ask for
 *   + idle, blink, saccades   (IdleController, per-param fade while the user steers it)
 *   + follow                  cursor steering of head yaw/pitch and gaze (setFollow)
 *   -> physics inputs
 *   -> physics outputs replace the driven params
 *   -> clamp to every param's [min, max]            -> `values`
 */
export class PuppetController {
  /**
   * @param {PuppetModel} model
   * @param {{seed?:number, idle?:boolean, blink?:boolean, physics?:boolean, follow?:boolean,
   *          holdSeconds?:number}} [opts]
   */
  constructor(model, opts = {}) {
    this.model = model;
    const n = model.params.length;
    this.store = new ParamStore(model); // what the user / API asked for
    this.user = this.store.values;
    this.values = Float64Array.from(model.defaults); // final values, indexed like model.params
    this._pre = new Float64Array(n);
    this.time = 0;
    this.idle = new IdleController(model, { seed: opts.seed ?? 1 });
    this.physics = new PhysicsSim(model.physics, model);
    this.holdSeconds = opts.holdSeconds ?? 0.8;
    this._touch = new Float64Array(n).fill(-1e9);
    this._hold = new Uint8Array(n);
    this._active = new Uint8Array(n);
    this.options = {
      idle: opts.idle ?? this.idle.hasIdle,
      blink: opts.blink ?? (this.idle.blinkCfg.enabled && this.idle.hasBlink),
      physics: opts.physics ?? this.physics.items.length > 0,
      follow: opts.follow ?? true, // follow is only active while setFollow() has a target
    };
    // cursor follow
    const ix = (id) => (model.paramIndex.has(id) ? model.paramIndex.get(id) : -1);
    this._f = {
      on: false, x: 0, y: 0, // target in [-1, 1] (x right, y down)
      sx: 0, sy: 0, // smoothed head
      gx: 0, gy: 0, // smoothed gaze
      w: 0, // overall weight 0..1
      ax: ix("ParamAngleX"), ay: ix("ParamAngleY"), ex: ix("ParamEyeBallX"), ey: ix("ParamEyeBallY"),
      headRange: 0.8,
      // param = gazeYSign * (cursor y, screen-down positive).  Cubism: +EyeBallY looks up (-> -1); some compilers emit
      // +EyeBallY = iris moves down the screen (-> +1), so ask the data instead of assuming
      gazeYSign: model.fieldDirection("ParamEyeBallY", 1) > 0 ? 1 : -1,
    };
    this._followAdd = new Float64Array(n);
    this.step(0); // populate `values` with the rest pose
  }

  // ---------------------------------------------------------------- parameters
  /** Set a parameter. `user:true` (default) marks it as being steered by the user, which pauses idle motion on it. */
  setParam(id, v, { user = true } = {}) {
    const i = this.model.paramIndex.get(id);
    if (i === undefined) return false;
    this.store.set(id, v);
    if (user) this._touch[i] = this.time;
    return true;
  }

  /** Explicit pointer-down / pointer-up on a control: while held, idle motion stays off for that parameter. */
  holdParam(id, on) {
    const i = this.model.paramIndex.get(id);
    if (i === undefined) return;
    this._hold[i] = on ? 1 : 0;
    if (!on) this._touch[i] = this.time;
  }

  /** User value (what was asked for, before idle/physics). */
  getUserParam(id) {
    const i = this.model.paramIndex.get(id);
    return i === undefined ? undefined : this.user[i];
  }

  /** Final value of the last step(). */
  getParam(id) {
    const i = this.model.paramIndex.get(id);
    return i === undefined ? undefined : this.values[i];
  }

  /** Final values as a plain {id: value} object (allocates; use `values` in hot paths). */
  getParams() {
    const o = {};
    const ps = this.model.params;
    for (let i = 0; i < ps.length; i++) o[ps[i].id] = this.values[i];
    return o;
  }

  getUserParams() {
    return this.store.toObject();
  }

  /** User values back to defaults; physics/idle/follow state restarts. */
  reset() {
    this.store.reset();
    this._touch.fill(-1e9);
    this._hold.fill(0);
    this.idle.reset();
    this.physics.reset();
    const f = this._f;
    Object.assign(f, { on: false, x: 0, y: 0, sx: 0, sy: 0, gx: 0, gy: 0, w: 0 });
    this.step(0);
  }

  setOption(name, on) {
    if (!(name in this.options)) throw new Error(`unknown option ${name}`);
    on = !!on;
    if (name === "physics" && on && !this.options.physics) this.physics.reset();
    this.options[name] = on;
  }

  /** Steer head + gaze towards a point; x, y in [-1, 1] (right / down).  `null` releases it. */
  setFollow(x, y) {
    const f = this._f;
    if (x == null || y == null) {
      f.on = false;
      return;
    }
    f.on = true;
    f.x = clamp(x, -1, 1);
    f.y = clamp(y, -1, 1);
  }

  // ---------------------------------------------------------------- stepping
  /** Advance by dtSeconds (clamped to 50 ms) and return the final parameter values (Float64Array, reused). */
  step(dtSeconds) {
    const m = this.model;
    const n = m.params.length;
    let dt = Number.isFinite(dtSeconds) ? dtSeconds : 0;
    dt = dt < 0 ? 0 : dt > 0.05 ? 0.05 : dt;
    this.time += dt;

    // ---- cursor follow (smoothed; head slower than eyes)
    const f = this._f;
    const fOn = this.options.follow && f.on;
    const ft = fOn ? 1 : 0;
    const kh = dt > 0 ? 1 - Math.exp(-dt / 0.22) : 0;
    const ke = dt > 0 ? 1 - Math.exp(-dt / 0.07) : 0;
    f.sx += ((fOn ? f.x : 0) - f.sx) * kh;
    f.sy += ((fOn ? f.y : 0) - f.sy) * kh;
    f.gx += ((fOn ? f.x : 0) - f.gx) * ke;
    f.gy += ((fOn ? f.y : 0) - f.gy) * ke;
    f.w += (ft - f.w) * (dt > 0 ? 1 - Math.exp(-dt / 0.15) : 0);
    const fa = this._followAdd;
    fa.fill(0);
    const followLive = f.w > 0.01 || Math.abs(f.sx) + Math.abs(f.sy) + Math.abs(f.gx) + Math.abs(f.gy) > 0.01;
    if (followLive) {
      if (f.ax >= 0) fa[f.ax] = f.sx * f.headRange * m.maxs[f.ax];
      if (f.ay >= 0) fa[f.ay] = -f.sy * f.headRange * m.maxs[f.ay]; // cursor above -> look up (+AngleY)
      if (f.ex >= 0) fa[f.ex] = f.gx;
      if (f.ey >= 0) fa[f.ey] = f.gy * f.gazeYSign;
    }

    // ---- who is being steered right now?
    const act = this._active;
    for (let i = 0; i < n; i++) act[i] = this._hold[i] || this.time - this._touch[i] < this.holdSeconds ? 1 : 0;
    if (followLive) {
      if (f.ax >= 0) act[f.ax] = 1;
      if (f.ay >= 0) act[f.ay] = 1;
      if (f.ex >= 0) act[f.ex] = 1;
      if (f.ey >= 0) act[f.ey] = 1;
    }

    // ---- idle / blink / saccade
    this.idle.update(dt, act, this.options);
    const add = this.idle.add;
    const mul = this.idle.mul;
    const pre = this._pre;
    const vals = this.values;
    for (let i = 0; i < n; i++) {
      const v = this.user[i] * mul[i] + add[i] + fa[i];
      pre[i] = v < m.mins[i] ? m.mins[i] : v > m.maxs[i] ? m.maxs[i] : v;
      vals[i] = pre[i];
    }

    // ---- physics replaces the driven params
    if (this.options.physics && this.physics.items.length) {
      this.physics.step(dt, vals);
      const items = this.physics.items;
      for (let k = 0; k < items.length; k++) {
        const o = items[k].out;
        vals[o] = vals[o] < m.mins[o] ? m.mins[o] : vals[o] > m.maxs[o] ? m.maxs[o] : vals[o];
      }
    }
    return vals;
  }
}
