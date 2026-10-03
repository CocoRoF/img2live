"""Partial regeneration: API -> task queue -> worker -> candidate versions -> apply.  Synthetic engine, no GPU."""
import io
import json
import time

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from img2live.engine.fake import FakeDecomposer
from img2live.worker.regen import process_regen

from test_studio import L, _job, _make, layer_png  # noqa: E402  (helpers shared with the studio tests)


@pytest.fixture()
def fresh(tmp_path):
    cfg, app, client = _make(tmp_path)
    return cfg, app, client, _job(cfg, app, client)


def run_worker_once(cfg, app):
    task = app.state.db.claim_next_task()
    assert task is not None
    eng = FakeDecomposer(); eng.load()
    process_regen(task, cfg, app.state.db, eng)
    return task["id"]


def test_regen_runs_whole_groups_and_every_layer_comes_back_as_a_candidate(fresh):
    cfg, app, client, jid = fresh
    s0 = client.get(f"/api/jobs/{jid}/studio").json()
    assert s0["can_regen"] is True and s0["tasks"] == []
    r = client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear", "face"], "seed": 11, "steps": 25})
    assert r.status_code == 200, r.text
    t = r.json()["task"]
    assert t["status"] == "queued" and t["tags"] == ["footwear", "face"] and t["seed"] == 11 and t["steps"] == 25
    assert client.get(f"/api/jobs/{jid}/studio").json()["tasks"][0]["id"] == t["id"]
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear"]}).status_code == 409   # one at a time per puppet

    run_worker_once(cfg, app)
    s = client.get(f"/api/jobs/{jid}/studio").json()
    task = s["tasks"][0]
    res = task["result"]
    assert task["status"] == "done" and task["progress"] == 1.0 and res["seed"] == 11
    assert set(res["tags"]) == {"footwear", "face"}                              # what was asked for
    got = {v["tag"]: v for v in res["versions"]}
    assert {"footwear", "topwear", "front hair", "face", "eyelash", "nose"} <= set(got)    # the model made the whole groups
    assert got["footwear"]["requested"] and got["face"]["requested"] and not got["topwear"]["requested"]
    for tag, v in got.items():
        lay = L(s, tag)
        assert lay["current"] == "v0"                                            # a candidate is never applied by itself
        cands = [x for x in lay["versions"] if x["kind"] == "regen"]
        assert len(cands) == 1 and cands[0]["id"] == v["version"] and cands[0]["seed"] == 11 and cands[0]["task"] == task["id"]
    assert s["rev"] == 0                                                          # the puppet did not change
    cand = got["footwear"]["version"]
    old, new = layer_png(client, jid, "footwear"), layer_png(client, jid, "footwear", cand)
    assert new.shape == old.shape and not np.array_equal(new, old)
    assert client.get(f"/api/jobs/{jid}/studio/layer/footwear/thumb", params={"v": cand}).status_code == 200
    # one layer: select its candidate
    ap = client.post(f"/api/jobs/{jid}/studio/layer/footwear/select", json={"version": cand}).json()["state"]
    assert ap["rev"] == 1 and L(ap, "footwear")["current"] == cand and L(ap, "topwear")["current"] == "v0"
    # the whole sample at once, optionally only some layers
    part = client.post(f"/api/jobs/{jid}/studio/task/{task['id']}/apply", json={"tags": ["topwear"]}).json()["state"]
    assert part["rev"] == 2 and L(part, "topwear")["current"] == got["topwear"]["version"] and L(part, "face")["current"] == "v0"
    allin = client.post(f"/api/jobs/{jid}/studio/task/{task['id']}/apply", json={}).json()["state"]
    assert allin["rev"] == 3 and all(L(allin, tag)["current"] == v["version"] for tag, v in got.items())
    assert client.post(f"/api/jobs/{jid}/studio/task/{task['id']}/apply", json={"tags": "x"}).status_code == 400
    assert client.post(f"/api/jobs/{jid}/studio/task/nope/apply", json={}).status_code == 404
    # a finished task frees the puppet for the next one
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["topwear"], "seed": 5}).status_code == 200


