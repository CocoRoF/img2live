# SPDX-License-Identifier: Apache-2.0
"""Browser tests of the layer editor (js/layer-editor.js) against a FAKE studio api.

The harness page `layer-editor-test.html` builds synthetic layers + a synthetic source image in the page, records every api.edit
payload on `window.__calls` and applies the operation to its in-memory layers like the real server would.  The page is served by
the real img2live app (`/static/...`), so the production Content-Security-Policy applies (no inline scripts, no eval): the tests
poll from Python instead of using `wait_for_function`.

Needs playwright (python), /usr/bin/google-chrome (IMG2LIVE_CHROME), numpy, pillow, scipy.
Screenshots (light + dark, 1920x1080 and 1280x800) go to bench/outputs/editor_shots/.
"""
from __future__ import annotations

import base64
import io
import json
import os
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
CHROME_PATH = os.environ.get("IMG2LIVE_CHROME", "/usr/bin/google-chrome")
SHOTS = ROOT / "bench" / "outputs" / "editor_shots"
sync_api = pytest.importorskip("playwright.sync_api", reason="playwright is not installed")
uvicorn = pytest.importorskip("uvicorn")
PIL_Image = pytest.importorskip("PIL.Image")
ndi = pytest.importorskip("scipy.ndimage")
if not Path(CHROME_PATH).exists():
    pytest.skip(f"{CHROME_PATH} not found (set IMG2LIVE_CHROME)", allow_module_level=True)

from img2live.config import Settings  # noqa: E402
from img2live.server.app import create_app  # noqa: E402

N = 1280
HARNESS = "/static/layer-editor-test.html"

# Instrumentation injected before the page's own scripts: global listener bookkeeping, blob URLs, getImageData calls, smoothing flag.
INIT = r"""
(() => {
  const live = new Map();
  const nameOf = (t) => (t === window ? "window" : t === document ? "document" : null);
  const add = EventTarget.prototype.addEventListener, rem = EventTarget.prototype.removeEventListener;
  const key = (n, type, o) => `${n}:${type}:${typeof o === "object" && o ? !!o.capture : !!o}`;
  EventTarget.prototype.addEventListener = function (type, fn, o) {
    const n = nameOf(this);
    if (n && fn) { const k = key(n, type, o); if (!live.has(k)) live.set(k, new Set()); live.get(k).add(fn); }
    return add.call(this, type, fn, o);
  };
  EventTarget.prototype.removeEventListener = function (type, fn, o) {
    const n = nameOf(this);
    if (n && fn) { const k = key(n, type, o); const s = live.get(k); if (s) { s.delete(fn); if (!s.size) live.delete(k); } }
    return rem.call(this, type, fn, o);
  };
  window.__liveListeners = () => { let n = 0; for (const s of live.values()) n += s.size; return n; };
  const blobs = new Set(), cu = URL.createObjectURL, ru = URL.revokeObjectURL;
  URL.createObjectURL = function (b) { const u = cu.call(URL, b); blobs.add(u); return u; };
  URL.revokeObjectURL = function (u) { blobs.delete(u); return ru.call(URL, u); };
  window.__liveBlobs = () => blobs.size;
  let gid = 0; const g = CanvasRenderingContext2D.prototype.getImageData;
  CanvasRenderingContext2D.prototype.getImageData = function (...a) { gid++; return g.apply(this, a); };
  window.__getImageDataCount = () => gid;
  const di = CanvasRenderingContext2D.prototype.drawImage;
  CanvasRenderingContext2D.prototype.drawImage = function (...a) {
    if (this.canvas && this.canvas.classList && this.canvas.classList.contains("le-view") && a[0] && a[0].width === 1280) window.__lastSmooth = this.imageSmoothingEnabled;
    return di.apply(this, a);
  };
})();
"""


def until(fn, what, timeout=8.0):
    """Poll a Python predicate (the page's CSP forbids wait_for_function, which evals a string)."""
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {what}")


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("editor-site")
    cfg = Settings(data_dir=tmp)
    cfg.ensure_dirs()
    cfg.gate_enabled = False
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


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(executable_path=CHROME_PATH, args=["--no-sandbox"])
        yield b
        b.close()


def decode_png(b64: str, mode="RGBA") -> np.ndarray:
    return np.array(PIL_Image.open(io.BytesIO(base64.b64decode(b64))).convert(mode))


class Ed:
    """Thin driver around the harness page."""

    def __init__(self, page, base, errors):
        self.page, self.base, self.errors = page, base, errors
        self.scene = page.evaluate("window.__scene")

    # ---- page access
    def ev(self, expr, arg=None):
        return self.page.evaluate(expr, arg) if arg is not None else self.page.evaluate(expr)

    def state(self):
        return self.ev("window.__ed.getState()")

    def calls(self):
        return self.ev("window.__calls")

    def set_view(self, zoom=1, x=0, y=0):
        """Exact view (test hook): grid pixel (gx, gy) is at stage (x + gx*zoom, y + gy*zoom)."""
        self.ev("([z,x,y]) => window.__ed.setView({zoom: z, x, y})", [zoom, x, y])

    def pt(self, gx, gy):
        r = self.ev("([x, y]) => window.__ed.gridToClient(x, y)", [gx, gy])
        return r["x"], r["y"]

    def stage_box(self):
        return self.page.locator(".le-stage").bounding_box()

    # ---- mouse in grid coordinates
    def click(self, gx, gy, *mods, button="left"):
        x, y = self.pt(gx, gy)
        for m in mods:
            self.page.keyboard.down(m)
        self.page.mouse.click(x, y, button=button)
        for m in reversed(mods):
            self.page.keyboard.up(m)

    def drag(self, pts, *mods, button="left", steps=6):
        for m in mods:
            self.page.keyboard.down(m)
        x, y = self.pt(*pts[0])
        self.page.mouse.move(x, y)
        self.page.mouse.down(button=button)
        for p in pts[1:]:
            x, y = self.pt(*p)
            self.page.mouse.move(x, y, steps=steps)
        self.page.mouse.up(button=button)
        for m in reversed(mods):
            self.page.keyboard.up(m)

    # ---- masks as numpy
    def mask(self) -> np.ndarray:
        url = self.ev("window.__ed.getMask().toDataURL('image/png')")
        return decode_png(url.split(",", 1)[1])[:, :, 3]

    def count(self) -> int:
        return int(self.ev("""() => { const d = window.__ed.getMask().getContext('2d').getImageData(0, 0, 1280, 1280).data; let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 127) n++; return n; }"""))

    def layer(self, tag="body") -> np.ndarray:
        return decode_png(self.ev("(t) => window.__harness.layerDataUrl(t)", tag).split(",", 1)[1])

    def source(self, grid="canvas") -> np.ndarray:
        return decode_png(self.ev("(g) => window.__harness.sourceDataUrl(g)", grid).split(",", 1)[1])

    def view_px(self, gx, gy):
        """RGBA of the main view canvas at grid pixel (gx, gy) (device pixel ratio 1)."""
        return self.ev("""([gx, gy]) => { const ed = window.__ed; ed.flush(); const st = document.querySelector('.le-stage').getBoundingClientRect();
            const p = ed.gridToClient(gx + 0.5, gy + 0.5); const ctx = ed.getViewCanvas().getContext('2d');
            return [...ctx.getImageData(Math.floor(p.x - st.left), Math.floor(p.y - st.top), 1, 1).data]; }""", [gx, gy])

    # ---- ui
    def tool(self, name):
        self.page.click(f'[data-tool="{name}"]')

    def act(self, name):
        self.page.click(f'[data-act="{name}"]')

    def set_num(self, label, value):
        self.page.fill(f'input.le-num[aria-label="{label} 값"]', str(value))

    def enabled(self, act):
        return not self.page.locator(f'[data-act="{act}"]').is_disabled()

    def wait_idle(self, ops_done=None):
        until(lambda: not self.state()["busy"] and (ops_done is None or self.state()["ops"] >= ops_done), "the request to finish")
        until(lambda: self.state()["ready"], "the layer to reload")

    def apply(self, act):
        n = self.state()["ops"]
        self.act(act)
        self.wait_idle(n + 1)

    def payload_mask(self, call) -> np.ndarray:
        return decode_png(call["payload"]["mask"], "L")


