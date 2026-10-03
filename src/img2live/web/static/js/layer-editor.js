// SPDX-License-Identifier: Apache-2.0
/**
 * img2live layer editor: a canvas editor for ONE layer of a layered 2D puppet (plan/08-studio.md).
 *
 *   import { mountLayerEditor } from "./layer-editor.js";
 *   const ed = mountLayerEditor(container, { api, tag, label, grid, layers, onApplied(state), onClose() });
 *   ed.setTag(tag, { label, grid });   // Promise<boolean>; asks first when a selection would be lost
 *   ed.dispose();
 *
 * The layer is an RGBA image in the 1280x1280 "edit grid" (api.layerImageUrl), the source image rendered in the same grid is
 * api.sourceUrl.  The user builds a SELECTION (brush, wand, lasso, rectangle, connected island, grow/shrink/feather, ...) and
 * sends an operation with a grid-sized mask to the server through `api.edit(tag, payload)`; the server answers { ok, state }.
 * The editor never calls the server itself - only `api` (so tests can pass a fake) - and only loads the two images.
 *
 * Test hooks (always available): getMask(), getState(), getViewCanvas(), getLayerCanvas(), getSourceCanvas(), flush(),
 * whenReady(), gridToClient(x, y), clientToGrid(x, y).
 */
import { maskToBase64 } from "./studio-api.js";
import * as ops from "./layer-editor-ops.js";
import { icon } from "./layer-editor-icons.js";

const G = ops.GRID;
const MIN_ZOOM = 0.05, MAX_ZOOM = 32;
const VEC_ZOOM = 6;   // from this zoom on the selection outline is drawn as thin vector lines instead of the masked ants (a grid pixel is >= 6 screen px)
const HIST_MAX = 60, HIST_BYTES = 192 * 1024 * 1024;
const TOOLS = [
  { id: "brush", label: "브러시", key: "B", ico: "brush", tip: "선택 영역에 칠하기" },
  { id: "eraser", label: "지우개", key: "E", ico: "eraser", tip: "선택 영역에서 지우기 (레이어 픽셀은 그대로)" },
  { id: "wand", label: "마술봉", key: "W", ico: "wand", tip: "비슷한 색·밝기·투명도로 영역 선택" },
  { id: "lasso", label: "올가미", key: "L", ico: "lasso", tip: "자유롭게 그려서 선택" },
  { id: "rect", label: "사각형 선택", key: "M", ico: "rect", tip: "드래그해서 사각형 선택" },
  { id: "island", label: "연결 성분", key: "C", ico: "island", tip: "클릭한 덩어리(섬) 전체 선택" },
  { id: "hand", label: "손", key: "H", ico: "hand", tip: "화면 이동 (Space 누르고 드래그도 가능)" },
  { id: "zoom", label: "확대", key: "Z", ico: "zoom", tip: "클릭해서 확대, Alt+클릭은 축소, 드래그는 영역 확대" },
];
const MODES = [
  { v: "replace", l: "새로", t: "새 선택으로 바꾸기" },
  { v: "add", l: "추가", t: "선택에 더하기 (Shift)" },
  { v: "subtract", l: "빼기", t: "선택에서 빼기 (Alt)" },
  { v: "intersect", l: "교집합", t: "겹친 부분만 남기기 (Shift+Alt)" },
];
const OVERLAYS = [
  { v: "layer", l: "레이어", k: "1", ico: "layerOnly", t: "레이어만 보기" },
  { v: "source", l: "원본", k: "2", ico: "source", t: "원본 이미지만 보기" },
  { v: "blend", l: "겹쳐 보기", k: "3", ico: "blend", t: "레이어 아래에 흐린 원본을 겹쳐 보기" },
  { v: "diff", l: "차이", k: "4", ico: "diff", t: "원본과 다른 부분 표시" },
];
const OP_LABEL = { erase: "지우는 중…", restore: "원본으로 채우는 중…", move: "옮기는 중…", clean: "자동 정리 중…", fill_hole: "구멍을 메우는 중…" };
const OP_DONE = { erase: "지웠습니다", restore: "원본으로 채웠습니다", move: "옮겼습니다", clean: "자동 정리했습니다", fill_hole: "구멍을 메웠습니다" };

const clamp = (v, a, b) => (v < a ? a : v > b ? b : v);
let uidCounter = 0;

// ------------------------------------------------------------------------------------------ DOM helpers
function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const c of kids) if (c !== undefined && c !== null && c !== false) n.append(c);
  return n;
}

function ensureStyles() {
  let link = document.querySelector("link[data-le-css]");
  if (!link) {
    link = el("link", { rel: "stylesheet", href: new URL("../css/layer-editor.css", import.meta.url).href, "data-le-css": "" });
    document.head.append(link);
  }
  if (link.sheet) return Promise.resolve();
  return new Promise((resolve) => {
    link.addEventListener("load", resolve, { once: true });
    link.addEventListener("error", resolve, { once: true });
    setTimeout(resolve, 3500);
  });
}

function mkCanvas(w = G, h = G) {
  const c = document.createElement("canvas");
  c.width = w; c.height = h;
  return c;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const im = new Image();
    im.onload = () => resolve(im);
    im.onerror = () => reject(new Error("이미지를 불러오지 못했습니다"));
    im.src = url;
  });
}

function btn({ text, title, ico, cls = "", data = {}, label, onClick, pressed }) {
  const b = el("button", { type: "button", class: `le-btn ${cls}`.trim(), title, "aria-label": label || text || title });
  if (pressed !== undefined) b.setAttribute("aria-pressed", String(!!pressed));
  for (const [k, v] of Object.entries(data)) b.dataset[k] = v;
  if (ico) b.insertAdjacentHTML("beforeend", icon(ico, 18));
  if (text) b.append(el("span", { class: "le-btn-t", text }));
  if (onClick) b.addEventListener("click", onClick);
  return b;
}

/** label + range + number input kept in sync. */
function mkSlider({ label, min, max, step = 1, value, unit = "", title, onInput, cls = "" }) {
  const range = el("input", { type: "range", min, max, step, value, "aria-label": label });
  const num = el("input", { type: "number", class: "le-num", min, max, step, value, "aria-label": `${label} 값`, inputmode: "decimal" });
  const wrap = el("div", { class: `le-field ${cls}`.trim(), role: "group", "aria-label": label, title }, el("span", { class: "le-field-l", text: label }), range, num);
  if (unit) wrap.append(el("span", { class: "le-unit", text: unit }));
  const norm = (v) => clamp(Math.round(Number(v) / step) * step, Number(min), Number(max));
  range.addEventListener("input", () => { num.value = range.value; onInput && onInput(Number(range.value)); });
  num.addEventListener("input", () => { if (num.value === "" || Number.isNaN(Number(num.value))) return; const v = norm(num.value); range.value = v; onInput && onInput(v); });
  num.addEventListener("change", () => { const v = norm(num.value === "" ? value : num.value); num.value = v; range.value = v; onInput && onInput(v); });
  return {
    el: wrap, range, num,
    set(v) { v = norm(v); range.value = v; num.value = v; },
    get: () => Number(range.value),
  };
}

function mkSeg(items, onPick, aria) {
  const wrap = el("div", { class: "le-seg", role: "group", "aria-label": aria });
  const map = new Map();
  for (const it of items) {
    const b = el("button", { type: "button", class: "le-seg-b", title: it.t, "aria-pressed": "false", "data-v": it.v }, it.l);
    b.addEventListener("click", () => onPick(it.v));
    wrap.append(b);
    map.set(it.v, b);
  }
  return { el: wrap, set(v) { for (const [k, b] of map) b.setAttribute("aria-pressed", String(k === v)); } };
}

function mkSelect(label, options, onPick, cls = "") {
  const sel = el("select", { "aria-label": label, class: "le-select" });
  for (const [v, l] of options) sel.append(el("option", { value: v, text: l }));
  sel.addEventListener("change", () => onPick(sel.value));
  const wrap = el("label", { class: `le-field ${cls}`.trim() }, el("span", { class: "le-field-l", text: label }), sel);
  return { el: wrap, sel, set: (v) => { sel.value = String(v); } };
}

function mkCheck(label, checked, onPick, title) {
  const cb = el("input", { type: "checkbox", "aria-label": label });
  cb.checked = !!checked;
  cb.addEventListener("change", () => onPick(cb.checked));
  return { el: el("label", { class: "le-check", title }, cb, el("span", { text: label })), cb, set: (v) => { cb.checked = !!v; } };
}

function isTyping(t) {
  if (!t || !t.tagName) return false;
  const n = t.tagName;
  return n === "TEXTAREA" || n === "SELECT" || t.isContentEditable || (n === "INPUT" && !["checkbox", "radio", "button", "range"].includes(t.type));
}

// ------------------------------------------------------------------------------------------ the editor
/**
 * @param {HTMLElement} container  an element with a definite height; the editor fills it (100% x 100%)
 * @param {{api: object, tag: string, label?: string, grid?: 'canvas'|'head', layers?: Array<{tag:string,label:string,grid?:string,empty?:boolean}>,
 *          rev?: number, initial?: {tool?: string, overlay?: string}, onApplied?: (state: object) => void, onClose?: () => void}} opts
 */
