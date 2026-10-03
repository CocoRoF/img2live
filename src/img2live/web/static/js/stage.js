// SPDX-License-Identifier: Apache-2.0
/**
 * The studio "stage": the puppet viewer engine without the viewer's own UI (plan/08-studio.md §5).
 *
 *   const stage = createStage(container, { puppetUrl, onPick(tag|null), onReady(stage), onError(err) });
 *   await stage.ready;                                   // first puppet loaded and drawn
 *   await stage.reload(newUrl, { keepParams: true });    // swap puppets without a flash: new canvas is built off-screen
 *
 * The container is filled by a WebGL canvas (GLRenderer / PuppetModel / PuppetController are reused untouched) and a
 * 2D overlay canvas that draws the selection outline from the mesh boundary edges (it follows the deformation).
 * Layers = puppet meshes grouped by their `tag` (eyelash_l / eyelash_r share "eyelash").
 */
import { PuppetModel, PuppetController } from "./puppet-runtime.js";
import { GLRenderer, WebGL2Unavailable, BACKGROUNDS } from "./gl-renderer.js";
import { el, emitter } from "./studio-util.js";

const HIT_ALPHA = 16; // a texel counts as "ink" above this alpha (same threshold as the server's opaque mask)
const CLIP_ALPHA = 127; // clip masks use alpha >= 0.5
const DIM = 0.28; // opacity factor of the unselected layers in focus mode
const CLICK_PX = 5; // pointer travel that still counts as a click
const OUTLINE = { halo: "rgba(255,255,255,0.92)", line: "#5b4bdb", fill: "rgba(91,75,219,0.16)", hoverFill: "rgba(91,75,219,0.08)" };

const tagOf = (m) => m.tag || m.id;

/** Boundary loops of a mesh: edges used by exactly one triangle, chained into closed polylines (vertex index lists). */
function boundaryLoops(m) {
  const idx = m.indices;
  const n = m.vertexCount;
  const directed = new Map(); // a*n+b -> true
  for (let t = 0; t < idx.length; t += 3) {
    for (let e = 0; e < 3; e++) directed.set(idx[t + e] * n + idx[t + ((e + 1) % 3)], true);
  }
  const next = new Map(); // a -> [b, ...] for boundary half-edges (no opposite half-edge)
  for (const key of directed.keys()) {
    const a = Math.floor(key / n);
    const b = key - a * n;
    if (directed.has(b * n + a)) continue;
    if (!next.has(a)) next.set(a, []);
    next.get(a).push(b);
  }
  const loops = [];
  for (const start of [...next.keys()]) {
    while (next.get(start)?.length) {
      const loop = [start];
      let cur = next.get(start).pop();
      let guard = 0;
      while (cur !== start && guard++ < 100000) {
        loop.push(cur);
        const outs = next.get(cur);
        if (!outs || !outs.length) break;
        cur = outs.pop();
      }
      if (loop.length >= 3) loops.push(Uint32Array.from(loop));
    }
  }
  return loops;
}