def open_editor(browser, site, query="", viewport=(1600, 900), scheme="light"):
    ctx = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, color_scheme=scheme)
    ctx.add_init_script(INIT)
    page = ctx.new_page()
    errors: list = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" else None)
    page.goto(site + HARNESS + query)
    until(lambda: page.evaluate("document.documentElement.dataset.ready") == "1", "the harness to be ready", 15)
    ed = Ed(page, site, errors)
    ed.ctx = ctx
    return ed


@pytest.fixture()
def ed(browser, site):
    e = open_editor(browser, site)
    yield e
    errs = [x for x in e.errors if "favicon" not in x]
    e.ctx.close()
    assert errs == [], f"console/page errors: {errs}"


@pytest.fixture()
def make_ed(browser, site):
    made = []

    def make(query="", viewport=(1600, 900), scheme="light", allow_errors=False):
        e = open_editor(browser, site, query, viewport, scheme)
        e.allow_errors = allow_errors
        made.append(e)
        return e

    yield make
    for e in made:
        errs = [x for x in e.errors if "favicon" not in x]
        e.ctx.close()
        if not getattr(e, "allow_errors", False):
            assert errs == [], f"console/page errors: {errs}"


# ---------------------------------------------------------------------------------------------------- references (numpy / scipy)
def wand_ref(rgba, sx, sy, metric="rgb", tol=32, contiguous=True, win=1):
    px = rgba.astype(np.float64)
    if win > 1:
        h = (win - 1) // 2
        seed = px[sy - h:sy + h + 1, sx - h:sx + h + 1].reshape(-1, 4).mean(0)
    else:
        seed = px[sy, sx]
    da = np.abs(px[:, :, 3] - seed[3])
    if metric == "alpha":
        d = da
    elif metric == "luma":
        y = 0.2126 * px[:, :, 0] + 0.7152 * px[:, :, 1] + 0.0722 * px[:, :, 2]
        sy_ = 0.2126 * seed[0] + 0.7152 * seed[1] + 0.0722 * seed[2]
        d = np.maximum(np.abs(y - sy_), da)
    else:
        d = np.maximum.reduce([da, np.abs(px[:, :, 0] - seed[0]), np.abs(px[:, :, 1] - seed[1]), np.abs(px[:, :, 2] - seed[2])])
    ok = d <= tol
    ok[sy, sx] = True
    if not contiguous:
        return ok
    lab, _ = ndi.label(ok)                               # 4-connected
    return lab == lab[sy, sx]


def disc_area(r):
    return int(sum(2 * int(np.floor(np.sqrt(r * r - dy * dy))) + 1 for dy in range(-r, r + 1)))


# ---------------------------------------------------------------------------------------------------- mount / view
def test_mount_dispose_leaves_nothing_behind(ed):
    st = ed.state()
    assert st["ready"] and st["tool"] == "brush" and st["overlay"] == "blend" and not st["hasSelection"] and st["undoDepth"] == 0
    assert ed.ev("[window.__ed.getMask().width, window.__ed.getMask().height]") == [N, N]
    assert ed.page.locator(".le-root").count() == 1
    assert ed.page.locator(".le-toolbox [data-tool]").count() == 8
    ed.ev("window.__harness.dispose()")
    base_listeners = ed.ev("window.__liveListeners()")
    assert ed.page.locator(".le-root").count() == 0
    ed.ev("window.__harness.mount()")
    until(lambda: ed.state()["ready"], "remount")
    assert ed.ev("window.__liveListeners()") > base_listeners                 # keydown / keyup / blur / pointerdown
    ed.tool("wand")
    x, y = ed.pt(900, 600)
    ed.page.mouse.click(x, y)
    until(lambda: ed.ev("getComputedStyle(document.querySelector('.le-ants')).maskImage").startswith("url("), "the marching-ants mask")
    mask_cv = ed.ev("(window.__keep = window.__ed.getMask(), 1)")
    ed.ev("window.__harness.dispose()")
    assert ed.ev("window.__liveListeners()") == base_listeners, "dispose must remove every window/document listener"
    assert ed.ev("window.__keep.width") == 0, "dispose releases the canvases"
    assert ed.page.locator(".le-root").count() == 0
    until(lambda: ed.ev("window.__liveBlobs()") == 0, "every blob URL to be revoked", 3)
    ed.ev("window.__ed = null")


def test_fit_on_open_frames_the_layer(ed):
    st = ed.state()
    bb = st["layerBBox"]
    stage = ed.stage_box()
    ys, xs = np.where(ed.layer()[:, :, 3] > 16)
    assert bb == {"x0": int(xs.min()), "y0": int(ys.min()), "x1": int(xs.max()), "y1": int(ys.max())}
    x0, y0 = ed.pt(bb["x0"], bb["y0"])
    x1, y1 = ed.pt(bb["x1"] + 1, bb["y1"] + 1)
    assert stage["x"] <= x0 and x1 <= stage["x"] + stage["width"] and stage["y"] <= y0 and y1 <= stage["y"] + stage["height"], "the whole layer is visible"
    # it fills the limiting dimension to within the margin
    fill = max((x1 - x0) / stage["width"], (y1 - y0) / stage["height"])
    assert 0.8 < fill <= 0.95
    ed.set_view(3, -400, -400)
    ed.act("fit")
    assert abs(ed.state()["zoom"] - st["zoom"]) < 1e-6


def test_zoom_wheel_keeps_cursor_point_and_buttons(ed):
    x, y = (round(v) for v in ed.pt(900, 600))                         # mouse events carry whole pixels
    before = ed.ev("([x, y]) => window.__ed.clientToGrid(x, y)", [x, y])
    z0 = ed.state()["zoom"]
    ed.page.mouse.move(x, y)
    ed.page.mouse.wheel(0, -300)
    until(lambda: ed.state()["zoom"] > z0 * 1.3, "wheel zoom in")
    after = ed.ev("([x, y]) => window.__ed.clientToGrid(x, y)", [x, y])
    assert abs(after["x"] - before["x"]) < 0.01 and abs(after["y"] - before["y"]) < 0.01, "the pixel under the cursor stays put"
    z1 = ed.state()["zoom"]
    ed.page.mouse.wheel(0, 300)
    until(lambda: ed.state()["zoom"] < z1 * 0.8, "wheel zoom out")
    ed.act("zoom-in")
    z = ed.state()["zoom"]
    ed.act("zoom-out")
    assert ed.state()["zoom"] < z
    ed.act("zoom100")
    assert abs(ed.state()["zoom"] - 1) < 1e-9
    assert "100%" in ed.page.locator(".le-st-zoom").inner_text()
    ed.act("fit")
    assert abs(ed.state()["zoom"] - z0) < 1e-6
    lo = ed.ev("() => { for (let i = 0; i < 60; i++) window.__ed.zoomTo(window.__ed.getState().zoom * 0.5); return window.__ed.getState().zoom; }")
    hi = ed.ev("() => { for (let i = 0; i < 60; i++) window.__ed.zoomTo(window.__ed.getState().zoom * 2); return window.__ed.getState().zoom; }")
    assert lo >= 0.05 - 1e-9 and hi <= 32 + 1e-9


def test_pan_with_space_middle_button_and_hand_tool(ed):
    s0 = ed.state()
    x, y = ed.pt(640, 640)
    # space + drag
    ed.page.keyboard.down("Space")
    ed.page.mouse.move(x, y)
    ed.page.mouse.down()
    ed.page.mouse.move(x + 70, y + 40, steps=4)
    ed.page.mouse.up()
    ed.page.keyboard.up("Space")
    s1 = ed.state()
    assert abs((s1["panX"] - s0["panX"]) - 70) < 1 and abs((s1["panY"] - s0["panY"]) - 40) < 1
    assert not s1["hasSelection"] and s1["undoDepth"] == 0, "panning must not paint"
    # middle button
    x, y = ed.pt(640, 640)
    ed.page.mouse.move(x, y)
    ed.page.mouse.down(button="middle")
    ed.page.mouse.move(x - 30, y - 20, steps=3)
    ed.page.mouse.up(button="middle")
    s2 = ed.state()
    assert abs((s2["panX"] - s1["panX"]) + 30) < 1 and abs((s2["panY"] - s1["panY"]) + 20) < 1
    # right button
    x, y = ed.pt(640, 640)
    ed.page.mouse.move(x, y)
    ed.page.mouse.down(button="right")
    ed.page.mouse.move(x + 10, y + 10, steps=3)
    ed.page.mouse.up(button="right")
    s3 = ed.state()
    assert abs((s3["panX"] - s2["panX"]) - 10) < 1
    # hand tool
    ed.tool("hand")
    x, y = ed.pt(640, 640)
    ed.page.mouse.move(x, y)
    ed.page.mouse.down()
    ed.page.mouse.move(x - 15, y + 5, steps=3)
    ed.page.mouse.up()
    s4 = ed.state()
    assert abs((s4["panX"] - s3["panX"]) + 15) < 1 and not s4["hasSelection"]


