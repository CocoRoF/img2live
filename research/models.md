> **정정 (2026-10-02, 원본 보고서 작성 후 직접 재확인):**
> 1. 아래 본문의 "Marigold·SAM 가중치 라이선스 이슈 #43 은 답이 없다"는 **틀렸다.** 2026-09-28 저자(ljsabc)가 "세 가중치 모두 상업 사용 OK, Open RAIL 2종은 서비스 약관에 사용 제한(단락 5, Attachment A) 포함 필요"라고 답했고 HF 카드 5개를 수정했다. → `plan/01-see-through-analysis.md` §5
> 2. Bunraku 코드·라이선스 "미확인"은 **확인됨:** GitHub `SparcAI-Inc/Bunraku` 는 README(722B) 한 장짜리 자리 표시자, LICENSE 없음, 코드·가중치 없음. → `plan/02-generative-models.md` §3
> 3. 본문의 수치·가격은 WebFetch(요약 모델 경유)로 읽은 것이 많다. 확정 전 원문 재확인.

# img2live 후보 생성 모델 조사 보고서 (기준일: 2026-10-02)

작성 방식: WebSearch + WebFetch 로 2026-10-02 에 직접 확인. 기억에 의존한 주장은 넣지 않았다.

## 0. 읽는 법과 신뢰도 표기

- **(V) VERIFIED** = 1차 출처(벤더 공식 문서·모델 카드·GitHub 저장소·arXiv·리더보드 원문 페이지)를 이번 세션에서 직접 열어 본 내용.
- **(U) UNVERIFIED** = 블로그·리셀러·집계 사이트·검색 결과 요약 같은 2차 출처, 또는 1차 출처가 막혀(403/404) 열지 못한 내용.
- 주의: WebFetch 는 페이지를 작은 모델이 요약해 돌려주는 방식이다. (V) 라도 수치(가격, 개수 상한)는 계약·설계 확정 전에 원문으로 한 번 더 확인할 것. 페이지끼리 서로 어긋난 곳은 본문에 "충돌"로 따로 적었다.
- 출처는 문서 끝 `Sources` 에 `[S번호]` 로 모았다.

---

## 1. 핵심 결론 (먼저 읽을 것)

1. **기준 논문(See-through)의 가중치·코드가 이미 공개돼 있고 상업 이용이 허용된다.** 코드 Apache-2.0, LayerDiff 3D·Marigold 가중치는 OpenRAIL++-M(상업 허용, 사용 제한 조항 적용), SAM 신체 파싱은 Apache-2.0 (V) [S75][S78][S79][S80]. 즉 "공개 생성 모델로 1단계(레이어 분해+인페인팅)를 할 수 있나" 의 답은 "된다. 애니 전용으로 이미 학습된 공개 모델이 있고, 범용 API 모델은 이 단계에서 그보다 낫다는 증거가 없다" 이다. 다만 Marigold·SAM 가중치의 라이선스는 저장소 이슈 #43(2026-09-28)에서 아직 답이 없다 (V) [S81].
2. **범용 API 중 "레이어 분해" 를 제품 기능으로 내놓은 곳은 ByteDance Seedream 5.0 Pro 하나뿐이다** (기본 이미지 + 투명 레이어 최대 16장, 가려진 배경 인페인팅) (V: BytePlus 개요) [S53]. 하지만 공개된 시험은 포스터·사진·명화였고 **애니 캐릭터 시험 결과는 찾지 못했다** (U) [S55]. 한 번 호출에 약 $0.75~$1.53, 약 77초라는 수치는 리셀러 값이다 (U) [S54].
3. **눈 감은 얼굴·입 모양(あいうえお) 같은 "부위 변형 생성" 은 지금 gpt-image-2.5-sunburst 가 편집 리더보드 1위**(Elo 1522, 2026-09-29) (V) [S50]. 그러나 OpenAI 자신의 가이드가 "픽셀이 그대로여야 하면 승인된 편집 결과를 원본에 합성하라, 프롬프트만 믿지 말라" 고 적고 있다 (V) [S8]. 설계는 **얼굴 크롭 → 편집 → 마스크로 원본에 합성** 이 되어야 한다.
4. **투명 배경(알파) 출력**: OpenAI 는 2026-08-20 부터 `background:"transparent"` 를 preview 로 제공 (V) [S6]. Gemini(Nano Banana) 문서에는 투명 PNG 언급이 없고, 2차 자료는 "알파 없음" 이라고 한다 (U) [S27]. Qwen-Image-2.1 은 네이티브 RGBA 이지만 **연구용(비상업) 라이선스** (V) [S44][S45]. NovelAI V5 도 네이티브 알파를 주장 (V: 공식 저널) [S73]. 단 OpenAI 편집 엔드포인트의 투명 출력은 "원본 윤곽을 따라 그린 것이 아니라 다시 그린 것" 이라는 보고가 있어(U) [S14], 분해 레이어를 서로 어긋남 없이 합치는 용도에는 못 쓴다.
5. **머리 회전(15°/30°) 생성은 측정된 근거가 거의 없다.** Qwen-Image-Edit-2511 Multiple-Angles LoRA(Apache-2.0, 96개 카메라 자세)는 있지만 학습 데이터가 "Gaussian Splatting 렌더 3,000+장" 이라는 것만 확인되고 대상(애니 여부)은 불명이다 (V) [S49]. Live2D 형태에서는 머리 회전을 **메시 변형(워프)** 으로 하고(Bunraku 의 keypose 방식) 새 시점 그림 생성은 하지 않는 편이 안전하다.
6. **Sora 2 는 2026-09-24 에 API 가 종료**됐고 대체 API 가 없다 (V) [S7]. 영상 쪽 보조 경로는 Veo 3.1(preview)·Seedance 2.0·Kling 3.0·Wan 2.7(Apache-2.0 오픈) 등이 남아 있다.
7. **자체 호스팅 가능한 상업 허용 오픈 가중치의 현재 최선**: 편집은 Qwen-Image-Edit-2511(Apache-2.0, 20B, 아레나 오픈소스 편집 4위), FLUX.2 klein 4B(Apache-2.0), HiDream-O1-Image(MIT, 8B); 레이어 분해는 See-through(애니)와 Qwen-Image-Layered(Apache-2.0, 범용). **조심**: Qwen-Image-2.1·FLUX.2 dev·klein 9B 는 비상업 라이선스다 (V).
8. **이 문제를 정확히 푸는 논문이 이미 있다: Bunraku(arXiv 2607.27348, 2026-07-29).** Qwen-Image-Layered 를 Live2D 10K 모델로 파인튜닝해 레이어 분해, 이어서 레이어별 메시와 keypose 변위 예측(5.1M 파라미터 트랜스포머, 리그 하나에 H800 약 1~3초)까지 한다 (V) [S88]. 저자 스스로 "병목은 1단계(분해)" 라고 쓴다. 코드 저장소(SparcAI-Inc/Bunraku)는 있으나 라이선스·가중치 공개 여부는 확인하지 못했다 (U).

---

## 2. 벤더별 현행 모델 (2026-10-02 기준)

### 2.1 OpenAI

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| 최신 이미지 모델 | `gpt-image-2.5-sunburst`(편집 정밀도 우선), `gpt-image-2.5-flare`(빠른 일상 생성). 기본 스냅샷 `...-2026-09-08`. 2026-09-08 출시 | V [S1][S2][S6] |
| 직전 세대 | `gpt-image-2`(스냅샷 2026-04-21), `gpt-image-1.5`, `gpt-image-1`, `gpt-image-1-mini`, `chatgpt-image-latest` | V [S3][S5] |
| 종료 일정 | `gpt-image-1-mini`·`gpt-image-1.5`·`chatgpt-image-latest` 는 **2026-12-01 종료**(대체: 2.5 두 모델). `dall-e-2/3` 는 2026-05-12 종료. 이번에 보인 종료 목록에 `gpt-image-1`, `gpt-image-2` 는 없음 | V [S7] |
| 엔드포인트 | `v1/images/generations`, `v1/images/edits`, `v1/batch` (Batch 는 약 50% 가격) | V [S1] |
| 가격(토큰제) | 2.5 두 모델 동일: 텍스트 입력 $5/M, 이미지 입력 $8/M, 이미지 출력 $30/M(Batch $15/M) | V [S1][S2] |
| 1024×1024 장당 추정 | low $0.006 / medium $0.013 / high $0.053 / xhigh $0.094 / max $0.211. 토큰 수(196/439/1,756/3,122/7,024)는 2차 자료, $30/M 로 곱한 값이 일치함. 편집이면 입력 이미지 토큰이 추가됨(크기별 토큰 수 미확인) | 요율 V, 토큰 수 U [S16] |
| 품질·크기 | quality: low/medium/high/xhigh/max/auto. 권장 1024², 1536×1024, 1024×1536. 임의 크기는 16의 배수, 비율 1:3~3:1, 한 변 최대 3840px | V [S4] |
| 속도 한도(기본) | Tier1 5 IPM·100K TPM … Tier4 150 IPM … Tier5 250 IPM·8M TPM | V [S1] |
| 투명 배경 | `background:"transparent"` + png/webp. **2026-08-20 preview 로 gpt-image-2 에 추가**, 가이드는 2.5 두 모델도 지원한다고 적음. JPEG 불가(400). 같은 품질에서 추가 토큰 없음 | V(변경 이력·가이드), 세부 U [S4][S6][S14] |
| 마스크 편집 | 알파 채널이 있는 마스크 지원, 단 "마스크의 정확한 모양을 완전히 따르지 않을 수 있음" | V [S4] |
| 참조 이미지 수 | 편집 호출당 최대 16장 | U [S13] |
| `input_fidelity` | gpt-image-2 는 항상 high 로 처리해 파라미터가 무시됨 | U [S13] |
| moderation | `auto` / `low` (덜 엄격) | V [S4] |
| LLM 의 네이티브 이미지 출력 | **없다.** Responses API 에서 LLM 이 `image_generation` 도구를 호출하는 구조이며 이미지 모델은 gpt-image-* 가 맡는다. 도구를 부를 수 있는 모델 목록은 페이지마다 달라(GPT-5.5/5.4/5.2 목록 vs 가이드 예시는 `gpt-6-astra`) 정확한 지원 목록은 확정하지 못함 | V(구조) / U(목록) [S4][S10] |
| 현행 LLM 이름 | GPT-6 계열(`gpt-6-astra`, `gpt-6.1-sol`, `gpt-6-luna`, `gpt-6-sol`), GPT-5.6 계열(`gpt-5.6-sol/terra/luna`) | V [S5] |
| 비디오 | Sora 2·Videos API **2026-09-24 종료**, 대체 없음. 소비자 Sora 앱도 종료 | V [S7] |
| 편집 아레나 | 2.5-sunburst 1위(1522±5), 2.5-flare 2위(1478), gpt-image-2(medium) 3위(1461) (2026-09-29) | V [S50] |
| 알려진 한계 | 반복 편집 시 보존해야 할 디테일이 바뀔 수 있음, 반복 등장 캐릭터 일관성 문제, 복잡한 프롬프트는 최대 2분, 텍스트 렌더링 불완전 | V [S4][S8] |

