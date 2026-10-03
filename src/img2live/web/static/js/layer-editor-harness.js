// SPDX-License-Identifier: Apache-2.0
// Test harness for the layer editor (layer-editor-test.html).  It builds a FAKE studio api in the page:
//   - synthetic layers (a figure with a wrongly attached blob, a floating island, specks, a hole ...) and a synthetic source image,
//     both drawn on canvases and served to the editor as data: URLs (so nothing needs a server);
//   - api.edit() records every payload on window.__calls, applies the operation to its in-memory layers like the real server would
//     (erase / restore / move / clean / fill_hole), bumps the rev and answers { ok, state };
//   - knobs: window.__fake.hold (keep requests pending until window.__fake.release()), window.__fake.failNext = "message".
// Query: ?tag=body  ?theme=dark|light  ?w=900&h=640 (fixed container size)  ?tool=wand  ?overlay=layer  ?layers=0 (no move targets)
import { mountLayerEditor } from "./layer-editor.js";
import * as ops from "./layer-editor-ops.js";

const N = 1280;
const q = new URLSearchParams(location.search);
if (q.get("theme")) document.documentElement.dataset.theme = q.get("theme");

const app = document.getElementById("app");
if (q.get("w") || q.get("h")) {
  app.style.cssText = `position:fixed; left:0; top:0; width:${q.get("w") || "100%"}${/^\d+$/.test(q.get("w") || "") ? "px" : ""}; height:${q.get("h") || "100%"}${/^\d+$/.test(q.get("h") || "") ? "px" : ""}; border:1px solid var(--line)`;
}

// ------------------------------------------------------------------------------------------ the synthetic scene
export const SCENE = {
  body: { cx: 640, cy: 800, rx: 230, ry: 330, color: [60, 110, 200] },
  belt: { x: 560, y: 700, w: 160, h: 60, color: [80, 130, 215] },        // slightly different blue (tolerance tests)
  blob: { cx: 900, cy: 600, r: 90, color: [60, 200, 110] },               // wrongly attached to the body's shoulder
  island: { cx: 220, cy: 300, r: 55, color: [60, 110, 200] },             // same blue as the body, but disconnected
  hole: { cx: 600, cy: 920, r: 28 },                                      // transparent hole inside the body (filled in the source)
  patch: { x: 700, y: 860, w: 60, h: 50, color: [200, 60, 60] },          // red patch on the layer where the source is blue
  specks: [{ x: 300, y: 1100, w: 2, h: 2 }, { x: 350, y: 1100, w: 5, h: 5 }],   // 4 px and 25 px stray pixels
  head: { cx: 640, cy: 330, r: 140, color: [240, 200, 170] },             // in the source only (belongs to another layer)
  hair: { cx: 640, cy: 250, rx: 170, ry: 110, color: [90, 60, 40] },
};
window.__scene = SCENE;

const mk = () => { const c = document.createElement("canvas"); c.width = c.height = N; return c; };
const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const ell = (x, cx, cy, rx, ry, color) => { x.fillStyle = rgb(color); x.beginPath(); x.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2); x.fill(); };
// no anti-aliasing: hard pixels make the tests exact
function disc(x, cx, cy, r, color) {
  x.fillStyle = rgb(color);
  for (let dy = -r; dy <= r; dy++) { const w = Math.floor(Math.sqrt(r * r - dy * dy)); x.fillRect(cx - w, cy + dy, 2 * w + 1, 1); }
}
function ellHard(x, cx, cy, rx, ry, color) {
  x.fillStyle = rgb(color);
  for (let dy = -ry; dy <= ry; dy++) { const w = Math.floor(rx * Math.sqrt(1 - (dy * dy) / (ry * ry))); x.fillRect(cx - w, cy + dy, 2 * w + 1, 1); }
}

function drawBody(x, withFlaws) {
  const S = SCENE;
  ellHard(x, S.body.cx, S.body.cy, S.body.rx, S.body.ry, S.body.color);
  x.fillStyle = rgb(S.belt.color); x.fillRect(S.belt.x, S.belt.y, S.belt.w, S.belt.h);
  disc(x, S.blob.cx, S.blob.cy, S.blob.r, S.blob.color);
  disc(x, S.island.cx, S.island.cy, S.island.r, S.island.color);
  if (withFlaws) {
    for (let dy = -S.hole.r; dy <= S.hole.r; dy++) { const w = Math.floor(Math.sqrt(S.hole.r * S.hole.r - dy * dy)); x.clearRect(S.hole.cx - w, S.hole.cy + dy, 2 * w + 1, 1); }   // a round hole
    x.fillStyle = rgb(S.patch.color); x.fillRect(S.patch.x, S.patch.y, S.patch.w, S.patch.h);
    x.fillStyle = rgb(S.body.color);
    for (const s of S.specks) x.fillRect(s.x, s.y, s.w, s.h);
  }
}

