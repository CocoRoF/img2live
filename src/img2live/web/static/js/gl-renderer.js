// SPDX-License-Identifier: Apache-2.0
/**
 * WebGL2 renderer for img2live puppets.
 *
 *  - premultiplied-alpha textures (mipmaps, linear filtering, CLAMP_TO_EDGE)
 *  - one dynamic position buffer per mesh, uploaded only when the mesh's parameters changed
 *  - `clip` masks through the stencil buffer (clip mesh drawn with alpha-discard 0.5, then EQUAL test)
 *  - per-mesh visibility / solo / opacity override, wireframe overlay, background modes
 *  - camera: fit, head close-up, wheel zoom, drag pan, pinch, double-click reset
 *  - DPR aware, context loss recovery, PNG snapshot (renders then captures in the same task)
 */

export const BACKGROUNDS = ["checker", "white", "dark", "green"];

const BG_COLORS = {
  white: [1, 1, 1, 1],
  dark: [0.09, 0.1, 0.12, 1],
  green: [0.0, 0.69, 0.25, 1],
};

const VS_MESH = `#version 300 es
in vec2 aPos;
in vec2 aUV;
uniform vec4 uXform; // scale.xy, offset.xy : canvas px -> clip space
out vec2 vUV;
void main() {
  vUV = aUV;
  gl_Position = vec4(aPos * uXform.xy + uXform.zw, 0.0, 1.0);
}`;

const FS_MESH = `#version 300 es
precision highp float;
in vec2 vUV;
uniform sampler2D uTex;
uniform float uOpacity;
uniform float uCutoff;
out vec4 outColor;
void main() {
  vec4 c = texture(uTex, vUV);
  if (c.a < uCutoff) discard;
  outColor = c * uOpacity; // texture is premultiplied
}`;

const VS_WIRE = `#version 300 es
in vec2 aPos;
uniform vec4 uXform;
void main() {
  gl_Position = vec4(aPos * uXform.xy + uXform.zw, 0.0, 1.0);
}`;

const FS_WIRE = `#version 300 es
precision highp float;
uniform vec4 uColor; // premultiplied
out vec4 outColor;
void main() { outColor = uColor; }`;

