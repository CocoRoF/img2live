# 08 · 스튜디오: 레이어 제어·편집·부분 재생성 (2026-10-03)

사용자 요구(요약): 퍼펫 화면에서 **레이어를 제어**하고, **특정 레이어만 고치거나 다시 생성**해 품질을 조절할 수 있어야 한다. 레이아웃은 `[헤더] + [메인=전체 폭]`, 가운데 정렬 래퍼 금지. prj-geny 의 geny-avatar 레이어 시스템을 참고(복사 또는 새로 구현).

## 1. geny-avatar 에서 가져온 것과 버린 것

조사 결과(서브에이전트가 코드를 읽고 정리, 2026-10-03):

| geny-avatar | 우리 |
|---|---|
| 편집의 단위 = 레이어별 **대체 텍스처 1장 + 마스크**(알파가 기준, 먼저 지우고 그림) | 같은 원리. 우리는 레이어마다 **자기 텍스처**가 있어 아틀라스·삼각형 클리핑이 필요 없다 |
| 분해 스튜디오: 브러시·지우개·양동이·마술봉(알파/밝기/RGB 허용오차, 연결 여부, 샘플 창)·선택 확장/축소/페더/반전·연결 성분·개미 행진·2배 해상도 가장자리 | 같은 도구 모음을 직접 구현 + **올가미**(그쪽엔 없음) |
| 영역 재생성 = 외부 이미지 편집 모델(gpt-image) 호출: 영역 크롭 → 흰 배경 정사각형 패딩 → 결과를 **원본 실루엣으로 알파 잠금** → 블렌드(ai-only / mask-hard / mask-soft) | 우리의 생성기는 **LayerDiff3D**(자체 모델). 같은 후처리 원칙(실루엣 잠금, 원본 대조)을 쓴다 |
| 저자들이 적은 약점: 모델이 실루엣 안에 캐릭터를 통째로 환각, 부위 간 팔레트 불일치, 시드·진행 표시 없음, 후보가 레이어 단위 1급이 아님, **텍스처 변경에 undo 없음**, 침식이 재생성마다 누적 | 후보(variant)를 **레이어 단위 1급**으로, 모든 변경이 **버전**이라 undo/redo, 시드·진행 표시, 원본 실루엣은 따로 보관 |
| 지울 때 `destination-out` 후 그리기(그냥 source-over 는 지운 픽셀이 되살아남) | 서버에서 numpy 로 알파를 직접 쓴다 |
| 레이어 이동/병합/솔로/잠금/정렬 UI 없음, 캔버스에서 레이어 선택·강조 없음 | 솔로·숨김·정렬·**캔버스 클릭으로 선택**·선택 강조·픽셀 **다른 레이어로 옮기기** 를 넣는다 |

## 2. 화면

`/j/{id}` 가 스튜디오다(작업 중에는 진행 화면). 레이아웃은 `[헤더 52px]` + `[메인: 남은 높이 전부, 전체 폭]`.

```
┌ 헤더 ────────────────────────────────────────────────────────────────┐
├ 레이어 (300) ┬ 무대 ─────────────────────────────┬ 검사기 (360) ──────┤
│ 검색         │  퍼펫 / 레이어 편집기(전환)        │ 탭: 움직임 · 레이어 │
│ 그룹▾ 머리…  │  떠 있는 도구줄(배경·맞춤·와이어…) │      · 보고서 · 파일│
│ 행: 👁 썸네일 │                                    │                     │
│  이름 배지 S  │                                    │ 레이어 탭:          │
│              │                                    │  포함 스위치·순서    │
│              │                                    │  버전 목록(원본·편집 │
│              │                                    │  ·후보) · 편집 ·    │
│              │                                    │  다시 생성 · 원본으로│
└──────────────┴────────────────────────────────────┴─────────────────────┘
```
- 레이어 행: 눈(미리보기에서 숨김, 서버 변경 없음), 썸네일, 이름, 배지(편집됨 / 후보 n / 제외됨 / 비어 있음), 솔로(S). 행 클릭 = 선택(무대에 윤곽 강조, 검사기 레이어 탭 열림). **무대에서 퍼펫을 클릭해도 그 레이어가 선택**된다.
- 레이어 편집기는 무대 자리를 차지하며(전환), 원본 이미지를 겹쳐 보여 준다. 적용하면 서버가 퍼펫을 다시 컴파일하고(CPU 2~4초) 무대가 새 퍼펫을 다시 읽는다(슬라이더 값 유지).

## 3. 서버 상태와 버전

작업 폴더의 `studio/` 아래에 둔다(처음 열 때 기존 `layers/`·`layers_hires/` 에서 v0 를 만든다).

```
studio/state.json                          레이어별 {enabled, order, current, history, versions[]}, rev
studio/v/<tag>/<vid>.png                   그 레이어의 편집 격자 전체(1280², RGBA) 한 버전
studio/puppet/r<rev>/puppet.json + tex/    현재 퍼펫(리비전마다 새 폴더 → 캐시 문제 없음, 최근 3개만 보관)
```
- **편집 격자**: 몸 레이어는 `canvas`(소스를 정사각 캔버스에 놓은 1280²), 머리 부품(얼굴·눈·코·입·귀·눈썹·속눈썹·홍채·머리 장식 등 고해상도 머리 패스가 있는 것)은 `head`(머리 사각형 `head_square` 를 1280² 로 확대한 격자). 머리 격자 레이어의 캔버스 복사본은 재컴파일 때 `head_to_canvas` 로 만든다.
- 버전 종류: `original`(v0, 파이프라인이 낸 결과) · `edit`(사용자 편집) · `regen`(다시 생성한 **후보**, 자동 적용 안 됨) · `auto`(자동 정리).
- `current` 는 지금 쓰는 버전. 편집은 새 `edit` 버전을 만들어 current 로. **undo = 이전 current 로 되돌리기**(스택), 어떤 버전이든 골라 current 로 만들 수 있다(후보 비교와 같은 동작).
- 레이어 플래그: `enabled`(퍼펫에 포함), `order`(그리기 순서, 기본은 `DRAW_ORDER`).

