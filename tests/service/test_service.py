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