const VS_BG = `#version 300 es
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

const FS_CHECKER = `#version 300 es
precision highp float;
uniform float uCell;
uniform vec3 uA;
uniform vec3 uB;
out vec4 outColor;
void main() {
  vec2 c = floor(gl_FragCoord.xy / uCell);
  float k = mod(c.x + c.y, 2.0);
  outColor = vec4(mix(uA, uB, k), 1.0);
}`;

export class WebGL2Unavailable extends Error {
  constructor(message = "WebGL2 is not available in this browser") {
    super(message);
    this.name = "WebGL2Unavailable";
  }
}

export function webgl2Supported() {
  try {
    const c = document.createElement("canvas");
    return !!c.getContext("webgl2");
  } catch {
    return false;
  }
}

function hslToRgb(h, s, l) {
  h = (((h % 360) + 360) % 360) / 360;
  const f = (n) => {
    const k = (n + h * 12) % 12;
    return l - s * Math.min(l, 1 - l) * Math.max(-1, Math.min(k - 3, 9 - k, 1));
  };
  return [f(0), f(8), f(4)];
}

export class GLRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {import('./puppet-runtime.js').PuppetModel} model
   * @param {{baseUrl?: string, onEvent?: (type:string, detail?:any)=>void, maxDpr?:number}} [opts]
   */
  constructor(canvas, model, { baseUrl = "", onEvent = null, maxDpr = 3 } = {}) {
    this.canvas = canvas;
    this.model = model;
    this.baseUrl = baseUrl;
    this.onEvent = onEvent;
    this.maxDpr = maxDpr;

    const attrs = {
      alpha: true,
      premultipliedAlpha: true,
      antialias: true,
      stencil: true,
      depth: false,
      preserveDrawingBuffer: true,
      powerPreference: "high-performance",
    };
    const gl = canvas.getContext("webgl2", attrs);
    if (!gl) throw new WebGL2Unavailable();
    this.gl = gl;
    this.lost = false;
    this.disposed = false;

    // per-mesh debug state
    const n = model.meshes.length;
    this.visible = new Uint8Array(n).fill(1);
    this.opacityOverride = new Array(n).fill(null);
    this.dim = new Float32Array(n).fill(1); // multiplies the opacity (studio "focus" mode fades the unselected layers)
    this.solo = -1;
    this.wireframe = false;
    this.background = "checker";

    // camera: centre (puppet px), zoom (CSS px per puppet px)
    this.camera = { cx: model.canvas.w / 2, cy: model.canvas.h / 2, zoom: 0.5 };
    this.cameraMode = "fit"; // 'fit' | 'head' | 'custom'
    this._lastPreset = "fit";
    this.cssWidth = 1;
    this.cssHeight = 1;
    this.dpr = 1;
    this.dirty = true;
    this.stats = { drawCalls: 0, uploads: 0, meshesDrawn: 0, clipped: 0 };
    this._values = model.makeValues();
    this._xf = new Float64Array(4); // canvas px -> clip transform of the current frame
    this._drag = null;
    this._pointers = new Map();
    this._pinch = null;
    this.dragging = false;

    this.g = model.meshes.map((m) => ({
      pos: new Float32Array(m.positions.length),
      bitmap: null,
      error: null,
      tex: null,
      vao: null,
      wireVao: null,
      dirty: true,
    }));
    // wire edges (unique) per mesh, built once on the CPU
    this._edges = model.meshes.map((m) => buildEdges(m));
    this.g.forEach((g, i) => {
      g.wireColor = ((c) => [c[0] * 0.9, c[1] * 0.9, c[2] * 0.9, 0.9])(hslToRgb(i * 47, 0.85, 0.55));
    });

    this._onLost = (e) => {
      e.preventDefault();
      this.lost = true;
      this._emit("contextlost");
    };
    this._onRestored = () => {
      try {
        this._initGL();
        this._uploadAllTextures();
        this.model.invalidate();
        this.lost = false;
        this.dirty = true;
        this._emit("contextrestored");
      } catch (err) {
        this._emit("error", err);
      }
    };
    canvas.addEventListener("webglcontextlost", this._onLost);
    canvas.addEventListener("webglcontextrestored", this._onRestored);

    this._initGL();
  }

  _emit(type, detail) {
    try {
      if (this.onEvent) this.onEvent(type, detail);
    } catch (e) {
      console.error(e);
    }
  }

  // ===================================================================================== GL resources
  _compile(type, src) {
    const gl = this.gl;
    const s = gl.createShader(type);
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(s);
      gl.deleteShader(s);
      throw new Error("shader compile failed: " + log);
    }
    return s;
  }

  _program(vs, fs, attribs) {
    const gl = this.gl;
    const p = gl.createProgram();
    const v = this._compile(gl.VERTEX_SHADER, vs);
    const f = this._compile(gl.FRAGMENT_SHADER, fs);
    gl.attachShader(p, v);
    gl.attachShader(p, f);
    (attribs || []).forEach((a, i) => gl.bindAttribLocation(p, i, a));
    gl.linkProgram(p);
    gl.deleteShader(v);
    gl.deleteShader(f);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error("program link failed: " + gl.getProgramInfoLog(p));
    const u = {};
    const count = gl.getProgramParameter(p, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const info = gl.getActiveUniform(p, i);
      u[info.name] = gl.getUniformLocation(p, info.name);
    }
    return { p, u };
  }

  _initGL() {
    const gl = this.gl;
    this.progMesh = this._program(VS_MESH, FS_MESH, ["aPos", "aUV"]);
    this.progWire = this._program(VS_WIRE, FS_WIRE, ["aPos"]);
    this.progBg = this._program(VS_BG, FS_CHECKER, []);
    this.bgVao = gl.createVertexArray();
    this.anisoExt = gl.getExtension("EXT_texture_filter_anisotropic");
    this.loseExt = gl.getExtension("WEBGL_lose_context"); // getExtension() returns null once the context is lost

    // 16x16 magenta/black checker shown for meshes whose texture failed to load
    const px = new Uint8Array(16 * 16 * 4);
    for (let y = 0; y < 16; y++) {
      for (let x = 0; x < 16; x++) {
        const k = (y * 16 + x) * 4;
        const on = ((x >> 2) + (y >> 2)) & 1;
        px[k] = on ? 255 : 30;
        px[k + 1] = on ? 0 : 0;
        px[k + 2] = on ? 220 : 30;
        px[k + 3] = 255;
      }
    }
    this.errorTex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, this.errorTex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, 16, 16, 0, gl.RGBA, gl.UNSIGNED_BYTE, px);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.NEAREST);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.REPEAT);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.REPEAT);

    this.model.meshes.forEach((m, i) => {
      const g = this.g[i];
      g.tex = null;
      g.posBuf = gl.createBuffer();
      g.uvBuf = gl.createBuffer();
      g.ebo = gl.createBuffer();
      g.wireEbo = gl.createBuffer();

      gl.bindBuffer(gl.ARRAY_BUFFER, g.posBuf);
      gl.bufferData(gl.ARRAY_BUFFER, g.pos, gl.DYNAMIC_DRAW);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.uvBuf);
      gl.bufferData(gl.ARRAY_BUFFER, m.uvs, gl.STATIC_DRAW);

      g.vao = gl.createVertexArray();
      gl.bindVertexArray(g.vao);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.posBuf);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.uvBuf);
      gl.enableVertexAttribArray(1);
      gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.ebo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, m.indices, gl.STATIC_DRAW);

      const edges = this._edges[i];
      g.wireCount = edges.length;
      g.wireVao = gl.createVertexArray();
      gl.bindVertexArray(g.wireVao);
      gl.bindBuffer(gl.ARRAY_BUFFER, g.posBuf);
      gl.enableVertexAttribArray(0);
      gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, g.wireEbo);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, edges, gl.STATIC_DRAW);
      gl.bindVertexArray(null);
      g.dirty = true;
    });
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, null);
  }

  // ===================================================================================== textures
  /**
   * Load every mesh texture (parallel). Failed textures get a visible magenta placeholder and are
   * reported through onEvent('textureerror'); resolves with the list of failures (never rejects).
   */
  async loadTextures(onProgress) {
    const meshes = this.model.meshes;
    let done = 0;
    const failures = [];
    await Promise.all(
      meshes.map(async (m, i) => {
        const g = this.g[i];
        try {
          const base = new URL(this.baseUrl || document.baseURI, document.baseURI);
          const url = new URL(m.texture, base).href;
          g.url = url;
          // a puppet.json is user content: never let it make the viewer fetch from some other origin
          if (new URL(url).origin !== base.origin) throw new Error(`texture URL leaves the puppet's origin: ${url}`);
          g.bitmap = await loadImage(url);
          this._uploadTexture(i);
        } catch (err) {
          g.error = String(err && err.message ? err.message : err);
          g.tex = this.errorTex;
          failures.push({ id: m.id, url: g.url || m.texture, error: g.error });
          console.warn(`img2live: texture for "${m.id}" failed to load: ${g.error}`);
          this._emit("textureerror", { id: m.id, url: g.url || m.texture, error: g.error });
        }
        done++;
        if (onProgress) onProgress(done, meshes.length);
      }),
    );
    this.dirty = true;
    return failures;
  }

  _uploadAllTextures() {
    for (let i = 0; i < this.g.length; i++) {
      const g = this.g[i];
      if (g.bitmap) this._uploadTexture(i);
      else if (g.error) g.tex = this.errorTex;
    }
  }

  _uploadTexture(i) {
    const gl = this.gl;
    const g = this.g[i];
    const src = g.bitmap;
    if (!src) return;
    const tex = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D, tex);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, false);
    gl.pixelStorei(gl.UNPACK_COLORSPACE_CONVERSION_WEBGL, gl.NONE);
    // ImageBitmaps are premultiplied at decode time; HTMLImageElements are premultiplied by the upload
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, !src.__premultiplied);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src);
    gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
    gl.generateMipmap(gl.TEXTURE_2D);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    if (this.anisoExt) {
      const max = gl.getParameter(this.anisoExt.MAX_TEXTURE_MAX_ANISOTROPY_EXT);
      gl.texParameterf(gl.TEXTURE_2D, this.anisoExt.TEXTURE_MAX_ANISOTROPY_EXT, Math.min(4, max));
    }
    g.tex = tex;
    g.error = null;
  }

  /** Texture failures so far: [{id, error}] */
  get textureErrors() {
    return this.g.map((g, i) => (g.error ? { id: this.model.meshes[i].id, error: g.error } : null)).filter(Boolean);
  }

  // ===================================================================================== debug state
  setMeshVisible(i, on) {
    this.visible[i] = on ? 1 : 0;
    this.dirty = true;
  }
  setSolo(i) {
    this.solo = i == null ? -1 : i;
    this.dirty = true;
  }
  setMeshOpacity(i, v) {
    this.opacityOverride[i] = v == null ? null : Math.max(0, Math.min(1, v));
    this.dirty = true;
  }
  /** Multiply the drawn opacity of mesh i by v (0..1); 1 = unchanged.  Keeps opacityBind working. */
  setMeshDim(i, v) {
    this.dim[i] = Math.max(0, Math.min(1, v));
    this.dirty = true;
  }
  setWireframe(on) {
    this.wireframe = !!on;
    this.dirty = true;
  }
  setBackground(mode) {
    if (!BACKGROUNDS.includes(mode)) throw new Error("unknown background " + mode);
    this.background = mode;
    this.dirty = true;
  }
  isShown(i) {
    return this.visible[i] === 1 && (this.solo < 0 || this.solo === i);
  }

  // ===================================================================================== camera
  /** Resize to CSS pixels; keeps a preset framing (fit/head), keeps centre+zoom when the camera is custom. */
  resize(cssW, cssH, dpr = (typeof devicePixelRatio === "number" ? devicePixelRatio : 1)) {
    cssW = Math.max(1, Math.floor(cssW));
    cssH = Math.max(1, Math.floor(cssH));
    dpr = Math.max(1, Math.min(dpr || 1, this.maxDpr));
    const w = Math.round(cssW * dpr);
    const h = Math.round(cssH * dpr);
    if (this.canvas.width !== w || this.canvas.height !== h) {
      this.canvas.width = w;
      this.canvas.height = h;
    }
    const changed = cssW !== this.cssWidth || cssH !== this.cssHeight || dpr !== this.dpr;
    this.cssWidth = cssW;
    this.cssHeight = cssH;
    this.dpr = dpr;
    if (changed) {
      if (this.cameraMode !== "custom") this.setCamera(this.cameraMode);
      this.dirty = true;
    }
  }

  _frame(box, pad) {
    const [x0, y0, x1, y1] = box;
    const bw = Math.max(x1 - x0, 1);
    const bh = Math.max(y1 - y0, 1);
    const zoom = Math.min(this.cssWidth / (bw * (1 + pad)), this.cssHeight / (bh * (1 + pad)));
    this.camera.cx = (x0 + x1) / 2;
    this.camera.cy = (y0 + y1) / 2;
    this.camera.zoom = zoom;
  }

  /** @param {'fit'|'head'} mode */
  setCamera(mode) {
    if (mode === "head") this._frame(this.model.headBounds, 0.04);
    else if (mode === "fit") this._frame(this.model.bounds, 0.1);
    else throw new Error("unknown camera mode " + mode);
    this.cameraMode = mode;
    this._lastPreset = mode;
    this.dirty = true;
    this._emit("camera", { mode });
  }

  resetCamera() {
    this.setCamera(this._lastPreset || "fit");
  }

  zoomAt(cssX, cssY, factor) {
    const c = this.camera;
    const nz = Math.max(0.05, Math.min(30, c.zoom * factor));
    const dx = cssX - this.cssWidth / 2;
    const dy = cssY - this.cssHeight / 2;
    const wx = c.cx + dx / c.zoom;
    const wy = c.cy + dy / c.zoom;
    c.zoom = nz;
    c.cx = wx - dx / nz;
    c.cy = wy - dy / nz;
    this._customCamera();
  }

  panBy(dxCss, dyCss) {
    this.camera.cx -= dxCss / this.camera.zoom;
    this.camera.cy -= dyCss / this.camera.zoom;
    this._customCamera();
  }

  _customCamera() {
    this.cameraMode = "custom";
    this.dirty = true;
    this._emit("camera", { mode: "custom" });
  }

  worldToCss(x, y, out = { x: 0, y: 0 }) {
    const c = this.camera;
    out.x = (x - c.cx) * c.zoom + this.cssWidth / 2;
    out.y = (y - c.cy) * c.zoom + this.cssHeight / 2;
    return out;
  }

  /** Pointer controls: wheel zoom, drag pan, two-finger pinch, double-click reset. */
  attachControls() {
    const cv = this.canvas;
    const rect = () => cv.getBoundingClientRect();
    this._onWheel = (e) => {
      e.preventDefault();
      const r = rect();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      this.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * unit * (e.ctrlKey ? 0.01 : 0.0015)));
    };
    this._onDown = (e) => {
      if (e.pointerType === "mouse" && e.button !== 0 && e.button !== 1) return;
      cv.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (this._pointers.size === 1) {
        this.dragging = true;
        cv.classList.add("is-dragging");
      } else if (this._pointers.size === 2) {
        const [a, b] = [...this._pointers.values()];
        this._pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) };
      }
    };
    this._onMove = (e) => {
      const p = this._pointers.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x;
      const dy = e.clientY - p.y;
      p.x = e.clientX;
      p.y = e.clientY;
      if (this._pointers.size === 1) {
        this.panBy(dx, dy);
      } else if (this._pointers.size === 2 && this._pinch) {
        const [a, b] = [...this._pointers.values()];
        const d = Math.hypot(a.x - b.x, a.y - b.y);
        const r = rect();
        if (this._pinch.d > 0 && d > 0) this.zoomAt((a.x + b.x) / 2 - r.left, (a.y + b.y) / 2 - r.top, d / this._pinch.d);
        this._pinch.d = d;
      }
    };
    this._onUp = (e) => {
      this._pointers.delete(e.pointerId);
      if (this._pointers.size < 2) this._pinch = null;
      if (this._pointers.size === 0) {
        this.dragging = false;
        cv.classList.remove("is-dragging");
      }
    };
    this._onDbl = () => this.resetCamera();
    cv.addEventListener("wheel", this._onWheel, { passive: false });
    cv.addEventListener("pointerdown", this._onDown);
    cv.addEventListener("pointermove", this._onMove);
    cv.addEventListener("pointerup", this._onUp);
    cv.addEventListener("pointercancel", this._onUp);
    cv.addEventListener("dblclick", this._onDbl);
  }

  // ===================================================================================== drawing
  /**
   * Evaluate dirty meshes, upload their positions and draw.  `values` = final parameter values.
   * @param {Float64Array} [values] defaults to the previous call's values
   * @param {{transparent?: boolean}} [opts]
   * @returns {boolean} false when nothing could be drawn (context lost)
   */
  render(values, { transparent = false } = {}) {
    if (this.lost || this.disposed) return false;
    const gl = this.gl;
    if (gl.isContextLost()) return false;
    const model = this.model;
    if (values) this._values = values;
    values = this._values;

    // devicePixelRatio may change (browser zoom, other monitor) without a resize event
    if (typeof devicePixelRatio === "number" && Math.max(1, Math.min(devicePixelRatio, this.maxDpr)) !== this.dpr) this.resize(this.cssWidth, this.cssHeight);

    // ---- evaluate + upload
    const stats = this.stats;
    stats.uploads = 0;
    stats.drawCalls = 0;
    stats.meshesDrawn = 0;
    stats.clipped = 0;
    for (let i = 0; i < this.g.length; i++) {
      const g = this.g[i];
      const changed = model.evaluateMeshIfChanged(i, values, g.pos);
      if (changed || g.dirty) {
        gl.bindBuffer(gl.ARRAY_BUFFER, g.posBuf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, g.pos);
        g.dirty = false;
        stats.uploads++;
      }
    }

    // ---- frame setup
    const W = this.canvas.width;
    const H = this.canvas.height;
    const zd = this.camera.zoom * this.dpr;
    const sx = (2 * zd) / W;
    const sy = (-2 * zd) / H;
    const ox = (-2 * zd * this.camera.cx) / W;
    const oy = (2 * zd * this.camera.cy) / H;
    const xf = this._xf;
    xf[0] = sx;
    xf[1] = sy;
    xf[2] = ox;
    xf[3] = oy;

    gl.viewport(0, 0, W, H);
    gl.disable(gl.SCISSOR_TEST);
    gl.disable(gl.STENCIL_TEST);
    gl.disable(gl.BLEND);
    gl.colorMask(true, true, true, true);
    gl.stencilMask(0xff);
    gl.clearStencil(0);
    if (transparent) {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.STENCIL_BUFFER_BIT);
    } else if (this.background === "checker") {
      gl.clearColor(1, 1, 1, 1);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.STENCIL_BUFFER_BIT);
      gl.useProgram(this.progBg.p);
      gl.uniform1f(this.progBg.u.uCell, 12 * this.dpr);
      gl.uniform3f(this.progBg.u.uA, 0.82, 0.83, 0.85);
      gl.uniform3f(this.progBg.u.uB, 0.93, 0.94, 0.95);
      gl.bindVertexArray(this.bgVao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    } else {
      const c = BG_COLORS[this.background];
      gl.clearColor(c[0], c[1], c[2], c[3]);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.STENCIL_BUFFER_BIT);
    }

    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.ONE, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    const P = this.progMesh;
    gl.useProgram(P.p);
    gl.uniform4f(P.u.uXform, sx, sy, ox, oy);
    gl.uniform1i(P.u.uTex, 0);
    gl.activeTexture(gl.TEXTURE0);

    // ---- meshes in draw order
    for (let i = 0; i < this.g.length; i++) {
      if (!this.isShown(i)) continue;
      const g = this.g[i];
      if (!g.tex) continue; // still loading
      const m = model.meshes[i];
      const ov = this.opacityOverride[i];
      const opacity = (ov !== null ? ov : model.opacityOf(i, values)) * this.dim[i];
      if (opacity <= 0.001) continue;

      let masked = false;
      if (m.clipIndex >= 0) masked = this._beginClip(m.clipIndex);
      if (m.clipIndex >= 0 && !masked) continue; // empty mask: nothing visible

      gl.uniform1f(P.u.uOpacity, opacity);
      gl.uniform1f(P.u.uCutoff, 0);
      gl.bindTexture(gl.TEXTURE_2D, g.tex);
      gl.bindVertexArray(g.vao);
      gl.drawElements(gl.TRIANGLES, m.indices.length, m.indices instanceof Uint16Array ? gl.UNSIGNED_SHORT : gl.UNSIGNED_INT, 0);
      stats.drawCalls++;
      stats.meshesDrawn++;
      if (masked) {
        stats.clipped++;
        gl.disable(gl.SCISSOR_TEST);
        gl.disable(gl.STENCIL_TEST);
      }
    }

    // ---- wireframe overlay
    if (this.wireframe) {
      const Wp = this.progWire;
      gl.useProgram(Wp.p);
      gl.uniform4f(Wp.u.uXform, sx, sy, ox, oy);
      for (let i = 0; i < this.g.length; i++) {
        if (!this.isShown(i)) continue;
        const g = this.g[i];
        const c = g.wireColor;
        gl.uniform4f(Wp.u.uColor, c[0], c[1], c[2], c[3]);
        gl.bindVertexArray(g.wireVao);
        gl.drawElements(gl.LINES, g.wireCount, gl.UNSIGNED_INT, 0);
        stats.drawCalls++;
      }
    }
    gl.bindVertexArray(null);
    this.dirty = false;
    return true;
  }

  /**
   * Write the clip mesh into the stencil buffer (alpha >= 0.5) inside its screen bounding box and leave the
   * stencil test set to EQUAL 1 for the masked mesh.  Returns false when the mask is entirely off-screen.
   */
  _beginClip(ci) {
    const gl = this.gl;
    const cg = this.g[ci];
    if (!cg.tex) return false;
    const W = this.canvas.width;
    const H = this.canvas.height;
    const sx = this._xf[0];
    const sy = this._xf[1];
    const ox = this._xf[2];
    const oy = this._xf[3];
    const pos = cg.pos;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (let k = 0; k < pos.length; k += 2) {
      const cx = (pos[k] * sx + ox + 1) * 0.5 * W;
      const cy = (1 - (pos[k + 1] * sy + oy + 1) * 0.5) * H; // not used for the sign below, bbox only
      if (cx < x0) x0 = cx;
      if (cx > x1) x1 = cx;
      if (cy < y0) y0 = cy;
      if (cy > y1) y1 = cy;
    }
    // gl.scissor wants bottom-up window coordinates
    const sxl = Math.max(0, Math.floor(x0) - 2);
    const sxr = Math.min(W, Math.ceil(x1) + 2);
    const syb = Math.max(0, Math.floor(H - y1) - 2);
    const syt = Math.min(H, Math.ceil(H - y0) + 2);
    if (sxr <= sxl || syt <= syb) return false;

    const P = this.progMesh;
    gl.enable(gl.SCISSOR_TEST);
    gl.scissor(sxl, syb, sxr - sxl, syt - syb);
    gl.enable(gl.STENCIL_TEST);
    gl.stencilMask(0xff);
    gl.clear(gl.STENCIL_BUFFER_BIT);
    gl.colorMask(false, false, false, false);
    gl.stencilFunc(gl.ALWAYS, 1, 0xff);
    gl.stencilOp(gl.KEEP, gl.KEEP, gl.REPLACE);
    gl.uniform1f(P.u.uOpacity, 1);
    gl.uniform1f(P.u.uCutoff, 0.5);
    gl.bindTexture(gl.TEXTURE_2D, cg.tex);
    gl.bindVertexArray(cg.vao);
    const cm = this.model.meshes[ci];
    gl.drawElements(gl.TRIANGLES, cm.indices.length, cm.indices instanceof Uint16Array ? gl.UNSIGNED_SHORT : gl.UNSIGNED_INT, 0);
    this.stats.drawCalls++;
    gl.colorMask(true, true, true, true);
    gl.stencilFunc(gl.EQUAL, 1, 0xff);
    gl.stencilOp(gl.KEEP, gl.KEEP, gl.KEEP);
    gl.stencilMask(0);
    return true;
  }

  // ===================================================================================== capture
  /** Render now and read the framebuffer: {width, height, data: Uint8ClampedArray RGBA, top row first}. */
  readPixels({ transparent = false } = {}) {
    this.render(undefined, { transparent });
    const gl = this.gl;
    const W = this.canvas.width;
    const H = this.canvas.height;
    const raw = new Uint8Array(W * H * 4);
    gl.readPixels(0, 0, W, H, gl.RGBA, gl.UNSIGNED_BYTE, raw);
    const data = new Uint8ClampedArray(W * H * 4);
    for (let y = 0; y < H; y++) data.set(raw.subarray((H - 1 - y) * W * 4, (H - y) * W * 4), y * W * 4);
    this.dirty = true;
    return { width: W, height: H, data };
  }

  /** PNG of the current view (transparent background when the checkerboard is selected, unless told otherwise). */
  snapshotBlob({ transparent } = {}) {
    if (transparent === undefined) transparent = this.background === "checker";
    return new Promise((resolve, reject) => {
      if (!this.render(undefined, { transparent })) {
        reject(new Error("WebGL context is lost"));
        return;
      }
      // toBlob copies the canvas bitmap synchronously, so we may redraw straight away
      this.canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("canvas.toBlob returned null"))), "image/png");
      this.dirty = true;
    });
  }

  /** Read back the GPU copy of mesh i's positions (verifies the upload path). */
  debugReadPositions(i) {
    const gl = this.gl;
    const out = new Float32Array(this.g[i].pos.length);
    gl.bindBuffer(gl.ARRAY_BUFFER, this.g[i].posBuf);
    gl.getBufferSubData(gl.ARRAY_BUFFER, 0, out);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    return out;
  }

  /** Test hook: lose / restore the context through WEBGL_lose_context. */
  debugLoseContext() {
    const ext = this.loseExt;
    if (!ext) return false;
    ext.loseContext();
    return true;
  }
  debugRestoreContext() {
    const ext = this.loseExt;
    if (!ext) return false;
    ext.restoreContext();
    return true;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    const cv = this.canvas;
    cv.removeEventListener("webglcontextlost", this._onLost);
    cv.removeEventListener("webglcontextrestored", this._onRestored);
    if (this._onWheel) {
      cv.removeEventListener("wheel", this._onWheel);
      cv.removeEventListener("pointerdown", this._onDown);
      cv.removeEventListener("pointermove", this._onMove);
      cv.removeEventListener("pointerup", this._onUp);
      cv.removeEventListener("pointercancel", this._onUp);
      cv.removeEventListener("dblclick", this._onDbl);
    }
    for (const g of this.g) {
      if (g.bitmap && g.bitmap.close) g.bitmap.close();
      g.bitmap = null;
    }
    if (this.loseExt && !this.gl.isContextLost()) this.loseExt.loseContext(); // browsers cap the number of live contexts
  }
}