function makeScene() {
  const S = SCENE;
  const body = mk(), bx = body.getContext("2d");
  drawBody(bx, true);
  const hair = mk(); ellHard(hair.getContext("2d"), S.hair.cx, S.hair.cy, S.hair.rx, S.hair.ry, S.hair.color);
  const arm = mk();                                                      // empty target layer
  const face = mk(), fx = face.getContext("2d");                         // head grid
  disc(fx, 640, 640, 420, S.head.color);
  disc(fx, 500, 560, 40, [30, 30, 60]); disc(fx, 780, 560, 40, [30, 30, 60]);
  // sources
  const source = mk(), sx = source.getContext("2d");
  drawBody(sx, false);                                                   // no holes, no patch colour, no specks
  disc(sx, S.head.cx, S.head.cy, S.head.r, S.head.color);
  ellHard(sx, S.hair.cx, S.hair.cy - 20, S.hair.rx, S.hair.ry, S.hair.color);
  const headSource = mk(), hx = headSource.getContext("2d");
  disc(hx, 640, 640, 420, S.head.color);
  disc(hx, 500, 560, 40, [30, 30, 60]); disc(hx, 780, 560, 40, [30, 30, 60]);
  disc(hx, 640, 840, 60, [200, 80, 90]);                                 // a mouth only the source has
  return { layers: { body, hair, arm_r: arm, face }, sources: { canvas: source, head: headSource } };
}

const scene = makeScene();
export const LAYERS = [
  { tag: "body", label: "몸", grid: "canvas", empty: false },
  { tag: "arm_r", label: "오른팔", grid: "canvas", empty: true },
  { tag: "hair", label: "앞머리", grid: "canvas", empty: false },
  { tag: "face", label: "얼굴", grid: "head", empty: false },
];
window.__layers = LAYERS;

// ------------------------------------------------------------------------------------------ the fake api
const fake = (window.__fake = { rev: 0, hold: false, release: null, failNext: null, latency: 0, badLayer: false, badSource: false });
window.__calls = [];
window.__applied = [];
window.__closed = 0;
window.__imageRequests = [];

const cache = new Map();
const urlOf = (key, canvas) => { const k = `${key}`; if (!cache.has(k)) cache.set(k, canvas.toDataURL("image/png")); return cache.get(k); };
const imgData = (c) => c.getContext("2d").getImageData(0, 0, N, N);

function decodeMask(b64) {
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => { const c = mk(); c.getContext("2d").drawImage(im, 0, 0); const d = imgData(c).data, m = new Uint8Array(N * N); for (let i = 0; i < N * N; i++) m[i] = d[i * 4] > 127 ? 1 : 0; resolve(m); };
    im.onerror = () => reject(new Error("bad mask png"));
    im.src = `data:image/png;base64,${b64}`;
  });
}

