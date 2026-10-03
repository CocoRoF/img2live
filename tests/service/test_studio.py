"""Studio backend: versions, edits, flags, rebuild, rollback.  Synthetic character, no GPU."""
import base64
import io
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from img2live.config import Settings
from img2live.engine.fake import FakeDecomposer
from img2live.server.app import create_app
from img2live.worker.pipeline import process_job


def _png(w=640, h=800) -> bytes:
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 255, (h, w, 4), dtype=np.uint8)
    arr[..., 3] = 255
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, "PNG")
    return buf.getvalue()


@pytest.fixture(scope="module")
def made(tmp_path_factory):
    """One finished job reused by the read-only tests; write tests make their own copy via ``fresh``."""
    return _make(tmp_path_factory.mktemp("studio"))


def _make(tmp):
    cfg = Settings(data_dir=tmp)
    cfg.ensure_dirs()
    cfg.gate_enabled, cfg.per_ip_per_day, cfg.max_queue = False, 50, 20
    app = create_app(cfg)
    client = TestClient(app)
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 3600, "model_loaded": True}))
    return cfg, app, client


def _job(cfg, app, client, prompt="차분하게"):
    r = client.post("/api/jobs", files={"image": ("a.png", _png(), "image/png")},
                    data={"consent": "yes", "prompt": prompt, "resolution": "1280"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    job = app.state.db.claim_next()
    eng = FakeDecomposer(); eng.load()
    process_job(job, cfg, app.state.db, eng, {"engine": "fake"})
    return jid


@pytest.fixture()
def fresh(tmp_path):
    cfg, app, client = _make(tmp_path)
    return cfg, app, client, _job(cfg, app, client)


def mask_b64(box, n=1280):
    m = np.zeros((n, n), np.uint8)
    x0, y0, x1, y1 = box
    m[y0:y1, x0:x1] = 255
    buf = io.BytesIO()
    Image.fromarray(m, "L").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


def layer_png(client, jid, tag, v="current"):
    r = client.get(f"/api/jobs/{jid}/studio/layer/{tag}/image", params={"v": v})
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    return np.asarray(Image.open(io.BytesIO(r.content)).convert("RGBA"))


def edit(client, jid, tag, **payload):
    return client.post(f"/api/jobs/{jid}/studio/layer/{tag}/edit", json=payload)


def L(state, tag):
    return next(x for x in state["layers"] if x["tag"] == tag)


def test_initial_state_and_images(fresh):
    cfg, app, client, jid = fresh
    s = client.get(f"/api/jobs/{jid}/studio").json()
    assert s["rev"] == 0 and s["puppet"] == f"/files/{jid}/puppet/puppet.json" and s["canvas"] == 1280
    assert s["head_square"] and s["can_regen"] and s["tasks"] == []          # the (fake) worker is alive
    tags = {x["tag"] for x in s["layers"]}
    assert {"front hair", "face", "topwear", "footwear", "nose"} <= tags and len(tags) == 23
    assert L(s, "face")["grid"] == "head" and L(s, "topwear")["grid"] == "canvas"
    assert L(s, "topwear")["current"] == "v0" and L(s, "topwear")["versions"][0]["kind"] == "original"
    assert not L(s, "topwear")["empty"] and L(s, "tail")["empty"] and L(s, "topwear")["label"] == "상의" and L(s, "topwear")["group"] == "body"
    a = layer_png(client, jid, "topwear")
    assert a.shape == (1280, 1280, 4) and a[..., 3].sum() > 0
    assert layer_png(client, jid, "face").shape == (1280, 1280, 4)
    t = client.get(f"/api/jobs/{jid}/studio/layer/topwear/thumb")
    assert t.status_code == 200 and max(Image.open(io.BytesIO(t.content)).size) <= 160
    assert client.get(f"/api/jobs/{jid}/studio/layer/tail/thumb").status_code == 404          # empty layer: no preview
    for grid in ("canvas", "head"):
        r = client.get(f"/api/jobs/{jid}/studio/source", params={"grid": grid})
        assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == (1280, 1280)
    assert client.get(f"/api/jobs/{jid}/studio/source", params={"grid": "x"}).status_code == 400
    assert client.get(f"/api/jobs/{jid}/studio/layer/nope/image").status_code == 404


def test_erase_makes_a_version_rebuilds_the_puppet_and_undo_restores(fresh):
    cfg, app, client, jid = fresh
    before = layer_png(client, jid, "topwear")
    r = edit(client, jid, "topwear", op="erase", mask=mask_b64((600, 400, 700, 500)), note="시험")
    assert r.status_code == 200, r.text
    s = r.json()["state"]
    assert s["rev"] == 1 and s["puppet"] == f"/files/{jid}/studio/puppet/r1/puppet.json"
    tw = L(s, "topwear")
    assert tw["current"] != "v0" and [v["kind"] for v in tw["versions"]] == ["original", "edit"] and tw["versions"][1]["note"] == "시험"
    after = layer_png(client, jid, "topwear")
    assert (after[400:500, 600:700, 3] == 0).all() and (before[400:500, 600:700, 3] > 0).any()
    assert np.array_equal(after[:400], before[:400])                                 # nothing outside the mask changed
    puppet = client.get(s["puppet"]).json()
    assert puppet["schema"] == "img2live-puppet/1" and any(m["tag"] == "topwear" for m in puppet["meshes"])
    assert client.get(f"/files/{jid}/studio/puppet/r1/{puppet['meshes'][0]['texture']}").status_code == 200
    assert (cfg.jobs_dir / jid / "thumb.png").exists()
    # undo = select the original again
    u = client.post(f"/api/jobs/{jid}/studio/layer/topwear/select", json={"version": "v0"}).json()["state"]
    assert u["rev"] == 2 and L(u, "topwear")["current"] == "v0"
    assert np.array_equal(layer_png(client, jid, "topwear"), before)
    redo = client.post(f"/api/jobs/{jid}/studio/layer/topwear/select", json={"version": tw["current"]}).json()["state"]
    assert L(redo, "topwear")["current"] == tw["current"]


def test_restore_paints_source_pixels_but_never_the_background(fresh):
    cfg, app, client, jid = fresh
    original = layer_png(client, jid, "topwear")
    box = (600, 400, 700, 500)
    edit(client, jid, "topwear", op="erase", mask=mask_b64(box))
    r = edit(client, jid, "topwear", op="restore", mask=mask_b64(box))
    assert r.status_code == 200, r.text
    got = layer_png(client, jid, "topwear")
    region = (slice(400, 500), slice(600, 700))
    assert (got[region][..., 3] > 200).mean() > 0.95                                  # the source's garment came back
    assert np.abs(got[region][..., :3].astype(int) - original[region][..., :3].astype(int)).mean() < 12
    # the blank background of the source is not pasted into a layer
    bad = edit(client, jid, "topwear", op="restore", mask=mask_b64((1000, 1000, 1100, 1100)))
    assert bad.status_code == 400 and "채울 픽셀" in bad.json()["detail"]


def test_move_pixels_between_layers_and_between_grids(fresh):
    cfg, app, client, jid = fresh
    box = (600, 400, 700, 500)
    top0, bot0 = layer_png(client, jid, "topwear"), layer_png(client, jid, "bottomwear")
    r = edit(client, jid, "topwear", op="move", to="bottomwear", mask=mask_b64(box))
    assert r.status_code == 200, r.text
    s = r.json()["state"]
    top1, bot1 = layer_png(client, jid, "topwear"), layer_png(client, jid, "bottomwear")
    assert (top1[400:500, 600:700, 3] == 0).all() and (bot1[400:500, 600:700, 3] > 0).any()
    assert np.array_equal(bot1[400:500, 600:700, :3][bot1[400:500, 600:700, 3] > 250],
                          top0[400:500, 600:700, :3][bot1[400:500, 600:700, 3] > 250])           # colours travel with the pixels
    assert len(L(s, "topwear")["versions"]) == 2 and len(L(s, "bottomwear")["versions"]) == 2
    # head grid -> canvas grid: a patch of the face goes to the neck, at the right place
    face_cur = layer_png(client, jid, "face")
    ys, xs = np.where(face_cur[..., 3] > 200)
    cx, cy = int(xs.mean()), int(ys.mean())
    r2 = edit(client, jid, "face", op="move", to="neck", mask=mask_b64((cx - 80, cy - 80, cx + 80, cy + 80)))
    assert r2.status_code == 200, r2.text
    neck = layer_png(client, jid, "neck")
    assert (neck[..., 3] > 0).sum() > 0
    assert edit(client, jid, "topwear", op="move", to="topwear", mask=mask_b64(box)).status_code == 400
    assert edit(client, jid, "topwear", op="move", to="bogus", mask=mask_b64(box)).status_code == 400


def test_flags_enable_and_draw_order_reach_the_puppet(fresh):
    cfg, app, client, jid = fresh
    r = client.post(f"/api/jobs/{jid}/studio/layer/back hair/flags", json={"enabled": False})
    assert r.status_code == 200, r.text
    puppet = client.get(r.json()["state"]["puppet"]).json()
    assert not any(m["tag"] == "back hair" for m in puppet["meshes"])
    assert L(r.json()["state"], "back hair")["enabled"] is False
    r = client.post(f"/api/jobs/{jid}/studio/layer/nose/flags", json={"order": 300})
    puppet = client.get(r.json()["state"]["puppet"]).json()
    assert {m["order"] for m in puppet["meshes"] if m["tag"] == "nose"} == {300}
    assert L(r.json()["state"], "nose")["order"] == 300 and L(r.json()["state"], "nose")["order_default"] != 300
    r = client.post(f"/api/jobs/{jid}/studio/layer/nose/flags", json={"order": None})
    assert L(r.json()["state"], "nose")["order"] == L(r.json()["state"], "nose")["order_default"]
    assert client.post(f"/api/jobs/{jid}/studio/layer/nose/flags", json={"order": "x"}).status_code == 400


def test_a_failed_rebuild_rolls_the_change_back(fresh):
    cfg, app, client, jid = fresh
    r = client.post(f"/api/jobs/{jid}/studio/layer/face/flags", json={"enabled": False})
    assert r.status_code == 422 and "얼굴" in r.json()["detail"]
    s = client.get(f"/api/jobs/{jid}/studio").json()
    assert L(s, "face")["enabled"] is True and s["rev"] == 0                           # nothing changed


def test_batching_edits_then_one_rebuild_and_reset(fresh):
    cfg, app, client, jid = fresh
    r1 = edit(client, jid, "topwear", op="erase", mask=mask_b64((600, 400, 700, 500)), rebuild=False).json()["state"]
    assert r1["rev"] == 0 and r1["dirty"] is True and r1["puppet"].endswith("/puppet/puppet.json")
    r2 = edit(client, jid, "bottomwear", op="erase", mask=mask_b64((600, 620, 680, 680)), rebuild=False).json()["state"]
    assert r2["rev"] == 0
    rb = client.post(f"/api/jobs/{jid}/studio/rebuild").json()["state"]
    assert rb["rev"] == 1 and rb["dirty"] is False
    rs = client.post(f"/api/jobs/{jid}/studio/reset").json()["state"]
    assert rs["rev"] == 2 and all(x["current"] == "v0" and x["enabled"] for x in rs["layers"])
    assert len(L(rs, "topwear")["versions"]) == 2                                      # the history stays, only the choice resets


def test_delete_version_rules(fresh):
    cfg, app, client, jid = fresh
    s = edit(client, jid, "topwear", op="erase", mask=mask_b64((600, 400, 700, 500))).json()["state"]
    e1 = L(s, "topwear")["current"]
    assert client.delete(f"/api/jobs/{jid}/studio/layer/topwear/version/v0").status_code == 400      # the original stays
    assert client.delete(f"/api/jobs/{jid}/studio/layer/topwear/version/{e1}").status_code == 400    # so does the current one
    client.post(f"/api/jobs/{jid}/studio/layer/topwear/select", json={"version": "v0"})
    d = client.delete(f"/api/jobs/{jid}/studio/layer/topwear/version/{e1}")
    assert d.status_code == 200 and [v["id"] for v in L(d.json()["state"], "topwear")["versions"]] == ["v0"]
    assert not (cfg.jobs_dir / jid / "studio" / "v" / "topwear" / f"{e1}.png").exists()


def test_fill_hole_and_clean_and_input_errors(fresh):
    cfg, app, client, jid = fresh
    edit(client, jid, "topwear", op="erase", mask=mask_b64((620, 420, 660, 460)))      # a hole inside the garment
    r = edit(client, jid, "topwear", op="fill_hole")
    assert r.status_code == 200, r.text
    assert (layer_png(client, jid, "topwear")[430:450, 630:650, 3] > 200).all()
    assert edit(client, jid, "topwear", op="fill_hole").status_code == 400             # nothing left to fill
    c = edit(client, jid, "topwear", op="clean")
    assert c.status_code in (200, 400)                                                  # a faithful layer may have nothing to clean
    assert edit(client, jid, "topwear", op="erase").status_code == 400                  # no mask
    assert edit(client, jid, "topwear", op="erase", mask=mask_b64((0, 0, 1, 1))).status_code == 400   # nothing of the layer there
    assert edit(client, jid, "topwear", op="dance", mask=mask_b64((600, 400, 700, 500))).status_code == 400
    assert client.post(f"/api/jobs/{jid}/studio/layer/topwear/select", json={"version": "zzz"}).status_code == 404
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": []}).status_code == 400


def test_head_grid_edit_and_job_state_guards(fresh):
    cfg, app, client, jid = fresh
    mouth = layer_png(client, jid, "mouth")
    ys, xs = np.where(mouth[..., 3] >= 16)
    box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1)
    r = edit(client, jid, "mouth", op="erase", mask=mask_b64(box))
    assert r.status_code == 200, r.text
    assert (layer_png(client, jid, "mouth")[..., 3] > 16).sum() == 0
    puppet = client.get(r.json()["state"]["puppet"]).json()
    assert not any(m["tag"] == "mouth" for m in puppet["meshes"])
    # guards
    assert client.get("/api/jobs/zzzzzzzzzzzzzzzzzzzzzz/studio").status_code == 404
    assert client.get("/api/jobs/short/studio").status_code == 404
    queued = client.post("/api/jobs", files={"image": ("a.png", _png(), "image/png")}, data={"consent": "yes", "resolution": "1280"}).json()["id"]
    assert client.get(f"/api/jobs/{queued}/studio").status_code == 409
    assert client.delete(f"/api/jobs/{jid}").status_code == 200
    assert client.get(f"/api/jobs/{jid}/studio").status_code == 404
