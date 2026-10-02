# img2live

**One illustration + a prompt → an animatable 2D puppet you can view in the browser.**
일러스트 1장과 프롬프트를 올리면 브라우저에서 바로 움직여 볼 수 있는 2D 퍼펫(Live2D 류)을 만드는 웹 서비스입니다.

> **Status: under active construction.** The research and plan are done; the engine, rig compiler,
> web viewer and service are landing in the following commits. Nothing here is a finished product yet.

## What it does (target: "Tier 1")

1. **Decompose** the illustration into ~20 semantic RGBA layers (hair front/back, face, eyes, brows, nose,
   mouth, ears, neck, clothes, arms, legs, shoes …) with the hidden parts inpainted — our own
   implementation of the method from *See-through* (arXiv:2602.03749), see [NOTICE](NOTICE).
2. **Rig** the layers automatically: head turn, blink, eye gaze, breathing, hair sway, idle motion.
3. **View** every result in the browser: layers, composite, mesh, live puppet, downloads.

Honest limits: this is a Tier-1 auto-rig (no professional-grade rigging), works best on a single, mostly
frontal, full-body or bust-up anime-style character, and every puppet ships with a capability report that says
what could and could not be rigged.

## Documents

| | |
|---|---|
| [plan/00-master-plan.md](plan/00-master-plan.md) | conclusions, decisions, roadmap, risks |
| [plan/01-see-through-analysis.md](plan/01-see-through-analysis.md) | analysis of the See-through method, code and licences |
| [plan/02-generative-models.md](plan/02-generative-models.md) | which current generative models can do which pipeline step |
| [plan/03-rigging-and-runtime-design.md](plan/03-rigging-and-runtime-design.md) | rig representation, compiler, runtime, QA |
| [plan/04-format-and-legal.md](plan/04-format-and-legal.md) | Live2D file-format feasibility, licences, safety |
| [plan/05-service-architecture.md](plan/05-service-architecture.md) | service, GPU, cost |
| [plan/06-evaluation.md](plan/06-evaluation.md) | benchmark and metrics plan |
| [plan/07-m0-measurements.md](plan/07-m0-measurements.md) | first measurements on an RTX 5070 |
| [research/](research/) | raw research reports with sources |

Trust tags used in the docs: **(V)** verified at the primary source, **(V†)** verified via a summary, **(U)** estimate / unverified.
Legal remarks are research notes, not legal advice.

## Licence and attribution

Apache-2.0, see [LICENSE](LICENSE). The engine contains code derived from
[See-through](https://github.com/shitagaki-lab/see-through) (Apache-2.0), see [NOTICE](NOTICE).
Model weights are **not** part of this repository: they are downloaded at runtime under the
CreativeML Open RAIL++-M licence family, whose use restrictions are passed on in the service's Terms of Use.

img2live is an independent project, not affiliated with Live2D Inc. or the See-through authors.
It does not use or redistribute the Cubism SDK/Core.
