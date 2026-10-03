// SPDX-License-Identifier: Apache-2.0
// Admin-only list of every job that still exists.  The data endpoints check the admin cookie; this page only draws.
const $ = (id) => document.getElementById(id);
const PAGE = 24;
const STATUS = { done: ["완료", "ok"], running: ["진행 중", "warn"], queued: ["대기", "warn"], failed: ["실패", "bad"] };
let offset = 0, total = 0, loading = false, timer = null, state = { q: "", status: "" };

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmtDur = (s) => (s == null ? "" : s >= 90 ? `${Math.round(s / 60)}분` : `${Math.round(s)}초`);
function ago(t, now) {
  const d = Math.max(0, now - t);
  if (d < 90) return "방금";
  if (d < 5400) return `${Math.round(d / 60)}분 전`;
  if (d < 129600) return `${Math.round(d / 3600)}시간 전`;
  return `${Math.round(d / 86400)}일 전`;
}
function left(t, now) {
  if (!t) return "";
  const d = t - now;
  if (d <= 0) return "곧 삭제";
  return d < 5400 ? `삭제까지 ${Math.round(d / 60)}분` : `삭제까지 ${Math.round(d / 3600)}시간`;
}

function card(j, now) {
  const [label, tone] = STATUS[j.status] || [j.status, ""];
  const thumb = j.has_thumb
    ? `<img src="/api/admin/jobs/${j.id}/thumb" alt="" loading="lazy" decoding="async">`
    : `<div class="adm-ph">${j.status === "failed" ? "실패" : j.status === "done" ? "미리보기 없음" : esc(j.message || label)}</div>`;
  const meta = [ago(j.created_at, now), j.total_s ? `처리 ${fmtDur(j.total_s)}` : "", j.resolution ? `${j.resolution}px` : "",
                j.attempts > 1 ? `재시도 ${j.attempts - 1}회` : ""].filter(Boolean).join(" · ");
  const prog = j.status === "running" ? ` <span class="small muted">${Math.round((j.progress || 0) * 100)}%</span>` : "";
  return `<article class="adm-card" data-id="${j.id}">
    <a class="adm-thumb" href="/j/${j.id}" title="열기">${thumb}</a>
    <div class="adm-body">
      <div class="adm-row"><span class="pill ${tone}">${label}</span>${prog}<code class="small adm-id" title="${j.id}">${j.id.slice(0, 8)}…</code></div>
      <p class="adm-prompt" title="${esc(j.prompt)}">${j.prompt ? esc(j.prompt) : '<span class="muted">(프롬프트 없음)</span>'}</p>
      ${j.error ? `<p class="small adm-err" title="${esc(j.error)}">${esc(j.error)}</p>` : ""}
      <p class="small muted">${meta}${j.delete_after ? `<br>${left(j.delete_after, now)}` : ""}</p>
      <div class="adm-actions"><a class="btn small primary" href="/j/${j.id}">열기</a>
        <button class="btn small danger" data-del="${j.id}">삭제</button></div>
    </div></article>`;
}

async function load(reset) {
  if (loading) return;
  loading = true;
  if (reset) offset = 0;
  const qs = new URLSearchParams({ limit: PAGE, offset, status: state.status, q: state.q });
  try {
    const r = await fetch("/api/admin/jobs?" + qs, { cache: "no-store" });
    if (r.status === 403) { show(false); return; }
    const d = await r.json();
    total = d.total;
    const html = d.items.map((j) => card(j, d.now)).join("");
    if (reset) $("list").innerHTML = html; else $("list").insertAdjacentHTML("beforeend", html);
    offset += d.items.length;
    $("empty").hidden = total > 0;
    $("more").hidden = offset >= total;
    const c = d.counts || {};
    $("summary").textContent = `조건에 맞는 작업 ${total}건 · 지금 대기열 ${d.queue}건`;
    $("counts").innerHTML = ["done", "running", "queued", "failed"].filter((k) => c[k])
      .map((k) => `<button class="pill ${STATUS[k][1]} adm-count${state.status === k ? " on" : ""}" data-status="${k}">${STATUS[k][0]} ${c[k]}</button>`).join("");
    schedule(d.items.some((j) => j.status === "queued" || j.status === "running"));
  } catch (e) {
    $("summary").textContent = "불러오지 못했습니다: " + e.message;
  } finally { loading = false; }
}

function schedule(active) {
  clearTimeout(timer);
  if (active) timer = setTimeout(() => { if (offset <= PAGE) load(true); }, 8000); // only the first page refreshes itself
}

function show(admin) {
  $("gate").hidden = admin; $("panel").hidden = !admin;
  if (admin) load(true);
}

$("more").addEventListener("click", () => load(false));
let t0;
$("q").addEventListener("input", () => { clearTimeout(t0); t0 = setTimeout(() => { state.q = $("q").value.trim(); load(true); }, 250); });
$("status").addEventListener("change", () => { state.status = $("status").value; load(true); });
$("counts").addEventListener("click", (e) => {
  const b = e.target.closest("[data-status]"); if (!b) return;
  state.status = state.status === b.dataset.status ? "" : b.dataset.status; $("status").value = state.status; load(true);
});
$("list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  if (!confirm("이 작업을 지금 삭제할까요? 되돌릴 수 없습니다.")) return;
  const r = await fetch(`/api/jobs/${b.dataset.del}`, { method: "DELETE" });
  if (r.ok) { b.closest(".adm-card")?.remove(); total -= 1; offset -= 1; load(true); }
});
window.addEventListener("i2l-admin-changed", () => location.reload());

(async () => {
  let admin = false;
  try { admin = !!(await (await fetch("/api/info", { cache: "no-store" })).json()).admin; } catch (e) { /* offline */ }
  show(admin);
})();
