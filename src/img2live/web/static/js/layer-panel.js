// SPDX-License-Identifier: Apache-2.0
/**
 * Left panel of the studio: searchable, grouped layer list.
 *
 *   const panel = createLayerPanel(container, {
 *     thumbUrl(layer, thumbRev) -> url | null,          // layer thumbnail
 *     onSelect(tag | null), onVisible(tag, visible), onSolo(tag | null), onShowAll(), onHideAll(),
 *   });
 *   panel.setLayers(state.layers, { rev, groups })      // render / update in place (rows are reused, thumbnails do not flicker)
 *   panel.select(tag, { scroll: true })                 // programmatic selection (the canvas picked a layer)
 *
 * Keyboard (focus on a row): Up/Down move the selection, Space toggles the eye, S toggles solo, Home/End jump.
 * The panel owns the preview-only "hidden" and "solo" state and reports changes through the callbacks.
 */
import { el, icon, GROUP_LABELS, GROUP_ORDER, groupOf, labelOf, uid } from "./studio-util.js";

export function createLayerPanel(container, opts = {}) {
  const { thumbUrl = () => null, onSelect = () => {}, onVisible = () => {}, onSolo = () => {}, onShowAll = () => {}, onHideAll = () => {} } = opts;
  const id = uid("lp");

  let layers = [];
  let groupLabels = { ...GROUP_LABELS };
  let selected = null;
  let solo = null;
  const hidden = new Set();
  const collapsed = new Set();
  let query = "";
  const rows = new Map(); // tag -> {row, thumbImg, thumbBox, name, badges, eye, soloBtn, thumbKey}
  const thumbRev = new Map(); // tag -> {cur, rev}: bumps only when that layer's current version changes (so thumbnails refresh per layer)
  const groups = new Map(); // group id -> {section, head, body, count}
  let rowSeq = 0;

  // ---- static skeleton
  const search = el("input", { type: "search", class: "lp-search", placeholder: "레이어 검색", "aria-label": "레이어 검색", autocomplete: "off", spellcheck: "false" });
  const showAll = el("button", { type: "button", class: "btn small", text: "모두 보기" });
  const hideAll = el("button", { type: "button", class: "btn small", text: "모두 숨기기" });
  const soloChip = el("button", { type: "button", class: "lp-solochip", hidden: true });
  const empty = el("p", { class: "lp-empty muted small", hidden: true, text: "일치하는 레이어가 없습니다." });
  const groupsBox = el("div", { class: "lp-groups" });
  const hint = el("p", { class: "lp-hint small muted", text: "↑↓ 이동 · Space 보이기 · S 솔로" });
  const summary = el("p", { class: "lp-summary small muted", "aria-live": "polite" });
  container.classList.add("lp");
  container.append(
    el("div", { class: "lp-head" },
      el("label", { class: "lp-searchbox" }, icon("search", 16), search),
      el("div", { class: "lp-actions" }, showAll, hideAll),
      soloChip),
    el("div", { class: "lp-scroll" }, groupsBox, empty),
    el("div", { class: "lp-foot" }, summary, hint));

  // ---- rows
  function makeRow(layer) {
    const eye = el("button", { type: "button", class: "lp-eye", tabindex: "-1", "aria-pressed": "true" }, icon("eye", 16));
    const soloBtn = el("button", { type: "button", class: "lp-solo", tabindex: "-1", "aria-pressed": "false", text: "S" });
    const thumbImg = el("img", { alt: "", decoding: "async", loading: "lazy" });
    const thumbBox = el("span", { class: "lp-thumb checker" }, thumbImg);
    const name = el("span", { class: "lp-name" });
    const badges = el("span", { class: "lp-badges" });
    const row = el("div", { class: "lp-row", role: "option", id: `${id}-r${rowSeq++}`, "data-tag": layer.tag, tabindex: "-1", "aria-selected": "false" },
      eye, thumbBox, el("span", { class: "lp-main" }, name, badges), soloBtn);
    const refs = { row, thumbImg, thumbBox, name, badges, eye, soloBtn, thumbKey: "" };
    thumbImg.addEventListener("error", () => { thumbBox.classList.add("is-missing"); thumbImg.removeAttribute("src"); refs.thumbKey = ""; });
    eye.addEventListener("click", (e) => { e.stopPropagation(); toggleVisible(layer.tag); });
    soloBtn.addEventListener("click", (e) => { e.stopPropagation(); toggleSolo(layer.tag); });
    row.addEventListener("click", () => selectTag(layer.tag, { focus: true }));
    row.addEventListener("keydown", (e) => onRowKey(e, layer.tag));
    return refs;
  }

  function badgeList(l) {
    const out = [];
    if (l.enabled === false) out.push(["제외됨", "bad"]);
    if (l.empty) out.push(["비어 있음", ""]);
    if (l.current && l.current !== "v0") out.push(["편집됨", "accent"]);
    const cand = (l.versions || []).filter((v) => v.kind === "regen" && v.id !== l.current).length;
    if (cand) out.push([`후보 ${cand}`, "warn"]);
    return out;
  }

  function updateRow(refs, l, rev) {
    const label = l.label || labelOf(l.tag);
    refs.name.textContent = label;
    refs.row.title = `${label} (${l.tag})`;
    refs.row.classList.toggle("is-empty", !!l.empty);
    refs.row.classList.toggle("is-excluded", l.enabled === false);
    refs.badges.replaceChildren(...badgeList(l).map(([t, tone]) => el("span", { class: `lp-badge ${tone}`, text: t })));
    refs.eye.disabled = !!l.empty;
    refs.soloBtn.disabled = !!l.empty;
    refs.eye.setAttribute("aria-label", `${label} 보이기`);
    refs.soloBtn.setAttribute("aria-label", `${label}만 보기 (솔로)`);
    refs.eye.title = `${label} 보이기·숨기기 (미리보기에서만)`;
    refs.soloBtn.title = `${label}만 보기 (솔로)`;
    // thumbnail: empty layers get a placeholder and no request; the URL changes only when the current version changes
    if (l.empty) {
      refs.thumbBox.classList.add("is-missing");
      refs.thumbImg.removeAttribute("src");
      refs.thumbKey = "";
    } else {
      const t = thumbRev.get(l.tag);
      const key = `${l.current}@${t ? t.rev : 0}`;
      if (key !== refs.thumbKey) {
        const url = thumbUrl(l, t ? t.rev : rev);
        if (url) { refs.thumbBox.classList.remove("is-missing"); refs.thumbImg.src = url; refs.thumbKey = key; }
        else refs.thumbBox.classList.add("is-missing");
      }
    }
    paintRowState(l.tag, refs);
  }

  function paintRowState(tag, refs = rows.get(tag)) {
    if (!refs) return;
    const vis = !hidden.has(tag);
    const isSolo = solo === tag;
    refs.eye.setAttribute("aria-pressed", String(vis));
    refs.eye.replaceChildren(icon(vis ? "eye" : "eyeOff", 16));
    refs.row.classList.toggle("is-hidden", !vis && !isSolo);
    refs.row.classList.toggle("is-dimmed", solo != null && !isSolo);
    refs.soloBtn.setAttribute("aria-pressed", String(isSolo));
    const sel = selected === tag;
    refs.row.classList.toggle("is-selected", sel);
    refs.row.setAttribute("aria-selected", String(sel));
  }

  function makeGroup(g) {
    const body = el("div", { class: "lp-list", role: "listbox", "aria-label": `${groupLabels[g] || g} 레이어` });
    const count = el("span", { class: "lp-gcount" });
    const head = el("button", { type: "button", class: "lp-ghead", "aria-expanded": "true", "aria-controls": `${id}-g-${g}` }, icon("chevronDown", 14), el("span", { class: "lp-gname", text: groupLabels[g] || g }), count);
    body.id = `${id}-g-${g}`;
    const section = el("section", { class: "lp-group", "data-group": g }, head, body);
    head.addEventListener("click", () => toggleGroup(g));
    const refs = { section, head, body, count, name: head.querySelector(".lp-gname") };
    return refs;
  }

  function toggleGroup(g, open) {
    const isOpen = open ?? collapsed.has(g);
    if (isOpen) collapsed.delete(g); else collapsed.add(g);
    const refs = groups.get(g);
    if (!refs) return;
    refs.section.classList.toggle("is-collapsed", !isOpen);
    refs.head.setAttribute("aria-expanded", String(isOpen));
    refs.head.replaceChildren(icon(isOpen ? "chevronDown" : "chevronRight", 14), refs.name, refs.count);
  }

  // ---- state changes
  function toggleVisible(tag, on) {
    const vis = on ?? hidden.has(tag);
    if (vis) hidden.delete(tag); else hidden.add(tag);
    paintRowState(tag);
    paintSummary();
    onVisible(tag, vis);
  }
  function toggleSolo(tag) {
    solo = solo === tag ? null : tag;
    paintAll();
    onSolo(solo);
  }
  function selectTag(tag, { focus = false, scroll = false, silent = false } = {}) {
    const prev = selected;
    selected = tag;
    if (prev && prev !== tag) paintRowState(prev);
    if (tag) {
      const refs = rows.get(tag);
      if (refs) {
        const g = refs.row.closest(".lp-group")?.dataset.group;
        if (g && collapsed.has(g)) toggleGroup(g, true);
        for (const r of rows.values()) r.row.tabIndex = -1;
        refs.row.tabIndex = 0;
        paintRowState(tag, refs);
        if (scroll) refs.row.scrollIntoView({ block: "nearest" });
        if (focus) refs.row.focus({ preventScroll: true });
      }
    }
    if (!silent) onSelect(tag);
  }

  function visibleRows() { // DOM order, only rows that are filtered in and whose group is open
    return [...groupsBox.querySelectorAll(".lp-group:not(.is-collapsed) .lp-row:not([hidden])")];
  }
  function onRowKey(e, tag) {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const list = visibleRows();
    const at = list.findIndex((r) => r.dataset.tag === tag);
    const go = (k) => { e.preventDefault(); const r = list[Math.max(0, Math.min(list.length - 1, k))]; if (r) selectTag(r.dataset.tag, { focus: true, scroll: true }); };
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(list.length - 1);
    else if (e.key === " " || e.code === "Space") { e.preventDefault(); const l = layers.find((x) => x.tag === tag); if (l && !l.empty) toggleVisible(tag); }
    else if (e.key === "s" || e.key === "S") { const l = layers.find((x) => x.tag === tag); if (l && !l.empty) { e.preventDefault(); toggleSolo(tag); } }
    else if (e.key === "Enter") { e.preventDefault(); selectTag(tag, { focus: true }); }
  }

  function paintAll() {
    for (const [tag, refs] of rows) paintRowState(tag, refs);
    paintSummary();
  }
  function paintSummary() {
    const total = layers.filter((l) => !l.empty).length;
    const nHidden = [...hidden].filter((t) => layers.some((l) => l.tag === t && !l.empty)).length;
    summary.textContent = `레이어 ${layers.length}개 (그리는 것 ${total})${nHidden ? ` · 숨김 ${nHidden}` : ""}`;
    soloChip.hidden = solo == null;
    if (solo != null) {
      const l = layers.find((x) => x.tag === solo);
      soloChip.replaceChildren(icon("close", 12), document.createTextNode(` 솔로 해제: ${l ? l.label || labelOf(l.tag) : solo}`));
      soloChip.setAttribute("aria-label", "솔로 해제");
    }
  }

  function applyFilter() {
    const q = query.trim().toLowerCase();
    let any = false;
    for (const [g, refs] of groups) {
      let n = 0;
      for (const r of refs.body.children) {
        const l = layers.find((x) => x.tag === r.dataset.tag);
        const hit = !q || (l && (`${l.label || ""} ${l.tag}`.toLowerCase().includes(q)));
        r.hidden = !hit;
        if (hit) n++;
      }
      refs.section.hidden = n === 0;
      refs.count.textContent = String(n);
      if (n) any = true;
    }
    empty.hidden = any;
  }

  // ---- public: render from state
  function setLayers(next, { rev = 0, groups: gl } = {}) {
    layers = Array.isArray(next) ? next : [];
    if (gl) groupLabels = { ...GROUP_LABELS, ...gl };
    // remember when each layer's current version last changed (drives thumbnail refresh)
    for (const l of layers) {
      const t = thumbRev.get(l.tag);
      if (!t) thumbRev.set(l.tag, { cur: l.current, rev: 0 });
      else if (t.cur !== l.current) { t.cur = l.current; t.rev = rev; }
    }
    const byGroup = new Map();
    for (const l of layers) {
      const g = l.group || groupOf(l.tag);
      if (!byGroup.has(g)) byGroup.set(g, []);
      byGroup.get(g).push(l);
    }
    const gOrder = [...GROUP_ORDER.filter((g) => byGroup.has(g)), ...[...byGroup.keys()].filter((g) => !GROUP_ORDER.includes(g))];
    const seen = new Set();
    for (const g of gOrder) {
      let gr = groups.get(g);
      if (!gr) { gr = makeGroup(g); groups.set(g, gr); }
      gr.name.textContent = groupLabels[g] || g;
      groupsBox.append(gr.section); // (re)orders the sections
      // front-most first, like a layer stack
      const list = [...byGroup.get(g)].sort((a, b) => (b.order ?? 0) - (a.order ?? 0) || String(a.tag).localeCompare(String(b.tag)));
      for (const l of list) {
        seen.add(l.tag);
        let refs = rows.get(l.tag);
        if (!refs) { refs = makeRow(l); rows.set(l.tag, refs); }
        updateRow(refs, l, rev);
        gr.body.append(refs.row); // moving keeps the <img> loaded
      }
    }
    for (const [tag, refs] of [...rows]) if (!seen.has(tag)) { refs.row.remove(); rows.delete(tag); if (selected === tag) selected = null; }
    for (const [g, gr] of [...groups]) if (!byGroup.has(g)) { gr.section.remove(); groups.delete(g); }
    if (solo && !seen.has(solo)) solo = null;
    for (const t of [...hidden]) if (!seen.has(t)) hidden.delete(t);
    // roving tabindex: the selected row (or the first one) is the tab stop
    const stop = (selected && rows.get(selected)) || visibleRows().map((r) => rows.get(r.dataset.tag))[0];
    for (const r of rows.values()) r.row.tabIndex = r === stop ? 0 : -1;
    applyFilter();
    paintAll();
  }

  // ---- header wiring
  search.addEventListener("input", () => { query = search.value; applyFilter(); });
  search.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { const r = visibleRows()[0]; if (r) { e.preventDefault(); selectTag(r.dataset.tag, { focus: true, scroll: true }); } }
    else if (e.key === "Escape" && search.value) { search.value = ""; query = ""; applyFilter(); e.stopPropagation(); }
  });
  showAll.addEventListener("click", () => { hidden.clear(); solo = null; paintAll(); onShowAll(); });
  hideAll.addEventListener("click", () => { solo = null; for (const l of layers) if (!l.empty) hidden.add(l.tag); paintAll(); onHideAll(); });
  soloChip.addEventListener("click", () => { solo = null; paintAll(); onSolo(null); });

  return {
    setLayers,
    select: (tag, o = {}) => selectTag(tag || null, { scroll: true, silent: true, ...o }),
    /** Focus the selected row (or the search box when nothing is selected). */
    focus() { (selected && rows.get(selected) ? rows.get(selected).row : search).focus(); },
    setVisible: (tag, on) => { if (on) hidden.delete(tag); else hidden.add(tag); paintRowState(tag); paintSummary(); },
    setSolo: (tag) => { solo = tag || null; paintAll(); },
    get selected() { return selected; },
    get solo() { return solo; },
    get hidden() { return [...hidden]; },
    get rowCount() { return rows.size; },
    dispose() { container.replaceChildren(); container.classList.remove("lp"); rows.clear(); groups.clear(); },
  };
}