def test_zoom_tool_click_alt_click_and_drag_box(ed):
    ed.tool("zoom")
    z0 = ed.state()["zoom"]
    ed.click(640, 640)
    z1 = ed.state()["zoom"]
    assert abs(z1 / z0 - 2) < 1e-6
    ed.click(640, 640, "Alt")
    assert abs(ed.state()["zoom"] / z1 - 0.5) < 1e-6
    ed.drag([(560, 600), (720, 700)])
    assert ed.state()["zoom"] > 3


def test_pixels_are_crisp_when_zoomed_in(ed):
    ed.set_view(1.5, 0, 0)
    ed.ev("window.__ed.flush()")
    assert ed.ev("window.__lastSmooth") is True
    ed.set_view(4, -4 * 860, -4 * 790)                   # grid (860, 790) at the stage's top-left corner
    ed.ev("window.__ed.flush()")
    assert ed.ev("window.__lastSmooth") is False, "imageSmoothingEnabled must be off above 200%"
    # no interpolation: a hard body edge is only ever the body colour or a checker colour along a scanline
    gx = 640 + 230                                        # right edge of the body at y = 800
    px = [tuple(ed.view_px(gx + d, 800)[:3]) for d in range(-3, 4)]
    assert len(set(px)) <= 3 and (60, 110, 200) in px


# ---------------------------------------------------------------------------------------------------- brush / eraser
def test_brush_adds_to_selection(ed):
    ed.set_view(1, -100, -50)
    ed.set_num("크기", 30)
    ed.set_num("경도", 100)
    ed.drag([(300, 300), (600, 300), (600, 500)])
    m = ed.mask()
    assert m[300, 450] > 250 and m[400, 600] > 250, "centre line of the stroke is selected"
    assert m[300 - 14, 450] > 127 and m[300 - 20, 450] == 0, "radius 15"
    assert m[600, 100] == 0 and m[100, 100] == 0
    st = ed.state()
    assert st["hasSelection"] and st["dirty"] and st["undoDepth"] == 1 and st["redoDepth"] == 0
    assert ed.enabled("erase") and ed.enabled("restore")
    # a second stroke is a second step and adds to the first
    ed.drag([(300, 600), (500, 600)])
    assert ed.state()["undoDepth"] == 2 and ed.mask()[300, 450] > 250 and ed.mask()[600, 400] > 250


def test_brush_size_hardness_and_shortcuts(ed):
    ed.set_view(1, -100, -50)
    ed.page.keyboard.press("]")
    assert ed.state()["brush"]["size"] > 40
    ed.page.keyboard.press("[")
    ed.page.keyboard.press("[")
    assert ed.state()["brush"]["size"] < 40
    ed.set_num("크기", 9999)
    ed.page.locator('input.le-num[aria-label="크기 값"]').blur()
    assert ed.state()["brush"]["size"] == 400
    ed.set_num("크기", 40)
    ed.set_num("경도", 0)
    ed.drag([(400, 400), (401, 400)], steps=1)
    m = ed.mask()
    assert 200 <= m[400, 400] and m[400, 400] <= 255 and 0 < m[400, 400 + 15] < m[400, 400], "soft brush: opaque core, fading edge"
    ed.page.keyboard.press("Control+a")
    ed.page.keyboard.press("Control+d")
    # 1 px brush selects exactly the pixels it touches
    ed.set_num("크기", 1)
    ed.set_num("경도", 100)
    ed.drag([(500, 500), (510, 500)])
    m = ed.mask()
    assert 8 <= int((m > 127).sum()) <= 14 and m[500, 505] > 127 and m[502, 505] == 0


def test_eraser_removes_from_selection(ed):
    ed.set_view(1, -100, -50)
    ed.set_num("크기", 60)
    ed.set_num("경도", 100)
    ed.drag([(300, 400), (700, 400)])
    assert ed.mask()[400, 500] > 250
    ed.tool("eraser")
    ed.set_num("크기", 20)
    ed.drag([(450, 400), (550, 400)])
    m = ed.mask()
    assert m[400, 500] == 0 and m[400, 350] > 250 and m[400, 650] > 250 and m[400 + 25, 500] > 127
    assert ed.state()["undoDepth"] == 2 and ed.state()["tool"] == "eraser"
    ed.page.keyboard.press("x")                           # swap brush/eraser
    assert ed.state()["tool"] == "brush"
    ed.page.keyboard.press("x")
    assert ed.state()["tool"] == "eraser"


def test_brush_stays_smooth_without_per_frame_readback(ed):
    ed.set_view(1, -100, -50)
    ed.set_num("크기", 50)
    ed.set_num("경도", 40)
    x, y = ed.pt(300, 300)
    ed.page.mouse.move(x, y)
    ed.page.mouse.down()
    n0 = ed.ev("window.__getImageDataCount()")
    t0 = time.time()
    for i in range(1, 90):                                # a long fast stroke, many pointer moves
        ed.page.mouse.move(x + i * 5, y + 100 * np.sin(i / 8), steps=2)
    during = ed.ev("window.__getImageDataCount()") - n0
    ed.page.mouse.up()
    assert during == 0, "no getImageData while the stroke is being drawn"
    assert ed.state()["hasSelection"] and ed.state()["undoDepth"] == 1
    m = ed.mask()
    assert (m > 127).sum() > 5000 and m[int(round(300 + 100 * np.sin(40 / 8))), 500] > 100
    assert time.time() - t0 < 25


def test_pen_pressure_scales_the_dab_and_touch_pinch_zooms(ed):
    ed.set_view(1, -100, -50)
    ed.set_num("크기", 60)
    ed.set_num("경도", 100)
    cx, cy = ed.pt(500, 500)

    def stroke(pressure, pid):
        ed.ev("""([cx, cy, p, pid]) => { const s = document.querySelector('.le-stage');
            const mk = (type, x) => new PointerEvent(type, { pointerId: pid, pointerType: 'pen', isPrimary: true, pressure: p, clientX: x, clientY: cy, button: 0, buttons: 1, bubbles: true, cancelable: true });
            s.dispatchEvent(mk('pointerdown', cx)); for (let i = 1; i <= 20; i++) s.dispatchEvent(mk('pointermove', cx + i * 4));
            s.dispatchEvent(new PointerEvent('pointerup', { pointerId: pid, pointerType: 'pen', isPrimary: true, pressure: 0, clientX: cx + 80, clientY: cy, button: 0, bubbles: true })); }""", [cx, cy, pressure, pid])
        n = ed.count()
        ed.page.keyboard.press("Control+d")
        return n

    light, heavy = stroke(0.1, 11), stroke(1.0, 12)
    assert 0 < light < heavy * 0.5, f"low pressure paints a thinner stroke ({light} vs {heavy})"
    # touch: the first finger starts a stroke, the second turns it into a pinch (the stroke is dropped)
    z0 = ed.state()["zoom"]
    ed.ev("""([cx, cy]) => { const s = document.querySelector('.le-stage');
        const mk = (type, id, x, y) => new PointerEvent(type, { pointerId: id, pointerType: 'touch', isPrimary: id === 21, pressure: .5, clientX: x, clientY: y, button: 0, buttons: 1, bubbles: true, cancelable: true });
        s.dispatchEvent(mk('pointerdown', 21, cx - 30, cy)); s.dispatchEvent(mk('pointermove', 21, cx - 40, cy));
        s.dispatchEvent(mk('pointerdown', 22, cx + 30, cy));
        for (let i = 1; i <= 10; i++) { s.dispatchEvent(mk('pointermove', 21, cx - 30 - i * 10, cy)); s.dispatchEvent(mk('pointermove', 22, cx + 30 + i * 10, cy)); }
        s.dispatchEvent(mk('pointerup', 22, cx + 130, cy)); s.dispatchEvent(mk('pointerup', 21, cx - 130, cy)); }""", [cx, cy])
    st = ed.state()
    assert st["zoom"] > z0 * 2.5, "pinch out zooms in"
    assert not st["hasSelection"], "the half-drawn stroke was dropped"


