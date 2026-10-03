"""Partial regeneration (studio): run the model again for some layers of a finished job and store the results as
candidate versions - never applied automatically."""
from __future__ import annotations

import logging
import secrets
import time

import numpy as np
from PIL import Image

from ..engine.cleanup import clean_result
from ..engine.decompose import head_to_canvas
from ..engine.fidelity import CANVAS_PARTS, HEAD_PARTS, refine_canvas, refine_head
from ..engine.matting import cutout_plain_background
from ..studio.labels import HEAD_TAGS, LABELS
from ..studio.service import as_result
from ..studio.store import Studio, job_lock

log = logging.getLogger("img2live.regen")


def process_regen(task: dict, cfg, db, engine) -> None:
    tid, jid = task["id"], task["job_id"]
    p = task.get("params_json") or {}
    job = db.get(jid)
    if job is None or job["status"] == "deleted":
        db.update_task(tid, status="failed", error="이 퍼펫이 삭제되었습니다.", finished_at=time.time())
        return
    jdir = cfg.jobs_dir / jid
    tags = [t for t in p.get("tags", []) if t in LABELS]
    seed = int(p.get("seed") or secrets.randbelow(2**31))
    steps = int(p.get("steps") or cfg.steps)

    def upd(frac: float, msg: str) -> None:
        db.update_task(tid, progress=round(float(frac), 4), message=msg)

    t0 = time.time()
    with job_lock(jid, jdir):
        st = Studio(jdir, jid)
        n, hs = st.n, st.head_square
    rgba = np.asarray(Image.open(jdir / "source.png").convert("RGBA"), dtype=np.uint8).copy()
    if cfg.cutout_bg:
        rgba, _ = cutout_plain_background(rgba)
    upd(0.03, "모델에 넣는 중")
    imgs = engine.regen(rgba, tags, resolution=n, steps=steps, seed=seed, head_square=hs,
                        progress=lambda stage, frac, msg: upd(0.05 + 0.8 * frac, msg))
    upd(0.88, "정리하고 소스와 맞춰 보는 중")
    gen_s = time.time() - t0

    # clean the new layers the way the first run did, against the layers as they are now
    with job_lock(jid, jdir):
        res = as_result(Studio(jdir, jid))
    for tag, arr in imgs.items():
        if tag in HEAD_TAGS and hs:
            res.head_hires[tag] = arr
            res.layers[tag] = head_to_canvas(arr, hs, n)
        else:
            res.layers[tag] = arr
    rep = clean_result(res)
    # the model sometimes dumps the background (or half the character) into one layer: such a candidate is not offered
    dropped = [t for t in imgs if t in rep.severe]
    for t in dropped:
        log.warning("regen %s: dropping the %s candidate (leak)", tid, t)
    elig = [t for t in imgs if t in HEAD_PARTS and t in res.head_hires]
    if elig:
        refine_head(res, eligible=elig)
    can = [t for t in imgs if t in CANVAS_PARTS and t not in HEAD_TAGS]
    if can:
        refine_canvas(res, eligible=can)

    made = []
    with job_lock(jid, jdir):
        st = Studio(jdir, jid)
        for tag in imgs:
            if tag in dropped:
                continue
            arr = res.head_hires.get(tag) if (tag in HEAD_TAGS and hs) else res.layers.get(tag)
            if arr is None or not (arr[..., 3] >= 16).any():
                continue  # the model left this slot empty (no tail on this character, ...)
            v = st.add_version(tag, arr, "regen", note=f"시드 {seed}", make_current=False, seed=seed, steps=steps, task=tid,
                               requested=tag in tags)
            made.append({"tag": tag, "version": v["id"], "requested": tag in tags})
        st.save()
    db.update_task(tid, status="done", progress=1.0, message="완료", finished_at=time.time(),
                   result_json={"tags": [m["tag"] for m in made if m["requested"]], "versions": made, "dropped": dropped, "seed": seed, "steps": steps,
                                "generate_s": round(gen_s, 1), "total_s": round(time.time() - t0, 1)})
    log.info("regen %s for job %s: %s seed %s in %.1fs", tid, jid, [m["tag"] for m in made], seed, time.time() - t0)
