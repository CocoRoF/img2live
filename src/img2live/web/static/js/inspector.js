// SPDX-License-Identifier: Apache-2.0
/**
 * Right panel of the studio with four tabs: 움직임 · 레이어 · 보고서 · 파일.
 *
 *   const insp = createInspector(container, {
 *     stage,                       // js/stage.js handle (params, options, background, snapshot, capability)
 *     api,                         // js/studio-api.js handle, or null when the backend has no /studio yet (degraded mode)
 *     job,                         // public job json (result.downloads, files, ...)
 *     fileUrl(path),               // /files/<job>/<path>
 *     loadReport(),                // Promise<report.json>
 *     notify(message, kind),       // toast
 *     onState(state),              // a studio call returned a new state -> the page applies it (returns a promise)
 *     onEdit(tag),                 // [편집] -> the page opens the layer editor
 *     refreshState(),              // re-read GET /studio (after a regen request)
 *     deleteJob(),                 // DELETE the job and leave
 *     onBusy(on),                  // a studio call is in flight (the page shows a chip: the server recompiles the puppet, 2-4 s)
 *   });
 *   insp.setState(state)  insp.setSelected(tag, { openTab })  insp.showTab(name)  insp.setDegraded(bool)
 */
import { el, icon, esc, fmtBytes, fmtInt, agoText, labelOf, groupOf, GROUP_LABELS, downloadBlob, stamp, uid } from "./studio-util.js";
import { reportHtml } from "./studio-report.js";

const TABS = [["motion", "움직임"], ["layer", "레이어"], ["report", "보고서"], ["files", "파일"]];
const KIND = { original: ["원본", ""], edit: ["편집", "accent"], regen: ["후보", "warn"], auto: ["자동", "ok"] };
const BG_NAMES = { checker: "체크무늬", white: "흰색", dark: "어둡게", green: "초록(크로마)" };
const PARAM_GROUPS = [
  { id: "head", title: "머리", test: (id) => /^ParamAngle[XYZ]$/.test(id) },
  { id: "eyes", title: "눈·눈썹", test: (id) => /Eye|Brow/.test(id) },
  { id: "mouth", title: "입", test: (id) => /Mouth/.test(id) },
  { id: "body", title: "몸·호흡", test: (id) => /Body|Breath/.test(id) },
  { id: "hair", title: "머리카락·꼬리 (물리)", test: (id) => /Hair|Tail|Skirt|Cloth|Ribbon/.test(id) },
  { id: "other", title: "기타", test: () => true },
];
const SWITCHES = [
  ["idle", "대기 동작", "숨 쉬듯 가만히 있을 때의 작은 움직임 (Space)"],
  ["blink", "자동 깜빡임", "눈을 주기적으로 깜빡입니다"],
  ["physics", "물리", "머리카락·꼬리가 흔들립니다"],
  ["follow", "마우스 따라보기", "커서 쪽으로 머리와 시선을 돌립니다"],
  ["wireframe", "와이어프레임", "메시 격자를 겹쳐 그립니다"],
  ["focus", "선택 레이어 집중", "선택한 레이어 외에는 흐리게 봅니다"],
];

const fmt = (v, d) => (Math.abs(v) < 0.5 * 10 ** -d ? 0 : v).toFixed(d);

function classifyCapability(text) {
  const s = String(text);
  if (/^ok\b/i.test(s)) return { level: "ok", label: "정상", detail: s.replace(/^ok\b:?\s*/i, "") };
  if (/^degraded\b/i.test(s)) return { level: "degraded", label: "대체 방식", detail: s.replace(/^degraded\b:?\s*/i, "") };
  if (/^unavailable\b/i.test(s)) return { level: "unavailable", label: "불가", detail: s.replace(/^unavailable\b:?\s*/i, "") };
  return { level: "info", label: "", detail: s };
}

function makeSwitch(label, { checked = false, onChange, title, disabled = false } = {}) {
  const id = uid("sw");
  const input = el("input", { type: "checkbox", role: "switch", id, checked: checked || false, disabled: disabled || false });
  const row = el("label", { class: "st-switch", for: id, title: title || false }, input, el("span", { class: "st-track", "aria-hidden": "true" }), el("span", { class: "st-switch-label", text: label }));
  if (onChange) input.addEventListener("change", () => onChange(input.checked));
  return { row, input };
}

