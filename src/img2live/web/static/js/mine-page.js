// SPDX-License-Identifier: Apache-2.0
// "My puppets": this browser's list (localStorage), asked of the server which still exist and in what state.
import { mine, lookup } from "./mine.js";
import { card } from "./pcard.js";
const $ = (id) => document.getElementById(id);
let jobs = [], now = Date.now() / 1000, status = "", query = "", sort = "new", timer = null, loaded = false;

const isActive = (j) => j.status === "queued" || j.status === "running";
const matches = (j) => (!status || (status === "active" ? isActive(j) : j.status === status)) && (!query || (j.prompt || "").toLowerCase().includes(query));

function render() {
  const total = jobs.length;
  const counts = { "": total, done: jobs.filter((j) => j.status === "done").length, active: jobs.filter(isActive).length, failed: jobs.filter((j) => j.status === "failed").length };
  document.querySelectorAll("#filter button").forEach((b) => {
    b.setAttribute("aria-pressed", String(b.dataset.s === status));
    b.querySelector(".n").textContent = counts[b.dataset.s] ? counts[b.dataset.s] : "";
  });
  $("total").textContent = total ? `${total}건` : "";
  $("tools").hidden = total === 0;
  $("empty").hidden = !(loaded && total === 0);
  const rows = jobs.filter(matches).sort((a, b) => (sort === "new" ? b.created_at - a.created_at : a.created_at - b.created_at));
  $("nomatch").hidden = !(total > 0 && rows.length === 0);
  $("list").innerHTML = rows.map((j) => card(j, now)).join("");
}

async function load() {
  const items = mine.list();
  if (!items.length) { jobs = []; loaded = true; render(); return; }
  try {
    const d = await lookup(items.map((x) => x.id));
    jobs = d.jobs; now = d.now; loaded = true;
    if (jobs.length !== items.length) mine.keepOnly(jobs.map((j) => j.id));   // deleted or expired: tidy the list
  } catch (e) { if (!loaded) { $("empty").hidden = true; } return; }            // offline: keep what is drawn
  render();
  clearTimeout(timer);
  if (jobs.some(isActive)) timer = setTimeout(load, 8000);
}

$("list").addEventListener("click", async (e) => {
  const b = e.target.closest("[data-del]"); if (!b) return;
  if (!confirm("이 퍼펫을 지금 삭제할까요? 서버에서 바로 지워지고 되돌릴 수 없습니다.")) return;
  const r = await fetch(`/api/jobs/${b.dataset.del}`, { method: "DELETE" });
  if (r.ok || r.status === 404) { mine.remove(b.dataset.del); jobs = jobs.filter((j) => j.id !== b.dataset.del); render(); }
  else alert((await r.json().catch(() => ({}))).detail || `삭제하지 못했습니다 (${r.status})`);
});
let t0;
$("q").addEventListener("input", () => { clearTimeout(t0); t0 = setTimeout(() => { query = $("q").value.trim().toLowerCase(); render(); }, 150); });
$("filter").addEventListener("click", (e) => { const b = e.target.closest("button[data-s]"); if (!b) return; status = b.dataset.s; render(); });
$("sort").addEventListener("change", () => { sort = $("sort").value; render(); });

// moving the list to another device
const dlg = $("ioDlg");
$("ioBtn").addEventListener("click", () => { $("ioText").value = mine.exportText(); $("ioMsg").textContent = ""; dlg.showModal(); });
$("ioClose").addEventListener("click", () => dlg.close());
$("ioCopy").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("ioText").value); $("ioMsg").textContent = "복사했습니다."; } catch (e) { $("ioText").select(); $("ioMsg").textContent = "직접 복사해 주세요."; } });
$("ioImport").addEventListener("click", async () => {
  const n = mine.importText($("ioText").value.trim());
  $("ioMsg").textContent = n < 0 ? "읽을 수 없는 텍스트입니다." : `${n}건을 추가했습니다.`;
  if (n > 0) await load();
});

load();
