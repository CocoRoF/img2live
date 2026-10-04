// SPDX-License-Identifier: Apache-2.0
// /j/<id>: the progress view while the job runs, the studio once it is done.
//
//   studio  =  [layer panel | stage | inspector]  filling the whole width and the height under the header (plan/08-studio.md §2)
//   modules =  stage.js (engine) · layer-panel.js · inspector.js · layer-editor.js (lazy) · studio-api.js (REST)
//
// Test switches (harmless in production): ?idle=0&blink=0&physics=0&follow=0|1&bg=checker|white|dark|green&camera=fit|head&wire=1&seed=N,
// and ?test=1 exposes window.__studio for the browser tests.
import { mine } from "./mine.js";
import { el, icon, store, labelOf, groupOf, downloadBlob, stamp, fmtClock } from "./studio-util.js";

const $ = (id) => document.getElementById(id);
const jobId = location.pathname.split("/").filter(Boolean).pop();
const F = (p) => `/files/${jobId}/${p}`;
const Q = new URLSearchParams(location.search);
const TEST = Q.get("test") === "1";
const STAGES = [["queued", "대기"], ["decompose", "레이어 분해(GPU)"], ["layers", "레이어 저장"], ["rig", "리깅·QA"], ["package", "패키징"], ["done", "완료"]];
const fmtT = (s) => (s == null ? "-" : s >= 90 ? `${Math.round(s / 60)}분` : `${Math.round(s)}초`);
const UI_KEY = "i2l_studio_ui_v1";

let es = null;
let current = null; // last public job json
let studioStarted = false;

// ================================================================================================ toasts
function toast(message, kind = "info", ms) {
  const box = $("toasts");
  const t = el("div", { class: `st-toast ${kind}`, text: message });
  box.append(t);
  while (box.children.length > 4) box.firstChild.remove();
  setTimeout(() => t.remove(), ms ?? (kind === "bad" ? 8000 : 4500));
}

// ================================================================================================ views
function show(view) {
  const studio = view === "studio";
  $("vStatus").hidden = studio;
  $("result").hidden = !studio;
  $("siteFooter").hidden = studio;
  document.body.classList.toggle("is-studio", studio);
}

function gone(text = "삭제되었거나 만료된 작업입니다") {
  show("status");
  $("title").textContent = text;
  $("badge").textContent = "없음";
  $("badge").className = "pill";
  $("pbar").hidden = true;
  $("stepper").replaceChildren();
  $("msg").textContent = "";
  $("qinfo").textContent = "작업은 1년이 지나거나 직접 삭제하면 사라집니다.";
  $("statusActions").hidden = false;
  $("srcCard").hidden = true;
  document.title = "img2live — 작업 없음";
  mine.remove(jobId);
}

function render(j) {
  current = j;
  const map = { queued: ["대기 중", ""], running: ["처리 중", "warn"], done: ["완료", "ok"], failed: ["실패", "bad"] };
  const [t, cls] = map[j.status] || [j.status, ""];
  if (j.status === "done") {
    if (!studioStarted) { studioStarted = true; startStudio(j); }
    return;
  }
  show("status");
  $("badge").textContent = t;
  $("badge").className = "pill " + cls;
  $("title").textContent = j.status === "failed" ? "처리하지 못했습니다" : "퍼펫을 만드는 중…";
  $("pbar").hidden = false;
  const pct = Math.round((j.progress || 0) * 100);
  $("pfill").style.width = pct + "%";
  $("pbar").setAttribute("aria-valuenow", pct);
  const idx = Math.max(0, STAGES.findIndex(([k]) => k === j.stage));
  $("stepper").innerHTML = STAGES.map(([k, label], i) => `<span class="s ${i < idx ? "done" : i === idx ? "on" : ""}">${label}</span>`).join("");
  $("msg").textContent = j.status === "running" ? `${pct}% · ${j.message || ""}` : j.message && j.status !== "failed" ? j.message : "";
  const e = $("err");
  e.hidden = !j.error;
  e.textContent = j.error || "";
  $("statusActions").hidden = j.status !== "failed";
  if (j.status === "queued" || j.status === "running") {
    const parts = [];
    if (j.status === "queued") parts.push(`대기열 ${j.queue_position + 1}번째`);
    if (j.eta_seconds != null) parts.push(`예상 남은 시간 ${fmtT(j.eta_seconds)}`);
    parts.push("이 페이지를 닫아도 작업은 계속되며, 같은 주소로 다시 열 수 있습니다.");
    $("qinfo").textContent = parts.join(" · ");
  } else $("qinfo").textContent = "";
  // the uploaded image next to the progress (uses the empty space of a wide screen)
  const sc = $("srcCard");
  if (j.status === "queued" || j.status === "running") {
    if (sc.hidden) { sc.hidden = false; $("srcImg").src = F("source.png"); $("srcImg").addEventListener("error", () => { sc.hidden = true; }, { once: true }); }
    $("srcPrompt").textContent = j.prompt ? `프롬프트: ${j.prompt}` : "프롬프트 없음";
    $("vStatus").classList.toggle("has-source", !sc.hidden);
  } else { sc.hidden = true; $("vStatus").classList.remove("has-source"); }
  document.title = j.status === "failed" ? "img2live — 실패" : `img2live — 만드는 중 ${pct}%`;
}

