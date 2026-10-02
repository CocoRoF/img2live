# img2live 리깅 자동화 조사 보고서 (기준일 2026-10-02)

작성 목적: See-through(arXiv 2602.03749)가 만든 약 23장의 RGBA 레이어(PSD)를 입력으로, 브라우저에서 재생 가능한 Live2D 스타일 2D 퍼펫(메시, 워프/회전 디포머, 파라미터, 키폼, 물리, 모션)을 자동 생성하는 방법의 문헌·OSS 현황과 구현 가능한 설계안.

## 0. 먼저 읽을 결론

1. **"리깅은 미해결"이라는 전제가 2026-10 기준으로는 절반만 맞다.** See-through 공개(2026-02) 이후 약 6개월 동안 OSS가 폭발적으로 나왔다. 그중 `psd2live`(Kotlin, GPL-3.0, 2026-09-03 생성, 2026-10-02 기준 463 커밋·529 star)는 레이어 PSD → 메시 + 디포머 계층 + 머리/몸/눈/입/눈썹 파라미터 + 대기/눈깜빡임/끄덕임 모션 + 앞/뒤 머리 물리 + `.moc3`/`.cmo3` 내보내기를 **헤드리스 CLI 한 번**에 수행한다. 개발 머신(Ubuntu, GPU 없음, JDK 21)에서 예제 PSD(2048x2048, 24레이어)를 실제로 돌려 **벽시계 약 9초**에 moc3 파일군이 나오는 것을 직접 확인했다. [S40, S82] (VERIFIED, 직접 실행)
2. **그러나 "자동 리그 = 전문가급"은 아무도 달성하지 못했고, 개발자들 스스로 그렇게 말한다.** psd2live 예제 산출물은 24 드로어블/29 디포머/20 파라미터이고, Cubism 샘플 Hiyori는 134 아트메시/104 디포머/70 파라미터다. [S82, S42] 상용 파이프라인(Cubism 자체)도 자동 기능을 "최소 품질까지의 공수를 줄이는 보조"로 정의한다. [S73] 현실적 천장은 Tier 1(눈깜빡임, 입 열림, 호흡, 머리카락 흔들림, 작은 머리 회전)이다.
3. **See-through 출력만으로는 리깅에 필요한 아트가 모자란다.** psd2live 규격이 요구하는 `eye_close`, `mouth_close`, 완전히 벌린 `mouth_open`, `tooth-t/b`, `tongue`를 See-through는 만들지 않고, 입이 닫힌 그림이면 "입이 안 열리는데 에러도 없는" 조용한 실패가 난다. [S54] 이 간극을 메우는 것(이미지 편집 모델로 변형 레이어 생성 + 측정 기반 정합)이 img2live의 실질적 R&D 포인트다. image-to-live2d, PachiPakuGen, PNGAL이 모두 이 방식으로 갔다. [S50, S48, S47]
4. **머리 각도 XYZ(의사 3D)는 학습 없이 해석적 모델이 실전 해법이다.** StretchyStudio는 See-through의 Marigold 깊이를 얼굴 시차에 써 보다가 **깊이 없이 원통 돔이 더 낫다**며 제거했고, psd2live는 9포즈(AngleX x AngleY) 얼굴 격자 + 특징 보정을 쓴다. Anime2.5DRig는 레이어별 깊이 시차 + 전단(shear)이다. 생성 키프레임(이미지 편집으로 돌린 얼굴을 레이어에 정합) 방식은 **내가 찾은 범위에서는 공개 구현이 없다**(연구 공백으로 보임, 부재 증명은 불가). [S42, S40, S44]
5. **학계 직접 경쟁작은 Bunraku(arXiv 2607.27348, 2026-07-29) 한 편뿐이고 아직 쓸 수 없다.** 코드 저장소는 README 스텁(1KB), 가중치 미공개, 논문 표기 라이선스 CC BY-NC-SA 4.0, 파라미터 8개(확장 24개), 정점 방향 코사인 평균 0.768(50캐릭터 중 31개만 0.80 이상). [S6-S9] 눈 깜빡임·물리는 논문에서 확인되지 않는다.
6. **법무가 기술보다 먼저 막을 수 있다.** (a) Cubism Core 재생은 Live2D 독점 라이선스(연 매출 1,000만 엔 초과 사업자는 출판 라이선스) [S70, S71], (b) nizima는 AI 생성 일러스트 기반 Live2D 마켓 판매를 금지(2024-05-07) [S72] — 서비스 약관에 반영 필요, (c) See-through 가중치는 Open RAIL 계열이라 서비스 약관에 사용 제한 조항 전파가 필요(저자 확인) [S4], (d) psd2live는 GPL-3.0. 법적 판단은 변호사 확인 필요(UNVERIFIED).
7. **권장 방향**: "결정론적 리그 컴파일러 + 자체 rig-spec JSON + 웹 런타임 + 수치/VLM QA 루프" 하이브리드. 1단계는 psd2live를 서버 워커로 감싸 Tier 1 MVP를 빠르게 만들고, 동시에 자체 컴파일러(GPL·Cubism Core 의존 탈피)를 키운다. LLM/VLM은 계획·레이어 보정·QA 판정·모션 스펙 작성에 쓰고, 정점 단위 기하는 맡기지 않는다. 상세는 7장.

### 검증 등급 표기

- **[V]** VERIFIED: 1차 자료를 직접 읽음(저장소 clone 후 소스/문서 열람, `gh api`로 README/이슈 원문, arXiv 초록 페이지, 공식 문서) 또는 직접 실행.
- **[V†]** 1차 페이지를 WebFetch 요약기로 읽음. 핵심 수치는 원문 줄 단위 대조를 하지 않았다.
- **[U]** UNVERIFIED: 검색 스니펫, 2차 설명, 기억, 또는 나의 추론/설계 제안.

---

## 1. 문헌 조사 (2023-2026)

### 1.1 arXiv 검색 결과의 크기

arXiv 검색(제목/초록 기준) "Live2D"는 **4건**: Bunraku(2607.27348), See-through(2602.03749), CartoonAlive(2507.17327), Textoon(2501.10020). [S38] [V†] "anime layer decomposition" 검색은 16건이 나오나 대부분 무관하고 관련 건은 Bunraku, Workflow-Aware(2603.14925), StdGEN++(3D)다. "2D character rigging"은 대부분 3D 리깅 논문이다. Semantic Scholar의 See-through 인용 목록은 2건(Stable-Layers, Workflow-Aware)만 반환했는데 Bunraku가 빠져 있어 **불완전**하다. [S39] [V] → "See-through를 인용/추종하는 모든 논문"을 완전하게 열거했다고 주장할 수 없다(UNVERIFIED 한계).

### 1.2 직접 관련 논문

| 논문 | 방법 | 입력 → 출력 | 코드 | 라이선스 | 비고 | 검증 |
|---|---|---|---|---|---|---|
| **See-through** (Lin et al., SIGGRAPH 2026, arXiv 2602.03749, 2026-02-03) | LayerDiff 3D(SDXL 기반 투명 레이어 확산) + Body Part Consistency Module + 파인튜닝 Marigold 의사 깊이. 학습 데이터는 상용 Live2D 모델 9,102개(7,404/851/847)에서 ArtMesh 렌더러로 추출 | 일러스트 1장 → 최대 23레이어(코드 V3 태그 23종, 논문은 19클래스) 인페인팅된 RGBA + 그림 순서 + 깊이, PSD. 1024px에서 분해 74초 + 깊이 10초(RTX 4090) | github.com/shitagaki-lab/see-through (4,214 star) | 코드 Apache-2.0. 가중치는 각 파인튜닝 원본 라이선스 상속(LayerDiff 3D=Animagine XL 4.0/LayerDiffuse Open RAIL, 깊이=Marigold v1.1 OpenRAIL++-M, 신체 파싱 SAM=Apache-2.0). 상업 사용 가능하나 Open RAIL 2종은 서비스 약관에 사용 제한 포함 필요 | 저자: "리깅은 가장 중요하고 노동집약적인 단계이며 이 프로젝트가 다루지 않는다", 미래 과제로 "분해로부터 애니메이션 타이밍 예측". 아티스트 7명 평가에서 "모션 초안을 30-60분에 만들 수 있다" | [V]/[V†] |
| **Bunraku** (Chen et al., arXiv 2607.27348, 2026-07-29) | Stage 1: Qwen-Image-Layered를 Live2D 8x32 분류 체계로 파인튜닝(Live2D 1만 모델, 8xA100, 6K step), 레이어 캡션·가림 마스크 조건. Stage 2: 레이어별 알파로 삼각 메시를 결정적으로 생성(알파>4/255, 3px 팽창, 외곽선 + 지터 격자 + Delaunay, 정점의 약 55%가 경계) 후 **모든 레이어의 정점 토큰을 하나의 시퀀스로 묶는 5.1M 파라미터 트랜스포머**가 키포즈별 정점 변위를 한 번의 forward로 회귀(레이어별 독립 대비 방향 코사인 0.693→0.740 개선) | 일러스트 → 순서 있는 RGBA + 레이어별 메시 + 파라미터 키포즈 변위. WebGL 30fps 뷰어 | **저장소는 README 스텁(2026-07-31, 1KB)**, 데이터셋은 "요청 시" | arXiv 표기 CC BY-NC-SA 4.0 | 8,884 모델 코퍼스(학습 1,443 + 보류 50캐릭터), Live2D-Bench 120건. Stage 2 방향 코사인 평균 0.768/중앙값 0.828, 0.80 이상 31/50. 파라미터 8개(본문에서 이름이 확인되는 것은 ParamAngleX, ParamBodyAngleZ, ParamMouthOpenY), 확장 24개. 다중 파라미터는 변위 합산. **.moc3/.cmo3 내보내기와 눈 깜빡임/물리는 본문에서 확인되지 않음.** 모델 크기를 5.1M→571M으로 키워도 개선 없음, 1.0B는 발산(데이터 다양성이 병목) | [V]/[V†] |
| **CartoonAlive** (He et al., Tongyi Lab, arXiv 2507.17327, 2025-07) | 얼굴 정렬 + MediaPipe 랜드마크 → 템플릿 정합, 블렌드셰이프 기저(x, y, scale, -30~+30), PyGame 합성 10만 장으로 MLP가 랜드마크→Live2D 파라미터 회귀, 아티팩트 인페인팅, 머리카락 전이 | 인물 사진 1장 → 얼굴만 리깅된 Live2D(눈·코·입·눈썹 분리 텍스처 + ARKit 52 표현) | 프로젝트 페이지만, 코드/라이선스 미표기 | 미표기 | 정량 평가 없음, 30초 미만. 귀 검출·동공 위치·가는 머리카락 한계 인정 | [V†] |
| **Textoon** (Tongyi Lab, arXiv 2501.10020, 2025-01) | 파인튜닝 Qwen2.5-1.5B가 텍스트에서 부품 서술 추출(합성 640,000 쌍, 90% 이상), SDXL로 부품 이미지 생성, **고정 템플릿 Live2D의 부품 라이브러리(앞머리 3, 중간 3, 뒷머리 5, 상의 5 등)에 마스크로 텍스처 이식**, ARKit 52를 블렌드셰이프로 매핑 | 텍스트 → 1분 내 리깅된 Live2D | github.com/human3daigc/Textoon (235 star) | README 배지 Apache-2.0(GitHub 메타 라이선스 없음) | 템플릿 메시 위에 그림만 갈아 끼우는 방식이라 "자유 일러스트 → 리그" 문제와 다름 | [V†]/[V] |
| **Spiritus / Outline-and-Detail / Text2AC** | 텍스트+스케치 → 레이어 분할 캐릭터, shape-compatible 메시-스켈레톤 바인딩, Spine 호환 내보내기 / 범용 템플릿 기반 게임용 2D 에이전트 캐릭터 | 텍스트(+스케치) → Spine 스켈레톤 | 초록에 미표기 | 미표기 | Live2D 워프 디포머가 아니라 Spine식 본 | [V†]/[U] |