function applyOp(tag, payload, mask) {
  const lc = scene.layers[tag], lx = lc.getContext("2d");
  const L = imgData(lc);
  const src = imgData(scene.sources[LAYERS.find((l) => l.tag === tag).grid]);
  const px = L.data;
  if (payload.op === "erase") {
    for (let i = 0; i < N * N; i++) if (mask[i]) { px[i * 4] = px[i * 4 + 1] = px[i * 4 + 2] = px[i * 4 + 3] = 0; }
  } else if (payload.op === "restore") {
    for (let i = 0; i < N * N; i++) if (mask[i]) { for (let k = 0; k < 4; k++) px[i * 4 + k] = src.data[i * 4 + k]; }
  } else if (payload.op === "move") {
    const tc = scene.layers[payload.to], T = imgData(tc);
    for (let i = 0; i < N * N; i++) if (mask[i] && px[i * 4 + 3]) { for (let k = 0; k < 4; k++) { T.data[i * 4 + k] = px[i * 4 + k]; px[i * 4 + k] = 0; } }
    tc.getContext("2d").putImageData(T, 0, 0);
    cache.forEach((_, k) => { if (k.startsWith(`layer:${payload.to}:`)) cache.delete(k); });
    LAYERS.find((l) => l.tag === payload.to).empty = false;
  } else if (payload.op === "clean") {
    const { labels, comps } = ops.labelComponents(ops.alphaPlane(px), N, N, ops.CONTENT_T);
    const kill = new Set(comps.filter((c) => c.area < 64).map((c) => c.id));
    for (let i = 0; i < N * N; i++) if (labels[i] && kill.has(labels[i])) px[i * 4 + 3] = 0;
  } else if (payload.op === "fill_hole") {
    const seen = new Uint8Array(N * N), stack = [];
    const push = (i) => { if (!seen[i] && px[i * 4 + 3] <= ops.CONTENT_T) { seen[i] = 1; stack.push(i); } };
    for (let x = 0; x < N; x++) { push(x); push((N - 1) * N + x); }
    for (let y = 0; y < N; y++) { push(y * N); push(y * N + N - 1); }
    while (stack.length) { const i = stack.pop(), x = i % N, y = (i / N) | 0; if (x > 0) push(i - 1); if (x < N - 1) push(i + 1); if (y > 0) push(i - N); if (y < N - 1) push(i + N); }
    for (let i = 0; i < N * N; i++) {
      if (seen[i] || px[i * 4 + 3] > ops.CONTENT_T || (mask && !mask[i])) continue;
      for (let k = 0; k < 4; k++) px[i * 4 + k] = src.data[i * 4 + k];
    }
  }
  lx.putImageData(L, 0, 0);
  cache.forEach((_, k) => { if (k.startsWith(`layer:${tag}:`)) cache.delete(k); });
  const ent = LAYERS.find((l) => l.tag === tag);
  let any = false; for (let i = 3; i < px.length; i += 4) if (px[i] > ops.CONTENT_T) { any = true; break; }
  ent.empty = !any;
}

const api = {
  jobId: "fake",
  layerImageUrl(tag, v = "current", rev = 0) { window.__imageRequests.push({ kind: "layer", tag, v, rev }); if (fake.badLayer) return "/static/does-not-exist-layer.png"; return urlOf(`layer:${tag}:${rev}`, scene.layers[tag]); },
  layerThumbUrl(tag) { return urlOf(`thumb:${tag}`, scene.layers[tag]); },
  sourceUrl(grid = "canvas", rev = 0) { window.__imageRequests.push({ kind: "source", grid, rev }); if (fake.badSource) return "/static/does-not-exist-source.png"; return urlOf(`source:${grid}`, scene.sources[grid]); },
  async edit(tag, payload) {
    window.__calls.push({ tag, payload: JSON.parse(JSON.stringify(payload)), t: performance.now() });
    if (fake.hold) await new Promise((r) => { fake.release = r; });
    else if (fake.latency) await new Promise((r) => setTimeout(r, fake.latency));
    if (fake.failNext) { const m = fake.failNext; fake.failNext = null; throw new Error(m); }
    const mask = payload.mask ? await decodeMask(payload.mask) : null;
    applyOp(tag, payload, mask);
    fake.rev += 1;
    return { ok: true, state: { rev: fake.rev, layers: LAYERS.map((l) => ({ ...l })) } };
  },
};
window.__api = api;

// ------------------------------------------------------------------------------------------ mount
window.__harness = {
  mount(extra = {}) {
    if (window.__ed) { try { window.__ed.dispose(); } catch (e) { console.error(e); } }
    const tag = extra.tag || q.get("tag") || "body";
    const ent = LAYERS.find((l) => l.tag === tag) || LAYERS[0];
    window.__ed = mountLayerEditor(app, {
      api, tag: ent.tag, label: ent.label, grid: ent.grid,
      layers: q.get("layers") === "0" ? [] : LAYERS,
      initial: { tool: q.get("tool") || undefined, overlay: q.get("overlay") || undefined },
      rev: fake.rev,
      onApplied: (s) => window.__applied.push(s),
      onClose: () => { window.__closed++; },
      ...extra,
    });
    return window.__ed;
  },
  dispose() { if (window.__ed) { window.__ed.dispose(); window.__ed = null; } },
  layerAlpha(tag) { const d = imgData(scene.layers[tag]).data, a = new Uint8Array(N * N); for (let i = 0; i < N * N; i++) a[i] = d[i * 4 + 3]; return a; },
  layerPixel(tag, x, y) { return [...scene.layers[tag].getContext("2d").getImageData(x, y, 1, 1).data]; },
  layerDataUrl: (tag) => scene.layers[tag].toDataURL("image/png"),
  sourceDataUrl: (grid) => scene.sources[grid].toDataURL("image/png"),
  sceneFlaws: () => SCENE,
};

window.__harness.mount();
await window.__ed.whenReady();
document.documentElement.dataset.ready = "1";
