"""End-to-end service test without a GPU: API -> queue -> worker pipeline (synthetic engine) -> files."""
import io
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from img2live.config import Settings
from img2live.engine.fake import FakeDecomposer
from img2live.server.app import create_app
from img2live.worker.pipeline import process_job


def _png(w=640, h=800, color=(240, 240, 255, 255)) -> bytes:
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, (h, w, 4), dtype=np.uint8)
    arr[..., 3] = 255
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture()
def env(tmp_path):
    cfg = Settings(data_dir=tmp_path)
    cfg.ensure_dirs()
    cfg.gate_enabled = False
    cfg.per_ip_per_day = 3
    cfg.max_queue = 4
    app = create_app(cfg)
    client = TestClient(app)
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time(), "model_loaded": True}))
    return cfg, app, client


def _submit(client, data=None, **form):
    data = data or _png()
    f = {"consent": "yes", "prompt": form.pop("prompt", ""), "resolution": str(form.pop("resolution", 1280)), **form}
    return client.post("/api/jobs", files={"image": ("a.png", data, "image/png")}, data=f)


def test_full_flow(env):
    cfg, app, client = env
    r = _submit(client, prompt="차분하게, 머리카락 크게")
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "queued"
    # worker side (synthetic engine)
    job = app.state.db.claim_next()
    assert job["id"] == jid
    eng = FakeDecomposer(); eng.load()
    process_job(job, cfg, app.state.db, eng, {"engine": "fake"})
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "done" and j["progress"] == 1.0
    res = j["result"]
    for key in ("puppet", "composite", "layers_index", "report", "source"):
        assert client.get(f"/files/{jid}/{res[key]}").status_code == 200, key
    puppet = client.get(f"/files/{jid}/{res['puppet']}").json()
    assert puppet["schema"] == "img2live-puppet/1" and len(puppet["meshes"]) >= 15
    assert client.get(f"/files/{jid}/qa/pose_sheet.png").status_code == 200
    names = {d["path"].split("/")[-1] for d in res["downloads"]}
    assert {"layers.psd", "layers_fullcanvas.zip", "puppet.zip"} <= names
    rep = client.get(f"/files/{jid}/report.json").json()
    assert rep["qa"]["passed"] and rep["rigSpec"]["motion_intensity"] < 1.0 and rep["rigSpec"]["hair_strength"] > 1.0
    fid = rep["decompose"]["fidelity"]                       # the synthetic character matches its own source: nothing is cut
    assert set(fid) >= {"nose", "eyelash", "canvas:topwear"} and all(v < 0.1 for v in fid.values()), fid
    assert "fidelity_s" in rep["timings"]
    # delete
    assert client.delete(f"/api/jobs/{jid}").json()["deleted"]
    assert client.get(f"/api/jobs/{jid}").status_code == 404
    assert client.get(f"/files/{jid}/report.json").status_code == 404
    assert not (cfg.jobs_dir / jid).exists()


def test_rejects_bad_inputs(env):
    cfg, app, client = env
    assert client.post("/api/jobs", files={"image": ("a.png", _png(), "image/png")}, data={"consent": "", "resolution": "1280"}).status_code == 400
    assert _submit(client, data=b"not an image at all" * 100).status_code == 400
    assert _submit(client, data=_png(100, 100)).status_code == 400  # too small
    assert _submit(client, resolution=999).status_code == 400
    buf = io.BytesIO(); Image.new("RGB", (400, 400)).save(buf, "GIF" if False else "BMP")
    assert _submit(client, data=buf.getvalue()).status_code == 400  # BMP not allowed
    big = b"\x89PNG" + b"0" * (cfg.max_upload_mb * 1024 * 1024 + 10)
    assert _submit(client, data=big).status_code == 413


def test_file_serving_is_safe(env):
    cfg, app, client = env
    jid = _submit(client).json()["id"]
    assert client.get(f"/files/{jid}/source.png").status_code == 200
    assert client.get(f"/files/{jid}/../../img2live.sqlite3").status_code in (404, 400)
    assert client.get(f"/files/{jid}/%2e%2e/%2e%2e/img2live.sqlite3").status_code == 404
    assert client.get("/files/short/source.png").status_code == 404
    assert client.get("/api/jobs/../../etc/passwd").status_code in (404, 405)
    h = client.get(f"/files/{jid}/source.png").headers
    assert h["x-content-type-options"] == "nosniff" and "frame-ancestors 'none'" in h["content-security-policy"]


def test_limits(env):
    cfg, app, client = env
    for _ in range(3):
        assert _submit(client).status_code == 200
    r = _submit(client)
    assert r.status_code == 429  # per-ip daily limit (3)
    cfg.per_ip_per_day = 0
    assert _submit(client).status_code == 200   # 4th active
    assert _submit(client).status_code == 429   # queue full (4)


def test_worker_offline_blocks_uploads(env):
    cfg, app, client = env
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() - 600}))
    assert _submit(client).status_code == 503


