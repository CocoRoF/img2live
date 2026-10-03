# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the studio UI tests (no GPU, no model).

* ``ensure_fixture()`` runs the real worker pipeline once with the synthetic engine and caches the whole data dir under
  ``bench/outputs/studio_fixture`` (set IMG2LIVE_REBUILD_FIXTURE=1 to rebuild).  Every test module copies it to a temp dir.
* ``Site`` serves it with a real uvicorn instance of ``create_app`` (real job page, files, SSE, DELETE).
* ``StudioMock`` answers ``/api/jobs/<id>/studio/...`` through ``page.route`` with a small stateful fake of the studio
  backend (plan/08-studio.md §4): state, thumbnails, select / flags / edit / delete / reset / regen, and a recompiled
  puppet per revision (layers switched off are dropped, draw order follows the flags).
"""
from __future__ import annotations

import io
import json
import os
import re
import shutil
import socket
import sys
import threading
import time
from pathlib import Path
from urllib.parse import unquote, urlparse

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "src"))

CACHE = ROOT / "bench" / "outputs" / "studio_fixture"

LABELS = {
    "front hair": "앞머리", "back hair": "뒷머리", "face": "얼굴", "eyewhite": "눈 흰자", "irides": "홍채",
    "eyelash": "속눈썹", "eyebrow": "눈썹", "nose": "코", "mouth": "입", "ears": "귀", "earwear": "귀걸이",
    "eyewear": "안경", "headwear": "머리 장식", "neck": "목", "neckwear": "목걸이·목 장식", "topwear": "상의",
    "handwear": "팔·손", "bottomwear": "하의", "legwear": "다리", "footwear": "신발", "tail": "꼬리",
    "wings": "날개", "objects": "소품",
}
GROUPS = {
    "hair": ["front hair", "back hair"],
    "face": ["face", "eyewhite", "irides", "eyelash", "eyebrow", "nose", "mouth", "ears", "earwear", "eyewear", "headwear"],
    "body": ["neck", "neckwear", "topwear", "handwear", "bottomwear", "legwear", "footwear"],
    "other": ["tail", "wings", "objects"],
}
GROUP_LABELS = {"hair": "머리카락", "face": "얼굴", "body": "몸", "other": "기타"}
TAG_GROUP = {t: g for g, ts in GROUPS.items() for t in ts}
HEAD_TAGS = set(GROUPS["face"])


# ------------------------------------------------------------------------------------------------ the job
def _build(dst: Path) -> str:
    from fastapi.testclient import TestClient

    from img2live.config import Settings
    from img2live.engine.fake import FakeDecomposer
    from img2live.server.app import create_app
    from img2live.worker.pipeline import process_job

    cfg = Settings(data_dir=dst)
    cfg.ensure_dirs()
    cfg.gate_enabled, cfg.per_ip_per_day, cfg.max_queue = False, 50, 20
    app = create_app(cfg)
    client = TestClient(app)
    (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 3600, "model_loaded": True}))
    arr = np.random.default_rng(0).integers(0, 255, (800, 640, 4), dtype=np.uint8)
    arr[..., 3] = 255
    buf = io.BytesIO()
    Image.fromarray(arr, "RGBA").save(buf, "PNG")
    r = client.post("/api/jobs", files={"image": ("a.png", buf.getvalue(), "image/png")},
                    data={"consent": "yes", "prompt": "차분하게, 머리카락은 조금", "resolution": "1280"})
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    job = app.state.db.claim_next()
    eng = FakeDecomposer()
    eng.load()
    process_job(job, cfg, app.state.db, eng, {"engine": "fake"})
    (dst / "FIXTURE_JOB").write_text(jid)
    return jid


def ensure_fixture() -> tuple[Path, str]:
    """(data dir, job id) of the cached finished synthetic job."""
    if os.environ.get("IMG2LIVE_REBUILD_FIXTURE") and CACHE.exists():
        shutil.rmtree(CACHE)
    if not (CACHE / "FIXTURE_JOB").exists():
        if CACHE.exists():
            shutil.rmtree(CACHE)
        CACHE.mkdir(parents=True)
        _build(CACHE)
    return CACHE, (CACHE / "FIXTURE_JOB").read_text().strip()


class Site:
    """A real uvicorn instance over a private copy of the fixture data dir."""

    def __init__(self, tmp: Path):
        import uvicorn

        from img2live.config import Settings
        from img2live.server.app import create_app

        src, self.job_id = ensure_fixture()
        self.data = tmp / "data"
        shutil.copytree(src, self.data)
        cfg = Settings(data_dir=self.data)
        cfg.ensure_dirs()
        cfg.gate_enabled, cfg.per_ip_per_day, cfg.max_queue = False, 50, 20
        (cfg.data_dir / "worker.json").write_text(json.dumps({"ts": time.time() + 36000, "model_loaded": True}))
        self.cfg = cfg
        self.app = create_app(cfg)
        self.db = self.app.state.db
        self.jdir = cfg.jobs_dir / self.job_id
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        while not self.server.started:
            time.sleep(0.05)

    def close(self):
        self.server.should_exit = True
        self.thread.join(5)

    def job(self, jid=None):
        return f"{self.url}/j/{jid or self.job_id}"

    def add_job(self, status: str, **fields) -> str:
        """A job row without any worker: queued / running / failed, with a source image so the page can show it."""
        self._n = getattr(self, "_n", 0) + 1
        jid = f"t{status[:3]}{self._n:03d}" + "x" * 15
        self.db.create(jid, fields.pop("prompt", "대기 중인 그림"), 1280, 1, "ih", {}, 72)
        d = self.cfg.jobs_dir / jid
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.jdir / "source.png", d / "source.png")
        if status != "queued":
            self.db.update(jid, status=status, **fields)
        return jid


# ------------------------------------------------------------------------------------------------ studio state
def base_state(jid: str, jdir: Path, rev: int = 0, puppet: str | None = None, can_regen: bool = True) -> dict:
    from img2live.rig.compile import DRAW_ORDER

    idx = json.loads((jdir / "layers" / "index.json").read_text())
    by = {l["tag"]: l for l in idx["layers"]}
    layers = []
    for tag, label in LABELS.items():
        e = by.get(tag) or {"empty": True}
        empty = bool(e.get("empty")) or not e.get("file")
        order = DRAW_ORDER.get(tag, 100)
        layers.append({
            "tag": tag, "label": label, "group": TAG_GROUP[tag], "grid": "head" if tag in HEAD_TAGS else "canvas",
            "enabled": True, "order": order, "order_default": order, "current": "v0",
            "versions": [{"id": "v0", "kind": "original", "note": "", "created": time.time() - 3600}],
            "bbox": None if empty else [e["x"], e["y"], e["w"], e["h"]],  # [x, y, width, height] like the real server
            "opaque_px": 0 if empty else e["opaque_px"], "empty": empty,
        })
    return {"rev": rev, "puppet": puppet or f"/files/{jid}/puppet/puppet.json", "canvas": idx["canvas"], "head_square": idx["head_square"],
            "layers": layers, "groups": GROUP_LABELS, "tasks": [], "can_regen": can_regen}


def png_bytes(img: Image.Image) -> bytes:
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


class StudioMock:
    """Stateful fake of /api/jobs/<id>/studio/*, installed on a Playwright page (or context)."""

    def __init__(self, jid: str, jdir: Path, can_regen: bool = True, delay: float = 0.0):
        self.jid, self.jdir, self.delay = jid, jdir, delay
        self.state = base_state(jid, jdir, can_regen=can_regen)
        self.calls: list[tuple[str, str, object]] = []
        self.fail: dict[str, tuple[int, str]] = {}  # "POST /layer/x/flags" -> (status, detail)
        self.puppet0 = json.loads((jdir / "puppet" / "puppet.json").read_text())
        self._thumbs: dict[str, bytes] = {}
        self._vcount = 0
        self.hold = False          # True: POST/DELETE requests wait until release() (to look at the page while the "server" works)
        self.pending: list = []

    # ---- helpers for tests
    def layer(self, tag: str) -> dict:
        return next(l for l in self.state["layers"] if l["tag"] == tag)

    def add_version(self, tag: str, kind: str, note: str = "", seed=None, make_current: bool = False) -> str:
        self._vcount += 1
        vid = f"v{self._vcount}"
        v = {"id": vid, "kind": kind, "note": note, "created": time.time() - 60 * self._vcount}
        if seed is not None:
            v["seed"] = seed
        L = self.layer(tag)
        L["versions"].append(v)
        if make_current:
            L["current"] = vid
        return vid

    def bump(self):
        self.state["rev"] += 1
        self.state["puppet"] = f"/mock/{self.jid}/r{self.state['rev']}/puppet.json"

    def calls_of(self, kind: str) -> list[tuple[str, object]]:
        return [(p, b) for m, p, b in self.calls if p.endswith(kind) or kind in p]

    # ---- the recompiled puppet of the current state
    def puppet(self) -> dict:
        p = json.loads(json.dumps(self.puppet0))
        off = {l["tag"] for l in self.state["layers"] if not l["enabled"]}
        order = {l["tag"]: l["order"] for l in self.state["layers"]}
        p["meshes"] = [m for m in p["meshes"] if m.get("tag") not in off]
        for m in p["meshes"]:
            if m.get("tag") in order:
                m["order"] = order[m["tag"]]
        return p

    def thumb(self, tag: str, vid: str) -> bytes | None:
        L = self.layer(tag)
        if L["empty"]:
            return None
        key = f"{tag}:{vid}"
        if key not in self._thumbs:
            name = tag.replace(" ", "_") + ".png"
            im = Image.open(self.jdir / "layers" / name).convert("RGBA")
            im.thumbnail((160, 160))
            if vid != "v0":  # make versions visibly different (a hue shift) so the list is not a column of twins
                a = np.asarray(im).copy()
                a[..., 0] = np.clip(a[..., 0].astype(int) + 40 * (int(vid[1:]) % 4), 0, 255)
                im = Image.fromarray(a, "RGBA")
            self._thumbs[key] = png_bytes(im)
        return self._thumbs[key]

    # ---- request handling
    def install(self, page):
        page.route(re.compile(rf".*/api/jobs/{re.escape(self.jid)}/studio(/.*)?(\?.*)?$"), self._studio)
        page.route(re.compile(rf".*/mock/{re.escape(self.jid)}/r\d+/.*"), self._puppet)

    def _json(self, route, body, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(body, ensure_ascii=False))

    def _puppet(self, route, request):
        rel = urlparse(request.url).path.split("/", 4)[4]  # /mock/<jid>/r<N>/<rel>
        if rel == "puppet.json":
            return self._json(route, self.puppet())
        route.fulfill(path=str(self.jdir / "puppet" / rel))

    def release(self):
        """Answer every held request (call from the test thread)."""
        pending, self.pending = self.pending, []
        for route, request in pending:
            self._answer(route, request)

    def _studio(self, route, request):
        if self.delay:
            time.sleep(self.delay)
        if self.hold and request.method != "GET":
            self.pending.append((route, request))
            return
        self._answer(route, request)

    def _answer(self, route, request):
        path = unquote(urlparse(request.url).path.split("/studio", 1)[1])
        method = request.method
        body = {}
        if method in ("POST", "PUT") and request.post_data:
            body = json.loads(request.post_data)
        self.calls.append((method, path, body))
        key = f"{method} {path}"
        if key in self.fail:
            code, detail = self.fail[key]
            return self._json(route, {"detail": detail}, code)
        if path in ("", "/") and method == "GET":
            return self._json(route, self.state)
        m = re.match(r"^/layer/([^/]+)/(thumb|image)$", path)
        if m and method == "GET":
            vid = (parse_qs(request.url).get("v") or ["current"])[0]
            tag = m.group(1)
            if vid == "current":
                vid = self.layer(tag)["current"]
            data = self.thumb(tag, vid)
            if data is None:
                return route.fulfill(status=404, body="")
            return route.fulfill(status=200, content_type="image/png", body=data)
        m = re.match(r"^/layer/([^/]+)/(select|flags|edit)$", path)
        if m and method == "POST":
            tag, op = m.group(1), m.group(2)
            L = self.layer(tag)
            if op == "select":
                if body["version"] not in {v["id"] for v in L["versions"]}:
                    return self._json(route, {"detail": "그런 버전이 없습니다"}, 404)
                L["current"] = body["version"]
            elif op == "flags":
                if "enabled" in body:
                    L["enabled"] = bool(body["enabled"])
                if "order" in body:
                    L["order"] = int(body["order"])
            else:
                vid = self.add_version(tag, "edit", body.get("note") or "편집", make_current=True)
                L["current"] = vid
            self.bump()
            return self._json(route, {"ok": True, "state": self.state})
        m = re.match(r"^/layer/([^/]+)/version/([^/]+)$", path)
        if m and method == "DELETE":
            L = self.layer(m.group(1))
            L["versions"] = [v for v in L["versions"] if v["id"] != m.group(2)]
            self.bump()
            return self._json(route, {"ok": True, "state": self.state})
        if path == "/reset" and method == "POST":
            for L in self.state["layers"]:
                L["current"], L["enabled"], L["order"] = "v0", True, L["order_default"]
            self.bump()
            return self._json(route, {"ok": True, "state": self.state})
        if path == "/rebuild" and method == "POST":
            self.state["dirty"] = False
            self.bump()
            return self._json(route, {"ok": True, "state": self.state})
        m = re.match(r"^/task/([^/]+)/apply$", path)
        if m and method == "POST":
            task = next((t for t in self.state["tasks"] if t["id"] == m.group(1) and t.get("status") == "done"), None)
            if not task:
                return route.fulfill(status=404, content_type="application/json", body=json.dumps({"detail": "finished regeneration not found"}))
            only = body.get("tags")
            for item in (task.get("result") or {}).get("versions", []):
                if only is None or item["tag"] in only:
                    self.layer(item["tag"])["current"] = item["version"]
            self.bump()
            return self._json(route, {"ok": True, "state": self.state})
        if path == "/regen" and method == "POST":
            task = {"id": f"task{len(self.state['tasks']) + 1}", "kind": "regen", "tags": body.get("tags", []), "status": "running", "progress": 0.1, "message": "생성 중"}
            self.state["tasks"].append(task)
            return self._json(route, {"task": task})
        route.fulfill(status=404, body="")


