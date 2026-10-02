"""img2live web API (FastAPI).

Responsibilities: validate uploads, run the safety gate, enforce rate/queue limits, create jobs, report
progress (JSON + SSE), serve a job's files by capability URL, and delete on request.  The GPU work happens in
``img2live.worker`` which shares the SQLite database and the data directory with this process.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import mimetypes
import os
import re
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError

from .. import __version__
from ..config import Settings, get_settings
from ..db import DB, new_job_id
from ..rig.spec import parse_prompt
from ..safety.gate import GateConfig, SafetyGate, sha256_bytes

log = logging.getLogger("img2live.api")
STATIC_DIR = Path(__file__).resolve().parent.parent / "web" / "static"
JOB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,40}$")
ALLOWED_FORMATS = {"PNG", "JPEG", "WEBP"}
RESOLUTIONS = (1024, 1280)
MAX_SOURCE_SIDE = 3072

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": ("default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                                "style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; "
                                "worker-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"),
}


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    cfg = settings or get_settings()
    db = DB(cfg.db_path)
    gate = SafetyGate(cfg.models_dir / "hf", GateConfig(nsfw=cfg.gate_nsfw, minor_tag=cfg.gate_minor_tag,
                                                      minor_sensitive=cfg.gate_minor_sensitive, photo=cfg.gate_photo,
                                                      multi=cfg.gate_multi),
                      blocklist=cfg.data_dir / "blocklist.txt")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if cfg.gate_enabled:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _warm_gate)  # load in the background; uploads wait on it
        yield

    def _warm_gate():
        try:
            gate.load()
        except Exception:  # noqa: BLE001
            log.exception("safety gate failed to load")

    app = FastAPI(title="img2live", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.cfg, app.state.db, app.state.gate = cfg, db, gate

    @app.middleware("http")
    async def headers(request: Request, call_next):
        resp = await call_next(request)
        for k, v in SECURITY_HEADERS.items():
            resp.headers.setdefault(k, v)
        return resp

    # ------------------------------------------------------------------ helpers
    def client_ip(request: Request) -> str:
        if cfg.trust_proxy:
            ip = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if ip:
                return ip
        return request.client.host if request.client else "unknown"

    def ip_hash(ip: str) -> str:
        return hashlib.sha256((cfg.ip_salt + "|" + ip).encode()).hexdigest()[:24]

    def eta_seconds() -> float:
        d = db.recent_durations(5)
        return sum(d) / len(d) if d else 420.0

    def worker_status() -> dict:
        p = cfg.data_dir / "worker.json"
        try:
            w = json.loads(p.read_text())
            w["age_s"] = round(time.time() - w.get("ts", 0), 1)
            w["alive"] = w["age_s"] < 90
            return w
        except Exception:  # noqa: BLE001
            return {"alive": False, "age_s": None}

    def public_job(j: dict) -> dict:
        out = {k: j.get(k) for k in ("id", "status", "stage", "progress", "message", "prompt", "resolution", "created_at",
                                     "started_at", "finished_at", "delete_after", "error")}
        out["timings"] = j.get("timings_json") or {}
        out["result"] = j.get("result_json") or None
        g = j.get("gate_json") or {}
        out["gate"] = {"ratings": g.get("ratings"), "top_tags": g.get("top_tags")} if g else None
        if j["status"] in ("queued", "running"):
            pos = db.queue_position(j["id"]) or 0
            avg = eta_seconds()
            out["queue_position"] = pos
            # running: what is left of this job; queued: every job ahead (incl. the running one) plus this one
            out["eta_seconds"] = round(avg * (1 - (j.get("progress") or 0))) if j["status"] == "running" else round(avg * (pos + 1))
        return out

    # ------------------------------------------------------------------ pages
    def page(name: str):
        async def _p():
            return FileResponse(STATIC_DIR / name, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache, no-transform"})
        return _p

    app.get("/", include_in_schema=False)(page("index.html"))
    app.get("/terms", include_in_schema=False)(page("terms.html"))

    @app.get("/j/{job_id}", include_in_schema=False)
    async def job_page(job_id: str):
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        return FileResponse(STATIC_DIR / "job.html", media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache, no-transform"})

    FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#5b4bdb"/>'
               '<circle cx="32" cy="27" r="13" fill="#fff"/><circle cx="27" cy="26" r="2.6" fill="#5b4bdb"/><circle cx="37" cy="26" r="2.6" fill="#5b4bdb"/>'
               '<path d="M16 54c2-10 9-14 16-14s14 4 16 14z" fill="#fff"/></svg>')

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon_svg():
        return PlainTextResponse(FAVICON, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/favicon.ico", include_in_schema=False)
    async def favicon_ico():
        return PlainTextResponse(FAVICON, media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/robots.txt", include_in_schema=False)
    async def robots():
        return PlainTextResponse("User-agent: *\nDisallow: /j/\nDisallow: /files/\nDisallow: /api/\n")

    # ------------------------------------------------------------------ API
    @app.get("/api/health")
    async def health():
        w = worker_status()
        return {"ok": True, "version": __version__, "worker": w, "queue": db.active_count(), "gate_ready": gate.session is not None}

    @app.get("/api/info")
    async def info():
        w = worker_status()
        return {"version": __version__, "limits": {"max_upload_mb": cfg.max_upload_mb, "max_pixels": cfg.max_pixels,
                                                    "min_side": cfg.min_side, "per_ip_per_day": cfg.per_ip_per_day,
                                                    "retention_hours": cfg.retention_hours},
                "resolutions": list(RESOLUTIONS), "queue": db.active_count(), "max_queue": cfg.max_queue,
                "eta_seconds": round(eta_seconds()), "worker_alive": w.get("alive", False),
                "worker_model_loaded": w.get("model_loaded", False), "access_code_required": bool(cfg.access_code),
                "contact_url": cfg.contact_url}

    @app.post("/api/parse-prompt")
    async def parse(prompt: str = Form("")):
        return parse_prompt(prompt).to_dict()

    @app.post("/api/jobs")
    async def create_job(request: Request, image: UploadFile = File(...), prompt: str = Form(""),
                         resolution: int = Form(1280), access_code: str = Form(""), owner_code: str = Form(""),
                         consent: str = Form("")):
        if consent != "yes":
            raise HTTPException(400, "약관 동의가 필요합니다. (You must accept the terms.)")
        # the operator's code lifts the per-IP daily limit (the queue cap and everything else still apply)
        owner = bool(cfg.owner_code) and secrets.compare_digest(owner_code.encode(), cfg.owner_code.encode())
        if cfg.access_code and not owner and not secrets.compare_digest(access_code, cfg.access_code):
            raise HTTPException(403, "접근 코드가 올바르지 않습니다. (Invalid access code.)")
        if resolution not in RESOLUTIONS:
            raise HTTPException(400, f"resolution must be one of {RESOLUTIONS}")
        worker = worker_status()
        if not worker.get("alive"):
            raise HTTPException(503, "GPU 작업기가 아직 준비 중입니다. 잠시 후 다시 시도해 주세요. (The GPU worker is not ready yet.)")
        ip = client_ip(request)
        ih = ip_hash(ip)
        if db.active_count() >= cfg.max_queue:
            raise HTTPException(429, f"대기열이 가득 찼습니다({cfg.max_queue}). 잠시 후 다시 시도해 주세요. (The queue is full.)")
        if not owner and cfg.per_ip_per_day > 0 and db.recent_by_ip(ih, time.time() - 86400) >= cfg.per_ip_per_day:
            raise HTTPException(429, f"하루 {cfg.per_ip_per_day}건까지 처리할 수 있습니다. (Daily limit reached.)")

        # ---- read with a hard size cap
        limit = cfg.max_upload_mb * 1024 * 1024
        buf = bytearray()
        while True:
            chunk = await image.read(1024 * 1024)
            if not chunk:
                break
            buf += chunk
            if len(buf) > limit:
                raise HTTPException(413, f"파일이 너무 큽니다(최대 {cfg.max_upload_mb}MB). (File too large.)")
        raw = bytes(buf)
        if len(raw) < 1024:
            raise HTTPException(400, "이미지가 비어 있거나 너무 작습니다. (Empty image.)")

        # ---- decode defensively and re-encode (drops metadata, normalises format)
        try:
            Image.MAX_IMAGE_PIXELS = cfg.max_pixels * 2
            probe = Image.open(io.BytesIO(raw))
            fmt = probe.format
            if fmt not in ALLOWED_FORMATS:
                raise HTTPException(400, "PNG / JPEG / WebP 만 지원합니다. (Unsupported format.)")
            w, h = probe.size
            if w * h > cfg.max_pixels:
                raise HTTPException(400, f"해상도가 너무 큽니다(최대 {cfg.max_pixels // 1_000_000}MP). (Image too large.)")
            if min(w, h) < cfg.min_side:
                raise HTTPException(400, f"이미지가 너무 작습니다(짧은 변 최소 {cfg.min_side}px). (Image too small.)")
            img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert("RGBA")
        except HTTPException:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            raise HTTPException(400, "이미지를 읽을 수 없습니다. (Cannot decode the image.)")
        if max(img.size) > MAX_SOURCE_SIDE:
            s = MAX_SOURCE_SIDE / max(img.size)
            img = img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)

        # ---- safety gate (CPU, before any GPU time is spent)
        gate_dict: dict = {"enabled": cfg.gate_enabled}
        if cfg.gate_enabled:
            try:
                res = await asyncio.get_running_loop().run_in_executor(None, gate.check, img, sha256_bytes(raw))
            except Exception:  # noqa: BLE001
                log.exception("gate error")
                raise HTTPException(503, "안전 검사를 수행할 수 없습니다. 잠시 후 다시 시도해 주세요. (Safety check unavailable.)")
            gate_dict = {"enabled": True, **res.to_dict()}
            if not res.allowed:
                log.info("gate rejected: %s %s", res.reason, res.flagged)
                raise HTTPException(422, res.message)

        spec = parse_prompt(prompt)
        job_id = new_job_id()
        jdir = cfg.jobs_dir / job_id
        jdir.mkdir(parents=True, exist_ok=False)
        img.save(jdir / "source.png", compress_level=6)
        db.create(job_id, spec.raw_prompt, resolution, secrets.randbelow(2**31), ih, gate_dict, cfg.retention_hours)
        return {"id": job_id, "url": f"/j/{job_id}", "queue": db.active_count(), "rigSpec": spec.to_dict()}

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        j = db.get(job_id)
        if j is None or j["status"] == "deleted":
            raise HTTPException(404, "작업을 찾을 수 없습니다(삭제되었거나 만료됨). (Job not found.)")
        return public_job(j)

    @app.get("/api/jobs/{job_id}/events")
    async def job_events(job_id: str, request: Request):
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        if db.get(job_id) is None:
            raise HTTPException(404)

        async def gen():
            last = None
            ticks = 0
            while True:
                if await request.is_disconnected():
                    return
                j = db.get(job_id)
                if j is None or j["status"] == "deleted":
                    yield "event: gone\ndata: {}\n\n"
                    return
                pj = public_job(j)
                key = json.dumps(pj, sort_keys=True, default=str)
                if key != last:
                    last = key
                    yield f"data: {json.dumps(pj, default=str)}\n\n"
                elif ticks % 15 == 0:
                    yield ": keepalive\n\n"
                if j["status"] in ("done", "failed"):
                    return
                ticks += 1
                await asyncio.sleep(1.0)

        return StreamingResponse(gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str):
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        j = db.get(job_id)
        if j is None or j["status"] == "deleted":
            raise HTTPException(404)
        if j["status"] == "running":
            raise HTTPException(409, "처리 중인 작업은 끝난 뒤 삭제할 수 있습니다. (Job is running.)")
        _rmtree(cfg.jobs_dir / job_id)
        db.mark_deleted(job_id)
        return {"deleted": True}

    @app.get("/files/{job_id}/{path:path}")
    async def job_file(job_id: str, path: str):
        if not JOB_ID_RE.match(job_id):
            raise HTTPException(404)
        j = db.get(job_id)
        if j is None or j["status"] == "deleted":
            raise HTTPException(404)
        base = (cfg.jobs_dir / job_id).resolve()
        target = (base / path).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404)
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype in ("text/html", "image/svg+xml", "application/xhtml+xml"):
            ctype = "application/octet-stream"
        disp = "attachment" if target.suffix.lower() in (".zip", ".psd") else "inline"
        return FileResponse(target, media_type=ctype, headers={
            "Cache-Control": "private, max-age=600", "Content-Disposition": f'{disp}; filename="{target.name}"'})

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


def _rmtree(p: Path) -> None:
    import shutil

    shutil.rmtree(p, ignore_errors=True)


app = None  # created lazily by uvicorn factory: `uvicorn img2live.server.app:create_app --factory`
