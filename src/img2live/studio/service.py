"""Studio actions: edits, version selection, flags, reset and the puppet rebuild.  Every write goes through here."""
from __future__ import annotations

import copy
import logging
import shutil
import time
from pathlib import Path
from typing import Dict, Optional

import numpy as np
from PIL import Image

from . import ops
from .labels import HEAD_TAGS, LABELS
from .store import Studio, StudioError, job_lock

log = logging.getLogger("img2live.studio")
KEEP_REVS = 3


# ------------------------------------------------------------------ assembling the current layer set
def current_arrays(st: Studio, only_enabled: bool = False) -> Dict[str, np.ndarray]:
    out = {}
    for tag in LABELS:
        L = st.layer(tag)
        if only_enabled and not L["enabled"]:
            out[tag] = np.zeros((st.n, st.n, 4), np.uint8)
        else:
            out[tag] = st.load(tag)
    return out


def as_result(st: Studio, only_enabled: bool = False):
    """The current layers as a DecomposeResult (what the engine's cleanup/fidelity code works on)."""
    from ..engine.decompose import head_to_canvas
    from ..engine.types import DecomposeResult

    arrs = current_arrays(st, only_enabled)
    layers, hires = {}, {}
    for tag, a in arrs.items():
        if st.grid_of(tag) == "head":
            if (a[..., 3] > 0).any():
                hires[tag] = a
            layers[tag] = head_to_canvas(a, st.head_square, st.n) if (a[..., 3] > 0).any() else np.zeros_like(a)
        else:
            layers[tag] = a
    layers["head"] = np.zeros((st.n, st.n, 4), np.uint8)
    try:
        size = Image.open(st.jdir / "source.png").size
    except Exception:  # noqa: BLE001
        size = (st.n, st.n)
    return DecomposeResult(canvas=st.n, source_size=tuple(size), layers=layers, head_hires=hires, head_square=st.head_square,
                           fullpage=st.source("canvas"), source_box=(0, 0, st.n, st.n))


# ------------------------------------------------------------------ rebuild
def rebuild(st: Studio, prompt: str) -> None:
    """Recompile the puppet from the current versions (CPU, a few seconds) and bump the revision."""
    from ..engine.decompose import head_to_canvas
    from ..rig.compile import compile_puppet
    from ..rig.layers import build_layers
    from ..rig.spec import parse_prompt
    from ..thumbs import make_thumb
    from ..worker import exports

    sv = st.state()
    arrs = current_arrays(st, only_enabled=True)
    canvas_layers, hires = {}, {}
    for tag, a in arrs.items():
        if st.grid_of(tag) == "head":
            has = bool((a[..., 3] > 0).any())
            if has:
                hires[tag] = a
            canvas_layers[tag] = head_to_canvas(a, st.head_square, st.n) if has else np.zeros_like(a)
        else:
            canvas_layers[tag] = a
    layers = build_layers(canvas_layers, hires or None, st.head_square)
    if not any(l.tag == "face" for l in layers):
        raise StudioError("얼굴 레이어가 없으면 퍼펫을 만들 수 없습니다. 얼굴 레이어를 포함해 주세요.", 422)
    rev = sv["rev"] + 1
    out = st.root / "puppet" / f"r{rev}"
    overrides = {t: int(L["order"]) for t, L in sv["layers"].items() if L["order"] is not None}
    try:
        puppet, report = compile_puppet(layers, parse_prompt(prompt or ""), out_dir=str(out), order_overrides=overrides)
    except Exception as e:  # noqa: BLE001
        shutil.rmtree(out, ignore_errors=True)
        log.exception("studio rebuild failed for %s", st.job_id)
        raise StudioError(f"퍼펫을 다시 만들지 못했습니다: {e}", 422)
    # keep the job's previews in step with what the studio shows
    try:
        Image.fromarray(exports.composite(canvas_layers, st.n, overrides), "RGBA").save(st.jdir / "composite.png", compress_level=6)
        (st.jdir / "thumb.png").unlink(missing_ok=True)
        make_thumb(st.jdir)
    except Exception:  # noqa: BLE001 - previews are a convenience
        log.exception("preview refresh failed")
    sv["rev"] = rev
    sv["dirty"] = False
    st.save()
    # old revisions: keep a few so open pages can still read their textures
    revs = sorted((p for p in (st.root / "puppet").glob("r*") if p.name[1:].isdigit()), key=lambda p: int(p.name[1:]))
    for p in revs[:-KEEP_REVS]:
        shutil.rmtree(p, ignore_errors=True)


def _commit(st: Studio, before: dict, do_rebuild: bool, prompt: str) -> None:
    """Save the new state; rebuild; on failure put the old state back."""
    st.state()["dirty"] = True
    if not do_rebuild:
        st.save()
        return
    try:
        rebuild(st, prompt)
    except StudioError:
        st._state = before  # roll back (the version files stay on disk, harmless)
        st.save()
        raise


