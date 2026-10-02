// SPDX-License-Identifier: Apache-2.0
/**
 * img2live puppet viewer: builds the whole UI (canvas, controls, layers, capability report) inside a container.
 *
 *   import { mountViewer } from "./viewer.js";
 *   const viewer = await mountViewer(document.getElementById("app"), { puppetUrl: "/files/<job>/puppet/puppet.json" });
 *
 * Texture URLs are resolved relative to the puppet.json URL (or `baseUrl`).
 */
import { PuppetModel, PuppetController } from "./puppet-runtime.js";
import { GLRenderer, WebGL2Unavailable, BACKGROUNDS } from "./gl-renderer.js";

let mountCounter = 0;

// ------------------------------------------------------------------------------------------ DOM helpers
function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const c of children) if (c !== undefined && c !== null && c !== false) node.append(c);
  return node;
}

function ensureStyles() {
  let link = document.querySelector("link[data-img2live-css]");
  if (!link) {
    link = el("link", { rel: "stylesheet", href: new URL("../css/viewer.css", import.meta.url).href, "data-img2live-css": "" });
    document.head.append(link);
  }
  if (link.sheet) return Promise.resolve();
  return new Promise((resolve) => {
    link.addEventListener("load", resolve, { once: true });
    link.addEventListener("error", resolve, { once: true });
    setTimeout(resolve, 4000);
  });
}

function download(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 15000);
}

const stamp = () => new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");

const PARAM_GROUPS = [
  { id: "head", title: "Head", test: (id) => /^ParamAngle[XYZ]$/.test(id) },
  { id: "eyes", title: "Eyes", test: (id) => /Eye|Brow/.test(id) },
  { id: "mouth", title: "Mouth", test: (id) => /Mouth/.test(id) },
  { id: "body", title: "Body", test: (id) => /Body|Breath/.test(id) },
  { id: "hair", title: "Hair / tail", test: (id) => /Hair|Tail|Skirt|Cloth|Ribbon/.test(id) },
  { id: "other", title: "Other", test: () => true },
];

function classifyCapability(text) {
  const s = String(text);
  if (/^ok\b/i.test(s)) return { level: "ok", label: "OK", detail: s.replace(/^ok\b:?\s*/i, "") };
  if (/^degraded\b/i.test(s)) return { level: "degraded", label: "Degraded", detail: s.replace(/^degraded\b:?\s*/i, "") };
  if (/^unavailable\b/i.test(s)) return { level: "unavailable", label: "Unavailable", detail: s.replace(/^unavailable\b:?\s*/i, "") };
  return { level: "info", label: "", detail: s };
}

/** `puppet.meta.capability` -> card: key + status, degraded/unavailable rows tinted and badged. */
function buildCapabilityCard(model, uid) {
  const cap = model.meta && model.meta.capability;
  const card = el("section", { class: "i2l-card", "aria-labelledby": `${uid}-h-cap` }, el("h2", { id: `${uid}-h-cap`, text: "Capability report" }));
  if (!cap || typeof cap !== "object" || !Object.keys(cap).length) {
    card.append(el("p", { class: "i2l-muted", text: "This puppet carries no capability report." }));
  } else {
    const list = el("ul", { class: "i2l-cap" });
    const counts = { degraded: 0, unavailable: 0 };
    for (const [key, value] of Object.entries(cap)) {
      const c = classifyCapability(value);
      if (c.level in counts) counts[c.level]++;
      const val = el("div", { class: "i2l-cap-val" });
      if (c.label) val.append(el("span", { class: "i2l-badge", "data-level": c.level, text: c.label }));
      val.append(document.createTextNode(c.detail));
      list.append(el("li", { class: "i2l-cap-item", "data-level": c.level }, el("div", { class: "i2l-cap-key", text: key.replace(/_/g, " ") }), val));
    }
    const bits = [];
    if (counts.unavailable) bits.push(`${counts.unavailable} unavailable`);
    if (counts.degraded) bits.push(`${counts.degraded} degraded`);
    card.append(el("p", { class: "i2l-cap-summary", text: bits.length ? `Needs attention: ${bits.join(", ")}.` : "All reported features are fully available." }), list);
  }
  const notes = [];
  if (model.meta && model.meta.ai_generated) notes.push("AI-generated content.");
  if (model.warnings.length) notes.push(`Puppet notes: ${model.warnings.join("; ")}`);
  if (notes.length) card.append(el("p", { class: "i2l-cap-foot", text: notes.join(" ") }));
  return card;
}

