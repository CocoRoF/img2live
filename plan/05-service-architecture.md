# 05. 웹 서비스 아키텍처 · GPU · 비용

근거: 에이전트 조사 `research/service.md`(가격표 2026-10-02 조회) + 실측(`07`). 신뢰도 표기 **(V)/(V~)/(U2)/(U)**.
**GPU 속도·VRAM 은 RTX 5070 한 장에서만 실측했고(`07`), 그 외 카드의 숫자는 README·논문 값에 외삽한 추정이다.**

---

> **실측 갱신(2026-10-02, `07`):** RTX 5070 12GB 한 장에서 LayerDiff3D(NF4, 1280px)가 **374.6초·장치 메모리 8.6GB** 로 돌았다. 같은 GPU 를 다른 운영 워크로드와 나눠 쓰는 상태에서는 여유 3.0GB 라 UNet(2.6GB)도 로드 실패했고, 깊이(Marigold) 단계에서는 GPU 폴트(Xid 31/109)가 났다. → **GPU 는 이 서비스 전용으로 쓰고, 깊이 단계는 기본 비활성**으로 둔다. 아래 비용 모델의 150초 가정은 카드에 따라 2~3배 이상 빗나갈 수 있다(5070 급 ≈6.2분/장, 그룹 오프로드 ON).

## 1. 결정 요약

| 항목 | 결정 | 이유 |
|---|---|---|
| 제어면 | 기존 방식 그대로: **FastAPI + Postgres + Redis + Next.js**, 자체 서버 docker-compose | 이미 운영 경험, GPU 불필요 |
| GPU | **scale-to-zero 서버리스 + 이식 가능한 GPU 워커 컨테이너 1개** (Modal 또는 RunPod Serverless, M0 에서 A/B 실측) | 버스트 트래픽, 자체 서버에 GPU 없음 |
| 큐/상태 | **Postgres 상태기계 + Redis 큐(RQ) + SSE**. 복잡해지면 DBOS/Hatchet(MIT, Postgres 기반) | MVP 충분. **Arq 는 maintenance only → 신규 금지** |
| 오브젝트 스토어 | **SeaweedFS(Apache-2.0)** 또는 **Cloudflare R2** | **MinIO 오픈소스는 archived** |
| 렌더러 | **WebGL2 기준**(지원 96.4%), WebGPU 는 감지 후 선택 | WebGPU 85.7%(Firefox/Safari 조건부), PixiJS v8 도 프로덕션은 WebGL 권장 |
| 서빙 금지 | ComfyUI(GPL)·RunPod worker-comfyui(AGPL)·bizarre-pose-estimator(AGPL)·Depth Anything V2 Large(CC-BY-NC) | `04` §4 |
| 상용 이미지 API | **MVP 에서 제외** (옵션 어댑터로만) | 비용보다 정책 리스크(`02`/`04`) |

## 2. 파이프라인 = 상태기계

```
UPLOAD ─► VALIDATING ─► SAFETY_CHECK ──reject──► REJECTED(사유 코드, GPU 비용 0)
                              │ pass
                          PLANNING (VLM: 전신/정면/애니 판정, 얼굴·눈·입 박스, prompt→RigSpec)
                              ▼
                        QUEUED_GPU ─► DECOMPOSING (GPU, See-through V3, ~2–3분)
                              ▼
                        REPAIRING  (CPU: 좌우 규약·앞/뒤 머리·원본 픽셀 재투영·오염 제거·언더랩)
                              ▼
                        SYNTHESIZING_VARIANTS (GPU/API 어댑터: 눈 감김·입 모양, 크롭→편집→합성→검사→재시도)
                              ▼
                        AWAITING_REVIEW  ◄── 사용자: 레이어 켜기/끄기, 지우개/복원, 좌우 분리선, 앵커 드래그, seed 재굴림, RigSpec 수정
                              ▼
                        RIGGING (CPU, 결정론) ─► QA (수치 → 렌더 시트 → VLM → 수리 ≤3라운드)
                              ▼
                        PACKAGING ─► READY (뷰어: 슬라이더·웹캠·idle·립싱크·내보내기)
                              └──────► NEEDS_REVIEW (QA 미통과: 공개 불가, capability report 와 함께 사용자에게 제시)
```
- **사용자 보정(HITL)은 워커를 붙잡지 않는다.** `AWAITING_REVIEW` 상태 + **두 개의 잡**(A: ~REPAIRING/VARIANTS, B: RIGGING~)으로 분리. 사용자가 수정한 레이어는 새 해시 아티팩트로 올리고 B 가 그 해시를 입력으로 새 캐시 키로 실행. 검토 대기에 TTL(예 72h) 후 정리.
- See-through 는 레이어를 **분할**하는 게 아니라 **확산 모델로 생성**하므로 "보정"의 실체는 ①레이어 PNG 지우개/복원 브러시 ②좌우 분리선 이동(`heuristic_partseg.py seg_wlr/seg_wdepth`) ③특정 파트 seed 재굴림(머리 단계만 재실행 가능한지는 **U**) 이다.
- **GPU 호출은 한 가지 계약만 노출:** `decompose(input_url, output_prefix, seed, resolution) → manifest`. 변형 편집도 `edit_region(crop, mask, instruction, refs) → rgba` 한 가지(어댑터 교체 가능, `02` §5).
- **안전 게이트(S1)는 GPU 앞에서 실패**시킨다(거절 건 GPU 비용 0). 상세 `04` §6.