def test_a_body_only_request_does_not_run_the_head_group(fresh):
    cfg, app, client, jid = fresh
    client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear"], "seed": 3})
    run_worker_once(cfg, app)
    res = client.get(f"/api/jobs/{jid}/studio").json()["tasks"][0]["result"]
    tags = {v["tag"] for v in res["versions"]}
    assert "topwear" in tags and "face" not in tags and "eyelash" not in tags     # body group only


class LeakyEngine(FakeDecomposer):
    """The model's known failure: one layer (legwear) comes back as the whole picture."""

    def regen(self, *a, **k):
        out = super().regen(*a, **k)
        out["legwear"] = np.full_like(out["legwear"], (170, 170, 170, 255))
        return out


def test_a_leaked_layer_is_not_offered_as_a_candidate(fresh):
    cfg, app, client, jid = fresh
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear"], "seed": 9}).status_code == 200
    task = app.state.db.claim_next_task()
    eng = LeakyEngine(); eng.load()
    process_regen(task, cfg, app.state.db, eng)
    s = client.get(f"/api/jobs/{jid}/studio").json()
    res = s["tasks"][0]["result"]
    assert res["dropped"] == ["legwear"]
    assert "legwear" not in {v["tag"] for v in res["versions"]}
    assert [v["kind"] for v in L(s, "legwear")["versions"]] == ["original"]            # nothing was stored for it
    assert "footwear" in {v["tag"] for v in res["versions"]} and "topwear" in {v["tag"] for v in res["versions"]}   # the rest is fine


def test_regen_input_checks_limits_and_admin(fresh):
    cfg, app, client, jid = fresh
    post = lambda **p: client.post(f"/api/jobs/{jid}/studio/regen", json=p)
    assert post(tags=[]).status_code == 400 and post(tags=["nope"]).status_code == 400 and post().status_code == 400
    assert post(tags=["footwear"], seed="abc").status_code == 400
    cfg.regen_per_ip_per_day, cfg.admin_password = 1, "pw-for-test"
    assert post(tags=["footwear"]).status_code == 200
    run_worker_once(cfg, app)
    assert post(tags=["footwear"]).status_code == 429                          # a visitor's daily allowance is used up
    assert client.post("/api/admin/login", data={"password": "pw-for-test"}).status_code == 200
    assert post(tags=["footwear"]).status_code == 200                          # the admin is not limited
    # the worker is gone -> no new work is accepted
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() - 600, "model_loaded": True}))
    run_worker_once(cfg, app)
    assert post(tags=["footwear"]).status_code == 503
    assert client.get(f"/api/jobs/{jid}/studio").json()["can_regen"] is False


def test_regen_for_a_deleted_job_fails_cleanly_and_tasks_go_with_the_job(fresh):
    cfg, app, client, jid = fresh
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear"]}).status_code == 200
    assert client.delete(f"/api/jobs/{jid}").json()["deleted"]
    assert app.state.db.claim_next_task() is None                              # the queued task was removed with the job
    assert client.post(f"/api/jobs/{jid}/studio/regen", json={"tags": ["footwear"]}).status_code == 404


def test_the_studio_lock_is_reentrant_and_exclusive_across_threads(tmp_path):
    import threading
    from img2live.studio.store import job_lock

    lock = job_lock("x" * 22, tmp_path)
    order = []
    with lock:
        with lock:                                                             # re-entry in the same thread works
            order.append("a")
        t = threading.Thread(target=lambda: (lock.__enter__(), order.append("b"), lock.__exit__(None, None, None)))
        t.start(); time.sleep(0.2)
        assert order == ["a"]                                                  # the other thread waits while we hold it
    t.join(5)
    assert order == ["a", "b"] and (tmp_path / ".studio.lock").exists()
