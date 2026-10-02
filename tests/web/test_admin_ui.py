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
