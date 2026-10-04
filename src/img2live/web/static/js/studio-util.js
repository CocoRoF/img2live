// SPDX-License-Identifier: Apache-2.0
// Small helpers shared by the studio modules: DOM builder, inline SVG icons, formatting, labels, an event emitter.

/** el("div", {class:"x", text:"hi", onclick:fn, "aria-label":"..."}, child, ...) — null/false attrs and children are skipped. */
export function el(tag, attrs, ...children) {
  const node = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === undefined || v === null || v === false) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else if (k === "html") node.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
      else node.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const c of children) if (c !== undefined && c !== null && c !== false) node.append(c);
  return node;
}

export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmtBytes = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : (n / 1024).toFixed(0) + " KB");
export const fmtInt = (n) => (Number.isFinite(n) ? Math.round(n).toLocaleString("ko-KR") : "-");
export const fmtDur = (s) => (s == null ? "-" : s >= 90 ? `${Math.round(s / 60)}분` : `${Math.round(s)}초`);

/** Epoch seconds (or ms, or an ISO string) -> "방금", "3분 전", "2시간 전", "3일 전". */
export function agoText(t, nowMs = Date.now()) {
  let sec = typeof t === "string" ? Date.parse(t) / 1000 : Number(t);
  if (!Number.isFinite(sec) || sec <= 0) return "";
  if (sec > 1e11) sec /= 1000;
  const d = Math.max(0, nowMs / 1000 - sec);
  if (d < 60) return "방금";
  if (d < 3600) return `${Math.round(d / 60)}분 전`;
  if (d < 86400) return `${Math.round(d / 3600)}시간 전`;
  return `${Math.round(d / 86400)}일 전`;
}

// ------------------------------------------------------------------------------------------------ icons
// 24x24 stroke icons (rounded caps/joins), drawn here so the page needs no icon font or library.
const ICONS = {
  eye: '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  eyeOff: '<path d="M3 3l18 18"/><path d="M6.6 6.7C3.9 8.5 2 12 2 12s3.6 7 10 7c1.7 0 3.2-.4 4.5-1M10.6 5.1A10.9 10.9 0 0 1 12 5c6.4 0 10 7 10 7a17 17 0 0 1-3.2 4.2"/><path d="M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5 9-5z"/><path d="M3 13l9 5 9-5"/>',
  sliders: '<path d="M4 6h8M18 6h2M4 12h2M12 12h8M4 18h10M20 18h0"/><circle cx="15" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
  fit: '<path d="M4 9V5a1 1 0 0 1 1-1h4M20 9V5a1 1 0 0 0-1-1h-4M4 15v4a1 1 0 0 0 1 1h4M20 15v4a1 1 0 0 1-1 1h-4"/>',
  head: '<circle cx="12" cy="8" r="4"/><path d="M4 21c1-4.5 4.2-7 8-7s7 2.5 8 7"/>',
  grid: '<path d="M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18"/>',
  play: '<path d="M7 4.5v15l12-7.5z"/>',
  pause: '<path d="M8 5v14M16 5v14"/>',
  record: '<circle cx="12" cy="12" r="5.5" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="9"/>',
  stop: '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/>',
  film: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
  camera: '<path d="M4 8h3l2-3h6l2 3h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/><circle cx="12" cy="13" r="3.5"/>',
  panelLeft: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/>',
  panelRight: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/>',
  trash: '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-12M9 7V4h6v3"/>',
  chevronDown: '<path d="M6 9l6 6 6-6"/>',
  chevronRight: '<path d="M9 6l6 6-6 6"/>',
  up: '<path d="M6 15l6-6 6 6"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
  pencil: '<path d="M4 20l1-4L16.5 4.5a2.1 2.1 0 0 1 3 3L8 19z"/><path d="M14 7l3 3"/>',
  refresh: '<path d="M20 11a8 8 0 0 0-14.5-4M4 5v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4M20 19v-4h-4"/>',
  undo: '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/>',
  close: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12l5 5 9-10"/>',
  arrowLeft: '<path d="M19 12H5M11 6l-6 6 6 6"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>',
  focus: '<circle cx="12" cy="12" r="3"/><path d="M12 3v3M12 18v3M3 12h3M18 12h3"/>',
};

/** Inline SVG icon element (decorative: aria-hidden). */
export function icon(name, size = 18) {
  const span = document.createElement("span");
  span.className = "ic";
  span.setAttribute("aria-hidden", "true");
  span.innerHTML = `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" focusable="false">${ICONS[name] || ""}</svg>`;
  return span;
}

