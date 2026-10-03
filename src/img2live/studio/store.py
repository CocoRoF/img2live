"""Per-job studio state: layer versions on disk, the grids, the source in each grid."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image

from . import ops
from .labels import GROUP_LABELS, HEAD_TAGS, LABELS, TAG_GROUP

_LOCKS: Dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def job_lock(job_id: str) -> threading.RLock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(job_id, threading.RLock())


class StudioError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


def _safe(tag: str) -> str:
    return tag.replace(" ", "_")


class Studio:
    """All access to one job's studio files.  Callers hold ``job_lock(job_id)`` while writing."""

    def __init__(self, jdir: Path, job_id: str):
        self.jdir, self.job_id = jdir, job_id
        self.root = jdir / "studio"
        idx_path = jdir / "layers" / "index.json"
        if not idx_path.exists():
            raise StudioError("이 작업에는 아직 레이어가 없습니다.", 409)
        self.index = json.loads(idx_path.read_text())
        self.n = int(self.index["canvas"])
        hs = self.index.get("head_square")
        self.head_square: Optional[Tuple[float, float, float]] = tuple(hs) if hs else None
        self._state: Optional[dict] = None
        self._src: Dict[str, np.ndarray] = {}
        self._fg: Dict[str, np.ndarray] = {}

    # ------------------------------------------------------------------ state
    def grid_of(self, tag: str) -> str:
        return "head" if (self.head_square and tag in HEAD_TAGS) else "canvas"

    def state(self) -> dict:
        if self._state is None:
            p = self.root / "state.json"
            if p.exists():
                self._state = json.loads(p.read_text())
            else:
                now = time.time()
                self._state = {"rev": 0, "next": 1, "layers": {
                    tag: {"enabled": True, "order": None, "current": "v0",
                          "versions": [{"id": "v0", "kind": "original", "note": "분해 결과", "created": now, **self._original_stats(tag)}]}
                    for tag in LABELS}}
        return self._state

    def save(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / "state.json.tmp"
        tmp.write_text(json.dumps(self.state(), ensure_ascii=False))
        tmp.replace(self.root / "state.json")

    def layer(self, tag: str) -> dict:
        L = self.state()["layers"].get(tag)
        if L is None:
            raise StudioError("알 수 없는 레이어입니다.", 404)
        return L

    def version(self, tag: str, vid: str) -> dict:
        v = next((v for v in self.layer(tag)["versions"] if v["id"] == vid), None)
        if v is None:
            raise StudioError("알 수 없는 버전입니다.", 404)
        return v

    def new_vid(self, prefix: str) -> str:
        st = self.state()
        vid = f"{prefix}{st['next']}"
        st["next"] += 1
        return vid

    # ------------------------------------------------------------------ images
    def _entry(self, tag: str) -> Optional[dict]:
        if self.grid_of(tag) == "head":
            return next((h for h in self.index.get("hires", []) if h["tag"] == tag), None)
        return next((l for l in self.index.get("layers", []) if l["tag"] == tag and "file" in l), None)

    def _original_stats(self, tag: str) -> dict:
        ent = self._entry(tag)
        if not ent:
            return {"bbox": None, "opaque": 0}
        return {"bbox": [ent["x"], ent["y"], ent["w"], ent["h"]], "opaque": int(ent.get("opaque_px", ent["w"] * ent["h"]))}

    def _original(self, tag: str) -> np.ndarray:
        n = self.n
        out = np.zeros((n, n, 4), np.uint8)
        ent = self._entry(tag)
        if ent:
            im = np.asarray(Image.open(self.jdir / ent["file"]).convert("RGBA"))
            out[ent["y"]:ent["y"] + ent["h"], ent["x"]:ent["x"] + ent["w"]] = im
        return out

    def vpath(self, tag: str, vid: str) -> Path:
        return self.root / "v" / _safe(tag) / f"{vid}.png"

    def load(self, tag: str, vid: Optional[str] = None) -> np.ndarray:
        L = self.layer(tag)
        vid = L["current"] if vid in (None, "current") else vid
        self.version(tag, vid)
        p = self.vpath(tag, vid)
        if p.exists():
            return np.asarray(Image.open(p).convert("RGBA")).copy()
        if vid == "v0":
            arr = self._original(tag)
            self.write_png(p, arr)
            return arr
        raise StudioError("버전 파일이 없습니다.", 404)

    @staticmethod
    def write_png(p: Path, arr: np.ndarray) -> None:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".tmp.png")
        Image.fromarray(arr, "RGBA").save(tmp, compress_level=3)
        tmp.replace(p)

    def add_version(self, tag: str, arr: np.ndarray, kind: str, note: str = "", make_current: bool = True, **extra) -> dict:
        vid = self.new_vid({"edit": "e", "regen": "c", "auto": "a"}.get(kind, "x"))
        self.write_png(self.vpath(tag, vid), arr)
        bb = ops.alpha_bbox(arr)
        v = {"id": vid, "kind": kind, "note": note, "created": time.time(),
             "bbox": [bb[0], bb[1], bb[2] - bb[0], bb[3] - bb[1]] if bb else None, "opaque": int((arr[..., 3] >= 16).sum()), **extra}
        L = self.layer(tag)
        L["versions"].append(v)
        if make_current:
            L["current"] = vid
        return v

    # ------------------------------------------------------------------ source in each grid
    def source(self, grid: str) -> np.ndarray:
        if grid not in self._src:
            p = self.jdir / "source_canvas.png"
            if not p.exists():
                raise StudioError("원본 이미지가 없습니다.", 404)
            if grid == "canvas":
                self._src[grid] = np.asarray(Image.open(p).convert("RGBA")).copy()
            else:
                self._src[grid] = ops.convert_grid(self.source("canvas"), "canvas", "head", self.head_square)
        return self._src[grid]

    def foreground(self, grid: str) -> np.ndarray:
        """Where the source is character (not background / padding), in the given grid."""
        if grid not in self._fg:
            if grid == "canvas":
                from ..engine.cleanup import _estimate
                src = self.source("canvas")
                a = src[..., 3]
                ys, xs = np.where(a >= 250)
                box = (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1) if len(xs) else None
                _, solid, _ = _estimate(src, box)
                self._fg[grid] = solid & (a > 16)
            else:
                m = self.foreground("canvas").astype(np.float32)
                self._fg[grid] = ops.convert_mask(m, "canvas", "head", self.head_square) > 0.5
        return self._fg[grid]

    # ------------------------------------------------------------------ thumbnails
    def thumb_path(self, tag: str, vid: str) -> Path:
        return self.root / "t" / _safe(tag) / f"{vid}.png"

    def thumb(self, tag: str, vid: Optional[str] = None, size: int = 160) -> Optional[Path]:
        L = self.layer(tag)
        vid = L["current"] if vid in (None, "current") else vid
        p = self.thumb_path(tag, vid)
        if p.exists():
            return p
        arr = self.load(tag, vid)
        bb = ops.alpha_bbox(arr)
        if bb is None:
            return None
        im = Image.fromarray(arr[bb[1]:bb[3], bb[0]:bb[2]], "RGBA")
        im.thumbnail((size, size), Image.LANCZOS)
        p.parent.mkdir(parents=True, exist_ok=True)
        im.save(p, compress_level=6)
        return p

    # ------------------------------------------------------------------ public view
    def view(self) -> dict:
        st = self.state()
        puppet = (f"/files/{self.job_id}/studio/puppet/r{st['rev']}/puppet.json" if st["rev"] > 0
                  else f"/files/{self.job_id}/puppet/puppet.json")
        from ..rig.compile import DRAW_ORDER
        layers = []
        for tag in LABELS:
            L = self.layer(tag)
            cur = next(v for v in L["versions"] if v["id"] == L["current"])
            opaque = int(cur.get("opaque", 0))
            layers.append({
                "tag": tag, "label": LABELS[tag], "group": TAG_GROUP.get(tag, "other"), "grid": self.grid_of(tag),
                "enabled": L["enabled"], "order": L["order"] if L["order"] is not None else DRAW_ORDER.get(tag, 100),
                "order_default": DRAW_ORDER.get(tag, 100), "current": L["current"],
                "versions": [{k: v for k, v in ver.items() if k not in ("bbox",)} for ver in L["versions"]],
                "bbox": cur.get("bbox"), "opaque_px": opaque, "empty": not cur.get("bbox") or opaque == 0,
            })
        return {"rev": st["rev"], "puppet": puppet, "canvas": self.n, "head_square": list(self.head_square) if self.head_square else None,
                "layers": layers, "groups": GROUP_LABELS, "tasks": [], "can_regen": False}
