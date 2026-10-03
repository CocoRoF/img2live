# SPDX-License-Identifier: Apache-2.0
"""Page structure and layout of the public pages: one job per page, no horizontal overflow at any width,
width policy per page (focused / reading / full).  Real Chrome against the real app (fake engine)."""
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

PASSWORD = "pw-for-layout-test"
SHOTS = ROOT / "bench" / "outputs" / "page_shots"
WIDTHS = [360, 768, 1280, 1680, 1920, 2560]


def until(fn, what, timeout=8.0):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    from PIL import Image, ImageDraw

    tmp = tmp_path_factory.mktemp("pages")
    cfg = Settings(data_dir=tmp)
    cfg.ensure_dirs()
    cfg.gate_enabled, cfg.per_ip_per_day, cfg.admin_password = False, 3, PASSWORD
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 3600, "model_loaded": True}))
    app = create_app(cfg)
    now = time.time()
    ids = []
    for i, (prompt, status) in enumerate((("차분하게, 머리카락은 조금만 흔들리게", "done"), ("활발하고 통통 튀는 느낌", "done"),
                                          ("머리카락과 꼬리를 바람에 크게 흔들리게", "done"), ("대기 중인 것", "queued"),
                                          ("실패한 것", "failed"))):
        jid = f"p{i}" + "abcdefgh"[i] * 4 + "x" * 14
        app.state.db.create(jid, prompt, 1280, 1, "ih", {}, 24 * 365)
        ids.append(jid)
        if status != "queued":
            app.state.db.update(jid, status=status, stage=status, progress=1.0, finished_at=now, timings_json={"total_s": 380.0},
                                error="분해하지 못했습니다" if status == "failed" else None)
        if status == "done":
            d = cfg.jobs_dir / jid
            d.mkdir(parents=True)
            im = Image.new("RGBA", (1280, 1280), (0, 0, 0, 0))
            ImageDraw.Draw(im).ellipse([440 + i * 30, 120, 840 - i * 30, 1180], fill=(90 + i * 40, 80, 200 - i * 40, 255))
            im.save(d / "composite.png")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", ids
    server.should_exit = True
    t.join(5)


def new_page(p, base, ids, width, scheme="light", admin=False, seed_list=True):
    b = p.chromium.launch(executable_path=CHROME_PATH, args=["--no-sandbox"])
    ctx = b.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme)
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    if seed_list:
        page.goto(base + "/about")
        page.evaluate("ids => localStorage.setItem('i2l_mine_v1', JSON.stringify(ids.map(id => ({id, prompt:'', at:0}))))", ids)
    if admin:
        assert page.request.post(base + "/api/admin/login", form={"password": PASSWORD}).ok
    return b, page, errors


def overflow(page):
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def test_each_page_has_one_job_and_the_header_links_them(site):
    base, ids = site
    with sync_api.sync_playwright() as p:
        b, page, errors = new_page(p, base, ids, 1440)
        page.goto(base + "/")
        until(lambda: "GPU" in page.inner_text("#status"), "server status")
        assert page.locator("#form").count() == 1 and page.locator("#drop").count() == 1
        assert page.locator(".pcard").count() == 0 and page.locator("#list").count() == 0           # no gallery here
        assert page.locator(".steps").count() == 0 and "솔직한 한계" not in page.inner_text("main")   # no manual here
        nav = {a.evaluate("e => e.firstChild.textContent.trim()"): a.get_attribute("href") for a in page.locator("header.site nav a").all()}
        assert nav["만들기"] == "/" and nav["내 퍼펫"] == "/mine" and nav["소개"] == "/about" and nav["약관"] == "/terms"
        assert page.locator('header.site a[aria-current="page"]').evaluate("e => e.firstChild.textContent.trim()") == "만들기"
        until(lambda: page.locator("#navMineCount").inner_text() == "5", "the header count of my puppets")

        page.goto(base + "/mine")
        until(lambda: page.locator(".pcard").count() == 5, "five cards")
        assert page.locator("#form").count() == 0 and page.locator(".steps").count() == 0
        assert page.locator('header.site a[aria-current="page"]').evaluate("e => e.firstChild.textContent.trim()") == "내 퍼펫"
        assert page.locator("#total").inner_text() == "5건"

        page.goto(base + "/about")
        assert page.locator(".steps .step").count() == 4 and "솔직한 한계" in page.inner_text("main")
        assert page.locator("#form").count() == 0 and page.locator(".pcard").count() == 0
        page.goto(base + "/terms")
        assert "보관 기간" in page.inner_text("main") and page.locator("#form").count() == 0
        assert errors == [], errors
        b.close()


@pytest.mark.parametrize("width", WIDTHS)
def test_no_horizontal_overflow_on_any_page_at_any_width(site, width):
    base, ids = site
    with sync_api.sync_playwright() as p:
        b, page, errors = new_page(p, base, ids, width, admin=True)
        for path, ready in (("/", "#drop"), ("/mine", ".pcard"), ("/about", ".steps"), ("/terms", "article"), ("/admin", ".pcard")):
            page.goto(base + path)
            page.wait_for_selector(ready)
            page.wait_for_timeout(250)
            assert overflow(page) <= 0, (path, width, overflow(page))
        assert errors == [], errors
        b.close()


