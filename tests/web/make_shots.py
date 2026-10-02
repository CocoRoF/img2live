# SPDX-License-Identifier: Apache-2.0
"""Write review screenshots of the viewer to bench/outputs/viewer_shots/.

    python tests/web/make_shots.py            # needs playwright + /usr/bin/google-chrome + the sample puppet

`take_all(browser, base_url, outdir)` is also called by tests/web/test_viewer.py::test_screenshots.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SHOTS = ROOT / "bench" / "outputs" / "viewer_shots"

QUIET = "idle=0&blink=0&physics=0"  # deterministic rest pose: no idle motion, no blink, no physics


def settle(page, frames: int = 3):
    page.evaluate(
        "(n) => new Promise((res) => { const f = (k) => k <= 0 ? res() : requestAnimationFrame(() => f(k - 1)); f(n); })",
        frames,
    )


def set_params(page, params: dict, reset: bool = True):
    page.evaluate(
        "([p, reset]) => { const v = window.__img2live.viewer; if (reset) v.resetParams();"
        " for (const [k, x] of Object.entries(p)) v.setParam(k, x); }",
        [params, reset],
    )
    settle(page)


def open_viewer(browser, base_url, query=QUIET, viewport=(1280, 800), scale=1, **ctx):
    context = browser.new_context(viewport={"width": viewport[0], "height": viewport[1]}, device_scale_factor=scale, **ctx)
    page = context.new_page()
    page.goto(f"{base_url}/viewer-test.html?{query}")
    page.wait_for_function("document.documentElement.dataset.ready", timeout=30000)
    settle(page)
    return context, page


def canvas_shot(page, path: Path):
    page.add_style_tag(content=".i2l-hint { display: none !important; }")  # keep the overlay text out of review images
    page.locator(".i2l-canvas-wrap").screenshot(path=str(path))


def take_all(browser, base_url: str, outdir: Path = SHOTS) -> list[Path]:
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    def out(name: str) -> Path:
        p = outdir / name
        written.append(p)
        return p

    ctx, page = open_viewer(browser, base_url, QUIET + "&bg=white", viewport=(1280, 900), scale=1)
    assert page.evaluate("window.__img2live.viewer.getOption('idle')") is False

    # ---- whole character, with the UI
    page.evaluate("window.__img2live.viewer.setBackground('checker')")
    settle(page)
    page.screenshot(path=str(out("01_rest_fit_ui.png")))
    page.evaluate("window.__img2live.viewer.setBackground('white')")
    canvas_shot(page, out("01b_rest_fit.png"))

    # ---- head close-up poses
    page.evaluate("window.__img2live.viewer.setCamera('head')")
    settle(page)
    canvas_shot(page, out("02_head_rest.png"))
    poses = {
        "03_head_yaw_p30.png": {"ParamAngleX": 30},
        "04_head_yaw_m30.png": {"ParamAngleX": -30},
        "05_head_pitch_p30.png": {"ParamAngleY": 30},
        "05b_head_pitch_m30.png": {"ParamAngleY": -30},
        "06_head_roll_p25.png": {"ParamAngleZ": 25},
        "07_eyes_closed_head.png": {"ParamEyeLOpen": 0, "ParamEyeROpen": 0},
        "07b_eyes_half_head.png": {"ParamEyeLOpen": 0.5, "ParamEyeROpen": 0.5},
        "07c_wink_l_head.png": {"ParamEyeLOpen": 0},
        "08_gaze_right_head.png": {"ParamEyeBallX": 1},
        "08b_gaze_left_head.png": {"ParamEyeBallX": -1},
        "08c_gaze_up_head.png": {"ParamEyeBallY": 1},
        "09_mouth_open_head.png": {"ParamMouthOpenY": 1},
        "09b_mouth_half_head.png": {"ParamMouthOpenY": 0.4},
        "09c_brows_up_head.png": {"ParamBrowLY": 1, "ParamBrowRY": 1},
        "09d_yaw_gaze_head.png": {"ParamAngleX": -20, "ParamEyeBallX": 1},
    }
    for name, params in poses.items():
        set_params(page, params)
        canvas_shot(page, out(name))

    # ---- hair sway (physics off: driven params follow the sliders), seen whole and close
    set_params(page, {"ParamHairBack": 1, "ParamHairFront": -0.8})
    canvas_shot(page, out("10_hair_sway_head.png"))
    page.evaluate("window.__img2live.viewer.setCamera('fit')")
    settle(page)
    canvas_shot(page, out("10b_hair_sway_fit.png"))
    set_params(page, {"ParamBodyAngleX": 10, "ParamBodyAngleZ": 8, "ParamBreath": 1})
    canvas_shot(page, out("10c_body_sway_fit.png"))

    # ---- wireframe
    set_params(page, {})
    page.evaluate("window.__img2live.viewer.setCamera('head'); window.__img2live.viewer.setOption('wireframe', true)")
    settle(page)
    canvas_shot(page, out("11_wireframe_head.png"))
    page.evaluate("window.__img2live.viewer.setCamera('fit')")
    settle(page)
    canvas_shot(page, out("11b_wireframe_fit.png"))
    page.evaluate("window.__img2live.viewer.setOption('wireframe', false)")

    # ---- a layer hidden / solo (iris clip must hold)
    page.evaluate("window.__img2live.viewer.setCamera('head'); window.__img2live.viewer.setLayerVisible('front_hair', false)")
    set_params(page, {"ParamEyeBallX": 1, "ParamEyeLOpen": 0.35, "ParamEyeROpen": 0.35})
    canvas_shot(page, out("12_no_fronthair_gaze_halfclosed.png"))
    page.evaluate("window.__img2live.viewer.setLayerVisible('front_hair', true)")

    # ---- full UI with the panel scrolled to the layers + capability report
    set_params(page, {})
    page.evaluate("window.__img2live.viewer.setCamera('fit')")
    page.evaluate("document.querySelector('.i2l-panel').scrollTop = 1e6")
    settle(page)
    page.screenshot(path=str(out("13_panel_layers_capability.png")))
    ctx.close()

    # ---- dark scheme
    ctx, page = open_viewer(browser, base_url, QUIET + "&camera=head&bg=dark", viewport=(1280, 800), color_scheme="dark")
    page.screenshot(path=str(out("14_dark_theme.png")))
    ctx.close()

    # ---- phone layout (and a narrow one)
    ctx, page = open_viewer(browser, base_url, QUIET, viewport=(390, 844), scale=2, is_mobile=True, has_touch=True)
    page.screenshot(path=str(out("15_mobile_top.png")))
    page.screenshot(path=str(out("15b_mobile_full.png")), full_page=True)
    ctx.close()
    ctx, page = open_viewer(browser, base_url, QUIET, viewport=(360, 740), scale=1, is_mobile=True, has_touch=True)
    page.screenshot(path=str(out("15c_mobile_360_full.png")), full_page=True)
    ctx.close()
    return written


def main() -> int:
    from playwright.sync_api import sync_playwright

    sys.path.insert(0, str(HERE))
    from test_viewer import CHROME_ARGS, CHROME_PATH, SAMPLE, STATIC, serve

    if not SAMPLE.joinpath("puppet.json").exists():
        print(f"sample puppet missing: {SAMPLE}", file=sys.stderr)
        return 2
    server, base = serve(STATIC, SAMPLE)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME_PATH, headless=True, args=CHROME_ARGS)
            files = take_all(browser, base)
            browser.close()
    finally:
        server.shutdown()
    for f in files:
        print(f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
