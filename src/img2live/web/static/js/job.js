// SPDX-License-Identifier: Apache-2.0
const $ = (id) => document.getElementById(id);
const jobId = location.pathname.split("/").filter(Boolean).pop();
const F = (p) => `/files/${jobId}/${p}`;
const STAGES = [["queued", "대기"], ["decompose", "레이어 분해(GPU)"], ["layers", "레이어 저장"], ["rig", "리깅·QA"], ["package", "패키징"], ["done", "완료"]];
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtBytes = (n) => (n > 1048576 ? (n / 1048576).toFixed(1) + " MB" : (n / 1024).toFixed(0) + " KB");
const fmtT = (s) => (s == null ? "-" : s >= 90 ? `${Math.round(s / 60)}분` : `${Math.round(s)}초`);
let shown = false, es = null, current = null;

function render(j) {
  current = j;
  const badge = $("badge");
  const map = { queued: ["대기 중", ""], running: ["처리 중", "warn"], done: ["완료", "ok"], failed: ["실패", "bad"] };
  const [t, cls] = map[j.status] || [j.status, ""];
  badge.textContent = t; badge.className = "pill " + cls;
  $("title").textContent = j.status === "done" ? "퍼펫이 준비되었습니다" : j.status === "failed" ? "처리하지 못했습니다" : "퍼펫을 만드는 중…";
  const pct = Math.round((j.progress || 0) * 100);
  $("pfill").style.width = pct + "%"; $("pbar").setAttribute("aria-valuenow", pct);
  const idx = Math.max(0, STAGES.findIndex(([k]) => k === (j.status === "done" ? "done" : j.stage)));
  $("stepper").innerHTML = STAGES.map(([k, label], i) => `<span class="s ${i < idx || j.status === "done" ? "done" : i === idx ? "on" : ""}">${label}</span>`).join("");
  $("msg").textContent = j.status === "running" ? `${pct}% · ${j.message || ""}` : j.message && j.status !== "done" ? j.message : "";
  const e = $("err"); e.hidden = !j.error; e.textContent = j.error || "";
  if (j.status === "queued" || j.status === "running") {
    const parts = [];
    if (j.status === "queued") parts.push(`대기열 ${j.queue_position + 1}번째`);
    if (j.eta_seconds != null) parts.push(`예상 남은 시간 ${fmtT(j.eta_seconds)}`);
    parts.push("이 페이지를 닫아도 작업은 계속되며, 같은 주소로 다시 열 수 있습니다.");
    $("qinfo").textContent = parts.join(" · ");
  } else $("qinfo").textContent = j.finished_at && j.started_at ? `총 ${fmtT(j.finished_at - j.started_at)} 걸렸습니다.` : "";
  if (j.status === "done" && !shown) { shown = true; showResult(j); }
}

function connect() {
  es = new EventSource(`/api/jobs/${jobId}/events`);
  es.onmessage = (m) => { render(JSON.parse(m.data)); };
  es.addEventListener("gone", () => { es.close(); $("title").textContent = "삭제되었거나 만료된 작업입니다"; $("badge").textContent = "없음"; });
  es.onerror = async () => {
    if (current && (current.status === "done" || current.status === "failed")) { es.close(); return; }
    // fall back to polling when SSE drops
    es.close(); setTimeout(poll, 2000);
  };
}
async function poll() {
  try {
    const r = await fetch(`/api/jobs/${jobId}`);
    if (r.status === 404) { $("title").textContent = "삭제되었거나 만료된 작업입니다"; return; }
    const j = await r.json(); render(j);
    if (j.status === "queued" || j.status === "running") setTimeout(poll, 2500);
  } catch { setTimeout(poll, 4000); }
}