# ---------------------------------------------------------------------------------------------------- wand
def test_wand_contiguous_matches_a_reference_and_noncontiguous_reaches_the_island(ed):
    ed.tool("wand")
    ed.set_num("허용치", 8)
    rgba = ed.layer()
    ed.click(640, 1000)
    got = ed.mask() > 127
    assert np.array_equal(got, wand_ref(rgba, 640, 1000, "rgb", 8, True))
    s = ed.scene
    assert not got[s["island"]["cy"], s["island"]["cx"]], "the disconnected island is not reached"
    assert not got[s["blob"]["cy"], s["blob"]["cx"]] and not got[s["belt"]["y"] + 30, s["belt"]["x"] + 80], "other colours stay out at tolerance 8"
    assert ed.state()["lastWandMs"] < 60, ed.state()["lastWandMs"]
    ed.page.uncheck('input[aria-label="인접한 영역만"]')
    ed.click(640, 1000)
    got2 = ed.mask() > 127
    assert np.array_equal(got2, wand_ref(rgba, 640, 1000, "rgb", 8, False))
    assert got2[s["island"]["cy"], s["island"]["cx"]] and got2.sum() > got.sum()
    ed.page.check('input[aria-label="인접한 영역만"]')
    ed.set_num("허용치", 30)
    ed.click(640, 1000)
    got3 = ed.mask() > 127
    assert np.array_equal(got3, wand_ref(rgba, 640, 1000, "rgb", 30, True))
    assert got3[s["belt"]["y"] + 30, s["belt"]["x"] + 80], "the slightly lighter belt joins at tolerance 30"
    assert not got3[s["patch"]["y"] + 20, s["patch"]["x"] + 20], "the red patch does not"


@pytest.mark.parametrize("metric,tol", [("alpha", 0), ("alpha", 40), ("luma", 10), ("luma", 25), ("rgb", 3)])
def test_wand_distance_metrics(ed, metric, tol):
    ed.tool("wand")
    ed.page.select_option('select[aria-label="거리"]', metric)
    ed.set_num("허용치", tol)
    rgba = ed.layer()
    seed = (640, 1000) if metric != "alpha" else (300, 700)           # alpha: the transparent background
    ed.click(*seed)
    assert np.array_equal(ed.mask() > 127, wand_ref(rgba, seed[0], seed[1], metric, tol, True))


def test_wand_samples_the_source_and_averages_a_window(ed):
    ed.tool("wand")
    ed.page.click('.le-seg-b[data-v="source"]')
    ed.set_num("허용치", 8)
    src = ed.source()
    ed.click(640, 420)                                                # skin in the source, empty in the layer
    got = ed.mask() > 127
    assert got.sum() > 20000 and np.array_equal(got, wand_ref(src, 640, 420, "rgb", 8, True))
    ed.page.click('.le-seg-b[data-v="layer"]')
    ed.click(640, 420)
    assert (ed.mask() > 127).sum() > 100000, "sampling the (transparent) layer there selects the empty background"
    ed.page.select_option('select[aria-label="샘플 창"]', "11")
    ed.set_num("허용치", 20)
    s = ed.scene
    rgba = ed.layer()
    sx, sy = s["belt"]["x"] + 3, s["belt"]["y"] + 30                  # 3 px inside the belt: the window mixes belt and body
    ed.click(sx, sy)
    assert np.array_equal(ed.mask() > 127, wand_ref(rgba, sx, sy, "rgb", 20, True, win=11))


def test_wand_modifiers_add_subtract_intersect(ed):
    s = ed.scene
    ed.tool("wand")
    ed.set_num("허용치", 8)
    rgba = ed.layer()
    body = wand_ref(rgba, 640, 1000, "rgb", 8, True)
    blob = wand_ref(rgba, s["blob"]["cx"], s["blob"]["cy"], "rgb", 8, True)
    ed.click(640, 1000)
    assert np.array_equal(ed.mask() > 127, body)
    ed.click(s["blob"]["cx"], s["blob"]["cy"], "Shift")                  # add
    assert np.array_equal(ed.mask() > 127, body | blob)
    ed.click(s["blob"]["cx"], s["blob"]["cy"], "Alt")                    # subtract
    assert np.array_equal(ed.mask() > 127, body)
    ed.click(s["blob"]["cx"], s["blob"]["cy"], "Shift")
    ed.click(s["blob"]["cx"], s["blob"]["cy"], "Shift", "Alt")           # intersect
    assert np.array_equal(ed.mask() > 127, blob)
    assert ed.state()["undoDepth"] == 5
    # the same through the mode buttons (touch users have no Shift/Alt)
    ed.click(640, 1000)
    ed.page.click('.le-seg-b[data-v="add"]')
    ed.click(s["blob"]["cx"], s["blob"]["cy"])
    assert np.array_equal(ed.mask() > 127, body | blob)
    ed.page.click('.le-seg-b[data-v="subtract"]')
    ed.click(s["blob"]["cx"], s["blob"]["cy"])
    assert np.array_equal(ed.mask() > 127, body)
    ed.page.click('.le-seg-b[data-v="replace"]')


# ---------------------------------------------------------------------------------------------------- lasso / rectangle / islands
def test_lasso_closes_on_release_and_uses_modifiers(ed):
    ed.set_view(1, -100, -50)
    ed.tool("lasso")
    ed.drag([(800, 500), (1010, 500), (1010, 700), (800, 700)])           # three sides drawn; the fourth is implied
    m = ed.mask() > 127
    assert abs(int(m.sum()) - 210 * 200) < 0.02 * 210 * 200
    assert m[600, 900] and m[510, 810] and not m[600, 790] and not m[490, 900] and not m[600, 1020]
    assert ed.state()["undoDepth"] == 1
    ed.drag([(850, 550), (950, 550), (950, 650), (850, 650)], "Alt")      # subtract a square
    m2 = ed.mask() > 127
    assert not m2[600, 900] and m2[510, 810] and 100 * 100 * 0.96 < int(m.sum() - m2.sum()) < 100 * 100 * 1.04
    ed.drag([(880, 580), (920, 580), (920, 620)], "Shift", "Alt")         # intersect with a triangle -> all gone (inside the hole)
    assert ed.count() == 0
    # a click without drawing in "new" mode deselects
    ed.drag([(800, 500), (1010, 500), (1010, 700)])
    assert ed.count() > 0
    ed.click(400, 300)
    assert ed.count() == 0


def test_rectangle_selection_is_pixel_exact(ed):
    ed.set_view(1, -100, -50)
    ed.tool("rect")
    ed.drag([(200, 300), (450, 520)])
    m = ed.mask() > 127
    ys, xs = np.where(m)
    assert (xs.min(), xs.max(), ys.min(), ys.max()) == (200, 449, 300, 519) and int(m.sum()) == 250 * 220
    ed.drag([(300, 400), (700, 600)], "Shift")                            # add
    assert int((ed.mask() > 127).sum()) == 250 * 220 + 400 * 200 - 150 * 120
    ed.drag([(250, 350), (320, 450)], "Alt")                              # subtract
    ed.drag([(100, 100), (1000, 450)], "Shift", "Alt")                    # intersect: only rows < 450 remain
    ys, _ = np.where(ed.mask() > 127)
    assert ys.max() == 449
    ed.page.keyboard.press("Escape")
    assert ed.count() == 0


def test_connected_island_tool_and_island_list(ed):
    s = ed.scene
    alpha = ed.layer()[:, :, 3] > 16
    lab, n = ndi.label(alpha, structure=np.ones((3, 3)))                  # 8-connected
    ed.tool("island")
    ed.click(s["blob"]["cx"], s["blob"]["cy"])                            # body + blob are one island (they touch)
    got = ed.mask() > 127
    assert np.array_equal(got, lab == lab[s["blob"]["cy"], s["blob"]["cx"]]) and got[s["body"]["cy"], s["body"]["cx"]]
    ed.click(s["island"]["cx"], s["island"]["cy"])
    got = ed.mask() > 127
    assert int(got.sum()) == disc_area(s["island"]["r"]) and not got[s["body"]["cy"], s["body"]["cx"]]
    # list
    ed.act("islands")
    until(lambda: ed.page.locator(".le-isl").count() > 0, "the island list")
    areas = sorted([int((lab == i).sum()) for i in range(1, n + 1)], reverse=True)
    listed = [a for a in areas if a >= 16]
    assert ed.page.locator(".le-isl").count() == len(listed) == 3, "specks under 16 px are dropped"
    first = ed.page.locator(".le-isl .le-isl-a").first.inner_text().replace(",", "").replace(" px", "")
    assert int(first) == areas[0]
    ed.page.locator(".le-isl").nth(1).click()                              # the second biggest: the floating island
    assert int((ed.mask() > 127).sum()) == areas[1]
    ed.page.locator('[data-act="islands-rest"]').click()                   # everything but the biggest, specks included
    assert np.array_equal(ed.mask() > 127, alpha & (lab != lab[s["body"]["cy"], s["body"]["cx"]]))
    ed.page.locator('[data-act="islands"]').click()
    assert ed.page.locator(".le-islands").is_hidden()