const fmt = (v, decimals) => (Math.abs(v) < 0.5 * 10 ** -decimals ? 0 : v).toFixed(decimals);

// ------------------------------------------------------------------------------------------ mountViewer
/**
 * @param {HTMLElement} container
 * @param {{puppetUrl: string, baseUrl?: string, onParams?: (params: Record<string, number>) => void,
 *          showLayers?: boolean,
 *          initial?: {idle?: boolean, blink?: boolean, physics?: boolean, follow?: boolean,
 *                     camera?: 'fit'|'head', background?: string, wireframe?: boolean, seed?: number}}} opts
 */
export async function mountViewer(container, opts = {}) {
  const { puppetUrl, onParams = null, showLayers = true, initial = {} } = opts;
  if (!(container instanceof Element)) throw new TypeError("mountViewer: container must be a DOM element");
  if (!puppetUrl) throw new TypeError("mountViewer: puppetUrl is required");
  const uid = `i2l${++mountCounter}`;

  await ensureStyles();
  const puppetAbs = new URL(puppetUrl, document.baseURI);
  let baseUrl = opts.baseUrl ? new URL(opts.baseUrl, document.baseURI).href : new URL("./", puppetAbs).href;
  if (!baseUrl.endsWith("/")) baseUrl += "/";

  const root = el("div", { class: "i2l-viewer", "data-state": "loading" });
  container.textContent = "";
  container.append(root);
  const fatal = (title, message) => {
    root.dataset.state = "error";
    root.replaceChildren(el("div", { class: "i2l-fatal", role: "alert" }, el("h2", { text: title }), el("p", { text: message })));
  };
  root.append(el("div", { class: "i2l-loading", role: "status", text: "Loading puppet…" }));

  // ---- puppet.json
  let model;
  try {
    const resp = await fetch(puppetAbs.href);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} while fetching ${puppetAbs.href}`);
    model = new PuppetModel(await resp.json());
  } catch (err) {
    fatal("Could not load the puppet", String(err && err.message ? err.message : err));
    throw err;
  }
  const ctrl = new PuppetController(model, {
    seed: initial.seed ?? 1,
    idle: initial.idle,
    blink: initial.blink,
    physics: initial.physics,
    follow: initial.follow ?? false,
  });

  // =========================================================================================== build the UI
  const canvas = el("canvas", {
    class: "i2l-canvas",
    tabindex: "0",
    role: "img",
    "aria-label": "Puppet preview. Drag to pan, scroll to zoom, double-click to reset the view, Space toggles idle motion.",
  });
  const banner = el("div", { class: "i2l-banner", role: "alert", hidden: true });
  const loadingBadge = el("div", { class: "i2l-canvas-note", role: "status", text: "Loading textures…" });
  const hint = el("div", { class: "i2l-hint", text: "Drag: pan · wheel: zoom · double-click: reset · Space: idle on/off" });
  const wrap = el("div", { class: "i2l-canvas-wrap" }, canvas, banner, loadingBadge, hint);

  const btnFit = el("button", { type: "button", class: "i2l-btn", "aria-pressed": "true", text: "Fit" });
  const btnHead = el("button", { type: "button", class: "i2l-btn", "aria-pressed": "false", text: "Head" });
  const bgSelect = el(
    "select",
    { class: "i2l-select", id: `${uid}-bg` },
    ...BACKGROUNDS.map((b) => el("option", { value: b, text: b[0].toUpperCase() + b.slice(1) })),
  );
  const btnPng = el("button", { type: "button", class: "i2l-btn", text: "PNG", title: "Download a PNG of the current view (transparent on the checkerboard)" });
  const btnRec = el("button", { type: "button", class: "i2l-btn i2l-rec", "aria-pressed": "false" }, el("span", { class: "i2l-rec-dot", "aria-hidden": "true" }), el("span", { class: "i2l-rec-label", text: "Record WebM" }));
  const toolbar = el(
    "div",
    { class: "i2l-toolbar", role: "toolbar", "aria-label": "View controls" },
    el("div", { class: "i2l-group", role: "group", "aria-label": "Camera" }, btnFit, btnHead),
    el("div", { class: "i2l-group" }, el("label", { for: `${uid}-bg`, class: "i2l-inline-label", text: "Background" }), bgSelect),
    el("div", { class: "i2l-group", role: "group", "aria-label": "Capture" }, btnPng, btnRec),
  );
  const status = el("div", { class: "i2l-status", role: "status", "aria-live": "off", text: "" });
  const stage = el("section", { class: "i2l-stage", "aria-label": "Preview" }, wrap, toolbar, status);

  // ---- switches
  const switches = {};
  function makeSwitch(key, label, shortcut) {
    const input = el("input", { type: "checkbox", role: "switch", id: `${uid}-sw-${key}`, "aria-keyshortcuts": shortcut || false });
    const row = el(
      "label",
      { class: "i2l-switch", for: input.id },
      input,
      el("span", { class: "i2l-track", "aria-hidden": "true" }),
      el("span", { class: "i2l-switch-label", text: label }),
    );
    if (shortcut) row.title = `${label} (${shortcut})`;
    switches[key] = input;
    return row;
  }
  const btnReset = el("button", { type: "button", class: "i2l-btn", text: "Reset parameters" });
  const motionCard = el(
    "section",
    { class: "i2l-card", "aria-labelledby": `${uid}-h-motion` },
    el("h2", { id: `${uid}-h-motion`, text: "Motion and view" }),
    el(
      "div",
      { class: "i2l-switches" },
      makeSwitch("idle", "Idle motion", "Space"),
      makeSwitch("blink", "Auto blink"),
      makeSwitch("physics", "Physics"),
      makeSwitch("follow", "Mouse follow"),
      makeSwitch("wireframe", "Wireframe"),
    ),
    el("div", { class: "i2l-actions" }, btnReset),
  );

  // ---- parameter sliders
  const sliders = []; // {p, input, output, row, shown}
  const paramsCard = el("section", { class: "i2l-card", "aria-labelledby": `${uid}-h-params` }, el("h2", { id: `${uid}-h-params`, text: "Parameters" }));
  const groups = PARAM_GROUPS.map((g) => ({ ...g, params: [] }));
  for (const p of model.params) groups.find((g) => g.test(p.id)).params.push(p);
  for (const g of groups) {
    if (!g.params.length) continue;
    const body = el("div", { class: "i2l-group-body" });
    for (const p of g.params) {
      const range = p.max - p.min;
      const decimals = range >= 20 ? 1 : 2;
      const input = el("input", {
        type: "range",
        id: `${uid}-p-${p.id}`,
        min: p.min,
        max: p.max,
        step: range / 400,
        value: p.default,
        "data-param": p.id,
      });
      const output = el("output", { for: input.id, class: "i2l-value", text: fmt(p.default, decimals) });
      const tag = p.driven ? el("span", { class: "i2l-chip", text: "physics", title: "Driven by the physics simulation while physics is on" }) : null;
      const row = el(
        "div",
        { class: "i2l-param" + (p.driven ? " is-driven" : "") },
        el("label", { for: input.id, class: "i2l-param-name" }, el("span", { text: p.name }), tag),
        output,
        input,
      );
      body.append(row);
      sliders.push({ p, input, output, row, decimals, shown: NaN });
    }
    paramsCard.append(el("details", { class: "i2l-details", open: true }, el("summary", { text: g.title }), body));
  }

  // ---- layers panel
  const layerRows = [];
  let layersCard = null;
  if (showLayers) {
    const list = el("ul", { class: "i2l-layers" });
    model.meshes.forEach((m, i) => {
      const cb = el("input", { type: "checkbox", checked: true, id: `${uid}-l-${i}` });
      const solo = el("button", { type: "button", class: "i2l-btn i2l-solo", "aria-pressed": "false", text: "Solo", title: `Show only ${m.id}` });
      const tags = [];
      if (m.clip) tags.push(el("span", { class: "i2l-chip", text: `clip: ${m.clip}`, title: "Only drawn where this mesh has alpha > 0.5" }));
      if (m.opacityBind) tags.push(el("span", { class: "i2l-chip", text: "opacity bind", title: `Opacity follows ${m.opacityBind.param}` }));
      const errChip = el("span", { class: "i2l-chip is-bad", text: "texture failed", hidden: true });
      const li = el(
        "li",
        { class: "i2l-layer" },
        el("label", { for: cb.id, class: "i2l-layer-main" }, cb, el("span", { class: "i2l-layer-name", text: m.id }), el("span", { class: "i2l-layer-order", text: String(m.order), title: "Draw order (low = behind)" })),
        el("div", { class: "i2l-layer-meta" }, ...tags, errChip),
        solo,
      );
      list.append(li);
      layerRows.push({ cb, solo, li, errChip });
      cb.addEventListener("change", () => renderer && renderer.setMeshVisible(i, cb.checked));
      solo.addEventListener("click", () => setSolo(renderer.solo === i ? null : i));
    });
    const showAll = el("button", { type: "button", class: "i2l-btn", text: "Show all" });
    const hideAll = el("button", { type: "button", class: "i2l-btn", text: "Hide all" });
    showAll.addEventListener("click", () => {
      setSolo(null);
      model.meshes.forEach((_, i) => setLayerVisible(i, true));
    });
    hideAll.addEventListener("click", () => model.meshes.forEach((_, i) => setLayerVisible(i, false)));
    layersCard = el(
      "section",
      { class: "i2l-card", "aria-labelledby": `${uid}-h-layers` },
      el("details", { class: "i2l-details", open: true }, el("summary", { id: `${uid}-h-layers`, class: "i2l-h2", text: `Layers (${model.meshes.length})` }),
        el("p", { class: "i2l-muted", text: "Draw order, back to front. Untick to hide, Solo to isolate." }),
        el("div", { class: "i2l-actions" }, showAll, hideAll),
        list),
    );
  }

  // ---- capability report
  const capCard = buildCapabilityCard(model, uid);

  const panel = el("aside", { class: "i2l-panel", "aria-label": "Controls" }, motionCard, paramsCard, layersCard, capCard);

  root.replaceChildren(stage, panel);
  root.dataset.state = "ready";

  // =========================================================================================== renderer
  let renderer = null;
  const showBanner = (text, level = "bad") => {
    banner.hidden = !text;
    banner.dataset.level = level;
    banner.textContent = text || "";
  };
  try {
    renderer = new GLRenderer(canvas, model, {
      baseUrl,
      onEvent: (type, detail) => {
        if (type === "contextlost") showBanner("The graphics context was lost. Waiting for the browser to restore it…", "warn");
        else if (type === "contextrestored") showBanner("");
        else if (type === "textureerror") updateTextureBanner();
        else if (type === "error") showBanner(`Renderer error: ${detail && detail.message ? detail.message : detail}`);
      },
    });
  } catch (err) {
    const msg =
      err instanceof WebGL2Unavailable
        ? "This viewer needs WebGL2, which is not available in this browser (or it is disabled). Try a current Chrome, Edge, Firefox or Safari with hardware acceleration enabled."
        : `Could not start the renderer: ${err && err.message ? err.message : err}`;
    fatal("Cannot draw the puppet", msg);
    throw err;
  }
  renderer.attachControls();
  const fit = () => renderer.resize(wrap.clientWidth || 1, wrap.clientHeight || 1);
  const ro = new ResizeObserver(fit);
  ro.observe(wrap);
  fit();

  function updateTextureBanner() {
    const errs = renderer.textureErrors;
    for (let i = 0; i < layerRows.length; i++) {
      const g = renderer.g[i];
      layerRows[i].errChip.hidden = !g.error;
      layerRows[i].errChip.title = g.error || "";
    }
    if (errs.length) {
      const names = errs.map((e) => e.id).join(", ");
      showBanner(`${errs.length} texture${errs.length > 1 ? "s" : ""} failed to load (${names}). Affected layers are drawn as a magenta checker. ${errs[0].error}`);
    } else showBanner("");
  }

  // =========================================================================================== state helpers
  function syncSwitches() {
    switches.idle.checked = ctrl.options.idle;
    switches.blink.checked = ctrl.options.blink;
    switches.physics.checked = ctrl.options.physics;
    switches.follow.checked = ctrl.options.follow;
    switches.wireframe.checked = renderer.wireframe;
    for (const s of sliders) {
      const disable = s.p.driven && ctrl.options.physics;
      s.input.disabled = disable;
      s.row.classList.toggle("is-locked", disable);
    }
    // nothing to blink / idle / simulate: grey the switch out
    switches.idle.disabled = !ctrl.idle.hasIdle && !ctrl.idle.hasSaccade;
    switches.blink.disabled = !ctrl.idle.hasBlink;
    switches.physics.disabled = ctrl.physics.items.length === 0;
  }

  function setOption(name, on) {
    if (name === "wireframe") renderer.setWireframe(on);
    else {
      ctrl.setOption(name, on);
      if (name === "follow" && !on) ctrl.setFollow(null);
    }
    syncSwitches();
  }
  function getOption(name) {
    return name === "wireframe" ? renderer.wireframe : ctrl.options[name];
  }
  for (const key of Object.keys(switches)) switches[key].addEventListener("change", () => setOption(key, switches[key].checked));

  function setCamera(mode) {
    renderer.setCamera(mode);
  }
  function syncCameraButtons() {
    shownCamera = renderer.cameraMode;
    btnFit.setAttribute("aria-pressed", String(renderer.cameraMode === "fit"));
    btnHead.setAttribute("aria-pressed", String(renderer.cameraMode === "head"));
  }
  btnFit.addEventListener("click", () => setCamera("fit"));
  btnHead.addEventListener("click", () => setCamera("head"));

  function setBackground(mode) {
    renderer.setBackground(mode);
    bgSelect.value = mode;
  }
  bgSelect.addEventListener("change", () => setBackground(bgSelect.value));

  function setLayerVisible(i, on) {
    if (typeof i === "string") i = model.meshIndex.get(i);
    if (i === undefined) return;
    renderer.setMeshVisible(i, on);
    if (layerRows[i]) layerRows[i].cb.checked = !!on;
  }
  function setSolo(i) {
    if (typeof i === "string") i = model.meshIndex.get(i);
    renderer.setSolo(i == null ? null : i);
    layerRows.forEach((r, k) => {
      const on = renderer.solo === k;
      r.solo.setAttribute("aria-pressed", String(on));
      r.li.classList.toggle("is-dimmed", renderer.solo >= 0 && !on);
    });
  }

  // sliders -> controller
  const dragging = new Set();
  for (const s of sliders) {
    const id = s.p.id;
    s.input.addEventListener("pointerdown", () => {
      dragging.add(id);
      ctrl.holdParam(id, true);
    });
    const release = () => {
      if (dragging.delete(id)) ctrl.holdParam(id, false);
    };
    s.input.addEventListener("pointerup", release);
    s.input.addEventListener("pointercancel", release);
    s.input.addEventListener("blur", release);
    s.input.addEventListener("input", () => {
      const v = parseFloat(s.input.value);
      ctrl.setParam(id, v, { user: true });
      s.output.textContent = fmt(v, s.decimals);
      s.shown = v;
    });
  }
  btnReset.addEventListener("click", () => resetParams());

  function resetParams() {
    ctrl.reset();
    ctrl.setFollow(null);
    syncSliders(true);
  }

  // mouse follow
  const headCss = { x: 0, y: 0 };
  canvas.addEventListener("pointermove", (e) => {
    if (!ctrl.options.follow || renderer.dragging || e.pointerType === "touch") return;
    const r = canvas.getBoundingClientRect();
    const hb = model.headBounds;
    renderer.worldToCss((hb[0] + hb[2]) / 2, (hb[1] + hb[3]) / 2, headCss);
    const nx = (e.clientX - r.left - headCss.x) / (r.width * 0.4);
    const ny = (e.clientY - r.top - headCss.y) / (r.height * 0.4);
    ctrl.setFollow(nx, ny);
  });
  canvas.addEventListener("pointerleave", () => ctrl.setFollow(null));
  canvas.addEventListener("pointerdown", () => ctrl.setFollow(null));

  // keyboard: space toggles idle motion
  const onKey = (e) => {
    if (e.code !== "Space" || e.repeat || e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t instanceof Element) {
      if (t.closest("button, a, select, textarea, summary, input:not([type=range])")) return;
      if (t !== document.body && t !== document.documentElement && !root.contains(t)) return;
    }
    if (switches.idle.disabled) return;
    e.preventDefault();
    setOption("idle", !ctrl.options.idle);
  };
  document.addEventListener("keydown", onKey);

  // =========================================================================================== recording
  let rec = null;
  let recChunks = [];
  let recStream = null;
  let recStart = 0;
  let recording = false;
  function pickMime() {
    const cands = ["video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"];
    return cands.find((t) => MediaRecorder.isTypeSupported(t)) || "";
  }
  function startRecording() {
    if (recording) return;
    if (typeof MediaRecorder === "undefined" || !canvas.captureStream) throw new Error("Recording is not supported in this browser (MediaRecorder / captureStream missing)");
    const mimeType = pickMime();
    recStream = canvas.captureStream(60);
    recChunks = [];
    rec = new MediaRecorder(recStream, mimeType ? { mimeType, videoBitsPerSecond: 8_000_000 } : undefined);
    rec.ondataavailable = (e) => {
      if (e.data && e.data.size) recChunks.push(e.data);
    };
    rec.start(250);
    recStart = performance.now();
    recording = true;
    renderer.dirty = true;
    syncRecButton();
  }
  function stopRecording() {
    if (!recording || !rec) return Promise.reject(new Error("not recording"));
    const r = rec;
    const stream = recStream;
    return new Promise((resolve, reject) => {
      r.onerror = (e) => reject(e.error || new Error("MediaRecorder error"));
      r.onstop = () => {
        const blob = new Blob(recChunks, { type: r.mimeType || "video/webm" });
        stream.getTracks().forEach((t) => t.stop());
        resolve(blob);
      };
      recording = false;
      rec = null;
      recStream = null;
      syncRecButton();
      try {
        r.requestData();
      } catch {
        /* inactive recorder */
      }
      r.stop();
    });
  }
  function syncRecButton() {
    btnRec.setAttribute("aria-pressed", String(recording));
    btnRec.querySelector(".i2l-rec-label").textContent = recording ? "Stop 0:00" : "Record WebM";
  }
  btnRec.addEventListener("click", async () => {
    try {
      if (!recording) startRecording();
      else download(await stopRecording(), `img2live-${stamp()}.webm`);
    } catch (err) {
      showBanner(String(err && err.message ? err.message : err), "warn");
      recording = false;
      syncRecButton();
    }
  });
  btnPng.addEventListener("click", async () => {
    try {
      download(await snapshotPNG(), `img2live-${stamp()}.png`);
    } catch (err) {
      showBanner(`Snapshot failed: ${err && err.message ? err.message : err}`, "warn");
    }
  });
  if (typeof MediaRecorder === "undefined" || !canvas.captureStream) {
    btnRec.disabled = true;
    btnRec.title = "This browser cannot record the canvas (MediaRecorder/captureStream missing)";
  }
  const snapshotPNG = () => renderer.snapshotBlob();

  // =========================================================================================== main loop
  const n = model.params.length;
  const renderedVals = new Float64Array(n).fill(NaN);
  let raf = 0;
  let destroyed = false;
  let last = performance.now();
  let fpsFrames = 0;
  let fpsT = last;
  let fps = 0;
  let uiT = 0;
  let cbT = 0;
  let statusT = 0;
  let shownCamera = "";

  function syncSliders(force) {
    const vals = ctrl.values;
    for (let i = 0; i < sliders.length; i++) {
      const s = sliders[i];
      if (dragging.has(s.p.id)) continue;
      const v = vals[s.p.index];
      if (force || Math.abs(v - s.shown) > 1e-4 || s.shown !== s.shown) {
        s.shown = v;
        s.input.value = v;
        s.output.textContent = fmt(v, s.decimals);
      }
    }
  }

  function updateStatus() {
    const st = renderer.stats;
    const z = renderer.camera.zoom;
    const rec = recording ? `  ·  REC ${((performance.now() - recStart) / 1000).toFixed(0)}s` : "";
    status.textContent =
      `${fps.toFixed(0)} fps  ·  ${model.meshes.length} meshes  ·  ${model.vertexCount.toLocaleString("en-US")} vertices  ·  ` +
      `${model.triangleCount.toLocaleString("en-US")} triangles  ·  ${st.drawCalls} draws  ·  zoom ${z.toFixed(2)}x${rec}`;
    if (recording) {
      const secs = Math.floor((performance.now() - recStart) / 1000);
      btnRec.querySelector(".i2l-rec-label").textContent = `Stop ${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
    }
  }

  function frame(now) {
    if (destroyed) return;
    raf = requestAnimationFrame(frame);
    const dt = (now - last) / 1000;
    last = now;
    fpsFrames++;
    if (now - fpsT >= 500) {
      fps = (fpsFrames * 1000) / (now - fpsT);
      fpsFrames = 0;
      fpsT = now;
    }
    const vals = ctrl.step(dt);
    let changed = renderer.dirty || recording;
    for (let i = 0; i < n; i++) {
      if (vals[i] !== renderedVals[i]) {
        renderedVals[i] = vals[i];
        changed = true;
      }
    }
    if (changed) renderer.render(vals);
    if (now - uiT > 33) {
      uiT = now;
      syncSliders(false);
    }
    if (now - statusT > 500) {
      statusT = now;
      updateStatus();
    }
    if (onParams && now - cbT > 50) {
      cbT = now;
      try {
        onParams(ctrl.getParams());
      } catch (e) {
        console.error(e);
      }
    }
    if (renderer.cameraMode !== shownCamera) syncCameraButtons();
  }

  // =========================================================================================== start
  syncSwitches();
  syncSliders(true);
  if (initial.background) setBackground(initial.background);
  if (initial.wireframe) setOption("wireframe", true);
  setCamera(initial.camera || "fit");
  syncCameraButtons();

  await renderer.loadTextures((done, total) => {
    loadingBadge.textContent = `Loading textures ${done}/${total}…`;
  });
  loadingBadge.hidden = true;
  updateTextureBanner();
  renderer.render(ctrl.values);
  last = performance.now();
  raf = requestAnimationFrame(frame);
  updateStatus();

  // =========================================================================================== public controller
  function destroy() {
    if (destroyed) return;
    destroyed = true;
    cancelAnimationFrame(raf);
    ro.disconnect();
    document.removeEventListener("keydown", onKey);
    if (recording && rec) {
      try {
        rec.stop();
      } catch {
        /* ignore */
      }
      recStream && recStream.getTracks().forEach((t) => t.stop());
    }
    renderer.dispose();
    root.remove();
  }

  return {
    /** Set a parameter (as the user would: pauses idle motion on it briefly). */
    setParam(id, v, o) {
      const ok = ctrl.setParam(id, v, o);
      return ok;
    },
    /** Final parameter values {id: value} (user + idle + blink + physics). */
    getParams: () => ctrl.getParams(),
    resetParams,
    setCamera,
    snapshotPNG,
    startRecording,
    stopRecording,
    destroy,
    // ---- extras (used by tests and tools)
    setOption,
    getOption,
    setBackground,
    setLayerVisible,
    setSolo,
    get recording() {
      return recording;
    },
    model,
    controller: ctrl,
    renderer,
    root,
  };
}