## 3. 오케스트레이션 선택 (GitHub API 2026-10-02, V)
| 도구 | 버전 | 라이선스 | 판단 |
|---|---|---|---|
| **RQ** | 2.12 | BSD 계열(U) | **MVP 후보** — 단순·충분 |
| **Procrastinate** | 3.10.0 | MIT, Postgres 만 | MVP 후보 — 비즈니스 쓰기와 같은 트랜잭션에서 enqueue |
| **DBOS Transact** | 3.2.0 | MIT, Postgres | 단계 체크포인트·`send/recv`·이벤트로 HITL·재개 내장 — **복잡해질 때 1순위** |
| **Hatchet** | 0.107 | MIT, Postgres | 내구성 태스크·대시보드 |
| Temporal | 1.32 | MIT | HITL 최강, 운영 부담 큼 |
| Celery | 5.6.3 | BSD(U) | 무난, 재개·HITL 직접 구현 |
| **Arq** | 0.28 | MIT | **maintenance only → 금지** |
| Dramatiq / Inngest / Restate | — | LGPL / SSPL / BUSL계열(U) | 라이선스 검토 필요 → 비추천 |

- **진행률:** 단방향이라 **SSE** 로 충분(FastAPI 0.142 내장). `job_events(job_id, seq, type, payload)` 재생 + Redis pub/sub, `Last-Event-ID` 재접속.
- **멱등·캐시:** 아티팩트는 sha256 키(`artifacts(hash PK, kind, size, storage_key, refcount)`), 단계 캐시 키 = `sha256(stage || code_version || canonical_json(params) || sorted(input_hashes))`. **GPU diffusion 은 GPU 종류·드라이버에 따라 비트 단위로 달라질 수 있으므로 입력+seed+모델 리비전을 키로, "같은 출력"을 기대하지 않는다**(U). `POST /jobs` 는 `Idempotency-Key`.
- **재개:** `stages(job_id, name, status, input_key, output_key, attempts, lease_until, error)`. 서버리스 GPU 는 워커가 3분을 붙잡지 않도록 **제출(`spawn`/`/run`) → 폴링 → 재큐** (Modal `FunctionCall.get(timeout=0)`, RunPod `/run`+`/status`).
- **입력 파서 샌드박스:** 사용자 이미지/PSD 를 파싱하는 CPU 워커는 네트워크 없는 컨테이너(gVisor/seccomp) + Pillow 픽셀 상한(decompression bomb). *샌드박스 러너를 재사용하기 좋은 지점.*
- **스토리지:** presigned URL(10–15분, 사용자별 prefix, 비공개 버킷). 레이어는 bbox 로 잘라 WebP 서빙, PSD 는 요청 시 생성.

## 4. GPU 추론 호스팅

### 4.1 워크로드 (V: README·논문·HF API 실측)
- LayerDiff3D(body 13태그 → head 11태그 **연속 2단계**) + Marigold. bf16 1280px **12–16 GB VRAM**, group offload ~10GB(×1.5 느림), NF4 ~8GB.
- 속도: 논문 **RTX 4090 에서 1024² 분해 ≈74초 + 깊이 ≈10초**, HF ZeroGPU 데모 1280px 약 2–3분. 1280px(×1.56 픽셀) + 2단계를 감안한 **150초를 기준값**으로 쓴다(**U**).
- 가중치(HF API 실측): LayerDiff3D **10.16GB**(unet 8.14), Marigold **3.28GB**, NF4 LayerDiff3D 3.76GB → 콜드 때 로드 ≈13.4GB.
- **런타임에 `torch.hub.load_state_dict_from_url` 로 HF 에서 LaMa 체크포인트를 받는 코드가 있다 → 이미지에 굽거나 사설 미러로 고칠 것**(공급망·가용성).
- 메인 추론(`inference_psd.py`)은 **LayerDiff3D + Marigold + 휴리스틱 후처리**만 필요(LaMa 는 좌우 분할 시 선택).