def test_pages_and_info(env):
    cfg, app, client = env
    for path in ("/", "/terms"):
        r = client.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert client.get("/static/css/app.css").status_code == 200
    info = client.get("/api/info").json()
    assert info["worker_alive"] and info["resolutions"] == [1024, 1280]
    assert client.get("/robots.txt").text.count("Disallow") >= 2
    p = client.post("/api/parse-prompt", data={"prompt": "no blink, 활발하게"}).json()
    assert p["blink"] is False and p["motion_intensity"] > 1


def test_cleanup_clips_background_leak_and_pipeline_retries(env):
    """The real failure mode: the plain background lands in one layer. It must be detected, clipped, and retried."""
    from img2live.engine.cleanup import clean_result

    res = FakeDecomposer(leak_attempts=1).run(np.zeros((10, 10, 4), np.uint8))
    before = int((res.layers["legwear"][..., 3] > 16).sum())
    assert before > 0.5 * res.canvas ** 2  # the leak covers most of the canvas
    rep = clean_result(res)
    assert rep.silhouette_ok and "legwear" in rep.severe
    after = int((res.layers["legwear"][..., 3] > 16).sum())
    assert after < 0.2 * before  # clipped to (at most) the dilated silhouette: nothing is left outside the character

    cfg, app, client = env
    cfg.retries = 1
    jid = _submit(client).json()["id"]
    job = app.state.db.claim_next()
    eng = FakeDecomposer(leak_attempts=1)
    process_job(job, cfg, app.state.db, eng, {"engine": "fake"})
    rep = json.loads((cfg.jobs_dir / jid / "report.json").read_text())
    att = rep["decompose"]["attempts"]
    assert len(att) == 2 and att[0]["severe"] == ["legwear"] and att[1]["severe"] == []
    assert app.state.db.get(jid)["status"] == "done"


def test_cleanup_fills_a_layer_the_model_left_empty_from_the_source(env):
    """Real failure: the model returned no footwear at all, so the shoes vanished from the character."""
    from img2live.engine.cleanup import clean_result

    res = FakeDecomposer().run(np.zeros((10, 10, 4), np.uint8))
    shoes = int((res.layers["footwear"][..., 3] > 16).sum())
    assert shoes > 0
    res.layers["footwear"] = np.zeros_like(res.layers["footwear"])  # the model dropped them
    rep = clean_result(res)
    assert rep.silhouette_ok and rep.uncovered_frac > 0.01
    assert set(rep.filled) == {"footwear"}  # below the legs -> footwear, not legwear
    filled = res.layers["footwear"]
    assert int((filled[..., 3] > 16).sum()) >= 0.8 * shoes
    # the filled pixels carry the source colours (the shoes are dark in the synthetic character)
    px = filled[filled[..., 3] > 200][:, :3].astype(int)
    assert px.mean() < 90


def test_cleanup_leaves_a_complete_decomposition_alone(env):
    from img2live.engine.cleanup import clean_result

    res = FakeDecomposer().run(np.zeros((10, 10, 4), np.uint8))
    rep = clean_result(res)
    assert rep.filled == {} and rep.uncovered_frac < 0.01 and rep.severe == []


def test_nose_is_drawn_under_the_eyes():
    """The model's 'nose' layer can be a second face-sized skin layer; on top of the eyes it hides them."""
    from img2live.rig.compile import DRAW_ORDER

    assert DRAW_ORDER["face"] < DRAW_ORDER["nose"] < DRAW_ORDER["eyewhite"] < DRAW_ORDER["irides"] < DRAW_ORDER["eyebrow"]


def test_admin_login_lifts_daily_and_queue_limits(env):
    cfg, app, client = env
    cfg.per_ip_per_day, cfg.max_queue, cfg.admin_password = 1, 2, "pw-for-test"
    assert _submit(client).status_code == 200
    assert _submit(client).status_code == 429                                   # a visitor is limited
    assert client.get("/api/info").json()["admin"] is False
    r = client.post("/api/admin/login", data={"password": "nope"})
    assert r.status_code == 403 and "i2l_admin" not in client.cookies           # wrong password: no session
    assert _submit(client).status_code == 429
    r = client.post("/api/admin/login", data={"password": "pw-for-test"})
    assert r.status_code == 200 and "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/info").json()["admin"] is True
    for _ in range(3):                                                          # past the per-IP limit (1) and the queue cap (2)
        assert _submit(client).status_code == 200
    client.post("/api/admin/logout")
    assert client.get("/api/info").json()["admin"] is False
    assert _submit(client).status_code == 429


def test_admin_cookie_cannot_be_forged_and_login_is_throttled(env):
    cfg, app, client = env
    cfg.per_ip_per_day, cfg.admin_password = 1, "pw-for-test"
    _submit(client)
    for forged in ("9999999999.deadbeef", "abc", "1.2", "0.00"):
        client.cookies.set("i2l_admin", forged)
        assert client.get("/api/info").json()["admin"] is False, forged
    client.cookies.clear()
    codes = [client.post("/api/admin/login", data={"password": f"bad{i}"}).status_code for i in range(7)]
    assert codes[:5] == [403] * 5 and codes[5:] == [429, 429]                   # locked after 5 failures
    assert client.post("/api/admin/login", data={"password": "pw-for-test"}).status_code == 429   # even the right one, while locked