export function createInspector(container, deps) {
  const { stage, api = null, job = {}, fileUrl = (p) => p, loadReport = async () => ({}), notify = () => {}, onState = async () => {}, onEdit = () => {}, refreshState = async () => {}, deleteJob = async () => {}, onBusy = () => {} } = deps;
  const uidp = uid("in");
  let state = null;
  let selected = null;
  let degraded = !api;
  let busy = false;
  let regenOpen = false;
  const offs = [];

  container.classList.add("in");

  // =========================================================================================== tabs
  const tabBar = el("div", { class: "in-tabs", role: "tablist", "aria-label": "검사기" });
  const panels = {};
  const tabBtns = {};
  for (const [key, label] of TABS) {
    const b = el("button", { type: "button", role: "tab", id: `${uidp}-t-${key}`, "aria-controls": `${uidp}-p-${key}`, "aria-selected": "false", tabindex: "-1", "data-tab": key, text: label });
    tabBtns[key] = b;
    tabBar.append(b);
    panels[key] = el("div", { class: "in-panel", role: "tabpanel", id: `${uidp}-p-${key}`, "aria-labelledby": b.id, tabindex: "0", hidden: true });
  }
  const panelBox = el("div", { class: "in-panels" }, ...Object.values(panels));
  const busyBar = el("div", { class: "in-busybar", role: "status", hidden: true }, el("span", { class: "st-spin", "aria-hidden": "true" }), el("span", { text: "적용하는 중… 퍼펫을 다시 만드는 데 몇 초 걸립니다." }));
  container.append(tabBar, busyBar, panelBox);
  let tab = "motion";
  function showTab(name) {
    if (!panels[name]) return;
    tab = name;
    for (const [k, b] of Object.entries(tabBtns)) {
      b.setAttribute("aria-selected", String(k === name));
      b.tabIndex = k === name ? 0 : -1;
      panels[k].hidden = k !== name;
    }
    if (name === "report") ensureReport();
    if (name === "motion") syncMotion();
  }
  tabBar.addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) showTab(b.dataset.tab); });
  tabBar.addEventListener("keydown", (e) => {
    const keys = TABS.map(([k]) => k);
    const at = keys.indexOf(tab);
    let to = null;
    if (e.key === "ArrowRight") to = keys[(at + 1) % keys.length];
    else if (e.key === "ArrowLeft") to = keys[(at - 1 + keys.length) % keys.length];
    else if (e.key === "Home") to = keys[0];
    else if (e.key === "End") to = keys[keys.length - 1];
    if (to) { e.preventDefault(); showTab(to); tabBtns[to].focus(); }
  });

  // =========================================================================================== 움직임
  const motion = panels.motion;
  const switches = {};
  const swGrid = el("div", { class: "st-switches" });
  for (const [key, label, title] of SWITCHES) {
    const s = makeSwitch(label, { title, onChange: (on) => { stage.option(key, on); syncSwitches(); } });
    switches[key] = s;
    swGrid.append(s.row);
  }
  const bgBtns = {};
  const bgBox = el("div", { class: "in-bg", role: "radiogroup", "aria-label": "배경" });
  for (const mode of stage.backgrounds) {
    const b = el("button", { type: "button", class: "in-bgbtn", role: "radio", "aria-checked": "false", "data-bg": mode, title: BG_NAMES[mode] || mode }, el("span", { class: `in-swatch bg-${mode}`, "aria-hidden": "true" }), el("span", { text: BG_NAMES[mode] || mode }));
    b.addEventListener("click", () => stage.setBackground(mode));
    bgBtns[mode] = b;
    bgBox.append(b);
  }
  const btnReset = el("button", { type: "button", class: "btn small", "data-fk": "reset-params" }, icon("undo", 14), " 매개변수 초기화");
  const btnPng = el("button", { type: "button", class: "btn small", "data-fk": "snapshot" }, icon("camera", 14), " PNG 저장");
  btnReset.addEventListener("click", () => { stage.params.reset(); syncSliders(true); });
  btnPng.addEventListener("click", async () => {
    try { downloadBlob(await stage.snapshot(), `img2live-${stamp()}.png`); } catch (e) { notify(`스냅샷에 실패했습니다: ${e.message || e}`, "bad"); }
  });
  // ---- saving: PNG stills and the WebM recording (the toolbar's record button does the same)
  const btnPngT = el("button", { type: "button", class: "btn small", "data-fk": "snapshot-alpha", title: "배경 없이 캐릭터만 PNG로 저장합니다" }, icon("camera", 14), " 투명 PNG");
  btnPngT.addEventListener("click", async () => {
    try { downloadBlob(await stage.renderer.snapshotBlob({ transparent: true }), `img2live-${stamp()}-alpha.png`); } catch (e) { notify(`스냅샷에 실패했습니다: ${e.message || e}`, "bad"); }
  });
  const btnRec = el("button", { type: "button", class: "btn small primary in-rec", "data-fk": "record" });
  btnRec.addEventListener("click", () => window.dispatchEvent(new Event("i2l-record-toggle")));
  const recBg = el("select", { "aria-label": "녹화 배경", class: "in-sel", "data-fk": "rec-bg" },
    el("option", { value: "alpha", text: "투명 (알파 채널, VP9)" }), el("option", { value: "screen", text: "지금 보이는 배경 그대로" }));
  const recFps = el("select", { "aria-label": "프레임 속도", class: "in-sel", "data-fk": "rec-fps" },
    el("option", { value: "60", text: "60 fps" }), el("option", { value: "30", text: "30 fps" }));
  recBg.addEventListener("change", () => { stage.recordOptions.alpha = recBg.value === "alpha"; });
  recFps.addEventListener("change", () => { stage.recordOptions.fps = Number(recFps.value); });
  const recHelp = el("p", { class: "small muted" });
  const recSync = () => {
    const on = stage.recording, can = stage.canRecord();
    btnRec.replaceChildren(icon(on ? "stop" : "record", 14), on ? " 녹화 중지하고 저장" : " WebM 녹화 시작");
    btnRec.disabled = !can;
    recBg.disabled = recFps.disabled = on || !can;
    if (!stage.recordAlphaSupported) { recBg.value = "screen"; stage.recordOptions.alpha = false; recBg.querySelector('option[value="alpha"]').disabled = true; }
    recHelp.textContent = !can ? "이 브라우저는 캔버스 녹화를 지원하지 않습니다."
      : on ? "녹화 중입니다. 슬라이더·대기 동작·마우스 따라보기로 움직임을 만든 뒤 중지하면 .webm 파일이 저장됩니다."
      : "움직이는 모습을 .webm 영상으로 저장합니다. 투명 배경 영상은 알파 채널이 있는 VP9라 Chrome·Edge·OBS 브라우저 소스에서 재생됩니다. 다른 프로그램에서 쓰려면 배경을 초록으로 바꾸고 '지금 보이는 배경 그대로'로 녹화하세요.";
  };
  window.addEventListener("i2l-record-state", recSync);
  stage.on("record", recSync);
  recSync();
  const paramsBox = el("div", { class: "in-params" });
  const capBox = el("div", { class: "in-cap" });
  motion.append(
    el("section", { class: "in-sec" }, el("h3", { text: "움직임" }), swGrid),
    el("section", { class: "in-sec" }, el("h3", { text: "배경" }), bgBox, el("div", { class: "in-row" }, btnReset)),
    el("section", { class: "in-sec in-save" }, el("h3", { text: "저장·녹화" }),
      el("div", { class: "in-row" }, btnPng, btnPngT),
      el("div", { class: "in-row" }, btnRec),
      el("div", { class: "in-row split" }, el("label", { class: "small muted", text: "배경" }), recBg, el("label", { class: "small muted", text: "속도" }), recFps),
      recHelp),
    el("section", { class: "in-sec" }, el("h3", { text: "매개변수" }), paramsBox),
    el("section", { class: "in-sec" }, el("h3", { text: "기능 상태" }), capBox));

  const sliders = new Map(); // id -> {p, input, output, row, decimals, shown}
  const dragging = new Set();
  const openGroups = new Map(); // remember <details> state across rebuilds
  let paramSig = "";
  function buildParams() {
    const list = stage.params.list();
    const sig = list.map((p) => `${p.id}:${p.min}:${p.max}`).join("|");
    if (sig === paramSig) return;
    paramSig = sig;
    sliders.clear();
    paramsBox.replaceChildren();
    if (!list.length) { paramsBox.append(el("p", { class: "muted small", text: "매개변수가 없습니다." })); return; }
    for (const g of PARAM_GROUPS) {
      const ps = list.filter((p) => PARAM_GROUPS.find((x) => x.test(p.id)) === g);
      if (!ps.length) continue;
      const body = el("div", { class: "in-group-body" });
      for (const p of ps) {
        const range = p.max - p.min;
        const decimals = range >= 20 ? 1 : 2;
        const iid = `${uidp}-p-${p.id}`;
        const input = el("input", { type: "range", id: iid, min: p.min, max: p.max, step: range / 400, value: p.final ?? p.default, "data-param": p.id });
        const output = el("output", { for: iid, class: "in-value", text: fmt(p.final ?? p.default, decimals) });
        const chip = p.driven ? el("span", { class: "in-chip", text: "물리", title: "물리가 켜져 있으면 시뮬레이션이 이 값을 정합니다" }) : null;
        const row = el("div", { class: "in-param" + (p.driven ? " is-driven" : "") }, el("label", { for: iid, class: "in-param-name" }, el("span", { text: p.name }), chip), output, input);
        const rec = { p, input, output, row, decimals, shown: NaN };
        sliders.set(p.id, rec);
        input.addEventListener("pointerdown", () => { dragging.add(p.id); stage.params.hold(p.id, true); });
        const release = () => { if (dragging.delete(p.id)) stage.params.hold(p.id, false); };
        input.addEventListener("pointerup", release);
        input.addEventListener("pointercancel", release);
        input.addEventListener("blur", release);
        input.addEventListener("input", () => {
          const v = parseFloat(input.value);
          stage.params.set(p.id, v);
          output.textContent = fmt(v, decimals);
          rec.shown = v;
        });
        body.append(row);
      }
      const det = el("details", { class: "in-details", open: openGroups.get(g.id) ?? true }, el("summary", { text: g.title }), body);
      det.addEventListener("toggle", () => openGroups.set(g.id, det.open));
      paramsBox.append(det);
    }
  }
  function syncSliders(force = false) {
    if (panels.motion.hidden) return;
    const physicsOn = stage.option("physics");
    for (const [id, s] of sliders) {
      if (dragging.has(id)) continue;
      const v = stage.params.getFinal(id);
      if (v === undefined) continue;
      if (force || Math.abs(v - s.shown) > 1e-4 || s.shown !== s.shown) {
        s.shown = v;
        s.input.value = v;
        s.output.textContent = fmt(v, s.decimals);
      }
      const lock = s.p.driven && physicsOn;
      if (s.input.disabled !== lock) { s.input.disabled = lock; s.row.classList.toggle("is-locked", lock); }
    }
  }
  function syncSwitches() {
    for (const [key, s] of Object.entries(switches)) {
      s.input.checked = !!stage.option(key);
      s.input.disabled = !stage.canOption(key);
    }
  }
  function syncBackground() {
    for (const [mode, b] of Object.entries(bgBtns)) b.setAttribute("aria-checked", String(stage.background === mode));
  }
  function buildCapabilities() {
    capBox.replaceChildren();
    const cap = stage.meta && stage.meta.capability;
    if (!cap || typeof cap !== "object" || !Object.keys(cap).length) { capBox.append(el("p", { class: "muted small", text: "이 퍼펫에는 기능 상태 기록이 없습니다." })); return; }
    const list = el("ul", { class: "in-capl" });
    const counts = { degraded: 0, unavailable: 0 };
    for (const [key, value] of Object.entries(cap)) {
      const c = classifyCapability(value);
      if (c.level in counts) counts[c.level]++;
      list.append(el("li", { class: "in-capi", "data-level": c.level },
        el("span", { class: "in-capk", text: key.replace(/_/g, " ") }),
        el("span", { class: "in-capv" }, c.label ? el("span", { class: `pill ${c.level === "ok" ? "ok" : c.level === "degraded" ? "warn" : c.level === "unavailable" ? "bad" : ""}`, text: c.label }) : null, c.detail ? ` ${c.detail}` : "")));
    }
    const bits = [];
    if (counts.unavailable) bits.push(`불가 ${counts.unavailable}`);
    if (counts.degraded) bits.push(`대체 방식 ${counts.degraded}`);
    capBox.append(el("p", { class: "small muted", text: bits.length ? `확인이 필요한 항목: ${bits.join(", ")}.` : "보고된 모든 기능을 온전히 쓸 수 있습니다." }), list);
    const notes = [];
    if (stage.meta && stage.meta.ai_generated) notes.push("AI 생성물입니다.");
    if (stage.warnings.length) notes.push(`퍼펫 메모: ${stage.warnings.join("; ")}`);
    if (notes.length) capBox.append(el("p", { class: "small muted", text: notes.join(" ") }));
  }
  function syncMotion() {
    buildParams();
    syncSwitches();
    syncBackground();
    syncSliders(true);
  }
  offs.push(stage.on("frame", () => syncSliders()));
  offs.push(stage.on("option", syncSwitches));
  offs.push(stage.on("background", syncBackground));
  offs.push(stage.on("params-reset", () => syncSliders(true)));
  const onStageLoaded = () => { buildParams(); buildCapabilities(); syncSwitches(); syncBackground(); syncSliders(true); };
  offs.push(stage.on("ready", onStageLoaded));
  offs.push(stage.on("reload", onStageLoaded));
  if (stage.loaded) onStageLoaded();

  // =========================================================================================== 레이어
  const layerTab = panels.layer;
  const layerHost = el("div", { class: "in-layer" });
  layerTab.append(layerHost);
  const secs = new Map(); // keyed sections: only the ones whose signature changed are rebuilt (keeps focus and thumbnails calm)
  function put(name, sig, build) {
    let s = secs.get(name);
    if (!s) { s = { sig: null, node: el("div", { class: "in-block", "data-sec": name }) }; secs.set(name, s); }
    if (s.sig !== sig) { s.sig = sig; s.node.replaceChildren(...[].concat(build()).filter(Boolean)); }
    return s.node;
  }
  const layerOf = (tag) => (state && state.layers ? state.layers.find((l) => l.tag === tag) : null);

  async function act(fn, okMsg) {
    if (busy) return null;
    setBusy(true);
    try {
      const res = await fn();
      if (res && res.state) await onState(res.state);
      if (okMsg) notify(okMsg, "ok");
      return res;
    } catch (e) {
      notify(e && e.message ? e.message : "요청에 실패했습니다", "bad");
      for (const s of secs.values()) s.sig = null; // rebuild everything so a flipped switch snaps back to the server's truth
      renderLayer(true);
      return null;
    } finally { setBusy(false); }
  }
  function setBusy(on) {
    busy = on;
    layerHost.classList.toggle("is-busy", on);
    layerHost.setAttribute("aria-busy", String(on));
    busyBar.hidden = !on;
    try { onBusy(on); } catch (e) { console.error(e); }
  }

  // ---- regen form (persistent element so typed values survive re-renders)
  const regen = (() => {
    const seedAuto = el("input", { type: "radio", name: `${uidp}-seed`, value: "auto", checked: true, id: `${uidp}-seed-auto` });
    const seedManual = el("input", { type: "radio", name: `${uidp}-seed`, value: "manual", id: `${uidp}-seed-manual` });
    const seedNum = el("input", { type: "number", class: "in-num", min: 0, max: 2147483647, step: 1, value: 42, disabled: true, "aria-label": "시드 값" });
    const steps = el("input", { type: "range", min: 20, max: 50, step: 1, value: 30, id: `${uidp}-steps` });
    const stepsOut = el("output", { for: steps.id, class: "in-value", text: "30" });
    const intro = el("p", { class: "small muted" });
    const submit = el("button", { type: "submit", class: "btn primary small", "data-fk": "regen-submit" }, icon("refresh", 14), " 다시 생성 요청");
    const cancel = el("button", { type: "button", class: "btn small", text: "취소" });
    const form = el("form", { class: "in-regen", "aria-label": "다시 생성" },
      el("h4", { text: "다시 생성" }), intro,
      el("div", { class: "in-field" },
        el("div", { class: "in-field-top" }, el("span", { class: "in-label", text: "시드" })),
        el("div", { class: "in-seed" },
          el("label", { class: "in-radio", for: seedAuto.id }, seedAuto, " 자동"),
          el("label", { class: "in-radio", for: seedManual.id }, seedManual, " 직접"), seedNum)),
      el("div", { class: "in-field" }, el("div", { class: "in-field-top" }, el("label", { for: steps.id, text: "스텝" }), stepsOut), steps),
      el("div", { class: "in-row" }, submit, cancel));
    const syncSeed = () => { seedNum.disabled = !seedManual.checked; };
    seedAuto.addEventListener("change", syncSeed);
    seedManual.addEventListener("change", () => { syncSeed(); if (seedManual.checked) seedNum.focus(); });
    steps.addEventListener("input", () => { stepsOut.textContent = steps.value; });
    cancel.addEventListener("click", () => { regenOpen = false; renderLayer(true); layerHost.querySelector('[data-fk="regen"]')?.focus(); });
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const l = layerOf(selected);
      if (!l || !api) return;
      const body = { tags: [l.tag], steps: Number(steps.value) };
      if (seedManual.checked && Number.isFinite(parseInt(seedNum.value, 10))) body.seed = parseInt(seedNum.value, 10);
      const res = await act(() => api.regen(body));
      if (res) { notify("다시 생성을 요청했습니다. 약 3분 뒤 같은 시드의 후보가 그룹의 모든 레이어에 도착하며, 자동으로 적용되지 않습니다.", "ok"); regenOpen = false; await refreshState(); renderLayer(true); }
    });
    return {
      form,
      /** Every opening starts from the defaults (a seed typed for one layer must not leak into the next). */
      reset() { seedAuto.checked = true; syncSeed(); seedNum.value = 42; steps.value = 30; stepsOut.textContent = "30"; },
      prepare(l) {
        const group = l.grid === "head" ? "머리 11개" : "몸 12개";
        intro.textContent = `모델은 부위 그룹 전체를 한 번에 생성합니다. '${l.label || labelOf(l.tag)}'이(가) 속한 그룹(${group} 레이어)을 새 시드로 다시 돌려 GPU 작업기에서 약 3분 걸립니다. 같은 시드의 결과가 그룹의 모든 레이어에 후보로 도착하고, 자동으로 적용되지 않습니다. 마음에 드는 레이어만 골라 쓰거나 [모두 적용]으로 한꺼번에 바꿀 수 있습니다.`;
      },
    };
  })();

  function orderNeighbors(l) {
    const others = (state.layers || []).filter((x) => x.tag !== l.tag && !x.empty && x.enabled !== false);
    const above = others.filter((x) => x.order > l.order).sort((a, b) => a.order - b.order);
    const below = others.filter((x) => x.order < l.order).sort((a, b) => b.order - a.order);
    const ties = others.some((x) => x.order === l.order);
    return {
      up: above.length ? above[0].order + 1 : ties ? l.order + 1 : null,
      down: below.length ? below[0].order - 1 : ties ? l.order - 1 : null,
    };
  }

  function pendingOf(t) {
    // the candidates of this regeneration that are still there and not in use
    const vs = (t.result && t.result.versions) || [];
    return vs.filter((x) => { const l = layerOf(x.tag); return l && l.versions.some((v) => v.id === x.version) && l.current !== x.version; });
  }
  function taskLine(t) {
    const st = String(t.status || "");
    const [stLabel, tone] = st === "running" ? ["진행 중", "warn"] : st === "queued" ? ["대기", ""] : st === "failed" ? ["실패", "bad"] : st === "done" ? ["완료", "ok"] : [st || "-", ""];
    const names = (t.tags || []).map((x) => labelOf(x));
    const title = `${t.kind === "regen" || !t.kind ? "다시 생성" : t.kind}${names.length ? ` · ${names.slice(0, 3).join(", ")}${names.length > 3 ? ` 외 ${names.length - 3}` : ""}` : ""}`;
    const p = Math.max(0, Math.min(1, Number(t.progress) || 0));
    const pending = st === "done" ? pendingOf(t) : [];
    const applyAll = pending.length ? el("button", { type: "button", class: "btn small primary", "data-fk": `apply-${t.id}`, title: "이 시드의 후보를 모두 적용합니다 (레이어별 되돌리기는 버전 목록에서)" }, icon("check", 14), ` 시드 ${t.seed ?? ""} 후보 ${pending.length}개 모두 적용`) : null;
    if (applyAll) applyAll.addEventListener("click", () => act(() => api.applyTask(t.id), "후보를 적용했습니다. 마음에 안 드는 레이어는 버전 목록에서 되돌릴 수 있습니다."));
    return el("li", { class: "in-task", "data-status": st },
      el("div", { class: "in-task-top" }, el("span", { class: "in-task-title", text: title }), el("span", { class: `pill ${tone}`, text: stLabel })),
      applyAll,
      (st === "failed" || st === "done") ? null : el("div", { class: "progress", role: "progressbar", "aria-label": `${title} 진행률`, "aria-valuemin": "0", "aria-valuemax": "100", "aria-valuenow": String(Math.round(p * 100)) }, el("i", { style: `width:${Math.round(p * 100)}%` })),
      (t.error || t.message) ? el("p", { class: `small ${st === "failed" ? "bad-text" : "muted"}`, text: t.error || t.message }) : null,
      st === "done" && t.result && t.result.dropped && t.result.dropped.length
        ? el("p", { class: "small muted", text: `모델이 배경을 섞어 만든 레이어는 후보에서 뺐습니다: ${t.result.dropped.map((x) => labelOf(x)).join(", ")}` }) : null);
  }

  function versionItem(l, v) {
    const [kindLabel, kindTone] = KIND[v.kind] || [v.kind || "?", ""];
    const isCur = v.id === l.current;
    const meta = [v.seed != null ? `시드 ${v.seed}` : "", agoText(v.created)].filter(Boolean).join(" · ");
    // a blank version has no thumbnail on the server (404): do not ask for it
    const blank = v.opaque === 0 || (isCur && l.empty);
    const img = el("img", { alt: "", decoding: "async", loading: "lazy", src: blank ? false : api.layerThumbUrl(l.tag, v.id, 0) });
    const thumb = el("span", { class: "in-ver-thumb checker" + (blank ? " is-missing" : "") }, img);
    img.addEventListener("error", () => { thumb.classList.add("is-missing"); img.removeAttribute("src"); });
    const main = el("button", { type: "button", class: "in-ver-main", "data-fk": `ver-${v.id}`, "aria-label": `${kindLabel} 버전 ${v.id}${isCur ? " (현재)" : " 적용"}`, "aria-current": isCur ? "true" : false, title: isCur ? "지금 쓰는 버전" : "이 버전을 적용합니다 (되돌리기·다시 하기·후보 비교에 씁니다)" },
      thumb,
      el("span", { class: "in-ver-body" },
        el("span", { class: "in-ver-top" }, el("span", { class: `pill ${kindTone}`, text: kindLabel }), isCur ? el("span", { class: "pill ok", text: "현재" }) : null, el("span", { class: "in-ver-id small muted", text: v.id })),
        v.note ? el("span", { class: "in-ver-note", text: v.note }) : null,
        meta ? el("span", { class: "in-ver-meta small muted", text: meta }) : null));
    if (!isCur) main.addEventListener("click", () => act(() => api.select(l.tag, v.id), `'${l.label || labelOf(l.tag)}' 레이어에 ${kindLabel} 버전을 적용했습니다.`));
    const li = el("li", { class: "in-ver" + (isCur ? " is-current" : "") }, main);
    if (v.kind !== "original" && !isCur) {
      const del = el("button", { type: "button", class: "in-ver-del", "aria-label": `${kindLabel} 버전 ${v.id} 삭제`, title: "이 버전 삭제", "data-fk": `verdel-${v.id}` }, icon("trash", 15));
      del.addEventListener("click", () => {
        if (!confirm("이 버전을 삭제할까요? 되돌릴 수 없습니다.")) return;
        act(() => api.deleteVersion(l.tag, v.id), "버전을 삭제했습니다.");
      });
      li.append(del);
    }
    return li;
  }

  let lastFocusKey = null;
  function renderLayer(force = false) {
    // remember which control had focus so a rebuild can hand it back
    const ae = document.activeElement;
    if (ae && layerHost.contains(ae) && ae.dataset && ae.dataset.fk) lastFocusKey = ae.dataset.fk;
    const l = selected ? layerOf(selected) : null;
    const nodes = [];
    const tasks = state && Array.isArray(state.tasks) ? state.tasks : [];
    const active = (t) => ["queued", "running"].includes(String(t.status));
    const recentFail = (t) => String(t.status) === "failed" && (!t.finished_at || Date.now() / 1000 - Number(t.finished_at) < 600);
    const hasPending = (t) => String(t.status) === "done" && pendingOf(t).length > 0;
    const shownTasks = tasks.filter((t) => active(t) || recentFail(t) || hasPending(t)).slice(0, 6);
    const regenBusy = tasks.some(active); // the server runs one regeneration per puppet at a time

    if (api && !degraded && state && state.dirty) {
      nodes.push(put("dirty", "dirty", () => {
        const b = el("button", { type: "button", class: "btn small", "data-fk": "rebuild" }, icon("check", 14), " 지금 반영");
        b.addEventListener("click", () => act(() => api.rebuild(), "퍼펫에 반영했습니다."));
        return el("div", { class: "notice warn in-dirty" }, icon("info", 16), " 아직 퍼펫에 반영하지 않은 변경이 있습니다. ", b);
      }));
    }
    if (!l) {
      nodes.push(put("empty", `empty|${degraded}|${selected}`, () => [
        el("div", { class: "in-hint" }, icon("layers", 22),
          el("p", { text: selected ? `'${labelOf(selected)}'는 편집할 수 있는 레이어가 아닙니다.` : "왼쪽 목록이나 캔버스에서 레이어를 선택하세요." }),
          el("p", { class: "small muted", text: "눈 아이콘은 미리보기에서만 숨기고, S 는 그 레이어만 보여 줍니다. 서버의 퍼펫은 바뀌지 않습니다." })),
        degraded ? el("div", { class: "notice" }, "편집 기능 준비 중입니다.") : null]));
    } else {
      const label = l.label || labelOf(l.tag);
      const grp = (state.groups && state.groups[l.group]) || GROUP_LABELS[l.group || groupOf(l.tag)] || "";
      nodes.push(put("head", `head|${JSON.stringify([l.tag, label, l.group, l.grid, l.opaque_px, l.bbox, l.empty])}`, () => {
        // bbox is [x, y, width, height] in the edit grid
        const bb = Array.isArray(l.bbox) && l.bbox.length === 4 ? `${l.bbox[2]}×${l.bbox[3]} px · 위치 ${l.bbox[0]}, ${l.bbox[1]}` : "-";
        return [
          el("div", { class: "in-title" }, el("h3", { text: label }), el("code", { class: "small muted", text: l.tag }), grp ? el("span", { class: "pill", text: grp }) : null),
          el("dl", { class: "kv in-kv" },
            el("dt", { text: "편집 격자" }), el("dd", { text: l.grid === "head" ? "머리 확대 격자 (1280²)" : "캔버스 (1280²)" }),
            el("dt", { text: "불투명 픽셀" }), el("dd", { text: l.empty ? "없음 (비어 있는 레이어)" : `${fmtInt(l.opaque_px)} px` }),
            el("dt", { text: "범위" }), el("dd", { class: "small", text: bb })),
        ];
      }));
      if (degraded || !api) {
        nodes.push(put("degraded", "degraded", () => el("div", { class: "notice" }, icon("info", 16), " 편집 기능 준비 중입니다. 지금은 레이어를 보고·숨기고·강조하는 것만 됩니다.")));
      } else {
        const nb = orderNeighbors(l);
        nodes.push(put("flags", `flags|${JSON.stringify([l.tag, l.enabled, l.empty, l.order, l.order_default, nb])}`, () => {
          const inc = makeSwitch("퍼펫에 포함", { checked: l.enabled !== false, title: "끄면 이 레이어를 뺀 퍼펫으로 다시 만듭니다", onChange: (on) => act(() => api.flags(l.tag, { enabled: on }), on ? `'${label}' 레이어를 퍼펫에 포함했습니다.` : `'${label}' 레이어를 퍼펫에서 뺐습니다.`) });
          inc.input.setAttribute("data-fk", "include");
          const up = el("button", { type: "button", class: "btn small icon-only", "aria-label": "앞으로 (그리기 순서 올리기)", title: "앞으로 — 한 칸 위 레이어를 넘어 앞에 그립니다", disabled: nb.up == null || l.empty, "data-fk": "order-up" }, icon("up", 15));
          const down = el("button", { type: "button", class: "btn small icon-only", "aria-label": "뒤로 (그리기 순서 내리기)", title: "뒤로 — 한 칸 아래 레이어를 넘어 뒤에 그립니다", disabled: nb.down == null || l.empty, "data-fk": "order-down" }, icon("down", 15));
          up.addEventListener("click", () => act(() => api.flags(l.tag, { order: nb.up })));
          down.addEventListener("click", () => act(() => api.flags(l.tag, { order: nb.down })));
          const reset = l.order !== l.order_default ? el("button", { type: "button", class: "btn small", text: "기본값", title: "기본 그리기 순서로", "data-fk": "order-default" }) : null;
          if (reset) reset.addEventListener("click", () => act(() => api.flags(l.tag, { order: l.order_default })));
          return [
            el("div", { class: "in-row split" }, inc.row),
            l.enabled === false ? el("p", { class: "small muted", text: "퍼펫에서 제외된 레이어라 무대에는 보이지 않습니다." }) : null,
            l.empty ? el("p", { class: "small muted", text: "비어 있는 레이어입니다. 편집이나 다시 생성으로 채울 수 있습니다." }) : null,
            el("div", { class: "in-order" }, el("span", { class: "in-label", text: "그리기 순서" }), el("span", { class: "mono", text: String(l.order), "aria-label": `현재 ${l.order}` }), el("span", { class: "small muted", text: `기본 ${l.order_default}` }), up, down, reset),
            el("p", { class: "small muted", text: "숫자가 클수록 앞에 그려집니다." }),
          ];
        }));
        const canRegen = state.can_regen !== false;
        nodes.push(put("actions", `actions|${JSON.stringify([l.tag, l.current, canRegen, regenOpen, regenBusy])}`, () => {
          const bEdit = el("button", { type: "button", class: "btn small primary", "data-fk": "edit" }, icon("pencil", 14), " 편집");
          const bRegen = el("button", { type: "button", class: "btn small", "data-fk": "regen", "aria-expanded": String(regenOpen), disabled: !canRegen || regenBusy, title: !canRegen ? "GPU 작업기가 준비되지 않아 지금은 다시 생성할 수 없습니다" : regenBusy ? "이 퍼펫은 이미 다시 생성 중입니다. 끝난 뒤 눌러 주세요" : "이 레이어를 모델로 다시 생성합니다" }, icon("refresh", 14), " 다시 생성");
          const bOrig = el("button", { type: "button", class: "btn small", "data-fk": "to-original", disabled: l.current === "v0", title: l.current === "v0" ? "이미 원본입니다" : "원본(v0) 버전으로 되돌립니다" }, icon("undo", 14), " 원본으로");
          bEdit.addEventListener("click", () => onEdit(l.tag));
          bRegen.addEventListener("click", () => { regenOpen = !regenOpen; if (regenOpen) regen.reset(); renderLayer(true); if (regenOpen) regen.form.querySelector("input,button")?.focus(); });
          bOrig.addEventListener("click", () => act(() => api.select(l.tag, "v0"), `'${label}' 레이어를 원본으로 되돌렸습니다.`));
          return [el("div", { class: "in-actions" }, bEdit, bRegen, bOrig), !canRegen ? el("p", { class: "small muted", text: "다시 생성은 GPU 작업기가 준비되면 사용할 수 있습니다." }) : regenBusy ? el("p", { class: "small muted", text: "이 퍼펫은 이미 다시 생성 중입니다. 끝난 뒤 다시 요청할 수 있습니다." }) : null];
        }));
        regen.prepare(l);
        nodes.push(put("regen", `regen|${regenOpen}|${l.grid}|${l.tag}`, () => (regenOpen ? [regen.form] : [])));
        if (shownTasks.length) nodes.push(put("tasks", `tasks|${JSON.stringify(shownTasks)}`, () => [el("h4", { text: "작업" }), el("ul", { class: "in-tasks" }, ...shownTasks.map(taskLine))]));
        else secs.delete("tasks");
        const vers = [...(l.versions || [])].reverse();
        nodes.push(put("versions", `versions|${JSON.stringify([l.tag, l.current, vers])}`, () => [
          el("h4", {}, `버전 (${vers.length})`),
          el("ul", { class: "in-vers" }, ...vers.map((v) => versionItem(l, v))),
        ]));
      }
    }
    if (!l && api && shownTasks.length) nodes.push(put("tasks", `tasks|${JSON.stringify(shownTasks)}`, () => [el("h4", { text: "작업" }), el("ul", { class: "in-tasks" }, ...shownTasks.map(taskLine))]));
    if (api && !degraded) {
      nodes.push(put("global", `global|${state ? state.rev : 0}`, () => {
        const b = el("button", { type: "button", class: "btn small danger", "data-fk": "reset-all" }, icon("undo", 14), " 모두 원본으로 되돌리기");
        b.addEventListener("click", () => {
          if (!confirm("모든 레이어를 원본·포함·기본 순서로 되돌릴까요? 편집한 내용은 버전으로 남지만 지금 쓰는 버전은 원본으로 바뀝니다.")) return;
          act(() => api.reset(), "모든 레이어를 원본으로 되돌렸습니다.");
        });
        return [el("hr", { class: "in-hr" }), b];
      }));
    }
    // swap children only when the set of section nodes changed (re-inserting a node drops focus inside it)
    const cur = [...layerHost.children];
    if (force || cur.length !== nodes.length || cur.some((n, k) => n !== nodes[k])) layerHost.replaceChildren(...nodes);
    for (const [name, s] of [...secs]) if (!nodes.includes(s.node)) { if (name !== "regen") secs.delete(name); }
    if (lastFocusKey && (!document.activeElement || document.activeElement === document.body)) {
      const target = layerHost.querySelector(`[data-fk="${CSS.escape(lastFocusKey)}"]`);
      if (target && !target.disabled) target.focus({ preventScroll: true });
    }
    lastFocusKey = null;
  }

  // =========================================================================================== 보고서
  let reportLoaded = false;
  async function ensureReport() {
    if (reportLoaded) return;
    reportLoaded = true;
    const host = panels.report;
    host.replaceChildren(el("p", { class: "muted small", role: "status", text: "보고서를 불러오는 중…" }));
    try {
      const r = await loadReport();
      host.innerHTML = reportHtml(r, job);
    } catch (e) {
      reportLoaded = false;
      host.replaceChildren(el("div", { class: "notice bad", role: "alert", text: `보고서를 불러오지 못했습니다: ${e.message || e}` }));
    }
  }

  // =========================================================================================== 파일
  function buildFiles() {
    const R = job.result || {};
    const host = panels.files;
    const dl = [...(R.downloads || [])].map((d) => `<a class="btn small" href="${esc(fileUrl(d.path))}">${esc(d.path.split("/").pop())} <span class="muted small">${fmtBytes(d.size)}</span></a>`);
    if (R.puppet) dl.push(`<a class="btn small" href="${esc(state && state.puppet ? state.puppet : fileUrl(R.puppet))}" data-current-puppet>puppet.json</a>`);
    if (R.report) dl.push(`<a class="btn small" href="${esc(fileUrl(R.report))}">report.json</a>`);
    const rows = (R.files || []).map((f) => `<tr><td><a href="${esc(fileUrl(f.path))}" target="_blank" rel="noopener">${esc(f.path)}</a></td><td class="nowrap">${fmtBytes(f.size)}</td></tr>`).join("");
    host.innerHTML = `
      <section class="in-sec"><h3>다운로드</h3><div class="in-dl">${dl.join("") || '<span class="muted small">파일이 없습니다.</span>'}</div></section>
      <section class="in-sec"><h3>모든 파일</h3><div class="scroll-x"><table class="t in-files"><thead><tr><th>경로</th><th>크기</th></tr></thead><tbody>${rows}</tbody></table></div></section>
      <section class="in-sec"><h3>삭제</h3><p class="small muted">이 퍼펫과 모든 결과 파일을 지금 바로 삭제합니다. 되돌릴 수 없습니다.</p>
        <button class="btn small danger" id="${uidp}-del" type="button">이 퍼펫 삭제</button></section>
      <p class="small muted in-legal">AI 생성물입니다. 업로드·결과는 비공개 링크로만 열리며 1년 뒤 자동 삭제됩니다. <a href="/terms">약관·고지</a></p>`;
    host.querySelector(`#${uidp}-del`).addEventListener("click", async () => {
      if (!confirm("이 퍼펫과 모든 결과를 지금 삭제할까요? 되돌릴 수 없습니다.")) return;
      try { await deleteJob(); } catch (e) { notify(e && e.message ? e.message : "삭제하지 못했습니다.", "bad"); }
    });
  }

  // =========================================================================================== public
  showTab("motion");
  buildFiles();
  renderLayer(true);

  return {
    setState(next) {
      const hadPuppet = state && state.puppet;
      state = next;
      renderLayer();
      if (!hadPuppet || hadPuppet !== next.puppet) { const a = panels.files.querySelector("[data-current-puppet]"); if (a && next.puppet) a.href = next.puppet; }
    },
    setSelected(tag, { openTab = false } = {}) {
      if ((tag || null) !== selected) regenOpen = false; // a new selection closes the regen form
      selected = tag || null;
      renderLayer(true);
      if (selected && openTab) showTab("layer");
    },
    setDegraded(on) { degraded = !!on || !api; renderLayer(true); },
    showTab,
    get tab() { return tab; },
    get busy() { return busy; },
    dispose() { for (const off of offs) off(); container.replaceChildren(); container.classList.remove("in"); },
  };
}