// ------------------------------------------------------------------------------------------------ labels
// Same vocabulary as the server (studio/labels.py).  Used for the degraded mode (no /studio endpoint) and as a fallback.
export const LABELS = {
  "front hair": "앞머리", "back hair": "뒷머리", face: "얼굴", eyewhite: "눈 흰자", irides: "홍채", eyelash: "속눈썹", eyebrow: "눈썹",
  nose: "코", mouth: "입", ears: "귀", earwear: "귀걸이", eyewear: "안경", headwear: "머리 장식", neck: "목", neckwear: "목걸이·목 장식",
  topwear: "상의", handwear: "팔·손", bottomwear: "하의", legwear: "다리", footwear: "신발", tail: "꼬리", wings: "날개", objects: "소품",
};
export const GROUPS = {
  hair: ["front hair", "back hair"],
  face: ["face", "eyewhite", "irides", "eyelash", "eyebrow", "nose", "mouth", "ears", "earwear", "eyewear", "headwear"],
  body: ["neck", "neckwear", "topwear", "handwear", "bottomwear", "legwear", "footwear"],
  other: ["tail", "wings", "objects"],
};
export const GROUP_LABELS = { hair: "머리카락", face: "얼굴", body: "몸", other: "기타" };
export const GROUP_ORDER = ["hair", "face", "body", "other"];
const TAG_GROUP = Object.fromEntries(Object.entries(GROUPS).flatMap(([g, ts]) => ts.map((t) => [t, g])));
export const groupOf = (tag) => TAG_GROUP[tag] || "other";
export const labelOf = (tag) => LABELS[tag] || String(tag).replace(/_/g, " ");

// ------------------------------------------------------------------------------------------------ misc
/** Tiny event emitter: on(name, fn) -> off(); emit(name, ...args). */
export function emitter() {
  const map = new Map();
  return {
    on(name, fn) {
      if (!map.has(name)) map.set(name, new Set());
      map.get(name).add(fn);
      return () => map.get(name)?.delete(fn);
    },
    emit(name, ...args) {
      for (const fn of [...(map.get(name) || [])]) {
        try { fn(...args); } catch (e) { console.error(e); }
      }
    },
    clear() { map.clear(); },
  };
}

/** localStorage that never throws (private windows, blocked storage). */
export const store = {
  get(key, fallback = null) {
    try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
  },
};

export const fmtClock = (ms) => { const s = Math.floor(ms / 1000); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; };

export function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 15000);
}

export const stamp = () => new Date().toISOString().replace(/[-:]/g, "").replace(/\..*/, "").replace("T", "-");

let uidCounter = 0;
export const uid = (prefix = "st") => `${prefix}${++uidCounter}`;

// ------------------------------------------------------------------------------------------------ capability wording
// The compiler writes its capability report in English; the studio shows it in Korean (unknown text is shown as it is).
const CAP_KEYS = {
  layers: "레이어", head_yaw_pitch: "머리 좌우·상하", head_roll: "머리 기울임", blink: "눈 깜빡임", gaze: "시선", brows: "눈썹",
  mouth_open: "입 벌림", lipsync: "립싱크", hair_physics: "머리카락 물리", body: "몸", tail: "꼬리",
  mouth_shapes_aiueo: "모음 입 모양", closed_eye_art: "감은 눈 그림",
};
const CAP_TEXT = [
  [/^no face layer, head box estimated$/, "얼굴 레이어가 없어 머리 범위를 추정했습니다"],
  [/^no closed-eye art; lashes close onto a curve, eye white\/iris collapse$/, "감은 눈 그림이 없어 속눈썹이 닫힘 곡선으로 내려오고 눈 흰자·홍채가 접힙니다"],
  [/^eye white collapses, no lash line$/, "눈 흰자가 접히고 속눈썹 선은 없습니다"],
  [/^eyes not separable, both blink together$/, "양쪽 눈을 나눌 수 없어 함께 깜빡입니다"],
  [/^no eye layers found$/, "눈 레이어가 없습니다"],
  [/^no iris\/eye-white pair$/, "홍채와 눈 흰자 쌍이 없습니다"],
  [/^no eyebrow layer$/, "눈썹 레이어가 없습니다"],
  [/^template mouth overlay \(no generated open-mouth art\)$/, "벌린 입 그림이 없어 템플릿 입 모양을 씁니다"],
  [/^no mouth layer$/, "입 레이어가 없습니다"],
  [/^open\/close only \(no vowel shapes\)$/, "열고 닫기만 되고 모음 모양은 없습니다"],
  [/^no hair layer$/, "머리카락 레이어가 없습니다"],
  [/^no body layers$/, "몸 레이어가 없습니다"],
  [/^no generated vowel shapes yet$/, "모음 모양은 아직 만들지 않습니다"],
  [/^not generated yet$/, "감은 눈 그림은 아직 만들지 않습니다"],
  [/^absent$/, "없음"], [/^off by prompt$/, "프롬프트로 껐습니다"],
  [/^(\d+) layers$/, "$1개"],
];
export const capKeyKo = (key) => CAP_KEYS[key] || String(key).replace(/_/g, " ");
export function capTextKo(text) {
  const t = String(text ?? "").trim();
  for (const [re, ko] of CAP_TEXT) if (re.test(t)) return t.replace(re, ko);
  return t;
}