// ========================================================================================= helpers
function buildEdges(m) {
  const seen = new Set();
  const out = [];
  const idx = m.indices;
  const n = m.vertexCount;
  for (let t = 0; t < idx.length; t += 3) {
    for (let e = 0; e < 3; e++) {
      const a = idx[t + e];
      const b = idx[t + ((e + 1) % 3)];
      const lo = a < b ? a : b;
      const hi = a < b ? b : a;
      const key = lo * n + hi;
      if (!seen.has(key)) {
        seen.add(key);
        out.push(lo, hi);
      }
    }
  }
  return Uint32Array.from(out);
}

/** Decode a PNG into something texImage2D accepts; prefers a premultiplied ImageBitmap. */
async function loadImage(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`HTTP ${resp.status} for ${url}`);
  const blob = await resp.blob();
  if (typeof createImageBitmap === "function") {
    try {
      const bmp = await createImageBitmap(blob, { premultiplyAlpha: "premultiply", colorSpaceConversion: "none" });
      bmp.__premultiplied = true;
      return bmp;
    } catch {
      /* fall through to <img> */
    }
  }
  const obj = URL.createObjectURL(blob);
  try {
    const img = new Image();
    img.decoding = "async";
    img.src = obj;
    await img.decode();
    return img;
  } finally {
    URL.revokeObjectURL(obj);
  }
}