## 4. REST 계약 (`/api/jobs/{id}/studio/…`, 작업 id 가 열쇠 — 로그인 없음)

| 메서드·경로 | 본문 → 응답 |
|---|---|
| `GET …/studio` | → `{rev, puppet, canvas, head_square, layers[], tasks[], can_regen}` ; 레이어 = `{tag,label,group,grid,enabled,order,order_default,current,versions[{id,kind,note,seed?,created}],bbox,opaque_px,empty}` |
| `GET …/studio/layer/{tag}/image?v=<vid\|current>` | → PNG, 편집 격자 전체 크기 |
| `GET …/studio/layer/{tag}/thumb?v=<vid\|current>` | → PNG, 캐릭터 영역만 잘라 ≤160px |
| `GET …/studio/source?grid=canvas\|head` | → 그 격자로 옮긴 소스 이미지(PNG, RGBA) |
| `POST …/studio/layer/{tag}/edit` | `{op, mask?, to?, feather?, note?, rebuild?}` → `{ok, state}` ; `op` = `erase`(마스크 부분 알파 0) · `restore`(마스크 부분을 **소스 픽셀로 채움**) · `move`(마스크 부분을 `to` 레이어로 옮김) · `clean`(자동 정리: 충실도 판정) · `fill_hole`; `mask` 는 격자 크기 8비트 회색 PNG 의 base64(127 초과 = 선택) |
| `POST …/studio/layer/{tag}/select` | `{version}` → `{ok, state}` (undo·redo·후보 적용) |
| `POST …/studio/layer/{tag}/flags` | `{enabled?, order?}` → `{ok, state}` |
| `DELETE …/studio/layer/{tag}/version/{vid}` | 후보·편집 버전 삭제(원본·current 제외) → `{ok, state}` |
| `POST …/studio/rebuild` | → `{ok, state}` (편집 요청의 `rebuild:false` 로 모아 둔 변경을 한 번에 반영) |
| `POST …/studio/reset` | 모든 레이어를 v0·포함·기본 순서로 → `{ok, state}` |
| `POST …/studio/regen` | `{tags[], seed?, steps?, head_margin?}` → `{task}` (GPU 작업기에서 실행, 결과는 `regen` 후보 버전) |

모든 쓰기는 작업 폴더 잠금 아래에서 하고, 재컴파일이 끝난 뒤 `rev` 를 올린다. 삭제된 작업이면 404.

## 5. JS 모듈 계약

- `js/studio-api.js` — 위 REST 의 얇은 래퍼(`studioApi(jobId)`), 마스크 캔버스 → PNG base64 변환.
- `js/stage.js` — **무대**(뷰어 엔진만, UI 없음): `createStage(container, {puppetUrl, onPick, onReady})` → `{reload(url,{keepParams}), layers, setVisible(tag,on), setSolo(tag|null), highlight(tag|null), pickAt(x,y), params(get/set/reset/list), option(name,on), setBackground, resetCamera, snapshot(), dispose()}`.
- `js/layer-editor.js` — **레이어 편집기**: `mountLayerEditor(container, {api, tag, label, grid, layers, onApplied(state), onClose()})` → `{setTag(tag), dispose()}`. 서버를 직접 부르지 않고 `api` 객체만 쓴다(테스트에서 대체 가능).
- `js/job.js`(스튜디오 본체)가 위 둘과 레이어 패널·검사기를 묶는다.

## 6. 재생성(GPU)

- 단위는 **모델의 그룹**: 몸(13태그) 한 번 · 머리(11태그) 한 번. LayerDiff3D 는 태그 수를 고정하지 않으므로(`num_frames = len(prompt)`) **원하는 태그만** 넣어 돌릴 수 있다 — 얼마나 품질을 유지하는지는 GPU 로 실측한다(§8).
- 조절값: **시드**, **스텝**, 머리는 **머리 크롭 여백**(머리 장식이 잘릴 때 키움 / 얼굴 디테일을 더 얻으려 줄임 — 머리 부품 전체가 한꺼번에 바뀐다).
- 결과는 정리(실루엣 잠금·가장자리 색 보정)와 충실도 판정을 거쳐 `regen` 후보 버전으로 저장된다. 사용자가 비교하고 적용한다.
- 작업 큐: `studio_tasks` 표. 워커는 작업(jobs)과 재생성 작업을 FIFO 로 처리하고 GPU 를 한 번에 하나만 쓴다.

## 7. 단계

1. (완료) 전체 폭 홈, 내 퍼펫(브라우저 저장), 1년 보관.
2. 스튜디오 껍데기 + 레이어 패널 + 무대 API (클라이언트만).
3. 서버 스튜디오(버전·편집·재컴파일) + 레이어 편집기.
4. 재생성 작업 + 후보 UI + GPU 실측.

## 8. 실측해야 할 것

- 태그 일부만으로 돌린 결과가 전체로 돌린 결과와 비교해 품질이 유지되는가(시간·소스와의 색 오차·가려진 부분 일관성).
- 시드만 바꿔 다시 생성할 때 실패(배경 쏟기, 몸통 누락)가 얼마나 줄거나 느는가.
- 머리 크롭 여백이 머리 장식 잘림과 얼굴 선명도에 주는 영향.
