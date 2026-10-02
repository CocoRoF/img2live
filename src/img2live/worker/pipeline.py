"""One job: decompose -> export layers -> rig -> QA -> package."""
from __future__ import annotations

import json
import logging
import platform
import time
import traceback
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from .. import __version__
from ..config import Settings
from ..db import DB
from ..engine.cleanup import clean_result
from ..engine.types import DecomposeResult
from ..rig.compile import compile_puppet
from ..rig.layers import build_layers
from ..rig.spec import parse_prompt
from . import exports

log = logging.getLogger("img2live.worker")


class JobError(Exception):
    """A failure whose message is safe and useful to show to the user."""


def process_job(job: dict, cfg: Settings, db: DB, engine, engine_info: dict) -> None:
    jid = job["id"]
    jdir = cfg.jobs_dir / jid
    t_job = time.time()
    timings: dict = {}

    def upd(stage: str, progress: float, message: str = "", **kw):
        db.update(jid, stage=stage, progress=round(float(progress), 4), message=message, **kw)

    src = Image.open(jdir / "source.png").convert("RGBA")
    rgba = np.asarray(src, dtype=np.uint8).copy()

    # ---- 1. decomposition (GPU)
    upd("decompose", 0.01, "loading / preparing")

    attempts = []
    res: DecomposeResult = None  # type: ignore[assignment]
    cleanup = None
    for attempt in range(1 + max(0, cfg.retries)):
        seed = (int(job["seed"]) + attempt * 7919) % (2**31)
        base = 0.02 if attempt == 0 else 0.30

        def cb(stage, frac, msg, _b=base, _a=attempt):
            upd("decompose", _b + (0.82 - _b) * frac, (f"retry {_a}: " if _a else "") + msg)

        r = engine.run(rgba, resolution=int(job["resolution"]), steps=cfg.steps, seed=seed, progress=cb)
        cl = clean_result(r)
        attempts.append({"seed": seed, "severe": list(cl.severe), "leaks": {k: round(v, 3) for k, v in cl.leaks.items()},
                         "decompose_s": round(r.timings.get("total_s", 0.0), 1)})
        better = res is None or len(cl.severe) < len(cleanup.severe)
        if better:
            res, cleanup = r, cl
        if not cl.severe:
            break
        log.warning("job %s attempt %d: severe leak in %s%s", jid, attempt, cl.severe, " - retrying" if attempt < cfg.retries else "")
        upd("decompose", 0.30, f"layer leak detected in {', '.join(cl.severe)}; retrying with another seed")
    timings["decompose_attempts"] = len(attempts)
    timings.update({f"decompose_{k}": round(v, 2) for k, v in res.timings.items()})
    nonempty = [t for t, a in res.layers.items() if t != "head" and (a[..., 3] > 16).any()]
    if len(nonempty) < 4 or "face" not in nonempty:
        raise JobError("캐릭터를 분해하지 못했습니다(레이어가 거의 비어 있음). 정면의 캐릭터가 또렷한 이미지를 시도해 주세요. "
                       "(Could not decompose a character from this image.)")

    # ---- 2. layer exports
    t0 = time.time()
    upd("layers", 0.83, "writing layers")
    index = exports.write_layers(res, jdir)
    if res.fullpage is not None and res.fullpage[..., 3].any():
        Image.fromarray(res.fullpage, "RGBA").save(jdir / "source_canvas.png", compress_level=6)
    Image.fromarray(exports.composite(res.layers, res.canvas), "RGBA").save(jdir / "composite.png", compress_level=6)
    (jdir / "downloads").mkdir(exist_ok=True)
    try:
        exports.write_psd(res.layers, res.canvas, jdir / "downloads" / "layers.psd")
    except Exception:  # noqa: BLE001 - PSD is a convenience export
        log.exception("psd export failed")
    exports.write_fullcanvas_zip(res.layers, jdir / "downloads" / "layers.psd", jdir / "downloads" / "layers_fullcanvas.zip")
    timings["layers_s"] = round(time.time() - t0, 2)

    # ---- 3. rig
    t0 = time.time()
    upd("rig", 0.88, "building meshes and deformation keyforms")
    spec = parse_prompt(job.get("prompt") or "")
    rig_layers = build_layers(res.layers, res.head_hires, res.head_square)
    puppet, report = compile_puppet(rig_layers, spec, out_dir=str(jdir / "puppet"))
    timings["rig_s"] = round(time.time() - t0, 2)
    t0 = time.time()
    try:
        from ..rig.preview import pose_sheet

        (jdir / "qa").mkdir(exist_ok=True)
        pose_sheet(puppet, str(jdir / "puppet"), str(jdir / "qa" / "pose_sheet.png"), cell=300)
    except Exception:  # noqa: BLE001 - the sheet is a QA convenience, never fail the job for it
        log.exception("pose sheet failed")
    timings["pose_sheet_s"] = round(time.time() - t0, 2)

    # ---- 4. package + report
    upd("package", 0.97, "packaging")
    exports.zip_dir(jdir, jdir / "downloads" / "puppet.zip", ["puppet"])
    timings["total_s"] = round(time.time() - t_job, 2)
    job_report = {
        "version": __version__, "job": jid, "prompt": job.get("prompt", ""), "resolution": job["resolution"], "seed": job["seed"],
        "steps": cfg.steps, "engine": engine_info, "timings": timings, "rigSpec": spec.to_dict(),
        "capability": report["capability"], "qa": report["qa"], "decompose": {"attempts": attempts, "cleanup": cleanup.to_dict()}, "rig_stats": report["stats"], "rig_notes": report["notes"],
        "layers": {"nonempty": sorted(nonempty), "head_hires": [h["tag"] for h in index.get("hires", [])],
                   "head_square": index.get("head_square")},
        "gate": (job.get("gate_json") or {}),
        "host": {"python": platform.python_version()},
    }
    (jdir / "report.json").write_text(json.dumps(job_report, ensure_ascii=False, indent=1))
    files = exports.list_files(jdir)
    result = {
        "puppet": "puppet/puppet.json", "composite": "composite.png", "source": "source.png",
        "source_canvas": "source_canvas.png" if (jdir / "source_canvas.png").exists() else None,
        "layers_index": "layers/index.json", "report": "report.json",
        "downloads": [f for f in files if f["path"].startswith("downloads/")],
        "files": files,
    }
    db.update(jid, status="done", stage="done", progress=1.0, message="done", finished_at=time.time(),
              timings_json=timings, result_json=result)
    log.info("job %s done in %.1fs", jid, timings["total_s"])


def fail_job(job: dict, db: DB, exc: BaseException, cfg: Settings) -> None:
    jid = job["id"]
    user_msg = str(exc) if isinstance(exc, JobError) else "처리 중 내부 오류가 발생했습니다. 잠시 후 다시 시도해 주세요. (Internal error while processing.)"
    try:
        (cfg.jobs_dir / jid / "error.txt").write_text("".join(traceback.format_exception(exc)))
    except Exception:  # noqa: BLE001
        pass
    db.update(jid, status="failed", stage="failed", message="failed", error=user_msg, finished_at=time.time())
