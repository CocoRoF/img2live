# 04. 출력 포맷(Live2D 가능성) · 라이선스 · 법무

근거: 에이전트 조사 `research_live2d_format.md`, `research_service.md` + **직접 원문 재확인**(Live2D Core EULA, 관련 OSS 저장소 메타, See-through 이슈 #43).
표기: **(V)** 원문 확인 / **(V-S)** 요약 경유 확인 / **(U)** 미검증. **법률 자문이 아니다. §7 항목은 일본 IP 변호사·Live2D 문의 대상.**

---

## 0. 결론

1. **"진짜 .moc3 를 만들 수 있나" — 기술적으로는 이미 된다.** 2026-07~10 에 오픈소스 여러 개가 .moc3 쓰기까지 구현했다(아래 §2). 그러나 **독립 검증(VTube Studio/Core 로드 실측)은 아무도 하지 않았고**, 모두 "첫 초안" 수준이라고 스스로 말한다.
2. **법적 병목은 .moc3 생성이 아니라 ① Cubism Core 로 사용자 생성 모델을 공개 웹에서 렌더링하는 것 ② "2D 크리에이터의 창작성을 해칠 수 있는 용도" 금지 조항이다.**
3. **사용자 허락: 우리 포맷·런타임을 만들어도 된다고 했다.** → **MVP 는 자체 포맷(IRR) + 자체 웹 런타임**, 파라미터 ID 는 Cubism 표준을 그대로 써서 나중에 .moc3 로 "낮추기" 쉽게 한다. .moc3 내보내기는 **법무 게이트 뒤의 옵트인 3단계**.
4. 이름에 **"Live2D"/"Cubism" 을 넣지 않는다**(Core EULA 5.3.1). 호환성 서술(nominative)만 허용, 로고 금지.

## 1. Live2D 약관 — 직접 확인한 핵심 조항 (V)

출처: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html (영문은 번역본, **일본어 원문이 우선·일본법 준거** — 일본어 원문은 읽지 않았음)

| 조항 | 원문 요지 | 우리에게 |
|---|---|---|
| 1.5 Expandable Application | "any Derivative Work having significant expandability. In particular, it includes the Derivative Work which uses and generates **any indefinite number of models** by adding or combining files or data (e.g. avatars, live streaming applications, **video generators/video makers**)" | **사용자별 모델을 만들어 보여 주는 웹 서비스 = 이 정의에 해당할 가능성이 매우 높다(해석은 U)** |
| 2.1 / 2.2 | 배포는 별도 Publication License 필요. 소규모·일반 사용자 면제가 있으나 **"this exemption is not applicable for Publishing the Expandable Application"** | 소규모여도 면제 불가 |
| (SDK 페이지, V) | Expandable 은 **사전 신청·승인·별도 계약**, 승인 예시 조건에 "유효한 수익 모델(원칙적으로 **완전 무료는 승인 대상 아님**)", 매출 분배(소규모 건당 ¥300 또는 매출 20% 중 큰 값, 중·대규모 5%, 광고 수익 포함), 승인은 Live2D 재량 | Core 를 쓰는 순간 계약·수익분배 구조 |
| 6.4 | 역공학·디컴파일·디스어셈블 금지 | **디컴파일에 기댄 오픈소스 코드를 참조하지 않는다**(§2 출처 오염) |
| 6.7 | "will not use or offer the Software on a service bureau basis…" | **서버에서 Editor/Core 를 대신 돌려 주는 구조 금지** |
| 6.8 | "may not use the Software to develop, Publish, or distribute Derivative Works that **may harm the creativity of 2D Creators as the assumed primary use**" (Editor 5.1.9, Open License 5.7 에도 유사) | **"일러스트 1장 → 자동 퍼핏" 서비스가 정면으로 걸릴 수 있음(해석 U)**. Live2D 자신도 연구 방침에서 "일러스트에서의 완전 자동 모델링은 하지 않는다"(V-S, 2022) |
| 5.3.1 | 계약 없이 파생물·출력 파일 이름에 Live2D 상표 사용 금지 | 제품명·도메인·메타데이터에서 제외 |
| AI | 4개 약관 영문본에 **AI/ML, moc3·cmo3 형식, 제3자 생성기에 관한 명시 조항은 없음**(grep). 공식 FAQ(2025-03): AI 사용 자체는 막지 않되 "학습 데이터 침해 사용"과 "2D 크리에이터 창작성을 해칠 수 있는 파생물(서비스 포함)"은 금지 (V) | 조항은 "Core/Editor/SDK 를 쓰는 자"를 구속 → **안 쓰면 계약 구속은 약함**. 단 저작권·부정경쟁·특허·상표는 별개 |

**집행 선례(V):** 2019-09 Live2D Inc. 가 UlyssesWu/FreeLive 에 Editor EULA 5.1.2 / Core EULA 6.4 위반을 이유로 삭제 요구 → 소유자가 삭제.
**공개 입장 부재(U):** Umamo·psd2live·Ayagami·Purism 에 대해 Live2D 가 공식 입장을 낸 증거는 못 찾음(부재 증명 아님).

## 2. 기술 지형 — .moc3 와 오픈 구현 (2026-10-02, GitHub API 로 일부 직접 확인)

| 구분 | 내용 |
|---|---|
| JSON 계열 (model3 / physics3 / motion3 / pose3 / exp3 / cdi3 / userdata3) | **Live2D 가 스펙을 공개**(Live2D/CubismSpecs) → 우리가 직접 생성해도 문제 적음 (V) |
| .moc3 (런타임 바이너리) | 공식 스펙 없음. 가장 깨끗한 근거는 OpenL2D `moc3.hexpat`("MOC3 readers and writers 를 만드는 것을 제한하지 않는다", 단 "완전 검증 안 됨", 저장소는 아카이브) (V). 버전 1~5 지원, **Cubism 5.3 Editor 는 moc3 v6 를 내보내며 Core 5 이하는 읽지 못함** → 낮은 버전 방출이 호환에 유리 (V) |
| .cmo3 (Editor 프로젝트) | CAFF 컨테이너 + main.xml. 공식 문서 없음. 오픈 구현은 있으나 "Editor 검증 진행 중"(실험) |
| **Umamo** (Kotlin, GPL-3.0) | moc3·cmo3 읽기/쓰기, 2026-07-13 시작, clean-room 표방 + 기여자 조건 |
| **psd2live** (Kotlin, GPL-3.0) | PSD → .cmo3 + .moc3, **530 stars, 오늘 v2.0.1 푸시**(직접 확인). "수출 성공 ≠ 모든 런타임에서 동일 효과" 자체 경고 |
| **image2live2d** (Python, **Apache-2.0**) | **See-through 분해 → 자동 리깅 → .inp/.moc3(v3.00 최소)/.cmo3**. 2026-07-10 생성, 38 stars (직접 확인). "공식 모델 5개와 byte-for-byte 검증" 주장은 **독립 검증 불가(U)**. OpenL2D hexpat 기반이라 소스에 명시 |
| lvhaojie456/image-to-live2d (MIT) | 프롬프트/이미지 → See-through → psd2live → 시각 검수 루프. 2 stars, 9/20 생성. 제작 호스트가 Editor 의 Core JNI 를 써서 SaaS 부적합 |
| **StretchyStudio** (JS, MIT) | 브라우저 자동 리거 + Spine/.moc3(v4.00)/.cmo3 내보내기. **자기 문서에 "IDA Pro RE of Live2DCubismCoreJNI.dll", "Java decompile via CFR" 명시 → 출처 오염, 이 내보내기 코드는 쓰지 않는다** (V) |
| py-moc3 | 소스가 "moc3-reader-re(Java decompilation of the Cubism SDK exporter)" 이식 → 오염 |
| **Ayagami** (Rust, MIT/Apache-2.0) | Live2D 호환 **렌더러**(wgpu, WebGL/WebGPU), "black-box RE only", VTube Studio 를 테스트 오라클로 사용. 342 stars. 5.0 + 5.3 기능 |
| **Purism Core** (C99, MIT, WASM) | **Cubism Core ABI 재구현**("without any Live2D code"). 39 stars |
| Inochi2D / nijilive / Inox2D | BSD-2. Inox2D 는 "프로토타입, 프로덕션 비권장". nijigenerate 활발(10-01 푸시) |

> **출처 오염 규칙:** moc3/cmo3 인코더를 만드는 사람은 Cubism SDK/Editor/Core 를 설치하거나 약관에 동의하지 않는다. StretchyStudio·py-moc3·moc3-reader-re 계열 코드·문서는 참조하지 않는다. 근거로 쓸 수 있는 것: OpenL2D hexpat(FDPL), CubismSpecs(JSON), Ayagami/Purism/moc3-rs 를 블랙박스 오라클로 한 **자체 실험**.
> GPL-3.0 구성요소(Umamo, psd2live)는 서버 내부 CLI 호출과 사용자에게 전달하는 앱 번들의 법적 취급이 다르다(전자도 AGPL 이 아니라 GPL 이므로 서버 내 사용은 통상 배포가 아니지만 **U, 법무 확인**).

### Cubism Editor 자동화는 막혀 있다
- Editor EULA 5.1.7 "No Service Bureau": 서버에서 대신 출력해 주는 서비스 금지(V).
- Editor 5.4 alpha(2026-07-14)의 External API 에 편집 API 가 추가됐지만 **GUI 실행 + 사용자 승인 필요**, ArtMesh 신규 생성·PSD 임포트·키폼 정점 설정 API 는 없다(V). 헤드리스 자동화 불가.
- 공식 AI 기능은 5.0~5.1 의 자동 디포머/흔들림/얼굴 움직임 생성뿐. **"일러스트 → Live2D 완전 자동" 발표는 2026-07-17 까지의 뉴스에 없음**(V-S).

## 3. 선택지 평가

| 옵션 | 내용 | 공수(pw, 추정 U) | 법적 리스크 | 판단 |
|---|---|---|---|---|
| A1 | 자체 moc3 인코더 + Cubism Web SDK/Core 렌더 | 24~36 | **매우 높음**(Expandable 승인·수익분배·"완전 무료 비승인", 6.8) | ❌ 출시 전 Live2D 계약 선행 필요 |
| A2 | 자체 moc3 인코더 + Ayagami/Purism 렌더 | 26~38 | 높음(계약은 회피하나 분쟁·특허·정책, 공식 입장 없음) | ⚠️ 법무 게이트 뒤에서만 |
| A3 | Cubism Editor 구동 | 서버: **불가** / 사용자 PC 로컬 플러그인 6~10 | 서버 5.1.7 위반 | ❌ 일반 사용자와 안 맞음 |
| A4 | PSD(+옵션 cmo3)만 내보내고 사용자가 Editor 에서 마무리 | 3~6 (+cmo3 6~10) | 낮음(PSD) | ✅ 가치는 낮으나 안전 — 2단계에 포함 |
| **B** | **자체 포맷(IRR) + 자체 WebGL2 런타임 + 자동 리깅** | 20~32 | **낮음~중간**(Core 미사용, 이름 미사용) | ✅ **MVP** |
| **C** | **B → +PSD/.inp/투명 영상 → (게이트) 실험적 moc3** | 32~47 합 | 단계별 증가, 게이트로 통제 | ✅ **권고** |

moc3 의 실질 가치는 **VTube Studio 호환**이다(VTS 는 Live2D 만 지원, VRM 미지원 — V-S). VTuber 타깃이라면 3단계가 사업적으로 중요하다.

## 4. 라이선스 매트릭스 (서빙 경로 기준)

| 컴포넌트 | 라이선스 | 상업 SaaS | 비고 |
|---|---|---|---|
| See-through 코드 | Apache-2.0 | OK | `arial.ttf`, 출처 불명 테스트 이미지는 재배포 금지 |
| **LayerDiff3D 가중치** | 자체 Apache-2.0 + **Open RAIL++-M**(Animagine XL 4.0·SDXL) + OpenRAIL-M(LayerDiffuse) + MIT(VAE) | **조건부 OK** | **서비스 호스팅 = Distribution → 약관에 Attachment A 사용 제한 포함 + 사용자 고지**. 저자가 2026-09-28 이슈 #43 에서 "상업 사용 OK, 단 이 조건" 확인 (V) |
| **Marigold 파인튜닝** | Open RAIL++-M 승계 | 조건부 OK | 위와 동일 (저자 확인) |
| SAM 신체 파싱 | Apache-2.0 | OK | 메인 추론에 불필요 |
| SDXL base / Animagine XL 4.0 | Open RAIL++-M | 조건부 OK | "Updates and Runtime Restrictions"(licensor 가 원격 제한 권리 유보) 인지 |
| LaMa, SkyTNT anime-seg, WD tagger v3 | Apache-2.0/MIT | OK | LaMa 는 런타임 URL 다운로드 → **이미지에 굽거나 사설 미러**(공급망) |
| **bizarre-pose-estimator** | **AGPL-3.0** | ❌ 서빙 금지 | See-through `bizarre_tagger` 가 가중치 로드 → 메인 추론엔 불필요, 제외 |
| Depth Anything V2 **Large 이상** | CC-BY-NC-4.0 | ❌ | 학습 코드에만 존재, 추론엔 미사용 — 가중치 혼입 주의 |
| **FLUX.2 klein 9B / dev** | 비상업 | ❌ | 4B 는 Apache-2.0 OK |
| **Qwen-Image-2.1** | 연구 전용 | ❌ | |
| Qwen-Image-Edit-2511 / -Layered | Apache-2.0 | OK | 무겁다 |
| **ComfyUI / RunPod worker-comfyui** | GPL-3.0 / AGPL-3.0 | 서빙에 쓰지 말 것 | diffusers 로 직접 서빙 |
| **MinIO** | AGPL-3.0 + **archived** | 비권장 | SeaweedFS(Apache-2.0)/R2 |
| PixiJS / ag-psd / onnxruntime-web / MediaPipe tasks-vision | MIT / MIT / MIT / Apache-2.0 | OK | MediaPipe 모델 번들 개별 라이선스는 미확인 |
| StretchyStudio / Anime2.5DRig | MIT | OK(구조 참고) | StretchyStudio 의 Live2D 내보내기 코드는 제외 |
| Dramatiq / Inngest / Restate | LGPL / SSPL / BUSL계열 | 조건부 | 오케스트레이션은 RQ·DBOS·Hatchet(MIT) |

### OpenRAIL 의무 체크리스트 (약관에 반영)
1. 이용약관에 **Attachment A 사용 제한을 enforceable provision 으로 명시**하고 고지, 사용자가 준수하도록 요구.
2. 사용자에게 라이선스 사본 제공(오픈소스 고지 페이지에 SDXL/Animagine/LayerDiffuse/See-through LICENSE·NOTICE), 저작권·귀속 유지.
3. Attachment A 에 **"미성년자 착취·가해 목적 금지"** — NSFW 정책과 직결.
4. 출력물 책임은 우리·사용자에게("Licensor claims no rights in the Output").
5. See-through 크레딧 + 논문 인용 권고, **저자는 "유료 서비스를 운영하지 않으며 요금을 받는 사이트는 무관"이라고 공지** → 상용화 시 **비제휴 고지** 필요.
6. **사용 시점의 HF 커밋 해시 고정** + LICENSE/NOTICE 보관(저자가 9/28 에 카드를 고쳤으므로 옛 스냅샷 근거 금지).

## 5. 학습 데이터 리스크 (가장 큰 잔여 리스크)

- See-through: ArtStation·Booth·DeviantArt 등에서 모은 **상용 Live2D 모델 9,102개(증강 후)**. 권리 처리·윤리 진술 없음. Bunraku: 인터넷 공개 Live2D 8,884개, 권리 처리 명시 없음.
- Live2D 공식 샘플의 Sample Material 조항은 "내부 평가와 Training(소프트웨어 숙달)"에 한정 — ML 학습이 아니다(해석 U).
- 우리가 **리깅 모델을 직접 학습**하려면 같은 종류의 데이터가 필요 → 합법 확보 경로(작가 계약·옵트인·자체 제작·합성)가 사업 리스크의 핵심. **MVP 는 학습 없는 규칙/기하 리깅으로 시작**해서 이 리스크를 미룬다(→ `03`).

## 6. 안전 · 남용 (애니 스타일 서비스라서 구조적으로 위험)

| 관할 | 내용 | 수준 |
|---|---|---|
| 미국 §2258A | **실제 인지** 시 NCMEC 신고, 스캔 의무는 없음, 신고 건 **1년 보존**(REPORT Act) | V-S |
| 한국 | 아동·청소년이용음란물에 "표현물" 포함, 2019 대법원은 교복 입은 만화 캐릭터를 해당으로 판단, **헌재 2026-06-24 결정(6/28 보도): 만화·애니 캐릭터 아동성착취물 배포·소지 처벌 전원일치 합헌**. 제17조 OSP 조치 의무 | 헌재 V-S, 조문 U |
| EU/영국 등 | 임시 규칙 상태 불명 | U |

**MVP 정책(권고):** NSFW 전면 불허 + 미성년 인식 가능 캐릭터의 어떤 성적 요소도 불허 + **공개 갤러리·공유 링크 없음(기본 비공개)**.
다층 게이트(GPU 앞단, 거절 건은 GPU 비용 0): ①재인코딩·픽셀 상한·EXIF 제거·해시 차단 목록 ②**WD tagger v3(Apache-2.0)** 규칙 게이트(등급 태그 + `loli/shota/child/aged_down/nude…`, `multiple_*`·`realistic` 은 입력 부적합 거절) — **정확도 미검증이므로 자체 라벨 100~200장으로 임계값 보정** ③(선택) OpenAI moderation — **이미지에서 `sexual/minors` 미지원, "CSAM 은 탐지 불가"를 문서가 명시** ④사람 검토 큐 + 신고 + 감사 로그 + 의심 이미지 SOP(격리 버킷·최소 권한·신고 경로).
팬아트 차단은 사용 사례를 죽이므로 **차단이 아니라 DMCA/삭제 요청 체계**로.
- 약관·개인정보: 14세 미만 제외(PIPA 22조의2), 해외 GPU/API 로 보내면 **국외 이전 고지**, 업로드 원본·중간물 마지막 활동 후 30일 삭제(제안), "사용자 데이터를 모델 학습에 쓰지 않는다" 약속.
- AI 표시: 한국 AI 기본법(2026-01-22 시행)·EU AI Act 50조 대비 → C2PA 자격증명 + `puppet.json` 에 `ai_generated:true` + 무료 등급 가시 배지. (유예·범위는 2차 보도라 U)
- 상용 이미지 API 를 MVP 에서 빼야 하는 이유: 비용보다 **정책 리스크**(Gemini 55일 보관·계정 전체 차단 에스컬레이션, 단일 키가 계정 전체 위험).

## 7. 변호사 / Live2D 문의 목록 (일본 IP 변호사 + SDK 라이선스 팀)

1. Editor/Core 를 설치한 적 없는 팀이 공개 자료로 만든 moc3 인코더와 출력물 배포가 EULA·저작권·부정경쟁·**특허**에 문제 없는가. (Live2D 의 특허 범위는 못 읽음)
2. Core 없이 오픈 재구현(Ayagami/Purism)으로 사용자 모델을 렌더하는 웹 서비스가 Publication License/Expandable 승인 대상인가(서면 입장).
3. Core 사용 시 무료 베타가 Expandable 로 승인될 "별도 지정 조건"은 무엇인가. 광고·구독 수익 처리.
4. **6.8 "2D 크리에이터 창작성 침해" 해석:** 일러스트 1장 → 자동 퍼핏이 해당하는가. 해당하지 않는 설계 조건(리거용 보조 도구, 초안 + Editor 이어 편집 등)이 있는가.
5. 제품명·마케팅에서 "Live2D 호환" 표현 한계.
6. See-through 가중치 사용 리스크(학습 데이터 권리), OpenRAIL 전달 의무, 대체·파인튜닝 옵션.
7. 사용자 PC 의 Editor 를 우리 플러그인이 구동하는 BYO-license 구성의 5.1.7/5.1.9 저촉.
8. GPL-3.0 구성요소(Umamo, psd2live)를 서버 내부 CLI 로 호출하는 구성의 의무 범위.

## 8. 확인하지 못한 것
일본어 원문 EULA / Live2D 특허 목록·청구항 / 오픈 moc3 구현의 독립 로드 검증 / Ayagami·Purism 에 대한 Live2D 이의 여부 / 표준 Part ID 목록(공식 문서에 없는 듯) / 5.4 alpha 편집 API 전체 스펙 / 키폼 보간식·좌표계 세부(구현 단계에서 오픈 구현·실험으로 확정) / Warudo·VNyan·Vtuber Maker 의 Live2D 지원 / EU DSA·GDPR·PIPA 국외이전 조항 번호 / OpenAI·xAI 정책 원문(403).