function connect() {
  es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (m) => { render(JSON.parse(m.data)); };
  es.addEventListener("gone", () => { es.close(); gone(); });
  es.onerror = () => {
    if (current && (current.status === "done" || current.status === "failed")) { es.close(); return; }
    es.close();
    setTimeout(poll, 2000); // fall back to polling when SSE drops
  };
}
async function poll() {
  try {
    const r = await fetch(`/api/jobs/${jobId}`);
    if (r.status === 404) { gone(); return; }
    const j = await r.json();
    render(j);
    if (j.status === "queued" || j.status === "running") setTimeout(poll, 2500);
  } catch { setTimeout(poll, 4000); }
}

// ================================================================================================ studio
const ALIAS = { mouth_overlay: "mouth" }; // meshes that are not layers of their own

async function startStudio(job) {
  show("studio");
  document.title = "img2live — 퍼펫 스튜디오";
  const R = job.result || {};
  const root = $("result");
  let mods;
  try {
    const [stageMod, panelMod, inspMod, apiMod] = await Promise.all([import("./stage.js"), import("./layer-panel.js"), import("./inspector.js"), import("./studio-api.js")]);
    mods = { ...stageMod, ...panelMod, ...inspMod, ...apiMod };
  } catch (err) {
    console.error(err);
    show("status");
    $("title").textContent = "스튜디오를 불러오지 못했습니다";
    $("err").hidden = false;
    $("err").textContent = String(err && err.message ? err.message : err);
    return;
  }
  const api = mods.studioApi(jobId);

  // ---- state: the studio endpoint, or (backend not deployed yet) a read-only list derived from layers/index.json
  let state = null;
  let degraded = false;
  try {
    state = await api.state();
  } catch (e) {
    degraded = true;
    console.info("studio endpoint unavailable, read-only mode:", e && e.message);
    try { state = await degradedState(job); } catch (err) { toast(`레이어 정보를 불러오지 못했습니다: ${err.message || err}`, "bad"); state = { rev: 0, puppet: F(R.puppet), canvas: 1280, layers: [], tasks: [], can_regen: false }; }
  }

  // ---- UI chrome (panels, drawers, toolbar)
  const ui = { left: true, right: true, leftW: 300, rightW: 360, ...(store.get(UI_KEY) || {}) };
  const mq = matchMedia("(max-width: 999px)");
  const narrow = () => mq.matches;
  let stage = null, panel = null, inspector = null;
  let selected = null;
  let editorHandle = null, editorTag = null;
  let applyChain = Promise.resolve();
  let editorRev = null; // the revision the open editor has loaded
  let apiBusy = false, reloading = false; // the "puppet is being rebuilt" chip
  let pollTimer = 0;
  const seenActive = new Map(); // task id -> last known task (to toast when one finishes)
  const toolbarEls = {};
  let reportCache = null;

  // ---- layer panel
  panel = mods.createLayerPanel($("layerPanel"), {
    thumbUrl: (layer, rev) => (degraded ? (layer.file ? F(layer.file) : null) : api.layerThumbUrl(layer.tag, "current", rev)),
    onSelect: (tag) => select(tag, { from: "panel" }),
    onVisible: (tag, vis) => stage && stage.setVisible(tag, vis),
    onSolo: (tag) => stage && stage.setSolo(tag),
    onShowAll: () => stage && stage.showAll(),
    onHideAll: () => stage && stage.hideAll(),
  });

  // ---- stage
  const initial = {
    idle: flag("idle"), blink: flag("blink"), physics: flag("physics"), follow: flag("follow"),
    background: Q.get("bg") || undefined, camera: Q.get("camera") || undefined, wireframe: Q.get("wire") === "1",
    seed: Q.has("seed") ? Number(Q.get("seed")) : undefined,
  };
  stage = mods.createStage($("stageMount"), {
    puppetUrl: state.puppet,
    initial,
    insets: { top: 64 }, // the floating toolbar
    onPick: (tag) => select(tag && !layerOf(tag) ? ALIAS[tag] || null : tag, { from: "stage" }),
    onError: (err) => console.error("stage:", err),
  });
  stage.on("busy", (on) => { reloading = on && stage.loaded; syncBusy(); });
  stage.on("hover", updateChip);
  stage.on("warn", (m) => toast(m, "bad"));

  // ---- inspector
  const reportPromise = () => (reportCache ||= fetch(F(R.report)).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }));
  inspector = mods.createInspector($("inspector"), {
    stage, api: degraded ? null : api, job, fileUrl: F, loadReport: reportPromise, notify: toast,
    onState: (s) => applyState(s),
    onEdit: (tag) => openEditor(tag),
    refreshState: async () => { try { await applyState(await api.state()); } catch (e) { console.warn(e); } },
    deleteJob,
    onBusy: (on) => { apiBusy = on; syncBusy(); },
  });
  inspector.setDegraded(degraded);
  if (degraded) toast("편집 기능 준비 중입니다. 지금은 레이어를 보고·숨기고·강조할 수 있습니다.", "info", 6000);

  // ---- toolbar
  buildToolbar();
  buildPanels();

  applyState(state, { initial: true });

  function flag(k) { return Q.has(k) ? Q.get(k) !== "0" : undefined; }
  function syncBusy() {
    $("stBusy").hidden = !(apiBusy || reloading);
    $("stBusyText").textContent = apiBusy ? "퍼펫을 다시 만드는 중…" : "퍼펫 갱신 중…";
  }
  function layerOf(tag) { return state && state.layers ? state.layers.find((l) => l.tag === tag) : null; }

  // ================================================================ state application
  /** Take a new studio state: refresh the panels, and when the puppet changed reload the stage (slider values are kept). */
  function applyState(next, { initial: first = false } = {}) {
    applyChain = applyChain.then(async () => {
      if (!first && state && next.rev < state.rev) return; // a slower, older response
      const prev = state;
      state = next;
      panel.setLayers(next.layers, { rev: next.rev, groups: next.groups });
      inspector.setState(next);
      if (selected && !layerOf(selected)) select(null, { from: "state" });
      syncEditor(next);
      noteTasks(prev, next);
      pollTasks();
      if (!first && prev && (next.rev !== prev.rev || next.puppet !== prev.puppet)) {
        let url = next.puppet;
        if (url === stage.url) url += (url.includes("?") ? "&" : "?") + `r=${next.rev}`;
        try { await stage.reload(url, { keepParams: true }); }
        catch (err) { toast(`퍼펫을 다시 불러오지 못했습니다: ${err.message || err}`, "bad"); }
        if (selected) stage.highlight(selected);
      }
    }).catch((err) => console.error(err));
    return applyChain;
  }

  // ---- background tasks (regen): poll the state every 2 s while one is queued or running
  function noteTasks(prev, next) {
    const act = (t) => ["queued", "running"].includes(String(t.status));
    const now = new Map((next.tasks || []).map((t) => [t.id ?? JSON.stringify(t.tags), t]));
    for (const [id, old] of seenActive) {
      const t = now.get(id);
      if (!t || !act(t)) {
        if (t && String(t.status) === "failed") toast(`다시 생성에 실패했습니다${t.error ? `: ${t.error}` : ""}`, "bad");
        else toast("다시 생성이 끝났습니다. 레이어의 버전 목록에서 후보를 확인하세요.", "ok", 7000);
        seenActive.delete(id);
      }
    }
    for (const [id, t] of now) if (act(t)) seenActive.set(id, t);
  }
  function pollTasks() {
    const active = (state.tasks || []).some((t) => ["queued", "running"].includes(String(t.status)));
    if (active && !pollTimer) {
      pollTimer = setInterval(async () => {
        try { await applyState(await api.state()); } catch (e) { /* keep polling */ }
      }, 2000);
    } else if (!active && pollTimer) { clearInterval(pollTimer); pollTimer = 0; }
  }

  // ================================================================ selection
  function select(tag, { from = "ui" } = {}) {
    if (tag && !layerOf(tag)) tag = null;
    if (editorTag && !tag && from !== "editor") return; // while a layer is being edited the selection stays on it
    selected = tag || null;
    panel.select(selected, { scroll: true });
    inspector.setSelected(selected, { openTab: !!selected && from !== "state" });
    stage.highlight(selected);
    updateChip();
    if (editorTag && selected && selected !== editorTag) {
      if (editorHandle) retargetEditor(selected);
      else editorTag = selected; // the editor module is still loading: it mounts on the newest choice
    }
    if (narrow() && selected && from === "panel") setDrawer("none"); // the drawer would hide the highlight
    if (narrow() && selected && from === "stage") { /* stay on the stage; the toolbar button opens the inspector */ }
  }

  function updateChip() {
    const chip = $("stChip");
    const l = selected ? layerOf(selected) : null;
    const hov = stage.hovered && stage.hovered !== selected ? (layerOf(stage.hovered) || layerOf(ALIAS[stage.hovered]) || null) : null;
    if (!l && !hov) { chip.hidden = true; chip.replaceChildren(); return; }
    chip.hidden = false;
    const kids = [];
    if (l) {
      const x = el("button", { type: "button", class: "st-chip-x", "aria-label": "선택 해제", title: "선택 해제 (Esc)" }, icon("close", 12));
      x.addEventListener("click", () => select(null));
      kids.push(el("span", { class: "st-dot", "aria-hidden": "true" }), el("b", { text: l.label || labelOf(l.tag) }), el("code", { text: l.tag }), x);
    }
    if (hov) kids.push(el("span", { class: "st-chip-hover", text: `${l ? "· " : ""}가리키는 중: ${hov.label || labelOf(hov.tag)}` }));
    chip.replaceChildren(...kids);
  }

  // ================================================================ layer editor (layer-editor.js is loaded lazily)
  /** The user picked another layer while the editor is open: the editor may ask to discard its selection first (returns false). */
  async function retargetEditor(tag) {
    const prev = editorTag, l = layerOf(tag);
    try {
      const ok = await editorHandle.setTag(tag, { label: l.label || labelOf(tag), grid: l.grid, rev: state.rev, layers: state.layers });
      if (ok === false) { select(prev, { from: "editor" }); return; }
    } catch (e) { console.warn(e); }
    editorTag = tag;
    editorRev = state.rev;
    $("editorTitle").textContent = `레이어 편집 — ${l.label || labelOf(tag)}`;
  }
  /** A new state arrived while the editor is open (from the editor itself or from the inspector). */
  function syncEditor(next) {
    if (!editorHandle || !editorTag) return;
    const l = next.layers.find((x) => x.tag === editorTag);
    if (!l) { closeEditor(); toast("편집하던 레이어가 없어져 편집기를 닫았습니다.", "bad"); return; }
    try {
      if (next.rev !== editorRev || !editorHandle.setLayers) { // changed elsewhere: reload the layer image (same layer: keeps the selection and the view)
        editorRev = next.rev;
        editorHandle.setTag(editorTag, { label: l.label || labelOf(editorTag), grid: l.grid, rev: next.rev, layers: next.layers });
      } else editorHandle.setLayers(next.layers); // the editor refreshed its own images after its edit; only the layer list changed
    } catch (e) { console.warn(e); }
  }

  async function openEditor(tag) {
    const l = layerOf(tag);
    if (!l || degraded) return;
    if (editorTag) { if (tag !== editorTag) select(tag, { from: "ui" }); return; } // already open (or loading): never mount twice
    editorTag = tag;
    $("stCenter").dataset.mode = "editor";
    $("editorBox").hidden = false;
    $("stageBox").hidden = true;
    $("stToolbar").hidden = true;
    $("stChip").hidden = true;
    stage.pause();
    const label = l.label || labelOf(tag);
    $("editorTitle").textContent = `레이어 편집 — ${label}`;
    const back = $("editorBack");
    back.replaceChildren(icon("arrowLeft", 14), " 퍼펫으로 돌아가기");
    back.onclick = () => closeEditor();
    const host = $("editorMount");
    host.replaceChildren(el("p", { class: "st-editor-note muted", role: "status", text: "편집기를 불러오는 중…" }));
    try {
      const mod = await import("./layer-editor.js");
      if ($("editorBox").hidden || !editorTag) return; // closed while loading
      const cur = layerOf(editorTag) || l;
      host.replaceChildren();
      editorRev = state.rev;
      editorHandle = await mod.mountLayerEditor(host, {
        api, tag: cur.tag, label: cur.label || labelOf(cur.tag), grid: cur.grid, rev: state.rev,
        get layers() { return state.layers; },
        onApplied: async (s) => { editorRev = s.rev; await applyState(s); }, // the editor reloads its own images; syncEditor refreshes its layer list
        onClose: () => closeEditor(),
      });
    } catch (err) {
      console.warn("layer editor unavailable:", err);
      host.replaceChildren(el("div", { class: "notice st-editor-note" }, icon("info", 16), " 레이어 편집기를 불러오지 못했습니다. 아직 준비 중일 수 있습니다. 위의 [퍼펫으로 돌아가기]로 돌아가세요."));
    }
  }
  function closeEditor() {
    if (editorHandle && editorHandle.dispose) { try { editorHandle.dispose(); } catch (e) { console.warn(e); } }
    editorHandle = null;
    editorTag = null;
    editorRev = null;
    $("editorBox").hidden = true;
    $("editorMount").replaceChildren();
    $("stageBox").hidden = false;
    $("stToolbar").hidden = false;
    $("stCenter").dataset.mode = "stage";
    stage.resume();
    updateChip();
  }

  // ================================================================ toolbar
  function buildToolbar() {
    const bar = $("stToolbar");
    const tool = (key, ic, label, onClick, extra = {}) => {
      const b = el("button", { type: "button", class: "st-tool", "aria-label": label, title: label, "data-tool": key, ...extra }, icon(ic, 18));
      b.addEventListener("click", onClick);
      toolbarEls[key] = b;
      return b;
    };
    const bgBox = el("div", { class: "st-group", role: "radiogroup", "aria-label": "배경" });
    const BG = { checker: "체크무늬", white: "흰색", dark: "어둡게", green: "초록(크로마)" };
    for (const mode of stage.backgrounds) {
      const b = el("button", { type: "button", class: "st-bg", role: "radio", "aria-checked": "false", "aria-label": `배경 ${BG[mode]}`, title: `배경: ${BG[mode]}`, "data-bg": mode }, el("span", { class: `in-swatch bg-${mode}`, "aria-hidden": "true" }));
      b.addEventListener("click", () => stage.setBackground(mode));
      toolbarEls["bg-" + mode] = b;
      bgBox.append(b);
    }
    bar.append(
      tool("left", "panelLeft", "레이어 패널 열기·닫기", () => togglePanel("left"), { "aria-controls": "stLeft", "aria-expanded": "true" }),
      el("span", { class: "st-sep", "aria-hidden": "true" }),
      bgBox,
      el("span", { class: "st-sep", "aria-hidden": "true" }),
      tool("fit", "fit", "화면에 맞춤 (더블클릭)", () => stage.setCamera("fit")),
      tool("head", "head", "머리 확대", () => stage.setCamera("head")),
      tool("wire", "grid", "와이어프레임", () => stage.option("wireframe", !stage.option("wireframe")), { "aria-pressed": "false" }),
      tool("idle", "pause", "대기 동작 일시정지", () => stage.option("idle", !stage.option("idle"))),
      tool("snap", "camera", "PNG로 저장", async () => {
        try { downloadBlob(await stage.snapshot(), `img2live-${stamp()}.png`); }
        catch (e) { toast(`스냅샷에 실패했습니다: ${e.message || e}`, "bad"); }
      }),
      tool("rec", "record", "WebM으로 녹화 시작", () => recToggle(), { "aria-pressed": "false" }),
      el("span", { class: "st-sep", "aria-hidden": "true" }),
      tool("right", "panelRight", "검사기 열기·닫기", () => togglePanel("right"), { "aria-controls": "stRight", "aria-expanded": "true" }));
    // ---- WebM recording: start/stop here or in the inspector; the file is saved when the take ends
    const recTime = el("span", { class: "st-rec-time", hidden: true, "aria-hidden": "true" });
    toolbarEls.rec.append(recTime);
    let recTimer = 0;
    const saveTake = (blob, note) => {
      if (!blob || !blob.size) { toast("녹화된 내용이 없습니다.", "warn"); return; }
      const ext = (blob.type || "").includes("webm") ? "webm" : "mp4";
      downloadBlob(blob, `img2live-${stamp()}.${ext}`);
      toast(`${note || "녹화를 저장했습니다."} (${(blob.size / 1048576).toFixed(1)} MB)`, "ok");
    };
    async function recToggle() {
      if (!stage.recording) {
        try { stage.startRecording(); }
        catch (e) { toast(`녹화를 시작하지 못했습니다: ${e.message || e}`, "bad"); }
        return;
      }
      try { saveTake(await stage.stopRecording()); }
      catch (e) { toast(`녹화를 저장하지 못했습니다: ${e.message || e}`, "bad"); }
    }
    window.addEventListener("i2l-record-toggle", recToggle);   // the inspector's button
    const recSync = () => {
      const on = stage.recording;
      toolbarEls.rec.setAttribute("aria-pressed", String(on));
      toolbarEls.rec.classList.toggle("is-rec", on);
      const label = on ? "녹화 중지하고 WebM 저장" : "WebM으로 녹화 시작";
      toolbarEls.rec.setAttribute("aria-label", label); toolbarEls.rec.title = label;
      toolbarEls.rec.replaceChildren(icon(on ? "stop" : "record", 18), recTime);
      recTime.hidden = !on;
      clearInterval(recTimer);
      if (on) { const tick = () => { recTime.textContent = fmtClock(stage.recordingMs); }; tick(); recTimer = setInterval(tick, 250); }
      window.dispatchEvent(new CustomEvent("i2l-record-state", { detail: { on } }));
    };
    toolbarEls.rec.disabled = !stage.canRecord();
    if (!stage.canRecord()) toolbarEls.rec.title = "이 브라우저는 캔버스 녹화를 지원하지 않습니다";
    stage.on("record", recSync);
    stage.on("recorded", (blob, info) => saveTake(blob, info && info.reason === "reload" ? "퍼펫이 바뀌어 녹화를 마치고 저장했습니다." : "녹화를 저장했습니다."));
    const sync = () => {
      for (const mode of stage.backgrounds) toolbarEls["bg-" + mode].setAttribute("aria-checked", String(stage.background === mode));
      toolbarEls.wire.setAttribute("aria-pressed", String(stage.option("wireframe")));
      const idle = stage.option("idle");
      toolbarEls.idle.replaceChildren(icon(idle ? "pause" : "play", 18));
      toolbarEls.idle.setAttribute("aria-label", idle ? "대기 동작 일시정지" : "대기 동작 재생");
      toolbarEls.idle.title = toolbarEls.idle.getAttribute("aria-label");
      toolbarEls.idle.disabled = !stage.canOption("idle");
    };
    for (const ev of ["option", "background", "ready", "reload"]) stage.on(ev, sync);
    sync();
  }

  // ================================================================ panels: collapse, drawers, resize
  function setDrawer(which) { root.dataset.drawer = which; syncPanels(); }
  function togglePanel(side) {
    if (narrow()) setDrawer(root.dataset.drawer === side ? "none" : side);
    else {
      ui[side] = !ui[side];
      root.dataset[side] = ui[side] ? "open" : "closed";
      store.set(UI_KEY, ui);
      syncPanels();
    }
  }
  function syncPanels() {
    const n = narrow();
    for (const side of ["left", "right"]) {
      const open = n ? root.dataset.drawer === side : ui[side];
      const aside = $(side === "left" ? "stLeft" : "stRight");
      aside.inert = !open;
      aside.setAttribute("aria-hidden", String(!open));
      toolbarEls[side]?.setAttribute("aria-expanded", String(open));
    }
    $("stScrim").hidden = !(n && root.dataset.drawer !== "none");
  }
  function applyWidths() {
    root.style.setProperty("--left-w", `${ui.leftW}px`);
    root.style.setProperty("--right-w", `${ui.rightW}px`);
  }
  function setupSplit(elSplit, side) {
    const MIN = 220, MAX = 560, DEF = side === "left" ? 300 : 360, key = side + "W";
    const set = (w) => { ui[key] = Math.max(MIN, Math.min(MAX, Math.round(w))); applyWidths(); };
    let start = null;
    elSplit.addEventListener("pointerdown", (e) => { if (narrow()) return; elSplit.setPointerCapture(e.pointerId); start = { x: e.clientX, w: ui[key] }; elSplit.classList.add("is-drag"); });
    elSplit.addEventListener("pointermove", (e) => { if (start) set(start.w + (side === "left" ? e.clientX - start.x : start.x - e.clientX)); });
    const end = () => { if (start) { start = null; elSplit.classList.remove("is-drag"); store.set(UI_KEY, ui); } };
    elSplit.addEventListener("pointerup", end);
    elSplit.addEventListener("pointercancel", end);
    elSplit.addEventListener("dblclick", () => { set(DEF); store.set(UI_KEY, ui); });
    elSplit.addEventListener("keydown", (e) => {
      const d = e.key === "ArrowLeft" ? -16 : e.key === "ArrowRight" ? 16 : 0;
      if (d) { e.preventDefault(); set(ui[key] + (side === "left" ? d : -d)); store.set(UI_KEY, ui); }
      else if (e.key === "Home") { e.preventDefault(); set(DEF); store.set(UI_KEY, ui); }
    });
    elSplit.setAttribute("aria-valuemin", String(MIN));
    elSplit.setAttribute("aria-valuemax", String(MAX));
  }
  function buildPanels() {
    root.dataset.left = ui.left ? "open" : "closed";
    root.dataset.right = ui.right ? "open" : "closed";
    root.dataset.drawer = "none";
    applyWidths();
    setupSplit($("splitL"), "left");
    setupSplit($("splitR"), "right");
    $("stScrim").addEventListener("click", () => setDrawer("none"));
    mq.addEventListener("change", () => { root.dataset.drawer = "none"; syncPanels(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && narrow() && root.dataset.drawer !== "none") setDrawer("none"); });
    syncPanels();
  }

  // ================================================================ test hook
  if (TEST) {
    window.__studio = {
      stage, panel, inspector, api, select, openEditor, closeEditor, applyState, toast,
      get state() { return state; },
      get selected() { return selected; },
      get degraded() { return degraded; },
      get editor() { return editorHandle; },
    };
    document.documentElement.dataset.studioReady = "0";
    stage.ready.then(() => { document.documentElement.dataset.studioReady = "1"; }).catch(() => { document.documentElement.dataset.studioReady = "error"; });
  }

  async function deleteJob() {
    const r = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (r.ok) { mine.remove(jobId); location.href = "/"; return; }
    const j = await r.json().catch(() => ({}));
    throw new Error(j.detail || "삭제하지 못했습니다.");
  }
}