### 4.2 가격 (USD/GPU-시간, 2026-10-02 조회, 1차 페이지)
| 제공자 | GPU | 가격 | 비고 |
|---|---|---|---|
| **RunPod Serverless** | **4090 $1.10** · 5090 $1.58 · L40S $1.75 · A100 $2.72 | 초당 | FlashBoot, 4090 이 가장 저렴 (V~) |
| **Modal** | L40S **$1.95** · A100-40 $2.10 · RTX PRO 6000 $3.03 | 초당 | Python 네이티브, 메모리 스냅샷, 4090/5090 없음, 동시 GPU 10(Starter)/50(Team) (V) |
| RunPod Pods | 4090 커뮤니티 $0.34 / 시큐어 $0.74 | 초당 | 24/7 용 |
| Cloud Run GPU | L4 $0.672 | 초당 | L4 는 4090 대비 2–3배 느림(U) |
| HF Endpoints | L40S $1.80 | 시간 | ZeroGPU 는 프로덕션 백엔드 아님 |
| fal / Replicate / Baseten | — | — | 같은 GPU 대비 2–3배 비쌈(Replicate L40S $3.51) → 비추천 |
| Vast.ai / Hetzner GEX / 국내 IDC | 4090 ~$0.14–0.44 (U2) / 월 €214~ (U2) / 월 264,300원~ (V~) | — | 2차 자료·가격 불확실 |
| 자체 구매 | RTX 5090 시중 평균 ~$4.7k(MSRP $1,999) (U2) | — | **지금은 임대가 유리** |

### 4.3 작업당 비용 (T_run=150s 가정, **U**)
| 구성 | 웜 1건 | 콜드 포함 1건(콜드 90s+idle 30s) |
|---|---|---|
| RunPod Serverless 4090 | **$0.046** | $0.083 |
| Modal L40S | **$0.081** | $0.146 |
| RunPod 팟 4090(24/7, 가동률 100%일 때만) | $0.014 | $0.026 |

- **24/7 팟 손익분기:** 월 약 3,900건(4090 커뮤니티) ~ 8,400건(4090 시큐어) ~ 12,400건(L40S 시큐어). 그 이하는 서버리스.
- **큐 사이징(Erlang-C, U):** 시간당 30건→4대, 120건→9대(p95 대기 ~18초), 300건→17대, 600건→30대. 서버리스는 **동시 실행 상한 = 처리량 상한**(Modal Starter 시간당 ≤240건, Team ≤1,200건).
- **콜드스타트(미측정, U):** 이미지 pull(torch+cu128 수 GB) + 가중치 13.4GB 로드 = 최적화 없이 60–150초, 가중치 굽기/볼륨 캐시/스냅샷이면 20–60초. **M0 에서 플랫폼별 실측 필수.**

### 4.4 **퍼펫 1개당 비용 추정 (U 모델, 가격 입력만 V)**
| 항목 | 값 |
|---|---|
| GPU 분해(150s) | 웜 $0.046 – $0.081 |
| 콜드 30% 가중 + 재시도 ×1.3 | 합계 **≈ $0.08 – $0.14** |
| **변형 소재 생성** | **자체 호스팅(Qwen-Image-Edit-2511 등)이면 GPU 시간만 — 변형 4~12회 × 수~수십 초(U)** / API 면 gpt-image-2.5 medium ×12 ≈ $0.16 (high ≈ $0.64), NB2 1K×4 ≈ $0.27 |
| VLM 계획·QA(수회~수십 회 호출) | 수 센트 이하로 추정(U, 토큰 단가 미확인) |
| CPU 단계·저장·egress | 거의 0 (R2 egress 무료) |
| **합계(변형 API 포함 시)** | **$0.2 – $0.8 / 퍼펫** (U) |
- 하루 1,000건이면 월 ≈ $2.4k–4.2k(서버리스, 변형 제외). **무료 등급은 일일 쿼터(예: 3건)로 막지 않으면 비용이 사용자 수에 선형으로 붙는다.**

## 5. 브라우저 렌더링·상호작용