// ------------------------------------------------------------------ result
async function showResult(j) {
  $("result").hidden = false;
  const R = j.result;
  const tabs = $("tabs");
  tabs.addEventListener("click", (e) => {
    const b = e.target.closest("button[data-tab]"); if (!b) return;
    for (const x of tabs.querySelectorAll("button")) x.setAttribute("aria-selected", x === b);
    for (const p of document.querySelectorAll(".panel")) p.hidden = p.id !== "p-" + b.dataset.tab;
    if (b.dataset.tab === "live") window.dispatchEvent(new Event("resize"));
  });
  // live viewer (loaded lazily so a viewer error never blocks the rest of the page)
  import("/static/js/viewer.js").then(({ mountViewer }) => mountViewer($("viewerMount"), { puppetUrl: F(R.puppet) }))
    .catch((err) => { $("viewerMount").innerHTML = `<div class="notice bad">뷰어를 불러오지 못했습니다: ${esc(err.message)}</div>`; console.error(err); });
  // pose sheet
  const sheet = R.files.find((f) => f.path === "qa/pose_sheet.png");
  if (sheet) { $("sheetImg").src = F(sheet.path); $("sheetLink").href = F(sheet.path); } else $("p-sheet").innerHTML = '<p class="muted">점검 시트가 없습니다.</p>';
  // layers
  const idx = await (await fetch(F(R.layers_index))).json();
  const card = (l, hires) => {
    if (l.empty) return `<div class="layer" style="opacity:.55;cursor:default"><div class="thumb"><span class="small muted">없음</span></div><div class="meta"><b>${esc(l.tag)}</b>이 이미지에 없음(빈 레이어)</div></div>`;
    return `<button class="layer" data-src="${F(l.file)}" data-name="${esc(l.tag)}" type="button"><div class="thumb"><img loading="lazy" src="${F(l.file)}" alt="${esc(l.tag)}"></div><div class="meta"><b>${esc(l.tag)}</b>${l.w}×${l.h}px${hires ? " · ×" + (1 / l.scale).toFixed(1) + " 해상도" : ""}</div></button>`;
  };
  $("layerGrid").innerHTML = idx.layers.map((l) => card(l, false)).join("");
  $("hiresGrid").innerHTML = (idx.hires || []).map((l) => card(l, true)).join("") || '<p class="muted small">이 작업에는 고해상도 머리 레이어가 없습니다.</p>';
  $("hiresBadge").textContent = idx.hires && idx.hires.length ? `${idx.hires.length}개` : "없음";
  for (const grid of [$("layerGrid"), $("hiresGrid")]) grid.addEventListener("click", (e) => {
    const b = e.target.closest("button.layer"); if (!b) return;
    $("dlgTitle").textContent = b.dataset.name; $("dlgImg").src = b.dataset.src; $("dlgDl").href = b.dataset.src; $("dlgDl").download = b.dataset.name + ".png"; $("dlg").showModal();
  });
  $("dlgClose").onclick = () => $("dlg").close();
  // compare
  const srcUrl = F(R.source_canvas || R.source);
  $("cmpSrc").src = srcUrl; $("cmpComp").src = F(R.composite); $("ovA").src = srcUrl; $("ovB").src = F(R.composite);
  $("ovl").addEventListener("input", (e) => { $("ovB").style.opacity = e.target.value / 100; }); $("ovB").style.opacity = 0.5;
  // report
  const rep = await (await fetch(F(R.report))).json();
  $("reportBox").innerHTML = reportHtml(rep, j);
  // files
  $("dlBox").innerHTML = R.downloads.map((d) => `<a class="btn" href="${F(d.path)}">${esc(d.path.split("/").pop())} <span class="muted small">${fmtBytes(d.size)}</span></a>`).join("") +
    `<a class="btn" href="${F(R.puppet)}">puppet.json</a><a class="btn" href="${F(R.report)}">report.json</a>`;
  $("fileTable").querySelector("tbody").innerHTML = R.files.map((f) => `<tr><td><a href="${F(f.path)}" target="_blank" rel="noopener">${esc(f.path)}</a></td><td>${fmtBytes(f.size)}</td></tr>`).join("");
  $("delBtn").onclick = async () => {
    if (!confirm("이 작업과 모든 결과를 지금 삭제할까요? 되돌릴 수 없습니다.")) return;
    const r = await fetch(`/api/jobs/${jobId}`, { method: "DELETE" });
    if (r.ok) { location.href = "/"; } else alert("삭제하지 못했습니다.");
  };
}

