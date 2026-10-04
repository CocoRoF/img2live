// SPDX-License-Identifier: Apache-2.0
// "보고서" tab: the job's report.json as compact sections (ported from the old result page, laid out for a narrow column).
import { esc, labelOf, capKeyKo, capTextKo } from "./studio-util.js";

function statusPill(s) {
  const text = String(s);
  const k = text.startsWith("ok") ? "ok" : text.startsWith("degraded") ? "warn" : text.startsWith("unavailable") ? "bad" : "";
  const detail = text.includes(":") ? text.split(":").slice(1).join(":").trim() : "";
  const head = text.split(":")[0];
  const label = { ok: "정상", degraded: "대체 방식", unavailable: "불가" }[head.trim()] || capTextKo(head);
  return `<span class="pill ${k}">${esc(label)}</span>${detail ? ` <span class="small muted">${esc(capTextKo(detail))}</span>` : ""}`;
}

const pct = (v, d = 1) => (Number.isFinite(v) ? `${(v * 100).toFixed(d)}%` : "-");
const sec = (title, body, note = "") => `<section class="in-sec"><h3>${title}</h3>${body}${note ? `<p class="small muted">${note}</p>` : ""}</section>`;

/** @param {object} r report.json  @param {object} job public job json */
export function reportHtml(r, job = {}) {
  const parts = [];
  const cap = Object.entries(r.capability || {}).map(([k, v]) => `<tr><td>${esc(capKeyKo(k))}</td><td>${statusPill(v)}</td></tr>`).join("");
  parts.push(sec("기능별 상태", `<div class="scroll-x"><table class="t"><tbody>${cap || '<tr><td class="muted">기록 없음</td></tr>'}</tbody></table></div>`,
    "이 퍼펫이 무엇을 할 수 있고 무엇을 못 하는지 그대로 적습니다. <b>대체 방식</b> = 동작하지만 다른 방법으로 처리, <b>불가</b> = 할 수 없음."));

  const spec = r.rigSpec || {};
  const notes = (spec.notes || []).map((n) => `<li>${esc(n)}</li>`).join("");
  parts.push(sec("프롬프트 해석", `<p class="small mono">${esc(spec.raw_prompt || "(없음)")}</p><ul class="small">${notes}</ul>
    <dl class="kv"><dt>동작 크기</dt><dd>×${(spec.motion_intensity ?? 1).toFixed(1)}</dd><dt>머리 범위</dt><dd>×${(spec.head_range ?? 1).toFixed(1)}</dd>
    <dt>머리카락</dt><dd>×${(spec.hair_strength ?? 1).toFixed(1)}</dd><dt>깜빡임</dt><dd>${spec.blink ? "켬" : "끔"}</dd><dt>대기 동작</dt><dd>${spec.idle ? "켬" : "끔"}</dd></dl>`));

  const q = r.qa || {};
  if (Object.keys(q).length) {
    parts.push(sec("수치 QA", `<dl class="kv"><dt>판정</dt><dd>${q.passed ? '<span class="pill ok">통과</span>' : '<span class="pill bad">미통과</span>'}</dd>
      <dt>시험한 포즈</dt><dd>${esc(q.poses_tested ?? "-")}</dd>
      <dt>접힘 비율(최대)</dt><dd>${Number.isFinite(q.max_flipped_fraction) ? (q.max_flipped_fraction * 100).toFixed(2) + "%" : "-"} <span class="small muted">(한도 2%)</span></dd>
      <dt>최악 메시</dt><dd>${esc(q.worst_mesh || "-")}</dd><dt>최대 신축(p99)</dt><dd>${esc(q.max_stretch_p99 ?? "-")}×</dd>
      <dt>자동 감쇠</dt><dd>${Object.keys(q.auto_damped || {}).length ? esc(JSON.stringify(q.auto_damped)) : "없음"}</dd></dl>`));
  }

  // fidelity / clean-up (the pass that drops generated detail the source contradicts)
  const dec = r.decompose || {};
  const fid = Object.entries(dec.fidelity || {}).filter(([, v]) => v > 0.004).sort((a, b) => b[1] - a[1]);
  const cl = dec.cleanup || null;
  if (cl || fid.length || (dec.attempts || []).length) {
    let body = "";
    if (cl) {
      body += `<dl class="kv"><dt>실루엣 판정</dt><dd>${cl.silhouette_ok ? '<span class="pill ok">일치</span>' : '<span class="pill warn">불확실</span>'} <span class="small muted">${pct(cl.silhouette_frac)}</span></dd>
        <dt>심각한 문제</dt><dd>${(cl.severe || []).length ? esc((cl.severe || []).map(labelOf).join(", ")) : "없음"}</dd>
        <dt>제거한 점 잡티</dt><dd>${esc(cl.removed_specks ?? 0)}</dd><dt>덮이지 않은 면적</dt><dd>${pct(cl.uncovered_frac, 2)}</dd></dl>`;
      const filled = Object.entries(cl.filled || {});
      if (filled.length) body += `<p class="small muted">소스에서 채워 넣은 픽셀: ${filled.map(([k, v]) => `${esc(labelOf(k))} ${esc(v)}px`).join(", ")}</p>`;
      if (cl.note) body += `<p class="small muted">${esc(cl.note)}</p>`;
    }
    if (fid.length) body += `<div class="scroll-x"><table class="t"><thead><tr><th>부품</th><th>소스와 달라 지운 비율</th></tr></thead><tbody>${fid.map(([k, v]) => `<tr><td>${esc(labelOf(k.replace(/^canvas:/, "")))}${k.startsWith("canvas:") ? ' <span class="small muted">(캔버스)</span>' : ""}</td><td>${pct(v)}</td></tr>`).join("")}</tbody></table></div>`;
    const att = dec.attempts || [];
    if (att.length > 1) body += `<p class="small muted">분해를 ${att.length}번 시도했습니다 (시드 ${att.map((a) => esc(a.seed)).join(" → ")}).</p>`;
    parts.push(sec("충실도·자동 정리", body, "생성 결과가 소스 이미지와 어긋나는 부분을 줄이는 자동 정리 기록입니다."));
  }

  const st = r.rig_stats || r.stats;
  if (st) parts.push(sec("리그 통계", `<dl class="kv"><dt>메시</dt><dd>${esc(st.meshes)}</dd><dt>정점</dt><dd>${esc(st.vertices)}</dd><dt>삼각형</dt><dd>${esc(st.triangles)}</dd><dt>파라미터</dt><dd class="small">${esc((st.params || []).join(", "))}</dd></dl>`));

  const eng = r.engine || {};
  const tr = Object.entries(r.timings || {}).map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}s</td></tr>`).join("");
  parts.push(sec("엔진·소요 시간", `<dl class="kv"><dt>엔진</dt><dd>${esc(eng.engine || "-")}</dd><dt>모델</dt><dd class="small mono">${esc(eng.repo || "-")}</dd><dt>양자화</dt><dd>${esc(eng.quant || "-")}</dd>
    <dt>해상도·시드·스텝</dt><dd>${esc(r.resolution ?? "-")}px · ${esc(r.seed ?? "-")} · ${esc(r.steps ?? "-")}</dd></dl>${tr ? `<div class="scroll-x"><table class="t"><tbody>${tr}</tbody></table></div>` : ""}`));

  const g = r.gate || job.gate || {};
  if (g && (g.ratings || g.top_tags)) {
    parts.push(sec("안전 검사 기록", `<dl class="kv"><dt>등급 점수</dt><dd class="small mono">${esc(JSON.stringify(g.ratings || {}))}</dd>
      <dt>상위 태그</dt><dd class="small">${esc((g.top_tags || []).slice(0, 10).map((x) => x[0] + " " + x[1]).join(", "))}</dd></dl>`,
      "업로드 시 태거가 계산한 값입니다(판정에만 쓰이며 작업과 함께 삭제됩니다)."));
  }
  return parts.join("");
}
