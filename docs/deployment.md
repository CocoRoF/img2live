# Deployment notes

Reference deployment: one Linux host with a single NVIDIA GPU, Docker Compose, Cloudflare Tunnel in front.

```
Cloudflare (TLS, WAF) ──tunnel──► 127.0.0.1:58600  api (FastAPI)  ──SQLite WAL + files──  worker (GPU)
                                                   └ safety gate (onnxruntime, CPU)
```

* `deploy/docker-compose.yml` builds two images: `api` (no torch) and `worker` (torch 2.8 / CUDA 12.8). They share
  `${IMG2LIVE_DATA_DIR}` (database, jobs, model caches).
* The worker writes `worker.json` (heartbeat). The API refuses uploads while the worker is not alive and shows the
  state on the front page. A CUDA error makes the worker exit so Docker restarts it with a clean context.
* **The GPU must belong to this service.** A CUDA fault on a GPU shared with other workloads can wedge the device
  (see plan/07). The default NF4 + group-offload setup needs ~8.6 GB of VRAM at 1280 px.
* Retention: jobs are deleted `IMG2LIVE_RETENTION_HOURS` after finishing (the worker sweeps every 10 minutes);
  users can delete earlier from the result page.
* Abuse controls: per-IP daily limit (IPs are stored only as salted hashes), queue cap, upload size/pixel caps,
  safety gate, optional invite code (`IMG2LIVE_ACCESS_CODE`), strict CSP, private capability URLs.
* Blocklist: put SHA-256 hashes (one per line) into `${IMG2LIVE_DATA_DIR}/blocklist.txt` to refuse exact files.

## Update

```bash
git pull && docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
```

## Admin mode

Set `IMG2LIVE_ADMIN_PASSWORD` in `deploy/.env` (never commit it).  On any page press **Alt+Shift+M**, enter the password and you
are signed in (signed cookie, 30 days): no per-IP daily limit, no queue cap, and `/admin` lists every job that still exists
(thumbnails, search, status filter, delete).  Wrong passwords are throttled (5 per 15 minutes per IP).  With the variable
empty, admin mode is off.  Operator access to all jobs is disclosed in the terms page.

Static assets are referenced with a content hash (`?v=`) and `/static` revalidates, so a CDN in front cannot serve stale
scripts or styles after a deploy.