export function mountLayerEditor(container, opts = {}) {
  if (!(container instanceof Element)) throw new TypeError("mountLayerEditor: container must be a DOM element");
  const api = opts.api;
  if (!api || typeof api.edit !== "function") throw new TypeError("mountLayerEditor: opts.api (with edit/layerImageUrl/sourceUrl) is required");
  const uid = `le${++uidCounter}`;
  let disposed = false;
  const cleanups = [];
  const on = (target, type, fn, o) => { target.addEventListener(type, fn, o); cleanups.push(() => target.removeEventListener(type, fn, o)); };

  // ---- state
  const st = {
    tag: opts.tag, label: opts.label || opts.tag, grid: opts.grid || "canvas", layers: opts.layers || [], rev: Number(opts.rev) || 0,
    tool: TOOLS.some((t) => t.id === opts.initial?.tool) ? opts.initial.tool : "brush",
    overlay: OVERLAYS.some((o) => o.v === opts.initial?.overlay) ? opts.initial.overlay : "blend",
    ghost: 0.35, diffThr: 48,
    brush: { size: 40, hardness: 70, pressure: true },
    wand: { source: "layer", metric: "rgb", tol: 32, contiguous: true, win: 1 },
    selMode: "replace", growPx: 3, featherSelPx: 4, applyFeather: 0, moveTo: "",
    space: false, busy: false, ready: false, loading: false, error: null, armed: true, interacted: false,
    sel: { count: 0, bbox: null, any: null },
    cursor: null, lastWandMs: 0, lastOpMs: 0, ops: 0,
  };
  const view = { zoom: 1, x: 0, y: 0 };
  let stageW = 0, stageH = 0, dpr = 1, needFit = true;

  // ---- canvases (all grid sized, never in the DOM)
  const maskCv = mkCanvas(), mctx = maskCv.getContext("2d", { willReadFrequently: true });
  const scratchCv = mkCanvas(), sctx = scratchCv.getContext("2d", { willReadFrequently: true });
  const tintCv = mkCanvas(), tctx = tintCv.getContext("2d");
  const layerCv = mkCanvas(), lctx = layerCv.getContext("2d", { willReadFrequently: true });
  const sourceCv = mkCanvas(), srcCtx = sourceCv.getContext("2d", { willReadFrequently: true });
  const diffCv = mkCanvas(), dctx = diffCv.getContext("2d");
  const antsCv = mkCanvas(), actx = antsCv.getContext("2d", { willReadFrequently: true });
  const shapeImg = new ImageData(G, G);
  { const d = shapeImg.data; for (let i = 0; i < d.length; i += 4) { d[i] = d[i + 1] = d[i + 2] = 255; } }
  let antsImg = null, diffBuf = null;
  let layerPx = null, sourcePx = null, layerA = new Uint8Array(G * G), sourceA = new Uint8Array(G * G);
  let layerBBox = null, sourceBBox = null;
  let selA = new Uint8Array(G * G), prevA = new Uint8Array(G * G);
  let islands = null;  // { labels, comps }
  let tintDirty = true, diffDirty = true, antsDirty = true, antsT = 1, antsToken = 0, antsUrl = null;
  let loadToken = 0, readyPromise = null, readyResolve = null, pendingOp = null;

  // ---- history of the selection (snapshots are bbox-cropped canvas clones; null = empty selection)
  let hist = { entries: [{ snap: null, label: "시작" }], idx: 0 };
  const snapBytes = (s) => (s ? s.w * s.h * 4 : 0);

  // ---------------------------------------------------------------------------------------- DOM
  const root = el("div", { class: "le-root", "data-active-tool": st.tool, "data-active-overlay": st.overlay, "data-uid": uid });
  root.style.visibility = "hidden";
  const stylesReady = ensureStyles().then(() => {
    if (disposed) return;
    root.style.visibility = "";
    css = null;                                   // the stylesheet decides the grid, the tint and the checker colours
    resize();
    if (!st.interacted && st.ready) fitView();
  });
  const grid = el("div", { class: "le-grid" });
  root.append(grid);

  const toolBtns = new Map();
  const toolbox = el("div", { class: "le-toolbox", role: "toolbar", "aria-label": "도구", "aria-orientation": "vertical" });
  TOOLS.forEach((t, i) => {
    if (i === 2 || i === 6) toolbox.append(el("div", { class: "le-sep", role: "separator" }));
    const b = btn({ ico: t.ico, label: `${t.label} (${t.key})`, title: `${t.label} (${t.key}) - ${t.tip}`, cls: "le-tool", data: { tool: t.id }, pressed: false, onClick: () => setTool(t.id) });
    toolBtns.set(t.id, b);
    toolbox.append(b);
  });
  const helpBtn = btn({ ico: "help", label: "단축키 도움말 (?)", title: "단축키 도움말 (?)", cls: "le-tool le-help-btn", data: { act: "help" }, onClick: () => toggleHelp() });
  toolbox.append(el("div", { class: "le-grow" }), helpBtn);

  // options bar ---------------------------------------------------------------------------------
  const optbar = el("div", { class: "le-optbar" });
  const optGroups = [];
  const addGroup = (tools, ...kids) => { const g = el("div", { class: "le-opts" }, ...kids); optGroups.push({ tools, el: g }); optbar.append(g); return g; };

  const brushSize = mkSlider({ label: "크기", min: 1, max: 400, value: st.brush.size, unit: "px", title: "브러시 크기 ([ ] 로 조절)", onInput: (v) => { st.brush.size = v; updateRing(); } });
  const brushHard = mkSlider({ label: "경도", min: 0, max: 100, value: st.brush.hardness, unit: "%", title: "0%에 가까울수록 가장자리가 부드럽습니다", onInput: (v) => { st.brush.hardness = v; updateRing(); } });
  const brushPress = mkCheck("펜 압력", st.brush.pressure, (v) => { st.brush.pressure = v; }, "펜이 있으면 누르는 세기로 크기를 조절합니다");
  addGroup(["brush", "eraser"], brushSize.el, brushHard.el, brushPress.el);

  const wandSource = mkSeg([{ v: "layer", l: "레이어", t: "레이어 픽셀에서 샘플" }, { v: "source", l: "원본", t: "원본 이미지 픽셀에서 샘플" }], (v) => { st.wand.source = v; wandSource.set(v); }, "샘플 대상");
  const wandMetric = mkSelect("거리", [["alpha", "알파"], ["luma", "밝기"], ["rgb", "RGB"]], (v) => { st.wand.metric = v; }, "le-metric");
  const wandTol = mkSlider({ label: "허용치", min: 0, max: 128, value: st.wand.tol, title: "클릭한 픽셀과 얼마나 달라도 포함할지 (0~128)", onInput: (v) => { st.wand.tol = v; } });
  const wandContig = mkCheck("인접한 영역만", st.wand.contiguous, (v) => { st.wand.contiguous = v; }, "끄면 레이어 전체에서 비슷한 픽셀을 모두 고릅니다");
  const wandWin = mkSelect("샘플 창", [["1", "1 px"], ["3", "3 px"], ["5", "5 px"], ["11", "11 px"]], (v) => { st.wand.win = Number(v); }, "le-win");
  addGroup(["wand"], el("div", { class: "le-field" }, el("span", { class: "le-field-l", text: "샘플" }), wandSource.el), wandMetric.el, wandTol.el, wandContig.el, wandWin.el);

  const modeSeg = mkSeg(MODES, (v) => setSelMode(v), "선택 방식");
  addGroup(["wand", "lasso", "rect", "island"], el("div", { class: "le-field" }, el("span", { class: "le-field-l", text: "방식" }), modeSeg.el), el("span", { class: "le-hint le-hint-opt", text: "Shift 추가 · Alt 빼기 · Shift+Alt 교집합" }));
  addGroup(["hand"], el("span", { class: "le-hint", text: "드래그해서 화면을 옮깁니다. 휠은 커서 위치를 기준으로 확대/축소합니다." }));
  addGroup(["zoom"], el("span", { class: "le-hint", text: "클릭 확대 · Alt+클릭 축소 · 드래그한 영역으로 확대" }));
  addGroup(["island"], el("span", { class: "le-hint", text: "클릭한 덩어리를 통째로 선택합니다. 목록은 오른쪽 패널에 있습니다." }));

  const undoBtn = btn({ ico: "undo", label: "되돌리기 (Ctrl+Z)", title: "선택 되돌리기 (Ctrl+Z)", cls: "le-ico-btn", data: { act: "undo" }, onClick: () => undo() });
  const redoBtn = btn({ ico: "redo", label: "다시 실행 (Ctrl+Shift+Z)", title: "선택 다시 실행 (Ctrl+Shift+Z / Ctrl+Y)", cls: "le-ico-btn", data: { act: "redo" }, onClick: () => redo() });
  const closeBtn = btn({ ico: "close", text: "닫기", label: "편집기 닫기", title: "편집기 닫기 (선택이 없을 때 Esc)", cls: "le-close", data: { act: "close" }, onClick: () => requestClose() });
  optbar.append(el("div", { class: "le-grow" }), el("div", { class: "le-opts le-opts-end" }, undoBtn, redoBtn, closeBtn));

  // stage ---------------------------------------------------------------------------------------
  const stage = el("div", { class: "le-stage", tabindex: "0", role: "application", "aria-label": "레이어 편집 캔버스" });
  const viewCv = el("canvas", { class: "le-view", "aria-hidden": "true" });
  const vctx = viewCv.getContext("2d");
  const ants = el("div", { class: "le-ants", "aria-hidden": "true", hidden: true });
  const uiCv = el("canvas", { class: "le-ui", "aria-hidden": "true" });
  const uictx = uiCv.getContext("2d");
  const ring = el("div", { class: "le-ring", "aria-hidden": "true" });
  const toasts = el("div", { class: "le-toasts", "aria-live": "polite" });
  const busyEl = el("div", { class: "le-busy", role: "status", "aria-live": "polite", hidden: true }, el("div", { class: "le-spin", "aria-hidden": "true" }), el("div", { class: "le-busy-t", text: "적용 중…" }));
  const loadingEl = el("div", { class: "le-loading", role: "status", hidden: true }, el("div", { class: "le-spin", "aria-hidden": "true" }), el("div", { class: "le-busy-t", text: "레이어를 불러오는 중…" }));
  stage.append(viewCv, ants, uiCv, ring, toasts, loadingEl, busyEl);

  // right panel ---------------------------------------------------------------------------------
  const panel = el("div", { class: "le-panel" });
  const section = (title, ...kids) => {
    const d = el("details", { class: "le-sec", open: true }, el("summary", {}, el("span", { class: "le-sec-t", text: title })), el("div", { class: "le-sec-b" }, ...kids));
    panel.append(d);
    return d;
  };
  const act = (name, o) => btn({ ...o, data: { act: name }, cls: `le-act ${o.cls || ""}` });

  const growIn = el("input", { type: "number", class: "le-num", min: 1, max: 200, step: 1, value: st.growPx, "aria-label": "확장·축소 크기(px)" });
  growIn.addEventListener("change", () => { st.growPx = clamp(Math.round(Number(growIn.value) || 1), 1, 200); growIn.value = st.growPx; });
  const featIn = el("input", { type: "number", class: "le-num", min: 1, max: 100, step: 1, value: st.featherSelPx, "aria-label": "선택 페더 크기(px)" });
  featIn.addEventListener("change", () => { st.featherSelPx = clamp(Math.round(Number(featIn.value) || 1), 1, 100); featIn.value = st.featherSelPx; });
  const selSummary = el("div", { class: "le-summary", "aria-live": "polite", text: "선택 없음" });
  const islandsBox = el("div", { class: "le-islands", hidden: true });
  section(
    "선택",
    el("div", { class: "le-row le-row3" }, act("select-all", { ico: "all", text: "전체", title: "전체 선택 (Ctrl+A)", onClick: () => selectAll() }), act("deselect", { ico: "none", text: "해제", title: "선택 해제 (Ctrl+D)", onClick: () => deselect() }), act("invert", { ico: "invert", text: "반전", title: "선택 반전 (Ctrl+I)", onClick: () => invert() })),
    el("div", { class: "le-row" }, act("shrink", { ico: "shrink", text: "축소", title: "선택을 안쪽으로 줄이기", onClick: () => morph("shrink") }), growIn, el("span", { class: "le-unit", text: "px" }), act("grow", { ico: "grow", text: "확장", title: "선택을 바깥으로 넓히기", onClick: () => morph("grow") })),
    el("div", { class: "le-row" }, el("span", { class: "le-field-l", text: "선택 페더" }), featIn, el("span", { class: "le-unit", text: "px" }), act("feather-sel", { ico: "feather", text: "적용", title: "선택 가장자리를 흐리게", onClick: () => featherSel() })),
    el("div", { class: "le-row" }, act("only-layer", { ico: "layer", text: "레이어 내용만", title: "레이어에 픽셀이 있는 곳만 남기기 (선택이 없으면 레이어 내용 전체 선택)", onClick: () => intersectWith("layer") }), act("only-source", { ico: "source", text: "소스 전경만", title: "원본에서 그림이 있는 곳만 남기기 (선택이 없으면 원본 전경 전체 선택)", onClick: () => intersectWith("source") })),
    el("div", { class: "le-row" }, act("islands", { ico: "list", text: "연결 성분 목록", title: "레이어의 덩어리(섬) 목록 - 작은 점(16px 미만)은 제외", onClick: () => toggleIslands() })),
    islandsBox,
    selSummary,
  );

  const moveSel = el("select", { class: "le-select", "aria-label": "옮길 레이어", "data-act": "move-target" });
  moveSel.addEventListener("change", () => { st.moveTo = moveSel.value; updateUi(); });
  const applyFeather = mkSlider({ label: "가장자리 부드럽게", min: 0, max: 8, value: 0, unit: "px", title: "적용할 때 선택 가장자리를 부드럽게 (0~8px)", onInput: (v) => { st.applyFeather = v; } });
  section(
    "적용",
    el("div", { class: "le-row le-row2" }, act("erase", { ico: "trash", text: "지우기", title: "선택한 부분의 레이어 픽셀 지우기 (Delete)", cls: "le-danger", onClick: () => runOp("erase") }), act("restore", { ico: "restore", text: "소스로 채우기", title: "선택한 부분을 원본 픽셀로 채우기 (R)", onClick: () => runOp("restore") })),
    el("div", { class: "le-row" }, moveSel, act("move", { ico: "move", text: "옮기기", title: "선택한 부분을 고른 레이어로 옮기기", onClick: () => runOp("move") })),
    el("div", { class: "le-row le-row2" }, act("fill-hole", { ico: "hole", text: "구멍 메우기", title: "레이어 안의 막힌 투명 구멍을 원본으로 메우기 (선택이 있으면 그 안만)", onClick: () => runOp("fill_hole") }), act("clean", { ico: "clean", text: "자동 정리", title: "레이어 전체 자동 정리 (작은 조각·잡티)", onClick: () => runOp("clean") })),
    applyFeather.el,
    el("p", { class: "le-note", text: "적용하면 새 버전이 생기고 퍼펫이 다시 만들어집니다. 되돌리기는 버전 목록에서 합니다." }),
  );

  const overlaySeg = el("div", { class: "le-seg le-seg-wide", role: "group", "aria-label": "보기 모드" });
  const overlayBtns = new Map();
  for (const o of OVERLAYS) {
    const b = el("button", { type: "button", class: "le-seg-b", title: `${o.t} (${o.k})`, "aria-pressed": "false", "data-overlay": o.v, "aria-label": `${o.l} (${o.k})` });
    b.insertAdjacentHTML("beforeend", icon(o.ico, 16));
    b.append(el("span", { text: o.l }));
    b.addEventListener("click", () => setOverlay(o.v));
    overlaySeg.append(b);
    overlayBtns.set(o.v, b);
  }
  const ghostSl = mkSlider({ label: "원본 진하기", min: 0, max: 100, value: Math.round(st.ghost * 100), unit: "%", title: "겹쳐 보기에서 원본이 얼마나 보일지", onInput: (v) => { st.ghost = v / 100; invalidate(); } });
  const diffSl = mkSlider({ label: "차이 민감도", min: 8, max: 128, value: st.diffThr, title: "색 차이가 이 값보다 크면 표시 (낮을수록 민감)", onInput: (v) => { st.diffThr = v; diffDirty = true; invalidate(); } });
  const legend = el("div", { class: "le-legend", role: "list" },
    el("span", { role: "listitem" }, el("i", { class: "le-sw le-sw-extra" }), "원본에 없는 곳"),
    el("span", { role: "listitem" }, el("i", { class: "le-sw le-sw-differs" }), "색이 다른 곳"),
    el("span", { role: "listitem" }, el("i", { class: "le-sw le-sw-missing" }), "원본엔 있고 레이어엔 없는 곳"));
  const miniCv = el("canvas", { class: "le-mini", width: 264, height: 264, "aria-label": "미니맵 (클릭해서 이동)", role: "img" });
  const mctxMini = miniCv.getContext("2d");
  const zoomLabel = el("span", { class: "le-zoom-l", "aria-live": "off", text: "100%" });
  section(
    "보기",
    overlaySeg, ghostSl.el, diffSl.el, legend,
    el("div", { class: "le-viewrow" }, miniCv,
      el("div", { class: "le-zoomcol" },
        el("div", { class: "le-row le-zoombar" }, act("zoom-out", { ico: "minus", label: "축소", title: "축소 (-)", cls: "le-ico-btn", onClick: () => zoomBy(1 / 1.25) }), zoomLabel, act("zoom-in", { ico: "plus", label: "확대", title: "확대 (+)", cls: "le-ico-btn", onClick: () => zoomBy(1.25) })),
        act("fit", { ico: "fit", text: "레이어에 맞춤", title: "레이어 영역에 맞추기 (F)", onClick: () => fitView() }),
        act("zoom100", { text: "100%", title: "실제 크기 (100%)", onClick: () => zoomTo(1) }))),
  );

  // status line ---------------------------------------------------------------------------------
  const stLayer = el("span", { class: "le-st-layer" }), stCursor = el("span", { class: "le-st-cursor", text: "좌표 -" }), stZoom = el("span", { class: "le-st-zoom" }), stSel = el("span", { class: "le-st-sel" });
  const statusBar = el("div", { class: "le-status", role: "status" }, stLayer, el("span", { class: "le-grow" }), stCursor, stZoom, stSel);

  // popovers ------------------------------------------------------------------------------------
  const helpPop = el("div", { class: "le-pop", role: "dialog", "aria-label": "단축키", hidden: true });
  const keyRow = (k, d) => el("div", { class: "le-krow" }, el("kbd", { text: k }), el("span", { text: d }));
  helpPop.append(
    el("div", { class: "le-pop-h" }, el("b", { text: "단축키" }), el("button", { type: "button", class: "le-ico-btn le-btn", "aria-label": "닫기", html: icon("close", 16), onclick: () => toggleHelp(false) })),
    el("div", { class: "le-pop-cols" },
      el("div", {}, el("h4", { text: "도구" }), keyRow("B", "브러시"), keyRow("E", "지우개"), keyRow("W", "마술봉"), keyRow("L", "올가미"), keyRow("M", "사각형 선택"), keyRow("C", "연결 성분"), keyRow("H", "손"), keyRow("Z", "확대"), keyRow("X", "브러시/지우개 전환"), keyRow("[ ]", "브러시 크기")),
      el("div", {}, el("h4", { text: "선택" }), keyRow("Ctrl+A", "전체 선택"), keyRow("Ctrl+D", "선택 해제"), keyRow("Ctrl+I", "반전"), keyRow("Shift", "더하기"), keyRow("Alt", "빼기"), keyRow("Shift+Alt", "교집합"), keyRow("Esc", "선택 해제 / 닫기"),
        el("h4", { text: "기록" }), keyRow("Ctrl+Z", "되돌리기"), keyRow("Ctrl+Shift+Z", "다시 실행 (Ctrl+Y)")),
      el("div", {}, el("h4", { text: "적용" }), keyRow("Delete", "지우기"), keyRow("R", "소스로 채우기"),
        el("h4", { text: "보기" }), keyRow("1 2 3 4", "레이어·원본·겹쳐·차이"), keyRow("휠", "커서 기준 확대"), keyRow("Space+드래그", "화면 이동"), keyRow("F", "레이어에 맞춤"), keyRow("+ -", "확대 / 축소"), keyRow("?", "이 도움말"))));

  const modal = el("div", { class: "le-modal", hidden: true });
  let modalResolve = null;

  grid.append(toolbox, optbar, stage, panel, statusBar);
  root.append(helpPop, modal);
  container.append(root);

  // ---------------------------------------------------------------------------------------- readiness
  readyPromise = new Promise((r) => { readyResolve = r; });

  // ---------------------------------------------------------------------------------------- selection plumbing
  function putPlane(plane, ctx) {
    const d = shapeImg.data;
    for (let i = 0, j = 3, n = plane.length; i < n; i++, j += 4) d[j] = plane[i];
    ctx.putImageData(shapeImg, 0, 0);
  }

  /** Compose the shape staged on `scratchCv` into the mask according to mode. */
  function combine(mode) {
    mctx.save();
    mctx.setTransform(1, 0, 0, 1, 0, 0);
    mctx.globalAlpha = 1;
    mctx.globalCompositeOperation = mode === "replace" ? "copy" : mode === "add" ? "source-over" : mode === "subtract" ? "destination-out" : "destination-in";
    mctx.drawImage(scratchCv, 0, 0);
    mctx.restore();
  }

  function refreshStats() {
    const d = mctx.getImageData(0, 0, G, G).data;
    const t = prevA; prevA = selA; selA = t;
    ops.alphaPlane(d, selA);
    st.sel = ops.maskStats(selA, G, G);
  }

  function snapshot() {
    const b = st.sel.any;
    if (!b) return null;
    const w = b.x1 - b.x0 + 1, h = b.y1 - b.y0 + 1;
    const c = mkCanvas(w, h);
    c.getContext("2d").drawImage(maskCv, b.x0, b.y0, w, h, 0, 0, w, h);
    return { cv: c, x: b.x0, y: b.y0, w, h };
  }

  function restoreSnap(s) {
    mctx.clearRect(0, 0, G, G);
    if (s) mctx.drawImage(s.cv, s.x, s.y);
  }

  function trimHistory() {
    const bytes = () => hist.entries.reduce((n, e) => n + snapBytes(e.snap), 0);
    while (hist.entries.length > 2 && (hist.entries.length > HIST_MAX || bytes() > HIST_BYTES) && hist.idx > 0) {
      const dead = hist.entries.shift();
      if (dead.snap) { dead.snap.cv.width = 0; }
      hist.idx--;
    }
  }

  function resetHistory() {
    for (const e of hist.entries) if (e.snap) e.snap.cv.width = 0;
    hist = { entries: [{ snap: null, label: "시작" }], idx: 0 };
  }

  /** After any change of the mask canvas: re-read stats, push a history entry when the selection really changed. */
  function commitMask(label, { record = true } = {}) {
    refreshStats();
    if (record && !ops.equalPlanes(prevA, selA)) {
      hist.entries.length = hist.idx + 1;
      hist.entries.push({ snap: snapshot(), label });
      hist.idx++;
      trimHistory();
    }
    tintDirty = true; antsDirty = true;
    invalidate();
    updateUi();
    if (view.zoom >= VEC_ZOOM) drawUi();
  }

  function clearMask() { mctx.clearRect(0, 0, G, G); }

  function resetSelectionAndHistory() {
    clearMask();
    resetHistory();
    refreshStats();
    tintDirty = true; antsDirty = true;
    invalidate(); updateUi(); drawUi();
  }

  function undo() { if (st.busy || hist.idx <= 0 || gest) return; hist.idx--; restoreSnap(hist.entries[hist.idx].snap); commitMask("undo", { record: false }); }
  function redo() { if (st.busy || hist.idx >= hist.entries.length - 1 || gest) return; hist.idx++; restoreSnap(hist.entries[hist.idx].snap); commitMask("redo", { record: false }); }

  function selectAll() {
    if (st.busy || !st.ready) return;
    mctx.save(); mctx.globalCompositeOperation = "copy"; mctx.fillStyle = "#fff"; mctx.fillRect(0, 0, G, G); mctx.restore();
    commitMask("전체 선택");
  }
  function deselect() {
    if (st.busy) return;
    clearMask();
    commitMask("선택 해제");
  }
  function invert() {
    if (st.busy || !st.ready) return;
    sctx.save(); sctx.globalCompositeOperation = "copy"; sctx.fillStyle = "#fff"; sctx.fillRect(0, 0, G, G);
    sctx.globalCompositeOperation = "destination-out"; sctx.drawImage(maskCv, 0, 0); sctx.restore();
    combine("replace");
    commitMask("반전");
  }
  function morph(mode) {
    if (st.busy || !st.sel.count) return;
    const t0 = performance.now();
    const out = ops.morphMask(selA, G, G, st.sel.bbox, st.growPx, mode);
    putPlane(out, mctx);
    st.lastOpMs = performance.now() - t0;
    commitMask(mode === "grow" ? "확장" : "축소");
  }
  function featherSel() {
    if (st.busy || !st.sel.count) return;
    const t0 = performance.now();
    const out = ops.featherPlane(selA, G, G, st.sel.any, st.featherSelPx);
    putPlane(out, mctx);
    st.lastOpMs = performance.now() - t0;
    commitMask("페더");
  }
  /** Intersect the selection with the layer's (or the source's) content; with no selection this selects all of that content. */
  function intersectWith(which) {
    if (st.busy || !st.ready) return;
    const plane = which === "layer" ? layerA : sourceA;
    putPlane(ops.thresholdPlane(plane, ops.CONTENT_T), sctx);
    combine(st.sel.count ? "intersect" : "replace");
    commitMask(which === "layer" ? "레이어 내용만" : "소스 전경만");
  }

  // ---------------------------------------------------------------------------------------- connected components
  function toggleIslands(force) {
    const open = force === undefined ? islandsBox.hidden : force;
    islandsBox.hidden = !open;
    if (open) renderIslands();
  }

  function ensureIslands() {
    if (!islands) {
      const t0 = performance.now();
      const { labels, comps } = ops.labelComponents(layerA, G, G, ops.CONTENT_T);
      comps.sort((a, b) => b.area - a.area);
      islands = { labels, comps };
      st.lastOpMs = performance.now() - t0;
    }
    return islands;
  }

  function renderIslands() {
    islandsBox.textContent = "";
    if (!st.ready) return;
    const { comps } = ensureIslands();
    const big = comps.filter((c) => c.area >= 16);
    const dropped = comps.length - big.length;
    islandsBox.append(el("div", { class: "le-isl-h", text: big.length ? `덩어리 ${big.length}개${dropped ? ` (16px 미만 ${dropped}개 제외)` : ""}` : "덩어리가 없습니다" }));
    if (comps.length > 1) {
      islandsBox.append(btn({ text: "가장 큰 덩어리 빼고 선택", title: "가장 큰 덩어리를 뺀 나머지 조각(작은 점 포함)을 모두 선택", cls: "le-act le-wide", data: { act: "islands-rest" }, onClick: (e) => selectIslands(comps.slice(1), e) }));
    }
    const list = el("div", { class: "le-isl-list", role: "list" });
    big.slice(0, 60).forEach((c, i) => {
      const b = el("button", { type: "button", class: "le-isl", role: "listitem", "data-island": String(c.id), title: "클릭: 선택 · Shift: 추가 · Alt: 빼기" },
        el("span", { class: "le-isl-n", text: `#${i + 1}` }), el("span", { class: "le-isl-a", text: `${c.area.toLocaleString("ko-KR")} px` }), el("span", { class: "le-isl-b", text: `${c.x1 - c.x0 + 1}×${c.y1 - c.y0 + 1}` }));
      b.addEventListener("click", (e) => selectIslands([c], e));
      b.addEventListener("pointerenter", () => { hoverBox = c; drawUi(); });
      b.addEventListener("pointerleave", () => { hoverBox = null; drawUi(); });
      list.append(b);
    });
    if (big.length > 60) list.append(el("div", { class: "le-isl-more", text: `그 밖에 ${big.length - 60}개` }));
    islandsBox.append(list);
  }

  function selectIslands(comps, e) {
    if (st.busy || !st.ready || !comps.length) return;
    putPlane(ops.maskFromLabels(ensureIslands().labels, new Set(comps.map((c) => c.id))), sctx);
    combine(modeFor(e));
    commitMask("연결 성분");
  }

  // ---------------------------------------------------------------------------------------- history of tools / modes
  function setSelMode(m) { st.selMode = m; modeSeg.set(m); }
  const modeFor = (e) => (e && e.shiftKey && e.altKey ? "intersect" : e && e.shiftKey ? "add" : e && e.altKey ? "subtract" : st.selMode);

  function setTool(id) {
    if (!toolBtns.has(id) || st.busy) return;
    if (gest) cancelGesture();
    st.tool = id;
    root.dataset.activeTool = id;
    for (const [k, b] of toolBtns) b.setAttribute("aria-pressed", String(k === id));
    for (const g of optGroups) g.el.hidden = !g.tools.includes(id);
    stage.style.cursor = "";
    ring.hidden = !(id === "brush" || id === "eraser");
    updateRing();
    drawUi();
    updateUi();
  }

  function setOverlay(v) {
    if (!OVERLAYS.some((o) => o.v === v)) return;
    st.overlay = v;
    root.dataset.activeOverlay = v;
    for (const [k, b] of overlayBtns) b.setAttribute("aria-pressed", String(k === v));
    ghostSl.el.hidden = v !== "blend";
    diffSl.el.hidden = v !== "diff";
    legend.hidden = v !== "diff";
    invalidate();
  }

  // ---------------------------------------------------------------------------------------- toasts / modal
  function toast(kind, text, { sticky = false, action = null, ms = 2800 } = {}) {
    const t = el("div", { class: `le-toast le-toast-${kind}`, role: kind === "bad" ? "alert" : "status" }, el("span", { class: "le-toast-t", text }));
    if (action) t.append(btn({ text: action.text, cls: "le-toast-a", onClick: () => { t.remove(); action.fn(); } }));
    const x = el("button", { type: "button", class: "le-toast-x", "aria-label": "메시지 닫기", html: icon("close", 14), onclick: () => t.remove() });
    t.append(x);
    while (toasts.children.length >= 3) toasts.firstElementChild.remove();
    toasts.append(t);
    if (!sticky) { const id = setTimeout(() => t.remove(), ms); cleanups.push(() => clearTimeout(id)); }
    return t;
  }

  function ask(text, okText = "확인", cancelText = "취소") {
    if (modalResolve) modalResolve(false);
    modal.textContent = "";
    const okB = btn({ text: okText, cls: "le-primary", data: { act: "confirm-ok" } });
    const noB = btn({ text: cancelText, data: { act: "confirm-cancel" } });
    modal.append(el("div", { class: "le-dialog", role: "alertdialog", "aria-modal": "true", "aria-label": text }, el("p", { text }), el("div", { class: "le-dialog-b" }, noB, okB)));
    modal.hidden = false;
    return new Promise((resolve) => {
      const done = (v) => { modal.hidden = true; modal.textContent = ""; modalResolve = null; resolve(v); };
      modalResolve = done;
      okB.addEventListener("click", () => done(true));
      noB.addEventListener("click", () => done(false));
      okB.focus();
    });
  }

  function toggleHelp(force) {
    const open = force === undefined ? helpPop.hidden : force;
    helpPop.hidden = !open;
    helpBtn.setAttribute("aria-pressed", String(open));
  }

  // ---------------------------------------------------------------------------------------- applying operations
  function setBusy(on, text) {
    st.busy = on;
    root.dataset.busy = on ? "1" : "";
    busyEl.hidden = !on;
    if (on) busyEl.querySelector(".le-busy-t").textContent = text || "적용 중…";
    stage.setAttribute("aria-busy", String(on));
    updateUi();
  }

  async function runOp(op) {
    if (st.busy || !st.ready || disposed) return;
    const needMask = op === "erase" || op === "restore" || op === "move";
    if (needMask && !st.sel.count) return;
    if (op === "move" && !st.moveTo) return;
    const tag = st.tag;
    const count = st.sel.count;
    const payload = { op, rebuild: true };
    if (needMask || (op === "fill_hole" && count)) {
      payload.mask = maskToBase64(maskCv);
      payload.feather = st.applyFeather;
    }
    if (op === "move") payload.to = st.moveTo;
    payload.note = op === "clean" ? "자동 정리" : `${{ erase: "지우기", restore: "소스로 채우기", move: "옮기기", fill_hole: "구멍 메우기" }[op]}${count ? ` (선택 ${count}px)` : ""}`;
    setBusy(true, OP_LABEL[op]);
    const t0 = performance.now();
    pendingOp = (async () => {
      try {
        const res = await api.edit(tag, payload);
        if (disposed) return;
        if (res && res.ok === false) throw new Error(res.detail || res.error || "적용하지 못했습니다");
        const state = res && res.state ? res.state : res;
        st.lastOpMs = performance.now() - t0;
        st.ops++;
        if (tag !== st.tag) return;
        if (state && Number.isFinite(Number(state.rev))) st.rev = Number(state.rev); else st.rev += 1;
        resetSelectionAndHistory();
        reloadImages({ fit: false });
        toast("ok", OP_DONE[op] || "적용했습니다");
        try { opts.onApplied && opts.onApplied(state); } catch (err) { console.error("onApplied failed:", err); }
      } catch (err) {
        if (disposed) return;
        st.error = String((err && err.message) || err);
        toast("bad", `적용하지 못했습니다: ${st.error}`, { sticky: true });
      } finally {
        pendingOp = null;
        if (!disposed) setBusy(false);
      }
    })();
    await pendingOp;
  }

  // ---------------------------------------------------------------------------------------- images
  function setLoading(on) {
    st.loading = on;
    loadingEl.hidden = !on;
    updateUi();
  }

  async function reloadImages({ fit = false } = {}) {
    const token = ++loadToken;
    const tag = st.tag, gridName = st.grid, rev = st.rev;
    st.ready = false;
    setLoading(true);
    const lp = loadImage(api.layerImageUrl(tag, "current", rev));
    const sp = loadImage(api.sourceUrl(gridName, rev));
    let li = null, si = null, lerr = null;
    try { li = await lp; } catch (e) { lerr = e; }
    try { si = await sp; } catch (e) { si = null; }
    if (disposed || token !== loadToken) return;
    if (!li) {
      setLoading(false);
      st.error = lerr ? lerr.message : "레이어 이미지를 불러오지 못했습니다";
      toast("bad", `레이어 이미지를 불러오지 못했습니다`, { sticky: true, action: { text: "다시 시도", fn: () => reloadImages({ fit: true }) } });
      return;
    }
    lctx.clearRect(0, 0, G, G); lctx.drawImage(li, 0, 0, G, G);
    layerPx = lctx.getImageData(0, 0, G, G).data;
    ops.alphaPlane(layerPx, layerA);
    srcCtx.clearRect(0, 0, G, G);
    if (si) srcCtx.drawImage(si, 0, 0, G, G);
    else toast("warn", "원본 이미지를 불러오지 못해 원본 기준 기능을 쓸 수 없습니다", { ms: 5000 });
    sourcePx = srcCtx.getImageData(0, 0, G, G).data;
    ops.alphaPlane(sourcePx, sourceA);
    layerBBox = ops.planeBBox(layerA, G, G, ops.CONTENT_T);
    sourceBBox = ops.planeBBox(sourceA, G, G, ops.CONTENT_T);
    islands = null;
    diffDirty = true;
    st.ready = true;
    setLoading(false);
    if (fit || needFit) { needFit = true; if (stageW > 0) fitView(); }
    invalidate();
    updateUi();
    if (!islandsBox.hidden) renderIslands();
    if (readyResolve) { readyResolve(); readyResolve = null; }
  }

  // ---------------------------------------------------------------------------------------- view
  function stageRect() { return stage.getBoundingClientRect(); }
  const toGrid = (cx, cy) => { const r = stageRect(); return { x: (cx - r.left - view.x) / view.zoom, y: (cy - r.top - view.y) / view.zoom }; };
  const toClient = (gx, gy) => { const r = stageRect(); return { x: r.left + view.x + gx * view.zoom, y: r.top + view.y + gy * view.zoom }; };

  function clampPan() {
    const m = 48, gw = G * view.zoom;
    view.x = clamp(view.x, m - gw, stageW - m);
    view.y = clamp(view.y, m - gw, stageH - m);
  }

  function applyView() {
    clampPan();
    ants.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`;
    ants.style.setProperty("--z", String(view.zoom));
    zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
    stZoom.textContent = `확대 ${Math.round(view.zoom * 100)}%`;
    const t = clamp(Math.ceil(1.6 / view.zoom), 1, 6);
    if (t !== antsT) { antsT = t; antsDirty = true; }
    ants.hidden = !antsUrl || view.zoom >= VEC_ZOOM;
    updateRing();
    drawUi();
    invalidate();
  }

  function zoomAround(sx, sy, z) {
    z = clamp(z, MIN_ZOOM, MAX_ZOOM);
    const gx = (sx - view.x) / view.zoom, gy = (sy - view.y) / view.zoom;
    view.zoom = z; view.x = sx - gx * z; view.y = sy - gy * z;
    applyView();
  }
  function zoomBy(f) { zoomAround(stageW / 2, stageH / 2, view.zoom * f); }
  function zoomTo(z) { zoomAround(stageW / 2, stageH / 2, z); }

  function fitBox(b, margin = 0.07) {
    if (!(stageW > 0 && stageH > 0)) return;
    const bw = b.x1 - b.x0 + 1, bh = b.y1 - b.y0 + 1;
    const z = clamp(Math.min((stageW * (1 - 2 * margin)) / bw, (stageH * (1 - 2 * margin)) / bh), MIN_ZOOM, 16);
    view.zoom = z;
    view.x = stageW / 2 - (b.x0 + bw / 2) * z;
    view.y = stageH / 2 - (b.y0 + bh / 2) * z;
    applyView();
  }
  function fitView() {
    needFit = false;
    fitBox(layerBBox || sourceBBox || { x0: 0, y0: 0, x1: G - 1, y1: G - 1 });
  }

  function resize() {
    const r = stage.getBoundingClientRect();
    const w = Math.max(0, Math.round(r.width)), h = Math.max(0, Math.round(r.height));
    const d = Math.min(window.devicePixelRatio || 1, 2);
    if (w === stageW && h === stageH && d === dpr) return;
    stageW = w; stageH = h; dpr = d;
    for (const c of [viewCv, uiCv]) { c.width = Math.max(1, Math.round(w * d)); c.height = Math.max(1, Math.round(h * d)); }
    if (needFit && st.ready && w > 0) fitView(); else applyView();
    drawUi();
  }

  // css cache ------------------------------------------------------------------------------------
  let css = null, checkerKey = "", checkerPat = null;
  function readCss() {
    const cs = getComputedStyle(root);
    const v = (n, f) => cs.getPropertyValue(n).trim() || f;
    css = { bg: v("--le-stage-bg", "#e9ecf1"), a: v("--le-checker-a", "#ffffff"), b: v("--le-checker-b", "#d9dde4"), sel: v("--le-sel", "#ff3b6b"), selAlpha: Number(v("--le-sel-alpha", "0.45")) || 0.45, line: v("--le-grid-line", "rgba(0,0,0,.28)"), frame: v("--le-frame", "rgba(0,0,0,.45)") };
    checkerKey = ""; tintDirty = true;
  }

  function checker(ox, oy) {
    const key = `${css.a}|${css.b}`;
    if (key !== checkerKey) {
      const c = mkCanvas(16, 16), x = c.getContext("2d");
      x.fillStyle = css.a; x.fillRect(0, 0, 16, 16);
      x.fillStyle = css.b; x.fillRect(0, 0, 8, 8); x.fillRect(8, 8, 8, 8);
      checkerPat = vctx.createPattern(c, "repeat");
      checkerKey = key;
    }
    if (checkerPat.setTransform) checkerPat.setTransform(new DOMMatrix().translate(ox, oy));
    return checkerPat;
  }

  // render ---------------------------------------------------------------------------------------
  let raf = 0, miniDirty = true;
  function invalidate() {
    if (disposed || raf) return;
    raf = requestAnimationFrame(() => { raf = 0; render(); });
  }
  function flush() { if (raf) { cancelAnimationFrame(raf); raf = 0; } render(); }

  function drawGrid(ctx, cv, alpha = 1) {
    const z = view.zoom;
    const sx0 = Math.max(0, Math.floor(-view.x / z)), sy0 = Math.max(0, Math.floor(-view.y / z));
    const sx1 = Math.min(G, Math.ceil((stageW - view.x) / z)), sy1 = Math.min(G, Math.ceil((stageH - view.y) / z));
    const sw = sx1 - sx0, sh = sy1 - sy0;
    if (sw <= 0 || sh <= 0) return;
    ctx.globalAlpha = alpha;
    ctx.drawImage(cv, sx0, sy0, sw, sh, view.x + sx0 * z, view.y + sy0 * z, sw * z, sh * z);
    ctx.globalAlpha = 1;
  }

  function ensureTint() {
    if (!tintDirty) return;
    tctx.save();
    tctx.globalCompositeOperation = "copy";
    tctx.drawImage(maskCv, 0, 0);
    tctx.globalCompositeOperation = "source-in";
    tctx.fillStyle = css.sel;
    tctx.fillRect(0, 0, G, G);
    tctx.restore();
    tintDirty = false;
  }

  function ensureDiff() {
    if (!diffDirty) return;
    if (layerPx) {
      diffBuf = ops.buildDiff(layerPx, sourcePx, st.diffThr, diffBuf);
      dctx.putImageData(new ImageData(diffBuf, G, G), 0, 0);
    } else dctx.clearRect(0, 0, G, G);
    diffDirty = false;
  }

  function render() {
    if (disposed || !stageW || !stageH) return;
    if (!css) readCss();
    const ctx = vctx, z = view.zoom;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalAlpha = 1;
    ctx.fillStyle = css.bg;
    ctx.fillRect(0, 0, stageW, stageH);
    const gw = G * z;
    ctx.save();
    ctx.beginPath(); ctx.rect(view.x, view.y, gw, gw); ctx.clip();
    ctx.fillStyle = checker(view.x, view.y);
    ctx.fillRect(view.x, view.y, gw, gw);
    ctx.imageSmoothingEnabled = z <= 2;
    ctx.imageSmoothingQuality = "high";
    if (st.ready) {
      if (st.overlay === "layer") drawGrid(ctx, layerCv);
      else if (st.overlay === "source") drawGrid(ctx, sourceCv);
      else if (st.overlay === "blend") { drawGrid(ctx, sourceCv, st.ghost); drawGrid(ctx, layerCv); }
      else { ensureDiff(); drawGrid(ctx, layerCv, 0.45); drawGrid(ctx, diffCv); }
      ensureTint();
      drawGrid(ctx, tintCv, css.selAlpha);
    }
    ctx.restore();
    if (z >= 12 && st.ready) {                     // pixel grid at deep zoom
      ctx.strokeStyle = css.line; ctx.lineWidth = 1;
      ctx.beginPath();
      const x0 = Math.max(0, Math.floor(-view.x / z)), x1 = Math.min(G, Math.ceil((stageW - view.x) / z));
      const y0 = Math.max(0, Math.floor(-view.y / z)), y1 = Math.min(G, Math.ceil((stageH - view.y) / z));
      for (let gx = x0; gx <= x1; gx++) { const sx = Math.round(view.x + gx * z) + 0.5; ctx.moveTo(sx, Math.max(0, view.y + y0 * z)); ctx.lineTo(sx, Math.min(stageH, view.y + y1 * z)); }
      for (let gy = y0; gy <= y1; gy++) { const sy = Math.round(view.y + gy * z) + 0.5; ctx.moveTo(Math.max(0, view.x + x0 * z), sy); ctx.lineTo(Math.min(stageW, view.x + x1 * z), sy); }
      ctx.stroke();
    }
    ctx.strokeStyle = css.frame; ctx.lineWidth = 1;
    ctx.strokeRect(Math.round(view.x) + 0.5, Math.round(view.y) + 0.5, gw, gw);
    if (antsDirty) rebuildAnts();
    renderMini();
  }

  function renderMini() {
    const w = miniCv.width, h = miniCv.height, x = mctxMini;
    x.clearRect(0, 0, w, h);
    if (!css) return;
    x.fillStyle = css.bg; x.fillRect(0, 0, w, h);
    x.fillStyle = checker(0, 0); x.fillRect(0, 0, w, h);
    x.imageSmoothingEnabled = true; x.imageSmoothingQuality = "high";
    if (st.ready) {
      if (st.overlay !== "layer") { x.globalAlpha = st.overlay === "source" ? 1 : 0.3; x.drawImage(sourceCv, 0, 0, w, h); x.globalAlpha = 1; }
      if (st.overlay !== "source") x.drawImage(layerCv, 0, 0, w, h);
      if (st.sel.count) { x.globalAlpha = css.selAlpha; x.drawImage(tintCv, 0, 0, w, h); x.globalAlpha = 1; }
    }
    const k = w / G;
    const vx = clamp(-view.x / view.zoom, 0, G), vy = clamp(-view.y / view.zoom, 0, G);
    const vx2 = clamp((stageW - view.x) / view.zoom, 0, G), vy2 = clamp((stageH - view.y) / view.zoom, 0, G);
    x.lineWidth = 2; x.strokeStyle = "#ffffff"; x.strokeRect(vx * k, vy * k, (vx2 - vx) * k, (vy2 - vy) * k);
    x.lineWidth = 1; x.strokeStyle = "#5b4bdb"; x.strokeRect(vx * k, vy * k, (vx2 - vx) * k, (vy2 - vy) * k);
  }

  // marching ants --------------------------------------------------------------------------------
  function rebuildAnts() {
    antsDirty = false;
    if (!st.sel.count) { setAntsImage(null); return; }
    antsImg = antsImg || new ImageData(G, G);
    const rgba = ops.outlineRGBA(selA, G, G, st.sel.bbox, antsT, antsImg.data);
    if (rgba !== antsImg.data) antsImg = new ImageData(rgba, G, G);
    actx.putImageData(antsImg, 0, 0);
    const token = ++antsToken;
    antsCv.toBlob((blob) => {
      if (disposed || token !== antsToken || !blob) return;
      setAntsImage(URL.createObjectURL(blob));
    }, "image/png");
  }
  function setAntsImage(url) {
    antsToken++;
    const old = antsUrl;
    antsUrl = url;
    ants.style.maskImage = ants.style.webkitMaskImage = url ? `url("${url}")` : "none";
    ants.hidden = !url || view.zoom >= VEC_ZOOM;
    if (old) setTimeout(() => URL.revokeObjectURL(old), 400);
  }

  // ---------------------------------------------------------------------------------------- cursor ring
  function updateRing() {
    const d = Math.max(5, st.brush.size * view.zoom);
    ring.style.width = ring.style.height = `${d}px`;
    ring.style.setProperty("--h", String(st.brush.hardness / 100));
    ring.dataset.soft = st.brush.hardness < 100 ? "1" : "";
    if (st.cursor) placeRing(st.cursor.sx, st.cursor.sy);
  }
  function placeRing(sx, sy) {
    const d = parseFloat(ring.style.width) || 20;
    ring.style.transform = `translate(${sx - d / 2}px, ${sy - d / 2}px)`;
    ring.classList.toggle("is-on", true);
  }

  // ---------------------------------------------------------------------------------------- ui overlay (lasso / rect / zoom box / island hover)
  let hoverBox = null;
  function drawUi() {
    if (disposed) return;
    const c = uictx;
    c.setTransform(dpr, 0, 0, dpr, 0, 0);
    c.clearRect(0, 0, stageW, stageH);
    const sx = (gx) => view.x + gx * view.zoom, sy = (gy) => view.y + gy * view.zoom;
    const dash = () => { c.lineWidth = 3; c.setLineDash([]); c.strokeStyle = "rgba(0,0,0,.55)"; c.stroke(); c.lineWidth = 1.5; c.strokeStyle = "#fff"; c.setLineDash([6, 4]); c.stroke(); c.setLineDash([]); };
    if (gest && gest.kind === "lasso" && gest.pts.length > 1) {
      c.beginPath(); c.moveTo(sx(gest.pts[0][0]), sy(gest.pts[0][1]));
      for (let i = 1; i < gest.pts.length; i++) c.lineTo(sx(gest.pts[i][0]), sy(gest.pts[i][1]));
      dash();
      c.beginPath(); c.moveTo(sx(gest.pts[gest.pts.length - 1][0]), sy(gest.pts[gest.pts.length - 1][1])); c.lineTo(sx(gest.pts[0][0]), sy(gest.pts[0][1]));
      c.globalAlpha = 0.5; dash(); c.globalAlpha = 1;
    } else if (gest && (gest.kind === "rect" || gest.kind === "zoomrect") && gest.box) {
      const b = gest.box;
      c.beginPath(); c.rect(sx(b.x0) + 0.5, sy(b.y0) + 0.5, (b.x1 - b.x0) * view.zoom, (b.y1 - b.y0) * view.zoom);
      dash();
    }
    if (view.zoom >= VEC_ZOOM && st.sel.count && !stroke) drawVectorOutline(c);
    if (hoverBox) {
      c.beginPath(); c.rect(sx(hoverBox.x0) - 1.5, sy(hoverBox.y0) - 1.5, (hoverBox.x1 - hoverBox.x0 + 1) * view.zoom + 3, (hoverBox.y1 - hoverBox.y0 + 1) * view.zoom + 3);
      c.lineWidth = 2; c.strokeStyle = "#5b4bdb"; c.stroke();
    }
  }

  /** Deep zoom: the selection edge as thin lines (only the visible part of the selection is scanned). */
  function drawVectorOutline(c) {
    const b = st.sel.bbox, z = view.zoom;
    const x0 = Math.max(b.x0, Math.floor(-view.x / z) - 1), x1 = Math.min(b.x1, Math.ceil((stageW - view.x) / z) + 1);
    const y0 = Math.max(b.y0, Math.floor(-view.y / z) - 1), y1 = Math.min(b.y1, Math.ceil((stageH - view.y) / z) + 1);
    if (x1 < x0 || y1 < y0) return;
    const sel = (x, y) => x >= 0 && y >= 0 && x < G && y < G && selA[y * G + x] > ops.SEL_T;
    const sx = (gx) => Math.round(view.x + gx * z) + 0.5, sy = (gy) => Math.round(view.y + gy * z) + 0.5;
    c.beginPath();
    for (let y = y0; y <= y1; y++) {            // horizontal edges, merged into runs (top edge of a selected pixel, then bottom edge)
      for (const dy of [-1, 1]) {
        let run = -1;
        for (let x = x0; x <= x1 + 1; x++) {
          const edge = x <= x1 && sel(x, y) && !sel(x, y + dy);
          if (edge && run < 0) run = x;
          if (!edge && run >= 0) { const ly = sy(dy < 0 ? y : y + 1); c.moveTo(sx(run) - 0.5, ly); c.lineTo(sx(x) - 0.5, ly); run = -1; }
        }
      }
    }
    for (let x = x0; x <= x1; x++) {            // vertical edges
      for (const dx of [-1, 1]) {
        let run = -1;
        for (let y = y0; y <= y1 + 1; y++) {
          const edge = y <= y1 && sel(x, y) && !sel(x + dx, y);
          if (edge && run < 0) run = y;
          if (!edge && run >= 0) { const lx = sx(dx < 0 ? x : x + 1); c.moveTo(lx, sy(run) - 0.5); c.lineTo(lx, sy(y) - 0.5); run = -1; }
        }
      }
    }
    c.lineWidth = 3; c.setLineDash([]); c.strokeStyle = "rgba(0,0,0,.8)"; c.stroke();
    c.lineWidth = 1.5; c.strokeStyle = "#fff"; c.setLineDash([5, 4]); c.stroke(); c.setLineDash([]);
  }

  // ---------------------------------------------------------------------------------------- brush engine
  let stroke = null;
  function dabRadius(p) {
    const base = st.brush.size / 2;
    return p.pen && st.brush.pressure ? base * (0.25 + 0.75 * clamp(p.p, 0, 1)) : base;
  }
  function stamp(p) {
    const r = dabRadius(p);
    const c = mctx;
    c.save();
    c.globalCompositeOperation = stroke.op === "add" ? "source-over" : "destination-out";
    if (r <= 1.25) {
      const n = Math.max(1, Math.round(r * 2));
      c.fillStyle = "#fff";
      c.fillRect(Math.round(p.x - n / 2), Math.round(p.y - n / 2), n, n);
    } else if (st.brush.hardness >= 100) {
      c.fillStyle = "#fff";
      c.beginPath(); c.arc(p.x, p.y, r, 0, Math.PI * 2); c.fill();
    } else {
      const inner = r * (st.brush.hardness / 100);
      const g = c.createRadialGradient(p.x, p.y, inner, p.x, p.y, r);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      c.fillStyle = g;
      c.beginPath(); c.arc(p.x, p.y, r, 0, Math.PI * 2); c.fill();
    }
    c.restore();
    tintDirty = true;
  }
  function beginStroke(p, op) {
    stroke = { op, last: p, left: 0 };
    root.dataset.painting = "1";
    stamp(p);
    if (view.zoom >= VEC_ZOOM) drawUi();            // the vector outline is stale while painting
    invalidate();
  }
  function strokeTo(p) {
    const prev = stroke.last;
    const dx = p.x - prev.x, dy = p.y - prev.y, dist = Math.hypot(dx, dy);
    if (dist <= 0) return;
    const spacing = Math.max(0.5, dabRadius(p) * 0.25);
    let t = spacing - stroke.left;
    while (t <= dist) {
      const k = t / dist;
      stamp({ x: prev.x + dx * k, y: prev.y + dy * k, p: prev.p + (p.p - prev.p) * k, pen: p.pen });
      t += spacing;
    }
    stroke.left = dist - (t - spacing);
    stroke.last = p;
    invalidate();
  }
  function endStroke() {
    const op = stroke.op;
    stroke = null;
    delete root.dataset.painting;
    commitMask(op === "add" ? "브러시" : "지우개");
  }

  // ---------------------------------------------------------------------------------------- pointer handling
  const pointers = new Map();
  let gest = null;

  function pt(e) {
    const g = toGrid(e.clientX, e.clientY);
    return { x: g.x, y: g.y, p: e.pointerType === "pen" ? e.pressure : 0.5, pen: e.pointerType === "pen" };
  }
  function updateHover(e) {
    const r = stageRect();
    const sx = e.clientX - r.left, sy = e.clientY - r.top;
    st.cursor = { sx, sy };
    const gx = (sx - view.x) / view.zoom, gy = (sy - view.y) / view.zoom;
    stCursor.textContent = gx >= 0 && gy >= 0 && gx < G && gy < G ? `좌표 ${Math.floor(gx)}, ${Math.floor(gy)}` : "좌표 -";
    if (!ring.hidden) placeRing(sx, sy);
  }

  function onPointerDown(e) {
    if (st.busy || disposed || e.target.closest(".le-toasts")) return;
    st.interacted = true;
    stage.focus({ preventScroll: true });
    pointers.set(e.pointerId, { cx: e.clientX, cy: e.clientY, type: e.pointerType });
    if (e.pointerType === "touch" && pointers.size >= 2) { beginPinch(); try { stage.setPointerCapture(e.pointerId); } catch { /* ignore */ } return; }
    if (gest || !st.ready) return;
    const nav = e.button === 1 || e.button === 2 || st.space || st.tool === "hand";
    if (!nav && e.button !== 0) return;
    try { stage.setPointerCapture(e.pointerId); } catch { /* synthetic events have no active pointer */ }
    updateHover(e);
    if (nav) {
      gest = { kind: "pan", id: e.pointerId, sx: e.clientX, sy: e.clientY, vx: view.x, vy: view.y };
      stage.classList.add("is-panning");
      e.preventDefault();
      return;
    }
    const mode = modeFor(e);
    const p = pt(e);
    switch (st.tool) {
      case "brush": case "eraser":
        gest = { kind: "brush", id: e.pointerId };
        beginStroke(p, st.tool === "brush" ? "add" : "sub");
        break;
      case "wand": case "island":
        gest = { kind: "click", id: e.pointerId, tool: st.tool, sx: e.clientX, sy: e.clientY, mode };
        break;
      case "lasso":
        gest = { kind: "lasso", id: e.pointerId, pts: [[p.x, p.y]], mode, moved: false };
        break;
      case "rect":
        gest = { kind: "rect", id: e.pointerId, x0: p.x, y0: p.y, box: null, mode };
        break;
      case "zoom":
        gest = { kind: "zoomrect", id: e.pointerId, x0: p.x, y0: p.y, sx: e.clientX, sy: e.clientY, box: null, alt: e.altKey };
        break;
      default: break;
    }
    e.preventDefault();
  }

  function onPointerMove(e) {
    if (disposed) return;
    if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { cx: e.clientX, cy: e.clientY, type: e.pointerType });
    updateHover(e);
    if (!gest) return;
    if (gest.kind === "pinch") { movePinch(); return; }
    if (e.pointerId !== gest.id) return;
    switch (gest.kind) {
      case "pan":
        view.x = gest.vx + (e.clientX - gest.sx); view.y = gest.vy + (e.clientY - gest.sy);
        applyView();
        break;
      case "brush": {
        const evs = e.getCoalescedEvents ? e.getCoalescedEvents() : null;
        for (const ev of evs && evs.length ? evs : [e]) strokeTo(pt(ev));
        break;
      }
      case "click":
        if (Math.hypot(e.clientX - gest.sx, e.clientY - gest.sy) > 8) gest.dead = true;
        break;
      case "lasso": {
        const p = pt(e), last = gest.pts[gest.pts.length - 1];
        if (Math.hypot(p.x - last[0], p.y - last[1]) * view.zoom >= 1.5) { gest.pts.push([p.x, p.y]); gest.moved = true; drawUi(); }
        break;
      }
      case "rect": case "zoomrect": {
        const p = pt(e);
        const snap = gest.kind === "rect" ? Math.round : (v) => v;
        gest.box = { x0: Math.min(snap(gest.x0), snap(p.x)), y0: Math.min(snap(gest.y0), snap(p.y)), x1: Math.max(snap(gest.x0), snap(p.x)), y1: Math.max(snap(gest.y0), snap(p.y)) };
        drawUi();
        break;
      }
      default: break;
    }
  }

  function onPointerUp(e) {
    pointers.delete(e.pointerId);
    try { stage.releasePointerCapture(e.pointerId); } catch { /* not captured */ }
    if (!gest) return;
    if (gest.kind === "pinch") { if (pointers.size < 2) { gest = null; } return; }
    if (e.pointerId !== gest.id) return;
    const g = gest;
    gest = null;
    stage.classList.remove("is-panning");
    switch (g.kind) {
      case "brush": endStroke(); break;
      case "click": if (!g.dead && e.type !== "pointercancel") { const p = toGrid(e.clientX, e.clientY); g.tool === "wand" ? doWand(p.x, p.y, g.mode) : doIsland(p.x, p.y, g.mode); } break;
      case "lasso": if (e.type !== "pointercancel") finishLasso(g); break;
      case "rect": if (e.type !== "pointercancel") finishRect(g); break;
      case "zoomrect": if (e.type !== "pointercancel") finishZoom(g, e); break;
      default: break;
    }
    drawUi();
  }

  function cancelGesture() {
    if (!gest) return;
    const g = gest;
    gest = null;
    stage.classList.remove("is-panning");
    if (g.kind === "brush") {
      stroke = null; delete root.dataset.painting;
      restoreSnap(hist.entries[hist.idx].snap);          // drop the half-drawn stroke
      commitMask("cancel", { record: false });
    }
    drawUi();
  }

  // pinch (two touches) --------------------------------------------------------------------------
  function beginPinch() {
    cancelGesture();
    const [a, b] = [...pointers.values()];
    const r = stageRect();
    const mid = { x: (a.cx + b.cx) / 2 - r.left, y: (a.cy + b.cy) / 2 - r.top };
    gest = { kind: "pinch", d0: Math.hypot(a.cx - b.cx, a.cy - b.cy) || 1, z0: view.zoom, gx: (mid.x - view.x) / view.zoom, gy: (mid.y - view.y) / view.zoom };
  }
  function movePinch() {
    const [a, b] = [...pointers.values()];
    if (!a || !b) return;
    const r = stageRect();
    const mid = { x: (a.cx + b.cx) / 2 - r.left, y: (a.cy + b.cy) / 2 - r.top };
    const z = clamp(gest.z0 * (Math.hypot(a.cx - b.cx, a.cy - b.cy) / gest.d0), MIN_ZOOM, MAX_ZOOM);
    view.zoom = z; view.x = mid.x - gest.gx * z; view.y = mid.y - gest.gy * z;
    applyView();
  }

  // tool actions ---------------------------------------------------------------------------------
  function doWand(gx, gy, mode) {
    gx = Math.floor(gx); gy = Math.floor(gy);
    const px = st.wand.source === "source" ? sourcePx : layerPx;
    if (!px) return;
    if (gx < 0 || gy < 0 || gx >= G || gy >= G) { if (mode === "replace") deselect(); return; }
    const t0 = performance.now();
    const { mask } = ops.floodSelect(px, G, G, gx, gy, { metric: st.wand.metric, tolerance: st.wand.tol, contiguous: st.wand.contiguous, window: st.wand.win });
    st.lastWandMs = performance.now() - t0;
    putPlane(mask, sctx);
    combine(mode);
    commitMask("마술봉");
  }

  function doIsland(gx, gy, mode) {
    gx = Math.floor(gx); gy = Math.floor(gy);
    let sx = -1, sy = -1;
    const R = Math.ceil(8 / view.zoom);                       // forgive a click next to a thin island
    let best = Infinity;
    for (let dy = -R; dy <= R; dy++) for (let dx = -R; dx <= R; dx++) {
      const x = gx + dx, y = gy + dy;
      if (x < 0 || y < 0 || x >= G || y >= G || layerA[y * G + x] <= ops.CONTENT_T) continue;
      const d = dx * dx + dy * dy;
      if (d < best) { best = d; sx = x; sy = y; }
    }
    if (sx < 0) { if (mode === "replace" && st.sel.count) deselect(); return; }
    const t0 = performance.now();
    const { mask } = ops.componentFrom(layerA, G, G, sx, sy, ops.CONTENT_T);
    st.lastOpMs = performance.now() - t0;
    putPlane(mask, sctx);
    combine(mode);
    commitMask("연결 성분");
  }

  function finishLasso(g) {
    if (g.pts.length < 3) { if (g.mode === "replace" && st.sel.count) deselect(); return; }
    sctx.save();
    sctx.setTransform(1, 0, 0, 1, 0, 0);
    sctx.globalCompositeOperation = "copy"; sctx.fillStyle = "rgba(0,0,0,0)"; sctx.fillRect(0, 0, G, G);
    sctx.globalCompositeOperation = "source-over"; sctx.fillStyle = "#fff";
    sctx.beginPath(); sctx.moveTo(g.pts[0][0], g.pts[0][1]);
    for (let i = 1; i < g.pts.length; i++) sctx.lineTo(g.pts[i][0], g.pts[i][1]);
    sctx.closePath(); sctx.fill("nonzero");
    sctx.restore();
    combine(g.mode);
    commitMask("올가미");
  }

  function finishRect(g) {
    const b = g.box;
    if (!b || b.x1 - b.x0 < 1 || b.y1 - b.y0 < 1) { if (g.mode === "replace" && st.sel.count) deselect(); return; }
    sctx.save();
    sctx.setTransform(1, 0, 0, 1, 0, 0);
    sctx.globalCompositeOperation = "copy"; sctx.fillStyle = "rgba(0,0,0,0)"; sctx.fillRect(0, 0, G, G);
    sctx.globalCompositeOperation = "source-over"; sctx.fillStyle = "#fff";
    sctx.fillRect(b.x0, b.y0, b.x1 - b.x0, b.y1 - b.y0);
    sctx.restore();
    combine(g.mode);
    commitMask("사각형");
  }

  function finishZoom(g, e) {
    const b = g.box;
    const r = stageRect();
    if (b && Math.hypot(e.clientX - g.sx, e.clientY - g.sy) > 6 && b.x1 - b.x0 > 0.5 && b.y1 - b.y0 > 0.5) {
      fitBox({ x0: b.x0, y0: b.y0, x1: b.x1, y1: b.y1 }, 0.02);
    } else {
      zoomAround(e.clientX - r.left, e.clientY - r.top, view.zoom * (g.alt || e.altKey ? 0.5 : 2));
    }
  }

  function onWheel(e) {
    e.preventDefault();
    if (st.busy || disposed) return;
    const r = stageRect();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    const k = e.ctrlKey ? 0.01 : 0.0016;
    zoomAround(e.clientX - r.left, e.clientY - r.top, view.zoom * Math.exp(-e.deltaY * unit * k));
  }

  on(stage, "pointerdown", onPointerDown);
  on(stage, "pointermove", onPointerMove);
  on(stage, "pointerup", onPointerUp);
  on(stage, "pointercancel", onPointerUp);
  on(stage, "pointerleave", (e) => { if (!gest) { ring.classList.remove("is-on"); st.cursor = null; stCursor.textContent = "좌표 -"; } });
  on(stage, "wheel", onWheel, { passive: false });
  on(stage, "contextmenu", (e) => e.preventDefault());
  on(stage, "dblclick", (e) => e.preventDefault());

  // minimap
  let miniDrag = false;
  const miniGo = (e) => {
    const r = miniCv.getBoundingClientRect();
    const gx = ((e.clientX - r.left) / r.width) * G, gy = ((e.clientY - r.top) / r.height) * G;
    view.x = stageW / 2 - gx * view.zoom; view.y = stageH / 2 - gy * view.zoom;
    applyView();
  };
  on(miniCv, "pointerdown", (e) => { if (st.busy) return; miniDrag = true; try { miniCv.setPointerCapture(e.pointerId); } catch { /* ignore */ } miniGo(e); });
  on(miniCv, "pointermove", (e) => { if (miniDrag) miniGo(e); });
  on(miniCv, "pointerup", (e) => { miniDrag = false; try { miniCv.releasePointerCapture(e.pointerId); } catch { /* ignore */ } });

  on(document, "pointerdown", (e) => { st.armed = root.contains(e.target); }, true);
  on(root, "pointerdown", (e) => { if (!helpPop.hidden && !helpPop.contains(e.target) && e.target !== helpBtn && !helpBtn.contains(e.target)) toggleHelp(false); });
  // after a mouse click on a button hand the keyboard back to the canvas (Space must pan, not press the button again)
  on(root, "click", (e) => { const b = e.target.closest && e.target.closest("button"); if (b && e.detail > 0 && !b.closest(".le-modal") && !b.closest(".le-pop")) stage.focus({ preventScroll: true }); });

  // ---------------------------------------------------------------------------------------- keyboard
  function requestClose() {
    if (st.busy) return;
    if (st.sel.count) {
      ask("저장하지 않은 선택이 있습니다. 버리고 닫을까요?", "버리고 닫기").then((ok) => { if (ok && !disposed) opts.onClose && opts.onClose(); });
    } else opts.onClose && opts.onClose();
  }

  function sizeStep() { const s = st.brush.size; return s < 10 ? 1 : s < 50 ? 5 : s < 150 ? 10 : 25; }
  function setBrushSize(v) { st.brush.size = clamp(Math.round(v), 1, 400); brushSize.set(st.brush.size); updateRing(); }

  function onKeyDown(e) {
    if (disposed || !root.isConnected) return;
    if (e.key === "Escape") {
      if (modalResolve) { modalResolve(false); e.preventDefault(); return; }
      if (!helpPop.hidden) { toggleHelp(false); e.preventDefault(); return; }
    }
    if (isTyping(e.target) && e.key !== "Escape") return;
    const inRoot = root.contains(e.target);
    if (!inRoot && !(st.armed && (e.target === document.body || e.target === document.documentElement))) return;
    if (modalResolve) return;
    const ctrl = e.ctrlKey || e.metaKey;
    const code = e.code;
    if (st.busy) { if (e.key === "Escape") e.preventDefault(); return; }
    if (code === "Space" && !ctrl) {
      if (e.target.tagName === "BUTTON" || e.target.tagName === "SUMMARY") return;
      st.space = true; stage.classList.add("is-space"); e.preventDefault(); return;
    }
    if (ctrl) {
      if (code === "KeyZ") { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if (code === "KeyY") { e.preventDefault(); redo(); return; }
      if (code === "KeyA" && !e.shiftKey) { e.preventDefault(); selectAll(); return; }
      if (code === "KeyD" && !e.shiftKey) { e.preventDefault(); deselect(); return; }
      if (code === "KeyI" && !e.shiftKey) { e.preventDefault(); invert(); return; }
      return;
    }
    if (e.altKey) return;
    const map = { KeyB: "brush", KeyE: "eraser", KeyW: "wand", KeyL: "lasso", KeyM: "rect", KeyC: "island", KeyH: "hand", KeyZ: "zoom" };
    if (map[code]) { e.preventDefault(); setTool(map[code]); return; }
    switch (code) {
      case "KeyX": e.preventDefault(); setTool(st.tool === "brush" ? "eraser" : "brush"); return;
      case "BracketLeft": e.preventDefault(); setBrushSize(st.brush.size - sizeStep()); return;
      case "BracketRight": e.preventDefault(); setBrushSize(st.brush.size + sizeStep()); return;
      case "Digit1": setOverlay("layer"); return;
      case "Digit2": setOverlay("source"); return;
      case "Digit3": setOverlay("blend"); return;
      case "Digit4": setOverlay("diff"); return;
      case "KeyF": e.preventDefault(); fitView(); return;
      case "Equal": case "NumpadAdd": e.preventDefault(); zoomBy(1.25); return;
      case "Minus": case "NumpadSubtract": e.preventDefault(); zoomBy(1 / 1.25); return;
      case "Delete": e.preventDefault(); runOp("erase"); return;
      case "KeyR": e.preventDefault(); runOp("restore"); return;
      case "Escape":
        e.preventDefault();
        if (gest) cancelGesture();
        else if (st.sel.count) deselect();
        else opts.onClose && opts.onClose();
        return;
      default: break;
    }
    if (e.key === "?" || (code === "Slash" && e.shiftKey)) { e.preventDefault(); toggleHelp(); }
  }
  function onKeyUp(e) {
    if (e.code === "Space" && st.space) { st.space = false; stage.classList.remove("is-space"); }
  }
  on(window, "keydown", onKeyDown);
  on(window, "keyup", onKeyUp);
  on(window, "blur", () => { st.space = false; stage.classList.remove("is-space"); if (gest && gest.kind !== "pinch") cancelGesture(); });

  // ---------------------------------------------------------------------------------------- panel state
  function refreshMoveTargets() {
    const keep = st.moveTo;
    moveSel.textContent = "";
    moveSel.append(el("option", { value: "", text: "다른 레이어로…" }));
    for (const l of st.layers || []) {
      if (!l || l.tag === st.tag) continue;
      moveSel.append(el("option", { value: l.tag, text: `${l.label || l.tag}${l.empty ? " (비어 있음)" : ""}` }));
    }
    moveSel.value = [...moveSel.options].some((o) => o.value === keep) ? keep : "";
    st.moveTo = moveSel.value;
  }

  function updateUi() {
    if (disposed) return;
    const has = st.sel.count > 0, free = !st.busy && st.ready;
    const setDis = (sel, v) => { for (const b of panel.querySelectorAll(sel)) b.disabled = !!v; };
    setDis('[data-act="erase"],[data-act="restore"]', !free || !has);
    setDis('[data-act="move"]', !free || !has || !st.moveTo);
    setDis('[data-act="grow"],[data-act="shrink"],[data-act="feather-sel"],[data-act="deselect"]', !free || !has);
    setDis('[data-act="select-all"],[data-act="invert"],[data-act="only-layer"],[data-act="only-source"],[data-act="islands"],[data-act="fill-hole"],[data-act="clean"]', !free);
    moveSel.disabled = !free;
    undoBtn.disabled = st.busy || hist.idx <= 0;
    redoBtn.disabled = st.busy || hist.idx >= hist.entries.length - 1;
    closeBtn.disabled = st.busy;
    const b = st.sel.bbox;
    const sum = has ? `선택 ${b.x1 - b.x0 + 1}×${b.y1 - b.y0 + 1} · ${st.sel.count.toLocaleString("ko-KR")} px` : "선택 없음";
    selSummary.textContent = sum;
    stSel.textContent = sum;
    stLayer.textContent = `${st.label || st.tag} · ${st.grid === "head" ? "머리 격자" : "캔버스 격자"} ${G}²`;
    root.dataset.hasSelection = has ? "1" : "";
  }

  // ---------------------------------------------------------------------------------------- public API
  function getState() {
    return {
      tool: st.tool, overlay: st.overlay, zoom: view.zoom, hasSelection: st.sel.count > 0, dirty: st.sel.count > 0,
      undoDepth: hist.idx, redoDepth: hist.entries.length - 1 - hist.idx,
      // extras
      busy: st.busy, ready: st.ready, loading: st.loading, tag: st.tag, label: st.label, grid: st.grid, rev: st.rev,
      selectionCount: st.sel.count, selectionBBox: st.sel.bbox ? { ...st.sel.bbox } : null, selMode: st.selMode,
      panX: view.x, panY: view.y, stageW, stageH, brush: { ...st.brush }, wand: { ...st.wand },
      layerBBox: layerBBox ? { ...layerBBox } : null, lastWandMs: st.lastWandMs, lastOpMs: st.lastOpMs, ops: st.ops, error: st.error,
      applyFeather: st.applyFeather, moveTo: st.moveTo,
    };
  }

  async function setTag(tag, o = {}) {
    if (disposed) return false;
    if (tag === st.tag && (!o.grid || o.grid === st.grid)) {       // same layer: a refresh that keeps the selection and the view
      if (o.label) { st.label = o.label; updateUi(); }
      if (o.rev !== undefined && Number.isFinite(Number(o.rev))) st.rev = Number(o.rev);
      if (o.layers) { st.layers = o.layers; refreshMoveTargets(); }
      reloadImages({ fit: false });
      return true;
    }
    if (st.busy && pendingOp) await pendingOp;
    if (disposed) return false;
    if (st.sel.count) {
      const ok = await ask("저장하지 않은 선택이 있습니다. 버리고 다른 레이어로 갈까요?", "버리고 이동");
      if (!ok || disposed) return false;
    }
    if (gest) cancelGesture();
    st.tag = tag;
    st.label = o.label || tag;
    if (o.grid) st.grid = o.grid;
    if (o.rev !== undefined && Number.isFinite(Number(o.rev))) st.rev = Number(o.rev);
    if (o.layers) st.layers = o.layers;
    st.moveTo = "";
    st.error = null;
    for (const t of [...toasts.children]) t.remove();
    refreshMoveTargets();
    resetSelectionAndHistory();
    readyPromise = new Promise((r) => { readyResolve = r; });
    needFit = true;
    reloadImages({ fit: true });
    return true;
  }

  function setLayers(layers) { st.layers = layers || []; refreshMoveTargets(); updateUi(); }

  function dispose() {
    if (disposed) return;
    disposed = true;
    if (modalResolve) { const r = modalResolve; modalResolve = null; r(false); }
    for (const fn of cleanups.splice(0)) { try { fn(); } catch { /* ignore */ } }
    if (raf) cancelAnimationFrame(raf);
    ro.disconnect(); mo.disconnect();
    if (mq && mq.removeEventListener) mq.removeEventListener("change", onTheme);
    if (antsUrl) URL.revokeObjectURL(antsUrl);
    antsUrl = null; antsToken++;
    for (const e of hist.entries) if (e.snap) e.snap.cv.width = 0;
    for (const c of [maskCv, scratchCv, tintCv, layerCv, sourceCv, diffCv, antsCv, viewCv, uiCv, miniCv]) { c.width = 0; c.height = 0; }
    layerPx = sourcePx = diffBuf = antsImg = null; islands = null;
    layerA = sourceA = selA = prevA = new Uint8Array(0);
    root.remove();
    if (readyResolve) { readyResolve(); readyResolve = null; }
  }

  // ---------------------------------------------------------------------------------------- boot
  const ro = new ResizeObserver(() => resize());
  ro.observe(stage);
  const onTheme = () => { css = null; invalidate(); };
  const mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
  if (mq && mq.addEventListener) mq.addEventListener("change", onTheme);
  const mo = new MutationObserver(onTheme);
  mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme", "class"] });

  setTool(st.tool);
  setSelMode(st.selMode);
  wandSource.set(st.wand.source); wandMetric.set(st.wand.metric); wandWin.set(String(st.wand.win));
  setOverlay(st.overlay);
  refreshMoveTargets();
  refreshStats();
  updateUi();
  resize();
  reloadImages({ fit: true });

  return {
    setTag, setLayers, dispose,
    reload: (o = {}) => { if (o.rev !== undefined) st.rev = Number(o.rev) || 0; return reloadImages({ fit: !!o.fit }); },
    fit: fitView, zoomTo,
    /** test hook: put the view exactly there (grid pixel g is at stage pixel x + g * zoom) */
    setView: (v = {}) => { if (v.zoom !== undefined) view.zoom = clamp(Number(v.zoom), MIN_ZOOM, MAX_ZOOM); if (v.x !== undefined) view.x = Number(v.x); if (v.y !== undefined) view.y = Number(v.y); applyView(); },
    getMask: () => maskCv,
    getState,
    // more test hooks
    getViewCanvas: () => viewCv,
    getLayerCanvas: () => layerCv,
    getSourceCanvas: () => sourceCv,
    flush,
    whenReady: () => Promise.all([readyPromise, stylesReady]).then(() => undefined),
    gridToClient: (x, y) => toClient(x, y),
    clientToGrid: (x, y) => toGrid(x, y),
  };
}