def test_admin_mode_is_off_without_a_configured_password(env):
    cfg, app, client = env
    cfg.admin_password = ""
    assert client.post("/api/admin/login", data={"password": ""}).status_code == 404
    client.cookies.set("i2l_admin", "9999999999.00")
    assert client.get("/api/info").json()["admin"] is False


def test_admin_can_list_every_job_and_preview_it_visitors_cannot(env):
    cfg, app, client = env
    cfg.per_ip_per_day, cfg.max_queue, cfg.admin_password = 20, 20, "pw-for-test"
    a = _submit(client, prompt="차분하게 100% 흔들림_보통").json()["id"]
    b = _submit(client, prompt="활발하게").json()["id"]
    c = _submit(client, prompt="삭제할 것").json()["id"]
    job = app.state.db.claim_next()
    assert job["id"] == a
    eng = FakeDecomposer(); eng.load()
    process_job(job, cfg, app.state.db, eng, {"engine": "fake"})             # a: done, with a composite to preview
    app.state.db.update(b, status="failed", error="boom")                     # b: failed, nothing to preview

    # a visitor sees nothing
    assert client.get("/api/admin/jobs").status_code == 403
    assert client.get(f"/api/admin/jobs/{a}/thumb").status_code == 403
    assert client.post("/api/admin/login", data={"password": "pw-for-test"}).status_code == 200

    d = client.get("/api/admin/jobs").json()
    assert d["total"] == 3 and [j["id"] for j in d["items"]] == [c, b, a]     # newest first
    assert d["counts"] == {"done": 1, "failed": 1, "queued": 1}
    by = {j["id"]: j for j in d["items"]}
    assert by[a]["has_thumb"] and by[a]["total_s"] and not by[b]["has_thumb"] and by[b]["error"] == "boom"
    assert [j["id"] for j in client.get("/api/admin/jobs?status=done").json()["items"]] == [a]
    assert client.get("/api/admin/jobs?status=bogus").status_code == 400
    # search: by prompt (percent sign and underscore are literal) and by id
    assert [j["id"] for j in client.get("/api/admin/jobs", params={"q": "100%"}).json()["items"]] == [a]
    assert [j["id"] for j in client.get("/api/admin/jobs", params={"q": "흔들림_보"}).json()["items"]] == [a]
    assert client.get("/api/admin/jobs", params={"q": "100_"}).json()["total"] == 0
    assert [j["id"] for j in client.get("/api/admin/jobs", params={"q": b[:10]}).json()["items"]] == [b]
    # pagination
    p1 = client.get("/api/admin/jobs?limit=2&offset=0").json(); p2 = client.get("/api/admin/jobs?limit=2&offset=2").json()
    assert p1["total"] == 3 and [j["id"] for j in p1["items"]] + [j["id"] for j in p2["items"]] == [c, b, a]

    # thumbnails: made from the composite, cached, cropped to the character, never for a job without one
    r = client.get(f"/api/admin/jobs/{a}/thumb")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    im = Image.open(io.BytesIO(r.content)); assert max(im.size) <= 320 and im.mode == "RGBA"
    assert (cfg.jobs_dir / a / "thumb.png").exists()
    assert client.get(f"/api/admin/jobs/{b}/thumb").status_code == 404
    assert client.get("/api/admin/jobs/..%2F..%2Fetc/thumb").status_code == 404
    assert client.get("/api/admin/jobs/not-a-job-id/thumb").status_code == 404

    # a deleted job leaves the list
    assert client.delete(f"/api/jobs/{c}").json()["deleted"]
    assert [j["id"] for j in client.get("/api/admin/jobs").json()["items"]] == [b, a]
    # the page itself is served to everyone but is not for crawlers
    assert client.get("/admin").status_code == 200 and "Disallow: /admin" in client.get("/robots.txt").text


def test_pages_version_their_assets_and_static_files_revalidate(env):
    """A CDN once kept serving an old stylesheet after a deploy: asset URLs now carry a content hash."""
    cfg, app, client = env
    for path in ("/", "/terms", "/admin", "/j/" + "a" * 22):
        h = client.get(path).text
        refs = __import__("re").findall(r'(?:src|href)="(/static/[^"]+)"', h)
        assert refs and all("?v=" in r and len(r.split("?v=")[1]) == 10 for r in refs), (path, refs)
    css = [r for r in __import__("re").findall(r'href="(/static/css/app\.css\?v=\w+)"', client.get("/").text)][0]
    r = client.get(css)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache" and r.headers.get("etag")
    assert client.get("/static/css/app.css", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    # the hash follows the content
    a = client.get("/").text
    css_file = Path(__import__("img2live.server.app", fromlist=["x"]).STATIC_DIR) / "css" / "app.css"
    old = css_file.read_bytes()
    try:
        css_file.write_bytes(old + b"\n/* changed */\n")
        assert client.get("/").text != a
    finally:
        css_file.write_bytes(old)