### 1.3 레이어 분해(입력 단계) 인접 연구

| 논문 | 요지 | 코드/라이선스 | img2live 관련도 | 검증 |
|---|---|---|---|---|
| Qwen-Image-Layered (2512.15603, 2025-12) | RGBA-VAE + VLD-MMDiT, 가변 레이어 RGBA 분해 (PSD 추출 데이터) | QwenLM/Qwen-Image-Layered (Apache-2.0 저장소; 논문은 CC BY 4.0) | Bunraku의 Stage 1 기반. See-through 대체 후보지만 애니 Live2D 분류 체계 없음 | [V†] |
| Stable-Layers (2605.30257) | Qwen-Image-Layered를 VLM 점수 + Flow-GRPO(LoRA)로 강화학습 | 코드 공개 여부 미확인 | VLM 점수를 보상으로 쓰는 패턴 참고 | [V†] |
| Workflow-Aware Structured Layer Decomposition (2603.14925) | 애니 일러스트를 선화/플랫/그림자/하이라이트 제작 레이어로 분해 | github zty0304/Anime-layer-decomposition (조회 시 404, 공개 여부 불명) | 리그용 분해가 아님(편집용) | [V†] |
| LayerPeeler 2505.23740, LayerD 2509.25134, PSDiffusion 2505.11468, ART 2502.18364 | 그래픽 디자인/벡터화/다층 생성 | 각 저장소 | 비애니 중심. 리그 직접 관련 없음 | [U] |
| 사용자가 언급한 "Anime2.5DRig", "AnimeGaussian", "Make-It-Move", "Joint-Image Rigging", "Cartoon Rig", "DeepRig(2D)" | Anime2.5DRig는 논문 없는 OSS. 나머지는 검색으로 해당 제목의 2D 리깅 논문을 **찾지 못함** | - | - | [U] |

### 1.4 머리 자세/표정 제어 단일 이미지 애니메이션 (비레이어형, 래스터 출력)

| 방법 | 요지 | 한계(img2live 관점) | 코드/라이선스 | 검증 |
|---|---|---|---|---|
| **Talking Head Anime 3/4** (Khungurn; THA4 arXiv 2311.17409, WACV 2025) | 애니 상반신 512x512 RGBA + 45차원 포즈 벡터로 새 이미지 생성. 전체 시스템 150ms/프레임, **캐릭터별 학생 모델로 증류**해야 실시간(2MB 미만, 30FPS+) | **학생 모델 학습에 RTX A6000로 약 30시간** (저장소 FAQ), PyTorch 모델은 브라우저에서 못 돌림(TF.js 변환 코드 비공개). 편집 가능한 레이어가 아님 | 저장소 MIT(THA4 355 star), 논문 CC BY-NC-SA 4.0. 가중치 라이선스 미확인 | [V]/[V†] |
| LivePortrait (2407.03168) | 암묵 키포인트 기반 초상 애니메이션 + 스티칭/리타게팅 | 사람/동물 모드. 애니 일러스트 품질 미검증. 기본 얼굴 검출이 InsightFace 계열(상업 제약 가능) | 코드 MIT(19k star) | [U] |
| AniPortrait, Hallo, X-Portrait, MagicPose, Animate-X(2410.10306) | 오디오/영상 구동 확산 기반 | 영상 출력, 편집 불가, 실시간/브라우저 재생 불가, 프레임 일관성 문제 | AniPortrait Apache-2.0, Hallo MIT, X-Portrait Apache-2.0, Animate-X Apache-2.0 | [U] |
| Animated Drawings (Smith et al., 2303.12741) | 아이 그림 → 분할·스켈레톤·rigging·twisted perspective retargeting. See-through가 이 파이프라인에 통합해 "찢어짐 감소" 시연 | 본 기반 리그, 얼굴 표정/머리 회전 없음 | 저장소 MIT(아카이브됨) | [V†]/[V] |
| From Rigging to Waving (2509.06573), DrawingSpinUp (2409.08615) | 손그림 캐릭터의 스켈레탈 + 확산 정제, 3D 애니메이션 | 비디오/3D 출력, Live2D식 파라미터 퍼펫 아님 | 각 저장소 | [V†]/[U] |
| View-Dependent Formulation of 2.5D Cartoon Models (Fukusato, 2103.15472) | **여러 시점의 2D 그림을 보간**해 아웃오브플레인 회전 | 입력으로 키 시점 손그림이 필요 → 생성 키프레임 방식의 이론적 근거 | - | [V†] |
| Puppet-Master (2408.04631), AnyMoLe (2503.08417) | 드래그/모션 인비트위닝용 비디오 확산 | 3D/렌더 캐릭터 대상. 2D 퍼펫 파이프라인과 거리 있음 | 각 저장소 | [V†] |
| 3D 리깅(RigAnything 2502.09615, UniRig 2504.12451, HumanRig 2412.02317, ASMR 2503.13579, APES 2206.02015(스프라이트 시트 관절 부품 추출), DRiVE 2411.17423) | 3D 메시/가우시안 스켈레톤·스키닝 | **2D 키폼 리그에 직접 이식 불가**(참고만) | 다양 | [V†]/[U] |

**문헌 종합**: (1) 레이어 분해는 학계가 강하고(See-through, Qwen-Image-Layered, Bunraku Stage 1), (2) 리깅은 "템플릿 기반"(Textoon, CartoonAlive) 또는 "학습 변위 회귀"(Bunraku, 미공개)뿐이며, (3) 구조화된 결정론적 리그 컴파일은 학계가 아니라 **OSS 커뮤니티**가 앞서 있다.

---

## 2. 커뮤니티 OSS와 상용 도구 조사

### 2.1 한눈에 비교 (GitHub 메타는 2026-10-02 `gh api` 조회 [V])

| 도구 | star / 라이선스 / 최종 push | 입력 → 출력 | 런타임 | 리깅 방식 |
|---|---|---|---|---|
| **psd2live** (tsunehimatoi) | 529 / GPL-3.0 / 2026-10-02 (생성 2026-09-03, 463 커밋) | 레이어 PSD → `.moc3` + `.model3.json` + `physics3`/`motion3`/`cdi3` + `.cmo3`(Cubism 3.0-5.0 타깃, 기본 5.0) | Kotlin/JDK 21, GUI(Compose) + **헤드리스 CLI**, 내장 CPU/OpenGL 렌더러, Cubism Native 미리보기는 선택 | 레이어 이름 분류 → 적응형 메시 → 머리/몸/이목구비 디포머 + 키폼 → 물리 → 모션. MCP 서버(공개 도구 25-26개) |
| **StretchyStudio** (MangoLion) | 494 / MIT / **2026-04-28 이후 정체**(최종 커밋 2026-04-27, 열린 이슈 5개 중 내보내기 메뉴 크래시 2026-09-21) | See-through PSD → 자체 `.stretch`, **Spine 4.0 JSON**, 소스 안에 **Live2D `.moc3`/`.cmo3`/`.can3`/`motion3` 내보내기**(랜딩 페이지에는 언급 없음) | 브라우저(Vite+React+WebGL), onnxruntime-web으로 DWPose | Hiyori 구조를 역공학한 템플릿 + 레이어 기하 측정 기반 자동 리그(`generateRig`) |
| **Anime2.5DRig** (852wa) | 233 / MIT / 2026-09-23 | 레이어 PSD(이름 규약) → 브라우저 재생 아바타, PNG/WebM/MP4 녹화, OBS | WebGL1 순수 JS(ag-psd, MediaPipe FaceMesh로 웹캠 추적) | **Live2D 형식이 아닌 자체 런타임.** 레이어별 깊이 시차 + 전단, 스트랜드 스프링 물리, 눈 크로스페이드 |
| **PNGAL** (1mm-module) | 353 / Apache-2.0 / 2026-09-01 | 투명 PNG 또는 PSD → PSD/WebM/MP4/GIF/스프라이트 시트 | Windows 로컬(ComfyUI 번들, VRAM 12GB+) | Qwen 이미지 편집으로 눈/입 변형 생성 + See-through 분할 + RIFE 보간. 본 리깅 없음 |
| **PachiPakuGen** (kazuya-bros) | 130 / MIT / 2026-09-21 | 서 있는 그림 1장 + 표정 소재 7장 → SpriTalk 소재, 루프 애니, 라이브 표시 | Windows 데스크톱 | 7장(eyes-closed, mouth-closed, a/i/u/e/o)을 See-through에 함께 넣어 부품 구성 + RIFE |
| **ComfyUI-See-through** (jtydhr88) | 814 / 라이선스 미표기 / 2026-08-20 | 이미지 → 레이어 PNG + 깊이 + 브라우저 PSD | ComfyUI 노드 | 분해만 |
| **image-to-live2d** (lvhaojie456) | 2 / MIT(+GPL 파생 파일) / 2026-09-22 | 프롬프트 또는 이미지 → `.moc3`, atlas, physics3, 6개 motion3, `.cmo3`, 정리된 PSD, 검증 보고서 | 제작 호스트 macOS/Windows(Cubism Core JNI 때문) + GPU 호스트 Linux 24GB | 9단계(생성 → 배경 중립화 → VLM 계획 → See-through → 누수 클립 → 표정 생성 → 정리 → psd2live 리그 → Core 370포즈 검증) + **감독(VLM) 루프** |
| live2d-agent-kit (Ariakage) | 19 / MIT + GPL 일부 / 2026-09-12 | 참조 이미지/PSD → moc3, Core/WebGL 검증, 4x 업스케일 | Node/Java/Python | psd2live 고정 커밋 + 누적 패치, 웹 미리보기 + 웹캠 추적 |
| 그 외 파이프라인 | seethrough-live2d-pipeline(Kota-Ohno, 8 star, MIT), jpg-to-live2d-workflow(flowingduskpro, Windows), lk2168/vtuber-pipeline, Sheeber-2024/live2d-pipeline(웹 서비스), daoming07280/live2d-auto-pipeline, 7l-ui/whalegirl-pet, naiyouj/live2d-ai-generator, kumakitiho/live2d-cubism-agent-lab | See-through → psd2live 연결층 | 다양 | 검색 결과 수준만 확인(README 일부는 읽음) [U] |
| Auto-live2D-beta (lTwTlol) | 27 / MIT | Anime2.5DRig 2차 개발(README에 명시) | 브라우저 | Anime2.5DRig와 동일 계열 |
| psd-motion-lab (shinshin86) | 5 / 라이선스 미표기 | 9방향 준비 이미지 + 메시 + RIFE로 4,225장(222MB) 중간 이미지 | macOS, Python | **생성/준비된 9방향 그림 + 보간** 방식의 소규모 시연. PSD에서 9방향을 자동 생성하지는 않음 |
| Rev2D (RevStudio) | 3 / MIT / 2026-09-25 | **리그 = JSON 파일 하나**, 결정론적 헤드리스 렌더러, 검증·렌더·시트·측정·ops CLI + MCP 16도구 | Node 22, 브라우저 에디터 | 에이전트 구동용 자체 형식. 매우 초기 |
| inochi-agent-tools (MohamedXIV) | 0 / 미표기 | Inochi2D 퍼펫 헤드리스 저작 도구, v2 로드맵 "레이어 자산 + 의미 리그 스펙 → 결정론적 빌드 → QA → 한정된 자동 수리" | D 브리지 + Node | 설계 원칙 참고용(진행 중) |
| PurismCore (SakuraMotion) | 39 / MIT / 2026-08-21 | Cubism Core의 오픈 재구현(C99, WASM 빌드 포함, Cubism Core 5 ABI와 6 ABI) | 네이티브/Emscripten | 런타임 대체재 후보. "동작 차이 없음"은 프로젝트 주장일 뿐 미검증 |
| Umamo (umamoorg) | 145 / GPL-3.0 / 2026-10-02 | CMO3/MOC3 가져오기·내보내기, 오픈 리깅 에디터(psd2live가 일부 모듈 통합) | Kotlin | 초기 단계. 애니메이션 없음 |
| py-moc3 (Ludentes) | 4 / MIT | moc3 바이너리 읽기/쓰기(Python) | Python | StretchyStudio가 moc3 레이아웃의 권위 참고로 사용 |