# ---------------------------------------------------------------------------------------------------- selection operations
def test_invert_grow_shrink_feather_and_select_all(ed):
    s = ed.scene
    ed.tool("island")
    ed.click(s["island"]["cx"], s["island"]["cy"])
    sel = ed.mask() > 127
    n0 = int(sel.sum())
    ed.page.fill('input[aria-label="확장·축소 크기(px)"]', "4")
    ed.page.locator('input[aria-label="확장·축소 크기(px)"]').blur()
    ed.act("grow")
    grown = ed.mask() > 127
    assert np.array_equal(grown, ndi.distance_transform_edt(~sel) <= 4)
    ed.act("shrink")
    ed.act("shrink")
    shrunk = ed.mask() > 127
    once = ndi.distance_transform_edt(grown) > 4
    assert np.array_equal(shrunk, ndi.distance_transform_edt(once) > 4), "two shrinks of 4 px"
    ed.page.keyboard.press("Control+z")
    ed.page.keyboard.press("Control+z")
    assert np.array_equal(ed.mask() > 127, grown)
    # feather: soft edge, same body
    ed.page.fill('input[aria-label="선택 페더 크기(px)"]', "8")
    ed.page.locator('input[aria-label="선택 페더 크기(px)"]').blur()
    ed.act("feather-sel")
    m = ed.mask()
    soft = int(((m > 0) & (m < 255)).sum())
    assert soft > 300 and m[s["island"]["cy"], s["island"]["cx"]] == 255
    assert abs(int((m > 127).sum()) - int(grown.sum())) < 0.03 * grown.sum()
    # invert
    ed.page.keyboard.press("Control+d")
    assert ed.count() == 0 and not ed.enabled("erase") and not ed.enabled("grow")
    ed.page.keyboard.press("Control+a")
    assert ed.count() == N * N
    ed.tool("rect")
    ed.set_view(1, -100, -50)
    ed.drag([(100, 100), (300, 250)], "Alt")
    inv_src = ed.mask() > 127
    ed.page.keyboard.press("Control+i")
    inv = ed.mask() > 127
    assert np.array_equal(inv, ~inv_src) and int(inv.sum()) == 200 * 150


def test_intersect_with_layer_content_and_source_foreground(ed):
    layer_fg = ed.layer()[:, :, 3] > 16
    src_fg = ed.source()[:, :, 3] > 16
    ed.page.keyboard.press("Control+a")
    ed.act("only-layer")
    assert np.array_equal(ed.mask() > 127, layer_fg)
    ed.page.keyboard.press("Control+a")
    ed.act("only-source")
    assert np.array_equal(ed.mask() > 127, src_fg)
    ed.page.keyboard.press("Control+d")
    ed.act("only-layer")                                                   # with no selection it selects the layer content
    assert np.array_equal(ed.mask() > 127, layer_fg)
    ed.tool("rect")
    ed.set_view(1, 0, 0)
    ed.drag([(10, 10), (700, 700)])
    ed.act("only-source")
    box = np.zeros((N, N), bool)
    box[10:700, 10:700] = True
    assert np.array_equal(ed.mask() > 127, src_fg & box)


def test_undo_redo_depth_and_history_reset(ed):
    s = ed.scene
    ed.tool("wand")
    ed.set_num("허용치", 8)
    snaps = [ed.mask() > 127]
    ed.click(640, 1000)
    snaps.append(ed.mask() > 127)
    ed.click(s["blob"]["cx"], s["blob"]["cy"], "Shift")
    snaps.append(ed.mask() > 127)
    ed.act("invert")
    snaps.append(ed.mask() > 127)
    st = ed.state()
    assert (st["undoDepth"], st["redoDepth"]) == (3, 0)
    assert ed.page.locator('[data-act="undo"]').is_enabled() and ed.page.locator('[data-act="redo"]').is_disabled()
    for want in (2, 1, 0):
        ed.page.keyboard.press("Control+z")
        assert np.array_equal(ed.mask() > 127, snaps[want]), f"state {want}"
        assert ed.state()["undoDepth"] == want
    assert ed.state()["redoDepth"] == 3 and not ed.state()["hasSelection"] and ed.page.locator('[data-act="undo"]').is_disabled()
    ed.page.keyboard.press("Control+z")                                    # nothing left: harmless
    assert ed.state()["undoDepth"] == 0
    ed.page.keyboard.press("Control+Shift+z")
    assert np.array_equal(ed.mask() > 127, snaps[1]) and ed.state()["undoDepth"] == 1
    ed.page.keyboard.press("Control+y")
    assert np.array_equal(ed.mask() > 127, snaps[2])
    ed.page.click('[data-act="undo"]')
    ed.page.click('[data-act="redo"]')
    assert np.array_equal(ed.mask() > 127, snaps[2]) and ed.state()["undoDepth"] == 2
    ed.page.keyboard.press("Control+z")
    ed.click(300, 700)                                                     # a new action drops the redo branch
    assert ed.state()["redoDepth"] == 0 and ed.state()["undoDepth"] == 2
    ed.act("deselect")
    assert ed.state()["undoDepth"] == 3
    ed.page.keyboard.press("Control+d")                                    # an unchanged selection adds no step
    assert ed.state()["undoDepth"] == 3


def test_history_is_capped_but_still_walks_back(ed):
    for i in range(80):
        ed.page.keyboard.press("Control+a" if i % 2 == 0 else "Control+d")
    st = ed.state()
    assert 20 <= st["undoDepth"] <= 60
    for _ in range(st["undoDepth"]):
        ed.page.keyboard.press("Control+z")
    assert ed.state()["undoDepth"] == 0 and ed.state()["redoDepth"] == st["undoDepth"]


def test_marching_ants_follow_the_selection(ed):
    s = ed.scene
    assert ed.page.locator(".le-ants").is_hidden()
    ed.tool("island")
    ed.click(s["island"]["cx"], s["island"]["cy"])
    until(lambda: ed.page.locator(".le-ants").is_visible() and ed.ev("getComputedStyle(document.querySelector('.le-ants')).maskImage").startswith("url("), "the ants")
    assert ed.ev("getComputedStyle(document.querySelector('.le-ants')).animationName") == "le-march"
    assert ed.ev("getComputedStyle(document.querySelector('.le-ants')).maskSize") in ("100% 100%", "100%")
    before = ed.ev("getComputedStyle(document.querySelector('.le-ants')).maskImage")
    ed.act("grow")
    until(lambda: ed.ev("getComputedStyle(document.querySelector('.le-ants')).maskImage") != before, "the outline to follow the grown selection")
    ed.page.keyboard.press("Control+d")
    until(lambda: ed.page.locator(".le-ants").is_hidden(), "the ants to go away")


def test_deep_zoom_draws_a_thin_vector_outline_instead_of_the_ants(ed):
    s = ed.scene
    ed.tool("island")
    ed.click(s["island"]["cx"], s["island"]["cy"])
    until(lambda: ed.page.locator(".le-ants").is_visible(), "the ants at normal zoom")

    def ui_ink():
        return ed.ev("""() => { const c = document.querySelector('.le-ui'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let n = 0;
            for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; }""")

    assert ui_ink() == 0
    # centre the left edge of the island at 800 %
    ed.set_view(8, -8 * (s["island"]["cx"] - s["island"]["r"] - 20), -8 * (s["island"]["cy"] - 40))
    assert ed.page.locator(".le-ants").is_hidden(), "from 600 % on the masked ants (one grid pixel thick) give way to thin lines"
    ink = ui_ink()
    assert 500 < ink < 60000, ink
    ed.set_view(2, -300, -100)
    assert ed.page.locator(".le-ants").is_visible() and ui_ink() == 0
    ed.set_view(8, -8 * (s["island"]["cx"] - s["island"]["r"] - 20), -8 * (s["island"]["cy"] - 40))
    ed.page.keyboard.press("Control+d")
    assert ui_ink() == 0, "the outline goes with the selection"