# ------------------------------------------------------------------ actions
def edit(st: Studio, tag: str, payload: dict, prompt: str) -> None:
    op = str(payload.get("op", ""))
    do_rebuild = bool(payload.get("rebuild", True))
    note = str(payload.get("note") or "")[:80]
    L = st.layer(tag)
    grid = st.grid_of(tag)
    n = st.n
    before = copy.deepcopy(st.state())
    cur = st.load(tag)
    if op in ("erase", "restore", "move") and not payload.get("mask"):
        raise StudioError("선택 영역이 필요합니다.")
    feather = float(payload.get("feather") or 0)
    m = ops.decode_mask(payload["mask"], n, min(max(feather, 0), 8)) if payload.get("mask") else None
    if m is not None and not (m > 0).any():
        raise StudioError("선택 영역이 비어 있습니다.")

    if op == "erase":
        out = ops.erase(cur, m)
        if np.array_equal(out, cur):
            raise StudioError("지울 픽셀이 없습니다. (선택 영역에 이 레이어의 내용이 없습니다.)")
        st.add_version(tag, out, "edit", note or "지우개")
    elif op == "restore":
        out = ops.restore(cur, m, st.source(grid), st.foreground(grid))
        if np.array_equal(out, cur):
            raise StudioError("채울 픽셀이 없습니다. (선택 영역의 소스가 배경이거나 이미 같은 내용입니다.)")
        st.add_version(tag, out, "edit", note or "소스로 채움")
    elif op == "move":
        to = str(payload.get("to") or "")
        if to == tag or to not in LABELS:
            raise StudioError("옮길 레이어를 골라 주세요.")
        taken = ops.take(cur, m)
        if not (taken[..., 3] > 0).any():
            raise StudioError("옮길 픽셀이 없습니다. (선택 영역에 이 레이어의 내용이 없습니다.)")
        tgt_grid = st.grid_of(to)
        moved = ops.convert_grid(taken, grid, tgt_grid, st.head_square)
        st.add_version(to, ops._over(moved, st.load(to)), "edit", note or f"'{LABELS[tag]}'에서 옮겨 옴")
        st.add_version(tag, ops.erase(cur, m), "edit", note or f"'{LABELS[to]}'(으)로 옮김")
    elif op == "fill_hole":
        out, cnt = ops.fill_holes(cur, st.source(grid), st.foreground(grid), m)
        if not cnt:
            raise StudioError("메울 구멍이 없습니다.")
        st.add_version(tag, out, "edit", note or "구멍 메우기")
    elif op == "clean":
        from ..engine.cleanup import decontaminate
        from ..engine.fidelity import refine_canvas, refine_head

        res = as_result(st)
        if grid == "head":
            res.head_hires[tag] = decontaminate(res.head_hires.get(tag, cur), reach=12)
            refine_head(res, eligible=[tag])
            out = res.head_hires[tag]
        else:
            refine_canvas(res, eligible=[tag])
            out = res.layers[tag]
        if np.array_equal(out, cur):
            raise StudioError("더 정리할 것이 없습니다.")
        st.add_version(tag, out, "auto", note or "자동 정리")
    else:
        raise StudioError("알 수 없는 편집입니다.")
    _commit(st, before, do_rebuild, prompt)


def select(st: Studio, tag: str, version: str, prompt: str, do_rebuild: bool = True) -> None:
    st.version(tag, version)
    before = copy.deepcopy(st.state())
    st.layer(tag)["current"] = version
    _commit(st, before, do_rebuild, prompt)


def flags(st: Studio, tag: str, payload: dict, prompt: str) -> None:
    L = st.layer(tag)
    before = copy.deepcopy(st.state())
    if "enabled" in payload:
        L["enabled"] = bool(payload["enabled"])
    if "order" in payload:
        o = payload["order"]
        if o is None:
            L["order"] = None
        else:
            try:
                L["order"] = max(0, min(400, int(o)))
            except (TypeError, ValueError):
                raise StudioError("순서는 정수여야 합니다.")
    _commit(st, before, bool(payload.get("rebuild", True)), prompt)


def delete_version(st: Studio, tag: str, vid: str) -> None:
    L = st.layer(tag)
    v = st.version(tag, vid)
    if v["kind"] == "original":
        raise StudioError("원본은 지울 수 없습니다.")
    if L["current"] == vid:
        raise StudioError("지금 쓰는 버전은 지울 수 없습니다. 다른 버전을 먼저 고르세요.")
    L["versions"] = [x for x in L["versions"] if x["id"] != vid]
    st.vpath(tag, vid).unlink(missing_ok=True)
    st.thumb_path(tag, vid).unlink(missing_ok=True)
    st.save()


def reset(st: Studio, prompt: str) -> None:
    before = copy.deepcopy(st.state())
    for L in st.state()["layers"].values():
        L["current"], L["enabled"], L["order"] = "v0", True, None
    _commit(st, before, True, prompt)
