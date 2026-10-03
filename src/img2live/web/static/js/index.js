// SPDX-License-Identifier: Apache-2.0
import { mine, lookup } from "./mine.js";
import { card } from "./pcard.js";
const $ = (id) => document.getElementById(id);
const EXAMPLES = ["차분하게, 머리카락은 조금만 흔들리게", "활발하고 통통 튀는 느낌", "머리카락과 꼬리를 바람에 크게 흔들리게",
  "과장된 큰 동작", "calm and gentle motion", "energetic, lively hair sway", "no blink, static pose"];
let file = null, info = null;

function fmtEta(s) { if (s == null) return "-"; const m = Math.round(s / 60); return m < 1 ? "1분 미만" : `약 ${m}분`; }
function setErr(msg) { const e = $("err"); e.hidden = !msg; e.textContent = msg || ""; }

async function refreshInfo() {
  try {
    info = await (await fetch("/api/info")).json();
  } catch { $("sWorker").textContent = "연결 실패"; return; }
  $("maxMb").textContent = info.limits.max_upload_mb;
  const days = Math.round(info.limits.retention_hours / 24);
  $("ret").textContent = days >= 365 ? `${Math.round(days / 365)}년` : days >= 2 ? `${days}일` : `${info.limits.retention_hours}시간`;
  const ok = info.worker_alive && info.worker_model_loaded;
  $("sWorker").innerHTML = ok ? '<span class="pill ok">준비됨</span>' : (info.worker_alive ? '<span class="pill warn">모델 로딩 중</span>' : '<span class="pill bad">오프라인</span>');
  $("slowNote").hidden = ok;
  $("sQueue").textContent = `${info.queue} / ${info.max_queue}`;
  $("sEta").textContent = info.queue ? fmtEta(info.eta_seconds * (info.queue + 1)) : fmtEta(info.eta_seconds);
  $("limits").innerHTML = `<li>${info.admin ? "관리자 모드: 하루·대기열 제한 없음" : `하루 IP당 ${info.limits.per_ip_per_day}건`}</li><li>최대 ${info.limits.max_upload_mb}MB · ${Math.round(info.limits.max_pixels / 1e6)}MP · 짧은 변 ${info.limits.min_side}px 이상</li><li>동시 대기 ${info.max_queue}건</li><li>한 건 약 ${fmtEta(info.eta_seconds)}</li>`;
  $("codeRow").hidden = !info.access_code_required;
  updateGo();
}

function updateGo() {
  const ready = info && info.worker_alive && info.worker_model_loaded;
  $("go").disabled = !(file && $("consent").checked && ready);
  $("goHint").textContent = !file ? "이미지를 선택하세요" : !$("consent").checked ? "약관에 동의해 주세요" : !ready ? "작업기가 준비되는 중입니다" : "";
}

function setFile(f) {
  setErr("");
  if (!f) return;
  if (!/^image\/(png|jpeg|webp)$/.test(f.type)) { setErr("PNG / JPEG / WebP 파일만 지원합니다."); return; }
  if (info && f.size > info.limits.max_upload_mb * 1024 * 1024) { setErr(`파일이 너무 큽니다(최대 ${info.limits.max_upload_mb}MB).`); return; }
  file = f;
  const url = URL.createObjectURL(f);
  const img = $("preview"); img.src = url; img.hidden = false; $("dropMsg").hidden = true; img.alt = "선택한 이미지 미리보기";
  updateGo();
}