/** No /studio endpoint yet: a read-only layer list from layers/index.json plus the puppet's draw order. */
async function degradedState(job) {
  const R = job.result || {};
  const [idx, pup] = await Promise.all([
    fetch(F(R.layers_index)).then((r) => { if (!r.ok) throw new Error(`layers/index.json HTTP ${r.status}`); return r.json(); }),
    fetch(F(R.puppet)).then((r) => (r.ok ? r.json() : { meshes: [] })),
  ]);
  const order = new Map();
  for (const m of pup.meshes || []) if (m.tag && !order.has(m.tag)) order.set(m.tag, m.order ?? 100);
  const heads = new Set((idx.hires || []).map((h) => h.tag));
  const layers = (idx.layers || []).map((l) => {
    const o = order.get(l.tag) ?? 100;
    return {
      tag: l.tag, label: labelOf(l.tag), group: groupOf(l.tag), grid: heads.has(l.tag) ? "head" : "canvas",
      enabled: true, order: o, order_default: o, current: "v0",
      versions: [{ id: "v0", kind: "original", note: "", created: 0 }],
      bbox: l.file ? [l.x, l.y, l.w, l.h] : null, // [x, y, width, height] like the server's state
      opaque_px: l.opaque_px || 0, empty: !!l.empty || !l.file, file: l.file || null,
    };
  });
  return { rev: 0, puppet: F(R.puppet), canvas: idx.canvas, head_square: idx.head_square, layers, tasks: [], can_regen: false, degraded: true };
}

// ================================================================================================ boot
(async () => {
  try {
    const r = await fetch(`/api/jobs/${jobId}`);
    if (r.status === 404) { gone(); return; }
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    mine.add(jobId, j.prompt || ""); // opening a job puts it in "내 퍼펫"
    const cnt = document.getElementById("navMineCount"); // (nav.js ran before this: refresh the header count)
    if (cnt) cnt.textContent = String(mine.list().length);
    render(j);
    if (current.status === "queued" || current.status === "running") connect();
  } catch (e) {
    $("title").textContent = "서버에 연결할 수 없습니다";
    $("pbar").hidden = true;
    console.error(e);
  }
})();
