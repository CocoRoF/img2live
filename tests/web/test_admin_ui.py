# SPDX-License-Identifier: Apache-2.0
"""Browser test of the admin mode: Alt+Shift+M -> password prompt -> signed in -> limits lifted (real site code, fake engine)."""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
CHROME_PATH = os.environ.get("IMG2LIVE_CHROME", "/usr/bin/google-chrome")
sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
uvicorn = pytest.importorskip("uvicorn")
if not Path(CHROME_PATH).exists():
    pytest.skip(f"{CHROME_PATH} not found (set IMG2LIVE_CHROME)", allow_module_level=True)

from img2live.config import Settings  # noqa: E402
from img2live.server.app import create_app  # noqa: E402

PASSWORD = "pw-for-ui-test"


def until(fn, what, timeout=8.0):
    """Poll a Python predicate (the page's CSP forbids wait_for_function, which evals a string)."""
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture()
def site(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    cfg.ensure_dirs()
    cfg.gate_enabled, cfg.per_ip_per_day, cfg.admin_password = False, 3, PASSWORD
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 3600, "model_loaded": True}))
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(create_app(cfg), host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


def test_alt_shift_m_login_and_logout(site):
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME_PATH, args=["--no-sandbox"])
        page = b.new_context(viewport={"width": 1100, "height": 800}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(site + "/")
        page.wait_for_selector("#limits li")
        assert "하루 IP당 3건" in page.inner_text("#limits")
        assert page.locator("#adminBadge").count() == 0 and page.locator("#adminOverlay").count() == 0   # nothing advertises it

        page.keyboard.press("Alt+Shift+M")
        page.wait_for_selector("#adminOverlay input[type=password]")
        page.fill("#adminOverlay input[type=password]", "wrong")
        page.click("#adminOverlay button[type=submit]")
        until(lambda: "올바르지" in page.inner_text(".admin-err"), "the wrong-password message")
        assert page.locator("#adminBadge").count() == 0

        page.fill("#adminOverlay input[type=password]", PASSWORD)
        page.click("#adminOverlay button[type=submit]")
        page.wait_for_selector("#adminBadge")
        until(lambda: "관리자 모드" in page.inner_text("#limits"), "the limits list to show admin mode")
        assert page.locator("#adminOverlay").count() == 0
        page.reload()                                                       # the session survives a reload
        page.wait_for_selector("#adminBadge")

        page.keyboard.press("Alt+Shift+M")                                  # now offers logout
        page.wait_for_selector("#adminOverlay")
        assert "로그아웃" in page.inner_text("#adminOverlay")
        page.click("#adminOverlay button[type=submit]")
        until(lambda: page.locator("#adminBadge").count() == 0, "the badge to disappear")
        until(lambda: "하루 IP당 3건" in page.inner_text("#limits"), "the daily limit to show again")
        page.keyboard.press("Alt+Shift+M"); page.keyboard.press("Escape")
        assert page.locator("#adminOverlay").count() == 0
        assert errors == []
        b.close()


@pytest.fixture()
def site_with_jobs(tmp_path):
    from PIL import Image, ImageDraw

    cfg = Settings(data_dir=tmp_path)
    cfg.ensure_dirs()
    cfg.gate_enabled, cfg.per_ip_per_day, cfg.admin_password = False, 3, PASSWORD
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 3600, "model_loaded": True}))
    app = create_app(cfg)
    db = app.state.db
    now = time.time()
    ids = {}
    for name, prompt, status in (("ok", "차분하게, 머리카락은 조금", "done"), ("bad", "활발하게", "failed"), ("wait", "대기 중인 것", "queued")):
        jid = "t" + name * 3 + "x" * 14
        db.create(jid, prompt, 1280, 1, "ih", {}, 72)
        ids[name] = jid
        if status != "queued":
            db.update(jid, status=status, stage=status, progress=1.0, finished_at=now, delete_after=now + 3600 * 40,
                      timings_json={"total_s": 421.0, "decompose_attempts": 2},
                      error="분해하지 못했습니다" if status == "failed" else None)
    jdir = cfg.jobs_dir / ids["ok"]
    jdir.mkdir(parents=True)
    im = Image.new("RGBA", (1280, 1280), (0, 0, 0, 0))
    ImageDraw.Draw(im).ellipse([500, 200, 780, 900], fill=(90, 80, 200, 255))
    im.save(jdir / "composite.png")
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        port = sk.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", ids
    server.should_exit = True
    t.join(5)


def test_admin_page_lists_every_puppet(site_with_jobs):
    base, ids = site_with_jobs
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME_PATH, args=["--no-sandbox"])
        page = b.new_context(viewport={"width": 1200, "height": 900}).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("dialog", lambda d: d.accept())
        page.goto(base + "/admin")
        page.wait_for_selector("#gate:not([hidden])")
        assert page.locator("#panel").is_hidden() and page.locator(".pcard").count() == 0   # a visitor sees no jobs

        page.keyboard.press("Alt+Shift+M")
        page.fill("#adminOverlay input[type=password]", PASSWORD)
        page.click("#adminOverlay button[type=submit]")
        page.wait_for_selector(".pcard")                                    # the page reloads itself once signed in
        until(lambda: page.locator(".pcard").count() == 3, "three cards")
        assert page.locator(".pcard").first.get_attribute("data-id") == ids["wait"]   # newest first
        until(lambda: page.locator(f'[data-id="{ids["ok"]}"] img').count() == 1, "the thumbnail")
        until(lambda: page.evaluate(f'document.querySelector(\'[data-id="{ids["ok"]}"] img\').naturalWidth') > 0, "thumbnail loaded")
        assert page.locator(f'[data-id="{ids["ok"]}"] a.btn').get_attribute("href") == f"/j/{ids['ok']}"
        assert "분해하지 못했습니다" in page.inner_text(f'[data-id="{ids["bad"]}"]') and "재시도 1회" in page.inner_text(f'[data-id="{ids["ok"]}"]')
        assert "삭제까지" in page.inner_text(f'[data-id="{ids["ok"]}"]')

        page.click('[data-status="failed"]')                                   # filter by clicking the count
        until(lambda: page.locator(".pcard").count() == 1, "the failed filter")
        page.click('[data-status="failed"]')
        until(lambda: page.locator(".pcard").count() == 3, "filter cleared")
        page.fill("#q", "머리카락")                                             # search by prompt
        until(lambda: page.locator(".pcard").count() == 1, "the search")
        page.fill("#q", "")
        until(lambda: page.locator(".pcard").count() == 3, "search cleared")

        page.click(f'[data-del="{ids["bad"]}"]')                               # delete one (the confirm dialog is accepted)
        until(lambda: page.locator(f'[data-id="{ids["bad"]}"]').count() == 0, "the card to go")
        until(lambda: page.locator(".pcard").count() == 2, "two cards left")

        page.goto(base + "/")                                                  # the badge leads here from any page
        page.wait_for_selector("#adminBadge")
        assert page.locator("#adminBadge").get_attribute("href") == "/admin"
        assert errors == []
        b.close()
