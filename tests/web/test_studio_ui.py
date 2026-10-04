# SPDX-License-Identifier: Apache-2.0
"""Browser tests of the studio page (/j/<id>): real uvicorn site + real fake-engine job, studio endpoints mocked with page.route.

Needs playwright, /usr/bin/google-chrome (software WebGL2 through SwiftShader) and the synthetic character (no GPU, no model).
The page's CSP forbids ``page.wait_for_function`` (string eval): conditions are polled Python-side with ``until``.
Screenshots (1920x1080 and 1280x800, light and dark) go to bench/outputs/studio_shots/.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(HERE))

CHROME_PATH = os.environ.get("IMG2LIVE_CHROME", "/usr/bin/google-chrome")
CHROME_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist", "--no-sandbox"]
SHOTS = ROOT / "bench" / "outputs" / "studio_shots"
QUIET = "idle=0&blink=0&physics=0"  # a deterministic rest pose

sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
pytest.importorskip("uvicorn")
if not Path(CHROME_PATH).exists():
    pytest.skip(f"{CHROME_PATH} not found (set IMG2LIVE_CHROME)", allow_module_level=True)

import studio_fixture as fx  # noqa: E402


# ------------------------------------------------------------------------------------------------ helpers
def until(fn, what, timeout=10.0):
    end = time.time() + timeout
    last = None
    while time.time() < end:
        try:
            if fn():
                return
        except Exception as e:  # noqa: BLE001 - the page may be mid-navigation; keep polling
            last = e
        time.sleep(0.05)
    raise AssertionError(f"timed out waiting for {what}" + (f" ({last})" if last else ""))


def settle(page, frames: int = 3):
    page.evaluate("(n) => new Promise((res) => { const f = (k) => k <= 0 ? res() : requestAnimationFrame(() => f(k - 1)); f(n); })", frames)


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    s = fx.Site(tmp_path_factory.mktemp("studio_site"))
    yield s
    s.close()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME_PATH, headless=True, args=CHROME_ARGS)
        yield b
        b.close()


class Studio:
    """A page on the studio with every console error / page error / failed request recorded."""

    def __init__(self, browser, site, viewport=(1280, 800), scheme="light", mock=True, can_regen=True):
        self.site = site
        self.ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=scheme)
        self.page = self.ctx.new_page()
        self.errors: list[str] = []
        self.dialogs: list[str] = []
        p = self.page
        p.on("console", lambda m: self.errors.append(f"console.error: {m.text}") if m.type == "error" else None)
        p.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        p.on("requestfailed", lambda r: self.errors.append(f"requestfailed: {r.url} {r.failure}"))
        p.on("response", lambda r: self.errors.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 else None)
        p.on("dialog", self._dialog)
        self.mock = fx.StudioMock(site.job_id, site.jdir, can_regen=can_regen) if mock else None
        if self.mock:
            self.mock.install(p)

    def _dialog(self, d):
        self.dialogs.append(d.message)
        d.accept()

    def open(self, query=QUIET, wait=True, jid=None):
        q = query if "test=" in query else "test=1&" + query
        self.page.goto(f"{self.site.job(jid)}?{q}")
        if wait:
            self.ready()
        return self

    def ready(self, timeout=30000):
        self.page.wait_for_selector("html[data-studio-ready='1']", state="attached", timeout=timeout)
        settle(self.page)

    def js(self, expr, arg=None):
        return self.page.evaluate(expr, arg) if arg is not None else self.page.evaluate(expr)

    def close(self):
        self.ctx.close()

    def __getattr__(self, name):
        return getattr(self.page, name)


@pytest.fixture()
def studio(browser, site):
    made: list[Studio] = []

    def make(**kw):
        s = Studio(browser, site, **kw)
        made.append(s)
        return s

    yield make
    for s in made:
        s.close()


def rect(page, selector):
    return page.evaluate("(s) => { const r = document.querySelector(s).getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height, r: r.right, b: r.bottom}; }", selector)


def ink(s: Studio) -> int:
    """Number of non-white pixels of the stage framebuffer (open with bg=white)."""
    return s.js("() => { const r = window.__studio.stage.renderer.readPixels(); const d = r.data; let n = 0; for (let i = 0; i < d.length; i += 4) if (d[i] !== 255 || d[i + 1] !== 255 || d[i + 2] !== 255) n++; return n; }")


def frame_hash(s: Studio) -> int:
    return s.js("() => { const r = window.__studio.stage.renderer.readPixels(); const d = r.data; let h = 2166136261; for (let i = 0; i < d.length; i += 3) h = Math.imul(h ^ d[i], 16777619) >>> 0; return h; }")


def visible_tags(s: Studio) -> set[str]:
    return set(s.js("() => window.__studio.stage.layers.filter((l) => l.visible).map((l) => l.tag)"))


def row(s: Studio, tag: str):
    return s.page.locator(f'.lp-row[data-tag="{tag}"]')


def screen_point(s: Studio, xy):
    """CSS-px page coordinates of a canvas-space puppet point."""
    return s.js("(pt) => { const st = window.__studio.stage; const c = st.renderer.worldToCss(pt[0], pt[1], { x: 0, y: 0 }); const r = st.canvas.getBoundingClientRect(); return { cx: c.x, cy: c.y, px: r.left + c.x, py: r.top + c.y }; }", list(xy))


# ------------------------------------------------------------------------------------------------ layout
@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080), (800, 900)])
def test_layout_fills_the_viewport_without_a_centred_wrapper(studio, w, h):
    s = studio(viewport=(w, h)).open()
    page = s.page
    hdr = rect(page, "header.site")
    main = rect(page, "main")
    assert abs(main["x"]) < 0.5 and abs(main["w"] - w) < 0.5, main            # main uses the whole width, flush left
    assert abs(main["y"] - hdr["h"]) < 0.5 and abs(main["h"] - (h - hdr["h"])) < 1.5, (main, hdr)   # ... and the remaining height
    st = rect(page, "#result")
    assert abs(st["w"] - w) < 0.5 and abs(st["h"] - main["h"]) < 1.5
    assert s.js("() => [document.documentElement.scrollWidth <= innerWidth, document.documentElement.scrollHeight <= innerHeight]") == [True, True]
    # no ancestor of the stage limits its width or centres it
    chain = s.js("""() => { const out = []; for (let e = document.querySelector('#stageMount'); e; e = e.parentElement) { const c = getComputedStyle(e); out.push([e.tagName + (e.id ? '#' + e.id : ''), c.maxWidth, c.marginLeft, c.marginRight]); } return out; }""")
    for name, max_w, ml, mr in chain:
        assert max_w == "none", (name, max_w)
        assert ml == "0px" and mr == "0px", (name, ml, mr)
    left, center, right = rect(page, "#stLeft"), rect(page, "#stCenter"), rect(page, "#stRight")
    canvas = rect(page, "#stageMount canvas.stage-canvas")
    if w >= 1000:                                                               # [layers 300 | stage 1fr | inspector 360]
        assert abs(left["w"] - 300) < 1.5 and abs(right["w"] - 360) < 1.5
        assert abs(center["w"] - (w - 660)) < 2 and abs(center["x"] - 300) < 2
        assert abs(canvas["w"] - center["w"]) < 1.5 and abs(canvas["h"] - center["h"]) < 1.5
        assert abs(right["r"] - w) < 1.5
    else:                                                                       # single column: panels are drawers
        assert abs(center["w"] - w) < 1.5 and abs(canvas["w"] - w) < 1.5
        assert s.js("() => [document.querySelector('#stLeft').inert, document.querySelector('#stRight').inert]") == [True, True]
    assert s.errors == []


def test_the_test_hook_exists_only_with_test_1(studio, site):
    s = studio()
    s.page.goto(f"{site.job()}?{QUIET}")                                             # no test=1
    s.page.wait_for_selector(".lp-row")
    until(lambda: s.page.locator("#stageMount canvas.stage-canvas").count() == 1, "the stage canvas")
    assert s.js("() => typeof window.__studio") == "undefined"
    assert s.errors == []


@pytest.mark.parametrize("w,h", [(1280, 800), (1920, 1080), (800, 900), (1100, 600)])
def test_fit_and_head_framing_stay_clear_of_the_floating_toolbar(studio, w, h):
    s = studio(viewport=(w, h)).open(QUIET)
    bar = rect(s.page, "#stToolbar")
    box = rect(s.page, "#stageMount canvas.stage-canvas")
    js = "(m) => { const st = window.__studio.stage; st.setCamera(m); const b = m === 'head' ? st.model.headBounds : st.model.bounds; const c = st.renderer.worldToCss(b[0], b[1], { x: 0, y: 0 }); const d = st.renderer.worldToCss(b[2], b[3], { x: 0, y: 0 }); return [c.y, d.y, c.x, d.x, st.renderer.cssWidth, st.renderer.cssHeight]; }"
    for mode in ("fit", "head"):
        top, bottom, left, right, cw, ch = s.js(js, mode)
        assert top >= bar["b"] - box["y"] - 1, (mode, top, bar)                    # the puppet starts below the toolbar ...
        assert bottom <= ch + 1 and left >= -1 and right <= cw + 1, (mode, top, bottom, left, right, cw, ch)   # ... and is fully in view
    assert s.errors == []


def test_panels_collapse_and_resize(studio):
    s = studio(viewport=(1280, 800)).open()
    page = s.page
    assert rect(page, "#stLeft")["w"] > 290
    page.click('[data-tool="left"]')                                           # collapse the layer panel: the stage takes the width
    until(lambda: rect(page, "#stLeft")["w"] < 1, "the layer panel to collapse")
    assert abs(rect(page, "#stCenter")["w"] - (1280 - 360)) < 2
    assert s.js("() => document.querySelector('#stLeft').inert") is True
    until(lambda: abs(rect(page, "#stageMount canvas.stage-canvas")["w"] - (1280 - 360)) < 2, "the canvas to follow")
    page.click('[data-tool="right"]')
    until(lambda: rect(page, "#stRight")["w"] < 1, "the inspector to collapse")
    assert abs(rect(page, "#stCenter")["w"] - 1280) < 2
    page.click('[data-tool="left"]'); page.click('[data-tool="right"]')
    until(lambda: rect(page, "#stLeft")["w"] > 290 and rect(page, "#stRight")["w"] > 350, "both panels back")
    # drag the left handle 80px to the right
    sp = rect(page, "#splitL")
    page.mouse.move(sp["x"] + 1, 300); page.mouse.down(); page.mouse.move(sp["x"] + 81, 300, steps=4); page.mouse.up()
    until(lambda: abs(rect(page, "#stLeft")["w"] - 380) < 2, "the left panel to be 380px wide")
    page.focus("#splitR"); page.keyboard.press("ArrowLeft")                      # keyboard: inspector grows by 16px
    until(lambda: abs(rect(page, "#stRight")["w"] - 376) < 2, "the inspector to grow")
    assert s.errors == []


def test_narrow_screen_uses_drawers(studio):
    s = studio(viewport=(800, 900)).open()
    page = s.page
    assert s.js("() => document.querySelector('#result').dataset.drawer") == "none"
    page.click('[data-tool="left"]')
    until(lambda: s.js("() => document.querySelector('#result').dataset.drawer") == "left", "the layer drawer")
    until(lambda: rect(page, "#stLeft")["x"] >= -1 and rect(page, "#stLeft")["w"] > 250, "the drawer to slide in")
    assert page.locator("#stScrim").is_visible()
    row(s, "topwear").click()                                                  # choosing a layer closes the drawer so the outline is visible
    until(lambda: s.js("() => document.querySelector('#result').dataset.drawer") == "none", "the drawer to close")
    assert s.js("() => window.__studio.selected") == "topwear"
    page.click('[data-tool="right"]')
    until(lambda: s.js("() => document.querySelector('#result').dataset.drawer") == "right", "the inspector drawer")
    assert "상의" in page.inner_text("#stRight")
    page.keyboard.press("Escape")
    until(lambda: s.js("() => document.querySelector('#result').dataset.drawer") == "none", "Esc closes the drawer")
    assert s.errors == []


# ------------------------------------------------------------------------------------------------ layer list
def test_layer_list_groups_rows_and_badges(studio):
    s = studio()
    m = s.mock
    m.add_version("topwear", "edit", "소매 정리", make_current=True)                  # -> 편집됨
    m.add_version("face", "regen", "시드 7", seed=7)                                 # -> 후보 1
    m.add_version("face", "regen", "시드 8", seed=8)                                 # -> 후보 2
    m.layer("nose")["enabled"] = False                                              # -> 제외됨
    s.open()
    page = s.page
    assert page.locator(".lp-gname").all_inner_texts() == ["머리카락", "얼굴", "몸", "기타"]
    assert page.locator(".lp-group").count() == 4 and page.locator(".lp-row").count() == 23
    counts = {g: page.locator(f'.lp-group[data-group="{g}"] .lp-row').count() for g in ("hair", "face", "body", "other")}
    assert counts == {"hair": 2, "face": 11, "body": 7, "other": 3}
    assert row(s, "front hair").locator(".lp-name").inner_text() == "앞머리"
    badges = lambda t: row(s, t).locator(".lp-badge").all_inner_texts()  # noqa: E731
    assert badges("topwear") == ["편집됨"]
    assert badges("face") == ["후보 2"]
    assert badges("nose") == ["제외됨"]
    assert badges("tail") == ["비어 있음"]
    assert badges("front hair") == []
    # front-most first inside a group
    assert [t for t in page.locator('.lp-group[data-group="hair"] .lp-row').evaluate_all("(r) => r.map((x) => x.dataset.tag)")] == ["front hair", "back hair"]
    # thumbnails: real ones load, empty layers get a placeholder and no request
    until(lambda: s.js("() => [...document.querySelectorAll('.lp-row:not(.is-empty) .lp-thumb img')].every((i) => i.naturalWidth > 0)"), "thumbnails to load")
    assert s.js("() => document.querySelectorAll('.lp-row.is-empty .lp-thumb.is-missing').length") == 7
    assert not [c for c in m.calls if "thumb" in c[1] and "tail" in c[1]]
    # search
    page.fill(".lp-search", "머리")
    until(lambda: page.locator(".lp-row:visible").count() == 3, "the search to filter (앞머리, 뒷머리, 머리 장식)")
    page.fill(".lp-search", "eyewhite")
    until(lambda: page.locator(".lp-row:visible").count() == 1, "the tag search")
    page.fill(".lp-search", "zzz")
    until(lambda: page.locator(".lp-empty").is_visible(), "the empty message")
    page.fill(".lp-search", "")
    until(lambda: page.locator(".lp-row:visible").count() == 23, "the filter to clear")
    # groups collapse
    page.click('.lp-group[data-group="face"] .lp-ghead')
    until(lambda: page.locator('.lp-group[data-group="face"] .lp-row:visible').count() == 0, "the face group to collapse")
    assert page.get_attribute('.lp-group[data-group="face"] .lp-ghead', "aria-expanded") == "false"
    page.click('.lp-group[data-group="face"] .lp-ghead')
    until(lambda: page.locator('.lp-group[data-group="face"] .lp-row:visible').count() == 11, "the face group to open")
    assert s.errors == []


def test_eye_toggle_hides_the_mesh_and_show_all_restores(studio):
    s = studio().open(QUIET + "&bg=white&camera=head")
    before = frame_hash(s)
    row(s, "front hair").locator(".lp-eye").click()
    settle(s.page)
    assert "front hair" not in visible_tags(s) and "face" in visible_tags(s)
    assert row(s, "front hair").locator(".lp-eye").get_attribute("aria-pressed") == "false"
    assert frame_hash(s) != before                                               # the hair is gone from the picture
    row(s, "front hair").locator(".lp-eye").click()
    settle(s.page)
    assert frame_hash(s) == before                                               # exactly the same picture again
    s.page.click("text=모두 숨기기")
    settle(s.page)
    assert visible_tags(s) == set() and ink(s) == 0
    s.page.click("text=모두 보기")
    settle(s.page)
    assert frame_hash(s) == before and s.page.locator(".lp-eye[aria-pressed='false']").count() == 0
    assert s.errors == []


def test_solo_isolates_one_layer(studio):
    s = studio().open(QUIET + "&bg=white&camera=head")
    full = ink(s)
    row(s, "nose").locator(".lp-solo").click()
    settle(s.page)
    assert visible_tags(s) == {"nose"}
    assert 0 < ink(s) < full * 0.05
    assert row(s, "nose").locator(".lp-solo").get_attribute("aria-pressed") == "true"
    assert s.page.locator(".lp-solochip").is_visible() and "코" in s.page.inner_text(".lp-solochip")
    s.page.click(".lp-solochip")                                                 # clear the solo
    settle(s.page)
    assert "face" in visible_tags(s) and abs(ink(s) - full) < 10
    row(s, "mouth").locator(".lp-solo").click(); row(s, "mouth").locator(".lp-solo").click()   # toggles off again
    settle(s.page)
    assert "face" in visible_tags(s)
    assert s.errors == []


def test_keyboard_navigation_in_the_layer_list(studio):
    s = studio().open()
    page = s.page
    row(s, "front hair").click()
    assert s.js("() => window.__studio.selected") == "front hair"
    assert s.js("() => document.activeElement.dataset.tag") == "front hair"
    page.keyboard.press("ArrowDown")
    assert s.js("() => window.__studio.selected") == "back hair"
    page.keyboard.press("ArrowDown")                                              # crosses into the next group
    assert s.js("() => window.__studio.selected") == "headwear"                  # first row of the face group (front-most first)
    page.keyboard.press("ArrowUp"); page.keyboard.press("ArrowUp")
    assert s.js("() => window.__studio.selected") == "front hair"
    page.keyboard.press("Space")                                                  # Space toggles the eye
    assert "front hair" not in visible_tags(s)
    page.keyboard.press("Space")
    assert "front hair" in visible_tags(s)
    page.keyboard.press("s")                                                      # S toggles solo
    assert visible_tags(s) == {"front hair"}
    page.keyboard.press("s")
    assert "face" in visible_tags(s)
    page.keyboard.press("End")
    assert s.js("() => window.__studio.selected") is not None
    assert s.errors == []


# ------------------------------------------------------------------------------------------------ canvas picking
def test_clicking_the_stage_selects_the_layer_under_the_pointer(studio, site):
    s = studio().open(QUIET)
    tags = ["front hair", "back hair", "face", "topwear", "bottomwear", "footwear", "neck"]
    pts = fx.topmost_points(site.jdir, tags)
    for tag in tags:                                                              # hit testing: deformed triangles + texture alpha
        sp = screen_point(s, pts[tag])
        got = s.js("(p) => window.__studio.stage.pickAt(p.cx, p.cy)", sp)
        assert got == tag, (tag, got, pts[tag])
    # real mouse clicks on the canvas
    for tag in ("topwear", "front hair", "face"):
        sp = screen_point(s, pts[tag])
        s.page.mouse.click(sp["px"], sp["py"])
        until(lambda tag=tag: s.js("() => window.__studio.selected") == tag, f"the click to select {tag}")
        until(lambda tag=tag: row(s, tag).get_attribute("aria-selected") == "true", f"the {tag} row to follow the canvas")
        assert s.js("() => window.__studio.stage.highlighted") == tag
        assert s.page.get_attribute('#stageMount canvas.stage-canvas', "aria-label")
        assert s.js("() => document.querySelector('.in-tabs [aria-selected=true]').dataset.tab") == "layer"   # the inspector opens the layer tab
        assert fx.LABELS[tag] in s.page.inner_text("#stChip")
    # hovering outlines the layer under the pointer (and names it in the chip)
    sp = screen_point(s, pts["bottomwear"])
    s.page.mouse.move(sp["px"] - 3, sp["py"] - 3); s.page.mouse.move(sp["px"], sp["py"])
    until(lambda: s.js("() => window.__studio.stage.hovered") == "bottomwear", "the hover pick")
    until(lambda: "가리키는 중: 하의" in s.page.inner_text("#stChip"), "the hover name")
    # clicking empty space clears the selection
    box = rect(s.page, "#stageMount canvas.stage-canvas")
    s.page.mouse.click(box["x"] + 24, box["y"] + 130)                              # blank corner of the stage
    until(lambda: s.js("() => window.__studio.selected") is None, "the empty click to deselect")
    assert s.page.locator(".lp-row[aria-selected='true']").count() == 0
    # a drag is a pan, not a click
    sp = screen_point(s, pts["topwear"])
    s.page.mouse.move(sp["px"], sp["py"]); s.page.mouse.down(); s.page.mouse.move(sp["px"] + 40, sp["py"] + 10, steps=5); s.page.mouse.up()
    assert s.js("() => window.__studio.selected") is None and s.js("() => window.__studio.stage.camera.mode") == "custom"
    # hidden layers cannot be picked; solo makes the other layers click-through
    s.js("() => window.__studio.stage.resetCamera()")
    settle(s.page)
    sp = screen_point(s, pts["topwear"])
    s.js("() => window.__studio.stage.setVisible('topwear', false)")
    assert s.js("(p) => window.__studio.stage.pickAt(p.cx, p.cy)", sp) != "topwear"
    assert s.errors == []


def test_selection_outline_is_drawn_on_the_overlay_and_follows_the_layer(studio, site):
    s = studio().open(QUIET)
    count = "() => { const c = document.querySelector('.stage-overlay'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 40) n++; return n; }"
    assert s.js(count) == 0
    row(s, "topwear").click()
    until(lambda: s.js(count) > 800, "the outline of the selected layer")
    c1 = s.js(count)
    s.js("() => window.__studio.stage.params.set('ParamBodyAngleX', 10)")           # the layer moves: the outline follows it
    settle(s.page)
    assert s.js(count) > 800
    row(s, "nose").click()
    until(lambda: 0 < s.js(count) < c1, "the outline to switch to the (smaller) nose")
    s.page.click(".st-chip-x")
    until(lambda: s.js(count) == 0, "the outline to clear")
    assert s.errors == []


def test_focus_option_dims_the_other_layers(studio):
    s = studio().open(QUIET + "&bg=white&camera=head")
    full = ink(s)
    row(s, "mouth").click()
    s.page.click(".in-tabs [data-tab=motion]")
    s.page.locator(".st-switch", has_text="선택 레이어 집중").click()
    settle(s.page)
    assert abs(ink(s) - full) <= full * 0.03                                     # dimmed, not removed: (nearly) the same pixels are covered ...
    assert s.js("() => Math.min(...Array.from(window.__studio.stage.renderer.dim))") < 0.5   # ... but fainter
    assert s.errors == []


# ------------------------------------------------------------------------------------------------ inspector
def test_inspector_tabs_and_motion_controls(studio):
    s = studio().open()
    page = s.page
    tabs = page.locator(".in-tabs button").all_inner_texts()
    assert tabs == ["움직임", "레이어", "보고서", "파일"]
    assert page.get_attribute(".in-tabs [data-tab=motion]", "aria-selected") == "true"
    assert page.locator('input[data-param="ParamAngleX"]').count() == 1 and page.locator(".in-details summary").count() >= 4
    assert "머리" in page.inner_text(".in-params") and "눈·눈썹" in page.inner_text(".in-params")
    # switches drive the stage
    assert s.js("() => window.__studio.stage.option('idle')") is False                # ?idle=0
    page.locator(".st-switch", has_text="와이어프레임").click()
    assert s.js("() => window.__studio.stage.option('wireframe')") is True and page.get_attribute('[data-tool="wire"]', "aria-pressed") == "true"
    page.click('[data-tool="wire"]')                                                  # the toolbar button is the same switch
    assert s.js("() => window.__studio.stage.option('wireframe')") is False
    assert page.locator(".st-switch", has_text="와이어프레임").locator("input").is_checked() is False
    # background chooser (inspector and toolbar stay in sync)
    page.click('.in-bgbtn[data-bg="dark"]')
    assert s.js("() => window.__studio.stage.background") == "dark" and page.get_attribute('.st-bg[data-bg="dark"]', "aria-checked") == "true"
    page.click('.st-bg[data-bg="white"]')
    assert page.get_attribute('.in-bgbtn[data-bg="white"]', "aria-checked") == "true"
    # a slider moves the parameter; reset puts it back
    sl = page.locator('input[data-param="ParamAngleX"]')
    sl.focus(); sl.press("End")
    assert s.js("() => window.__studio.stage.params.get('ParamAngleX')") == pytest.approx(30, abs=0.2)
    page.click("text=매개변수 초기화")
    until(lambda: abs(float(sl.input_value())) < 0.1, "the slider to reset")
    assert s.js("() => window.__studio.stage.params.get('ParamAngleX')") == 0
    # capability card
    assert "대체 방식" in page.inner_text(".in-cap") and "불가" in page.inner_text(".in-cap")
    # PNG snapshot downloads a real PNG
    with page.expect_download() as dl:
        page.click("text=PNG 저장")
    path = dl.value.path()
    assert Path(path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    # report + files tabs
    page.click(".in-tabs [data-tab=report]")
    page.wait_for_selector(".in-panel:not([hidden]) .in-sec")
    txt = page.inner_text("#inspector")
    assert "기능별 상태" in txt and "수치 QA" in txt and "프롬프트 해석" in txt and "충실도" in txt and "통과" in txt
    page.click(".in-tabs [data-tab=files]")
    assert page.locator('.in-dl a[href$="puppet.zip"]').count() == 1 and page.locator(".in-files tbody tr").count() > 10
    assert page.locator("#inspector button.danger", has_text="이 퍼펫 삭제").count() == 1
    # keyboard: arrows move between tabs
    page.focus(".in-tabs [aria-selected=true]"); page.keyboard.press("ArrowLeft")
    assert page.get_attribute(".in-tabs [data-tab=report]", "aria-selected") == "true"
    assert s.errors == []


def test_layer_tab_shows_the_selected_layer_and_its_versions(studio):
    s = studio()
    m = s.mock
    v_edit = m.add_version("front hair", "edit", "끝을 다듬음", make_current=True)
    v_cand = m.add_version("front hair", "regen", "시드 77로 다시 생성", seed=77)
    v_auto = m.add_version("front hair", "auto", "자동 정리")
    s.open()
    page = s.page
    assert "선택하세요" in page.inner_text(".in-layer") or "선택하세요" in page.inner_text("#inspector")
    row(s, "front hair").click()
    page.wait_for_selector(".in-title h3")
    assert page.inner_text(".in-title h3") == "앞머리" and "머리카락" in page.inner_text(".in-title")
    assert "불투명 픽셀" in page.inner_text(".in-kv") and "13,910" in page.inner_text(".in-kv")
    items = page.locator(".in-ver")
    assert items.count() == 4
    assert page.locator(".in-ver.is-current .in-ver-id").inner_text() == v_edit
    kinds = page.locator(".in-ver .pill").all_inner_texts()
    assert {"원본", "편집", "후보", "자동", "현재"} <= set(kinds), kinds
    assert page.locator(".in-ver", has_text="시드 77").count() == 1
    # undo-style: pick the original -> POST select v0 -> state with a new rev -> the stage is recompiled
    rev0 = s.js("() => window.__studio.state.rev")
    page.locator(".in-ver", has_text="원본").locator(".in-ver-main").click()
    until(lambda: ("/layer/front hair/select", {"version": "v0"}) in [(p, b) for _, p, b in m.calls], "the select call")
    until(lambda: s.js("() => window.__studio.state.rev") == rev0 + 1, "the new state")
    until(lambda: page.locator(".in-ver.is-current .in-ver-id").inner_text() == "v0", "the version list to follow")
    assert row(s, "front hair").locator(".lp-badge").count() == 1 and "후보 1" in row(s, "front hair").inner_text()   # edited badge gone, candidate shown
    # apply the candidate
    page.locator(".in-ver", has_text="시드 77").locator(".in-ver-main").click()
    until(lambda: m.layer("front hair")["current"] == v_cand, "the candidate to become current")
    until(lambda: "편집됨" in row(s, "front hair").inner_text(), "the edited badge")
    # trash: only for non-original, non-current versions; asks first
    assert page.locator(".in-ver", has_text="원본").locator(".in-ver-del").count() == 0
    assert page.locator(".in-ver.is-current .in-ver-del").count() == 0
    page.locator(".in-ver", has_text="자동 정리").locator(".in-ver-del").click()
    until(lambda: ("DELETE", f"/layer/front hair/version/{v_auto}", {}) in m.calls, "the DELETE call")
    until(lambda: page.locator(".in-ver").count() == 3, "the version to disappear")
    assert any("삭제" in d for d in s.dialogs)
    # [원본으로] and the thumbnails of the versions load
    until(lambda: s.js("() => [...document.querySelectorAll('.in-ver-thumb img')].every((i) => i.naturalWidth > 0)"), "version thumbnails")
    page.click('[data-fk="to-original"]')
    until(lambda: m.layer("front hair")["current"] == "v0", "back to the original")
    until(lambda: page.locator('[data-fk="to-original"]').is_disabled(), "the original button to disable itself")
    assert s.errors == []


def test_an_empty_layer_has_a_tab_but_requests_no_thumbnails(studio):
    s = studio().open(QUIET)
    row(s, "tail").click()
    s.page.wait_for_selector(".in-title h3")
    assert s.page.inner_text(".in-title h3") == "꼬리" and "비어 있는 레이어" in s.page.inner_text(".in-layer")
    assert s.page.locator(".in-ver").count() == 1 and s.page.locator(".in-ver-thumb.is-missing").count() == 1
    assert not [c for c in s.mock.calls if "thumb" in c[1] and "tail" in c[1]]
    assert s.js("() => window.__studio.stage.highlighted") == "tail" and s.errors == []        # nothing to outline, nothing breaks
    s.page.click('[data-fk="edit"]')                                                           # an empty layer can still be edited (restore from the source)
    s.page.wait_for_selector("#editorBox:not([hidden])")


def test_flags_include_switch_and_draw_order(studio):
    s = studio().open(QUIET)
    m, page = s.mock, s.page
    row(s, "nose").click()
    page.wait_for_selector(".in-title h3")
    assert s.js("() => window.__studio.stage.hasLayer('nose')") is True
    page.locator(".st-switch", has_text="퍼펫에 포함").click()
    until(lambda: ("/layer/nose/flags", {"enabled": False}) in [(p, b) for _, p, b in m.calls], "the flags call")
    until(lambda: s.js("() => window.__studio.stage.hasLayer('nose')") is False, "the stage to reload without the nose")
    until(lambda: "제외됨" in row(s, "nose").inner_text(), "the excluded badge")
    page.locator(".st-switch", has_text="퍼펫에 포함").click()
    until(lambda: s.js("() => window.__studio.stage.hasLayer('nose')") is True, "the nose back in the puppet")
    # draw order: nose is 116; the next layer above is eyewhite 120 -> to 121
    assert "116" in page.inner_text(".in-order") and "기본 116" in page.inner_text(".in-order")
    page.click('[data-fk="order-up"]')
    until(lambda: m.layer("nose")["order"] == 121, "order to move above the eye white")
    until(lambda: "121" in page.inner_text(".in-order") and page.locator('[data-fk="order-default"]').count() == 1, "the order to show")
    page.click('[data-fk="order-default"]')
    until(lambda: m.layer("nose")["order"] == 116, "default order restored")
    page.click('[data-fk="order-down"]')
    until(lambda: m.layer("nose")["order"] == 109, "order below the face (face is 110)")
    assert s.errors == []


def test_reset_everything_asks_first(studio):
    s = studio()
    s.mock.add_version("topwear", "edit", "x", make_current=True)
    s.mock.layer("neck")["enabled"] = False
    s.open()
    s.page.click(".in-tabs [data-tab=layer]")
    s.page.click('[data-fk="reset-all"]')
    until(lambda: s.mock.layer("topwear")["current"] == "v0" and s.mock.layer("neck")["enabled"], "the reset")
    assert any("되돌릴까요" in d for d in s.dialogs)
    until(lambda: s.page.locator(".lp-badge", has_text="편집됨").count() == 0, "badges to clear")
    assert s.errors == []


def test_api_errors_are_shown_and_the_switch_snaps_back(studio):
    s = studio().open(QUIET)
    s.mock.fail["POST /layer/nose/flags"] = (409, "다른 작업이 진행 중입니다")
    row(s, "nose").click()
    s.page.locator(".st-switch", has_text="퍼펫에 포함").click()
    until(lambda: "다른 작업이 진행 중입니다" in s.page.inner_text("#toasts"), "the error toast")
    until(lambda: s.page.locator(".st-switch", has_text="퍼펫에 포함").locator("input").is_checked(), "the switch to snap back")
    assert s.js("() => window.__studio.stage.hasLayer('nose')") is True
    assert any("409" in e for e in s.errors)           # the only expected error: the failed request itself
    s.errors = [e for e in s.errors if "409" not in e]
    assert s.errors == []


def test_busy_indicators_while_the_server_recompiles(studio):
    s = studio().open(QUIET)
    m, page = s.mock, s.page
    row(s, "neck").click()
    m.hold = True                                                                    # the "server" is slow: look at the page meanwhile
    page.locator(".st-switch", has_text="퍼펫에 포함").click()
    until(lambda: len(m.pending) == 1, "the request to be on its way")
    assert page.locator(".in-busybar").is_visible() and "다시 만드는 데" in page.inner_text(".in-busybar")
    assert page.locator("#stBusy").is_visible() and "다시 만드는 중" in page.inner_text("#stBusy")
    assert s.js("() => document.querySelector('.in-layer').getAttribute('aria-busy')") == "true"
    page.locator('[data-fk="order-up"]').click(force=True)                          # a second request while busy is ignored, not queued
    settle(page)
    assert len(m.pending) == 1
    m.hold = False
    m.release()
    until(lambda: page.locator(".in-busybar").is_hidden() and page.locator("#stBusy").is_hidden(), "the busy indicators to clear")
    assert s.js("() => window.__studio.stage.hasLayer('neck')") is False
    assert s.errors == []


def test_unapplied_changes_offer_a_rebuild(studio):
    s = studio()
    s.mock.state["dirty"] = True
    s.open(QUIET)
    page = s.page
    page.click(".in-tabs [data-tab=layer]")
    assert "반영하지 않은 변경" in page.inner_text(".in-dirty")
    page.click('[data-fk="rebuild"]')
    until(lambda: ("/rebuild", {}) in [(p, b) for _, p, b in s.mock.calls], "the rebuild call")
    until(lambda: page.locator(".in-dirty").count() == 0, "the notice to go away")
    until(lambda: s.js("() => window.__studio.stage.url").endswith("/r1/puppet.json"), "the rebuilt puppet to load")
    assert s.js("() => window.__studio.state.rev") == 1
    assert s.errors == []


def test_every_control_has_an_accessible_name(studio):
    s = studio().open(QUIET)
    page = s.page
    js = """() => {
      const bad = [];
      const vis = (e) => !!(e.offsetWidth || e.offsetHeight || e.getClientRects().length);
      for (const e of document.querySelectorAll('#result button, #result input, #result select, #result textarea, #result [role=tab], #result [role=option], #result [role=separator]')) {
        if (!vis(e) || e.closest('[inert]')) continue;
        let name = e.getAttribute('aria-label') || '';
        if (!name && e.getAttribute('aria-labelledby')) name = e.getAttribute('aria-labelledby').split(' ').map((i) => (document.getElementById(i) || {}).textContent || '').join(' ');
        if (!name && e.labels && e.labels.length) name = [...e.labels].map((l) => l.textContent).join(' ');
        if (!name) name = (e.textContent || '').trim();
        if (!name) name = e.getAttribute('title') || '';
        if (!name.trim()) bad.push(e.outerHTML.slice(0, 120));
      }
      return bad;
    }"""
    seen = 0
    for tab in ("motion", "layer", "report", "files"):
        if tab == "layer":
            row(s, "front hair").click()
        page.click(f".in-tabs [data-tab={tab}]")
        if tab == "report":
            page.wait_for_selector(".in-panel:not([hidden]) .in-sec")
        assert s.js(js) == [], tab
        seen += 1
    page.click(".in-tabs [data-tab=layer]")
    page.click('[data-fk="regen"]')                                               # the regen form too
    assert s.js(js) == []
    assert seen == 4 and s.errors == []


# ------------------------------------------------------------------------------------------------ revisions
def test_a_new_rev_reloads_the_stage_and_keeps_sliders_and_camera(studio):
    s = studio().open(QUIET)
    page = s.page
    sl = page.locator('input[data-param="ParamAngleX"]')
    sl.focus(); sl.press("End")                                                       # the user moved a slider to 30 ...
    page.locator('input[data-param="ParamMouthOpenY"]').focus(); page.keyboard.press("End")
    s.js("() => { const r = window.__studio.stage.renderer; r.zoomAt(300, 300, 1.5); }")  # ... and zoomed the camera
    cam = s.js("() => window.__studio.stage.camera")
    assert cam["mode"] == "custom"
    url0, model0 = s.js("() => window.__studio.stage.url"), s.js("() => window.__studio.stage.model.params.length")
    row(s, "neck").click()
    page.locator(".st-switch", has_text="퍼펫에 포함").click()                          # any flag change -> rev + 1 -> new puppet
    until(lambda: s.js("() => window.__studio.stage.url") != url0, "the stage to load the new puppet")
    until(lambda: s.js("() => window.__studio.stage.hasLayer('neck')") is False, "the neck to disappear")
    assert s.js("() => window.__studio.stage.url").startswith(f"/mock/{s.site.job_id}/r1/")
    assert s.js("() => window.__studio.stage.params.get('ParamAngleX')") == pytest.approx(30, abs=0.2)   # not reset
    assert s.js("() => window.__studio.stage.params.get('ParamMouthOpenY')") == pytest.approx(1, abs=0.01)
    page.click(".in-tabs [data-tab=motion]")
    assert float(page.locator('input[data-param="ParamAngleX"]').input_value()) == pytest.approx(30, abs=0.2)
    cam2 = s.js("() => window.__studio.stage.camera")
    assert cam2["mode"] == "custom" and cam2["zoom"] == pytest.approx(cam["zoom"], rel=1e-6) and cam2["cx"] == pytest.approx(cam["cx"], abs=1e-6)
    assert s.js("() => window.__studio.stage.highlighted") == "neck"                         # the selection survives too
    assert page.locator("#stBusy").is_hidden()
    assert s.js("() => document.querySelectorAll('canvas.stage-canvas').length") == 1        # the old canvas was released
    assert s.errors == []


def _snapshot(mock, rev: int) -> dict:
    st = json.loads(json.dumps(mock.state))
    st["rev"], st["puppet"] = rev, f"/mock/{mock.jid}/r{rev}/puppet.json"
    return st


def test_two_quick_changes_end_on_the_latest_puppet(studio):
    s = studio().open(QUIET)
    m = s.mock
    m.layer("nose")["enabled"] = False
    st5 = _snapshot(m, 5)
    m.layer("neck")["enabled"] = False
    st6 = _snapshot(m, 6)
    s.js(f"() => {{ window.__studio.applyState({json.dumps(st5)}); window.__studio.applyState({json.dumps(st6)}); }}")
    until(lambda: s.js("() => window.__studio.state.rev") == 6, "rev 6")
    until(lambda: s.js("() => window.__studio.stage.url").endswith("r6/puppet.json"), "the latest puppet")
    until(lambda: s.js("() => [window.__studio.stage.hasLayer('nose'), window.__studio.stage.hasLayer('neck')]") == [False, False], "both layers gone")
    s.js(f"() => window.__studio.applyState({json.dumps(_snapshot(m, 3))})")        # an older (slower) response is ignored
    settle(s.page)
    assert s.js("() => window.__studio.state.rev") == 6
    assert s.js("() => document.querySelectorAll('canvas.stage-canvas').length") == 1
    assert s.errors == []


# ------------------------------------------------------------------------------------------------ failures the stage must survive
def test_webgl_context_loss_is_reported_and_recovered(studio):
    s = studio().open(QUIET + "&bg=white&camera=head")
    before = frame_hash(s)
    assert s.js("() => window.__studio.stage.renderer.debugLoseContext()") is True
    until(lambda: s.page.locator(".stage-banner").is_visible() and "컨텍스트" in s.page.inner_text(".stage-banner"), "the context-lost banner")
    assert s.js("() => window.__studio.stage.renderer.lost") is True
    s.js("() => window.__studio.stage.renderer.debugRestoreContext()")
    until(lambda: s.page.locator(".stage-banner").is_hidden(), "the banner to go away after the context is restored")
    settle(s.page)
    assert s.js("() => window.__studio.stage.renderer.lost") is False
    assert frame_hash(s) == before                                                   # textures and buffers were rebuilt: same picture
    assert [e for e in s.errors if "CONTEXT_LOST" not in e and "WebGL" not in e] == []


def test_a_texture_that_fails_to_load_is_named_and_the_rest_still_works(studio):
    s = studio()
    s.page.route(re.compile(r".*/puppet/tex/nose\.png"), lambda route, req: route.fulfill(status=404, body="", content_type="text/plain"))
    s.open(QUIET)
    until(lambda: s.page.locator(".stage-banner").is_visible(), "the texture banner")
    assert "텍스처 1개" in s.page.inner_text(".stage-banner") and "nose" in s.page.inner_text(".stage-banner")
    row(s, "topwear").click()
    assert s.js("() => window.__studio.stage.highlighted") == "topwear"
    assert [e for e in s.errors if "404" not in e and "Failed to load resource" not in e and "nose.png" not in e] == []


def test_a_puppet_that_cannot_be_reloaded_keeps_the_old_one_and_says_so(studio):
    s = studio().open(QUIET)
    s.page.route(re.compile(r".*/mock/.*/r\d+/puppet\.json"), lambda route, req: route.fulfill(status=500, body="boom", content_type="text/plain"))
    url0 = s.js("() => window.__studio.stage.url")
    row(s, "neck").click()
    s.page.locator(".st-switch", has_text="퍼펫에 포함").click()
    until(lambda: "퍼펫을 다시 불러오지 못했습니다" in s.page.inner_text("#toasts"), "the reload-failed toast")
    assert s.js("() => window.__studio.stage.url") == url0 and s.js("() => window.__studio.stage.hasLayer('neck')") is True
    assert s.js("() => document.querySelectorAll('canvas.stage-canvas').length") == 1
    assert s.page.locator("#stBusy").is_hidden()
    assert s.page.locator(".lp-row").count() == 23                                  # the panels still work with the new state
    assert [e for e in s.errors if "500" not in e and "Failed to load resource" not in e and "HTTP 500" not in e] == []


# ------------------------------------------------------------------------------------------------ degraded mode
@pytest.mark.parametrize("code", [404, 501])
def test_degraded_mode_when_the_studio_endpoint_is_missing(studio, code):
    s = studio(mock=False)
    s.page.route(f"**/api/jobs/{s.site.job_id}/studio", lambda route, req: route.fulfill(status=code, body="", content_type="text/plain"))
    s.open(QUIET + "&bg=white&camera=head")
    page = s.page
    assert s.js("() => window.__studio.degraded") is True
    assert page.locator(".lp-row").count() == 23 and page.locator(".lp-group").count() == 4
    assert row(s, "front hair").locator(".lp-name").inner_text() == "앞머리" and "비어 있음" in row(s, "tail").inner_text()
    until(lambda: s.js("() => [...document.querySelectorAll('.lp-row:not(.is-empty) .lp-thumb img')].every((i) => i.naturalWidth > 0)"), "layer thumbnails from layers/*.png")
    # eye / solo / select / highlight keep working
    before = ink(s)
    row(s, "front hair").locator(".lp-eye").click()
    settle(page)
    assert ink(s) < before
    row(s, "front hair").locator(".lp-eye").click()
    row(s, "nose").locator(".lp-solo").click()
    assert visible_tags(s) == {"nose"}
    row(s, "nose").locator(".lp-solo").click()
    row(s, "face").click()
    assert s.js("() => window.__studio.stage.highlighted") == "face"
    # edit controls are gone, a notice explains why
    assert "편집 기능 준비 중" in page.inner_text("#inspector")
    for t in ("다시 생성", "원본으로", "퍼펫에 포함", "버전"):
        assert t not in page.inner_text(".in-layer"), t
    assert page.locator('[data-fk="edit"], [data-fk="regen"], [data-fk="reset-all"]').count() == 0
    assert page.locator(".st-toast", has_text="편집 기능 준비 중").count() == 1
    # the motion tab is unaffected
    page.click(".in-tabs [data-tab=motion]")
    assert page.locator('input[data-param="ParamAngleX"]').count() == 1
    errs = [e for e in s.errors if f"HTTP {code}" not in e and "Failed to load resource" not in e]
    assert errs == []


# ------------------------------------------------------------------------------------------------ editor + regen
EDITOR_STUB = """
export function mountLayerEditor(container, opts) {
  window.__editor = { opts, rev: opts.rev, calls: [], disposed: false, refuse: [] };
  container.innerHTML = '<div id="fakeEditor"><b>fake editor</b> <span id="fakeTag"></span> <button id="fakeApply" type="button">적용</button></div>';
  const tagEl = container.querySelector('#fakeTag');
  tagEl.textContent = opts.tag + '/' + opts.grid + '/' + opts.label;
  container.querySelector('#fakeApply').addEventListener('click', async () => {
    const r = await fetch(`/api/jobs/${opts.api.jobId}/studio/layer/${encodeURIComponent(window.__editor.tag || opts.tag)}/edit`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ op: 'erase', mask: 'AAAA' }) });
    const j = await r.json();
    window.__editor.rev = j.state.rev;           // like the real editor: it reloads its own images, then reports
    opts.onApplied(j.state);
  });
  return {
    async setTag(tag, o = {}) {
      window.__editor.calls.push(['setTag', tag, o.rev, (o.layers || []).length, o.grid]);
      if (window.__editor.refuse.includes(tag)) return false;          // like the real editor when the user keeps an unsaved selection
      window.__editor.tag = tag;
      tagEl.textContent = tag + '/' + (o.grid || '') + '/' + (o.label || '');
      return true;
    },
    setLayers(layers) { window.__editor.calls.push(['setLayers', layers.length]); },
    dispose() { window.__editor.disposed = true; container.innerHTML = ''; },
  };
}
"""


def test_editor_replaces_the_stage_and_stays_in_sync(studio):
    s = studio()
    s.page.route("**/static/js/layer-editor.js*", lambda route, req: route.fulfill(status=200, content_type="text/javascript", body=EDITOR_STUB))
    s.open(QUIET)
    page = s.page
    row(s, "topwear").click()
    page.click('[data-fk="edit"]')
    page.wait_for_selector("#fakeEditor")
    assert page.locator("#editorBox").is_visible() and page.locator("#stageMount").is_hidden() and page.locator("#stToolbar").is_hidden()
    assert s.js("() => [window.__editor.opts.tag, window.__editor.opts.label, window.__editor.opts.grid, window.__editor.opts.layers.length, window.__editor.opts.rev]") == ["topwear", "상의", "canvas", 23, 0]
    assert "topwear/canvas/상의" in page.inner_text("#fakeTag")
    assert s.js("() => window.__studio.stage.paused") is True                      # the engine sleeps behind the editor
    assert "퍼펫으로 돌아가기" in page.inner_text("#editorBack")
    # the panels stay usable: choosing another layer re-targets the open editor (grid + label + rev + layer list go along)
    row(s, "face").click()
    until(lambda: s.js("() => window.__editor.calls.at(-1)?.[1]") == "face", "setTag(face)")
    assert s.js("() => window.__editor.calls.at(-1)") == ["setTag", "face", 0, 23, "head"]
    until(lambda: "얼굴" in page.inner_text("#editorTitle"), "the editor title to follow")
    row(s, "topwear").click()
    until(lambda: s.js("() => window.__editor.calls.at(-1)?.[1]") == "topwear", "setTag(topwear)")
    # ... unless the editor refuses (it asks before discarding a selection): the selection snaps back
    s.js("() => { window.__editor.refuse = ['nose']; }")
    row(s, "nose").click()
    until(lambda: s.js("() => window.__editor.calls.at(-1)?.[1]") == "nose", "setTag(nose) was asked")
    until(lambda: s.js("() => window.__studio.selected") == "topwear", "the declined selection to snap back to topwear")
    assert row(s, "topwear").get_attribute("aria-selected") == "true" and "상의" in page.inner_text("#editorTitle")
    s.js("() => { window.__editor.refuse = []; }")
    # an edit made inside the editor: the stage reloads, the editor is only told the new layer list (it refreshed its own images)
    url0 = s.js("() => window.__studio.stage.url")
    n0 = s.js("() => window.__editor.calls.length")
    page.click("#fakeApply")
    until(lambda: s.js("() => window.__studio.stage.url") != url0, "the stage to reload after onApplied")
    until(lambda: s.js("() => window.__editor.calls.at(-1)?.[0]") == "setLayers", "setLayers after apply")
    assert [c[0] for c in s.js("() => window.__editor.calls.slice(%d)" % n0)] == ["setLayers"], "no second image reload after the editor's own"
    assert page.locator("#fakeEditor").count() == 1 and page.locator("#editorBox").is_visible()
    assert "편집됨" in row(s, "topwear").inner_text()
    # a change made elsewhere (the inspector's version list) reloads the editor on the same layer, with the new rev
    page.locator(".in-ver", has_text="원본").locator(".in-ver-main").click()
    until(lambda: s.js("() => window.__editor.calls.at(-1)?.[0]") == "setTag", "the editor to be refreshed")
    last = s.js("() => window.__editor.calls.at(-1)")
    assert last[1] == "topwear" and last[2] == s.js("() => window.__studio.state.rev") and last[3] == 23
    # back to the puppet
    page.click("#editorBack")
    until(lambda: page.locator("#stageMount").is_visible() and page.locator("#editorBox").is_hidden(), "the stage to return")
    assert s.js("() => window.__editor.disposed") is True and s.js("() => window.__studio.stage.paused") is False
    assert page.locator("#stToolbar").is_visible()
    until(lambda: abs(rect(page, "#stageMount canvas.stage-canvas")["w"] - rect(page, "#stCenter")["w"]) < 2, "the canvas to refill the stage")
    assert s.errors == []


def test_missing_editor_module_shows_a_friendly_message(studio):
    s = studio()
    s.page.route("**/static/js/layer-editor.js*", lambda route, req: route.fulfill(status=404, body="nope", content_type="text/plain"))
    s.open(QUIET)
    row(s, "topwear").click()
    s.page.click('[data-fk="edit"]')
    s.page.wait_for_selector(".st-editor-note.notice")
    assert "불러오지 못했습니다" in s.page.inner_text("#editorMount") and "준비 중" in s.page.inner_text("#editorMount")
    s.page.click("#editorBack")                                                     # the way back always works
    until(lambda: s.page.locator("#stageMount").is_visible(), "the stage to return")
    assert [e for e in s.errors if "404" not in e and "Failed to load resource" not in e and "layer-editor.js" not in e] == []


def test_regen_form_sends_the_chosen_settings_and_follows_the_task(studio):
    s = studio()
    m, page = s.mock, s.page
    s.open(QUIET)
    row(s, "eyewhite").click()
    page.click('[data-fk="regen"]')
    page.wait_for_selector(".in-regen")
    text = page.inner_text(".in-regen")
    assert "머리 11개" in text and "약 3분" in text and "후보" in text and "자동으로 적용되지 않습니다" in text and "모두 적용" in text
    assert page.locator(".in-regen [data-head-only]").count() == 0                   # the model cannot take a crop margin
    page.locator(".in-regen input[value=manual]").check()
    page.fill(".in-regen .in-num", "1234")
    page.locator(".in-regen input[type=range]").first.fill("42")
    page.click('[data-fk="regen-submit"]')
    until(lambda: any(p == "/regen" for _, p, _b in m.calls), "the regen call")
    body = next(b for _, p, b in m.calls if p == "/regen")
    assert body == {"tags": ["eyewhite"], "steps": 42, "seed": 1234}, body
    until(lambda: page.locator(".in-task").count() == 1, "the running task")
    assert "진행 중" in page.inner_text(".in-task") and page.locator(".in-task .progress i").evaluate("(e) => e.style.width") == "10%"
    # the page polls the state while a task runs: progress advances, then the candidates of the whole group arrive
    m.state["tasks"][0]["progress"] = 0.6
    until(lambda: page.locator(".in-task .progress i").evaluate("(e) => e.style.width") == "60%", "the progress poll", timeout=6)
    va = m.add_version("eyewhite", "regen", "시드 1234", seed=1234)
    vb = m.add_version("irides", "regen", "시드 1234", seed=1234)
    m.state["tasks"][0].update(status="done", seed=1234, result={"seed": 1234, "tags": ["eyewhite"], "versions": [
        {"tag": "eyewhite", "version": va, "requested": True}, {"tag": "irides", "version": vb, "requested": False}]})
    until(lambda: "후보 1" in row(s, "eyewhite").inner_text() and "후보 1" in row(s, "irides").inner_text(), "the candidate badges of the whole group")
    assert "다시 생성이 끝났습니다" in page.inner_text("#toasts")
    # the finished task stays while its candidates wait, with a button that applies the whole sample
    until(lambda: "시드 1234 후보 2개 모두 적용" in page.inner_text(".in-task"), "the apply-all button")
    rev0 = m.state["rev"]
    page.click('[data-fk="apply-task1"]')
    until(lambda: any(p == "/task/task1/apply" for _, p, _b in m.calls), "the apply call")
    until(lambda: m.state["rev"] > rev0, "the new revision")
    assert m.layer("eyewhite")["current"] == va and m.layer("irides")["current"] == vb
    until(lambda: page.locator(".in-task").count() == 0, "the task to leave once nothing waits")
    # a body layer: the form names the body group, "자동" seed sends no seed
    row(s, "topwear").click()
    page.click('[data-fk="regen"]')
    assert "몸 12개" in page.inner_text(".in-regen")
    page.click('[data-fk="regen-submit"]')
    until(lambda: len([1 for _, p, _b in m.calls if p == "/regen"]) == 2, "the second regen call")
    body = [b for _, p, b in m.calls if p == "/regen"][1]
    assert body == {"tags": ["topwear"], "steps": 30}, body
    assert s.errors == []


def test_regen_is_disabled_when_the_server_cannot_do_it(studio):
    s = studio(can_regen=False).open(QUIET)
    row(s, "topwear").click()
    assert s.page.locator('[data-fk="regen"]').is_disabled()
    assert "GPU 작업기" in s.page.inner_text(".in-layer")
    assert s.errors == []


# ------------------------------------------------------------------------------------------------ status views
def test_queued_running_failed_and_gone_views(studio, site):
    q = site.add_job("queued", prompt="차분한 포즈로")
    r = site.add_job("running", stage="decompose", progress=0.4, message="분해 중", started_at=time.time() - 30)
    f = site.add_job("failed", stage="failed", error="캐릭터를 분해하지 못했습니다", finished_at=time.time())
    s = studio(mock=False)
    page = s.page
    s.open("test=0", wait=False, jid=q)
    page.wait_for_selector("#title")
    until(lambda: "만드는 중" in page.inner_text("#title"), "the queued title")
    assert "대기 중" in page.inner_text("#badge")
    import re
    assert re.search(r"대기열 \d+번째", page.inner_text("#qinfo"))
    main = rect(page, "main")
    assert abs(main["w"] - 1280) < 1 and abs(main["x"]) < 1                           # wide, left aligned, no wrapper
    until(lambda: page.locator("#srcCard").is_visible() and s.js("() => document.querySelector('#srcImg').naturalWidth") > 0, "the uploaded image")
    assert "차분한 포즈로" in page.inner_text("#srcPrompt")
    assert page.locator("#result").is_hidden()
    assert "만들기" in page.inner_text("header.site") and page.locator("#navMineCount").inner_text() == "1"   # the shared header, with the count of my puppets
    # it is remembered in "내 퍼펫"
    mine = s.js("() => JSON.parse(localStorage.getItem('i2l_mine_v1') || '[]').map((x) => x.id)")
    assert q in mine
    # running: progress bar + stepper + message (server-sent events)
    s.open("test=0", wait=False, jid=r)
    until(lambda: "처리 중" in page.inner_text("#badge"), "the running badge")
    assert page.get_attribute("#pbar", "aria-valuenow") == "40" and "40%" in page.inner_text("#msg") and "분해 중" in page.inner_text("#msg")
    assert page.locator(".stepper .s.on").inner_text().startswith("레이어 분해") and page.locator(".stepper .s.done").count() == 1
    # progress moves with the server (SSE)
    site.db.update(r, progress=0.85, stage="rig", message="리깅")
    until(lambda: page.get_attribute("#pbar", "aria-valuenow") == "85", "the progress update", timeout=6)
    assert page.locator(".stepper .s.on").inner_text().startswith("리깅") and page.locator(".stepper .s.done").count() == 3
    # failed
    s.open("test=0", wait=False, jid=f)
    until(lambda: "처리하지 못했습니다" in page.inner_text("#title"), "the failed title")
    assert "실패" in page.inner_text("#badge") and "캐릭터를 분해하지 못했습니다" in page.inner_text("#err")
    assert page.locator("#statusActions a").is_visible() and page.locator("#srcCard").is_hidden()
    # gone
    page.goto(site.url + "/j/" + "z" * 22)
    until(lambda: "삭제되었거나 만료된 작업" in page.inner_text("#title"), "the gone title")
    assert page.locator("#pbar").is_hidden()
    assert [e for e in s.errors if "404" not in e and "Failed to load resource" not in e] == []


def test_a_running_job_turns_into_the_studio_when_it_finishes(studio, site):
    jid = site.add_job("running", stage="package", progress=0.97, message="packaging", started_at=time.time() - 60)
    d = site.cfg.jobs_dir / jid
    shutil.copytree(site.jdir, d, dirs_exist_ok=True)                                # the finished files appear next to the job
    s = studio(mock=False)
    s.mock = fx.StudioMock(jid, d)
    s.mock.install(s.page)
    s.open("test=1&" + QUIET, wait=False, jid=jid)
    until(lambda: "처리 중" in s.page.inner_text("#badge"), "the running view")
    assert s.page.locator("#result").is_hidden()
    result = site.db.get(site.job_id)["result_json"]
    site.db.update(jid, status="done", stage="done", progress=1.0, finished_at=time.time(), result_json=result)
    s.ready(timeout=40000)                                                         # SSE pushed "done": the studio starts by itself
    assert s.page.locator("#result").is_visible() and s.page.locator("#vStatus").is_hidden()
    assert s.page.locator(".lp-row").count() == 23
    assert s.js("() => document.title") == "img2live — 퍼펫 스튜디오"
    assert s.errors == []


def test_opening_a_job_adds_it_to_my_puppets_and_deleting_removes_it(studio, site):
    s = studio().open(QUIET)
    mine = s.js("() => JSON.parse(localStorage.getItem('i2l_mine_v1') || '[]')")
    assert [x["id"] for x in mine] == [site.job_id] and "차분하게" in mine[0]["prompt"]
    jid = site.add_job("failed", error="x", finished_at=time.time())               # a second, disposable job to delete
    s2 = studio(mock=False)
    s2.page.goto(site.job(jid))
    until(lambda: "처리하지 못했습니다" in s2.page.inner_text("#title"), "the failed view")
    assert jid in s2.js("() => JSON.parse(localStorage.getItem('i2l_mine_v1') || '[]').map((x) => x.id)")


def test_delete_from_the_files_tab_leaves_the_page(browser, tmp_path):
    other = fx.Site(tmp_path)                                                      # a private copy so the shared job survives
    s = Studio(browser, other)
    try:
        s.open(QUIET)
        s.page.click(".in-tabs [data-tab=files]")
        s.page.click("#inspector button:has-text('이 퍼펫 삭제')")
        s.page.wait_for_url(other.url + "/")
        assert s.js("() => JSON.parse(localStorage.getItem('i2l_mine_v1') || '[]').length") == 0
        assert other.db.get(other.job_id)["status"] == "deleted"
        assert any("삭제할까요" in d for d in s.dialogs)
    finally:
        s.close()
        other.close()


# ------------------------------------------------------------------------------------------------ real backend (when deployed)
def _real_studio_available(site) -> bool:
    import urllib.request

    try:
        with urllib.request.urlopen(f"{site.url}/api/jobs/{site.job_id}/studio", timeout=10) as r:
            return r.status == 200
    except Exception:  # noqa: BLE001 - not deployed in this checkout
        return False


def test_with_the_real_studio_backend_round_trip(browser, tmp_path):
    """No mocks: the real REST endpoints, the real recompiled puppets (/files/<id>/studio/puppet/r<N>) and the real layer editor module."""
    import base64
    import io

    import numpy as np
    from PIL import Image

    site = fx.Site(tmp_path)                                                       # a private copy: this test changes the job
    if not _real_studio_available(site):
        site.close()
        pytest.skip("the real /studio endpoint is not available in this checkout")
    s = Studio(browser, site, mock=False)
    try:
        s.open(QUIET)
        page = s.page
        assert s.js("() => window.__studio.degraded") is False
        assert page.locator(".lp-row").count() == 23
        until(lambda: s.js("() => [...document.querySelectorAll('.lp-row:not(.is-empty) .lp-thumb img')].every((i) => i.naturalWidth > 0)"), "real thumbnails")
        assert s.js("() => window.__studio.stage.url") == f"/files/{site.job_id}/puppet/puppet.json"
        # flags -> the server recompiles -> the stage loads /files/<id>/studio/puppet/r1
        row(s, "neck").click()
        page.wait_for_selector(".in-title h3")
        assert "[1, 2]" not in page.inner_text(".in-kv") and "목" in page.inner_text(".in-title") and "위치" in page.inner_text(".in-kv")
        page.locator(".st-switch", has_text="퍼펫에 포함").click()
        until(lambda: s.js("() => window.__studio.stage.url").endswith("/studio/puppet/r1/puppet.json"), "the recompiled puppet", timeout=40)
        until(lambda: s.js("() => window.__studio.stage.hasLayer('neck')") is False, "the neck to be gone from the puppet")
        until(lambda: "제외됨" in row(s, "neck").inner_text(), "the excluded badge")
        # an edit made through the API shows up as a version; undo it from the list, then delete it
        m = np.zeros((1280, 1280), np.uint8)
        m[400:460, 600:660] = 255
        buf = io.BytesIO()
        Image.fromarray(m, "L").save(buf, "PNG")
        mask = base64.b64encode(buf.getvalue()).decode()
        s.js("async (mask) => { const r = await window.__studio.api.edit('topwear', { op: 'erase', mask, note: '시험 지우기' }); await window.__studio.applyState(r.state); }", mask)
        row(s, "topwear").click()
        until(lambda: page.locator(".in-ver").count() == 2 and "편집됨" in row(s, "topwear").inner_text(), "the edit version", timeout=40)
        page.locator(".in-ver", has_text="원본").locator(".in-ver-main").click()
        until(lambda: page.locator(".in-ver.is-current", has_text="원본").count() == 1, "undo to v0", timeout=40)
        until(lambda: s.js("() => [...document.querySelectorAll('.in-ver-thumb img')].every((i) => i.naturalWidth > 0)"), "version thumbnails from the server")
        page.locator(".in-ver", has_text="편집").locator(".in-ver-del").click()
        until(lambda: page.locator(".in-ver").count() == 1, "the edit version to be deleted", timeout=40)
        # the real layer editor mounts inside the studio and the way back works
        page.click('[data-fk="edit"]')
        page.wait_for_selector(".le-root", timeout=20000)
        assert s.js("async () => { await window.__studio.editor.whenReady(); return true; }") is True
        assert page.locator("#stageMount").is_hidden() and page.locator("#editorBox").is_visible()
        page.click("#editorBack")
        until(lambda: page.locator("#stageMount").is_visible(), "the stage to return")
        # reset everything: the neck is back
        page.click('[data-fk="reset-all"]')
        until(lambda: s.js("() => window.__studio.stage.hasLayer('neck')") is True, "the neck to return after the reset", timeout=40)
        until(lambda: page.locator(".lp-badge", has_text="제외됨").count() == 0, "badges to clear")
        assert [e for e in s.errors if "confirm" not in e] == [], s.errors
    finally:
        s.close()
        site.close()


# ------------------------------------------------------------------------------------------------ screenshots
def _dress(mock):
    """A lived-in state for the review pictures: an edit, two candidates, an excluded layer, a task."""
    mock.add_version("front hair", "edit", "앞머리 끝을 다듬음", make_current=True)
    mock.add_version("front hair", "regen", "시드 77로 다시 생성", seed=77)
    mock.add_version("front hair", "regen", "시드 1234 · 스텝 40", seed=1234)
    mock.add_version("front hair", "auto", "자동 정리: 가장자리 색 보정")
    mock.add_version("face", "regen", "시드 7로 다시 생성", seed=7)
    mock.add_version("topwear", "edit", "소매의 얼룩을 지움", make_current=True)
    mock.layer("nose")["enabled"] = False
    mock.state["tasks"] = [{"id": "t1", "kind": "regen", "tags": ["back hair"], "status": "running", "progress": 0.45, "message": "생성 중 (스텝 14/30)"}]
    mock.bump()


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("w,h", [(1920, 1080), (1280, 800)])
def test_screenshots(studio, w, h, scheme):
    SHOTS.mkdir(parents=True, exist_ok=True)
    s = studio(viewport=(w, h), scheme=scheme)
    _dress(s.mock)
    s.open(QUIET + "&camera=fit")
    page = s.page
    until(lambda: s.js("() => [...document.querySelectorAll('.lp-row:not(.is-empty) .lp-thumb img')].every((i) => i.naturalWidth > 0)"), "thumbnails")
    row(s, "back hair").locator(".lp-eye").click()                                  # a hidden layer shows in the list
    row(s, "front hair").click()                                                    # selection + layer tab with versions
    until(lambda: s.js("() => [...document.querySelectorAll('.in-ver-thumb img')].every((i) => i.naturalWidth > 0)"), "version thumbnails")
    settle(page, 5)
    page.screenshot(path=str(SHOTS / f"studio_{w}x{h}_{scheme}_layer.png"))
    page.click(".in-tabs [data-tab=motion]")
    row(s, "back hair").locator(".lp-eye").click()
    s.js("() => { const p = window.__studio.stage.params; p.set('ParamAngleX', 14); p.set('ParamAngleZ', -6); p.set('ParamMouthOpenY', 0.5); }")
    settle(page, 5)
    page.screenshot(path=str(SHOTS / f"studio_{w}x{h}_{scheme}_motion.png"))
    assert (SHOTS / f"studio_{w}x{h}_{scheme}_layer.png").stat().st_size > 20000
    assert [e for e in s.errors] == []


def test_screenshots_narrow_status_and_degraded(studio, site):
    SHOTS.mkdir(parents=True, exist_ok=True)
    s = studio(viewport=(800, 900))
    _dress(s.mock)
    s.open(QUIET)
    s.page.click('[data-tool="left"]')
    until(lambda: rect(s.page, "#stLeft")["x"] >= -1, "the drawer")
    settle(s.page, 3)
    s.page.screenshot(path=str(SHOTS / "studio_800x900_light_drawer.png"))
    d = studio(viewport=(1280, 800), mock=False, scheme="dark")
    d.page.route(f"**/api/jobs/{site.job_id}/studio", lambda route, req: route.fulfill(status=404, body="", content_type="text/plain"))
    d.open(QUIET)
    row(d, "face").click()
    settle(d.page, 4)
    d.page.screenshot(path=str(SHOTS / "studio_1280x800_dark_degraded.png"))
    q = site.add_job("running", stage="decompose", progress=0.55, message="분해 중", started_at=time.time() - 120)
    st = studio(viewport=(1920, 1080), mock=False)
    st.open("test=0", wait=False, jid=q)
    until(lambda: st.page.locator("#srcCard").is_visible() and st.js("() => document.querySelector('#srcImg').naturalWidth") > 0, "the source image")
    st.page.screenshot(path=str(SHOTS / "status_running_1920x1080_light.png"))
    assert (SHOTS / "studio_800x900_light_drawer.png").exists()


# ------------------------------------------------------------------------------------------------ WebM recording
def _probe(path: str) -> dict:
    """ffprobe the take: container, codec, duration and the alpha flag."""
    import shutil
    import subprocess

    if not shutil.which("ffprobe"):
        pytest.skip("ffprobe is not installed")
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                          "stream=codec_name,width,height:stream_tags=alpha_mode:format=duration", "-of", "json", path],
                         capture_output=True, text=True, check=True).stdout
    j = json.loads(out)
    st = (j.get("streams") or [{}])[0]
    # the alpha_mode tag only says the stream HAS an alpha plane (Chrome sets it for any canvas); decode a frame to see the pixels
    import tempfile
    import numpy as np
    from PIL import Image
    png = tempfile.mktemp(suffix=".png")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", path, "-frames:v", "1", "-pix_fmt", "rgba", png], check=True)
    px = np.asarray(Image.open(png).convert("RGBA"))
    return {"codec": st.get("codec_name"), "w": st.get("width"), "h": st.get("height"),
            "alpha_plane": (st.get("tags") or {}).get("alpha_mode") == "1",
            "transparent": float((px[..., 3] == 0).mean()), "green": float(((px[..., 1] > px[..., 0] + 40) & (px[..., 1] > px[..., 2] + 40) & (px[..., 3] == 255)).mean()),
            "duration": float((j.get("format") or {}).get("duration") or 0)}


def _record(s, seconds=1.4):
    """Press the toolbar's record button, let the puppet move for a moment, press it again and return the downloaded file."""
    page = s.page
    page.click('[data-tool="rec"]')
    until(lambda: s.js("() => window.__studio.stage.recording") is True, "recording to start")
    assert page.get_attribute('[data-tool="rec"]', "aria-pressed") == "true"
    assert page.locator(".st-rec-time").is_visible()
    page.locator('input[data-param="ParamAngleX"]').focus()
    page.keyboard.press("Home"); time.sleep(seconds / 2); page.keyboard.press("End"); time.sleep(seconds / 2)   # something moves
    with page.expect_download() as dl:
        page.click('[data-tool="rec"]')
    return dl.value