### 2.2 psd2live 심층 (직접 소스 열람 + 직접 실행 [V])

- **규격**: 레이어 이름(영/중/일 별칭, NFKC 정규화, `-l`/`-r`, 번호 접미사)으로 `LayerClassifier`가 태그 분류. 태그 목록은 See-through V3 23종과 거의 일치(`back hair`, `front hair`, `headwear`, `face`, `facedetail`, `irides`, `eyebrow`, `eyewhite`, `eyelash`, `eye_close`, `eyewear`, `ears`, `earwear`, `nose`, `mouth`, `mouth_open`, `mouth_close`, `tooth-t`, `tooth-b`, `tongue`, `neck`, `neckwear`, `topwear`, `handwear`, `bottomwear`, `legwear`, `footwear`, `tail`, `wings`, `objects`). 알 수 없는 이름은 버리지 않고 `UNKNOWN`으로 보존해 위치로 추정. 같은 모양의 좌우 부품은 메시가 두 연결 성분이면 자동 분리.
- **요구 소재**: 눈흰자/홍채/위 속눈썹 분리 + 눈꺼풀에 가려진 홍채 부분 보존, **완전히 벌린 입**(또는 위/아래 치아+혀 분리), 앞/뒤 머리 분리, 몸이 대체로 정립. 아래 속눈썹 리그는 지원하지 않음. 입 내부는 "기하로 복원 불가"라고 문서에 명시. [S40]
- **메시**: `AdaptiveMeshGenerator` — 알파 윤곽 기반 제약 메시, 베지어 안내선 주변 윤곽 행 밴드(얇은 리본형은 spine path), 등급화된 내부(Poisson 샘플/구조적 채움), 홀 처리, 자기교차 검사. CLI `--mesh-spacing` 기본 64px, GUI 40px. [V: 소스 헤더, CLI 문서]
- **디포머 계층**(문서): `DeformBodyXY`(몸+목, 머리카락·다리 제외) → `DeformBodyLean` → `DeformBodyZBreath` → 머리 회전 → head-follow 컨테이너 → 얼굴 격자/윤곽/이목구비 변위. 앞/뒤 머리는 `...Follow` + `...Physics` 두 가닥. 선 서 있는 전신이면 `DeformLegs` 별도 루트(발은 어떤 몸 파라미터에도 안 움직임). 팔은 `DeformArmHang_L/R` 또는 스켈레톤(2본 IK, 자동 추론). 헤드리스 실행 JSON에서 `faceRig.algorithm = "perspective-parallelogram-nine-pose-v2"`, AngleX {-45,0,45} x AngleY {-30,0,30}. 소스 주석: "카메라 투영이 아니다. 표면 위치 T, 비대칭 볼륨 V, 시점 의존 재드로 S, 코너 상호작용 Cxy로 분해". 머리 초기 롤각은 `HeadOrientationEstimator`로 추정해 정렬 좌표계에서 변형 후 되돌림. [V: 소스, 문서, 실행 JSON]
- **기본 파라미터 20개**(실행 결과 cdi3): AngleX/Y/Z, BodyAngleX/Y/Z, BodyLean, Proportion(치비 비율), EyeL/ROpen, EyeBallX/Y/Form, BrowL/RY, MouthForm, MouthOpenY, Breath, HairFront, HairBack. 범위는 AngleX ±45, AngleY/Z ±30(Cubism 표준은 ±30), Eye 0..1 등. [V]
- **모션**: 12초 루프 idle(9개 커브: Breath, BodyAngleX/Y/Z, AngleX/Y/Z, EyeL/ROpen), blink(불규칙 간격 + 더블 블링크), nod, shake. 추가 프리셋(Wave, Cheer, Crouch, Shy 등)은 스켈레톤 사용 시. [V: 실행 결과 + MotionGenerator 소스]
- **물리 기본값**(소스): 뒷머리 pendulum 길이 15, mobility 0.95, delay 0.8, acceleration 1.5, 정규화 각도 ±30, 출력 scale 2.061 / 앞머리 길이 7.9, mobility 0.77, delay 1.45, acceleration 0.8, ±10, scale 1.522 / 입력 AngleX 60(X), AngleZ 60(Angle), BodyAngleX 40, BodyAngleZ 40 / "눈 젤리"(ParamEyeBallForm 출력, 2 세그먼트). 꼬리·날개는 몸 파라미터를 따르는 follow-through. [V: `PhysicsGenerator.kt`]
- **직접 실행 결과**: `./gradlew run --args="--input examples/tml/psd-input/tml.psd --output ..."` → 파일 11개(`tml.moc3` 306,944바이트 헤더 `MOC3` 버전 5, `model3.json`(EyeBlink/LipSync 그룹 포함), `physics3.json`(3 설정, 입력 10, 출력 3, 7 정점, 60fps), 모션 4종, `cdi3`, 4096 atlas 1장, `.cmo3` 4.9MB, 진단 JSON). 요약: 레이어 24, 드로어블 24, 디포머 29, 파라미터 20, atlas 1. 첫 빌드 2분 26초(의존성 다운로드 포함), 이후 실행 **벽시계 9.0초**(`--no-cmo3`, Gradle 기동 포함, 16코어 서버). **GPU/디스플레이 불필요.** [V: 직접 실행]
- **알려진 한계/불만**(이슈): 입 모양이 `.moc3` 내보내기에서만 변형(#5, 0.7.1), 얼굴/입 메시 범위 왜곡·부족(#14), 파라미터 저장·undo 불안정 보고(#14), Cubism Editor 5.3에서 `.cmo3`가 호환성 경고(image-to-live2d 문서), 같은 이름 레이어 중복 경고(실행 로그). MCP 에이전트 실측표(`docs/zh/STATUS.md`)는 "파라미터 조정 매우 좋음 / 소품 추가 가능 / 표정·모션 차이 간신히 / **머리카락 분리와 가림 영역 보완은 불가(gpt6-astra 3샘플)**"라고 스스로 기록. [V]
- **GPL-3.0**이며 Umamo(GPL-3.0) 모듈을 통합. Cubism SDK 바이너리는 포함하지 않고, 서드파티 고지에서 Stretchy Studio(MIT)를 "개념 영감"으로 언급. [V]

### 2.3 StretchyStudio 심층 (소스·문서 직접 열람 [V])

- **메시**: 알파 2px 팽창 → 윤곽 추적 → 둘레 비례로 가장자리 점 배분(기본 80점) → 내부 격자 샘플(간격 30px, 가장자리 패딩 8px) → 중복 제거 → **Delaunator(비제약 Delaunay)**. 비제약 삼각분할의 오목부 코드 단락은 "팽창으로 가려진다"고 주석에 적음.
- **리그 철학**: "툴 간 비교 결과 어떤 도구도 임의 스타일에서 PSD → 완성 리그를 달성하지 못한다"(AUTO_RIG_PLAN). 상수 43개 분석(14 bbox 상대, 16 정규화, 5 비율, 약 4개 미적 튜닝). 목표를 "80-90% 입력에서 허용 가능 + **안 될 때 정직하게 보고**"로 설정하고 `rig.log.json` 진단, 신뢰도(high/medium/low) 리포트, `rig.json` 오버라이드 파일을 계획.
- **눈 감김**: 메시 정점이 아니라 **레이어 PNG 알파를 아래에서 위로 스캔해 눈흰자의 실제 아래 윤곽**을 추출, X 균등 bin → 최대 Y → 최소제곱 포물선 적합, 눈 3종 메시를 그 곡선으로 수렴(P7/P12). 정점 기반 bin-max가 비제약 삼각분할의 내부 정점에 속아 ∩/∪ 방향을 뒤집는 버그를 발견.
- **얼굴 시차(AngleX/Y)**: 시행착오 기록 — 7개 워프(개별 이동)는 "각자 따로 움직인다"는 피드백, **Cubism은 워프끼리 보간하지 않으므로 하나의 얼굴 워프에 풍부한 공식**이 낫다. 이후 깊이 가중 타원체 → 눈 늘어짐 → **원통 돔**(Z가 U 방향만 변함), 이목구비 보호 영역(눈 0.95-1.0, 눈썹 0.5, 코/입 0.3, 얼굴/머리카락 0), 가장자리 깊이 하한(FP_EDGE_DEPTH_K=0.30), 좌우 대칭화, 먼 눈 찌그러뜨림, 목 코너 shapekey, `FP_DEPTH_AMP=3.0`. **See-through 깊이 PSD를 쓴 것이 더 나빠서 삭제**(Session 26). "단일 알고리즘이 대칭 정면 그림과 비대칭(그려진 기울임) 그림을 동시에 만족시키지 못한다"(Session 23).
- **Session 24 실패 기록**: AngleX에 2D 회전 디포머를 걸면 머리가 목에서 떨어져 턱 피벗 시소처럼 움직인다. 회전 디포머는 캔버스 Z축 회전(기울임)만 만들며 요(yaw)는 **워프 키폼만**으로 표현해야 한다.
- **좌표계 함정**(구현자에게 중요): 아트메시는 위치 배열이 2개(캔버스 픽셀: 텍스처용 / 부모 디포머 로컬: 렌더링용), **워프 로컬 공간 = 0..1**, **회전 디포머 로컬 프레임 = 자기 피벗 기준 캔버스 픽셀 오프셋**, 0..1 키폼은 소수 6자리 정밀도 필요(1자리면 텍스처가 "씹힌다"), 마스크 아트메시는 부모 디포머 체인에 키폼이 있어야 Cubism 경고가 사라짐, 키폼 바인딩 규칙(keys_count==keyform_count, Part는 null band).
- **물리**: `physics.js`가 Hiyori XML을 역공학한 3개 규칙(앞머리 y=3 mobility 0.95 delay 0.9, 뒷머리 y=15 delay 0.8, 스커트 y=10 delay 0.6)을 `CPhysicsSettingsSourceSet`로 방출. 출력 파라미터에 이미 워프 키폼이 있어야 움직임이 보이므로 규칙은 출력 바인딩이 있는 것만.
- **현황**: 마지막 커밋 2026-04-27 이후 정체, 작성자 본인이 "puppet warp 시스템을 Live2D식 워프 변형으로 대체"한다고 밝힘, 열린 이슈 5개. 기여자 fork(pelmentor)는 2026-06-19 push, star 3. **의존하기엔 유지보수 위험**이 있으나 문서화된 역공학 지식(MOC3_FORMAT.md, CMO3_FORMAT.md, WARP_DEFORMERS.md)은 매우 가치가 높다. [S42]

### 2.4 Anime2.5DRig 심층 (소스 열람 [V])

- 이름 규약은 See-through V3 태그와 호환(`mouth`→`mouth_open` 자동 리네임, `hair`는 얼굴보다 위면 앞머리·아래면 뒷머리). 닫힌 눈/닫힌 입이 없으면 **내장 `eye_close.psd`/`mouth_close.psd` 템플릿을 앵커에 맞춰 스케일·색 보정해 자동 생성**.
- 머리 회전: 정점마다 `x += hw*FS*(angleX*(14+40*(depth-1)) + angleX*(neckCy - y)*0.028)`, `y += hw*FS*(-angleY*(9+30*(depth-1)) - angleY*(depth-1)*(y-faceY)*0.05)` + 목 피벗 중심 회전. 깊이는 **PSD 순서가 아니라 레이어 이름 규약으로 초기화**(사용자 조정 가능). 순수 해석식, 신경망 없음.
- 머리카락 가닥 검출: 열별 불투명 최하단 y 프로파일 → 상자 평활(k=41) → **돌출도(prominence) 기반 피크 검출**(minProm 10, 최소 간격) → 레이어당 최대 6가닥(x, tipY, rootY), 뿌리는 단단하고 끝은 부드러운 2중 스프링. 이 알고리즘은 "머리카락 체인 자동 추정"의 가장 단순하고 검증된 구현이다.
- 알려진 한계(README): See-through 출력에서 목과 상의의 앞뒤 해결이 어려워 경계가 깨질 수 있어 "목을 상의에 합친 일체형"이 성공률이 높다고 권고. 입 열림은 "차분 전환 + 변형의 간이 표현".

### 2.5 Cubism/Spine/DragonBones/Inochi2D 자체의 자동화 기능 (Cubism 행은 공식 문서 페이지를 읽음 [V†], Spine/DragonBones/Inochi 행은 검색 스니펫 수준 [U])

| 도구 | 기능 | 한계 |
|---|---|---|
| **Cubism Editor 5.0** | 자동 메시 생성 정확도 개선(눈썹 같은 가늘고 긴 부품도 균일), 외곽/내부 밀도 조절 | 편집기 내부 기능, API 없음 |
| Cubism 5.0 "표정 움직임 자동 생성" | 얼굴 워프 디포머 생성 + AngleX/Y 키폼(및 네 모서리 폼) 알고리즘 생성. **AI 아님**(순수 알고리즘) | 정면 얼굴만, 사전에 얼굴/눈/눈썹/입 분리 부품과 워프 필요 |
| Cubism 5.1 "디포머 자동 생성"(AI) | 전신 휴머노이드의 고정 계층(Root, Chest, Shoulders, Arms, Forearms, Hands, Spine, Hips, Thighs, Calves, Feet) 배치를 ArtMesh 이미지에서 추정(nizima 작품 학습, 동의 하에) | **디포머 계층만. 파라미터/키폼은 생성 안 함.** 정면 직립 휴머노이드만, 치비/동물 부적합 |
| Cubism "흔들림 모션 자동 생성"(ML) | 워프 디포머의 위치/크기로 변형량 추정, 키폼 3개 생성(머리카락 흔들림, Z각 처짐). 가로·세로 크기, 부드러움, 확대 조절 | 워프 디포머만, 두 패턴만 |
| **Spine** | 메시에 처음 바인딩하는 본 집합에 자동 가중치, 위상(topography)을 고려하는 알고리즘, 선택 정점/본 한정 재계산(4.2에서 잠금 본 존중) | 본+가중치 모델, Live2D 워프/키폼과 다름. 런타임 라이선스는 별도(저장소 NOASSERTION) |
| **DragonBones** | Auto Boundary → Auto Mesh(밀도·정돈도), Auto Weight | 본 기반 |
| **Inochi Creator** | PSD 가져오기(그룹→노드, 픽셀 레이어→텍스처 파트), 오토메시(그리드, 외삽 알고리즘) | **자동 리깅 기능은 없음**(에이전트 툴 프로젝트가 개발 중) |

→ Cubism 자체의 자동 기능은 "편집기 안에서 사람이 누르는 보조"이고 프로그래밍 인터페이스가 없다. Cubism Editor 5.4 알파는 외부 앱 연동 API(WebSocket 22033)를 제공하고 MCP로 감싼 프로젝트(CubismExternalEditMCP, MIT, 42도구)가 있으나 **Windows/macOS 전용 + 편집기 라이선스**라 서버형 서비스에는 부적합. [S61]

### 2.6 moc3/model3.json을 프로그램으로 쓰는 프로젝트

- psd2live(Kotlin), StretchyStudio(`moc3writer.js` 921줄, V4.00 포맷 100+ 섹션), py-moc3(Python), Umamo(Kotlin). moc3는 공개 규격이 없고 Live2D CubismSpecs 저장소에는 `model3/physics3/motion3/cdi3/exp3/pose3/userdata3/motionsync3` JSON 명세만 있다. [V: CubismSpecs 목록] moc3 버전 호환성: Cubism 5.3 기본 내보내기(SDK 버전 6)는 VTube Studio가 못 읽고 `0x05`여야 함(Zenn 후기, 헤더 5번째 바이트). psd2live는 기본 5.0(실행 헤더 `05` 확인 [V]).

---

## 3. 기술 설계 분석 (문헌/OSS에서 도출한 구현안)

### 3a. 레이어별 메시 생성

**근거**: StretchyStudio(위 2.3), psd2live(적응형 제약 메시), Bunraku(55% 경계 예산, 3px 팽창, 알파>4/255), Cubism 5.0 자동 메시(가는 부품 균일화).

**권장 알고리즘 (named)**
1. 알파 이진화(임계 4-8/255) + 원형 구조 요소로 2-3px 팽창. (Stretchy 2px, Bunraku 3px — 흰 이음선 방지) → 윤곽 추출(Suzuki-Abe `findContours` 또는 marching squares), 홀(구멍) 보존 → Douglas-Peucker 단순화 → 호 길이 재샘플링.
2. 내부 점: Bridson **Poisson-disk** 샘플, 밀도장 = f(경계까지 거리, 부품 클래스, 곡률). 경계:내부 정점 예산 약 55:45(Bunraku).
3. 삼각분할은 **제약 Delaunay(CDT)**로 경계 선분을 강제(비제약 Delaunator는 오목부 코드 단락 때문에 팽창으로 땜질 중). 후보 라이브러리: CDT(artem-ogre), poly2tri, Triangle(상업 이용 라이선스 제약이 알려져 있어 확인 필요), earcut은 내부점 불가. 라이선스는 전부 확인하지 않음(UNVERIFIED). 
4. 후처리: 슬리버 제거(최소 각), 내부만 라플라시안 평활, 신주름/뒤집힘 검사(3g), UV = 아틀라스 좌표.
5. **부품 클래스별 밀도**: 눈/눈썹/입술/속눈썹은 가늘어서 리본형(spine 경로) 또는 윤곽 행 밴드, 머리카락은 가닥 방향 행, 얼굴은 이목구비 주변 조밀, 몸통/옷은 성김. **메시 간격은 부품 크기에 비례**해야 한다 — flowingduskpro는 "메시 간격 64 vs 32가 결과 동일, 부품(코/눈흰자/속눈썹/홍채)이 간격보다 작아서"라고 보고. [V†]
6. 해상도가 품질을 좌우: See-through 처리 해상도가 곧 PSD 캔버스이고 768px 처리에서 얼굴 레이어가 102x127px에 불과해 "정밀해 보이지 않음"의 원인이 됨. 512px면 `head` 레이어가 비어 머리 체인이 통째로 빠진다(flowingduskpro). [V†]

**실패 모드**: 눈/입 같은 소부품 메시 부족·왜곡(psd2live #14), 반투명 가장자리 헤일로가 부품 이동 시 더러운 테두리로 보임(업스케일 실험: 애니 ESRGAN 2종이 원화에서 멀어짐, RMSE 41→96/53 [V†]).

### 3b. 디포머 계층과 격자 배치

**참조 구조(Hiyori 역공학 [V], Stretchy)**: Body Z(캔버스 공간) → Body Y → Breath → Body X → [Face Rotation] → **FaceParallax(단일 워프)** → 눈/눈썹/코·입 워프. Hiyori의 50개 워프는 모두 5x5 격자(6x6 제어점), 얼굴 회전은 AngleX x AngleY 2D 격자(9 키폼), AngleZ는 회전 디포머가 아니라 머리카락 워프에 걸림. psd2live는 위 2.2의 계층(몸 3단 + 머리 컨테이너 + 앞/뒤 머리 follow+physics 분리 + 다리 별도 루트).

**랜드마크 대신 레이어 기하로 앵커를 얻는다 (권장)**: See-through 출력은 이미 `face`, `eyewhite`, `irides`, `eyelash`, `eyebrow`, `nose`, `mouth`, `neck`, `ears`가 분리돼 있어 앵커를 측정으로 얻을 수 있다.

| 앵커 | 산출 | 근거 |
|---|---|---|
| 얼굴 중심/반경 | `face` 레이어 bbox(+10% 패딩) | Stretchy/psd2live |
| 턱/머리 피벗 | **`face` 레이어 하단 + 목 상단**(머리+머리카락 합집합 bbox의 maxY를 턱으로 쓰면 턱 아래 104-151px, 얼굴 높이의 37-74% 어긋나 AngleZ가 목 아래 먼 점을 축으로 돎) | Stretchy AUTO_RIG_PLAN 실측 [V] |
| 눈 중심/닫힘선 | `eyewhite` 아래 윤곽(알파 스캔) + 포물선 적합 | Stretchy P7/P12 |
| 입 중심/폭 | `mouth` bbox, 열린 입은 변형 레이어의 윤곽 | psd2live `MouthCurve`(7점 두 베지어) |
| 초기 머리 롤 | 눈 중심선 기울기 등으로 추정, 정렬 좌표계에서 변형 후 복귀 | psd2live `HeadCoordinateSpace` [V] |
| 좌우 | 연결 성분 중심 기준 분할 | See-through `part_lr_split`, psd2live |

**애니 얼굴 랜드마크는 보조 검증용**: hysts/anime-face-detector는 HRNetV2 28점이고 "정면에 가까운 얼굴"만 검출 [V†]. MediaPipe는 사람 얼굴용이다(Anime2.5DRig는 웹캠 추적에만 사용). 분해가 `eyewhite`를 놓쳤을 때 교차 검증/대체 앵커로 쓰는 용도가 적절하다(설계 제안, UNVERIFIED).

**좌우 규약 주의**: See-through 코드 `part_lr_split`은 왼쪽(뷰어 기준) 성분에 `-r`, 오른쪽 성분에 `-l`을 붙여 **캐릭터 자신의 좌우 규약**을 따른다. [V: `common/utils/inference_utils.py`] 그런데 타 파이프라인(flowingduskpro)은 "See-through 출력의 맨 접미사 `eyewhitel`과 psd2live `-l/-r`이 거울상이라 12개 레이어가 `unknown`이 되고 눈 깜빡임·시선 바인딩이 깨진다"고 보고했다. [V†] → **구현 시 자체 테스트가 필수**: ParamEyeBallX를 돌려 두 눈이 같은 방향으로 움직이는지, ParamEyeLOpen이 올바른 눈을 닫는지 자동 점검.

**격자 해상도**: Hiyori 5x5 패치, 얼굴 6x6 제어점(Stretchy), psd2live 이목구비 변위 8x8(이슈 #14 답변). 격자가 이목구비 영역보다 성기면 영역 경계가 격자 한 칸보다 작아 근사 오차가 생겨, Stretchy는 보호 영역을 격자 한 칸만큼 확장(A.6b)해서 해결.

### 3c. 머리 각도 XYZ (핵심)

| 방식 | 실제 구현 | 장점 | 천장/실패 모드 | 판정 |
|---|---|---|---|---|
| (i) 깊이 구동 시차/워프 | Anime2.5DRig(레이어 깊이 + 전단), See-through 의사 깊이(Marigold) | 구현 단순, 학습 불필요, 레이어 단위 깊이는 견고 | **픽셀 단위 깊이는 노이즈로 해로움**: Stretchy가 See-through 깊이 PSD를 써 보고 더 나빠서 삭제. 얼굴 평면 전체를 한 방향으로 밀면 "마스크가 밀리는" 느낌, 귀/코 측면이 드러나지 않음 | 레이어 단위 깊이 순서로만 사용 |
| (ii) 3D 프록시 헤드 | Stretchy(깊이 가중 타원체 → **원통 돔** + 보호 영역 + 먼 눈 찌그러짐), psd2live(9포즈 격자 + 특징 보정 + 코너 항) | 학습 불필요, 대칭 정면 그림에서 안정, 파라미터 조정 쉬움 | 비대칭(그려진 기울임/3/4 시점) 그림에서 어긋남, 눈 늘어짐(보호 영역 필요), 목·머리 이음 찢어짐(목 코너 shapekey 필요), 큰 각도에서 새 윤곽(귀, 코 옆면)이 안 생김 | **기본 구현(Tier 1-2 경계)** |
| (iii) 생성 키프레임 | 공개 구현 없음. 부품: 이미지 편집 모델의 카메라 각도 LoRA(Qwen-Image-Edit 2511 "Multiple-Angles": 8방위, 높이 4단, 거리 3단 — 복잡한 캐릭터 측/후면 예측 부정확이라는 사용기), psd-motion-lab(손으로 준비한 9방향 그림 + 메시 + RIFE 4,225장 222MB), Fukusato 2.5D 시점 보간 | 윤곽/귀/코가 실제로 바뀌는 유일한 방법, 품질 상한 가장 높음 | 정체성/선 스타일 드리프트, 시점별 레이어 분할 불일치, **레이어별 정합 필요**(광류/대응점 → 메시 정점 변위 적합), 가림 해제, 비용/지연 | **R&D 트랙** |
| (iv) 신경망 와핑 | THA3/THA4 | 래스터 품질 높음 | 캐릭터별 증류 약 30시간, 브라우저 불가, 레이어 아님, 상반신 512 | 부적합(교사 모델 용도만 가능, UNVERIFIED) |
| (v) 학습된 정점 변위 | Bunraku Stage 2 | 레이어/부품 정체성 유지, 한 번에 전 레이어 | 코드/가중치 미공개, 방향 코사인 0.768, 62%만 0.80 이상, 눈/물리 미확인, 데이터가 병목(Live2D 8,884 모델은 우리에게 없음) | 추적하되 의존 금지 |

**수치 정리**
- Stretchy 최종 구조: 단일 FaceParallax 워프, 6x6 격자, `FP_DEPTH_AMP=3.0`, 가장자리 깊이 하한 0.30, 보호값(눈 0.95-1.00, 눈썹 0.5, 코/입 0.3, 얼굴/머리카락 0.0), 경험 상 증폭은 1.5배 이하(귀 3배는 얼굴 측면 25% 압축으로 실패).
- Cubism 표준 범위 ParamAngleX/Y/Z = ±30. psd2live는 X ±45로 더 크게 연다(자동 생성 결과가 큰 각도에서 안전한지는 별도 확인 필요, UNVERIFIED).
- 키폼 구조: AngleX x AngleY 3x3 = 9 키폼이 Hiyori 방식(Stretchy 문서) [V]. Cubism이 "네 모서리 폼 자동 생성" 기능을 따로 제공하는 것으로 보아 대각 조합이 축별 변형의 단순 합과 달라 별도 보정이 필요하다고 짐작되며, psd2live도 "코너 상호작용 항 Cxy"를 둔다 [V: 소스 주석]. (대각 항이 왜 필요한지에 대한 설명은 나의 추론, UNVERIFIED)

**제안 설계(Tier 2 후보, UNVERIFIED)**: ①기본 해석 리그(ii)를 항상 생성 → ②선택적으로 편집 모델로 ±20-30도 yaw/pitch **머리 영역** 뷰 4-8장 생성 → ③레이어 알파 안에서 광류 + 대응점 기반으로 각 레이어의 키폼 정점 변위를 ARAP/TPS로 정규화해 적합 → ④해석 리그 대비 오차/정체성 점수(VLM+임베딩)가 임계 이하일 때만 채택, 아니면 폴백. 미검증이므로 파일럿 후 판단.

### 3d. 눈 깜빡임, 입, 시선

**눈 열림**
- 기하 방식(Stretchy/psd2live): 위 속눈썹 + 눈흰자 + 홍채가 분리돼 있고 홍채의 가려진 부분이 보존돼 있을 때만 성립. 닫힘 곡선 = 눈흰자 실제 아래 윤곽의 포물선 적합(알파 스캔), 홍채/흰자는 곡선으로 수렴하고 속눈썹은 얇은 띠로 압축.
- 변형 레이어 방식(Anime2.5DRig/PNGAL/PachiPakuGen/image-to-live2d): 닫힌 눈 레이어를 크로스페이드. 닫힌 눈 소재가 없으면 템플릿 폴백(Anime2.5DRig) 또는 이미지 편집 모델로 생성(image-to-live2d: **마스크 편집 2회로 닫힌 눈/벌린 입 생성 → OpenCV로 입속·이빨·혀·눈꺼풀 측정**, 어두운 사진은 피부 정규화, 필요 시 MediaPipe 입술 안쪽 랜드마크로 폴백).
- 닫힌 눈이 드러내는 영역: 눈을 감으면 이마 아래 숨은 영역이 보여 **인페인팅 잔상/색 번짐**이 드러남 → 형태학적(blackhat/tophat) 국소 처리가 효과적이었고 광범위 인페인트는 실패(Zenn). [V†]

**입**
- 닫힌 입 그림은 기하로 입 안쪽을 만들 수 없다(psd2live 문서). 변형 레이어(열린 입 + 치아/혀)가 필수이고 `ParamMouthOpenY`는 크로스페이드/키폼 전환, `ParamMouthForm`은 입꼬리 곡선(psd2live: 입 곡선 7점 두 베지어, 폭/구경 정규화).
- **A-I-U-E-O**: Live2D 표준은 OpenY(0..1) x Form(-1..1) 2축이다. 모음은 이 평면의 점으로 매핑하는 것이 표준 모델과 호환됨(설계 제안, 값은 UNVERIFIED): A(1.0, 0), I(0.3, +1), U(0.3, -1), E(0.6, +0.5), O(0.7, -0.6). PachiPakuGen은 모음 5장을 **이미지 변형 레이어**로 생성해 RIFE로 프레임 보간하는 SpriTalk용 별도 경로. Live2D 호환을 원하면 모음 변형을 `MouthOpenY x Form` 키폼 격자의 조각 이미지로 쓰는 하이브리드가 가능(미검증).
- 눈 깜빡임/입 그룹은 `model3.json`의 `EyeBlink`, `LipSync` 그룹 ID로 표시해야 자동 깜빡임/립싱크가 동작(CubismSpecs, VTS 문서). [V]

**시선**: `ParamEyeBallX/Y`는 홍채 2D 균일 평행이동(Hiyori 기준 격자 폭의 약 9%, 높이의 약 7.5%), 눈흰자를 **클리핑 마스크**로 써서 홍채가 눈 밖으로 나가지 않게 함(Cubism 클리핑 ID; Anime2.5DRig는 마스크 텍스처 + 안티앨리어싱). 마스크 아트메시는 Cubism이 "Mask Artmeshes have problems" 경고를 내므로 같은 디포머 체인에 신원(identity) 키폼을 둬야 한다(Stretchy S28). [V]
"Eye jelly"(psd2live): 눈 열림 입력 → `ParamEyeBallForm` 출력 물리로 홍채 크기 흔들림.

### 3e. 머리카락/옷 물리와 호흡

**physics3.json 의미(공식 스키마 [V])**: `PhysicsSettings[]` 각각이 `Input[]`(Source 파라미터, Weight 0-100%, Type X|Angle, Reflect), `Output[]`(Destination, VertexIndex, Scale, Weight, Type, Reflect), `Vertices[]`(Position, Mobility, Delay, Acceleration, Radius), `Normalization`(Position/Angle의 Minimum/Default/Maximum). `Meta`에 PhysicsSettingCount, TotalInputCount, TotalOutputCount, VertexCount, Fps, EffectiveForces(Gravity, Wind). 물리 출력은 **이미 해당 파라미터에 키폼(워프/회전)이 걸려 있어야** 눈에 보이는 움직임이 된다.

**머리카락 체인 자동 추정 (권장)**
1. 가닥 후보: Anime2.5DRig 방식(열별 최하단 프로파일 → 평활 → 돌출도 피크) — 가장 단순, 가닥 수 상한(6) 필요.
2. 일반 형상: 머리카락 레이어 알파의 중심선(skeleton/medial axis) 또는 주성분축에서 뿌리(머리 윤곽과 닿는 쪽/레이어 상단)와 끝을 정하고, 뿌리→끝 측지 거리 L로 길이, `segments = clamp(round(L / (0.12 * 얼굴높이)), 1, 5)`. (설계 제안, UNVERIFIED.)
3. 키폼: 워프 행(row)마다 뿌리에서 거리의 제곱에 비례하는 변위로 끝만 크게(Stretchy "1D tips-swing, quadratic curl"; Cubism "흔들림 자동 생성"은 3키폼 + 부드러움/진폭 슬라이더).
4. pendulum 기본값은 위 2.2의 Hiyori 유래 값(앞머리 짧고 뻣뻣/뒷머리 길고 부드러움)에서 출발해 길이만 L에 비례해 조정.
5. 입력은 AngleX/AngleZ/BodyAngleX/BodyAngleZ, 출력은 ParamHairFront/Back(범위 ±1), 정규화 각도 앞머리 ±10 / 뒷머리 ±30.

**옷/장신구**: 스커트는 `ParamSkirt` + 하의 워프(Stretchy), psd2live는 헐렁한 옷만 시뮬레이션해 파라미터로 **베이크**(2D 천/머리카락 시뮬 → `ParamSim<id>_<k>` + 맞춤 pendulum, 적합 R^2 보고)하는 기능이 있다. 꼬리/날개는 몸 파라미터를 따르는 follow-through, 귀걸이는 pendulum.

**호흡**: `ParamBreath`는 가슴 압축 + 어깨 상승 + 아래로는 고정(Stretchy는 Hiyori보다 약 10배 강하게 해야 작은 캔버스에서 보임; psd2live는 그려진 어깨선/허리선 기준).

### 3f. 그리기 순서, 클리핑, 가려진 영역

- **순서의 출처**: See-through는 레이어 의사 깊이(depth_median)로 순서를 매기고 K-means로 같은 의미 부품의 깊이 지층을 나눈다(앞머리/뒷머리 분리 등). [V†] flowingduskpro는 `depth_median`으로 원거리→근거리 합성. Anime2.5DRig는 PSD 순서 대신 이름 기반 깊이. → 권장: 태그 기반 정준 순서(예: `back hair` < `body` < `neck` < `face` < 눈 계열 < `front hair` < `headwear`)를 기본으로 두고 See-through 깊이는 충돌 시 보조/검증용.
- **가림 영역**: See-through의 가장 큰 가치는 가려진 영역 인페인팅(앞머리 뒤 이마, 뒷머리, 치마 아래 다리)이며 "머리가 돌아갈 때도 유지된다"는 사용자 증언(Kota-Ohno, 주관) [V†]. 그러나 목-상의 경계, 손/팔 병합(2048px v2에서 팔이 몸통에 합쳐짐), 포니테일은 분리 실패(lilting 사용기, See-through 이슈 #14/#19/#25) [V†/V].
- **Draw order 키폼**(AngleY 극단에서 귀/머리 순서 교체): Stretchy가 검토 후 "현재 테스트 캐릭터에는 불필요"로 보류.
- **이음선 대책**: 사용자 보고에서 반복된 문제 — 앞머리 조각이 의복 픽셀을 머금어 머리와 같이 움직이는 현상, 큰 각도에서 목/머리카락 뿌리 잔상. 레이어 단계에서 오염 픽셀 제거와 **언더랩(겹침 여유)** 확보가 필요하며 업스케일은 그 후에 한다(live2d-agent-kit: "먼저 분해/마스크 수정, 그다음 초해상"). [V]
- **원본 픽셀 재투영**(Kota-Ohno): 가시 영역은 원본 일러스트 픽셀로, 생성 픽셀은 가려진 영역에만 쓴다(IoU 0.987 정렬). 선명도와 원화 충실도를 크게 개선. [V†] → 서비스 파이프라인 Step C의 핵심 후보.

### 3g. 리그 검증/QA 지표

**결정론적(수치) 지표 — 먼저 실행**

| 지표 | 정의 | 출처 |
|---|---|---|
| 삼각형 뒤집힘/붕괴 | 포즈 전후 부호 있는 면적 비 b/a, `<0`이면 flipped, `|ratio|<0.01`이면 collapsed, min/max 면적비, 최대 국소 변위 | psd2live `RigGeometryDiagnostics` [V] |
| 중립 포즈 경계 | 평가된 캔버스 공간 지오메트리와 PSD 레이어 bbox 비교(디포머 서브트리가 캔버스 밖으로 나가는 경우를 잡음), 비유한/붕괴 지오메트리는 실패 | `RigIntegrityValidator` [V] |
| 다포즈 샘플링 | 공식 Core로 370포즈 평가: 뒤집힌 삼각형 0, 발바닥 이동 < 0.25px | image-to-live2d [V] |
| 포즈 격자 | 192포즈(125 입 x 머리/몸 x 눈 조합), 202 네이티브 포즈, 22 웹 체크 | live2d-agent-kit [V] |
| 좌우 대칭/방향 | ParamEyeBallX 구동 시 두 눈 같은 방향, EyeLOpen이 올바른 눈을 닫음 | flowingduskpro "30초 점검" [V†] |
| 텍스처 신축 | 삼각형 면적비를 UV 면적과 비교해 확대 한계 초과 표시(설계 제안) | [U] |
| 실루엣 안정성 | 포즈별 합성 알파의 IoU/면적 변화, 발 고정 | [U] |
| 파라미터 상식 | 범위(AngleX/Y/Z ±30, EyeOpen 0..1 등 표준), 기본값 0/1, 키폼 수 == 바인딩 키 수, 비유한 값 금지 | CubismSpecs, Stretchy 규칙 [V] |
| 결정성 | 같은 입력이면 `.moc3`/`model3.json`/텍스처가 바이트 동일, `.cmo3`는 매번 해시가 달라짐 | flowingduskpro [V†] |

**VLM 심판(수치 통과 후)**: image-to-live2d의 설계가 가장 구체적이다 [V]:
- 증거: 원본 얼굴, **실제 내보낸 MOC**의 쌍눈 감김/단눈/반개구/전개구/웃는 입 조합/감은 눈 + 입 벌림, 신체·호흡·팔·치마 극단, 연속 몸/얼굴 프레임. 단계 게이트 썸네일 긴 변 384px, 최종 증거 시트 1536px. 비스트리밍 JSON, temperature 0, 타임아웃 90초 + 재시도 1, 최종 심사 최대 2200 토큰.
- 출력 스키마 v2: `identityPreserved`, `motionAdequate`, `score(0-1)`, `issues[{code, severity(minor|major|critical), part, detail}]`. **코드가 `passed`를 직접 계산하고 모델의 성공 표시를 믿지 않음**: 신원 유지 + 움직임 충분 + major/critical 없음이 모두 필요. 높은 점수가 심각 결함을 덮지 못함.
- **화이트리스트 수리 메뉴**: `eye_residual/eye_seam`(눈 위치 재검토·국소 재생성·커버리지 확대), `mouth_artifact/mouth_shape`, `identity_drift`(원본에서 재편집, 마스크 밖 원 픽셀 복원), `background_leak/layer_order`(재분해·클립), `joint_gap/motion_weak`(팔 알파로 지점 재추정·범위 조정·재바인딩), `other`(사람에게). 라운드 최대 3, 각 라운드 별도 보관, 개선이 없으면 롤백, 2라운드 무개선 정지, 감독 호출 24회 상한, 근거가 부족하면 `needs_review`로 **공개 불가**.
- 한계: 에이전트 MCP 실측(STATUS)에서 머리카락 분리/가림 보완은 "불가"였다. VLM 심판은 "이상 있음 판정"에는 쓸 만하나 "정점 수준 수리"는 안 된다.

### 3h. LLM/VLM 에이전트의 역할 분담

| 역할 | LLM/VLM이 하는 일 | 결정론적 코드가 하는 일 |
|---|---|---|
| 입력 검사/계획 | 정면 전신/애니 스타일/배경 판정, 얼굴/눈/입 사각형, 레이어 계획, 재그림 목록을 **엄격 JSON**으로(image-to-live2d 단계 3) | 크롭/중립 배경, 마스크 |
| 프롬프트 → 스펙 | 사용자 자유 텍스트를 구조화된 사양(표정 세트, 모션 스타일, 리그 강도)으로 | 스키마 검증, 기본값 채움, 범위 클램프 |
| 레이어 보정 | 잘못된 태그/좌우, 앞·뒤 머리, 포니테일 병합, 알 수 없는 레이어 분류 제안 | 알파/위치 기반 규칙, 연결 성분 분할, 앵커 계산 |
| 앵커 점검 | 오버레이 렌더를 보고 눈/입 앵커가 틀렸는지 판단 | 앵커 계산과 수정 적용 |
| QA | 증거 시트 판독, 결함 코드와 심각도 | `passed` 계산, 수리 실행, 롤백 |
| 모션 | 모션 스펙(파라미터 키 시퀀스) 작성 | motion3.json 컴파일, 클램프/루프 보장 |
| **하지 않음** | 정점 변위, 키폼 수치, 메시 | — |

근거: psd2live `AGENT_DESIGN`("Agent는 의도 이해/대상 선택/호출 계획/결과 관찰, 프로그램은 결정론적 소재/메시/파라미터/물리/이력"; "대량 정점을 추측시키지 말고 연속 변형/경로로 표현"), inochi-agent-tools v2 법칙("한 개의 의미 저작 권한, 숨은 두 번째 리깅 엔진 금지, 입력/설정/재빌드는 결정적, 자동 수리는 한정적·설명 가능·되돌릴 수 있고 예산이 있음"), Rev2D(검증 → 렌더 → 시트 → 측정 → 원자적 ops로 수리). Textoon은 소형 LLM(Qwen2.5-1.5B)을 640,000 합성 쌍으로 미세조정해 텍스트→부품 설명을 90% 이상 정확도·밀리초로 처리(템플릿형 좁은 도메인에서 유효). computer-use 에이전트가 Cubism Editor를 직접 조작하는 사례도 사용자 증언으로 보고(GPT-6 Astra, Kota-Ohno) [V†]되나 Windows/macOS GUI 의존이라 서비스에는 부적합.

---

## 4. 현실적 품질 천장과 티어

### 4.1 누가 무엇을 실제로 보여 줬나

| 사례 | 내용 | 한계(자체 기록) | 검증 |
|---|---|---|---|
| psd2live README `poses.webp`("예제 PSD 임포트 후 수동 수정 없는 자동 결과") | 좌/우/위/아래 5포즈, 얼굴·머리카락이 함께 움직이고 큰 이음 없음. 직접 렌더한 Idle/HeadTilt 시트에서도 자연스러운 섬네일 품질(내가 육안 확인, 2개 시트, 소부품 확대는 안 봄) | 포즈 폭은 비교적 작음. 예제 PSD는 사람이 규약에 맞춰 만든 것이지 See-through 출력이 아님 | [V] |
| StretchyStudio(MangoLion의 See-through 캐릭터 영상, 이슈 #8) | 자동 생성 디포머로 움직이는 캐릭터 시연 영상(영상은 직접 시청 못 함) | 문서상 "waifu.psd에서 모든 파라미터가 나쁘다"는 진단과 개선 이력, 최종 평가는 "decent/통과 가능" 수준 | [V]/[U] |
| live2d-agent-kit "Pink Sakura" | 24 소스 레이어 → 26 드로어블, 24 파라미터, 192-202 포즈 Core 검증, VTS는 사용자가 이전 버전만 확인 | **보수적 각도의 2D 바인딩**, 몸은 하나의 레이어(독립 팔/손가락 없음), "단일 그림에서 보이지 않는 눈꺼풀·입속·뒷머리·옷은 보완 필요", 초해상 후 가슴 앞 머리카락 이음 문제 등 반복 수리 | [V] |
| Kota-Ohno/Zenn | See-through → **수동** Cubism 리깅 → VTube Studio, 2일, GPU $4 | 분해 "뽑기" 변동(23레이어 vs 20레이어), 1024px 흐림, 팔이 몸통에 병합, 표정 변형 없음, "프로 리그와 동등하지 않음"(외주 시세 아트 4-10만엔 + 리깅 1-5만엔 인용) | [V†] |
| image-to-live2d | 프롬프트/이미지 → 초안 모델 + 감독 루프, 실패 시 `needs_review` | 닫힌 눈/열린 입은 두 편집 이미지로 측정한 값(연속 키폼 아님), `.cmo3` 재열기 미완전 검증, 사실 사진은 수염 그림자/어두운 배경에서 주로 실패 | [V] |
| flowingduskpro | 8GB VRAM에서 768px/30스텝 6분, 1024/30은 42분에도 미완 | "자동 바인딩은 '쓸 만함'이지 '전문가급'이 아님. 매뉴얼 대비 현저히 낮음" | [V†] |

### 4.2 사용자 불만 모음

- 분해 단계: 해상도에 따라 레이어 구조가 달라짐("분해 뽑기"), 포니테일 병합·머리 밖으로 나간 부분 손실, 신발 PSD 누락, 복잡한 프릴/치비/반투명 소재 실패, 레이어 중첩/생성 픽셀 침범(See-through 이슈 #40), 얼굴 디테일(#39). [V†/V]
- 리그 단계: 입이 안 열림(변형 레이어 부재), 눈 감을 때 이마 인페인트 잔상, 소부품 메시 왜곡, `.moc3` 내보내기에서만 입이 변형(psd2live #5), 목-몸통 경계 파손, 앞머리가 의복 픽셀을 머금음. [V†/V]
- 워크플로: PSD 쓰기 도구 차이로 Cubism이 "이름은 읽히는데 픽셀이 안 보이는" 상태(ag-psd로 재작성해 해결), moc3 SDK 버전 5/6 호환, 좌우 규약 불일치. [V†]
- 정책: nizima는 AI 일러스트 기반 Live2D의 마켓 판매/주문 납품 금지 → 제작자가 개인 사용으로 제한. [V†]

### 4.3 티어 (근거 기반 판단, 수치 확률은 근거 없어 제시하지 않음)

| 티어 | 내용 | 근거 | 현재 달성성 |
|---|---|---|---|
| **Tier 1** (현실적 MVP) | 눈 깜빡임 + 입 열림/닫힘(생성 변형 레이어 필수) + 호흡 + 앞/뒤 머리 흔들림 + **작은 머리 회전(±15도 정도의 시차)** + 시선 + idle | psd2live 기본 산출, Anime2.5DRig, Stretchy 모두 이 범위. 입력 일러스트가 정면 직립 단일 인물이라는 전제 | 분해 성공 시 자동 가능. **성공률 통계는 어디에도 공개되지 않음**(UNVERIFIED) |
| **Tier 2** | 전체 머리 XY(±30-45)의 그럴듯한 3D 느낌 + 표정 프리셋 + 몸 회전 + 팔 IK | 해석 모델로 일부(psd2live 9포즈, Stretchy). 윤곽 변화/귀/코 측면은 생성 시점이 필요 | 해석 모델 범위까지는 가능, **생성 키프레임 기반은 연구 필요** |
| **Tier 3** (프로급) | 134 메시/70 파라미터/104 디포머(Hiyori) 수준의 정교한 조합 파라미터, 미세 표정, 전신 동작, 손가락 | 누구도 자동으로 달성하지 못함. Stretchy: "어떤 도구도 인간 입력/학습 데이터 없이 못함", Cubism 자체도 보조 | 불가(현시점) |

**비교 수치**: Hiyori(134/104/70, 수작업) vs psd2live 예제(24/29/20 자동) vs Pink Sakura(26/24, 반자동 + 수동 수리). [V]

---

## 5. 모션 생성

### 5.1 현재 도구가 하는 것
- idle: psd2live 12초 루프(호흡, 몸/머리 각도, 불규칙 깜빡임 + 더블 블링크), nod/shake/blink 클립. `MotionPresetKnob`(id/min/max/default)으로 클립별 다이얼을 노출하고 MCP `motion` 도구가 `put/set_key/sample`을 제공. [V]
- 표정 프리셋: Anime2.5DRig 7종(보통, 웃음, 가는 눈, 놀람, 지토눈, 좌/우 윙크, 키 1-7). Live2D 쪽은 `exp3.json` + `model3.json` Expressions. Open-LLM-VTuber는 LLM이 `[joy]` 같은 태그를 내고 `model_dict.json`의 `emotionMap`으로 expression에 매핑. [V]/[V†]
- 립싱크: Cubism은 `LipSync` 그룹의 ParamMouthOpenY를 오디오 음량으로 구동. Rhubarb Lip Sync는 6 기본 + 3 확장 입 모양(A-F, G, H, X)을 오디오에서 산출[V†]. Rhubarb 입 모양 → (OpenY, Form) 매핑은 설계 사항(UNVERIFIED). Anime2.5DRig는 마이크 음량 립싱크 + 노이즈 게이트.

### 5.2 텍스트 프롬프트 → 모션
- **Live2D 리그에서 텍스트→모션을 다룬 공개 방법을 찾지 못했다**(검색 결과는 3D 스켈레톤: LLM의 rigged model 실시간 애니메이션 2310.17838 등 [U]). 
- **권장 구조(설계)**: LLM은 `{name, duration, loop, tracks:[{param, keys:[{t, v, ease}]}], fade}` 같은 **모션 스펙**만 작성 → 결정론적 컴파일러가 `motion3.json`(Segments: 0 선형, 1 3차 베지어(점 3개), 2 계단, 3 역계단; 첫 점 + 세그먼트 식별자 + 끝점의 평탄 배열; `FadeInTime/FadeOutTime`, `AreBeziersRestricted`, 합계 카운트 메타 필수) 생성 → 파라미터 범위 클램프, 가속/저크 제한, 루프 이음 보정 → 렌더/물리 시뮬레이션과 VLM 점검 → 실패하면 LLM에 수치 진단을 되돌려 재작성(최대 N회).
- 자유 텍스트 프롬프트가 현실적으로 제어할 수 있는 것: ①**모션 스타일/강도**(차분함, 장난스러움, 수줍음 — psd2live `rigTuning`: 머리 전환·눈·눈썹·입·머리카락·몸 회전/호흡 강도, CLI `--head-strength/--body-strength`), ②**표정 세트**(어떤 변형을 생성할지: 웃음, 윙크, 놀람, 눈 가늘게 — PNGAL "추가 표정", PachiPakuGen 7장), ③**리그 대상 선택**(꼬리/날개/귀 흔들기 유무, 치마 물리), ④**립싱크 사용 여부와 음성 모드**, ⑤**캐릭터 스타일 힌트**(이미지 생성형 입력일 때만: image-to-live2d 단계 1, Textoon).
- 프롬프트로 **제어할 수 없는 것**: See-through는 텍스트 조건이 없는 분해 모델이다(`VALID_BODY_PARTS` 커스터마이즈는 코드 수정이 필요, 이슈 #21). 어느 부품을 분리할지는 사후 휴리스틱(`heuristic_partseg.py`: 깊이 기반/좌우 분할) 또는 VLM 기반 재분류로만 가능. Bunraku의 Stage 1은 레이어별 캡션 조건(드롭아웃 50%)이 있어 "부위 지시" 가능성이 있으나 미공개. [V]/[V†]

---

## 6. 라이선스/정책 위험 표

| 항목 | 내용 | 영향 | 검증 |
|---|---|---|---|
| Live2D Cubism Core/SDK | 독점 라이선스. "Business"는 연 매출 1,000만 엔 초과, 초과 시 출판 라이선스(소급). 파생물(Derivative Work) 정의가 넓음(소프트웨어를 사용해 개발한 앱·애니메이션 등). Core 재배포는 조건부(Redistributable 목록, 보호 약관 전달, 면책) | 브라우저에서 Cubism Core로 `.moc3`를 재생하는 상용 서비스는 계약 검토 필요 | [V†] |
| moc3 포맷 | 공개 규격 없음(커뮤니티 역공학). EULA 6.4는 소프트웨어 소스코드의 역공학 금지. **포맷 역공학/작성이 허용되는지는 별도 법률 판단**(요약 모델이 "moc3 생성을 막는다"고 해석했으나 과잉 해석 가능) | 자체 moc3 작성기를 만들 때 리스크 | [U] |
| 대체 런타임 | PurismCore(MIT, C99, Core 5/6 ABI, WASM 빌드)가 "라이선스 불필요"를 표방. Umamo(GPL-3.0), Inochi2D(BSD-2). 호환성/법적 안전성은 프로젝트 주장 | 자체 형식 + 자체 WebGL 런타임이 가장 법적으로 단순 | [V]/[U] |
| nizima AI 정책(2024-05-07) | AI 생성 일러스트 및 그에 기반한 Live2D 모델의 게시·판매·주문 납품 금지. Live2D는 "일러스트에서 모델링 전자동화" 연구를 하지 않는다고 명시 | 우리 서비스 산출물의 마켓 판매를 약관에서 금지/경고 | [V†] |
| See-through 가중치 | 코드 Apache-2.0. LayerDiff 3D/깊이 가중치는 Open RAIL(++) 계열, SAM 가중치는 Apache-2.0. 상업 사용 가능, **서비스 약관에 사용 제한 포함 필요**(저자 2026-09-28 이슈 #43 답변), 인용/표기 권장. 학습 데이터에 상용 Live2D 모델 포함 | 약관 전파, 데이터 출처 평판 리스크 | [V] |
| psd2live GPL-3.0 | 서버 측 실행(미배포)은 GPL을 트리거하지 않는다는 일반 해석(AGPL 아님)이나 수정·배포(내장 번들, 사용자에게 바이너리 제공)는 소스 공개 의무. Umamo(GPL-3.0) 모듈 통합, Cubism SDK는 비포함 | 서비스 내부 워커로 사용 시 비교적 안전, 내장 배포 시 위험 | [U] |
| 기타 | StretchyStudio MIT, Anime2.5DRig MIT, PNGAL Apache-2.0, PachiPakuGen MIT, Bunraku 논문 CC BY-NC-SA 4.0(코드 없음), THA4 코드 MIT/논문 CC BY-NC-SA, LivePortrait 코드 MIT(검출 의존성 별도 확인) | 선택 시 개별 확인 | [V]/[U] |

---

## 7. 권장 아키텍처와 로드맵

### 7.1 파이프라인

```
업로드(+프롬프트)
 [A] 입력 검사/계획 (VLM: 전신·정면·애니 여부, 얼굴/눈/입 박스, 표정 세트, 실패 시 거절/안내)
 [B] See-through 분해 (1280px, bf16 12-16GB VRAM, NF4 약 8GB; 논문 4090에서 분해 74초 + 깊이 10초(1024px), HF ZeroGPU 2-3분)
 [C] 레이어 QA/보정 (태그·좌우 정규화, 앞/뒤 머리, 아래 속눈썹 분리, 원본 픽셀 재투영, 알파 정리/오염 제거, 언더랩 확보, 목-상의 병합 옵션)
 [D] 변형 소재 합성 (닫힌 눈, 열린 입(+치아/혀), 모음 변형, 선택 표정; 이미지 편집 모델 + 마스크 + 측정/정합 + 정체성 점수)
 [E] 리그 컴파일러 (결정론적): 메시 → 디포머 계층 → 파라미터/키폼 → 물리 → 모션 → rig-spec JSON
        백엔드 1: psd2live CLI (moc3/model3/physics3/motion3/cmo3)
        백엔드 2: 자체 JSON 리그(웹 런타임)
 [F] QA 루프: 수치 지표 → 렌더 시트 → VLM 판정 → 화이트리스트 수리(최대 3라운드, 롤백, needs_review)
 [G] 웹 플레이어(자체 WebGL 또는 Cubism Core/PurismCore) + 내보내기
```

### 7.2 단계

| 단계 | 내용 | 기간(추정, 근거 없음 UNVERIFIED) |
|---|---|---|
| P0 | psd2live CLI를 서버 워커로 래핑(검증됨), See-through PSD 실제 입력으로 end-to-end 시험 + 좌우 규약/입·눈 변형 누락 점검 자동화, Core/VTS 로드 확인(이 조사에서 못 한 부분) | 며칠-2주 |
| P1 | [C]/[D] 구현(변형 소재 생성/측정, 원본 픽셀 재투영), [F] 수치 QA + VLM 판정 + 수리 메뉴. image-to-live2d의 감독 설계를 참고 | 수 주 |
| P2 | 자체 리그 컴파일러 + rig-spec JSON + 웹 런타임(Rev2D/Anime2.5DRig/Stretchy 렌더러 참고) → GPL/Cubism Core 의존 해소. Hiyori 역공학 지식(Stretchy 문서) 이식 | 수 개월 |
| P3 | Tier 2 R&D: 생성 키프레임 정합 파일럿, 비대칭 시점 대응, 학습형 변위(Bunraku 공개 시 재평가) | 연구 |

### 7.3 "build vs adopt" 판단
- psd2live: **채택 + 래핑**이 가장 빠르다(Tier 1 즉시). 위험: GPL-3.0, 프로젝트 속도(463 커밋/29일)에 따른 API 불안정, 한 사람의 프로젝트, 입/눈 소재 요구 사항.
- Stretchy: 코드 재사용보다 **역공학 문서와 알고리즘 노하우**(워프 좌표계, 원통 돔, 눈 닫힘 곡선)의 지식 원천. 업스트림 정체.
- Anime2.5DRig: **웹 런타임/해석식** 참고(MIT). Live2D 비호환.
- Cubism 고유 기능: 서버에서 쓸 수 없음.

---

## 8. 검증하지 못한 것 (정직한 목록)

1. psd2live가 만든 `.moc3`를 **Cubism Core/VTube Studio/Cubism Viewer에서 실제 로드하지 못했다**(Core 없음). 제3자 기록만 있다: image-to-live2d(공식 Core 370포즈), live2d-agent-kit(Native Core 6.0.257, 192포즈), flowingduskpro("공식 export와 비트 수준 차이는 검증 안 함" 명시). 내가 한 것은 파일 생성, 헤더(`MOC3` v5), JSON 구조 확인과 psd2live 내장 렌더러의 모션 시트 육안 확인까지다.
2. **See-through 실제 출력 PSD로 psd2live를 돌리지 못했다**(GPU 없음, 14GB 모델 미다운로드, 저장소에 샘플 PSD 없음). 시험은 psd2live 동봉 예제 `tml.psd`뿐이므로 See-through → psd2live 연결 품질은 제3자 증언(위 4.1)에 의존한다.
3. Bunraku 논문은 PDF가 너무 커서 HTML을 요약기로 읽었다(파라미터 8개의 이름 전체, 눈/물리 지원 여부는 확인 못 함, "본문에서 확인되지 않음"으로 표기). 코드 저장소는 직접 확인(스텁).
4. Reddit 스레드/X 게시물은 접근 불가(차단/402). StretchyStudio·Pink Sakura·MangoLion 시연 영상은 시청하지 못했다.
5. See-through를 인용하는 모든 논문의 완전한 목록은 만들지 못했다(Semantic Scholar 불완전, Google Scholar 불가). Spiritus/Text2AC/Outline-and-Detail, DrawingSpinUp, From Rigging to Waving, 3D 리깅 논문들은 초록 수준.
6. 사용자가 언급한 "Make-It-Move", "Joint-Image Rigging", "Cartoon Rig", "DeepRig(2D)", "AnimeGaussian"에 해당하는 2D 리깅 논문은 찾지 못했다. SkeletonDiffusion은 3D 인간 운동 예측이다.
7. 메시 라이브러리(CDT, Triangle, poly2tri) 라이선스, THA4 가중치 라이선스, LivePortrait 검출 의존성, Rhubarb → Live2D 파라미터 매핑, 머리카락 체인 추정 수식, 모음 매핑 값, 생성 키프레임 정합 설계는 모두 **설계 제안 또는 미확인**이다.
8. 법적 판단(GPL 서버 사용, Live2D EULA의 moc3 작성/재생, nizima 정책 적용 범위)은 법률 자문이 필요한 영역이며 이 문서는 근거 요약일 뿐이다.
9. psd2live 큰 각도(AngleX ±45)에서의 안전성, 눈 깜빡임/입의 시각 품질, 실패율 통계는 미측정.

---

## 9. 로컬 재현 자료 (임시, 세션 종료 시 사라질 수 있음)

- clone: `<scratch>}`
- psd2live CLI 산출물: `.../scratchpad/repos/p2l_out/tml/` (moc3, model3, physics3, motion3 4종, cmo3, 진단 JSON)
- psd2live 모션 시트(내장 렌더러, 헤드리스): `.../scratchpad/repos/psd2live/build/tools/motion-sheet/tml-*.png`
- 실행 명령: `./gradlew run --args="--input examples/tml/psd-input/tml.psd --output <dir>"` (JDK 21, GPU/디스플레이 불필요)
- 다운로드한 README 사본: `.../scratchpad/readmes/`

---

## 10. Sources

번호는 본문의 [S#]. 태그는 열람 방식.

**논문 / 프로젝트 페이지**
- S1 See-through arXiv: https://arxiv.org/abs/2602.03749 [V†]
- S2 See-through HTML: https://arxiv.org/html/2602.03749v1 [V†]; ACM: https://dl.acm.org/doi/10.1145/3799902.3811209
- S3 See-through 저장소(README, 코드 `common/utils/inference_utils.py`, `common/live2d/scrap_model.py`, 로컬 사본 `<local clone of see-through>`): https://github.com/shitagaki-lab/see-through [V]
- S4 See-through 이슈 #43(가중치 라이선스): https://github.com/shitagaki-lab/see-through/issues/43 [V]
- S5 See-through 이슈 #8(Image-to-Live2D?): https://github.com/shitagaki-lab/see-through/issues/8 [V]
- S6 Bunraku 초록: https://arxiv.org/abs/2607.27348 [V†]
- S7 Bunraku HTML: https://arxiv.org/html/2607.27348v1 [V†]
- S8 Bunraku 프로젝트 페이지: https://bunraku-live2d.github.io/ [V†]
- S9 Bunraku 저장소(스텁): https://github.com/SparcAI-Inc/Bunraku [V]
- S10 CartoonAlive: https://arxiv.org/abs/2507.17327 , https://arxiv.org/html/2507.17327 [V†]; 저장소 https://github.com/human3daigc/CartoonAlive
- S11 Textoon: https://arxiv.org/abs/2501.10020 , https://arxiv.org/html/2501.10020v1 [V†]
- S12 Textoon 저장소: https://github.com/human3daigc/Textoon [V]
- S13 Spiritus: https://arxiv.org/abs/2503.09127 [V†]
- S14 Outline and Detail: https://dl.acm.org/doi/10.1145/3746059.3747707 [U]
- S15 Text2AC: https://doi.org/10.1145/3613905.3651049 [U]
- S16 Qwen-Image-Layered: https://arxiv.org/abs/2512.15603 [V†]; https://github.com/QwenLM/Qwen-Image-Layered
- S17 Stable-Layers: https://arxiv.org/abs/2605.30257 [V†]
- S18 Workflow-Aware Structured Layer Decomposition: https://arxiv.org/abs/2603.14925 [V†]
- S19 LayerPeeler: https://arxiv.org/abs/2505.23740 [U]; S20 LayerD: https://arxiv.org/abs/2509.25134 [U]; S21 PSDiffusion: https://arxiv.org/abs/2505.11468 [U]; S22 ART: https://arxiv.org/abs/2502.18364 [U]
- S23 THA4: https://arxiv.org/abs/2311.17409 [V†]; WACV: https://openaccess.thecvf.com/content/WACV2025/papers/Khungurn_Talking_Head_Anime_4_Distillation_for_Real-Time_Performance_WACV_2025_paper.pdf
- S24 THA4 저장소 README(학생 모델 약 30시간, TF.js 변환 비공개): https://github.com/pkhungurn/talking-head-anime-4-demo [V]
- S25 LivePortrait: https://arxiv.org/abs/2407.03168 , https://github.com/KwaiVGI/LivePortrait [U]; S26 X-Portrait https://arxiv.org/abs/2403.15931; S27 Animate-X https://arxiv.org/abs/2410.10306; S28 MagicPose https://arxiv.org/abs/2311.12052; S29 AniPortrait https://github.com/Zejun-Yang/AniPortrait; S30 Hallo https://github.com/fudan-generative-vision/hallo [U]
- S31 Animated Drawings: https://arxiv.org/abs/2303.12741 [V†]; https://github.com/facebookresearch/AnimatedDrawings
- S32 From Rigging to Waving: https://arxiv.org/abs/2509.06573 [V†]; S33 DrawingSpinUp: https://arxiv.org/abs/2409.08615 [U]
- S34 View-Dependent Formulation of 2.5D Cartoon Models: https://arxiv.org/abs/2103.15472 [V†]
- S35 Puppet-Master: https://arxiv.org/abs/2408.04631 ; S36 AnyMoLe: https://arxiv.org/abs/2503.08417 [V†]
- S37 3D 리깅: RigAnything https://arxiv.org/abs/2502.09615 ; UniRig https://arxiv.org/abs/2504.12451 ; HumanRig https://arxiv.org/abs/2412.02317 ; ASMR https://arxiv.org/abs/2503.13579 ; APES https://arxiv.org/abs/2206.02015 ; DRiVE https://arxiv.org/abs/2411.17423 [U]
- S38 arXiv 검색: https://arxiv.org/search/?query=Live2D&searchtype=all&order=-announced_date_first&size=50 ; https://arxiv.org/search/?query=anime+layer+decomposition&searchtype=all&order=-announced_date_first&size=50 ; https://arxiv.org/search/?query=2D+character+rigging&searchtype=all&order=-announced_date_first&size=50 ; https://arxiv.org/search/?query=anime+head+pose+animation+single+image&searchtype=all&order=-announced_date_first&size=50 [V†]
- S39 Semantic Scholar 인용 API: https://api.semanticscholar.org/graph/v1/paper/arXiv:2602.03749/citations [V]

**OSS (저장소 clone / `gh api` 원문 열람)**
- S40 psd2live: https://github.com/tsunehimatoi/psd2live (README, docs/en|zh/spec, docs/zh/STATUS.md, docs/zh/agent/*, src/main/kotlin/io/github/psd2live/core/*, 직접 실행) [V]
- S41 psd2live 이슈 #5, #14, #15: https://github.com/tsunehimatoi/psd2live/issues [V]
- S42 StretchyStudio: https://github.com/MangoLion/stretchystudio (README, docs/live2d-export/{ARCHITECTURE,AUTO_RIG_PLAN,PROGRESS,WARP_DEFORMERS,head-angle-x-technique/TECHNIQUE,research/SYNTHESIS}.md, src/mesh/*, src/io/live2d/*, 이슈 #2, #6) [V]
- S43 Stretchy 사이트: https://stretchy.studio/ ; 에디터 https://editor.stretchy.studio [V†]
- S44 Anime2.5DRig: https://github.com/852wa/Anime2.5DRig (README, lib/rigger.js, lib/app.js) [V]
- S45 Auto-live2D-beta: https://github.com/lTwTlol/Auto-live2D-beta [V]
- S46 psd-motion-lab: https://github.com/shinshin86/psd-motion-lab [V]
- S47 PNGAL: https://github.com/1mm-module/PNGAL [V]
- S48 PachiPakuGen: https://github.com/kazuya-bros/PachiPakuGen [V]
- S49 ComfyUI-See-through: https://github.com/jtydhr88/ComfyUI-See-through [V]
- S50 image-to-live2d(README, docs/supervisor.md): https://github.com/lvhaojie456/image-to-live2d [V]
- S51 live2d-agent-kit(README, docs/case-study.md): https://github.com/Ariakage/live2d-agent-kit [V]
- S52 seethrough-live2d-pipeline: https://github.com/Kota-Ohno/seethrough-live2d-pipeline [V]
- S53 Zenn 제작 기록: https://zenn.dev/shakebenn/articles/e9b4c797d103ed [V†]
- S54 jpg-to-live2d-workflow: https://github.com/flowingduskpro/jpg-to-live2d-workflow [V]
- S55 기타 파이프라인(검색 결과 수준): https://github.com/lk2168/vtuber-pipeline , https://github.com/Sheeber-2024/live2d-pipeline , https://github.com/daoming07280/live2d-auto-pipeline , https://github.com/7l-ui/whalegirl-pet , https://github.com/naiyouj/live2d-ai-generator , https://github.com/kumakitiho/live2d-cubism-agent-lab [U]
- S56 PurismCore: https://github.com/SakuraMotion/PurismCore [V]
- S57 Umamo: https://github.com/umamoorg/umamo [V]
- S58 py-moc3: https://github.com/Ludentes/py-moc3 [V†]
- S59 Rev2D: https://github.com/RevStudio/Rev2D [V]
- S60 inochi-agent-tools(이슈 #41): https://github.com/MohamedXIV/inochi-agent-tools [V]
- S61 CubismExternalEditMCP: https://github.com/nana7chi/CubismExternalEditMCP [V]
- S62 Inochi2D: https://github.com/Inochi2D/inochi-creator , https://github.com/Inochi2D/inochi2d , https://github.com/Inochi2D/inox2d ; 문서 https://docs.inochi2d.com [U, 검색 스니펫 + GitHub 메타]
- S63 See-through 사용기: https://lilting.ch/en/articles/see-through-anime-layer-decomposition [V†]

**공식 문서**
- S64 Cubism 디포머 자동 생성: https://docs.live2d.com/en/cubism-editor-manual/auto-generation-of-deformer/ [V†]
- S65 Cubism 표정 움직임 자동 생성: https://docs.live2d.com/en/cubism-editor-manual/face-auto-edit/ [V†]
- S66 Cubism 흔들림 모션 자동 생성: https://docs.live2d.com/en/cubism-editor-manual/auto-generation-of-sway-motion/ [V†]
- S67 Cubism 5.0 신기능: https://docs.live2d.com/en/cubism-editor-manual/new-function5-0/ ; 5.1: https://docs.live2d.com/en/cubism-editor-manual/new-function5-1/ [V†]
- S68 표준 파라미터 목록: https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/ [V†]
- S69 CubismSpecs(physics3/motion3/model3 JSON 명세): https://github.com/Live2D/CubismSpecs/tree/master/FileFormats [V]
- S70 Live2D Proprietary Software License: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html [V†]
- S71 SDK 출판 라이선스: https://www.live2d.com/en/sdk/license/ [U]
- S72 nizima AI 정책: https://docs.nizima.com/guide/ai-policy/ [V†]
- S73 Live2D AI 연구 정책: https://docs.nizima.com/en/ai-research-policy/ [V†]
- S74 Spine 자동 가중치: http://en.esotericsoftware.com/blog/Automatic-skinning-weights , http://en.esotericsoftware.com/spine-weights [U, 검색 스니펫]
- S75 DragonBones: https://docs.egret.com/dragonbones/en/docs/dbPro/advancedFeatures/skinWeights [U]
- S76 Qwen-Image-Edit 2511 카메라 각도 LoRA 사용기: https://ordinaryanimator.com/blog/qwen-image-edit-2511-camera-angles [V†]
- S77 anime-face-detector: https://github.com/hysts/anime-face-detector [U]
- S78 Open-LLM-VTuber: https://github.com/Open-LLM-VTuber/Open-LLM-VTuber , https://docs.llmvtuber.com/en/docs/user-guide/live2d/ [U]
- S79 Rhubarb Lip Sync: https://github.com/DanielSWolf/rhubarb-lip-sync [U]
- S80 LLM 기반 rigged 모델 애니메이션(3D): https://arxiv.org/abs/2310.17838 [U]
- S82 본 조사의 직접 실행/열람 기록: 위 9장 경로, GitHub 메타데이터는 `gh api repos/<owner>/<repo>` (2026-10-02)