def parse_qs(url: str) -> dict:
    from urllib.parse import parse_qs as _p

    return _p(urlparse(url).query)


# ------------------------------------------------------------------------------------------------ geometry helpers
def topmost_points(jdir: Path, tags: list[str], erode: int = 2) -> dict[str, tuple[int, int]]:
    """For each tag a canvas pixel where that layer is the topmost visible one (so a click there must pick it)."""
    import cv2

    from img2live.rig.compile import DRAW_ORDER

    idx = json.loads((jdir / "layers" / "index.json").read_text())
    n = idx["canvas"]
    masks: dict[str, np.ndarray] = {}
    for l in idx["layers"]:
        if l.get("empty") or not l.get("file"):
            continue
        a = np.asarray(Image.open(jdir / l["file"]).convert("RGBA"))[..., 3]
        m = np.zeros((n, n), np.uint8)
        m[l["y"]:l["y"] + l["h"], l["x"]:l["x"] + l["w"]] = (a > 16).astype(np.uint8)
        masks[l["tag"]] = m
    k = np.ones((2 * erode + 1, 2 * erode + 1), np.uint8)
    out = {}
    for tag in tags:
        mine = cv2.erode(masks[tag], k)
        above = np.zeros((n, n), np.uint8)
        for t, m in masks.items():
            if DRAW_ORDER.get(t, 100) > DRAW_ORDER.get(tag, 100):
                above |= cv2.dilate(m, k)
        free = (mine > 0) & (above == 0)
        ys, xs = np.nonzero(free)
        assert len(xs), f"no free pixel for {tag}"
        cx, cy = xs.mean(), ys.mean()
        j = int(np.argmin((xs - cx) ** 2 + (ys - cy) ** 2))
        out[tag] = (int(xs[j]), int(ys[j]))
    return out