def test_recording_saves_a_transparent_webm(studio):
    s = studio().open("idle=1&blink=1&physics=1")
    page = s.page
    d = _record(s)
    assert d.suggested_filename.startswith("img2live-") and d.suggested_filename.endswith(".webm")
    data = Path(d.path()).read_bytes()
    assert data[:4] == bytes.fromhex("1a45dfa3") and len(data) > 5000                    # a real WebM (EBML header), not an empty blob
    info = _probe(d.path())
    assert info["codec"] == "vp9" and info["alpha_plane"] and info["duration"] >= 0.8, info      # VP9, and the length is written in
    assert info["transparent"] > 0.3, info                                               # the background really is see-through
    until(lambda: s.js("() => window.__studio.stage.recording") is False, "recording to stop")
    assert page.get_attribute('[data-tool="rec"]', "aria-pressed") == "false" and page.locator(".st-rec-time").is_hidden()
    assert "녹화를 저장했습니다" in page.inner_text("#toasts")
    assert s.errors == []


def test_recording_the_screen_background_has_no_alpha_and_the_inspector_controls_it(studio):
    s = studio().open("idle=1&physics=1")
    page = s.page
    page.click('.in-bgbtn[data-bg="green"]')
    assert "WebM 녹화 시작" in page.inner_text('[data-fk="record"]') and "알파" in page.inner_text(".in-save")
    page.select_option('[data-fk="rec-bg"]', "screen"); page.select_option('[data-fk="rec-fps"]', "30")
    assert s.js("() => window.__studio.stage.recordOptions") == {"alpha": False, "fps": 30, "bitrate": 8000000}
    page.click('[data-fk="record"]')                                                    # start from the inspector ...
    until(lambda: s.js("() => window.__studio.stage.recording") is True, "recording to start")
    assert page.is_disabled('[data-fk="rec-bg"]') and "녹화 중지" in page.inner_text('[data-fk="record"]')
    assert page.locator(".is-recording").count() == 1 and page.locator(".rec-alpha").count() == 0    # no checkerboard: the screen is recorded
    time.sleep(1.0)
    with page.expect_download() as dl:
        page.click('[data-tool="rec"]')                                                 # ... stop from the toolbar: the same recording
    info = _probe(dl.value.path())
    assert info["codec"] in ("vp9", "vp8") and info["duration"] >= 0.6, info
    assert info["transparent"] == 0.0 and info["green"] > 0.3, info                      # the green screen background is in the picture, nothing is see-through
    assert "WebM 녹화 시작" in page.inner_text('[data-fk="record"]') and not page.is_disabled('[data-fk="rec-bg"]')
    assert s.errors == []