function statusPill(s) {
  const k = s.startsWith("ok") ? "ok" : s.startsWith("degraded") ? "warn" : s.startsWith("unavailable") ? "bad" : "";
  return `<span class="pill ${k}">${esc(s.split(":")[0])}</span> <span class="small muted">${esc(s.includes(":") ? s.split(":").slice(1).join(":").trim() : "")}</span>`;
}
function reportHtml(r, j) {
  const cap = Object.entries(r.capability).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${statusPill(String(v))}</td></tr>`).join("");
  const q = r.qa || {};
  const t = r.timings || {};
  const tr = Object.entries(t).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${v}s</td></tr>`).join("");
  const spec = r.rigSpec || {};
  const notes = (spec.notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  const g = r.gate || {};
  return `
  <div class="grid2" style="grid-template-columns:repeat(auto-fit,minmax(320px,1fr))">
    <div class="card"><h3>기능별 상태 (capability report)</h3><div class="scroll-x"><table class="t"><tbody>${cap}</tbody></table></div>
      <p class="small muted">이 퍼펫이 무엇을 할 수 있고 무엇을 못 하는지 그대로 적습니다. <b>degraded</b> = 동작하지만 대체 방식, <b>unavailable</b> = 불가.</p></div>
    <div class="card"><h3>프롬프트 해석</h3><p class="small mono">${esc(spec.raw_prompt || "(없음)")}</p><ul class="small">${notes}</ul>
      <dl class="kv"><dt>동작 크기</dt><dd>×${(spec.motion_intensity ?? 1).toFixed(1)}</dd><dt>머리 범위</dt><dd>×${(spec.head_range ?? 1).toFixed(1)}</dd><dt>머리카락</dt><dd>×${(spec.hair_strength ?? 1).toFixed(1)}</dd><dt>깜빡임</dt><dd>${spec.blink ? "켬" : "끔"}</dd><dt>대기 동작</dt><dd>${spec.idle ? "켬" : "끔"}</dd></dl></div>
    <div class="card"><h3>수치 QA</h3><dl class="kv"><dt>판정</dt><dd>${q.passed ? '<span class="pill ok">통과</span>' : '<span class="pill bad">미통과</span>'}</dd><dt>시험한 포즈</dt><dd>${q.poses_tested}</dd>
      <dt>접힘 비율(최대)</dt><dd>${(q.max_flipped_fraction * 100).toFixed(2)}% <span class="small muted">(보이는 면적 기준, 한도 2%)</span></dd><dt>최악 메시</dt><dd>${esc(q.worst_mesh || "-")}</dd><dt>최대 신축(p99)</dt><dd>${q.max_stretch_p99}×</dd>
      <dt>자동 감쇠</dt><dd>${Object.keys(q.auto_damped || {}).length ? esc(JSON.stringify(q.auto_damped)) : "없음"}</dd></dl></div>
    <div class="card"><h3>리그 통계</h3><dl class="kv"><dt>메시</dt><dd>${r.rig_stats.meshes}</dd><dt>정점</dt><dd>${r.rig_stats.vertices}</dd><dt>삼각형</dt><dd>${r.rig_stats.triangles}</dd><dt>파라미터</dt><dd class="small">${esc((r.rig_stats.params || []).join(", "))}</dd></dl></div>
    <div class="card"><h3>엔진·소요 시간</h3><dl class="kv"><dt>엔진</dt><dd>${esc(r.engine.engine)}</dd><dt>모델</dt><dd class="small mono">${esc(r.engine.repo || "-")}</dd><dt>양자화</dt><dd>${esc(r.engine.quant || "-")}</dd><dt>해상도·시드·스텝</dt><dd>${r.resolution}px · ${r.seed} · ${r.steps}</dd></dl>
      <div class="scroll-x"><table class="t"><tbody>${tr}</tbody></table></div></div>
    <div class="card"><h3>안전 검사 기록</h3><p class="small muted">업로드 시 태거가 계산한 값입니다(판정에만 쓰이며 작업과 함께 삭제됩니다).</p>
      <dl class="kv"><dt>등급 점수</dt><dd class="small mono">${esc(JSON.stringify(g.ratings || {}))}</dd><dt>상위 태그</dt><dd class="small">${esc((g.top_tags || []).slice(0, 10).map((x) => x[0] + " " + x[1]).join(", "))}</dd></dl></div>
  </div>`;
}

(async () => {
  try {
    const r = await fetch(`/api/jobs/${jobId}`);
    if (r.status === 404) { $("title").textContent = "삭제되었거나 만료된 작업입니다"; $("badge").textContent = "없음"; $("pbar").hidden = true; return; }
    render(await r.json());
    if (current.status === "queued" || current.status === "running") connect();
  } catch (e) { $("title").textContent = "서버에 연결할 수 없습니다"; console.error(e); }
})();
