// SPDX-License-Identifier: Apache-2.0
// One puppet card, shared by "my puppets" and the admin list.
export const STATUS = { done: ["완료", "ok"], running: ["진행 중", "warn"], queued: ["대기", "warn"], failed: ["실패", "bad"] };
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmtDur = (s) => (s == null ? "" : s >= 90 ? `${Math.round(s / 60)}분` : `${Math.round(s)}초`);
export function ago(t, now) {
  const d = Math.max(0, now - t);
  if (d < 90) return "방금";
  if (d < 5400) return `${Math.round(d / 60)}분 전`;
  if (d < 129600) return `${Math.round(d / 3600)}시간 전`;
  if (d < 86400 * 60) return `${Math.round(d / 86400)}일 전`;
  return `${Math.round(d / 86400 / 30)}개월 전`;
}
export function left(t, now) {
  if (!t) return "";
  const d = t - now;
  if (d <= 0) return "곧 삭제";
  if (d < 5400) return `삭제까지 ${Math.round(d / 60)}분`;
  if (d < 129600) return `삭제까지 ${Math.round(d / 3600)}시간`;
  return `삭제까지 ${Math.round(d / 86400)}일`;
}

/** HTML of a card.  opts.admin shows the error and the auto-delete clock. */
export function card(j, now, opts = {}) {
  const [label, tone] = STATUS[j.status] || [j.status, ""];
  const thumb = j.has_thumb
    ? `<img src="/api/jobs/${j.id}/thumb" alt="" loading="lazy" decoding="async">`
    : `<div class="pph">${j.status === "failed" ? "실패" : j.status === "done" ? "미리보기 없음" : esc(j.message || label)}</div>`;
  const meta = [ago(j.created_at, now), j.total_s ? `처리 ${fmtDur(j.total_s)}` : "", j.resolution ? `${j.resolution}px` : "",
                j.attempts > 1 ? `재시도 ${j.attempts - 1}회` : ""].filter(Boolean).join(" · ");
  const prog = j.status === "running" ? ` <span class="small muted">${Math.round((j.progress || 0) * 100)}%</span>` : "";
  return `<article class="pcard" data-id="${j.id}">
    <a class="pthumb" href="/j/${j.id}" title="열기">${thumb}</a>
    <div class="pbody">
      <div class="prow"><span class="pill ${tone}">${label}</span>${prog}<code class="small pid" title="${j.id}">${j.id.slice(0, 8)}…</code></div>
      <p class="pprompt" title="${esc(j.prompt)}">${j.prompt ? esc(j.prompt) : '<span class="muted">(프롬프트 없음)</span>'}</p>
      ${j.error ? `<p class="small perr" title="${esc(j.error)}">${esc(j.error)}</p>` : ""}
      <p class="small muted">${meta}${opts.admin && j.delete_after ? `<br>${left(j.delete_after, now)}` : ""}</p>
      <div class="pactions"><a class="btn small primary" href="/j/${j.id}">열기</a>
        <button class="btn small danger" data-del="${j.id}">삭제</button></div>
    </div></article>`;
}
