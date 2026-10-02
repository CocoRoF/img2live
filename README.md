# img2live

**One illustration + a prompt → an animatable 2D puppet you can view in the browser.**
일러스트 1장과 프롬프트를 올리면 레이어로 분해하고 자동 리깅해서, 브라우저에서 바로 움직여 볼 수 있는 2D 퍼펫(Live2D 류)을 만드는 웹 서비스입니다.

Live demo: **https://imglive.memo-ora.com** (single GPU, small queue — see the limits on the page)

```
upload ─► safety gate ─► layer decomposition ─► rig compiler ─► QA ─► web viewer
 (PNG/JPG)  (WD tagger)   (LayerDiff3D, GPU)    (meshes, keyforms,    (flip checks,   (WebGL2, sliders,
                                                 physics, motions)     pose sheet)     layers, report, files)
```

## What you get

* **~20 semantic RGBA layers** — hair front/back, face, eyes (white / iris / lashes), brows, nose, mouth, ears, neck,
  clothes, arms, legs, shoes … with hidden parts inpainted. Our own implementation of the method from
  [*See-through* (arXiv:2602.03749)](https://arxiv.org/abs/2602.03749); face parts come from a separate
  **high-resolution head pass** (the original shrinks it back and discards the detail).
* **An auto-rigged puppet** (`puppet.json` + textures, see [docs/puppet-format.md](docs/puppet-format.md)):
  head yaw/pitch/roll (cylinder-dome model), blink / wink, gaze, brows, mouth open, breathing, body sway,
  hair & tail physics, idle motion — all analytic and deterministic, no learning.
* **Everything is inspectable**: live viewer, layers, source-vs-recomposite, a server-rendered pose sheet, a
  *capability report* (what works, what is `degraded`, what is `unavailable`), numeric QA, PSD + zip downloads.

## Honest limits

This is a **Tier-1 auto-rig**: no professional-grade rigging, best on a single, mostly frontal anime-style character.
No closed-eye or vowel mouth art is generated yet — blinking closes the lashes onto a curve and the mouth is a
template overlay (both reported as `degraded`). Decomposition can fail on hard inputs (merged ponytails, missing
glasses/animal ears …). Details and measurements: [plan/07-m0-measurements.md](plan/07-m0-measurements.md).

## Run it

```bash
cp deploy/.env.example deploy/.env          # set IMG2LIVE_IP_SALT, IMG2LIVE_DATA_DIR, ...
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
# API on 127.0.0.1:${IMG2LIVE_PORT:-58600}
```

* The **worker** needs an NVIDIA GPU with ≥ 12 GB (default: NF4 weights, ~8.6 GB peak at 1280 px, ≈6 min/job on an RTX 5070).
  Weights (~3.8 GB) are downloaded on first start into `${IMG2LIVE_DATA_DIR}/models`.
* No GPU? `IMG2LIVE_ENGINE=fake` runs the whole stack with a synthetic character so you can try the UI and the rig.
* Put it behind a TLS reverse proxy / tunnel and set `IMG2LIVE_TRUST_PROXY=1` so rate limits see the client IP.

```bash
pip install -e ".[server,dev]" && pytest          # tests run without a GPU (synthetic engine)
```

## Repository layout

| path | |
|---|---|
| `src/img2live/engine/` | LayerDiff3D / transparent-VAE code derived from See-through (Apache-2.0) + our two-pass decomposition API |
| `src/img2live/rig/` | layers → meshes → deformation keyforms → physics/motions → QA → puppet; Python reference evaluator; software preview |
| `src/img2live/server/`, `worker/` | FastAPI app, SQLite job queue, GPU worker |
| `src/img2live/safety/` | input safety gate (WD tagger v3) |
| `src/img2live/web/static/` | pages and the WebGL2 viewer (vanilla ES modules, no build step) |
| `plan/`, `research/` | research notes, plan, first GPU measurements |
| `docs/` | puppet format |

## Licence, attribution, safety

Apache-2.0 ([LICENSE](LICENSE)). The engine contains code derived from
[See-through](https://github.com/shitagaki-lab/see-through) (Apache-2.0), see [NOTICE](NOTICE).
Model weights are **not** in this repository; they are downloaded at runtime under the CreativeML Open RAIL++-M
licence family. **A hosted service must pass those use restrictions on to its users** — the bundled
[Terms](src/img2live/web/static/terms.html) already do; keep them if you deploy this.

The upload gate (WD tagger) is best effort, not a guarantee. Results are private-link only, auto-deleted after
72 h, never used for training. img2live is independent of Live2D Inc. and of the See-through authors and does not
use the Cubism SDK/Core.