export function createStage(container, opts = {}) {
  if (!(container instanceof Element)) throw new TypeError("createStage: container must be a DOM element");
  const { onPick = null, onReady = null, onError = null, initial = {} } = opts;
  const bus = emitter();

  // ---- state that survives a reload (the user's view of the puppet, not part of the puppet itself)
  const view = {
    hidden: new Set(), // tags hidden by the eye toggle (preview only)
    solo: null, // tag or null
    highlight: null,
    hover: null,
    focusDim: !!initial.focus,
    background: BACKGROUNDS.includes(initial.background) ? initial.background : "checker",
    wireframe: !!initial.wireframe,
    options: { idle: initial.idle, blink: initial.blink, physics: initial.physics, follow: initial.follow ?? false }, // undefined = puppet default
    seed: initial.seed ?? 1,
    camera: initial.camera || "fit",
  };

  // ---- DOM
  container.classList.add("stage");
  const overlay = el("canvas", { class: "stage-overlay", "aria-hidden": "true" });
  const overlayCtx = overlay.getContext("2d");
  const note = el("div", { class: "stage-note", role: "status", text: "퍼펫을 불러오는 중…" });
  const banner = el("div", { class: "stage-banner", role: "alert", hidden: true });
  container.append(overlay, note, banner);
  const showBanner = (text, level = "bad") => {
    banner.hidden = !text;
    banner.dataset.level = level;
    banner.textContent = text || "";
  };

  let inst = null; // the live instance {canvas, model, ctrl, renderer, layers, alpha[], loops[], rendered}
  let loadSeq = 0;
  let disposed = false;
  let paused = false;
  let raf = 0;
  let last = performance.now();
  let emitT = 0;
  let overlayDirty = true;
  let camKey = "";
  let hoverReq = null;
  let urlNow = opts.puppetUrl || "";
  let firstReady = false;

  // ===================================================================================== build / swap
  function makeCanvas() {
    return el("canvas", {
      class: "stage-canvas",
      tabindex: "0",
      role: "img",
      "aria-label": "퍼펫 미리보기. 끌어서 이동, 휠로 확대, 클릭하면 레이어 선택, 더블클릭으로 시점 초기화, 스페이스로 대기 동작 켜기·끄기",
    });
  }

  /** Fetch puppet.json, build model/controller/renderer on a detached canvas and load every texture. */
  async function build(url) {
    const abs = new URL(url, document.baseURI);
    const baseUrl = new URL("./", abs).href;
    const resp = await fetch(abs.href);
    if (!resp.ok) throw new Error(`퍼펫을 불러오지 못했습니다 (HTTP ${resp.status})`);
    const model = new PuppetModel(await resp.json());
    const ctrl = new PuppetController(model, { seed: view.seed, ...view.options });
    const canvas = makeCanvas();
    const next = { canvas, model, ctrl, renderer: null, alpha: new Array(model.meshes.length).fill(undefined), loops: new Array(model.meshes.length).fill(undefined), rendered: new Float64Array(model.params.length).fill(NaN) };
    next.renderer = new GLRenderer(canvas, model, {
      baseUrl,
      onEvent: (type, detail) => {
        if (next !== inst) return;
        if (type === "contextlost") { showBanner("그래픽 컨텍스트를 잃었습니다. 브라우저가 복구하기를 기다리는 중…", "warn"); bus.emit("contextlost"); }
        else if (type === "contextrestored") { showBanner(""); bus.emit("contextrestored"); }
        else if (type === "textureerror") refreshTextureBanner();
        else if (type === "error") showBanner(`렌더러 오류: ${detail && detail.message ? detail.message : detail}`);
      },
    });
    next.renderer.attachControls();
    await next.renderer.loadTextures();
    // group meshes into layers by tag, back to front
    const byTag = new Map();
    model.meshes.forEach((m, k) => {
      const t = tagOf(m);
      if (!byTag.has(t)) byTag.set(t, { tag: t, meshes: [], index: [], order: m.order });
      const L = byTag.get(t);
      L.meshes.push(m.id);
      L.index.push(k);
    });
    next.layers = [...byTag.values()];
    return next;
  }

  function destroyInst(i) {
    if (!i) return;
    try { i.renderer.dispose(); } catch (e) { console.warn(e); }
    i.canvas.remove();
  }

  function refreshTextureBanner() {
    if (!inst) return;
    const errs = inst.renderer.textureErrors;
    showBanner(errs.length ? `텍스처 ${errs.length}개를 불러오지 못했습니다 (${errs.map((e) => e.id).join(", ")}). 해당 레이어는 마젠타 격자로 표시됩니다.` : "");
  }

  function applyView(i) {
    const r = i.renderer;
    r.setBackground(view.background);
    r.setWireframe(view.wireframe);
    syncVisibility(i);
    syncDim(i);
  }

  function syncVisibility(i = inst) {
    if (!i) return;
    i.model.meshes.forEach((m, k) => {
      const t = tagOf(m);
      i.renderer.setMeshVisible(k, view.solo != null ? t === view.solo : !view.hidden.has(t));
    });
  }

  function syncDim(i = inst) {
    if (!i) return;
    i.model.meshes.forEach((m, k) => i.renderer.setMeshDim(k, view.focusDim && view.highlight && tagOf(m) !== view.highlight ? DIM : 1));
  }

  function resizeTo(r) {
    r.resize(container.clientWidth || 1, container.clientHeight || 1);
  }

  /** Make `next` the live instance: copy the user's state across, draw once, swap the canvas in, free the old one. */
  function activate(next, prev, keepParams) {
    const r = next.renderer;
    resizeTo(r);
    applyView(next);
    if (prev && keepParams) {
      for (const p of prev.model.params) {
        const v = prev.ctrl.getUserParam(p.id);
        if (v !== undefined) next.ctrl.setParam(p.id, v, { user: false });
      }
    }
    if (prev) {
      const pr = prev.renderer;
      if (pr.cameraMode === "custom") {
        r.camera.cx = pr.camera.cx; r.camera.cy = pr.camera.cy; r.camera.zoom = pr.camera.zoom;
        r.cameraMode = "custom";
      } else r.setCamera(pr.cameraMode);
    } else r.setCamera(view.camera === "head" ? "head" : "fit");
    next.ctrl.step(0);
    r.render(next.ctrl.values);
    if (prev) container.replaceChild(next.canvas, prev.canvas);
    else container.insertBefore(next.canvas, overlay);
    inst = next;
    if (prev) destroyInst(prev);
    camKey = "";
    overlayDirty = true;
    note.hidden = true;
    refreshTextureBanner();
    resizeTo(r);
  }

  async function load(url, { keepParams = true, first = false } = {}) {
    const seq = ++loadSeq;
    bus.emit("busy", true);
    let next;
    try {
      next = await build(url);
    } catch (err) {
      if (seq === loadSeq) {
        bus.emit("busy", false);
        const msg = err instanceof WebGL2Unavailable
          ? "이 브라우저는 WebGL2 를 지원하지 않아(또는 꺼져 있어) 퍼펫을 그릴 수 없습니다. 하드웨어 가속이 켜진 최신 Chrome·Edge·Firefox·Safari 를 사용해 주세요."
          : String(err && err.message ? err.message : err);
        if (first || !inst) { note.hidden = true; showBanner(msg); } else bus.emit("warn", msg);
        bus.emit("error", err);
        if (onError) onError(err);
      }
      throw err;
    }
    if (seq !== loadSeq) { destroyInst(next); return; } // a newer reload superseded this one
    const prev = inst;
    activate(next, prev, keepParams);
    urlNow = url;
    bus.emit("busy", false);
    bus.emit(first ? "ready" : "reload", api);
    if (first) { firstReady = true; if (onReady) onReady(api); }
    if (!raf && !paused) { last = performance.now(); raf = requestAnimationFrame(frame); }
  }

  // ===================================================================================== hit testing
  /** Alpha plane of mesh k's texture (Uint8Array w*h), built lazily from the decoded bitmap; null = unknown (treat as opaque). */
  function alphaPlane(i, k) {
    let a = i.alpha[k];
    if (a !== undefined) return a;
    a = null;
    const bmp = i.renderer.g[k].bitmap;
    if (bmp && bmp.width && bmp.height) {
      try {
        const w = bmp.width, h = bmp.height;
        const cv = typeof OffscreenCanvas === "function" ? new OffscreenCanvas(w, h) : Object.assign(document.createElement("canvas"), { width: w, height: h });
        const ctx = cv.getContext("2d", { willReadFrequently: true });
        ctx.drawImage(bmp, 0, 0);
        const px = ctx.getImageData(0, 0, w, h).data;
        const data = new Uint8Array(w * h);
        for (let p = 0; p < data.length; p++) data[p] = px[p * 4 + 3];
        a = { w, h, data };
      } catch (e) { console.warn("stage: could not read texture alpha", e); }
    }
    i.alpha[k] = a;
    return a;
  }

  /** Does the world point (wx, wy) land on an inked texel of mesh k (current deformation, opacity and clip considered)? */
  function hitMesh(i, k, wx, wy, thr = HIT_ALPHA) {
    const m = i.model.meshes[k];
    if (i.model.opacityOf(k, i.ctrl.values) * i.renderer.dim[k] <= 0.001) return false; // not drawn at the moment
    const pos = i.renderer.g[k].pos;
    const idx = m.indices;
    const uvs = m.uvs;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let p = 0; p < pos.length; p += 2) {
      const x = pos[p], y = pos[p + 1];
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
    if (wx < x0 || wx > x1 || wy < y0 || wy > y1) return false;
    const plane = alphaPlane(i, k);
    for (let t = 0; t < idx.length; t += 3) {
      const a = idx[t] * 2, b = idx[t + 1] * 2, c = idx[t + 2] * 2;
      const ax = pos[a], ay = pos[a + 1], bx = pos[b], by = pos[b + 1], cx = pos[c], cy = pos[c + 1];
      const d = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy);
      if (d === 0) continue;
      const l0 = ((by - cy) * (wx - cx) + (cx - bx) * (wy - cy)) / d;
      const l1 = ((cy - ay) * (wx - cx) + (ax - cx) * (wy - cy)) / d;
      const l2 = 1 - l0 - l1;
      if (l0 < -1e-6 || l1 < -1e-6 || l2 < -1e-6) continue;
      if (plane) {
        const u = l0 * uvs[a] + l1 * uvs[b] + l2 * uvs[c];
        const v = l0 * uvs[a + 1] + l1 * uvs[b + 1] + l2 * uvs[c + 1];
        const px = Math.min(plane.w - 1, Math.max(0, Math.floor(u * plane.w)));
        const py = Math.min(plane.h - 1, Math.max(0, Math.floor(v * plane.h)));
        if (plane.data[py * plane.w + px] <= thr) continue;
      }
      if (m.clipIndex >= 0 && !hitMesh(i, m.clipIndex, wx, wy, CLIP_ALPHA)) continue; // masked by the clip mesh (e.g. iris by eye white)
      return true;
    }
    return false;
  }

  function pickIndexAt(i, cssX, cssY) {
    const r = i.renderer;
    const wx = (cssX - r.cssWidth / 2) / r.camera.zoom + r.camera.cx;
    const wy = (cssY - r.cssHeight / 2) / r.camera.zoom + r.camera.cy;
    for (let k = i.model.meshes.length - 1; k >= 0; k--) {
      if (!r.isShown(k)) continue;
      if (hitMesh(i, k, wx, wy)) return k;
    }
    return -1;
  }

  /** Topmost layer tag under a point given in CSS px relative to the stage canvas, or null.  `tolerance` (CSS px) retries on a small ring. */
  function pickAt(cssX, cssY, { tolerance = 0 } = {}) {
    const i = inst;
    if (!i) return null;
    let k = pickIndexAt(i, cssX, cssY);
    for (let ring = 2; k < 0 && tolerance > 0 && ring <= tolerance + 1e-6; ring += 2) {
      for (let s = 0; s < 8 && k < 0; s++) {
        const a = (s * Math.PI) / 4;
        k = pickIndexAt(i, cssX + Math.cos(a) * ring, cssY + Math.sin(a) * ring);
      }
    }
    return k < 0 ? null : tagOf(i.model.meshes[k]);
  }

  // ===================================================================================== overlay (outline)
  function drawOverlay() {
    overlayDirty = false;
    const i = inst;
    if (!i) return;
    const r = i.renderer;
    const w = Math.round(r.cssWidth * r.dpr), h = Math.round(r.cssHeight * r.dpr);
    if (overlay.width !== w || overlay.height !== h) { overlay.width = w; overlay.height = h; }
    const ctx = overlayCtx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, overlay.width, overlay.height);
    if (!view.highlight && !view.hover) return;
    ctx.setTransform(r.dpr, 0, 0, r.dpr, 0, 0);
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    if (view.hover && view.hover !== view.highlight) outlineTag(i, view.hover, true);
    if (view.highlight) outlineTag(i, view.highlight, false);
  }

  function outlineTag(i, tag, light) {
    const L = i.layers.find((x) => x.tag === tag);
    if (!L) return;
    const r = i.renderer, cam = r.camera, ctx = overlayCtx;
    const hw = r.cssWidth / 2, hh = r.cssHeight / 2, z = cam.zoom;
    ctx.beginPath();
    for (const k of L.index) {
      if (!r.isShown(k) || i.model.opacityOf(k, i.ctrl.values) <= 0.001) continue;
      const loops = (i.loops[k] ||= boundaryLoops(i.model.meshes[k]));
      const pos = r.g[k].pos;
      for (const loop of loops) {
        for (let p = 0; p < loop.length; p++) {
          const v = loop[p] * 2;
          const x = (pos[v] - cam.cx) * z + hw, y = (pos[v + 1] - cam.cy) * z + hh;
          if (p === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.closePath();
      }
    }
    ctx.fillStyle = light ? OUTLINE.hoverFill : OUTLINE.fill;
    ctx.fill("evenodd");
    if (!light) { ctx.strokeStyle = OUTLINE.halo; ctx.lineWidth = 4.5; ctx.stroke(); }
    ctx.strokeStyle = OUTLINE.line;
    ctx.lineWidth = light ? 1.5 : 2;
    ctx.globalAlpha = light ? 0.75 : 1;
    ctx.stroke();
    ctx.globalAlpha = 1;
  }

  // ===================================================================================== frame loop
  function frame(now) {
    if (disposed || paused) { raf = 0; return; }
    raf = requestAnimationFrame(frame);
    const i = inst;
    if (!i) return;
    const dt = (now - last) / 1000;
    last = now;
    if (!container.clientWidth || !container.clientHeight) return; // hidden (e.g. the layer editor is showing)
    const r = i.renderer;
    const vals = i.ctrl.step(dt);
    let changed = r.dirty;
    for (let n = 0; n < vals.length; n++) {
      if (vals[n] !== i.rendered[n]) { i.rendered[n] = vals[n]; changed = true; }
    }
    if (changed) r.render(vals);

    if (hoverReq) { // one hit test per frame at most
      const q = hoverReq;
      hoverReq = null;
      const t = q.leave ? null : pickAt(q.x, q.y, { tolerance: 3 });
      if (t !== view.hover) {
        view.hover = t;
        overlayDirty = true;
        i.canvas.classList.toggle("has-hover", !!t);
        bus.emit("hover", t);
      }
    }
    const cam = r.camera;
    const key = `${cam.cx}|${cam.cy}|${cam.zoom}|${r.cssWidth}|${r.cssHeight}|${r.dpr}`;
    if (overlayDirty || ((view.highlight || view.hover) && (changed || key !== camKey))) {
      camKey = key;
      drawOverlay();
    }
    if (key !== camKey) camKey = key;
    if (now - emitT > 33) { emitT = now; bus.emit("frame", vals); }
  }

  const ro = new ResizeObserver(() => {
    if (!inst || !container.clientWidth || !container.clientHeight) return;
    resizeTo(inst.renderer);
    overlayDirty = true;
  });
  ro.observe(container);

  // ===================================================================================== pointer input
  // GLRenderer.attachControls handles pan / zoom / pinch on the canvas itself; we add click-to-pick, hover and follow.
  const pointers = new Set();
  let down = null;
  const onDown = (e) => {
    if (!inst || e.target !== inst.canvas) return;
    pointers.add(e.pointerId);
    if (e.pointerType === "mouse" && e.button !== 0) { down = null; return; }
    down = { id: e.pointerId, x: e.clientX, y: e.clientY, t: performance.now(), multi: pointers.size > 1, moved: 0 };
    inst.ctrl.setFollow(null);
  };
  const onMove = (e) => {
    const i = inst;
    if (!i || e.target !== i.canvas) return;
    if (down && down.id === e.pointerId) down.moved = Math.max(down.moved, Math.hypot(e.clientX - down.x, e.clientY - down.y));
    if (down && pointers.size > 1) down.multi = true;
    if (e.pointerType === "touch" || i.renderer.dragging) return;
    const rect = i.canvas.getBoundingClientRect();
    hoverReq = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    if (i.ctrl.options.follow) { // mouse follow: steer head and gaze towards the cursor
      const hb = i.model.headBounds;
      const c = i.renderer.worldToCss((hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2, { x: 0, y: 0 });
      i.ctrl.setFollow((hoverReq.x - c.x) / (rect.width * 0.4), (hoverReq.y - c.y) / (rect.height * 0.4));
    }
  };
  const onUp = (e) => {
    pointers.delete(e.pointerId);
    const d = down;
    if (!d || d.id !== e.pointerId) return;
    down = null;
    if (!inst || d.multi || d.moved > CLICK_PX || performance.now() - d.t > 900) return;
    const rect = inst.canvas.getBoundingClientRect();
    const tag = pickAt(e.clientX - rect.left, e.clientY - rect.top, { tolerance: 4 });
    bus.emit("pick", tag);
    if (onPick) onPick(tag);
  };
  const onCancel = (e) => { pointers.delete(e.pointerId); if (down && down.id === e.pointerId) down = null; };
  const onLeave = () => { hoverReq = { leave: true }; inst?.ctrl.setFollow(null); };
  const onKey = (e) => {
    if (!inst || e.target !== inst.canvas || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.code === "Space" && !e.repeat) {
      if (!canOption("idle")) return;
      e.preventDefault();
      setOption("idle", !inst.ctrl.options.idle);
    } else if (e.code === "Escape") {
      bus.emit("pick", null);
      if (onPick) onPick(null);
    }
  };
  container.addEventListener("pointerdown", onDown);
  container.addEventListener("pointermove", onMove);
  container.addEventListener("pointerup", onUp);
  container.addEventListener("pointercancel", onCancel);
  container.addEventListener("pointerleave", onLeave);
  container.addEventListener("keydown", onKey);

  // ===================================================================================== options
  const OPTIONS = ["idle", "blink", "physics", "follow", "wireframe", "focus"];
  function canOption(name) {
    const i = inst;
    if (!i) return false;
    if (name === "idle") return i.ctrl.idle.hasIdle || i.ctrl.idle.hasSaccade;
    if (name === "blink") return i.ctrl.idle.hasBlink;
    if (name === "physics") return i.ctrl.physics.items.length > 0;
    return OPTIONS.includes(name);
  }
  function getOption(name) {
    if (name === "wireframe") return view.wireframe;
    if (name === "focus") return view.focusDim;
    return inst ? !!inst.ctrl.options[name] : !!view.options[name];
  }
  function setOption(name, on) {
    if (!OPTIONS.includes(name)) throw new Error(`unknown option ${name}`);
    on = !!on;
    if (name === "wireframe") { view.wireframe = on; inst?.renderer.setWireframe(on); }
    else if (name === "focus") { view.focusDim = on; syncDim(); }
    else {
      view.options[name] = on;
      if (inst) {
        inst.ctrl.setOption(name, on);
        if (name === "follow" && !on) inst.ctrl.setFollow(null);
      }
    }
    bus.emit("option", name, on);
  }

  // ===================================================================================== public API
  function cameraInfo() {
    const r = inst && inst.renderer;
    return r ? { mode: r.cameraMode, zoom: r.camera.zoom, cx: r.camera.cx, cy: r.camera.cy } : { mode: "fit", zoom: 1, cx: 0, cy: 0 };
  }

  const params = {
    /** [{id, name, min, max, default, driven, value (user), final (after idle/physics)}] */
    list: () => (inst ? inst.model.params.map((p) => ({ id: p.id, name: p.name, min: p.min, max: p.max, default: p.default, driven: p.driven, value: inst.ctrl.getUserParam(p.id), final: inst.ctrl.getParam(p.id) })) : []),
    get: (id) => inst?.ctrl.getUserParam(id),
    getFinal: (id) => inst?.ctrl.getParam(id),
    /** Set as a user would (pauses idle motion on that parameter for a moment). */
    set: (id, v, o) => !!inst && inst.ctrl.setParam(id, v, o),
    /** pointer down / up on a slider: while held, idle motion stays off for that parameter. */
    hold: (id, on) => inst?.ctrl.holdParam(id, on),
    reset() { if (inst) { inst.ctrl.reset(); inst.ctrl.setFollow(null); bus.emit("params-reset"); } },
    values: () => (inst ? inst.ctrl.getParams() : {}),
  };

  const api = {
    /** Resolves when the first puppet is drawn. */
    ready: null,
    on: bus.on,
    reload: (url, o = {}) => load(url, { keepParams: o.keepParams !== false }),
    get url() { return urlNow; },
    get loaded() { return firstReady; },
    /** Layers (meshes grouped by tag), back to front: [{tag, meshes:[meshId], order, visible}] */
    get layers() { return inst ? inst.layers.map((L) => ({ tag: L.tag, meshes: [...L.meshes], order: L.order, visible: view.solo != null ? L.tag === view.solo : !view.hidden.has(L.tag) })) : []; },
    hasLayer: (tag) => !!inst && inst.layers.some((L) => L.tag === tag),
    setVisible(tag, on) {
      if (on) view.hidden.delete(tag); else view.hidden.add(tag);
      syncVisibility();
      bus.emit("visibility", tag, !!on);
    },
    isVisible: (tag) => (view.solo != null ? tag === view.solo : !view.hidden.has(tag)),
    hiddenTags: () => [...view.hidden],
    showAll() { view.hidden.clear(); view.solo = null; syncVisibility(); bus.emit("visibility", null, true); },
    hideAll() { view.solo = null; for (const L of inst ? inst.layers : []) view.hidden.add(L.tag); syncVisibility(); bus.emit("visibility", null, false); },
    setSolo(tag) { view.solo = tag || null; syncVisibility(); bus.emit("solo", view.solo); },
    get solo() { return view.solo; },
    /** Outline the layer (and, in focus mode, fade the others).  null clears. */
    highlight(tag) { view.highlight = tag || null; syncDim(); overlayDirty = true; },
    get highlighted() { return view.highlight; },
    get hovered() { return view.hover; },
    pickAt,
    params,
    option: (name, on) => (on === undefined ? getOption(name) : setOption(name, on)),
    canOption,
    setBackground(mode) {
      if (!BACKGROUNDS.includes(mode)) throw new Error("unknown background " + mode);
      view.background = mode;
      inst?.renderer.setBackground(mode);
      bus.emit("background", mode);
    },
    get background() { return view.background; },
    backgrounds: BACKGROUNDS,
    setCamera(mode) { if (inst) { inst.renderer.setCamera(mode); bus.emit("camera", cameraInfo()); } },
    resetCamera() { if (inst) { inst.renderer.resetCamera(); bus.emit("camera", cameraInfo()); } },
    get camera() { return cameraInfo(); },
    /** PNG of the current view (transparent on the checkerboard). */
    snapshot: () => (inst ? inst.renderer.snapshotBlob() : Promise.reject(new Error("퍼펫이 아직 준비되지 않았습니다"))),
    pause() { paused = true; if (raf) { cancelAnimationFrame(raf); raf = 0; } },
    resume() {
      if (!paused && raf) return;
      paused = false;
      last = performance.now();
      if (inst && !raf) raf = requestAnimationFrame(frame);
      if (inst) { inst.renderer.dirty = true; overlayDirty = true; resizeTo(inst.renderer); }
    },
    get paused() { return paused; },
    get meta() { return inst ? inst.model.meta : {}; },
    get warnings() { return inst ? inst.model.warnings : []; },
    get stats() { return inst ? { meshes: inst.model.meshes.length, vertices: inst.model.vertexCount, triangles: inst.model.triangleCount, ...inst.renderer.stats } : null; },
    // ---- extras for tests / tools
    get model() { return inst?.model; },
    get controller() { return inst?.ctrl; },
    get renderer() { return inst?.renderer; },
    get canvas() { return inst?.canvas; },
    dispose() {
      if (disposed) return;
      disposed = true;
      loadSeq++;
      if (raf) cancelAnimationFrame(raf);
      ro.disconnect();
      for (const [t, fn] of [["pointerdown", onDown], ["pointermove", onMove], ["pointerup", onUp], ["pointercancel", onCancel], ["pointerleave", onLeave], ["keydown", onKey]]) container.removeEventListener(t, fn);
      destroyInst(inst);
      inst = null;
      overlay.remove(); note.remove(); banner.remove();
      bus.clear();
    },
  };

  api.ready = opts.puppetUrl
    ? load(opts.puppetUrl, { keepParams: false, first: true }).then(() => api)
    : Promise.resolve(api);
  api.ready.catch(() => {}); // errors are reported through onError / the banner; never an unhandled rejection
  return api;
}