### 2.2 Google

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| Nano Banana 2 | `gemini-3.1-flash-image`, GA. 0.5K $0.045 / 1K $0.067 / 2K $0.101 / 4K $0.151. 2026-02-26 출시 | V [S17][S25] |
| Nano Banana 2 Lite | `gemini-3.1-flash-lite-image`, GA. 1K $0.0336, 1K 해상도만 지원 | V [S17][S18] |
| Nano Banana Pro | `gemini-3-pro-image`, GA. 1K/2K $0.134, 4K $0.24 | V [S17] |
| Nano Banana(1세대) | `gemini-2.5-flash-image` **오늘(2026-10-02) 종료 예정**으로 가격표에 표시. 모델 목록 페이지는 아직 "Stable" 로 적음(충돌) | V [S17][S20] |
| Imagen | Gemini API 에서 **종료됨**("Imagen models are shut down. Use Nano Banana") | V [S19][S20] |
| 해상도·비율 | 1K/2K/4K(+3.1 Flash 는 0.5K), 비율 10종(1:1, 3:2, 2:3, 3:4, 4:3, 4:5, 5:4, 9:16, 16:9, 21:9) | V [S18] |
| 참조 이미지 | 문서: 3.1 Flash는 사물 10+인물 4(+스타일 3), 3 Pro는 사물 6+인물 5, Lite는 총 14장. 블로그: 인물 5명 일관성·사물 14개. 서술이 서로 달라 상한은 확정 못 함 | V(충돌) [S18][S25] |
| 편집 방식 | 대화형 다회전 편집. **마스크 입력 파라미터는 문서에서 확인 못 함** (프롬프트 기반 편집) | V(문서에 없음) [S18] |
| 알파 | 문서에 투명 PNG 언급 없음. 2차 자료는 "RGB 만 만들고 알파가 없어 흰/검정/체크무늬 배경이 나온다, 흰·검정 배경 두 장 차이로 알파를 복원하는 우회법" 을 소개 | 문서 부재 V, 알파 없음 U [S18][S27] |
| 워터마크 | 모든 생성물에 SynthID, C2PA 콘텐츠 자격 증명 연동 | V [S18][S25] |
| 속도 한도 | 이미지 모델 배치 한도만 문서에 있음(Tier1 3.1 Flash 1M 토큰 등). 동시 요청 한도(RPM)는 AI Studio 에서 확인해야 함. Tier 승급은 지출 $100(Tier2)·$1,000(Tier3) + 경과일 | V [S26] |
| 비디오 | `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, `veo-3.1-lite-generate-preview` (모두 Preview) | V [S20][S22] |
| 아레나 | 편집: gemini-3-pro-image 10위(1390), 3.1-flash-image 12위(1387) | V [S50] |

### 2.3 Black Forest Labs

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| FLUX 3 Image | **2026-10-01 출시**. `api.bfl.ai/v1/flux-3-image`. 문서 가격 768sq $0.041 / 1K $0.048 / 2K $0.100 / 4K $0.607 (2차 자료는 "10-08 까지 50% 할인가" 라 함, 충돌). 바운딩 박스(0~1000 격자)로 편집 영역 지정, 참조 최대 10장, 최대 약 5,456×3,072. "영역 밖 픽셀은 bit-identical" 이라는 보도와 "대체로 동일" 이라는 보도가 갈림 → 벤더 주장, 독립 검증 없음 | 가격·출시일 V [S29][S30], 편집 성능 U [S38][S39] |
| FLUX 3 오픈 가중치 | Image 의 오픈 가중치판은 "수주 내" 예고만 있음(날짜 없음). FLUX 3 Dev 는 2026년 후반 예정. 현재 오픈된 FLUX 3 구성요소는 Action 체크포인트(로봇)뿐이라는 보도 | U [S37][S39] |
| FLUX.2 API | [klein 4B] $0.014, [klein 9B] $0.015, [pro] $0.03(편집 $0.045), [flex] $0.05, [max] $0.07 부터(해상도별 과금). [max] 는 2025-12-16 출시, 참조 10장 | V [S29][S30] |
| FLUX.2 오픈 가중치 | **klein 4B = Apache-2.0**(상업 OK, 약 13GB VRAM). **klein 9B·dev = FLUX Non-Commercial License**(상업은 BFL 별도 계약). 상업 라이선스: Builder(LoRA 권리, 월 1만 장, 단일 도메인), Platform(월 10만 장, SaaS 내장용), Professional, Enterprise | V [S31][S32][S33][S34] |
| LoRA 호스팅 | 2026-04-23 "bring your own LoRA" beta. klein 계열에 한해 로컬에서 학습(AI-Toolkit/Diffusers) 후 업로드, 요청당 LoRA 1개 | V [S30][S35] |
| 알파 | 릴리스 노트·문서에서 투명/알파 지원 언급 없음 | V(부재) [S30] |
| 조정 | `safety_tolerance` 로 필터 강도 조절(모델별 범위 다름), NSFW 플래그 반환 | U |

### 2.4 Alibaba Qwen

| 모델 | 날짜 | 접근 | 라이선스 | 비고 | 신뢰도 |
|---|---|---|---|---|---|
| Qwen-Image-Layered | 2025-12-19 | 오픈 가중치(HF) | Apache-2.0 | 20B, RGBA 가변 레이어 분해, 재귀 분해, 640 해상도 권장(1024 도 지원) | V [S41][S42] |
| Qwen-Image-Edit / -2509 / -2511 | 2025-08 / 09 / 12-23 | 오픈 가중치 | Apache-2.0 | 20B MMDiT. 아레나 오픈소스 편집: qwen-image-edit 3위(1241), 2511 4위(1234) | V [S40][S52] |
| Qwen-Image-2512 | 2025-12-31 | 오픈 가중치 | Apache-2.0 | 텍스트→이미지 갱신판 | V [S40] |
| Qwen-Image-2.0 / 2.0 Pro | 2026-02-10 | API 전용 | 독점 | 2.0 Pro 아레나 표기도 Proprietary. GitHub 요약은 Apache 로 보였으나 충돌 → 독점으로 취급 | U [S47][S51] |
| **Qwen-Image-2.1** | 2026-09-20 | 가중치 공개(HF) | **Qwen Research License = 연구/평가 목적 한정**, 상업은 model-business@notice.qwencloud.com 에 별도 신청 | 7B, 생성+편집 통합, **네이티브 RGBA**, 참조 최대 10장, 원·그림·마스크로 국소 편집, 2K. 편집 아레나 16위(1366) | V [S44][S45][S50] |
| Qwen-Image-3.0 / 3.0-pro | 2026 | API(Model Studio) | 독점 | 참조 1~3장, 512²~2048². 가격 약 $0.03~0.04 는 2차 | 사양 V, 가격 U [S48] |
| Multiple-Angles LoRA(2511용, fal) | 2026 초 | 오픈 | Apache-2.0 | 방위 8 × 고도 4 × 거리 3 = 96 자세, "3000+ Gaussian Splatting 렌더" 학습. 애니 시험 언급 없음 | V [S49] |

### 2.5 ByteDance

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| Seedream 5.0 Pro | 모델 ID `dola-seedream-5-0-pro-260628`, 2026-07-08 발표(BytePlus·Dreamina). 1K/1.5K/2K. 가격은 BytePlus 기준 2.36MP 까지 $0.045, 초과 $0.09, 첫 참조 무료·추가 참조 $0.003 | ID V [S53], 가격 U |
| Pro 전용 기능 | 좌표·점·박스 지정 편집, **레이어 분해(기본 이미지 + 최대 16 레이어, 위치·z순서·설명 포함)**, 다국어 텍스트. 배치·스트리밍 미지원 | V [S53] |
| 레이어 분해 세부 | 이미지 1장 입력, 레이어는 항상 PNG(알파), 가려진 배경은 인페인팅. 리셀러 가격 $0.75(1K/1.5K)~$1.53(2K)/회, 평균 약 77초. 공개 시험은 5~10 레이어(사진·명화), 머리카락·유리·가장자리는 검수 필요, 정상 이미지에서 제공자 검증 실패도 관측 | 기능 V, 가격·시험 U [S54][S55] |
| Seedream 5.0 Lite | `seedream-5-0-260128`, 2K/3K/4K, 약 $0.035 | ID V [S53], 가격 U |
| 편집 아레나 | seedream-5.0-pro 8위(1394) | V [S50] |
| 비디오 | Seedance 2.0: 아티피셜 애널리시스 I2V 1위(Elo 1,344), BytePlus 공식가 480p $0.07/s ~ 4K $0.78/s | U |

### 2.6 그 밖의 벤더

| 벤더·모델 | 접근 | 가격 | 핵심 | 신뢰도 |
|---|---|---|---|---|
| xAI(SpaceXAI) `grok-imagine-image-2.0` | API | $0.04/장(공식 문서), 편집은 입력 이미지당 +$0.01(2차), 6 req/s | 편집 아레나 4위(1427). 해상도·마스크 지원은 공식 페이지에서 확인 못 함 | 가격 V [S58], 나머지 U |
| Microsoft `MAI-Image-2.6` / `-Flash` | Foundry 공개 프리뷰 | 출력 $38/M 토큰(약 $0.039/장) | 편집 5위(1427) | U [S68] |
| Meta `muse-image-1.0` | Meta Model API | $0.01/장, 독점(오픈 아님) | 2026-08-26 출시, 편집 6위(1403) | U [S67] |
| Reve 2.1 | API | 편집 $0.24/건(리셀러), 공식가 불일치 | 편집 14위(1374) | U [S69] |
| Ideogram 4.5 | API(`precise-edit/ideogram-4-5`) | 품질별 과금(dry_run 으로 견적) | 2026-09-30 출시. 마스크 지원(검정=편집·흰색=유지), 참조 4장(마스크 사용 시 3장), "의미 있게 안 바뀐 픽셀은 원본에서 그대로 복사". 오픈 가중치 "곧". 편집 18위(1351) | 문서 V [S61], 출시·오픈 U [S62] |
| Ideogram 4.0 | 오픈 가중치(2026-06-03) | - | 9.3B, 비상업 + 상업은 별도 라이선스 | U [S62] |
| Midjourney V8.2 | 웹·Discord만, **공식 API 없음** | 구독 | 2026-08-27 편집 모델(참조 4장, 인페인팅·아웃페인팅) 전체 공개 | U [S63] |
| Adobe Firefly Image 5 | Firefly Services API(기본 4 req/min·9,000 req/day) | 크레딧 | "레이어 편집" 은 2025-10 개발 중이라 했고 현 상태 확인 못 함. 타사 모델 25~30여 종 중개 | U [S64] |
| Recraft V4 / V4.1 | API | Vector $0.08, Pro Vector $0.30 등 | SVG 출력, 배경 제거 약 $0.011 | U [S65] |
| Stability SD 3.5 | 오픈 가중치 | - | 2024-10 이후 후속 없음, Community License(연 매출 $1M 미만 무료) | U [S66] |
| Tencent Hy Image 3.5 preview | Tencent Cloud API | 약 $0.024/장 | 2026-09-22, 폐쇄, 오픈 계획 없음. 3.0(80B MoE)은 Tencent Community License(EU·UK·한국 제외) | U [S70] |
| HiDream-O1-Image | 오픈 가중치 | - | **MIT**, 8B, VAE 없는 픽셀 공간 통합 트랜스포머, 참조 최대 10장, 2026-05-08 | V [S71] |
| LongCat-Image(-Edit) | 오픈 가중치 | - | Meituan, 6B, Apache-2.0 | U [S72] |
| Z-Image / Z-Image-Edit | 오픈 가중치 | - | Tongyi-MAI, Apache-2.0, 6B 계열 | U [S106] |
| NovelAI Diffusion V5 | 구독 내 REST | Anlas 크레딧 | 2026-08-21, **네이티브 알파**, 인페인팅(Full), 22 캐릭터 배치. 래퍼 기준 Director Tools 에 24가지 표정 변경 | 기능 V [S73], 도구·약관 U [S74] |
| Luma Uni-1.1-max | API | - | 편집 19위(1334) | U [S50] |

### 2.7 아레나 순위로 본 현재 지형 (V)

- 편집(2026-09-29, 투표 30.8M): 1~3위 OpenAI(2.5-sunburst, 2.5-flare, gpt-image-2), 4 grok-imagine-image-2.0, 5 MAI-Image-2.6, 6 Meta Muse Image, 8 Seedream 5.0 Pro, 10 Nano Banana Pro, 12 Nano Banana 2, 16 Qwen-Image-2.1(오픈 중 최고, 비상업) [S50].
- 오픈소스 필터: Qwen-Image-Edit 1241, Qwen-Image-Edit-2511 1234, FLUX.2-klein-4B 1187, BAGEL 1027, Step1X-Edit 998 [S52]. 상업 이용 가능한 오픈 가중치로는 Qwen-Image-Edit 계열이 앞서 있다. 위 점수는 일반 이미지 편집 선호도이고 **애니 부위 변형 성능은 따로 측정된 것이 없다.**
- FLUX 3 Image 는 어제 출시라 순위 없음 [S39].

---

## 3. 능력별 평가

### 3a. 네이티브 투명 배경(RGBA)

| 모델 | 진짜 알파? | 근거 |
|---|---|---|
| gpt-image-2 / 2.5 | 예(preview). 편집에서는 "다시 그린" 결과라 윤곽이 원본과 달라질 수 있음, 머리카락·유리·그림자 가장자리 검사 필요 | V(변경 이력·가이드) / U(재그림 주장) [S4][S6][S14][S15] |
| Gemini 3.x Image | 문서상 언급 없음, 2차 자료는 알파 없음 | V(부재) / U [S18][S27] |
| Qwen-Image-2.1 | 예(RGBA 생성·편집), 비상업 라이선스 | V [S44] |
| NovelAI V5 | 예(주장) | V [S73] |
| Qwen-Image-Layered, See-through(LayerDiffuse 계열), Seedream 레이어 분해 | 예(레이어 출력이 RGBA/PNG) | V [S41][S75][S53] |
| FLUX.2/3, Seedream 일반 생성, Grok, Ideogram 4.5 | 문서에서 확인 못 함 | V(부재) |
| Recraft | SVG 출력, 배경색 지정·별도 배경 제거 | U [S65] |

### 3b. 레이어 분해 모델 전수 (공개·논문, 2026-10 기준 확인된 것)

| 모델 | 출처·시기 | 입력 → 출력 | 레이어 수 | 라이선스 | VRAM·속도 | 애니 캐릭터 품질 |
|---|---|---|---|---|---|---|
| **See-through (V3)** | SIGGRAPH 2026, arXiv 2602.03749, 코드·학습 스크립트 2026-04-14 | 애니 일러스트 1장 → 인페인팅된 RGBA 레이어 + 그리기 순서 + 의사 깊이, PSD 출력 | 최대 **23** (19 신체 부위 + 층분리) | 코드 Apache-2.0, 가중치 OpenRAIL++-M(SDXL·LayerDiffuse·Animagine XL 4.0 계승), SAM 파싱 Apache-2.0 | bf16 약 12~16GB(1280px), NF4 약 8GB. 논문 기준 1024²당 약 74초 + 깊이 10초 | 직접 목적. 아래 3b-1 참고 | V [S75][S77][S78] |
| **Bunraku** | arXiv 2607.27348 (2026-07-29) | 일러스트 → 순서 있는 RGBA 레이어 → 레이어별 메시 → keypose 변위(Live2D 파라미터) | 예: 10~63 레이어 | 논문 CC BY-NC-SA 4.0(논문 자체), **코드·가중치 라이선스 미확인** | Stage2 H800 0.7~2.8초 | Qwen-Image-Layered 를 Live2D 10K 모델로 파인튜닝. A포즈 정면에 강하고 측면·후면·단축 자세에서 저하 | 논문·프로젝트 페이지 V [S88][S89], 저장소 내용 U |
| **Qwen-Image-Layered** | Qwen, 2025-12 | RGBA 이미지 → 가변 개수 RGBA 레이어 (재귀 분해) | 예시 3·4·8, 프롬프트로 지정 | Apache-2.0 | 20B. 640 해상도 권장. bf16 풀 정밀도는 약 45GB 급(Qwen-Image 20B 일반 수치, 레이어드 전용 수치는 미확인) | See-through 논문: "특정 신체 부위를 정확히 못 뽑고 레이어를 합치거나 한 부위를 쪼갬" | V [S41][S42][S77] |
| Seedream 5.0 Pro 레이어 분해 | ByteDance, 2026-07 | 이미지 1장 → 기본 이미지 + 투명 PNG 레이어 | 최대 16 | 독점 API | 약 77초(리셀러) | 애니 시험 없음 | 기능 V, 시험 U [S53][S55] |
| LayerD | ICCV 2025, CyberAgent | 그래픽 디자인 래스터 → 레이어(SVG/PSD) | 가변 | Apache-2.0 | - | 그래픽 디자인 대상, **가려진 부분 보완은 문서에 없음** | V [S94] |
| CLD | arXiv 2511.16249, 2025-11 | 래스터 → 다층 RGBA | 문서 미기재 | 코드 MIT, 가중치 `thuteam/CLD`, **베이스가 FLUX.1-dev**(비상업 라이선스 승계 여부 확인 필요) | 미기재 | 애니 시험 없음 | V [S91] |
| OmniPSD | CVPR 2026 Findings, showlab | 텍스트→PSD, 이미지→PSD | 배경·콘텐츠·텍스트 | 라이선스 파일 있으나 종류 미확인, 베이스 FLUX.1-dev / Kontext-dev | 미기재 | 포스터 중심 | V [S93] |
| RevealLayer | ICML 2026, 360CVGroup | RGB + 전경 박스 → 보이는/가려진 RGBA 레이어 | 가변 | 코드 Apache-2.0, 체크포인트 HF(라이선스 조항 동봉), 베이스 FLUX.1-dev | 미기재 | 자연 이미지 대상(RevealLayer-100K) | V [S92] |
| "From Inpainting to Layer Decomposition" | arXiv 2511.20996, CVPR 2026 | 인페인팅 모델 경량 파인튜닝으로 객체 제거·가림 복원 | - | 코드 공개 확인 못 함 | - | - | V(초록만) [S96] |
| ART / PrismLayers | CVPR 2025 | 텍스트+영역 레이아웃 → 투명 레이어 50+ 생성 | 50+ | 데이터셋 Apache-2.0(PrismLayersPro) | - | 생성형(분해 아님) | U [S90] |
| LayerDiffuse / LayerDecomp | 2024 | 투명 이미지 생성 / 시각효과 포함 레이어 분해 | 전경+배경 | - | - | See-through 의 베이스 기술 | U [S90] |
| Workflow-aware 애니 레이어 분해 | arXiv 2603.14925 | 애니 일러스트 → 선화·단색·그림자·하이라이트 | 4 | 코드 CC BY 4.0 표기 | - | **의미 분해가 아니라 제작 공정 분해**, 우리 용도와 다름 | V(초록) [S95] |
| Canva Magic Layers, Image-to-Layer 사이트류 | 상용 | 평면 이미지 → 레이어 | - | 독점, API 확인 못 함 | - | - | U [S90] |

#### 3b-1. See-through 의 측정 근거 (V, arXiv 원문 표)

- Table 1(애니 테스트셋): SAM+LaMa 기준선 대비 본 방법 — LPIPS 0.288 → 0.155, PSNR 12.28 → 18.30, SSIM 0.845 → 0.923, FID 81.14 → 18.37. 일관성 모듈을 빼면 마스크 Dice 0.648 → 0.386(낮을수록 좋음)으로 악화 [S77].
- 저자가 인정한 한계: 몸 바깥에서 레이어 겹침, 3개 이상 안정적으로 쪼개기 어려움, 뾰족한 머리끝·소품은 재확인 필요, 선에 "AI 같은 무늬" [S77].
- SAM 3 는 애니에서 분할이 불완전하거나 모호하다고 같은 논문이 비교함 [S77].
- 학습 데이터: 상용 Live2D 모델에서 부트스트랩한 9,102개 2.5D 모델(학습 7,404 / 검증 851 / 시험 847) [S77].
- 실사용 후기(U): 설정 포함 약 6분, 추론 2분 5초, 1회 약 $0.17(RTX PRO 6000 임대) [S82]. 정면~약간 비스듬한 자세·깔끔한 채색에 강하고, 복잡한 프릴·얼굴을 가리는 손/소품·극단 원근·치비·반투명 소재에 약함. 얼굴은 7부위(face/eyebrow/eyelash/eyewhite/irides/mouth/nose)로 분리됨. 사이드 포니테일은 뒷머리에 합쳐지고 별도 분류 없음 [S82]. 동물 귀·안경은 추출이 불안정하다는 보고(U) [S85]. 일본어 사용기: "3시간 걸릴 분해 작업이 1시간 정도의 수작업 보정으로 줄어든다" [S82], 프로 애니메이터 평가는 "미세 보정만 하면 그대로 쓸 수준" 이라는 요약(U) [S83].
- 생태계(V: 저장소 README 나열): ComfyUI-See-through, PachiPakuGen(눈 깜빡임·립싱크 소재 생성), StretchyStudio(브라우저 자동 리깅, MIT, See-through PSD 직접 입력), Anime2.5DRig, PNGAL [S75][S87].

### 3c. 편집 충실도 (부위 변형 생성)

우리가 필요한 편집: (1) 앞머리 제거 후 뒤 보이기, (2) 앞머리 없는 얼굴, (3) 눈 감김, (4) 입 모양 あいうえお, (5) 팔 뒤 몸통 복원, (6) 머리 15°/30° 회전, (7) 표정 변경.

**측정된 근거는 사실상 없다.** 애니 부위 변형만 따로 평가한 벤치마크를 찾지 못했다. 있는 것은 (a) 일반 편집 선호도 리더보드, (b) 벤더 가이드, (c) 커뮤니티 제작 도구의 작업 방식이다.

| 근거 | 내용 | 신뢰도 |
|---|---|---|
| OpenAI 가이드 | "change only X + 보존 목록" 형식, "반복 편집은 보존해야 할 디테일을 바꿀 수 있다", "픽셀 동일이 필요하면 승인된 편집을 원본에 합성하라", 캐릭터는 "재디자인하지 말라" 로 외형 제약을 매번 반복, 큰 편집에서 2560×1440 초과는 결과가 불안정, 캐릭터 드리프트는 "작은 단일 변경" 으로 반복하라 | V [S8][S9] |
| OpenAI 마스크 | "마스크 모양을 완전히 따르지 않을 수 있음" | V [S4] |
| 일본 커뮤니티 제작 도구 | **PachiPakuGen v0.4**: 외부 에이전트(Claude/GPT 이미지 생성)에 FACS 기반 "あ~お 모음 형태" 지시를 넣어 7종 소재를 만들고 "대부분의 패턴에서 좋은 변형이 나온다" 고 보고. 앱 자체는 생성하지 않고 안내만 제공(Codex·Nano Banana·수작업 중 선택). **PNGAL**: See-through 로 분해 → 눈·입 영역 마스크 → **Qwen-Image-Edit-2511(ComfyUI)** 로 감은 눈·벌린 입 변형 생성 → RIFE 프레임 보간. Anime2.5DRig 류는 변형을 만들지 않고 사용자가 준비한 이미지를 받음 | U [S85][S86] |
| 실패 사례 | "한 장의 일러스트에는 움직이게 할 정보가 없다. 앞머리 뒤의 눈, 입 안, 옷에 가린 목은 추정할 수 없고, '그럴듯한' 보완은 제작자 의도와 다르다" — 자동화는 "지루한 80% 자동화 + 나머지 20% 쉽게 고치기" 로 후퇴 | U [S84] |
| Nano Banana | 일관성은 강하다고 평가되나 각도 변화 시 얼굴이 부풀거나 넓어지는 재해석이 "프롬프트로 일부만 개선되고 완전히 피하기 어렵다" | U [S109] |
| FLUX 3 Image | 바운딩 박스 편집, 영역 밖 픽셀 동일(벤더 주장, 독립 검증 없음) | U [S38][S39] |
| Ideogram 4.5 | 마스크 편집 + "의미 있게 안 바뀐 픽셀은 원본 복사" (문서) | V [S61] |
| 오픈소스 쪽 | Qwen-Image-Edit-2511: 캐릭터 일관성 개선·참조 3장(U). 마스크 지정 인페인팅은 InstantX Qwen-Image-ControlNet-Inpainting, SDXL 계열은 Acly/NoobAI-Inpainting 컨트롤넷(NoobAI/Illustrious 용) 존재 | U [S105] |

**해석**: 부위 변형은 "생성 모델이 얼굴 영역 전체를 새로 그린다" 가 기본 동작이다. 픽셀 보존이 필요하면 모델 밖에서 (크롭 → 편집 → 알파 마스크 합성 → 경계 블렌딩) 해결해야 하고, 이는 OpenAI 가이드가 직접 권하는 방식이다. 선 굵기·채색 스타일 드리프트는 감지 로직(마스크 밖 SSIM, 눈동자 색 비교 등)으로 거르고 재시도하는 구조가 필요하다. "일관성이 80~90%" 라는 수치는 마케팅성 2차 자료라 근거로 삼지 않는다.

### 3d. 포즈·시점 제어, 멀티뷰

- Qwen-Image-Edit-2511 + Multiple-Angles LoRA(Apache-2.0): 96개 자세(방위 8×고도 4×거리 3), 프롬프트 `<sks> front view eye-level shot medium shot` 형식, "3000+ Gaussian Splatting 렌더" 학습, 애니 시험·한계 목록 없음 (V) [S49].
- 그 밖의 LoRA(AnyPose 포즈 전달, 사진→애니 변환 등)가 2511 위에 존재(U) [S105].
- 연구: RCM(arXiv 2601.05722, 단일 이미지에서 궤도 영상으로 3D 캐릭터 생성, 입력 최대 4장), CharacterGen(Anime3D 데이터셋 포함), AnimeAdapter(SD 기반 외형 어댑터, 코드 "게재 승인 후 공개") — 모두 코드·가중치 공개 여부 확인 못 함 (U) [S108].
- Bunraku 프로젝트 페이지(V): A포즈 정면 인물에서 최고 성능, 복잡한 자세·측면·후면·단축 자세에서 저하, 6개 이상 파라미터 동시 구동 시 레이어 분리 아티팩트 [S89].
- See-through 는 정면~약간 비스듬한 자세까지(U) [S82].
- **결론**: 15°/30° 머리 회전을 "그림으로 생성" 하는 것의 품질을 측정한 근거는 없다. Live2D 방식은 머리카락·얼굴 파츠를 메시 워프로 돌리는 것이므로 새 시점 생성은 필수가 아니다. 굳이 필요하면 Live2D 모델에서 직접 렌더해 학습 데이터를 만들어 LoRA 를 만드는 쪽이 현실적이다(See-through·Bunraku 모두 Live2D 모델에서 지도 데이터를 만들었다).

### 3e. 분할·시각-언어 그라운딩

| 모델 | 상태 | 라이선스·접근 | 애니 적합성 | 신뢰도 |
|---|---|---|---|---|
| SAM 3 / SAM 3.1 | SAM 3 2025-11-19, 3.1 2026-03-27(객체 멀티플렉스 추적) | **SAM License**(비독점·로열티 없음, 상업 사용·파생물 허용, 단 ITAR·군사·핵 등 금지, 소송 시 라이선스 종료, 면책 의무). HF 가중치는 접근 신청(gated), 848M~0.9B | See-through 논문에서 애니 분할이 불완전·모호 | V [S98][S77] |
| See-through SAM 신체 파싱 | SAM-HQ(ViT-H) 파인튜닝, 19부위 | Apache-2.0 | 애니 전용, 동물 귀 약함(U) | V [S79] |
| Gemini 분할 | 현행 문서의 이미지 이해 페이지에 바운딩 박스(0~1000 정규화, [ymin,xmin,ymax,xmax]) + bbox 안 폴리곤 마스크 예제가 `gemini-3.8-flash` 로 있음. thinking_level 을 minimal 로 두라고 권고. (예전 포럼 글은 3.x 미지원이라 했으나 현행 문서와 충돌, 문서를 따름) | API | 애니 부위 정확도 데이터 없음 | V [S21] |
| GPT 비전 | GPT-6 Astra: 객체 검출 82.1% mAP@50(저추론), 픽셀 좌표 박스 JSON, 분할은 폴리곤이며 SAM 3 보다 경계가 덜 정밀(2026-09-18 Roboflow 평가). GPT-5.5 는 13.8, 5.6 Sol 은 46.2 였다는 수치는 검색 요약에서만 확인 | API | 일반 객체 평가, 애니 부위 데이터 없음 | Astra 수치 V(블로그 원문), 이전 모델 수치 U [S99] |
| Florence-2, Grounding DINO(1.5), DINO-X, OWLv2 | 2026 에도 오픈 어휘 검출 표준으로 거론 | Florence-2 는 MIT 로 알려짐(이번에 라이선스 원문 미확인) | 일반 이미지 학습, 애니의 머리카락·꼬리·리본 등은 범용 분할이 못 잡는다는 보고 | U [S103] |

권장 구성: SAM 3(경계) + See-through 신체 파싱(애니 의미 체계) + VLM(Gemini/GPT-6)은 "무엇이 어디에 있는가" 제안자로만. VLM 의 폴리곤 마스크를 최종 경계로 쓰지 말 것.

### 3f. 깊이·법선

| 모델 | 비고 | 라이선스 | 신뢰도 |
|---|---|---|---|
| See-through Marigold 파인튜닝 | Marigold Depth v1.1 기반, 애니 캐릭터용 **의사 깊이**(그리기 순서 결정용, 기하학적 깊이 아님). 1B 파라미터, NF4 판 있음 | OpenRAIL++-M (Apache 기여분), 기반 SD2·Marigold 승계. 이슈 #43 에서 라이선스 명시 요청 중 | V [S80][S81] |
| Depth Anything 3 | 2025-11-14. DA3-Mono-Large·DA3Metric-Large·Base·Small 은 Apache-2.0, Giant·Large(1.1)·Nested 는 CC BY-NC 4.0 | 혼재 | V [S100] |
| Marigold V2 | arXiv 2609.08084, DiT 기반 단일 단계, KITTI·ETH3D AbsRel 16~26% 개선 주장, 가중치 공개 정황(HF Space)만 확인 | 논문 CC BY-SA 4.0 | 주장 U [S101] |
| MoGe-2 / MoGe-3 / Lotus-2 / DepthPro | MoGe-3(2026-07)은 코드·가중치 공개 확인 못 함, Lotus-2(arXiv 2512.01030) 상위 성능 주장 | 미확인 | U [S102][S103] |

일반 깊이 모델은 사진으로 학습돼 있고, 애니 일러스트에서 의미 있는 값은 "그리기 순서 보조용 상대 깊이" 정도다. 애니 전용으로 쓸 수 있는 공개 모델은 See-through 의 Marigold 하나다.

### 3g. 이미지→비디오 (보조 경로)

| 모델 | 접근 | 가격 | 비고 | 신뢰도 |
|---|---|---|---|---|
| Veo 3.1 | Gemini API preview | 표준 $0.40/s(720p·1080p), $0.60/s(4K); Fast $0.10/$0.12/$0.30; Lite $0.05(720p)·$0.08(1080p) | 이미지→비디오·참조 이미지 최대 3장·첫/끝 프레임 지원. 4/6/8초, 이미지 기반 입력은 `personGeneration=allow_adult` 만 가능. 지연 11초~6분. SynthID | V [S17][S22] |
| Seedance 2.0 | BytePlus | 480p $0.07/s ~ 4K $0.78/s | I2V 블라인드 투표 1위(Elo 1,344), 2D 애니 프롬프트 지원 안내 | U |
| Kling 3.0 | Kuaishou 및 리셀러 | $0.084/s(720p) ~ $0.42/s(4K) | 4K I2V | U |
| Wan 2.7 | **오픈 가중치 Apache-2.0** (2026-04) | 자체 호스팅 | 27B MoE, 1080p, 참조 5장, 첫/끝 프레임 | U |
| Runway Gen-4.5, Hailuo | - | - | 이번 조사에서 확인 못 함 | U |
| Sora 2 | **종료(2026-09-24)** | - | 대체 API 없음 | V [S7] |

활용 가능성:
- **직접 납품물로는 부적합.** Bunraku 는 "이미지→비디오는 픽셀을 돌려줄 뿐 구동 가능한 객체가 아니다" 라는 점을 논점으로 삼고, 비디오 기준선과 비교해 LPIPS 0.028 vs AniDoc 0.059, SSIM 0.955 를 보고한다 (V) [S88].
- **보조 감독·참조**로는 가능: 깜빡임·말하기·고개 돌림 프레임에서 "눈 감은 형태" 같은 프레임을 뽑아 참조로 쓸 수 있으나, 스타일·정체성 드리프트와 가격(8초 영상 한 번 $0.4~3 이상)이 부위 하나를 이미지 편집으로 만드는 비용($0.013~0.2)보다 훨씬 크다. 애니 스타일 보존에 대한 독립 측정은 찾지 못했다.

### 3h. 파인튜닝 가능성

| 구분 | 가능한 것 | 불가·제한 |
|---|---|---|
| 오픈 가중치(자체 학습) | FLUX.2 klein(Base 4B/9B; 4B 만 상업 자유), Qwen-Image / Qwen-Image-Edit(Apache-2.0, DiffSynth-Studio 가 LoRA·전체 학습·저VRAM 지원), HiDream-O1(MIT), Z-Image(Apache-2.0), SD3.5(Community License), Lumina-Image 2.0(Apache), SDXL 계열 애니 모델(NoobAI·Illustrious 등) | Qwen-Image-2.1·FLUX.2 dev·klein 9B 는 비상업 |
| API 형 맞춤화 | BFL "bring your own LoRA"(klein 계열 한정 베타, 요청당 LoRA 1개, 기본 엔드포인트와 같은 가격) (V) [S35] | OpenAI 는 2026-05-08 부로 파인튜닝 플랫폼을 접는 중(U) [S110], Nano Banana Pro·Seedream 5.0·GPT Image 1.5 는 LoRA 미지원(U) [S111]. Adobe 는 Custom Models 제공(U) |
| 상업 이용 시 | See-through·Bunraku 방식(자체 Live2D 데이터로 Qwen-Image-Layered 파인튜닝)이 가장 직접적. 단 Live2D 모델 자체의 학습 사용 권리는 별도 법적 검토 필요 | - |

---

## 4. 정책·약관 (공개 웹서비스에서 임의의 캐릭터 이미지를 받을 때)

| 벤더 | 미성년·애니 | 실존 인물 | 저작권 캐릭터 | 경쟁 모델·학습 금지 | 서비스 대상 연령 | 신뢰도 |
|---|---|---|---|---|---|---|
| OpenAI | 미성년 성적 묘사는 최상위 금지(Model Spec 2026-08-18 갱신). 성인 모드는 2026-03 무기한 보류 | 딥페이크·실존 인물 성적 묘사 금지 | 2차 자료 실험에서 저작권 캐릭터 거부율 91.7%(표본 24건, 2026-08-04, 기본 설정). 프롬프트·출력 이중 검열, 같은 프롬프트도 통과·차단이 갈림 | Services Agreement: Output 으로 OpenAI 와 경쟁하는 AI 모델을 개발 금지(분류·임베딩 등 예외). 고객 콘텐츠는 학습에 안 씀 | 미확인 | 정책 원문은 403 으로 못 읽음(U), 약관 문구는 검색 인용(U) [S11][S59] |
| Google Gemini API | 아동 착취·성적 노골 콘텐츠 금지. 2차 자료: "동일 프롬프트가 사실 화풍에서는 통과하고 애니에서는 저작권 감지로 더 자주 차단", 구글이 "의도보다 더 신중해졌다" 고 인정, 2단계 필터는 API 로 해제 불가 | 실존 인물 편집 거부 | 같은 실험에서 NB2 41.7%, NB2 Lite 50.0% 거부 (마리오·피카츄는 통과) | "서비스와 경쟁하는 모델 개발 금지", 리버스 엔지니어링 금지. **유료 API 는 프롬프트·응답을 제품 개선에 안 씀, 무료는 씀** | **앱이 18세 미만을 대상으로 하거나 접근 가능하면 안 됨**(공개 웹서비스에 연령 확인이 필요할 수 있음) | 약관·정책 V [S23][S24], 필터 동작 U [S28][S59] |
| BFL(FLUX API) | 개발자 약관: **18세 미만 개인의 이미지/개인정보 업로드 금지, 동의 없는 개인 이미지 업로드 금지**, 최종 사용자에게 AUP 를 구속력 있게 부과할 것 | 위와 같음 | - | **Output 으로 다른 AI 모델을 학습·증류·파인튜닝 금지**, 경쟁 제품 개발 금지. BFL 은 입출력을 자사 모델 개선에 쓸 영구 라이선스를 자신에게 부여 | 최종 사용자 약관 필수 | V [S36] |
| xAI(SpaceXAI) | AUP: 아동 성적 묘사, 실존 인물 누드화 금지. "spicy" 는 유료·API 라도 정책 예외 아님 | 실존 인물을 성적 맥락으로 편집하면 하드 블록·계정 정지 | 거부율 80.0% (2차) | 엔터프라이즈 약관: SpaceXAI 서비스와 유사·경쟁하는 서비스 개발·운영 금지(검색 인용), 입출력은 모델 학습에 안 씀, 30일 내 삭제 | - | U(원문 403) [S59][S60] |
| ByteDance BytePlus | 2단계 필터(입력 텍스트 + 이미지→이미지의 입력 이미지 검사). 공개 시험에서 정상 이미지가 제공자 검증에서 실패한 사례 | 정책 원문 미확인 | 미확인 | 경쟁 상용 서비스 개발 금지(검색 인용). Seedream 4.5/5.0 Pro 는 허용 용도에 IP 면책 제공(조건부, U) | - | U [S55][S57] |
| Alibaba Model Studio | 문서에 안전 항목 없음, 이미지 링크 24시간 만료 | - | - | - | - | V(부재) [S48] |
| 오픈 가중치 자체 호스팅 | 라이선스별 사용 제한 조항만 존재(예: OpenRAIL++-M 의 use-based restriction, SAM License 의 군사 금지, Hunyuan Community License 의 EU·UK·한국 제외). 거부 없음 → **우리가 직접 모더레이션을 책임** | - | - | Apache/MIT 모델은 학습 사용 제한 없음 | - | V(See-through 계열·SAM·HiDream) |

종합:
- 일본 애니풍 캐릭터는 외형상 어려 보이는 경우가 많고(성인이라도), API 벤더들은 "미성년" 에 영(零) 관용이며 필터가 확률적이다. **거부·오탐 가능성이 높은 순서(2차 근거 포함)**: OpenAI(출력 단계 이중 검열) > xAI > Google(애니 민감) > BFL(18세 미만 업로드를 약관으로 금지) > 오픈 가중치(거부 없음).
- 저작권 캐릭터(VTuber 팬아트, 게임 캐릭터 업로드)를 받는 서비스는 OpenAI·Grok 에서 막힐 확률이 높다는 2차 측정이 있다. 단 그 측정은 "텍스트로 캐릭터를 불러오는" 프롬프트 기준이고, **사용자가 올린 이미지를 편집하는 경우의 거부율은 측정된 것이 없다.**
- "경쟁 모델 개발 금지" 조항은 거의 모든 API 에 있다. 우리 서비스가 API 로 만든 부위 변형을 모아 자체 모델(예: 눈·입 변형 LoRA)을 학습하는 계획은 **OpenAI·Google·BFL·xAI·BytePlus 약관 모두 위반 소지**가 크다. 학습용 데이터는 오픈 가중치 모델 또는 Live2D 원본에서 만드는 편이 안전하다.
- 서비스 약관 설계: 최종 사용자에게 AUP·연령 확인·업로드 권리 진술을 받을 것(BFL 은 계약 조건, Google 은 18세 미만 접근 금지 조건).

---

## 5. 파이프라인 단계별 타당성 (솔직한 평가)

| 단계 | 현재 최선(API) | 최선(자체 호스팅 오픈 가중치) | 현실적인 실패 양상 |
|---|---|---|---|
| 1. 레이어 분해 + 가림 부분 인페인팅 | 애니 근거가 있는 API 는 없음. Seedream 5.0 Pro 레이어 분해(최대 16장)가 유일한 제품형 후보이나 애니 시험 부재 | **See-through V3**(23 레이어, 12~16GB, 74초/1024²), 후속으로 Bunraku 식 파인튜닝(Qwen-Image-Layered 기반, Apache-2.0) | 사이드 포니테일이 뒷머리에 합쳐짐, 동물 귀·안경 누락, 얼굴을 가리는 손·소품, 치비·극단 원근, 3층 이상 층분리 불안정, 몸 바깥에서 레이어 겹침, 선의 "AI 무늬". 범용 LLM 이미지 편집으로 "앞머리만 투명 배경에 추출" 하면 재그림이라 레이어 간 정합이 깨짐 |
| 2. 눈·입 변형 생성 | **gpt-image-2.5-sunburst**(편집 1위, 투명 지원, 최대 16장 참조(U)) 또는 Nano Banana Pro/2(일관성 강점, 알파 없음). Ideogram 4.5·FLUX 3 Image 는 마스크·영역 지정이 되어 후보이나 애니 성능 미측정 | Qwen-Image-Edit-2511(Apache, 마스크 컨트롤넷 가능), SDXL 계열 애니 모델 + NoobAI-Inpainting 컨트롤넷(스타일 일치 강점 가능성, 측정 근거 없음), 필요 시 LoRA | 스타일·선 굵기 드리프트, 눈동자 색·하이라이트 변동, 감은 눈의 속눈썹 곡선 불일치, 입 안(이빨·혀) 환각, 마스크 밖 픽셀 이동 → 합성으로 보정 필요. 프롬프트만으론 "그럴듯하지만 의도와 다른" 결과 |
| 3. 가려진 신체 보완(팔 뒤 몸통 등) | See-through 가 이미 포함. 추가로 sunburst 에 "팔 뒤 몸통을 그려라" 편집 | See-through + 인페인팅(LaMa 는 See-through 가 층분리 경계 복원에 사용) | 추정은 그럴듯해도 원작자 의도와 다름, 옷 경계 인공물 |
| 4. 머리 회전 시점 | 측정 근거 없음(Nano Banana 는 각도 변화 시 얼굴 비율 드리프트 보고) | Qwen-Image-Edit-2511 + Multiple-Angles LoRA(애니 미검증). 권장: 생성 대신 메시 워프 | 정체성 드리프트, 측면·후면 붕괴(Bunraku 도 측면에 약함) |
| 5. 분할 | Gemini/GPT-6 박스·폴리곤은 제안용 | SAM 3(상업 가능, ITAR 제한) + See-through SAM-HQ 신체 파싱(Apache) | SAM 3 는 애니에서 불완전, 범용 모델은 머리카락·꼬리·리본 못 잡음 |
| 6. 깊이 | 해당 없음 | See-through Marigold(애니·그리기 순서용), 범용은 DA3-Mono-Large(Apache) | 사진 학습 모델은 일러스트 깊이를 신뢰하기 어려움, 3층 이상 분리는 불안정 |
| 7. 리깅(메시·변형·물리) | - | Bunraku 방식(메시 + keypose 변위 예측, 코드 위치만 확인) 또는 StretchyStudio(MIT, DWPose 스켈레톤 + 메시 편집) | Bunraku: 31/50(62%) 캐릭터만 방향 코사인 ≥0.80, 작은 움직임은 과대·큰 회전은 과소, 6개 이상 파라미터 동시 구동 시 층 분리 아티팩트 |

**비용 감각(추정, 계산 근거 명시)**: 한 캐릭터당 부위 변형이 10~15회라 가정(감은 눈, 웃는 눈, 모음 5종, 닫힌 입, 눈썹 변형 등). gpt-image-2.5 high 1024² 출력만 $0.053 × 12 ≈ $0.64, medium 이면 $0.013 × 12 ≈ $0.16. 여기에 입력 이미지 토큰($8/M)과 실패 재시도(마스크 밖 SSIM 검사 탈락분)가 더해진다. 레이어 분해는 자체 GPU 에서 약 1.2~2분. 이 계산은 요율(V)과 토큰 수(U)를 곱한 추정이다.

**속도 한도 현실**: OpenAI Tier1 은 5 IPM 이라 공개 서비스에는 부족, 지출이 쌓여 Tier4(150 IPM)·Tier5(250 IPM) 가 되어야 의미가 있다(V) [S1]. Gemini 는 지출 $100·$1,000 단계 승급(V) [S26].

---

## 6. 권장 아키텍처 (근거 기반 제안)

1. **1단계는 오픈 가중치로 고정**: See-through V3 를 그대로 서비스화(상업 허용, Apache/OpenRAIL++-M). OpenRAIL++-M 의 사용 제한 조항을 서비스 약관에 승계하고, Marigold·SAM 가중치 라이선스는 이슈 #43 결과를 추적하거나 저자에게 직접 확인한다. Bunraku 식으로 Qwen-Image-Layered 를 자체 데이터로 파인튜닝하는 길은 2차 후보(라이선스 청소된 Live2D 데이터가 선결).
2. **부위 변형은 "크롭 → 편집 → 합성" 구조의 교체 가능한 어댑터**로 설계: 기본 어댑터 gpt-image-2.5-sunburst(품질), 대체 어댑터 Nano Banana 2(일관성·가격), 자체 호스팅 어댑터 Qwen-Image-Edit-2511(Apache, 모더레이션·약관 위험 회피). 마스크 밖 SSIM, 눈·입 영역 알파 윤곽 검사로 자동 재시도.
3. **API 결과로 우리 모델을 학습하지 말 것**(경쟁 모델 금지 조항).
4. **머리 회전은 생성하지 않고 메시 워프**로 처리(Bunraku/StretchyStudio 방식), 생성 시점 이미지는 선택 기능으로만.
5. **정책 대응**: 업로드 단계에 자체 모더레이션 + 연령 확인 + 업로드 권리 진술. API 벤더 거부는 "다른 어댑터로 폴백" 하되, 폴백이 결과 일관성을 깨므로 한 캐릭터는 같은 어댑터로 끝까지 가게 고정.
6. **측정을 먼저 만들 것**: 애니 부위 변형 벤치마크가 공개돼 있지 않으므로, 50~100개 캐릭터 × 변형 10종의 자체 평가 세트(마스크 밖 SSIM, 정체성 LPIPS, 수작업 합격률)를 가장 먼저 만들어 sunburst / Nano Banana 2 / Qwen-Image-Edit-2511 / FLUX 3 Image 를 같은 조건에서 비교한다.

---

## 7. 비교표

범례: 편집 충실도의 숫자는 LMArena 단일 이미지 편집 Elo(2026-09-29, V). "-" 는 순위 없음/확인 못 함.

| 모델 | 벤더 | 접근 | 장당 가격 | 알파 | 편집 충실도 | 레이어 분해 | 라이선스 | 비고 |
|---|---|---|---|---|---|---|---|---|
| gpt-image-2.5-sunburst | OpenAI | API | 1024² high $0.053(추정, 출력 토큰 $30/M) | 예(preview, 편집 시 재그림) | 1522, 1위 | 아니오 | 독점 | 마스크는 참고용, 반복 편집 드리프트, 합성 권장. 저작권 캐릭터·미성년 필터 엄격 |
| gpt-image-2.5-flare | OpenAI | API | 동일 토큰 요율 | 예 | 1478, 2위 | 아니오 | 독점 | 지연 약 절반(U) |
| gpt-image-2 | OpenAI | API | 동일 계열 | 예(preview) | 1461, 3위 | 아니오 | 독점 | input_fidelity 항상 high(U) |
| gemini-3-pro-image (Nano Banana Pro) | Google | API | $0.134(1K/2K), $0.24(4K) | 문서 없음 | 1390, 10위 | 아니오 | 독점 | 18세 미만 접근 금지 약관, 애니는 저작권 필터 민감(U) |
| gemini-3.1-flash-image (NB2) | Google | API | $0.045~0.151 | 문서 없음 | 1387, 12위 | 아니오 | 독점 | 인물 5·사물 14 일관성(블로그) |
| gemini-3.1-flash-lite-image | Google | API | $0.0336(1K) | 문서 없음 | - | 아니오 | 독점 | 1K 만 |
| FLUX 3 Image | BFL | API(오픈판 예고) | $0.048(1K, 할인 여부 충돌) | 문서 없음 | -(어제 출시) | 아니오 | 독점(상업 가중치 협의, 오픈판 "수주 내"(U)) | 바운딩 박스 편집, 참조 10, 영역 밖 동일(주장) |
| FLUX.2 [pro]/[max] | BFL | API | $0.03~0.07부터 | 문서 없음 | - | 아니오 | 독점 | max 는 참조 10 |
| FLUX.2 [klein] 4B | BFL | 오픈+API | $0.014부터 | 문서 없음 | 1187(오픈 7위) | 아니오 | **Apache-2.0** | 13GB, LoRA 호스팅 베타 |
| FLUX.2 [klein] 9B / [dev] | BFL | 오픈 | $0.015부터(9B API) | 문서 없음 | - | 아니오 | **비상업**(상업은 BFL 계약) | dev 32B |
| Seedream 5.0 Pro | ByteDance | API | $0.045(≤2.36MP, U) | 문서 없음 | 1394, 8위 | **예, 최대 16**(레이어 분해 호출 약 $0.75~1.53 U) | 독점 | 애니 레이어 시험 없음 |
| Qwen-Image-Edit-2511 | Alibaba | 오픈 | 자체 GPU | 아니오 | 1234(오픈 4위) | 아니오 | **Apache-2.0** | 20B, 참조 3(U), 멀티앵글 LoRA 존재 |
| Qwen-Image-Layered | Alibaba | 오픈 | 자체 GPU | 예(RGBA 레이어) | - | **예, 가변** | **Apache-2.0** | 640 권장, 애니 부위 분해는 약함(See-through 논문) |
| Qwen-Image-2.1 | Alibaba | 오픈 가중치 | 자체 GPU | **예(네이티브 RGBA)** | 1366, 16위 | 아니오 | **연구 전용(비상업)** | 7B, 참조 10, 상업 시 별도 계약 |
| Qwen-Image-3.0(-pro) | Alibaba | API | 약 $0.03~0.04(U) | 문서 없음 | - | 아니오 | 독점 | 참조 1~3 |
| grok-imagine-image-2.0 | xAI | API | $0.04 | 문서 없음 | 1427, 4위 | 아니오 | 독점 | 저작권 거부 80%(2차) |
| MAI-Image-2.6 | Microsoft | Foundry 프리뷰 | 약 $0.039(U) | - | 1427, 5위 | 아니오 | 독점 | |
| Muse Image | Meta | API | $0.01(U) | - | 1403, 6위 | 아니오 | 독점 | 2026-08-26 |
| Ideogram 4.5 | Ideogram | API | 품질별 | 문서 없음 | 1351, 18위 | 아니오 | 독점(오픈판 "곧", U) | 마스크 편집, 영역 밖 복사 |
| Midjourney V8.2 Edit | Midjourney | 웹·Discord | 구독 | - | - | 아니오 | 독점 | 공식 API 없음(U) |
| Adobe Firefly Image 5 | Adobe | Firefly Services | 크레딧 | - | - | "레이어 편집"(상태 미확인) | 독점(상업 안전 표방) | 4 req/min 기본(U) |
| Recraft V4(.1) | Recraft | API | $0.035~0.30(U) | SVG | - | 아니오 | 독점 | 벡터 |
| HiDream-O1-Image | HiDream | 오픈 | 자체 GPU | - | - | 아니오 | **MIT** | 8B, 참조 10, 픽셀 공간 |
| Hy Image 3.5 preview | Tencent | API | 약 $0.024(U) | - | - | 아니오 | 독점 | 3.0 은 오픈(EU·UK·한국 제외) |
| NovelAI Diffusion V5 | NovelAI | 구독 REST | Anlas | **예(주장)** | - | 아니오 | 독점 | 애니 특화, 제3자 서비스 제공은 약관상 제한(U) |
| See-through V3 | shitagaki-lab | 오픈 | 자체 GPU(약 74초) | 예 | - | **예, 23(애니)** | 코드 Apache-2.0 / 가중치 OpenRAIL++-M | 기준 논문 |
| Bunraku | SparcAI 등 | 논문+저장소 | - | 예 | - | **예 + 리깅** | 미확인 | Qwen-Image-Layered 기반 |
| Veo 3.1 (영상) | Google | API preview | $0.05~0.60/초 | - | - | - | 독점 | 이미지 입력은 성인만 허용 |
| Wan 2.7 (영상) | Alibaba | 오픈 | 자체 GPU | - | - | - | Apache-2.0(U) | 27B MoE |

---

## 8. 확인하지 못한 것 / 충돌한 것 (명시)

1. **애니 부위 변형(눈 감음·모음 입·앞머리 제거)의 정량 비교**: 어느 모델이 더 낫다는 측정 데이터가 공개돼 있지 않다. 커뮤니티 사례(PachiPakuGen, PNGAL)는 방식만 확인했고 성공률은 확인하지 못했다.
2. **Seedream 5.0 Pro 레이어 분해의 애니 캐릭터 성능**: 공개 시험이 없다. 최대 레이어 수 16은 BytePlus 개요 페이지에서 확인했으나 가격은 리셀러 값.
3. **Bunraku 코드·가중치 라이선스**: GitHub 저장소 페이지가 제목·인용만 보였고 README·LICENSE 를 못 읽었다(GitHub API 는 속도 제한). 논문 본문도 공개 범위를 명시하지 않는다.
4. **OpenAI 사용 정책 원문·서비스 약관 원문**: 403 으로 열지 못했다. 정책 내용은 검색 요약(2차), Services Agreement 문구는 검색 결과의 인용에 의존했다.
5. **xAI 엔터프라이즈 약관 원문**도 403 이었다(검색 인용만).
6. **Gemini 이미지 모델의 투명 배경 및 마스크 입력**: 공식 문서에 언급이 없다는 사실만 확인. "알파 없음" 은 2차 자료.
7. **참조 이미지 상한**: Gemini(문서 간 불일치), OpenAI 16장(2차), Qwen-Image-Edit-2511 3장(2차).
8. **Qwen-Image-2.0 의 라이선스**(GitHub 요약은 Apache, 다른 자료·아레나는 독점) — 독점 API 로 취급.
9. **FLUX 3 Image 의 "영역 밖 bit-identical"**: 벤더 주장과 "대체로 동일" 이라는 서술이 혼재, 독립 검증 없음. 오픈 가중치판 공개 시점 미정.
10. **FLUX.1-dev 기반 레이어 모델(CLD, OmniPSD, RevealLayer)의 상업 이용 가능성**: 코드 라이선스와 베이스 가중치(FLUX.1 [dev] 비상업) 라이선스의 관계를 확인하지 못했다. 사용 전 별도 법무 확인 필요.
11. **Hailuo, Runway Gen-4.5, Luma, Stable Diffusion 후속, Hunyuan3D 멀티뷰** 등은 이번에 깊이 확인하지 않았다.
12. **Qwen-Image-Layered 의 실제 VRAM**: README 에 수치가 없고, 20B 일반 수치(약 45GB bf16, Q4 약 11GB)는 Qwen-Image 기반 2차 추정이다.
13. **Marigold V2·MoGe-3 의 가중치 공개 여부**: 논문만 확인.
14. **GPT-6 계열 모델 중 `image_generation` 도구를 호출할 수 있는 정확한 목록**: 문서 페이지마다 목록이 달라 확정하지 못했다.
15. **서비스 약관상 "미성년 캐릭터" 해석**: 업로드된 일러스트 속 캐릭터가 BFL 약관의 "18세 미만 개인" 에 해당하는지는 약관 문구만으로 판단할 수 없다.

---

## Sources

(V = 1차 출처를 직접 열어 확인, U = 2차·검색 요약·접근 실패)

**OpenAI**
- [S1] https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst (V)
- [S2] https://developers.openai.com/api/docs/models/gpt-image-2.5-flare (V)
- [S3] https://developers.openai.com/api/docs/models/gpt-image-2 (V)
- [S4] https://developers.openai.com/api/docs/guides/image-generation (V)
- [S5] https://developers.openai.com/api/docs/pricing (V)
- [S6] https://developers.openai.com/api/docs/changelog (V)
- [S7] https://developers.openai.com/api/docs/deprecations (V)
- [S8] https://developers.openai.com/api/docs/guides/image-prompting (V)
- [S9] https://developers.openai.com/cookbook/examples/multimodal/image-gen-models-prompting-guide (V)
- [S10] https://developers.openai.com/api/docs/guides/tools-image-generation (V)
- [S11] https://openai.com/policies/services-agreement/ (U: 원문 403, 검색 인용)
- [S12] https://en.wikipedia.org/wiki/GPT_Image (U)
- [S13] https://fal.ai/learn/devs/gpt-image-2-5-vs-gpt-image-2 (U)
- [S14] https://docs.apiyi.com/en/live/2026-08/gpt-image-2-transparent-background (U)
- [S15] https://www.little6llc.com/2026/09/14/chatgpt-can-now-do-transparent-backgrounds-sort-of-whats-changed-in-2026/ (U)
- [S16] 2.5 토큰별 가격(2차): https://www.eesel.ai/blog/chatgpt-images-2-5-pricing , https://www.virse.ai/blog/gpt-image-2-5-pricing , https://www.cometapi.com/gpt-image-2-5-price-api-cost-per-image/ (U)

**Google**
- [S17] https://ai.google.dev/gemini-api/docs/pricing (V)
- [S18] https://ai.google.dev/gemini-api/docs/image-generation (V)
- [S19] https://ai.google.dev/gemini-api/docs/imagen (V)
- [S20] https://ai.google.dev/gemini-api/docs/models (V)
- [S21] https://ai.google.dev/gemini-api/docs/image-understanding (V)
- [S22] https://ai.google.dev/gemini-api/docs/veo (V)
- [S23] https://ai.google.dev/gemini-api/terms (V)
- [S24] https://policies.google.com/terms/generative-ai/use-policy (V)
- [S25] https://blog.google/innovation-and-ai/technology/ai/nano-banana-2/ (V)
- [S26] https://ai.google.dev/gemini-api/docs/rate-limits (V)
- [S27] https://jidefr.medium.com/nano-banana-2-with-transparency-4673640bb9e6 , https://transparify.app/blog/gemini-transparent-background (U)
- [S28] https://help.apiyi.com/en/nano-banana-pro-2-safety-mechanism-image-generation-failure-guide-en.html (U)

**Black Forest Labs**
- [S29] https://docs.bfl.ml/quick_start/pricing (V)
- [S30] https://docs.bfl.ml/release-notes (V)
- [S31] https://bfl.ai/licensing (V)
- [S32] https://huggingface.co/black-forest-labs/FLUX.2-klein-4B (V)
- [S33] https://huggingface.co/black-forest-labs/FLUX.2-klein-9B (V)
- [S34] https://huggingface.co/black-forest-labs/FLUX.2-dev (V)
- [S35] https://docs.bfl.ml/flux_2/flux2_lora_inference (V)
- [S36] https://bfl.ai/legal/developer-terms-of-service (V)
- [S37] https://bfl.ai/blog/flux-3 (V)
- [S38] https://alphasignal.ai/news/black-forest-labs-flux-3-image-lets-developers-place-objects-with-exact (U)
- [S39] https://www.orcarouter.ai/blog/flux-3-image-vs-flux-3 (U)

**Alibaba Qwen**
- [S40] https://github.com/QwenLM/Qwen-Image (V)
- [S41] https://github.com/QwenLM/Qwen-Image-Layered (V)
- [S42] https://huggingface.co/Qwen/Qwen-Image-Layered (V)
- [S43] https://arxiv.org/abs/2512.15603 (V)
- [S44] https://huggingface.co/Qwen/Qwen-Image-2.1 (V)
- [S45] https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE (V)
- [S46] https://cellcog.ai/blog/qwen-image-2-1/ (U)
- [S47] https://invideo.io/blog/qwen-image-ai-generator/ (U)
- [S48] https://www.alibabacloud.com/help/en/model-studio/qwen-image-generation-and-editing-api-reference (V)
- [S49] https://huggingface.co/fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA (V)

**리더보드**
- [S50] https://arena.ai/leaderboard/image-edit (V, 2026-09-29)
- [S51] https://arena.ai/leaderboard/text-to-image (V, 2026-09-24)
- [S52] https://arena.ai/leaderboard/image-edit?license=open-source (V, 2026-09-29)

**ByteDance**
- [S53] https://ai.byteplus.com/resources/seedream-5-0-overview-what-we-know-about-this-version (V)
- [S54] https://wavespeed.ai/models/bytedance/seedream-v5.0-pro/layer-decomposition (U)
- [S55] https://berryon.art/seedream-5-pro-layerize (U)
- [S56] https://docs.comfy.org/tutorials/partner-nodes/bytedance/seedream-5-pro (U)
- [S57] BytePlus 약관 관련(본문은 열지 못함, 검색 요약만 사용): https://docs.byteplus.com/en/docs/legal/acceptable_use_policy_byteplus_genai , https://docs.byteplus.com/en/docs/ModelArk/1541523 (U)

**xAI·기타 벤더**
- [S58] https://docs.x.ai/developers/models/grok-imagine-image-2.0 (V)
- [S59] https://www.dreampixelforge.com/blog/ai-image-generators-copyrighted-characters (U)
- [S60] https://x.ai/legal/terms-of-service-enterprise (U: 원문 403, 검색 인용)
- [S61] https://developer.ideogram.ai/api-reference/images/precise-edit/ideogram-4-5 (V)
- [S62] https://ideogram.ai/news/ideogram-4.0/ (403) 및 검색 결과 https://x.com/btibor91/status/2105334426410651993 (U)
- [S63] https://updates.midjourney.com/edit-model-for-v8/ , https://unifically.com/blogs/midjourney-api (U)
- [S64] https://www.unite.ai/adobe-unveils-firefly-image-model-5-with-layered-editing-and-custom-ai-creation/ , https://apiframe.ai/blog/adobe-firefly-api (U)
- [S65] https://www.recraft.ai/docs/recraft-models/recraft-V4 (검색 결과) (U)
- [S66] https://www.krea.ai/blog/is-stable-diffusion-free-where-to-get-it-and-what-it-costs-in-2026 (U)
- [S67] https://openrouter.ai/meta/muse-image , https://www.orcarouter.ai/blog/muse-image (U)
- [S68] https://learn.microsoft.com/en-us/azure/foundry/foundry-models/how-to/use-foundry-models-mai-image , https://openrouter.ai/microsoft/mai-image-2.6 (U)
- [S69] https://www.atlascloud.ai/models/reve-ai/reve-2.1/edit , https://www.eesel.ai/blog/reve-2-1-pricing (U)
- [S70] https://cellcog.ai/blog/hy-image-3-5-preview/ (U)
- [S71] https://huggingface.co/HiDream-ai/HiDream-O1-Image (V)
- [S72] https://github.com/meituan-longcat/LongCat-Image (U)
- [S73] https://journal.novelai.net/image-generation-novelai-diffusion-v5-is-here-c2df7c6b8d2d/ (V)
- [S74] https://github.com/DesmondFox/novelai-mcp , https://aitoolsdevpro.com/ai-tools/novelai-guide/ (U)

**See-through 및 레이어·리깅**
- [S75] https://github.com/shitagaki-lab/see-through (V) 및 로컬 사본 <local clone of see-through>/README.md (V)
- [S76] https://arxiv.org/abs/2602.03749 (V)
- [S77] https://arxiv.org/html/2602.03749v1 (V)
- [S78] https://huggingface.co/layerdifforg/seethroughv0.0.2_layerdiff3d (V)
- [S79] https://huggingface.co/24yearsold/l2d_sam_iter2 (V)
- [S80] https://huggingface.co/24yearsold/seethroughv0.0.1_marigold (V)
- [S81] https://github.com/shitagaki-lab/see-through/issues/43 (V)
- [S82] https://lilting.ch/en/articles/see-through-anime-layer-decomposition (U)
- [S83] https://note.com/yuuri_nerd/n/n385592ecdf4e?hl=en (U)
- [S84] https://note.com/dn0288/n/nf89c79d14d27?hl=en (U)
- [S85] https://note.com/kazuya_bros/n/nec31c3033265?hl=en (U)
- [S86] https://github.com/kazuya-bros/PachiPakuGen (V)
- [S87] https://github.com/MangoLion/stretchystudio (검색 결과, MIT) (U)
- [S88] https://arxiv.org/html/2607.27348 , https://arxiv.org/abs/2607.27348 (V)
- [S89] https://bunraku-live2d.github.io/ (V)
- [S90] https://github.com/s07811005141-lang/awesome-image-to-layer (U: 큐레이션 목록)
- [S91] https://github.com/monkek123King/CLD (V)
- [S92] https://github.com/360CVGroup/RevealLayer , https://arxiv.org/abs/2605.11818 (V)
- [S93] https://github.com/showlab/OmniPSD (V)
- [S94] https://github.com/CyberAgentAILab/LayerD (V)
- [S95] https://arxiv.org/abs/2603.14925 (V)
- [S96] https://arxiv.org/abs/2511.20996 (V)

**분할·깊이**
- [S98] https://github.com/facebookresearch/sam3 및 https://raw.githubusercontent.com/facebookresearch/sam3/main/LICENSE (V)
- [S99] https://blog.roboflow.com/gpt-6-astra-vision/ (V)
- [S100] https://github.com/ByteDance-Seed/Depth-Anything-3 (V)
- [S101] https://arxiv.org/abs/2609.08084 (V)
- [S102] https://arxiv.org/abs/2607.17967 (V)
- [S103] 검색 결과: Lotus-2 https://arxiv.org/pdf/2512.01030 , Florence-2·Grounding DINO 개요 https://www.forasoft.com/learn/ai-for-video-engineering/articles-ai/open-vocabulary-detection-grounding-dino-florence-2-rtdetr-rfdetr (U)

**기타**
- [S105] https://huggingface.co/Acly/NoobAI-Inpainting , https://github.com/PRITHIVSAKTHIUR/Qwen-Image-Edit-2511-LoRAs-Fast-Lazy-Load (U)
- [S106] https://github.com/Tongyi-MAI/Z-Image (U)
- [S108] https://arxiv.org/abs/2601.05722 (V: 초록), https://arxiv.org/abs/2605.20237 (V: 초록)
- [S109] https://help.apiyi.com/en/nano-banana-pro-face-consistency-guide-en.html (U: Nano Banana 각도 변화 시 얼굴 드리프트 보고)
- [S110] https://guptadeepak.com/tools/top-8-fine-tuning-model-customization-platforms-2026/ (U: OpenAI 파인튜닝 플랫폼 축소)
- [S111] https://wavespeed.ai/blog/posts/seedream-5-0-vs-nano-banana-pro-gpt-image-flux-klein-qwen-image-comparison-2026/ (U: 모델별 LoRA 지원 여부)
- 영상: Seedance https://www.atlascloud.ai/blog/case-studies/seedance-2.0-pricing-full-cost-breakdown-2026 , Kling https://www.atlascloud.ai/models/kling-v3 , Wan 2.7 https://wan27.org/blog/wan-2-7-open-source-guide (모두 U)