def test_selection_tint_uses_the_css_variable(ed):
    s = ed.scene
    ed.tool("island")
    ed.click(s["island"]["cx"], s["island"]["cy"])
    ed.set_view(1, -100, -50)
    plain = ed.view_px(s["island"]["cx"], s["island"]["cy"])
    ed.ev("document.querySelector('.le-root').style.setProperty('--le-sel', '#00ff40')")
    ed.ev("document.documentElement.setAttribute('data-theme', 'light')")      # the theme observer re-reads the css variables
    green = ed.view_px(s["island"]["cx"], s["island"]["cy"])
    assert plain[0] > plain[1] and green[1] > green[0], (plain, green)


# ---------------------------------------------------------------------------------------------------- applying operations
def select_blob(ed, tol=8):
    s = ed.scene
    ed.tool("wand")
    ed.set_num("허용치", tol)
    ed.click(s["blob"]["cx"], s["blob"]["cy"])
    return ed.mask() > 127


def test_buttons_are_disabled_without_a_selection(ed):
    for a in ("erase", "restore", "move", "grow", "shrink", "feather-sel", "deselect"):
        assert not ed.enabled(a), a
    for a in ("select-all", "invert", "fill-hole", "clean", "only-layer", "only-source", "islands", "fit", "zoom100"):
        assert ed.enabled(a), a
    select_blob(ed)
    for a in ("erase", "restore", "grow", "shrink", "feather-sel", "deselect"):
        assert ed.enabled(a), a
    assert not ed.enabled("move"), "no target chosen yet"
    ed.page.select_option('[data-act="move-target"]', "arm_r")
    assert ed.enabled("move")


def test_erase_sends_the_mask_and_reloads_the_layer(ed):
    s = ed.scene
    blob = select_blob(ed)
    assert ed.layer()[s["blob"]["cy"], s["blob"]["cx"], 3] == 255
    ed.page.fill('input.le-num[aria-label="가장자리 부드럽게 값"]', "3")
    ed.apply("erase")
    (call,) = ed.calls()
    p = call["payload"]
    assert call["tag"] == "body" and p["op"] == "erase" and p["rebuild"] is True and p["feather"] == 3 and "to" not in p and p["note"]
    pm = ed.payload_mask(call)
    assert pm.shape == (N, N) and set(np.unique(pm)) <= {0, 255} and np.array_equal(pm > 127, blob)
    st = ed.state()
    assert st["rev"] == 1 and st["ops"] == 1 and not st["hasSelection"] and st["undoDepth"] == 0 and not st["busy"]
    assert ed.ev("window.__applied.length") == 1 and ed.ev("window.__applied[0].rev") == 1
    assert ed.layer()[s["blob"]["cy"], s["blob"]["cx"], 3] == 0, "the fake server erased the blob"
    # both images are requested again with the new rev, and the editor shows the new layer
    reqs = ed.ev("window.__imageRequests")
    assert {"kind": "layer", "tag": "body", "v": "current", "rev": 1} in reqs and {"kind": "source", "grid": "canvas", "rev": 1} in reqs
    assert ed.ev("window.__ed.getLayerCanvas().getContext('2d').getImageData(900, 600, 1, 1).data[3]") == 0
    assert ed.ev("window.__ed.getLayerCanvas().getContext('2d').getImageData(640, 1000, 1, 1).data[3]") == 255
    assert ed.page.locator(".le-toast-ok").count() == 1


def test_delete_key_erases_and_enter_does_nothing(ed):
    select_blob(ed)
    ed.page.keyboard.press("Enter")
    ed.page.locator(".le-stage").focus()
    ed.page.keyboard.press("Enter")
    time.sleep(0.2)
    assert ed.calls() == [], "Enter is not bound to anything destructive"
    n = ed.state()["ops"]
    ed.page.keyboard.press("Delete")
    ed.wait_idle(n + 1)
    assert [c["payload"]["op"] for c in ed.calls()] == ["erase"]


def test_restore_fills_from_the_source(ed):
    s = ed.scene
    ed.tool("wand")
    ed.page.select_option('select[aria-label="거리"]', "alpha")
    ed.set_num("허용치", 0)
    ed.click(s["hole"]["cx"], s["hole"]["cy"])                              # the enclosed transparent hole
    assert int(ed.count()) == disc_area(s["hole"]["r"])
    assert ed.layer()[s["hole"]["cy"], s["hole"]["cx"], 3] == 0
    ed.page.keyboard.press("r")
    ed.wait_idle(1)
    (call,) = ed.calls()
    assert call["payload"]["op"] == "restore" and call["payload"]["mask"]
    px = ed.layer()[s["hole"]["cy"], s["hole"]["cx"]]
    assert list(px) == s["body"]["color"] + [255], "the server filled the selection with the source pixels"


def test_move_to_another_layer(ed):
    s = ed.scene
    blob = select_blob(ed)
    options = ed.page.locator('[data-act="move-target"] option').all_inner_texts()
    assert "몸" not in " ".join(options) and "오른팔 (비어 있음)" in options and "앞머리" in options and "얼굴" in options
    ed.page.select_option('[data-act="move-target"]', "arm_r")
    ed.apply("move")
    (call,) = ed.calls()
    p = call["payload"]
    assert p["op"] == "move" and p["to"] == "arm_r" and p["rebuild"] is True
    assert np.array_equal(ed.payload_mask(call) > 127, blob)
    assert ed.layer("arm_r")[s["blob"]["cy"], s["blob"]["cx"], 3] == 255 and ed.layer("body")[s["blob"]["cy"], s["blob"]["cx"], 3] == 0
    assert ed.state()["moveTo"] == "arm_r"


def test_clean_needs_no_mask_and_fill_hole_takes_an_optional_one(ed):
    s = ed.scene
    ed.apply("clean")
    p = ed.calls()[0]["payload"]
    assert p["op"] == "clean" and "mask" not in p and p["rebuild"] is True
    a = ed.layer()[:, :, 3]
    assert a[s["specks"][1]["y"], s["specks"][1]["x"]] == 0 and a[s["specks"][0]["y"], s["specks"][0]["x"]] == 0, "specks cleaned"
    assert a[s["hole"]["cy"], s["hole"]["cx"]] == 0
    ed.apply("fill-hole")
    p = ed.calls()[1]["payload"]
    assert p["op"] == "fill_hole" and "mask" not in p
    assert ed.layer()[s["hole"]["cy"], s["hole"]["cx"], 3] == 255, "the enclosed hole is filled"
    # with a selection the mask limits the area
    ed.tool("rect")
    ed.set_view(1, -100, -50)
    ed.drag([(100, 100), (400, 400)])
    ed.apply("fill-hole")
    c = ed.calls()[2]
    assert c["payload"]["op"] == "fill_hole" and c["payload"]["mask"]
    assert int((ed.payload_mask(c) > 127).sum()) == 300 * 300


def test_spinner_blocks_the_tools_while_a_request_is_pending(ed):
    select_blob(ed)
    n_sel = ed.count()
    ed.ev("window.__fake.hold = true")
    ed.act("erase")
    until(lambda: ed.page.locator(".le-busy").is_visible(), "the spinner")
    assert ed.state()["busy"] and "지우는 중" in ed.page.locator(".le-busy").inner_text()
    assert ed.page.locator(".le-root").get_attribute("data-busy") == "1"
    assert len(ed.calls()) == 1
    # clicks, keys and strokes are ignored
    x, y = ed.pt(300, 700)                                                 # a transparent spot well inside the stage
    tool_before = ed.state()["tool"]
    bx = ed.page.locator('[data-tool="lasso"]').bounding_box()
    ed.page.mouse.click(bx["x"] + 5, bx["y"] + 5)
    ed.page.keyboard.press("e")
    ed.page.keyboard.press("Control+a")
    ed.page.keyboard.press("Delete")
    ed.page.mouse.move(x, y)
    ed.page.mouse.down()
    ed.page.mouse.move(x + 80, y + 20, steps=4)
    ed.page.mouse.up()
    ed.page.mouse.wheel(0, -200)
    st = ed.state()
    assert st["tool"] == tool_before and ed.count() == n_sel and st["undoDepth"] == 1 and len(ed.calls()) == 1
    assert ed.page.locator('[data-act="erase"]').is_disabled() and ed.page.locator('[data-act="clean"]').is_disabled()
    assert ed.page.locator('[data-act="undo"]').is_disabled() and ed.page.locator('[data-act="close"]').is_disabled()
    ed.ev("window.__fake.hold = false; window.__fake.release()")
    until(lambda: not ed.state()["busy"], "the spinner to go away")
    until(lambda: ed.state()["ready"], "reload")
    assert ed.page.locator(".le-busy").is_hidden() and not ed.state()["hasSelection"]
    ed.page.keyboard.press("e")
    assert ed.state()["tool"] == "eraser"


