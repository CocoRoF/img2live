// SPDX-License-Identifier: Apache-2.0
// Admin-only list of every job that still exists.  The data endpoints check the admin cookie; this page only draws.
import { STATUS, card } from "./pcard.js";
const $ = (id) => document.getElementById(id);
const PAGE = 24;
let offset = 0, total = 0, loading = false, timer = null, state = { q: "", status: "" };

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
    const html = d.items.map((j) => card(j, d.now, { admin: true })).join("");
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
  if (r.ok) { b.closest(".pcard")?.remove(); total -= 1; offset -= 1; load(true); }
});
window.addEventListener("i2l-admin-changed", () => location.reload());

(async () => {
  let admin = false;
  try { admin = !!(await (await fetch("/api/info", { cache: "no-store" })).json()).admin; } catch (e) { /* offline */ }
  show(admin);
})();
