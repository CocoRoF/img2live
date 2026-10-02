# 01. See-through 분석 (코드·논문·라이선스 직접 확인분)

작성: 2026-10-02 · 대상: `reference_data/see-through` (커밋 a25a549, https://github.com/shitagaki-lab/see-through)
논문: arXiv 2602.03749, SIGGRAPH 2026 Conference Papers (doi 10.1145/3799902.3811209)

> 이 문서는 **로컬 코드를 읽고, arXiv HTML·HF 모델 카드·GitHub 이슈를 열어 본 것**만 적는다.
> 확인하지 못한 것은 "미확인"으로 표시한다.

---

## 1. See-through가 하는 일, 하지 않는 일

| 하는 일 | 하지 않는 일 (README "Is this Image-to-Live2D?" 에서 저자들이 직접 선을 그음) |
|---|---|
| 일러스트 1장 → **최대 23개 의미 레이어**(RGBA, 가려진 부분 인페인팅) + 레이어별 **의사 깊이** → 그리기 순서 | **리깅**(변형 메시, 디포머, 물리, 모션 곡선) — "가장 중요하고 가장 손이 많이 가는 단계, 이 프로젝트는 다루지 않음" |
| PSD 출력 (`.psd` + `_depth.psd` + `.psd.json`) | 라이브2D 식 **분해 설계**(변형을 염두에 둔 레이어 분할) |
| (커뮤니티) StretchyStudio·Anime2.5DRig·PNGAL 등이 PSD를 받아 자동 리깅 | 눈 감김/입 모양 같은 **상태 변형 레이어** 생성 |

→ **img2live 의 정의: See-through(=1단계)의 뒤에 "변형 가능한 레이어로 다시 설계 → 리깅 → 런타임" 을 붙이는 것.**
저자 스스로 "이 분해는 라이브2D 작가의 출발점" 이라고 말한다. 가장 많은 공감(👍9)을 받은 이슈가 #8 "Image-to-Live2D?" 이다.

## 2. 추론 파이프라인 (코드 기준)

진입점 `inference/scripts/inference_psd.py` → `common/utils/inference_utils.py`.

```
입력 RGBA 이미지
 └─ center_square_pad_resize(1280)                      ← 정사각 패딩
     ├─ apply_layerdiff  (SDXL 기반 LayerDiff3D, 30 step, guidance 1.0, bf16)
     │    ├─ [group 0] 전신 1회: front hair, back hair, head, neck, neckwear, topwear,
     │    │            handwear, bottomwear, legwear, footwear, tail, wings, objects   (13장)
     │    └─ [group 1] 'head' 알파의 bbox를 잘라(여백 w/5) 다시 1280으로 확대해 1회:
     │                 headwear, face, irides, eyebrow, eyewhite, eyelash, eyewear,
     │                 ears, earwear, nose, mouth                                      (11장)
     ├─ apply_marigold   (파인튜닝된 Marigold, 768px) 레이어별 + 합성 입력 → 레이어별 depth
     └─ further_extr     (규칙 기반 후처리)
          ├ 눈/눈썹·손·귀 좌/우: connectedComponents 의 면적 상위 2~4개로 L/R 분리
          ├ hair: cluster_inpaint_part → depth K-Means(K=2)로 hairf / hairb 분리 + LaMa 인페인팅
          ├ nose·mouth: RGB 를 **원본 픽셀로 되돌림**(생성 안 함)
          ├ depth_median 보정(눈·코·입은 얼굴보다 앞, 귀는 뒤)
          └ depth_median 내림차순으로 PSD 레이어 순서 결정 → save_psd
```

핵심 설계 4가지:

1. **"3D" = 레이어 축 어텐션.** SDXL UNet의 공간 어텐션 뒤마다 *part 차원*(비디오 확산의 시간 축처럼 레이어를 쌓은 축)으로
   어텐션을 한 번 더 건다(`CrossFrameAttnDownBlock`, `UNetMidBlockCrossFrameAttn`). 이 덕에 한 레이어에 비어 있는 내용을
   다른 레이어의 예측을 보고 채운다(논문 §4.1.2, Table 1: 이 모듈로 LPIPS 0.1952→0.1549, 마스크 Dice 0.6480→0.3855).
2. **Transparent VAE** (LayerDiffuse 방식): SDXL VAE 는 그대로 두고 알파를 예측하는 디코더만 학습.
   → **정수 알파가 아닌 반투명 가장자리**까지 나옴. (대신 촘촘한 해칭 선이 일부 뭉개짐 — 논문 부록 G.)
3. **태그 조건**: 레이어마다 클래스 임베딩(`front hair` 등)을 넣는다. 즉 "무엇을 뽑을지"는 고정된 어휘(V3: 23종)이고
   **사용자 프롬프트로 바꿀 수 없다.** (img2live 의 "프롬프트" 입력은 이 모델에 그대로 연결되지 않는다 — §5)
4. **깊이로 층 나누기**: 한 의미 레이어 안에서도 앞/뒤가 섞이는 경우(앞머리/뒷머리가 얼굴을 샌드위치)를
   의사 깊이 모드로 가른다. K=2 만 안정적(논문 §6: "더 많은 하위 층으로는 불안정").

V3 레이어 어휘 (23): `front hair, back hair, headwear, face, irides, eyebrow, eyewhite, eyelash, eyewear, ears,
earwear, nose, mouth, neck, neckwear, topwear, handwear, bottomwear, legwear, footwear, tail, wings, objects`
(후처리 후 `handwear/irides/eyewhite/eyelash/eyebrow/ears` 가 -l/-r 로 갈라짐.)

## 3. 성능·자원 (확인된 숫자)

- 논문 §5.1.1: **1024², RTX 4090 한 장에서 레이어 분해 ≈74초 + 깊이 ≈10초.**
- README: bf16 1280px 에서 **12–16 GB VRAM**, group offload 로 ~10 GB(속도 ×1.5 느림), NF4 양자화 ~8 GB (PSNR ~30 dB / SSIM ~0.96 vs bf16).
  HF ZeroGPU 데모는 한 건 2–3분.
- LayerDiff3D 는 **4B 파라미터**(SDXL UNet 확장), BF16 safetensors.
- 학습: 8×H200 — 확산 1단계 ~24h, 2단계 ~129h, 깊이 ~16h+115h. **재학습은 이 규모를 각오해야 한다**(우리가 고도화한다면 미세조정/LoRA 수준이 현실적).

## 4. 학습 데이터 (우리가 따라 하려면 반드시 알아야 하는 부분)

- 논문 §3: **상용 Live2D 모델**에서 레이어를 뽑아 지도 신호를 만든다. 9,102 샘플(학습 7,404 / 검증 851 / 테스트 847).
  - CubismPartExtr(C++, Cubism Native SDK 5-r.4.1 기반)가 `.moc3` → drawable 별 RGBA 추출.
  - 각 ArtMesh 조각에 Danbooru 태거(wd-eva02-large-tagger-v3)의 GradCAM++ 점수를 투표시켜 클래스 부여 → SAM-HQ 로 정제 → 사람이 12시간 교정.
  - 증강: Live2D 의 "angle following" 애니메이션으로 상/하/좌/우/사선 **자세를 돌려 비강체 포즈 데이터를 공짜로 생성**.
  - 깊이 라벨: ArtMesh z-buffer(그리기 순서)를 [0,1] 로 정규화.
- **이 데이터의 라이선스 처리는 논문 HTML/README 어디에서도 찾지 못했다**(미확인 — 논문 부록·보충자료 전문은 못 읽음). 레포에서 확인되는 공개물은 코드·가중치·`anime_segmentation_bg` 배경 데이터셋이며, Live2D 에서 뽑은 학습 샘플 자체의 공개 여부는 확인하지 못했다.
- 시사점 두 가지:
  1. **라이브2D 모델은 "정답 분해 + 정답 리그"를 동시에 가진 유일한 데이터**다. 우리가 리깅 모델을 학습시키려면 같은 종류의 데이터가 필요 → 합법적 확보 경로가 사업 리스크의 핵심(→ `04-legal-license.md`).
  2. "angle following" 증강은 **회전 키폼이 학습 신호가 될 수 있다**는 증거 — 우리 리깅의 머리 회전 단계 설계에 쓸 수 있다.

## 5. 라이선스 (직접 확인)

| 구성요소 | 확인 결과 | 상업 서비스 |
|---|---|---|
| see-through **코드** | Apache-2.0 (`LICENSE`) | OK |
| **LayerDiff3D 가중치** (`layerdifforg/seethroughv0.0.2_layerdiff3d`) | HF 카드: `openrail++`, "Commercial use is permitted", 단 Animagine XL 4.0 / SDXL 1.0 (CreativeML Open RAIL++-M), LayerDiffuse (Open RAIL-M), SDXL-VAE-FP16-Fix(MIT) 상속. **사용 제한 조항을 서비스 약관에 그대로 옮겨야 함.** 학습 데이터 설명 없음. | 조건부 OK |
| **Marigold(깊이) 가중치** | **확정(2026-09-28)** — GitHub 이슈 #43 에 저자(ljsabc)가 답변: Marigold v1.1 기반이라 **Open RAIL++-M 승계**, 상업 사용 OK. 카드 5개 모두 `license:` 필드와 `LICENSE`·`NOTICE` 추가 | 조건부 OK (아래 조건) |
| **SAM 몸 분할 가중치** (`24yearsold/l2d_sam_iter2`) | **확정** — SAM-HQ 기반, 순수 Apache-2.0, 상업 OK | OK |
| 학습 데이터(상용 Live2D 모델) | 서술 없음 | 가중치 사용 자체의 잔여 리스크 |

저자 답변 요지(원문 확인): "Commercial use is fine for all three. The two Open RAIL models need one extra step: if you run them in a service,
**your terms of use have to include the licence's use restrictions (paragraph 5 and Attachment A).** … crediting See-through in your product and citing the paper is highly recommended."
(LayerDiff3D 카드에 있던 `apache-2.0` 표기는 불완전했다고 저자가 인정. 옛 스냅샷·포크를 근거로 삼지 말고 사용 시점의 HF 커밋 해시를 고정할 것.)

→ 결론: See-through 가중치는 **상업 서비스에 쓸 수 있다.** 조건은 ① 이용약관에 OpenRAIL 사용 제한(Attachment A) 전달, ② 출처 표기.
남는 리스크는 **학습 데이터(상용 Live2D 모델)의 권리 처리**로 우리가 통제할 수 없다. 그래서 See-through 를 **교체 가능한 1단계 모듈**로 두고,
장기적으로 권리가 정리된 데이터로 파인튜닝한 자체 모델로 갈아탈 수 있게 입출력 계약을 고정한다.

## 6. 알려진 한계 (논문 §6, 부록 D/F/G + GitHub 이슈)

- 분해된 레이어 사이에 **가장자리 겹침/생성 픽셀 침범**(#40), 얼굴 디테일 부족(#39), 그림자 처리 한계(#35), 소매/장갑 특수 케이스(#14).
- 상의/하의 경계 모호(원피스), 신발 혀 부분 어긋남, 깊이 K-Means 가 2층 이상은 불안정.
- 애니 스타일 한정(실사 #2, 만화 #5 미지원).
- **사용자 연구(작가 7명 중 6명 응답)**: PSD 로 "30–60분 안에 모션 초안" 가능. 요구사항 = 좌/우 팔 더 세분화, **변형 힌트(모션 곡선·타이밍 템플릿)**.
  → 저자들이 말하는 "리깅 부재" 가 실제로 사용자가 요구한 항목이다.

## 7. 라이브2D 로 가기 위해 See-through 출력에 **없는 것** (갭 분석)

| # | 라이브2D 표준 리그가 필요로 하는 것 | See-through 출력 | 갭 |
|---|---|---|---|
| G1 | **눈 감김**: 눈꺼풀 피부 + 감은 속눈썹(눈 열림/닫힘 키폼) | irides / eyewhite / eyelash 는 있으나 **눈 감은 상태 없음**. ~~`face` 가 눈꺼풀 면을 가졌는지 미확인~~ → **실측(2026-10-02, n=1): `face` 는 눈 자리를 피부로 메운다**(눈꺼풀 면 있음, 희미한 잔상 1곳). 눈 **감은 상태 자체**(감은 속눈썹)는 여전히 없음 → `07` §5 | 생성 필요 |
| G2 | **입 모양**(A·I·U·E·O), 입안·이·혀 | `mouth` 는 **원본 픽셀을 그대로** 복사(생성하지 않음) | 생성 필요 |
| G3 | **머리 좌우/상하 회전**(ParamAngleX/Y)에 따른 시차·가림 | 깊이 맵만 있음. 시점 변환 데이터 없음 | 키폼 생성 or 깊이 시차 |
| G4 | **몸 회전·호흡·팔 스윙** (몸 레이어 분할) | topwear/bottomwear 는 덩어리, 팔은 handwear(L/R) 하나뿐 | 팔 상/하박 분할 등 |
| G5 | **머리카락 가닥 단위 스웨이**(물리용 체인) | front/back 2층만 | 분할 + 체인 추정 |
| G6 | **ArtMesh / 디포머 / 파라미터 / 키폼 / 물리 / 모션** | 없음 | 리깅 전체 |
| G7 | 파츠 ID·표준 파라미터 이름 | 자체 태그 | 매핑 |
| G8 | 해상도 | 1280² 고정 학습, 정사각 패딩. **실측: 전신 928×1232 입력에서 얼굴 118×134px, 입 6×6px — 머리 패스가 1280 으로 생성한 디테일을 `smart_resize` 로 다시 원본 스케일로 줄여 버림**(`07` §5) | 머리 레이어를 생성 해상도로 유지/업스케일 필요 |

img2live 의 핵심 R&D 는 **G1·G2(상태 변형 생성), G3(회전), G5·G6(리깅 자동화)** 이다. 이 중 G1·G2 는 "최신 범용 생성 모델"이
가장 잘 맞는 자리이고(→ `02`), G3·G6 는 기하/규칙 + 학습 혼합이 필요하다(→ `03`).

## 8. 재사용 가능 자산 (로컬 레퍼런스)

- `common/modules/layerdiffuse/*` — 레이어 축 어텐션 UNet + 투명 VAE (추론/학습 모두).
- `common/modules/marigold/*` — 깊이 파이프라인. `common/modules/sam/*` — SAM-HQ 신체 분할.
- `annotators/*` — anime face detector, anime instance seg, WD tagger, LaMa. (mmdet/detectron2 의존, 설치 난이도 높음)
- `inference/scripts/parse_live2d.py` (1,559줄), `common/live2d/scrap_model.py` (1,363줄) — **라이브2D 모델을 레이어+태그로 파싱하는 코드.** 반대로 우리가 만든 리그를 검증하는 데에도 응용 가능.
- `inference/scripts/inference_psd_quantized.py`, `inference_psd_blockswap.py` — 저VRAM 경로(서비스 비용 절감에 직결).
- `training/*` — 8×H200 기준 학습 스크립트·설정(재현·미세조정 시작점).
- `ui/*` — PyQt 기반 라벨링 UI(레이어 교정 UI 설계 참고).