const drop = $("drop");
drop.addEventListener("click", () => $("file").click());
drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("file").click(); } });
$("file").addEventListener("change", (e) => setFile(e.target.files[0]));
["dragenter", "dragover"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => drop.addEventListener(t, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
drop.addEventListener("drop", (e) => setFile(e.dataTransfer.files[0]));
$("consent").addEventListener("change", updateGo);

for (const ex of EXAMPLES) {
  const b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = ex;
  b.addEventListener("click", () => { $("prompt").value = ex; interpret(); }); $("chips").appendChild(b);
}

let tm;
async function interpret() {
  clearTimeout(tm);
  tm = setTimeout(async () => {
    const fd = new FormData(); fd.append("prompt", $("prompt").value);
    try {
      const s = await (await fetch("/api/parse-prompt", { method: "POST", body: fd })).json();
      const box = $("interp"); box.hidden = false;
      box.innerHTML = `<b>이렇게 이해했습니다</b><br>${s.notes.map((n) => "· " + n.replace(/</g, "&lt;")).join("<br>")}<br><span class="small muted">동작 ×${s.motion_intensity.toFixed(1)} · 머리 ×${s.head_range.toFixed(1)} · 머리카락 ×${s.hair_strength.toFixed(1)} · 깜빡임 ${s.blink ? "켬" : "끔"} · 대기 동작 ${s.idle ? "켬" : "끔"}</span>`;
    } catch { /* ignore */ }
  }, 350);
}
$("prompt").addEventListener("input", interpret);

$("form").addEventListener("submit", async (e) => {
  e.preventDefault(); setErr("");
  $("go").disabled = true; $("go").textContent = "업로드·검사 중…";
  const fd = new FormData();
  fd.append("image", file); fd.append("prompt", $("prompt").value); fd.append("resolution", $("res").value);
  fd.append("consent", "yes"); fd.append("access_code", $("code").value || "");
  try {
    const r = await fetch("/api/jobs", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `오류 ${r.status}`);
    mine.add(j.id, $("prompt").value);
    location.href = j.url;
  } catch (err) {
    setErr(err.message); $("go").textContent = "퍼펫 만들기"; updateGo();
  }
});

refreshInfo(); setInterval(refreshInfo, 8000);
window.addEventListener("i2l-admin-changed", refreshInfo);


// ---------------------------------------------------------------- my puppets (this browser's list)
let mineTimer = null;
async function loadMine() {
  const items = mine.list();
  $("mineEmpty").hidden = items.length > 0;
  if (!items.length) { $("mineList").innerHTML = ""; $("mineCount").textContent = ""; return; }
  let d;
  try { d = await lookup(items.map((x) => x.id)); } catch (e) { return; }   // offline: keep what is drawn
  const alive = new Map(d.jobs.map((j) => [j.id, j]));
  const gone = items.filter((x) => !alive.has(x.id)).length;
  if (gone) mine.keepOnly([...alive.keys()]);                                // deleted or expired elsewhere: tidy the list
  const rows = mine.list().map((x) => alive.get(x.id)).filter(Boolean);
  $("mineList").innerHTML = rows.map((j) => card(j, d.now)).join("");
  $("mineCount").textContent = rows.length ? `${rows.length}건` : "";
  $("mineEmpty").hidden = rows.length > 0;
  clearTimeout(mineTimer);
  if (rows.some((j) => j.status === "queued" || j.status === "running")) mineTimer = setTimeout(loadMine, 8000);
}
$("mineList").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  if (!confirm("이 퍼펫을 지금 삭제할까요? 서버에서 바로 지워지고 되돌릴 수 없습니다.")) return;
  const r = await fetch(`/api/jobs/${b.dataset.del}`, { method: "DELETE" });
  if (r.ok || r.status === 404) { mine.remove(b.dataset.del); loadMine(); }
  else alert((await r.json().catch(() => ({}))).detail || `삭제하지 못했습니다 (${r.status})`);
});
$("mineIO").addEventListener("click", () => { const box = $("mineIOBox"); box.hidden = !box.hidden; $("mineText").value = mine.exportText(); $("mineMsg").textContent = ""; });
$("mineCopy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("mineText").value); $("mineMsg").textContent = "복사했습니다."; } catch (e) { $("mineText").select(); $("mineMsg").textContent = "직접 복사해 주세요."; } });
$("mineImport").addEventListener("click", () => {
  const n = mine.importText($("mineText").value.trim());
  $("mineMsg").textContent = n < 0 ? "읽을 수 없는 텍스트입니다." : `${n}건을 추가했습니다.`;
  if (n > 0) loadMine();
});
loadMine();