def test_a_puppet_reload_during_a_recording_still_saves_the_take(studio):
    s = studio().open("idle=1&physics=1")
    page, m = s.page, s.mock
    page.click('[data-tool="rec"]')
    until(lambda: s.js("() => window.__studio.stage.recording") is True, "recording to start")
    time.sleep(0.8)
    m.layer("nose")["enabled"] = False
    with page.expect_download() as dl:                                                  # the canvas is replaced: the take is finished and saved
        s.js(f"() => window.__studio.applyState({json.dumps(_snapshot(m, 7))})")
    assert dl.value.suggested_filename.endswith(".webm") and Path(dl.value.path()).stat().st_size > 2000
    until(lambda: s.js("() => window.__studio.stage.recording") is False, "recording state to clear")
    until(lambda: "퍼펫이 바뀌어 녹화를 마치고 저장했습니다" in page.inner_text("#toasts"), "the explanation")
    assert page.get_attribute('[data-tool="rec"]', "aria-pressed") == "false"
    assert s.js("() => document.querySelectorAll('canvas.stage-canvas').length") == 1
    assert s.errors == []


def test_recording_is_disabled_where_the_browser_cannot_do_it(browser, site):
    s = Studio(browser, site)
    try:
        s.page.add_init_script("delete window.MediaRecorder;")
        s.open(QUIET)
        assert s.page.is_disabled('[data-tool="rec"]') and s.page.is_disabled('[data-fk="record"]')
        assert "지원하지 않습니다" in s.page.inner_text(".in-save")
        assert s.errors == []
    finally:
        s.close()