def test_a_rejected_request_shows_a_dismissible_message_and_keeps_the_selection(ed):
    select_blob(ed)
    n = ed.count()
    ed.ev("window.__fake.failNext = '서버가 거절했습니다 (409)'")
    ed.act("erase")
    until(lambda: ed.page.locator(".le-toast-bad").count() == 1, "the error toast")
    t = ed.page.locator(".le-toast-bad")
    assert "서버가 거절했습니다 (409)" in t.inner_text() and t.get_attribute("role") == "alert"
    st = ed.state()
    assert not st["busy"] and st["hasSelection"] and ed.count() == n and st["rev"] == 0 and st["ops"] == 0
    assert ed.ev("window.__applied.length") == 0
    assert ed.page.locator(".le-busy").is_hidden() and ed.enabled("erase"), "the tools are usable again"
    time.sleep(3.2)
    assert ed.page.locator(".le-toast-bad").count() == 1, "an error stays until dismissed"
    ed.page.locator(".le-toast-bad .le-toast-x").click()
    assert ed.page.locator(".le-toast-bad").count() == 0
    ed.apply("erase")                                                      # and a retry works
    assert ed.state()["rev"] == 1


def test_failed_layer_load_offers_a_retry(make_ed):
    e = make_ed(allow_errors=True)
    e.ev("window.__fake.badLayer = true")
    e.ev("window.__ed.reload({})")
    until(lambda: e.page.locator(".le-toast-bad").count() == 1, "the load error")
    assert "불러오지 못했습니다" in e.page.locator(".le-toast-bad").inner_text() and not e.state()["ready"]
    assert e.page.locator('[data-act="erase"]').is_disabled() and e.page.locator('[data-act="clean"]').is_disabled()
    e.ev("window.__fake.badLayer = false")
    e.page.locator(".le-toast-a").click()
    until(lambda: e.state()["ready"], "the retry to load")
    assert e.page.locator(".le-toast-bad").count() == 0


# ---------------------------------------------------------------------------------------------------- setTag / close
def test_set_tag_switches_layers_and_asks_before_dropping_a_selection(ed):
    s = ed.scene
    first = ed.state()["layerBBox"]
    # not dirty: switches at once
    assert ed.ev("window.__ed.setTag('hair', {label: '앞머리', grid: 'canvas'})") is True
    until(lambda: ed.state()["ready"] and ed.state()["tag"] == "hair", "hair to load")
    st = ed.state()
    assert st["label"] == "앞머리" and st["layerBBox"] != first and st["layerBBox"]["y1"] < 400
    assert "앞머리" in ed.page.locator(".le-st-layer").inner_text()
    assert ed.ev("window.__ed.getLayerCanvas().getContext('2d').getImageData(640, 250, 1, 1).data[3]") == 255
    options = ed.page.locator('[data-act="move-target"] option').all_inner_texts()
    assert "앞머리" not in " ".join(options) and "몸" in options
    # dirty: asks; cancel keeps everything, confirm switches and clears the selection
    ed.tool("rect")
    ed.set_view(1, -100, -50)
    ed.drag([(100, 100), (300, 300)])
    ed.ev("() => { window.__p = window.__ed.setTag('face', {label: '얼굴', grid: 'head'}); }")
    until(lambda: ed.page.locator(".le-modal").is_visible(), "the confirm dialog")
    assert ed.state()["tag"] == "hair"
    ed.page.click('[data-act="confirm-cancel"]')
    assert ed.ev("window.__p") is False and ed.state()["tag"] == "hair" and ed.state()["hasSelection"]
    ed.ev("() => { window.__p = window.__ed.setTag('face', {label: '얼굴', grid: 'head'}); }")
    ed.page.click('[data-act="confirm-ok"]')
    assert ed.ev("window.__p") is True
    until(lambda: ed.state()["ready"] and ed.state()["tag"] == "face", "face to load")
    st = ed.state()
    assert st["grid"] == "head" and not st["hasSelection"] and st["undoDepth"] == 0
    assert {"kind": "source", "grid": "head", "rev": 0} in ed.ev("window.__imageRequests")
    assert ed.ev("window.__ed.getSourceCanvas().getContext('2d').getImageData(640, 840, 1, 1).data[1]") == 80, "the head source (with a mouth) is shown"
    assert "머리 격자" in ed.page.locator(".le-st-layer").inner_text()
    # edits go to the new tag
    ed.tool("rect")
    ed.set_view(1, -100, -50)
    ed.drag([(100, 100), (300, 300)])
    ed.apply("erase")
    assert ed.calls()[-1]["tag"] == "face"


def test_close_asks_when_there_is_a_selection_and_escape_closes_when_empty(ed):
    ed.page.click('[data-act="close"]')
    assert ed.ev("window.__closed") == 1
    select_blob(ed)
    ed.page.click('[data-act="close"]')
    until(lambda: ed.page.locator(".le-modal").is_visible(), "the confirm dialog")
    ed.page.keyboard.press("Escape")                                       # Esc cancels the dialog only
    assert ed.page.locator(".le-modal").is_hidden() and ed.ev("window.__closed") == 1 and ed.state()["hasSelection"]
    ed.page.click('[data-act="close"]')
    ed.page.click('[data-act="confirm-ok"]')
    assert ed.ev("window.__closed") == 2
    ed.page.keyboard.press("Escape")                                       # clears the selection first ...
    assert not ed.state()["hasSelection"] and ed.ev("window.__closed") == 2
    ed.page.keyboard.press("Escape")                                       # ... and closes when there is none
    assert ed.ev("window.__closed") == 3


# ---------------------------------------------------------------------------------------------------- overlays
def test_overlay_modes_render_different_pixels(ed):
    s = ed.scene
    ed.set_view(1, -100, -350)
    head = (640, 420)                                                       # skin in the source; empty in the layer
    speck = (s["specks"][1]["x"] + 2, s["specks"][1]["y"] + 2)             # body colour in the layer; nothing in the source
    patch = (s["patch"]["x"] + 20, s["patch"]["y"] + 20)                    # red in the layer; blue in the source
    shots = {}
    for key, name in (("1", "layer"), ("2", "source"), ("3", "blend"), ("4", "diff")):
        ed.page.keyboard.press(key)
        assert ed.state()["overlay"] == name
        assert ed.page.locator(f'button[data-overlay="{name}"]').get_attribute("aria-pressed") == "true"
        shots[name] = {"head": ed.view_px(*head), "speck": ed.view_px(*speck), "patch": ed.view_px(*patch),
                       "all": ed.ev("window.__ed.getViewCanvas().toDataURL()")}
    assert len({v["all"] for v in shots.values()}) == 4, "every mode draws something different"
    checker = [(255, 255, 255), (216, 220, 228)]
    skin = np.array([240, 200, 170])
    assert tuple(shots["layer"]["head"][:3]) in checker, "layer only: nothing there -> checkerboard"
    assert np.abs(np.array(shots["source"]["head"][:3]) - skin).max() <= 2
    ghost = [0.35 * skin + 0.65 * np.array(c) for c in checker]
    assert min(np.abs(np.array(shots["blend"]["head"][:3]) - g).max() for g in ghost) <= 3, "blend: dim source ghost under the layer"
    r, g, b, _ = shots["diff"]["head"]
    assert b > 200 and b > r + 40, "diff: source solid, layer empty -> blue"
    r, g, b, _ = shots["diff"]["speck"]
    assert r > 200 and g < 120, "diff: layer pixels with no source -> red"
    r, g, b, _ = shots["diff"]["patch"]
    assert r > 220 and 120 < g < 200 and b < 110, "diff: colour differs -> amber"
    assert shots["layer"]["patch"][:3] == [200, 60, 60] and shots["blend"]["patch"][:3] == [200, 60, 60]
    # the ghost slider and the sensitivity slider act on the picture
    ed.page.keyboard.press("3")
    ed.page.fill('input.le-num[aria-label="원본 진하기 값"]', "100")
    assert np.abs(np.array(ed.view_px(*head)[:3]) - skin).max() <= 2
    ed.page.fill('input.le-num[aria-label="원본 진하기 값"]', "0")
    assert tuple(ed.view_px(*head)[:3]) in checker
    ed.page.locator(".le-stage").focus()                                    # keys typed into a field are not shortcuts
    ed.page.keyboard.press("4")
    ed.page.fill('input.le-num[aria-label="차이 민감도 값"]', "128")
    assert ed.view_px(*patch)[0] > 220, "the red patch (diff 140) still shows at sensitivity 128"
    assert ed.page.locator(".le-legend").is_visible()
    ed.page.locator(".le-stage").focus()
    ed.page.keyboard.press("1")
    assert ed.page.locator(".le-legend").is_hidden()