def test_width_policy_per_page(site):
    """Focused page: centred and capped.  Reading pages: narrow.  Grids (my puppets, admin): the whole width."""
    base, ids = site
    with sync_api.sync_playwright() as p:
        b, page, errors = new_page(p, base, ids, 2560, admin=True)
        width = lambda sel: page.evaluate(f"document.querySelector('{sel}').getBoundingClientRect().width")
        page.goto(base + "/"); page.wait_for_selector("#drop")
        assert width("main .container") <= 1180 + 2          # the create page does not stretch to a 2560px line
        page.goto(base + "/about"); page.wait_for_selector(".steps")
        assert width("main .container") <= 820 + 2
        page.goto(base + "/terms"); page.wait_for_selector("article")
        assert width("main .container") <= 820 + 2
        page.goto(base + "/mine"); page.wait_for_selector(".pcard")
        assert width("main .container") >= 2560 - 4 and width("#list") >= 2560 * 0.9      # the grid uses the width
        assert page.locator(".pcard").first.evaluate("e => e.getBoundingClientRect().width") <= 300   # ... and fills it with more columns
        page.goto(base + "/admin"); page.wait_for_selector(".pcard")
        assert width("main .container") >= 2560 - 4
        assert errors == [], errors
        b.close()


def test_my_puppets_filter_search_sort_delete_and_move(site):
    base, ids = site
    with sync_api.sync_playwright() as p:
        b, page, errors = new_page(p, base, ids, 1440)
        page.on("dialog", lambda d: d.accept())
        page.goto(base + "/mine")
        until(lambda: page.locator(".pcard").count() == 5, "five cards")
        counts = {x.get_attribute("data-s"): x.locator(".n").inner_text() for x in page.locator("#filter button").all()}
        assert counts == {"": "5", "done": "3", "active": "1", "failed": "1"}
        page.click('#filter [data-s="failed"]'); until(lambda: page.locator(".pcard").count() == 1, "failed only")
        page.click('#filter [data-s="active"]'); until(lambda: page.locator(".pcard").count() == 1, "active only")
        page.click('#filter [data-s=""]'); until(lambda: page.locator(".pcard").count() == 5, "all")
        page.fill("#q", "활발"); until(lambda: page.locator(".pcard").count() == 1, "search")
        page.fill("#q", "zzz"); until(lambda: page.locator("#nomatch").is_visible(), "no match message")
        page.fill("#q", ""); until(lambda: page.locator(".pcard").count() == 5, "search cleared")
        first_new = page.locator(".pcard").first.get_attribute("data-id")
        page.select_option("#sort", "old"); until(lambda: page.locator(".pcard").first.get_attribute("data-id") != first_new, "sort flips")
        # move to another device: export text round-trips through import
        page.click("#ioBtn"); page.wait_for_selector("#ioDlg[open]")
        text = page.input_value("#ioText"); assert set(json.loads(text)) == set(ids)
        page.fill("#ioText", "not json"); page.click("#ioImport"); until(lambda: "읽을 수 없는" in page.inner_text("#ioMsg"), "bad text message")
        page.click("#ioClose")
        # delete one (the confirm is accepted)
        victim = ids[4]
        page.click(f'[data-del="{victim}"]')
        until(lambda: page.locator(".pcard").count() == 4, "card removed")
        assert victim not in json.loads(page.evaluate("localStorage.getItem('i2l_mine_v1')") or "[]").__repr__()
        assert errors == [], errors
        b.close()


def test_empty_list_has_its_own_message_and_a_way_to_create(site):
    base, ids = site
    with sync_api.sync_playwright() as p:
        b, page, errors = new_page(p, base, ids, 1280, seed_list=False)
        page.goto(base + "/mine")
        page.wait_for_selector("#empty:not([hidden])")
        assert page.locator("#tools").is_hidden() and page.locator(".pcard").count() == 0
        assert page.locator("#empty a.btn").get_attribute("href") == "/"
        assert errors == [], errors
        b.close()


def test_screenshots_for_review(site):
    base, ids = site
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_api.sync_playwright() as p:
        for scheme in ("light", "dark"):
            for width, height in ((1920, 1080), (1280, 800), (390, 844)):
                b, page, _ = new_page(p, base, ids, width, scheme=scheme, admin=True)
                page.set_viewport_size({"width": width, "height": height})
                for name, path, ready in (("create", "/", "#drop"), ("mine", "/mine", ".pcard"), ("about", "/about", ".steps"), ("terms", "/terms", "article"), ("admin", "/admin", ".pcard")):
                    page.goto(base + path); page.wait_for_selector(ready); page.wait_for_timeout(500)
                    page.screenshot(path=str(SHOTS / f"{name}_{scheme}_{width}.png"), full_page=False)
                b.close()
