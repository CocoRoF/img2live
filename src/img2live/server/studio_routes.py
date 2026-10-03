"""REST API of the studio (plan/08-studio.md §4).  The job's private id is the key, like every other file of the job."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from ..studio import service
from ..studio.store import Studio, StudioError, job_lock

JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
MAX_BODY = 12 * 1024 * 1024
IMG_CACHE = {"Cache-Control": "private, max-age=3600"}


def register(app: FastAPI, cfg, db, helpers: dict) -> None:
    is_admin, client_ip, ip_hash, worker_status = (helpers[k] for k in ("is_admin", "client_ip", "ip_hash", "worker_status"))
    def job_of(job_id: str) -> dict:
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404, "not found")
        j = db.get(job_id)
        if j is None or j["status"] == "deleted":
            raise HTTPException(404, "not found")
        if j["status"] != "done":
            raise HTTPException(409, "퍼펫이 아직 만들어지지 않았습니다. (Job is not finished.)")
        return j

    async def run(job_id: str, fn: Callable, write: bool = False):
        """Run blocking studio work in a thread, under the job's lock; studio errors become HTTP errors."""
        j = job_of(job_id)

        def go():
            with job_lock(job_id, cfg.jobs_dir / job_id):
                st = Studio(cfg.jobs_dir / job_id, job_id)
                return fn(st, j)

        try:
            return await asyncio.to_thread(go)
        except StudioError as e:
            raise HTTPException(e.status, str(e))

    async def body(request: Request) -> dict:
        raw = await request.body()
        if len(raw) > MAX_BODY:
            raise HTTPException(413, "too large")
        try:
            d = json.loads(raw or b"{}")
        except ValueError:
            raise HTTPException(400, "json required")
        if not isinstance(d, dict):
            raise HTTPException(400, "object required")
        return d

    def task_view(t: dict) -> dict:
        p = t.get("params_json") or {}
        r = t.get("result_json") or {}
        return {"id": t["id"], "kind": t["kind"], "status": t["status"], "progress": t["progress"], "message": t["message"],
                "tags": p.get("tags", []), "seed": r.get("seed") or p.get("seed"), "steps": p.get("steps"),
                "created_at": t["created_at"], "finished_at": t["finished_at"], "error": t["error"], "result": r or None}

    def answer(st: Studio) -> dict:
        v = st.view()
        v["dirty"] = bool(st.state().get("dirty"))
        v["tasks"] = [task_view(t) for t in db.tasks_for_job(st.job_id)]
        w = worker_status()
        v["can_regen"] = bool(w.get("alive"))
        return v

    @app.get("/api/jobs/{job_id}/studio")
    async def studio_state(job_id: str):
        return await run(job_id, lambda st, j: answer(st))

    @app.get("/api/jobs/{job_id}/studio/layer/{tag}/image")
    async def studio_layer_image(job_id: str, tag: str, v: str = "current"):
        def f(st, j):
            st.load(tag, v)  # materialises v0 on first use
            vid = st.layer(tag)["current"] if v == "current" else v
            return st.vpath(tag, vid)
        return FileResponse(await run(job_id, f), media_type="image/png", headers=IMG_CACHE)

    @app.get("/api/jobs/{job_id}/studio/layer/{tag}/thumb")
    async def studio_layer_thumb(job_id: str, tag: str, v: str = "current"):
        p = await run(job_id, lambda st, j: st.thumb(tag, v))
        if p is None:
            raise HTTPException(404, "empty layer")
        return FileResponse(p, media_type="image/png", headers=IMG_CACHE)

    @app.get("/api/jobs/{job_id}/studio/source")
    async def studio_source(job_id: str, grid: str = "canvas"):
        if grid not in ("canvas", "head"):
            raise HTTPException(400, "grid must be canvas or head")

        def f(st, j):
            if grid == "canvas":
                return st.jdir / "source_canvas.png"
            p = st.root / "source_head.png"
            if not p.exists():
                st.write_png(p, st.source("head"))
            return p
        return FileResponse(await run(job_id, f), media_type="image/png", headers=IMG_CACHE)

    @app.post("/api/jobs/{job_id}/studio/layer/{tag}/edit")
    async def studio_edit(job_id: str, tag: str, request: Request):
        payload = await body(request)

        def f(st, j):
            service.edit(st, tag, payload, j.get("prompt") or "")
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.post("/api/jobs/{job_id}/studio/layer/{tag}/select")
    async def studio_select(job_id: str, tag: str, request: Request):
        payload = await body(request)

        def f(st, j):
            service.select(st, tag, str(payload.get("version", "")), j.get("prompt") or "", bool(payload.get("rebuild", True)))
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.post("/api/jobs/{job_id}/studio/layer/{tag}/flags")
    async def studio_flags(job_id: str, tag: str, request: Request):
        payload = await body(request)

        def f(st, j):
            service.flags(st, tag, payload, j.get("prompt") or "")
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.delete("/api/jobs/{job_id}/studio/layer/{tag}/version/{vid}")
    async def studio_delete_version(job_id: str, tag: str, vid: str):
        def f(st, j):
            service.delete_version(st, tag, vid)
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.post("/api/jobs/{job_id}/studio/rebuild")
    async def studio_rebuild(job_id: str):
        def f(st, j):
            st.state()
            service.rebuild(st, j.get("prompt") or "")
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.post("/api/jobs/{job_id}/studio/reset")
    async def studio_reset(job_id: str):
        def f(st, j):
            service.reset(st, j.get("prompt") or "")
            return answer(st)
        return {"ok": True, "state": await run(job_id, f, write=True)}

    @app.post("/api/jobs/{job_id}/studio/regen")
    async def studio_regen(job_id: str, request: Request):
        """Ask the GPU worker to run the model again for some layers; the results arrive as candidates."""
        payload = await body(request)
        j = job_of(job_id)
        from ..studio.labels import LABELS
        tags = payload.get("tags")
        if not isinstance(tags, list) or not tags or not all(isinstance(t, str) and t in LABELS for t in tags):
            raise HTTPException(400, "다시 생성할 레이어를 골라 주세요.")
        tags = list(dict.fromkeys(tags))
        if not worker_status().get("alive"):
            raise HTTPException(503, "GPU 작업기가 준비 중입니다. 잠시 후 다시 시도해 주세요. (The GPU worker is not ready yet.)")
        admin = is_admin(request)
        ih = ip_hash(client_ip(request))
        if not admin:
            import time as _t
            if cfg.regen_per_ip_per_day > 0 and db.recent_tasks_by_ip(ih, _t.time() - 86400) >= cfg.regen_per_ip_per_day:
                raise HTTPException(429, f"하루 {cfg.regen_per_ip_per_day}번까지 다시 생성할 수 있습니다. (Daily limit reached.)")
            if db.active_tasks() >= cfg.max_queue:
                raise HTTPException(429, "대기열이 가득 찼습니다. 잠시 후 다시 시도해 주세요. (The queue is full.)")
        if db.active_tasks(job_id) >= 1:
            raise HTTPException(409, "이 퍼펫은 이미 다시 생성 중입니다. 끝난 뒤 다시 눌러 주세요. (A regeneration is already running.)")
        try:
            seed = payload.get("seed")
            seed = None if seed in (None, "", "auto") else int(seed) % (2**31)
            steps = max(10, min(60, int(payload.get("steps") or cfg.steps)))
        except (TypeError, ValueError):
            raise HTTPException(400, "시드와 스텝은 숫자여야 합니다.")
        import secrets as _s
        tid = _s.token_urlsafe(10)
        db.create_task(tid, job_id, {"tags": tags, "seed": seed, "steps": steps}, ih)
        return {"ok": True, "task": task_view(db.get_task(tid))}
