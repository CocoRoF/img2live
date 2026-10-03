"""GPU worker: claims queued jobs one at a time and runs the pipeline.

Run with ``python -m img2live.worker.main``.  A CUDA failure exits the process (non-zero) so the container
restarts with a fresh CUDA context instead of continuing on a damaged one.
"""
from __future__ import annotations

import json
import logging
import shutil
import signal
import sys
import threading
import time

from ..config import get_settings
from ..db import DB
from .pipeline import JobError, fail_job, process_job
from .regen import process_regen

log = logging.getLogger("img2live.worker")


def make_engine(cfg):
    if cfg.engine == "fake":
        from ..engine.fake import FakeDecomposer

        return FakeDecomposer(), {"engine": "fake (synthetic character)"}
    from ..engine.decompose import Decomposer

    eng = Decomposer(quant=cfg.quant, group_offload=cfg.group_offload)
    return eng, {"engine": "layerdiff3d", "repo": eng.repo, "quant": cfg.quant, "group_offload": cfg.group_offload}


def release_gpu_cache() -> None:
    """Give PyTorch's cached blocks back between jobs (keeps idle VRAM low and fragmentation down)."""
    try:
        import gc

        import torch

        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def gpu_info() -> dict:
    try:
        import torch

        if not torch.cuda.is_available():
            return {}
        free, total = torch.cuda.mem_get_info()
        return {"name": torch.cuda.get_device_name(0), "total_mb": round(total / 2**20), "free_mb": round(free / 2**20)}
    except Exception:  # noqa: BLE001
        return {}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    cfg = get_settings()
    db = DB(cfg.db_path)
    state = {"model_loaded": False, "busy": None, "done": 0, "stop": False, "error": None}
    hb_path = cfg.data_dir / "worker.json"

    def heartbeat():
        while not state["stop"]:
            try:
                hb_path.write_text(json.dumps({"ts": time.time(), "model_loaded": state["model_loaded"], "busy": state["busy"],
                                               "jobs_done": state["done"], "gpu": gpu_info() if state["model_loaded"] else {},
                                               "error": state["error"]}))
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)

    threading.Thread(target=heartbeat, daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: state.update(stop=True))

    engine, info = make_engine(cfg)
    log.info("loading engine: %s", info)
    try:
        engine.load()
    except Exception as e:  # noqa: BLE001
        state["error"] = f"engine load failed: {e}"
        log.exception("engine load failed")
        time.sleep(15)
        return 2
    state["model_loaded"] = True
    n = db.requeue_stale()
    if n:
        log.warning("requeued %d jobs left running by a previous worker", n)
    n = db.requeue_stale_tasks()
    if n:
        log.warning("requeued %d studio tasks left running by a previous worker", n)
    last_clean = 0.0
    while not state["stop"]:
        task = db.claim_next_task()  # a layer regeneration is short and someone is watching it: it goes first
        if task is not None:
            state["busy"] = "task " + task["id"]
            log.info("studio task %s started (job %s)", task["id"], task["job_id"])
            try:
                process_regen(task, cfg, db, engine)
            except Exception as e:  # noqa: BLE001
                log.exception("studio task %s failed", task["id"])
                db.update_task(task["id"], status="failed", error=f"다시 생성하지 못했습니다: {str(e)[:300]}", finished_at=time.time())
                if "CUDA" in repr(e) or "cuda" in repr(e) or "out of memory" in repr(e).lower():
                    state["error"] = "CUDA error; restarting worker"
                    state["stop"] = True
                    time.sleep(1)
                    return 3
            finally:
                state["busy"] = None
                release_gpu_cache()
            continue
        job = db.claim_next()
        if job is None:
            if time.time() - last_clean > 600:
                last_clean = time.time()
                for jid in db.expired():
                    shutil.rmtree(cfg.jobs_dir / jid, ignore_errors=True)
                    db.mark_deleted(jid)
                    log.info("expired job %s deleted", jid)
            time.sleep(2)
            continue
        state["busy"] = job["id"]
        log.info("job %s started (res %s)", job["id"], job["resolution"])
        try:
            process_job(job, cfg, db, engine, info)
        except Exception as e:  # noqa: BLE001
            log.exception("job %s failed", job["id"])
            fail_job(job, db, e, cfg)
            if not isinstance(e, JobError) and ("CUDA" in repr(e) or "cuda" in repr(e) or "out of memory" in repr(e).lower()):
                state["error"] = "CUDA error; restarting worker"
                state["stop"] = True
                time.sleep(1)
                return 3
        finally:
            state["busy"] = None
            state["done"] += 1
            release_gpu_cache()
    return 0


if __name__ == "__main__":
    sys.exit(main())
