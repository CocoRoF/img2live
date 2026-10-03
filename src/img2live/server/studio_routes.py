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


def register(app: FastAPI, cfg, db) -> None:
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
            with job_lock(job_id):
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

    def answer(st: Studio) -> dict:
        v = st.view()
        v["dirty"] = bool(st.state().get("dirty"))
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
        await body(request)
        job_of(job_id)
        raise HTTPException(501, "다시 생성은 아직 준비 중입니다. (Regeneration is not available yet.)")
