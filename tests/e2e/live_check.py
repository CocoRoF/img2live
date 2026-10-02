"""Drive the REAL site in a browser: upload -> wait for the job -> visit every result tab -> screenshots.

Not a pytest test (it needs a running deployment and takes minutes).  Usage:
    python tests/e2e/live_check.py --base https://imglive.memo-ora.com --image path/to/character.png --out shots/
Requires: playwright (+ a Chrome/Chromium; set --chrome /usr/bin/google-chrome to use the system one).
"""
import argparse
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

TABS = ["live", "sheet", "layers", "compare", "report", "files"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--image", required=True)
    ap.add_argument("--prompt", default="차분하게, 머리카락은 조금 흔들리게")
    ap.add_argument("--out", default="live_shots")
    ap.add_argument("--chrome", default="")
    ap.add_argument("--timeout", type=int, default=1500)
    ap.add_argument("--access-code", default="")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    problems = []
    with sync_playwright() as p:
        kw = {"executable_path": a.chrome} if a.chrome else {}
        b = p.chromium.launch(headless=True, args=["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
                                                   "--ignore-gpu-blocklist", "--no-sandbox"], **kw)
        ctx = b.new_context(viewport={"width": 1280, "height": 900})
        page = ctx.new_page()
        console = []
        page.on("console", lambda m: console.append((m.type, m.text)) if m.type in ("error", "warning") else None)
        page.on("pageerror", lambda e: problems.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: problems.append(f"request failed: {r.url}"))
        page.on("response", lambda r: problems.append(f"HTTP {r.status}: {r.url}") if r.status >= 400 and "/api/jobs" not in r.url else None)

        page.goto(a.base, wait_until="networkidle")
        page.screenshot(path=str(out / "01_index.png"), full_page=True)
        page.set_input_files("#file", a.image)
        page.fill("#prompt", a.prompt)
        if a.access_code:
            page.fill("#code", a.access_code)
        page.check("#consent")
        page.wait_for_selector("#go:not([disabled])", timeout=120000)
        page.screenshot(path=str(out / "02_index_filled.png"), full_page=True)
        page.click("#go")
        page.wait_for_url("**/j/*", timeout=120000)
        job_url = page.url
        print("job:", job_url, flush=True)
        t0 = time.time()
        last = ""
        while time.time() - t0 < a.timeout:
            title = page.inner_text("#title")
            msg = page.inner_text("#msg")
            if (title, msg) != (last, ""):
                last = title
                print(f"  [{int(time.time() - t0):4d}s] {title} | {page.inner_text('#badge')} | {msg}", flush=True)
            if page.is_visible("#result"):
                break
            if "실패" in page.inner_text("#badge"):
                problems.append("job failed: " + page.inner_text("#err"))
                break
            page.wait_for_timeout(3000)
        page.screenshot(path=str(out / "03_job_status_or_done.png"), full_page=True)
        if page.is_visible("#result"):
            page.wait_for_timeout(2500)  # viewer textures
            for t in TABS:
                page.click(f'button[data-tab="{t}"]')
                page.wait_for_timeout(1500 if t != "live" else 3000)
                page.screenshot(path=str(out / f"10_tab_{t}.png"), full_page=True)
            # exercise the viewer
            page.click('button[data-tab="live"]')
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "20_viewer_idle.png"))
        errs = [c for c in console if c[0] == "error"]
        print(json.dumps({"job": job_url, "problems": problems, "console_errors": errs[:10]}, ensure_ascii=False, indent=1))
        b.close()
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
