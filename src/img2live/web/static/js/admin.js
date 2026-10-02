// SPDX-License-Identifier: Apache-2.0
// Admin mode: Alt+Shift+M opens a password prompt (or the logout prompt when already signed in).  The server sets a signed
// cookie; admins have no daily or queue limit.  Nothing on the page advertises this.
const STATE = { admin: false };

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "class") n.className = v; else n.setAttribute(k, v); }
  for (const c of kids) n.append(c);
  return n;
}

function badge() {
  let b = document.getElementById("adminBadge");
  if (STATE.admin && !b) {
    b = el("span", { id: "adminBadge", class: "pill ok admin-badge", title: "관리자 모드 (Alt+Shift+M)" }, "관리자");
    (document.querySelector("header.site .wrap") || document.body).append(b);
  } else if (!STATE.admin && b) b.remove();
}

async function refresh() {
  try { STATE.admin = !!(await (await fetch("/api/info", { cache: "no-store" })).json()).admin; } catch (e) { /* offline: keep state */ }
  badge();
}

function closeDialog() { document.getElementById("adminOverlay")?.remove(); }

function openDialog() {
  closeDialog();
  const err = el("p", { class: "admin-err", role: "alert" });
  const box = el("form", { class: "admin-box", autocomplete: "off" });
  const done = (admin) => { STATE.admin = admin; badge(); closeDialog(); window.dispatchEvent(new Event("i2l-admin-changed")); };
  const cancel = el("button", { type: "button", class: "btn ghost" }, "닫기");
  cancel.addEventListener("click", closeDialog);
  if (STATE.admin) {
    const out = el("button", { type: "submit", class: "btn" }, "로그아웃");
    box.append(el("h2", {}, "관리자 모드"), el("p", { class: "muted" }, "사용 중입니다. 하루 제한과 대기열 제한이 없습니다."), err, el("div", { class: "admin-row" }, out, cancel));
    box.addEventListener("submit", async (e) => { e.preventDefault(); await fetch("/api/admin/logout", { method: "POST" }); done(false); });
  } else {
    const pw = el("input", { type: "password", name: "password", autocomplete: "off", placeholder: "비밀번호", "aria-label": "관리자 비밀번호" });
    const go = el("button", { type: "submit", class: "btn primary" }, "로그인");
    box.append(el("h2", {}, "관리자 모드"), pw, err, el("div", { class: "admin-row" }, go, cancel));
    box.addEventListener("submit", async (e) => {
      e.preventDefault(); err.textContent = ""; go.disabled = true;
      try {
        const r = await fetch("/api/admin/login", { method: "POST", body: new URLSearchParams({ password: pw.value }) });
        const j = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(j.detail || `오류 ${r.status}`);
        done(true);
      } catch (x) { err.textContent = x.message; pw.select(); } finally { go.disabled = false; }
    });
    setTimeout(() => pw.focus(), 0);
  }
  const overlay = el("div", { id: "adminOverlay", class: "admin-overlay" }, box);
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) closeDialog(); });
  document.body.append(overlay);
}

window.addEventListener("keydown", (e) => {
  if (e.altKey && e.shiftKey && e.code === "KeyM") { e.preventDefault(); document.getElementById("adminOverlay") ? closeDialog() : openDialog(); }
  else if (e.key === "Escape") closeDialog();
});
refresh();