# ---------------------------------------------------------------------------------------------------- keyboard
def test_keyboard_shortcuts(ed):
    for key, tool in (("b", "brush"), ("e", "eraser"), ("w", "wand"), ("l", "lasso"), ("m", "rect"), ("c", "island"), ("h", "hand"), ("z", "zoom")):
        ed.page.keyboard.press(key)
        assert ed.state()["tool"] == tool, key
        assert ed.page.locator(f'[data-tool="{tool}"]').get_attribute("aria-pressed") == "true"
    ed.page.keyboard.press("b")
    ed.page.keyboard.press("Shift+B")
    ed.page.keyboard.press("]")
    ed.page.keyboard.press("]")
    assert ed.state()["brush"]["size"] > 40
    for key, ov in (("2", "source"), ("3", "blend"), ("4", "diff"), ("1", "layer")):
        ed.page.keyboard.press(key)
        assert ed.state()["overlay"] == ov
    ed.page.keyboard.press("Control+a")
    assert ed.count() == N * N
    ed.page.keyboard.press("Control+i")
    assert ed.count() == 0
    ed.page.keyboard.press("Control+Shift+a")                              # not bound
    ed.page.keyboard.press("Control+a")
    ed.page.keyboard.press("Control+d")
    assert ed.count() == 0 and ed.state()["undoDepth"] == 4
    ed.page.keyboard.press("=")
    z = ed.state()["zoom"]
    ed.page.keyboard.press("-")
    assert ed.state()["zoom"] < z
    ed.set_view(2, -300, -300)
    ed.page.keyboard.press("f")
    assert ed.state()["zoom"] < 1.5
    # typing in a field never triggers a tool shortcut
    ed.page.focus('input.le-num[aria-label="크기 값"]')
    ed.page.keyboard.press("w")
    ed.page.keyboard.press("Delete")
    assert ed.state()["tool"] == "brush" and ed.calls() == []
    # cheat sheet
    ed.page.locator(".le-stage").focus()
    ed.page.keyboard.press("?")
    assert ed.page.locator(".le-pop").is_visible() and "Ctrl+Shift+Z" in ed.page.locator(".le-pop").inner_text()
    ed.page.keyboard.press("Escape")
    assert ed.page.locator(".le-pop").is_hidden()
    ed.page.click('[data-act="help"]')
    assert ed.page.locator(".le-pop").is_visible()
    ed.page.mouse.click(*ed.pt(640, 640))                                  # clicking elsewhere closes it
    assert ed.page.locator(".le-pop").is_hidden()


def test_keys_outside_the_editor_are_left_alone(ed):
    ed.ev("document.body.insertAdjacentHTML('beforeend', '<input id=\"other\" type=\"text\" style=\"position:fixed;left:0;top:0;z-index:99\">')")
    ed.page.click("#other")
    ed.page.keyboard.press("w")
    ed.page.keyboard.press("Control+a")
    assert ed.state()["tool"] == "brush" and ed.count() == 0
    ed.ev("document.body.insertAdjacentHTML('beforeend', '<button id=\"otherb\" style=\"position:fixed;left:0;top:40px;z-index:99\">x</button>')")
    ed.page.click("#otherb")
    ed.page.keyboard.press("w")
    ed.page.keyboard.press("Control+a")
    assert ed.state()["tool"] == "brush" and ed.count() == 0, "a click outside disarms the editor's shortcuts"
    ed.page.mouse.click(*ed.pt(640, 640))                                  # clicking the canvas arms them again
    ed.page.keyboard.press("w")
    assert ed.state()["tool"] == "wand"


# ---------------------------------------------------------------------------------------------------- layout / looks
@pytest.mark.parametrize("size", [(700, 520), (960, 640), (2400, 1300)])
def test_layout_works_from_700_to_2400_px(make_ed, size):
    w, h = size
    e = make_ed(f"?w={w}&h={h}", viewport=(max(w, 800) + 20, max(h, 600) + 20))
    box = e.ev("""() => { const r = (s) => { const b = document.querySelector(s).getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
        const root = document.querySelector('.le-root'); const sw = (s) => document.querySelector(s).scrollWidth > document.querySelector(s).clientWidth + 1;
        return { root: r('.le-root'), tool: r('.le-toolbox'), opt: r('.le-optbar'), stage: r('.le-stage'), panel: r('.le-panel'), status: r('.le-status'),
                 overflow: [sw('.le-root'), sw('.le-optbar'), sw('.le-panel'), sw('.le-status')] }; }""")
    root = box["root"]
    assert abs(root[2] - root[0] - w) <= 3 and abs(root[3] - root[1] - h) <= 3
    st = box["stage"]
    assert st[2] - st[0] >= (330 if w <= 720 else 500) and st[3] - st[1] >= 250
    assert box["tool"][2] <= st[0] + 1 and st[2] <= box["panel"][0] + 1 and box["opt"][3] <= st[1] + 1 and st[3] <= box["status"][1] + 1
    assert box["panel"][2] <= root[2] + 1 and box["status"][3] <= root[3] + 1
    assert box["overflow"] == [False, False, False, False]
    # the editor still works at this size
    e.tool("island")
    s = e.scene
    e.click(s["island"]["cx"], s["island"]["cy"])
    assert e.count() == disc_area(s["island"]["r"])
    assert e.ev("window.__ed.getState().zoom") > 0.1


@pytest.mark.parametrize("scheme", ["light", "dark"])
@pytest.mark.parametrize("size", [(1920, 1080), (1280, 800)])
def test_screenshots_light_and_dark(make_ed, scheme, size):
    SHOTS.mkdir(parents=True, exist_ok=True)
    e = make_ed(f"?theme={scheme}", viewport=size, scheme=scheme)
    s = e.scene
    e.tool("wand")
    e.set_num("허용치", 8)
    e.click(640, 1000)
    e.click(s["blob"]["cx"], s["blob"]["cy"], "Shift")
    until(lambda: e.ev("getComputedStyle(document.querySelector('.le-ants')).maskImage").startswith("url("), "ants")
    time.sleep(0.25)
    path = SHOTS / f"editor_{scheme}_{size[0]}x{size[1]}.png"
    e.page.screenshot(path=str(path))
    assert path.stat().st_size > 20000
    if size[0] == 1920:
        e.page.keyboard.press("4")
        e.page.screenshot(path=str(SHOTS / f"editor_{scheme}_{size[0]}x{size[1]}_diff.png"))
        e.page.keyboard.press("3")
        e.page.keyboard.press("?")
        e.page.screenshot(path=str(SHOTS / f"editor_{scheme}_{size[0]}x{size[1]}_help.png"))
    bg = e.ev("getComputedStyle(document.querySelector('.le-panel')).backgroundColor")
    assert (bg == "rgb(255, 255, 255)") == (scheme == "light"), bg


def test_flood_fill_is_fast(ed):
    r = ed.ev("""async () => { const ops = await import('/static/js/layer-editor-ops.js'); const c = window.__ed.getLayerCanvas();
        const px = c.getContext('2d').getImageData(0, 0, 1280, 1280).data; const out = {};
        let t = performance.now(); ops.floodSelect(px, 1280, 1280, 640, 1000, { metric: 'rgb', tolerance: 8, contiguous: true, window: 1 }); out.contiguous = performance.now() - t;
        t = performance.now(); ops.floodSelect(px, 1280, 1280, 60, 60, { metric: 'alpha', tolerance: 0, contiguous: true, window: 1 }); out.background = performance.now() - t;
        t = performance.now(); ops.floodSelect(px, 1280, 1280, 640, 1000, { metric: 'rgb', tolerance: 8, contiguous: false, window: 11 }); out.global = performance.now() - t;
        const a = ops.alphaPlane(px); t = performance.now(); ops.labelComponents(a, 1280, 1280, 16); out.label = performance.now() - t;
        return out; }""")
    print("flood fill ms:", r)
    assert r["contiguous"] < 60 and r["background"] < 60 and r["global"] < 60, r
    assert r["label"] < 150, r