| 선택 | 판단 |
|---|---|
| **WebGL2 렌더러(기준)** | 지원 96.4%. PixiJS v8(`Mesh`/`MeshSimple`/커스텀 `Geometry`+`Shader`, 매 프레임 버퍼 수정) 또는 **얇은 커스텀 WebGL2**(StretchyStudio/Anime2.5DRig 방식, MIT 레퍼런스). **M1 초반 2일 스파이크로 결정**(클리핑 마스크·그리기 순서 구현 난이도 비교) |
| 변형 위치 | 23레이어 × 수백–수천 정점 = 총 수만 정점이면 **CPU 키폼 블렌딩 + `Float32Array` 동적 업로드**로 60fps 가능성이 높다(U, 구현 후 측정). 커지면 shape-key 델타를 attribute 로 올려 정점 셰이더에서 블렌딩 |
| Cubism Web SDK / Core / pixi-live2d-display | **쓰지 않는다**(`04` §1). pixi-live2d-display 는 마지막 푸시 2024-08, Cubism 5 미지원 |
| Inox2D | "프로토타입, 프로덕션 비권장" → 쓰지 않는다 |
| 웹캠 추적 | `@mediapipe/tasks-vision` 1.0.1(Apache-2.0): 478 랜드마크 + **52 블렌드셰이프** + 변환 행렬. **웹 워커 권장**, 일부 플랫폼에서 GPU 델리게이트가 오히려 느림(142ms vs 22ms 사례, U2) → **시작 시 CPU/GPU 벤치마크해 빠른 쪽**, 입력 320px. **웹캠 프레임은 서버로 보내지 않는다**(처리방침에 명시). 모델 번들 개별 라이선스는 미확인 |
| 매핑(U) | 머리 변환 행렬 → `ParamAngleX/Y/Z`, `eyeBlinkL/R` → `ParamEyeL/ROpen`(1−값), `jawOpen` → `ParamMouthOpenY`, `mouthSmile−mouthFrown` → `ParamMouthForm`, `browInnerUp/browDown` → `ParamBrowLY/RY`, `eyeLook*` → `ParamEyeBallX/Y`. Kalidokit(MIT)이 선행 구현 |
| 영상 내보내기 | WebCodecs + `mediabunny`(MPL-2.0) / `MediaRecorder` 폴백(96%). **투명 영상은 브라우저별로 갈림**: WebCodecs `alpha:"keep"` 로 VP9 알파 WebM 가능하나 MediaRecorder 는 알파 소실 가능, Safari 는 HEVC-with-alpha 만 신뢰 → **MVP = 불투명 MP4/WebM + 투명 PNG 시퀀스 ZIP, 투명 WebM 은 Chrome 계열 옵션** |
| PSD I/O | `ag-psd` 31.0.2(MIT). 서버는 `psd-tools` |
| 교환 포맷 | glTF 는 2D 키폼 리그에 맞지 않음. 내부 정본 = **`puppet.json`(IRR) + WebP 아틀라스**, 외부 = PSD(See-through 레이어 이름 규약) / (후속) `.inp` / (게이트) `.moc3` |
- **에디터 UI 최소 패널:** 레이어 트리, **파라미터 슬라이더**(AngleX/Y/Z, 눈 L/R, 시선, 눈썹, 입 개폐/형태, 몸, 호흡, 머리카락), 메시 오버레이, **앵커 편집(Anime2.5DRig 방식)**, **모델 진단/capability report**, undo/redo(immer patch), 표정 프리셋 1–7 키. 타임라인·shape key 편집기는 MVP 이후. Next.js 에서 렌더러는 `dynamic(..., {ssr:false})`, MediaPipe 는 워커.

## 6. 보존·개인정보·표시 (권고, 법률 자문 대상)
- 업로드 원본·중간산출물 = 마지막 활동 후 **30일 자동 삭제**(제안), 결과 퍼펫 = 사용자가 삭제 가능, 일반 로그 90일, 신고·격리 건은 미국 신고 시 1년 보존 후 파기.
- 14세 미만 제외(PIPA 22조의2), 해외 GPU/API 사용 시 **국외 이전·위탁 고지**, "사용자 데이터를 모델 학습에 쓰지 않는다" 약속.
- C2PA 자격증명 + `puppet.json` 의 `ai_generated:true` + 무료 등급 가시 배지(`c2pa-python` Apache-2.0 / `c2pa-js` MIT).
- **공개 갤러리·공유 링크·임베드 없음(기본 비공개)** — 저작권·NSFW 검토 부담 폭증 방지.

## 7. MVP 에서 자를 것
1. 상용 이미지 API 기반 변형·인페인팅(옵션 어댑터로만) 2. `.moc3`/`.cmo3`/Spine 내보내기 3. 공개 갤러리·공유 링크·임베드 4. VLM 에이전트의 **정점 단위** 리깅(VLM 은 계획·판정만) 5. WebGPU 렌더러, 멀티 프로바이더 폴백, Temporal, 타임라인·물리 편집기, GIF, 결제 6. SAM 신체 파싱·LaMa 등 비필수 모델 7. 모바일 앱(웹 반응형만)

## 8. 확인하지 못한 것
추론 속도·VRAM·콜드스타트 실측 / Vast.ai·Hetzner·RTX 5090 가격(2차) / NHN·네이버·KT 클라우드 GPU 요금 / RunPod·fal·Replicate 공식 콜드스타트 수치(문서에 없음) / MediaPipe 브라우저 성능·번들 라이선스 / EU DSA·GDPR·PIPA 국외이전 조항 번호·한국 OSP 의무 적용 방식 / DMCA 대리인 수수료($6/3년은 2차) / WD tagger 게이트·VLM 심판의 우리 도메인 정확도.
