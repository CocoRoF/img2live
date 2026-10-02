# img2live: Live2D(Cubism) 포맷 / 라이선스 / 대안 런타임 조사 보고서

- 조사일: 2026-10-02 (모든 "현재 상태"는 이 날짜 기준)
- 목적: See-through(23 레이어 RGBA, PSD 출력) 이후 단계(자동 리깅, 렌더/내보내기)를 어떤 포맷으로 만들지 결정
- 표기 규칙
  - [V] 원문(라이선스 전문, 공식 문서, 저장소 README/소스)을 직접 읽어 확인
  - [V-S] WebFetch 요약본으로만 확인(원문 재확인 권장)
  - [U] 미검증, 추론, 2차 출처, 또는 내 지식에서 나온 것
- 이 보고서는 법률 자문이 아니다. 법적 판단 항목은 7장에 변호사/Live2D 문의 목록으로 따로 모았다.

---

## 0. 먼저 읽을 결론 (TL;DR)

1. 기술적으로 "진짜 .moc3 생성"은 이제 가능하다는 증거가 있다. 2026년 7~10월 사이에 여러 오픈소스가 .moc3 쓰기까지 구현했다(Umamo, psd2live, image2live2d). 이 중 image2live2d는 "See-through 분해 -> 자동 리깅 -> .inp/.moc3/.cmo3"로 우리 파이프라인과 사실상 같은 구조다(Apache-2.0, 38 stars, 2026-09-07 마지막 푸시). 그러나 자동 리깅 품질은 어느 프로젝트도 "첫 초안" 이상을 주장하지 않는다.
2. 법적 병목은 "moc3를 쓸 수 있느냐"가 아니라 "Cubism Core로 사용자 생성 모델을 공개 웹에서 렌더링하느냐"와 "Live2D 약관의 '2D 크리에이터의 창작을 해칠 수 있는 용도' 금지 조항"이다.
   - Core EULA는 "불특정 다수 모델을 생성/조합하는 파생물"을 Expandable Application으로 정의하고, 소규모 면제(2.2)를 명시적으로 적용 제외한다. 승인 + 별도 계약 + 매출 분배(소규모는 건당 $1.90 또는 매출 20% 중 큰 값, 중/대규모 5%)가 필요하고 "원칙적으로 완전 무료는 승인 대상이 아님"이다.
   - 같은 약관에 "assumed primary use로 2D Creators의 창작성을 해칠 수 있는 파생물 개발/배포 금지"가 있고, Live2D 스스로 "일러스트에서 Live2D 모델링을 완전 자동화하는 연구는 하지 않는다"고 밝혔다. img2live는 이 문구와 정면으로 가까운 위치에 있다.
3. Cubism Editor를 SaaS 백엔드에서 대신 돌리는 길은 막혀 있다(Editor EULA 5.1.7 No Service Bureau). Editor 5.4 alpha의 External API에 편집 API가 추가됐지만(2026-07-14) GUI 실행 + 사용자 승인 + ArtMesh 생성/PSD 임포트 불가로 헤드리스 자동화가 안 된다.
4. 브라우저 렌더링은 Core 없이도 가능해졌다. 오픈 재구현인 Ayagami(Rust, wgpu, WebGL/WebGPU, MIT/Apache-2.0)와 Purism Core(C99, MIT, WASM 빌드, "Live2D 라이선스 불필요"라고 주장)가 있다. 다만 둘 다 "Live2D가 문제 삼지 않을 것"이라는 낙관일 뿐이며 Live2D의 공식 입장은 확인하지 못했다(없음).
5. moc3의 최대 가치는 VTube Studio 호환이다. VTube Studio는 Live2D 모델만 지원하고 VRM/3D는 지원하지 않는다[V-S]. Warudo/VNyan은 VRM 계열이다[V-S]. Inochi2D는 소규모 별도 생태계다.
6. 권고: (C) 하이브리드 단계적 접근. 1단계는 우리 포맷(IRR) + 자체 웹 런타임(Cubism 호환 파라미터 ID, physics3 호환 구조)으로 법적 노출을 최소화하고, 2단계에서 PSD/nijilive(.inp)/투명 영상 내보내기, 3단계에서 "실험적, 비공식" moc3 내보내기를 법무 검토 게이트 뒤에 얹는다. 상세는 6장.

---

## 1. Cubism 파일 포맷

### 1.1 포맷 한눈표

| 파일 | 성격 | 공식 문서 | 오픈 구현 | 생성 난이도 |
|---|---|---|---|---|
| .moc3 | 런타임 바이너리(리틀엔디언, struct-of-arrays) | 공개 문서 없음 [V: Live2D 문서/Core API만 공개] | 아래 1.3 | 높음(바이너리 + Core 일관성 검사) |
| .cmo3 | Cubism Editor 프로젝트(CAFF 컨테이너 + main.xml) | 없음 | Umamo, psd2live, image2live2d 등 | 높음(Editor 클래스 그래프) |
| .can3 | Editor 애니메이션 프로젝트 | 없음 | Stretchy Studio(can3writer.js) 등 | 중간 [U] |
| .model3.json | 모델 매니페스트(JSON) | 공개: Live2D/CubismSpecs [V] | 단순 | 쉬움 |
| .physics3.json | 물리(진자) 설정(JSON) | 공개 [V] | 단순 | 쉬움(튜닝은 어려움) |
| .motion3.json | 모션 커브(JSON) | 공개 [V] | 단순 | 쉬움 |
| .pose3.json | 파트 전환 그룹(JSON) | 공개 [V] | 단순 | 쉬움 |
| .exp3.json | 표정(파라미터 덮어쓰기/가산/곱) | 공개 [V] | 단순 | 쉬움 |
| .cdi3.json | 표시명/파라미터 그룹(JSON) | 공개 [V] | 단순 | 쉬움 |
| .userdata3.json | ArtMesh 사용자 데이터 | 공개 [V] | 단순 | 쉬움 |
| motionsync3.json | MotionSync(립싱크) 설정 | 공개 [V] | 선택 | 선택 |

- JSON 계열은 모두 Live2D가 스펙을 공개한다(저장소 Live2D/CubismSpecs, FileFormats/*.json.md, 최종 갱신 2026-08-05). 출처: https://github.com/Live2D/CubismSpecs/tree/master/FileFormats [V]
- Ayatsuri2D의 docs/format.md도 같은 판단이다: "Every JSON file there is publicly specified by Live2D ... The .moc3 binary is the only piece that does [need reverse engineering]". https://github.com/Yoru-KenomoVT/ayatsuri_2d/blob/main/docs/format.md [V]
- 공식 파일 형식 설명: https://docs.live2d.com/en/cubism-editor-manual/file-type-and-extension/ [V-S]

#### JSON 스펙 핵심(우리가 직접 생성할 것)
- model3.json: `Version:3`, `FileReferences{Moc, Textures[], Physics, UserData, Pose, DisplayInfo, Expressions[], Motions{그룹명:[{File,FadeInTime,...}]}}`, `Groups[{Target:"Parameter", Name:"EyeBlink"|"LipSync", Ids[]}]`, `HitAreas`. 필수는 Moc, Textures뿐. [V]
- physics3.json: `Meta{PhysicsSettingCount, TotalInputCount, TotalOutputCount, VertexCount, Fps, EffectiveForces{Gravity,Wind}, PhysicsDictionary}`, `PhysicsSettings[]{Input[{Source{Target:"Parameter",Id}, Weight, Type:"X"|"Angle", Reflect}], Output[{Destination, VertexIndex, Scale, Weight, Type, Reflect}], Vertices[{Position, Mobility, Delay, Acceleration, Radius}], Normalization{Position{Min,Default,Max}, Angle{...}}}`. [V]
- motion3.json: `Meta{Duration,Fps,Loop,CurveCount,TotalSegmentCount,TotalPointCount,...}`, `Curves[{Target:"Model"|"Parameter"|"PartOpacity", Id, Segments[평탄화 배열: 선형=0, 베지어=1, 계단=2, 역계단=3]}]`. [V]
- cdi3.json: `Parameters[{Id,GroupId,Name}]`, `ParameterGroups`, `Parts[{Id,Name}]`, `CombinedParameters`. [V]

### 1.2 .moc3 바이너리 구조 (커뮤니티 문서 기준)

공식 바이너리 스펙은 없다. 가장 신뢰할 만한 공개 근거는 OpenL2D의 ImHex 패턴 `moc3.hexpat`(v2.1b, 버전 1~5 지원, "pattern has not been fully verified for correctness")이다. https://github.com/OpenL2D/moc3ingbird/blob/master/src/moc3.hexpat [V]

- 라이선스 선언(원문): "you are free to use the included model files and pattern files to create your own MOC3 readers and writers. No license will restrict your right to do so." 그리고 "No file in this repository was derived from the output of any Live2D software." [V] https://github.com/OpenL2D/moc3ingbird (저장소는 2026-06-06 아카이브됨, 후속은 Sakura Motion 조직)
- 헤더 64B: `"MOC3"` + 버전 바이트(1=3.00, 2=3.03, 3=4.00, 4=4.02, 5=5.00) + 엔디안 플래그 + 패딩. Cubism 5.3 Editor가 내보내는 moc3는 버전 6이며 Core 5 이하는 읽지 못한다: "The Core unsupport later than moc3 ver:[5]. This moc3 ver is [6]." [V] https://docs.live2d.com/en/cubism-sdk-manual/compatibility-with-cubism-5-3/
- 섹션 오프셋 테이블(SOT) 160 x u32 @0x40, Count Info Table(파트/디포머/워프/회전/ArtMesh/파라미터/키폼/UV/인덱스/마스크/드로우오더 그룹/글루 등 23개 + 4.02 이상은 색상/블렌드셰이프 카운트, 5.00은 파트/회전 디포머/글루용 블렌드셰이프 카운트 추가), Canvas Info(pixelsPerUnit, originX/Y, width, height, reverseY 플래그). [V hexpat]
- 본문은 struct-of-arrays: 속성 하나를 모든 객체에 대해 연속 배열로 저장(예: `art_mesh.texture_indices`). 섹션은 64바이트 정렬, 데이터 시작은 관례상 0x7C0(1984). [V py-moc3 README, V image2live2d moc3_binary.py 주석]
- 객체 종류 [V hexpat]
  - Part: id(64바이트 ASCII), 키폼 바인딩/키폼 시작/개수, visible/enabled, 부모 파트
  - Deformer: id, 타입(0=Warp, 1=Rotation), 부모 파트/부모 디포머, 타입별 인덱스
  - Warp Deformer: rows, columns, vertex count(= (rows+1)*(cols+1)), 키폼
  - Rotation Deformer: baseAngle, 키폼마다 angle/originX/originY/scale/reflectX/reflectY/opacity
  - ArtMesh: id, 텍스처 번호, DrawableFlags(blendMode 2비트, isDoubleSided, isInverted(마스크 반전)), 정점 수, UV 시작, 위치 인덱스(s16 삼각형 인덱스) 시작/개수, 마스크 시작/개수, 키폼(opacity, drawOrder, 위치)
  - Parameter: id, min/max/default, repeat, decimalPlaces, 바인딩 시작/개수
  - KeyformBinding / ParameterBinding / Keys: "어떤 파라미터의 어떤 키 값들에서 어떤 키폼을 쓰는가"의 인덱스 체인
  - Draw Order Group(+Objects), Glue(+Info, Keyform), 4.02+: Multiply/Screen 컬러 키폼, 블렌드셰이프(바인딩/제약), 5.00+: 파트/회전 디포머/글루용 블렌드셰이프
- 구현자들이 겪은 제약(2차 출처, 아래 1.3의 "출처 오염" 주의) [V as 문서 내용]
  - 일부 구현은 Core가 begin<total 검사를 count=0이어도 수행해 DRAWABLE_MASKS를 최소 1로 두어야 한다고 보고함(Stretchy Studio MOC3_FORMAT.md). image2live2d는 "Cubism requires the TOTAL moc size to be a multiple of 64", "데이터는 0x7C0부터"라고 경험적으로 기록.
  - 2023-03 CVE-2023-27566(Core가 오프셋 경계 검사 안 함) 이후 패치된 Core는 "올바른 형식인데도" 읽지 못하는 moc3가 있다고 Live2D가 공지: https://docs.live2d.com/en/cubism-editor-manual/addressing-vulnerabilities/ [V-S]. 즉 생성 moc3는 `csmHasMocConsistency` 수준의 일관성을 엄격히 만족해야 한다. 공식 검증 툴: "Cubism MOC3 Consistency Checker"(v1.00.04, 5.3 지원, 다운로드에 약관 동의 필요) https://docs.live2d.com/en/cubism-editor-manual/moc3-consistency-checker/ [V-S]
  - 구버전 호환: 새 Core는 옛 moc3를 읽지만 옛 Core는 새 moc3를 거부한다. Editor는 내보내기 대화상자에서 대상 SDK 버전을 고르게 한다(https://docs.live2d.com/en/cubism-editor-manual/export-moc3-motion3-files/ [V-S]). 따라서 우리는 "표현 가능한 최저 버전"을 쓰는 것이 호환에 유리하다(image2live2d는 v3.00만 구현하고 "현행 Cubism 4/5 런타임에서 로드 가능"이라 주석) [V].

### 1.3 오픈소스 moc3 구현 지도 (2026-10-02, GitHub API/README 확인)

| 프로젝트 | 언어 | 읽기 | 쓰기 | 버전 | 라이선스 | 상태/신뢰도 | 출처(provenance) |
|---|---|---|---|---|---|---|---|
| OpenL2D moc3.hexpat | ImHex 패턴 | 문서 | - | v1~5 | FDPL-1.0-US(+ 읽기/쓰기 구현 허용 명시) | 아카이브, "완전 검증 안 됨" | Live2D 소프트웨어 출력물에서 파생되지 않았다고 선언 [V] |
| Umamo (umamoorg/umamo) | Kotlin(JVM/Android) | O | O (CMO3도 R/W) | "up to Cubism 5.4" | GPL-3.0 | 2026-07-13 시작, v0.4.0(2026-09-30), 145 stars. 초기 개발, 독립 검증 [U] | "clean-room ... black-box observation", 기여자 조건(Live2D 소스/디컴파일 노출자, 직원 배제) [V] |
| psd2live (tsunehimatoi) | Kotlin/Java | O | O (.cmo3 + .moc3 + 사이드카) | Cubism 3.0~5.0 선택(기본 5.0) | GPL-3.0 | 2026-09-03 생성, v2.0.1(2026-10-02), 529 stars. 빠르게 변함 | Umamo 모듈(format/runtime/interop/render/edit) 통합 [V THIRD_PARTY_NOTICES] |
| image2live2d (Wzhang3912) | Python | O | O (.moc3 v3.00 최소 레이아웃, 옵트인) | v3.00 | Apache-2.0 | 38 stars, 마지막 푸시 2026-09-07. "공식 v3 모델 5개와 byte-for-byte 검증" 주장 [U 독립검증 불가] | OpenL2D hexpat 기반 구현이라고 소스 주석에 명시 [V] |
| py-moc3 (Ludentes) | Python | O | O (수정 후 재저장, 바이트 동일 round-trip) | 3.00~5.00 | MIT | 4 stars, 커밋 2개. 처음부터 생성 기능은 README에 없음 | README: "Ported from moc3-reader-re (Java decompilation of the Cubism SDK exporter)" -> 디컴파일 계보 [V] |
| QiE2035/moc3-reader-re, YusaeMiu/moc3-reader-re | Java | O | O(오프셋 목록 초기화 필요) | - | 없음 | 2022, 아카이브 | 이름 자체가 "reversing Live2D Cubism" [V] |
| vtubing/moc3 | Rust | O | X | 3.0~5.0 | MIT | 2023 | hexpat 사용 [V] |
| moc3-rs (MahouTechnologies) | Rust | O(+렌더) | X | 4.2 목표, 파트 미지원 | Apache-2.0/MIT | 6 stars | OpenL2D 문서 기반 [V] |
| Ayagami (AyagamiDev) | Rust | O(+드라이버/렌더) | X | 5.0 + 5.3 기능(고급 블렌드/오프스크린) | MIT/Apache-2.0 | 342 stars, 2026-09-14 푸시, 웹 데모 있음 | "black-box reverse engineering only", VTube Studio를 테스트 오라클로 사용 [V] |
| PurismCore (SakuraMotion) | C99 | O(Core ABI 재구현) | X | Core 5.1/6.0 ABI 호환, 5.3 moc3 로드 | MIT | 39 stars, 1.1.0 릴리스 준비 커밋(2026-08-21), 내부 10,000+ 테스트 주장 [U 독립검증 불가] | "reimplementation of Live2D Cubism Core without any Live2D code" [V] |
| Stretchy Studio moc3writer.js | JS | - | O (V4.00) | v3(4.00) | MIT | 494 stars, 마지막 푸시 2026-04-28 | 문서에 "IDA Pro reverse engineering of Live2DCubismCoreJNI.dll", "Decompiled ... Live2D_Cubism.jar via CFR" 명시 -> 오염 [V] |
| Ayatsuri2D (Yoru-KenomoVT) | Rust | 계획 | 계획 | v3~v6 | GPL-3.0 | 2026-09-08 생성, "format research done, code being written" | 문서상 쓰기가 "일부 섹션의 trailing bytes가 0이 아니라 막혀 있다"고 기록 [V] |

해석:
- "실제로 moc3를 쓰는" 구현은 Umamo(및 그것을 쓰는 psd2live), image2live2d, py-moc3(수정형), Stretchy(V4.00)다. 사실상 독립적으로 Cubism Core/VTube Studio에서의 광범위한 호환성을 검증한 보고는 없다(각 README의 자기 주장뿐) [U].
- 출처 오염(provenance) 문제가 중요하다. Live2D는 2019년에 디컴파일 기반 리포지터리에 대해 EULA 위반을 주장했다(3.1절 (8) 참고). Stretchy/py-moc3 계열의 문서·코드는 디컴파일/IDA RE에 기대어 있으므로 우리 코드의 근거로 쓰는 것을 피해야 한다. 깨끗한 근거는 (1) OpenL2D hexpat, (2) CubismSpecs JSON 문서, (3) Ayagami/Purism/moc3-rs를 블랙박스 오라클로 한 자체 실험이다.
- 쓰기 구현의 완성도 지표: psd2live의 "수출 성공 != 모든 런타임에서 동일 효과"라는 자체 경고, Ayatsuri2D의 "쓰기는 아직 일부 섹션이 틀림", Umamo "alpha, 백업하라" [V]. 즉 완전하지 않다.

### 1.4 .cmo3

- 구조: "CAFF" 매직 + 아카이브/포맷 버전 + 난독화 XOR 키(int32) + 파일 테이블 + (RAW/ZIP 압축, 선택적 XOR 난독화) 엔트리 + 가드 바이트. 핵심 엔트리는 main.xml(Java 직렬화 스타일: `xs.id`/`xs.ref`/`xs.n`, 클래스명 CModelSource, CArtMeshSource, CWarpDeformerSource, CParameterSource, ...)과 레이어 PNG들. [V: Stretchy CMO3_FORMAT.md 기술. 단 이 문서는 "Decompiled com.live2d.serialize.XmlWriter ... via CFR"에 의존 -> 오염]
- Umamo는 같은 컨테이너를 독자 구현(`org.umamo.format.cmo3.caff`)하고 "CMO3 ... Compatible up to Cubism 5.4"라고 주장 [V README]. psd2live는 "PSD -> .cmo3 + .moc3" 생성 [V].
- 공식 API/문서는 없다. 에디터 버전마다 `fileFormatVersion` 등이 바뀐다(예: 5.0은 402030000) [V-S Stretchy].
- 용도: 사용자가 Cubism Editor에서 이어서 다듬을 수 있는 "편집 가능한 산출물". image2live2d는 이를 "Experimental, Editor-validation ongoing"으로 표기 [V].

### 1.5 PSD 경로 (공식 지원 경로, 법적으로 가장 안전)
- Cubism Editor는 PSD를 공식 임포트한다. 레이어마다 최소 정점의 ArtMesh를 만들고, 폴더는 Part 계층이 된다. "the lowest layer in each group is ultimately imported as the texture" (그룹 안 최하단 레이어만 텍스처로 쓰이므로 선화/채색은 사전에 병합) [V-S] https://docs.live2d.com/en/cubism-editor-manual/psd-import/
- Editor 5.1+의 자동 디포머 생성(휴머노이드)과 모델 템플릿 적용으로 PSD에서 빠르게 출발 가능 [V-S].
- FREE 버전 한도: ArtMesh 100개, 파라미터 30개(블렌드셰이프 파라미터 포함), 상업 사용은 연매출 1천만 엔 미만 개인/소기업만 [V-S] https://www.live2d.com/en/cubism/comparison/

---

## 2. Cubism SDK 구조와 변형 데이터 모델 (자동 리거 설계용)

### 2.1 구성요소와 라이선스 경계
| 구성요소 | 형태 | 라이선스 | 비고 |
|---|---|---|---|
| Cubism Core | 폐쇄 바이너리(Native 정적/동적, Web은 live2dcubismcore.min.js) | Live2D Proprietary Software License | `csmReviveMocInPlace`, `csmUpdateModel`, `csmGetDrawable*`, `csmHasMocConsistency` 등 C API. Web용 Core JS는 "Redistributable Code"(수정 금지) [V-S] |
| Framework(Web/Native/Java) | 소스 공개(TypeScript 등) | Live2D Open Software License | Core 위에서 렌더/모션/물리/표정 처리. Web R5는 2026-04-02 릴리스(5.3 지원) [V] |
| Samples | 소스 + 샘플 모델 | Open Software License + Sample Material 조항 | 샘플 모델은 "internal evaluation and Training" 한정(5.5절) [V] |
| Editor | 폐쇄 앱(Win/Mac) | Editor Software License Agreement | 현재 5.3.00(2026-01-20), 5.4 alpha(2026-07-14) [V] |

Core가 하는 일: moc3를 메모리에서 "소생(revive)"시키고, 파라미터 값을 받아 키폼을 보간하고 디포머 체인을 적용해 각 드로어블(ArtMesh)의 최종 정점 위치, 불투명도, 드로우 오더(5.3은 render order), 컬러(multiply/screen), 블렌드 모드, 마스크 목록을 출력한다. Framework의 Renderer는 이 출력을 받아 GPU로 그린다. [V 문서 개념 + U 세부]

### 2.2 데이터 모델 (생성기가 방출해야 하는 것)

- ArtMesh: 텍스처 아틀라스 영역을 참조하는 삼각형 메쉬. 정점(좌표), UV, 삼각형 인덱스(s16), 텍스처 번호, 드로우 플래그(블렌드/양면/마스크 반전). 정의: "An image with the mesh assigned is the 'ArtMesh.'" [V-S glossary]
- Warp Deformer: rows x cols 제어점 격자(Bezier 분할 포함). 격자 안의 자식(ArtMesh 또는 다른 디포머) 정점을 격자 변형으로 같이 움직인다. "Deforming a deformer with a mesh in a warp deformer also deforms the mesh inside." [V-S]
- Rotation Deformer: 원점/각도/스케일(+반사)로 자식을 회전/확대. 큰 회전을 선형 보간 키폼으로 하면 정점이 직선 경로로 움직여 수축되므로 회전 디포머를 쓰라는 공식 권고: "each vertex goes through a contracted form once to move along the shortest route connected by a straight line" [V-S https://docs.live2d.com/en/cubism-editor-manual/deformer/]
- 부모-자식: Part(그룹, 드로우 순서/불투명도/표시), Deformer(부모 디포머), ArtMesh가 부모 파트/부모 디포머 인덱스를 가진다. 자식 좌표는 부모 디포머의 로컬 공간(워프는 0~1 정규화 격자 좌표, 회전은 원점 기준)으로 표현된다 [U: Stretchy 문서의 `local = canvas - deformerWorldOrigin` 기술과 hexpat 구조로 추정; 정확한 좌표계는 구현 단계에서 Ayagami/Purism으로 교차검증 필요].
- Parameter와 키폼: 파라미터는 min/default/max. 각 객체(ArtMesh/디포머/파트)는 하나 이상의 파라미터에 키(key value) 목록으로 바인딩되고, 바인딩들의 조합(그리드)마다 키폼(정점 위치/각도/불투명도/드로우오더/컬러)을 가진다. 런타임은 현재 파라미터 값이 속한 격자 셀에서 선형(다차원 선형) 보간한다. 객체당 바인딩 파라미터 수가 늘면 키폼 수가 곱으로 늘어난다(예: AngleX 3키 x AngleY 3키 = 9키폼). [구조는 V hexpat, 보간 방식은 U(Ayagami README가 "Live2D-equivalent interpolation, extrapolation, and deformer chaining algorithms"를 구현했다고만 기술)]
- Blend Shape(Cubism 4.2+/5): 키폼 보간이 아니라 "지오메트리에 차이를 더하는" 방식. 지원 대상: ArtMesh, Warp/Rotation Deformer, Part, ArtPath, Glue. 가중치는 "base key에서 0%, 키에서 최대 100%", 여러 개가 가산된다 [V-S https://docs.live2d.com/en/cubism-editor-manual/blend-shape/]. FREE 버전은 파라미터 30개에 블렌드셰이프 파라미터 포함. 기본 리그에는 불필요 -> 우리 1차 범위에서 제외 가능.
- Clipping Mask: ArtMesh의 `drawableMasks`(다른 ArtMesh 인덱스 목록)로 클리핑, isInverted로 반전. 눈동자를 눈 흰자 안에 가두는 용도.
- Draw Order: ArtMesh 키폼의 drawOrder(0~1000) + Part의 draw order 키폼 + Draw Order Group. 5.3은 render order와 Offscreen(파트 단위 오프스크린 합성), 확장 블렌드 모드(15 컬러 + 5 알파)가 추가(moc3 v6, Core 6) [V compat53].
- Glue: 두 ArtMesh의 경계 정점을 가중치로 이어 붙이는 구속. 팔-몸통 접합 등.
- Physics(진자): physics3.json이 정의. 입력 파라미터(예: ParamAngleX, ParamBodyAngleX, 가중치/타입 X 또는 Angle) -> 진자 정점(Mobility, Delay, Acceleration, Radius) 시뮬레이션 -> 출력 파라미터(예: ParamHairFront)에 값 쓰기. Gravity/Wind, FPS 지정 [V]. 물리는 moc3에 포함되지 않고 Framework가 별도로 구동한다(Core 밖).
- Opacity/Color: 파트/ArtMesh/디포머 키폼에 불투명도, Multiply/Screen 컬러(4.02+) [V hexpat].
- 모션: motion3.json이 파라미터 커브를 재생. 눈 깜빡임/립싱크는 model3.json의 Groups(EyeBlink, LipSync)에 연결된 파라미터에 Framework가 자동 적용 [V].

### 2.3 자동 리거 설계 제안 (See-through 23 태그 -> Cubism 객체) [U, 설계안]

See-through V3 태그(VALID_BODY_PARTS_V3, 23개): front hair, back hair, headwear, face, irides, eyebrow, eyewhite, eyelash, eyewear, ears, earwear, nose, mouth, neck, neckwear, topwear, handwear, bottomwear, legwear, footwear, tail, wings, objects. https://github.com/shitagaki-lab/see-through/blob/main/common/live2d/scrap_model.py [V] 또한 눈/귀/손은 좌우 분리, 머리카락은 깊이 클러스터링으로 앞/뒤 분리가 제공된다 [V-S ComfyUI-See-through README].

| See-through 태그 | Cubism 객체/역할 | 구동 파라미터 |
|---|---|---|
| face | 얼굴 기반 ArtMesh + Face Warp(시차) | ParamAngleX/Y/Z |
| front hair / back hair | 앞/뒤 머리 Warp 2~3단 | ParamHairFront/Side/Back(물리), ParamAngleX/Y 시차 |
| eyewhite | 눈 형상 ArtMesh + 클리핑 마스크 소스 | ParamEyeLOpen/ROpen |
| irides | 마스크로 눈 흰자 안에 가둔 이동 | ParamEyeBallX/Y |
| eyelash | 눈 감김 곡선 변형 | ParamEyeLOpen/ROpen, ParamEyeLSmile/RSmile(선택) |
| eyebrow | 눈썹 이동/기울기/형태 | ParamBrowLY/RY, LAngle/RAngle, LForm/RForm(선택) |
| mouth | 입 열림/형태. 입 안쪽(구강, 치아)은 See-through가 만들지 않으므로 합성 필요 | ParamMouthOpenY, ParamMouthForm |
| nose, ears, earwear, eyewear, headwear | 머리 회전에 종속, 소량 시차 | ParamAngleX/Y/Z |
| neck, neckwear | 목 Warp(머리-몸 연결) | ParamAngleY, ParamBodyAngleX |
| topwear, bottomwear, legwear, footwear | 몸 Warp(호흡, 몸 회전) | ParamBodyAngleX/Y/Z, ParamBreath |
| handwear (좌/우) | 팔 회전 디포머 | ParamArmLA/RA 등(선택) |
| tail, wings, objects | 물리 흔들림 또는 정적 | 커스텀 파라미터 + 물리 |

주의:
- 입 안쪽, 감은 눈 아트, 머리카락 뒤 가려진 영역 등은 See-through만으로는 부족하다. 이미지 편집 모델로 보강하는 단계가 필요(image2live2d는 "표정 생성" 단계에서 마스크 편집 + OpenCV 측정으로 처리) [V].
- Stretchy Studio의 AUTO_RIG_PLAN.md(자체 평가): "No tool fully solves this ... Expecting 'paste PSD -> polished rig' across arbitrary styles is a goal no professional tool achieves without per-character human input", 목표는 "acceptable on ~80-90% of PSDs, and honestly tell the user when it can't" [V]. See-through README도 "Is this Image-to-Live2D? We don't think so — at least, not yet", 리깅은 "not covered in this project" [V].

---

## 3. 라이선스 (핵심)

### 3.1 문서와 핵심 조항

원문 확보: 아래 영문은 번역본이며 일본어 원문이 우선한다("This Agreement shall be executed in Japanese language only, and the Japanese text shall prevail", 준거법 일본법) [V Core EULA 15.1~15.2]. 일본어 원문은 읽지 않았다 -> 최종 해석은 일본어 기준 [U].

#### (1) Live2D Proprietary Software License Agreement (대상: Cubism Core, MotionSync Core)
https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html [V]

- 1.5 Expandable Application: "...the Derivative Work which uses and generates any indefinite number of models by adding or combining files or data (e.g. avatars, live streaming applications, video generators/video makers)..."
- 2.1: Publish/Distribute는 "separate Live2D Publication License Agreement" 필요. Expandable은 사전 신청/승인: "Live2D may, at its sole discretion, approve or reject such application."
- 2.2: 일반 사용자/소규모(연매출 1천만 엔 미만) 면제가 있으나 "this exemption is not applicable for Publishing the Expandable Application".
- 5.2~5.3: Redistributable Code(Core JS 등)는 조건부 재배포 허용(주요 기능이 이를 사용, 이용자에게 동등한 보호 조항 부과, Live2D 면책, as-is). 5.3.1: 계약 없이 "Use the trademark of Live2D in the name of the Derivative Works and Output Files" 금지, 오인 표시 금지.
- 6.4 No Reverse Engineering: "The Customer may not reverse engineer, decompile, disassemble, or otherwise attempt to discover the Source Code of the Software."
- 6.7 No Service Bureau: "...will not use or offer the Software on a service bureau basis to other individuals or legal entities not owning the Software License."
- 6.8: "may not use the Derivative Work or the Output File with software(s) or middleware(s) that compete with or could compete with the Software..." / "may not use the Software to develop, Publish, or distribute Derivative Works that may harm the creativity of 2D Creators as the assumed primary use" / "may not otherwise engage in any acts which Live2D judges inappropriate."
- 8.4: 계약 해지 시 "destroy the Software, all copies thereof, and all Derivative Work including the Output Files".
- AI/ML, moc3/cmo3 형식, 제3자 생성 파일에 관한 명시 조항: 없음(4개 약관 영문본 grep으로 확인) [V].

#### (2) Live2D Open Software License Agreement (대상: Framework, Samples 포함 Cubism Components)
https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html [V]
- 2.2.1/2.3: Framework 배포는 "Runtime Software"(=Core)와 결합될 때만 가능하고, 그 경우 Publication License가 필요: "...unless the 'Live2D Publication License Agreement' is separately executed..."
- 5.5 No Diversion of Sample Material: "The Sample Material or Output Files including the Sample Material may not be used for any purposes other than Internal evaluation of the Software and Training." 여기서 Training은 "the act for the Customer to become proficient in handling or in functions of the Software"(소프트웨어 숙달) 정의(1.9)이며 ML 학습이 아니다.
- 5.7: 6.8과 같은 "harm the creativity of 2D Creators" 조항, 경쟁 미들웨어 조항 포함.
- "Open"이지만 오픈소스가 아니다: Live2D 직원 발언 "our repositories in https://github.com/Live2D are not open-source" [V D2Evil issue #1].

#### (3) Cubism Editor Software License Agreement
https://www.live2d.com/eula/live2D-editor-software-license-agreement_en.html [V]
- 1.8 Output File = "an output file the Customer creates with the Software."
- 2.1.4 License Type별 Output File Usage: PRO for indie/FREE(소규모/개인)는 상업/비상업 모두 가능. FREE(그 외 사용자)와 Evaluation은 내부/비상업/감수 한정. 연 1천만 엔 이상 사업자는 PRO for business 필요.
- 5.1.2 No Reverse Engineering(자기 수정/디버깅 예외).
- 5.1.7 No Service Bureau: "a service for a third party to output files using a function only legitimately available to licensed Customer." 단, "an act of producing works at the request of a third party or selling Customer's own works" 는 제외.
- 5.1.9: Output File을 "competing middleware"와 함께 쓰는 것 금지, 그리고 2D Creators 조항.
- 2.2 Sample Material: "internal evaluation purposes, or training purposes" 한정.

#### (4) SDK Release License (Publication License) 페이지
https://www.live2d.com/en/sdk/license/ , https://www.live2d.com/en/sdk/license/expandable/ [V]
- "Individuals and Small-Scale Enterprises are exempted from the license and payment (except Expandable Application)."
- Expandable Application: "Review and License Agreement are required for every Expandable Application ... applied to all publishers including General Users and Small-Scale Enterprises who are normally exempted"
- 승인 예시 조건: "Existence of a valid revenue model (as a general rule, fully free of charge is not eligible for approval)", 매출 보고 및 매출 분배 지급 동의, (스트리밍 용도) 지정 문구 삽입, Expandable 로고 표시 + Showcase 등재. "approval may not be granted ... in all cases even if the above conditions are met."
- 비용(영문 페이지 표시, USD는 참고 환율): 

| 구분(연매출) | 초기 | 연간(플랫폼당) | 매출분배 |
|---|---|---|---|
| General User/Small-Scale (<1천만 엔) | 무료 | 무료 | 건당 ¥300($1.90) 또는 매출의 20% 중 큰 값 |
| Middle (1천만~1억 엔) | ¥50,000 | ¥240,000 | 5% |
| Large (>=1억 엔) | ¥300,000 | ¥1,200,000 | 5% |

  "Sales"에는 광고 수익도 포함, 분기별 보고 [V].
- 일반(비 Expandable) 웹 앱은 B(비영리, 비배포), E(일회성), G(Running Royalty) 플랜 등이 있고, G는 중규모 월 ¥20,000 x 플랫폼(iOS/Android/HarmonyOS/Web) x 지역 [V running_plan01]. 단 우리 서비스는 Expandable에 해당할 가능성이 높아 이 경로는 적용 안 된다 [U: 해석, Live2D 확인 필요].
- 사업자 규모 기준: 연매출 1천만 엔, 1억 엔(지배회사 매출 합산 규칙 1.25 포함) [V].

#### (5) Live2D Free Material License (샘플/오리지널 캐릭터 다운로드)
https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/ [V]
- 오리지널 캐릭터는 Purpose of Use 범위에서 사용/수정/배포 가능하지만 "may not modify (including significantly altering the original balance of the body ...)" 등 제한, 2D Creators 조항, "may not sell, distribute, or present 2D or 3D models created with third party software ... which use, divert, or deform the Materials". AI 학습에 대한 명시 조항은 없음 [V].

#### (6) Live2D의 AI 관련 공식 입장
- FAQ(2025-03-11): "Live2D does not limit or prohibit any content or the production process thereof, including content that uses AI-related technologies ... the Editor and SDK Terms of Use do not prohibit the use of AI-related technologies for the process of preparing source images or other materials. ... any use that may violate the rights of others, such as infringing use in training data, or development, publication, or distribution of a derivative work (e.g. applications, services etc.) that may harm the creativity of 2D Creators as the assumed primary use is prohibited." [V] https://help.live2d.com/en/other/other_33/
- nizima AI 연구 방침(최종 갱신 2022-04-25): Live2D는 "we do not aim for fully automated modeling by AI", 일러스트에서 Live2D를 완전 자동화하는 연구는 범위 밖, 학습 데이터는 nizima 판매 작품 중 제작자가 옵트인한 것만, "The provided models and textures themselves will not be included in the trained AI." [V-S] https://docs.nizima.com/en/ai-research-policy/

#### (7) 상표
- Core EULA 5.3.1(위). 브랜드 가이드라인(일본어): Live2D/Cubism을 호환성 등을 정확히 서술할 때 언급하는 것은 허용되나 "공식 추천/제휴/지원인 듯한 표현" 금지, "Live2D"는 한 단어, 공식 로고만 사용(변형 금지) [V-S] https://www.live2d.jp/brand
- 오픈소스들은 "nominative use, no endorsement" 면책 문구를 쓴다(Umamo, Ayagami, psd2live) [V].

#### (8) 집행 선례
- 2019-09-20 Live2D Inc.가 UlyssesWu/FreeLive 저장소에 대해 Editor EULA 5.1.2와 Core EULA 6.4 위반을 이유로 "stop providing this Repository ... delete any content"를 요구. 이후 "our repositories ... are not open-source ... Our EULA expressly restricts 'discovering the source code'"라고 보충. 저장소 소유자는 삭제 [V] https://github.com/UlyssesWu/D2Evil/issues/1
- 이후 Live2D가 Umamo/psd2live/Ayagami/Purism에 대해 공개 입장을 낸 증거는 찾지 못했다(2026-10-02) [U: 부재 증명 아님].
- hoshinolina(Ayagami 저자)의 FAQ(2026-09-15 갱신): "file formats are 'utilitarian, not creative'", "Software licenses are a civil contract ... they cannot apply to file formats themselves", "a few prior attempts were legally threatened by Live2D Inc." 그러나 이는 한 개발자의 법적 주장일 뿐이며 판결/자문이 아니다 [V-S] https://gist.github.com/hoshinolina/50154059c87d4c424827bdbf50fcbff7

### 3.2 질문별 답변

(a) 제3자 도구로 .moc3를 만드는 SaaS를 Editor 없이 운영할 수 있는가?
- 약관 문면상: 4개 약관 모두 moc3/cmo3 형식, 제3자 생성기, AI 생성에 대한 명시 조항이 없다 [V]. 약관은 "소프트웨어를 받아 쓴 자(Customer)"를 구속한다. 우리 개발팀이 Editor/Core/SDK를 설치/동의하지 않고 공개 자료(CubismSpecs JSON, OpenL2D hexpat, 오픈 구현의 블랙박스 관찰)만으로 인코더를 만들면 6.4(역공학 금지) 계약 위반 구성이 약하다. 하지만:
  - 개발자가 한 번이라도 SDK/Editor에 동의했다면 그 사람은 계약에 구속되고 clean-room이 오염된다(Umamo의 기여자 요건이 정확히 이 문제를 겨냥). 팀 운영 규칙이 필요.
  - 계약 외 청구권(저작권/부정경쟁/상표/특허)은 별개다. Live2D가 특허를 보유한다는 정황은 있으나 특정 특허/청구항은 읽지 못했다 [U] (Justia/PatentGuru 접근 실패).
  - 일본법 준거 + 실제 집행 의지는 FreeLive 선례가 있다 [V].
  - "Live2D Editor 출력(Output File)을 경쟁 미들웨어와 쓰지 말라"(Editor 5.1.9, Core 6.8)는 Editor로 만든 파일에 적용된다. Editor 없이 만든 moc3가 "Output File"인지는 약관 정의상(1.8) 아니다. 다만 해석은 법무 확인 [U].
- 결론: 기술적으로 가능, 법적으로는 "계약 위반은 구성하기 어렵지만 분쟁 위험은 0이 아님" 수준. 변호사 검토 필요.

(b) 공개 웹사이트에서 사용자 업로드/생성 모델을 Cubism Core wasm으로 렌더링할 수 있는가?
- 가능하려면 Expandable Application 승인 + 별도 Publication License가 필요하다(1.5, 2.1, 2.2). 소규모 면제 없음, 매출 분배(소규모 건당 ¥300 또는 20%, 중/대 5%), "완전 무료는 원칙적 비승인", 광고 수익도 매출 포함, 로고/Showcase, 승인은 재량 [V].
- 추가 리스크: 6.8의 "assumed primary use가 2D Creators의 창작을 해칠 수 있음" 조항은 승인 거부/해지 사유로 원용될 수 있다 [U 해석].
- Core JS는 Redistributable Code로 재배포 가능하지만 수정 불가, 5.2 조건 이행 필요 [V-S]. CDN 직링크(https://cubism.live2d.com/sdk-web/cubismcore/live2dcubismcore.min.js)는 pixi-live2d-display README가 "the direct link is quite unreliable, don't use it in production!"이라고 경고 [V]. 자체 호스팅이 필요하며 그 경우 5.2 재배포 조건을 이행해야 한다.
- 대안: Core를 아예 쓰지 않는 오픈 재구현(Ayagami/Purism) 또는 자체 런타임. 이때 Publication License는 필요 없다는 것이 이들의 주장이지만(Purism: "No. Because Purism Core is a reimplementation ... without any Live2D code"; "Will Live2D Inc. come after me ...? We currently do not think so.") 이는 Live2D의 입장이 아니다 [V].

(c) 자동/AI 생성, AI 학습 관련 제한?
- 약관에 AI 조항 없음 [V]. FAQ는 AI 사용 자체를 금지하지 않되 "학습 데이터 침해 사용"과 "2D Creators 창작성을 해칠 수 있는 용도가 assumed primary use인 파생물(서비스 포함)"을 금지한다 [V]. img2live("일러스트 1장 -> 애니메이션 가능한 퍼핏")는 리거 작업을 대체하는 서비스로 해석될 여지가 있다 [U]. Live2D 자신의 연구 방침도 "완전 자동 모델링은 하지 않는다"이다 [V-S]. 특히 Cubism Core/Editor/SDK를 쓰는 순간 이 조항이 계약으로 우리에게 걸린다.
- See-through 학습 데이터: 논문은 ArtStation/Booth/DeviantArt 등 커뮤니티 플랫폼에서 큐레이션한 "9,102 fully annotated 2.5D Live2D models after augmentation"(train 7,404 / val 851 / test 847)라고 밝힌다 [V, 논문 3.1절; 증강 후 수치이므로 원본 모델 수는 이보다 적을 수 있음]. 별도로 abstract는 "supervision from commercial Live2D models"라고 쓴다 [V]. 샘플 모델 한정이 아니라 커뮤니티 판매/공개 모델이다. 데이터 권리 처리는 논문/README에 명시가 없다 [V: 명시 없음]. CubismPartExtr은 Cubism SDK 5-r.4.1 Native를 내려받아 샘플 파트를 추출하는 도구로 안내된다 [V]. 샘플 자료는 Open Software License 5.5로 내부 평가/숙달 용도 한정이므로 ML 학습이 허용되는지는 불명 [U].
- 모델 가중치 라이선스: LayerDiff 3D, Marigold는 openrail++(상업 사용 허용, 용도 제한 조항을 서비스 약관에 "enforceable provision"으로 포함해야 함: "If you distribute the weights ... or host them as a service, you must include those restrictions"), SAM 파싱은 Apache-2.0, 코드는 Apache-2.0, 논문은 CC BY-NC-SA 4.0 [V: HF 모델 카드/GitHub]. 우리 SaaS는 OpenRAIL 용도 제한을 이용약관에 전달해야 한다.
- 학습 데이터 출처 리스크는 우리가 통제할 수 없다. 법무가 가중치 사용 위험을 평가하거나, 권리 정리된 데이터로 파인튜닝/대체하는 옵션을 검토해야 한다.

(d) 제품명에 "Live2D"를 써도 되는가?
- 아니오. 5.3.1 + 브랜드 가이드라인. "Live2D"/"Cubism"은 호환성 서술(nominative)로만, 로고 금지, 제휴/보증 오인 방지 문구 필수. 제품명은 현재 가칭 img2live처럼 상표를 포함하지 않는 이름이 안전하다(도메인/해시태그/메타데이터도 동일) [V 근거, U 적용].

(e) Editor 자동화 / 공식 AI 지원?
- External Application Integration API: WebSocket(기본 포트 22033, JSON). 사용자가 설정 대화상자에서 "Allow" 해야 함. 공식 함수 목록은 파라미터 조회/설정, 문서/모델 UID, 편집 모드 조회, 물리 FPS, 로그 전송, 그리고 내보내기 알림(NotifyMocFileExported 등)뿐이며 ArtMesh/디포머/키폼/PSD 임포트 API는 없다 [V] https://docs.live2d.com/en/cubism-editor-manual/external-application-integration-api-list/ (현행 안정판 문서 기준. VTube Studio의 파라미터 동기화가 이 API를 쓴다는 점은 VTS wiki로 확인 [V-S]).
- Cubism Editor 5.4 alpha1(2026-07-14): "Added editing APIs to the external application integration." 편집 API: EditBegin/EditEnd, AddParameter/Group, EditParameter, AddParameterKey/DeleteParameterKey, AddPart, EditPart, EditArtMesh(부모, 클리핑, drawOrder, opacity, 색 등), EditGlue, AddWarpDeformer/AddRotationDeformer, Edit*Deformer, 객체 삭제/선택. "available only in modeling mode", 새 "Edit" 권한 필요, 편집 중 Editor에 진행 대화상자가 떠 사용자는 Editor를 조작할 수 없고 Cancel로 중단 가능 [V] https://cubism.live2d.com/editor-alpha/doc/manual/alpha1/en/external-api-intergration/index.html . PSD 임포트나 ArtMesh 신규 생성, 키폼 정점 설정 API는 목록에 없다 [V: 목록 확인]. 알파 기간은 2026-10-18까지(안내 페이지) [V].
- 서드파티 MCP(nana7chi/CubismExternalEditMCP, MIT, 31 stars)가 이 API를 래핑해 AI 에이전트가 Editor를 조작한다 [V README]. 하지만 Editor GUI 실행 + 사용자 승인 필요.
- 법적으로: Editor 5.1.7 No Service Bureau가 "서버에서 대신 Editor로 산출물을 만들어주는 서비스"를 막는다. 사용자 본인 PC의 본인 Editor를 우리 플러그인이 구동하는 형태(bring your own license)만 가능성이 있다 [U 해석].
- 공식 AI 보조 기능(전수 확인): 5.0 "Automatic Generation of Facial Movements", 자동 메쉬 정확도 개선, 블렌드셰이프 확장; 5.1 Auto Generation of Deformer(휴머노이드 전신), Auto Generation of Sway Motion, 3D 회전 표현 적용; 5.2(2025-02-04) Parameter Controller 등(AI 아님); 5.3(2026-01-20) 블렌드 모드/오프스크린/브러시; 5.4 alpha(2026-07-14) Parameter Controller SDK 지원, Model state set, 텍스처 아틀라스 자동 배치 개선, 외부 연동 편집 API [V-S/V]. "일러스트 -> Live2D 완전 자동" 기능은 2026-07-17까지의 영문/일문 뉴스 목록에 없음 [V: https://www.live2d.com/en/information/ , https://www.live2d.com/information/]. 로드맵 비공개 부분은 확인 불가 [U].

### 3.3 리스크 요약(질적)

| 경로 | 계약(EULA) | 상표 | 특허/저작권 | 정책(2D Creators) | 총평 |
|---|---|---|---|---|---|
| Core 렌더 + 공개 웹 | Expandable 승인/분배 필수, 재량 승인 | 이름/로고 규정 | 낮음 | 높음(해지/거부 사유 가능) | 승인 없이는 불가 |
| Editor를 서버에서 구동 | 5.1.7 위반 | - | - | - | 불가 |
| 자체 moc3 인코더 + Core 없이 배포 | 개발자 오염만 주의 | 이름 주의 | 불명(특허 미확인) | 중간(분쟁 가능성) | 법무 검토 후 옵트인 |
| 자체 포맷 + 자체 런타임 | 해당 없음 | Live2D 이름 미사용 | 불명 | 낮음 | 가장 안전 |
| PSD만 제공(사용자가 Editor로 마무리) | 해당 없음 | - | - | 낮음 | 안전, 가치 낮음 |

---

## 4. 대안/오픈 포맷, 런타임, 관련 프로젝트 (2026-10-02 확인)

| 이름 | 하는 일 | 출력 | 라이선스 | 성숙도/상태 | 재사용 포인트 |
|---|---|---|---|---|---|
| Inochi2D (코어 SDK) | 2D 퍼핏 포맷/SDK(INP, 메쉬 변형, 파라미터, 물리) | .inp/.inx | BSD-2-Clause | 푸시 2026-09-15; inochi-creator 마지막 2025-06, inochi-session 2025-11(정체) | 포맷 공개(INP: 매직 `TRNSRTS\0`, JSON + 텍스처 PNG/TGA/BC7, 빅엔디안; "subject to change before 1.0") [V-S] |
| nijilive / nijigenerate / nijiexpose | Inochi2D v0.8 포크(편집기, 라이브러리, VTuber 뷰어) | nijilive .inp | BSD-2 | nijigenerate 푸시 2026-10-01, 1.0.0-beta2(2026-06-04); "No official stable build" | PSD/KRA 임포트, 메쉬/바인딩 편집. 자동 리깅은 확인 못 함 [V/U] |
| Inox2D | Inochi2D의 Rust 재구현(OpenGL, WASM/WebGL) | - | BSD-2 | "prototype state, not recommended for production", mesh group/animation 미지원 | 웹 렌더러 후보(미성숙) [V] |
| Ayagami | Live2D 호환 렌더러(Rust/wgpu, WebGL/WebGPU) | - | MIT/Apache-2.0 | 342 stars, 웹 데모, API 불안정, 모션/표정/포즈 미구현 | 브라우저 moc3 미리보기 + 검증 오라클 [V] |
| Purism Core | Cubism Core 재구현(C99, WASM) | - | MIT | v1.0 시리즈, 1.1.0 준비 | Cubism Framework 연동 가능(ABI 호환) [V] |
| Spine | 상용 2D 스켈레탈 | Spine JSON/바이너리 | Spine Runtimes License: "each user of the Products must obtain their own Spine Editor license" | 성숙 | 라이선스 문구상 "Products 사용자마다 Editor 라이선스"를 요구하므로 SaaS에서 사용자가 쓰는 구조에는 부적합해 보임(해석은 [U], 원문 인용은 [V]) |
| DragonBones | 2D 스켈레탈 | JSON | MIT(JS 런타임) | 푸시 2026-01-23, 에디터 상태 U | 메쉬 변형 한계 U |
| Rive | 상호작용 벡터 애니 | .riv | 런타임 MIT | 매우 활발(2026-10-02) | Live2D식 파라미터-키폼 리그와 모델이 다름 U |
| pixi-live2d-display | Cubism Core 위의 PixiJS 플러그인 | - | MIT | 마지막 푸시 2024-08, Cubism 2/3/4 표기 | Core 필요(라이선스 이슈 동일), 5.x 최신 기능 미보장 [V] |
| oh-my-live2d(현 hacxy/l2d-widget)/live2d-widget(stevenjoezhang) | 웹 위젯 | - | MIT / GPL-3.0 | 활발(2026-08~10 푸시, 639/10,973 stars) | Core 의존으로 추정 [U] |
| StretchyStudio | 브라우저 2D 퍼핏 자동 리거(See-through PSD 최적화) | Spine 4.0 JSON, Live2D .moc3(V4.00)+.cmo3+.can3 | MIT | 494 stars, 마지막 푸시 2026-04-28, 자체 문서 "auto-rig on girl.psd good, waifu.psd bad" | 아이디어(측정->결정->보고), 단 코드/문서는 디컴파일 의존 [V] |
| Anime2.5DRig | 브라우저에서 PSD 드롭 -> 자동 리그(메쉬 분할/변형/물리), MediaPipe 얼굴 추적, OBS 연동, WebM 출력 | 브라우저 재생 + 투명 WebM/MP4 + 설정 JSON | MIT | 233 stars, 2026-09-23 | 표준 모델 파일 출력은 없음 [V README] |
| PachiPakuGen | See-through + RIFE로 눈 깜빡임/립싱크 소재 생성 | 스프라이트(SpriTalk용) | MIT | 130 stars | 리그가 아님 [V] |
| PNGAL | 레이어 이동/흔들림 + 영상/스프라이트 | PSD/WebM/MP4/GIF | 선언 없음(NOASSERTION) | 353 stars | 리그 없음 [V] |
| ComfyUI-See-through | See-through ComfyUI 래퍼 | 레이어 PSD | 선언 없음 | 814 stars | 파이프라인 단계 [V] |
| image2live2d(Wzhang3912) | See-through -> 메쉬/리그/물리 -> .inp/.moc3/.cmo3 | 3종 | Apache-2.0 | 38 stars | IRR(중간 리그 표현) 아키텍처 참고 [V] |
| lvhaojie456/image-to-live2d | 프롬프트/이미지 -> See-through + psd2live + 시각 검수/수리 감독 루프 | moc3+cmo3+PSD | MIT | 2 stars | 파이프라인 오케스트레이션 참고. 제작 호스트가 Editor의 Core JNI를 쓰므로 SaaS로는 부적합 [V] |
| Talking Head Anime 3/4 (pkhungurn) | 단일 이미지 신경망 애니(퍼핏 아님) | 영상/실시간 | 코드 MIT, 모델 CC BY 4.0 | 2023~2024 이후 정체 | 신경 기반 대안(GPU 필요, 리그 없음) [V] |
| Facebook Animated Drawings | 어린이 그림 스켈레톤 애니 | GIF/영상 | MIT | 2025-09 아카이브 | Live2D식 얼굴 리그와 목적 상이 [V] |
| CartoonAlive (arXiv 2507.17327), Textoon (arXiv 2501.10020) | 단일 초상/텍스트 -> Live2D, 30초/1분 | (논문에 형식 상세는 확인 못 함) | 코드 공개 미확인 | 논문 | 선행연구. 상세 U [V-S] |
| OneClick2D(sweetcornna) | 정책상 moc3 생성/파싱/역공학/호환성 약속을 아예 하지 않기로 한 프로젝트(.oc2d + PSD) | 자체 포맷 | 선언 없음 | 프로젝트 단계 | "법적 경계를 먼저 그은" 사례 [V] |

### 변환기(INP <-> MOC3, PSD -> moc3)
- INP <-> MOC3 직접 변환기는 찾지 못함. 대신 IRR(중간 표현)에서 양쪽으로 내보내는 방식(image2live2d의 nijilive/Live2D 이미터)이 존재 [V].
- PSD -> moc3: psd2live(GPL-3.0), image2live2d(Apache-2.0), Stretchy(MIT), live2d-agent-kit(코덱스 에이전트용 스킬 + psd2live 어댑터) [V].
- moc3 -> cmo3(역변환): live2d2psd(alksdesu, 라이선스 선언 없음, "personal research purposes only"), D2Evil Lincubator(소스 비공개) [V]. 이는 타인 모델 복원 용도로 악용되는 영역이라 우리에게 필요 없고 법적으로도 피할 것.

---

## 5. 호환 생태계와 표준 파라미터

### 5.1 어느 앱이 무엇을 읽는가
| 앱 | 로드 포맷 | 근거 |
|---|---|---|
| VTube Studio | Live2D(.moc3 + model3.json 등)만. "VTube Studio ONLY supports Live2D Models. ... VRoid/VRM ... NOT supported." | [V-S] https://github.com/DenchiSoft/VTubeStudio/wiki/Models |
| Warudo, VNyan, VSeeFace | VRM(0.x/1.0), .warudo, VSFAvatar 등 3D | [V-S] 검색 결과 요약, 직접 문서 미확인 |
| Cubism Viewer, Unity/Unreal/Native/Web SDK 앱, Ren'Py, Godot gd_cubism | moc3 | [V] Purism README/COMPAT.md가 VTube Studio, Ren'Py, gd_cubism을 Cubism Core 사용 소프트웨어로 나열(Core 사용 방식 세부는 [U]) |
| Inochi Session, nijiexpose | .inp | [U: 이름만 확인] |
| Vtuber Maker 등 기타 | - | 확인 못 함 [U] |

- VTube Studio는 Core v5 ABI(Cubism 5.1 SDK 기준)를 쓰는 대표 사례로 문서화돼 있다: "In general, the v5 ABI has the widest support among third party applications ... Examples of software using the v5 ABI includes: VTube Studio ..." 5.3 신기능 moc3(버전 6)는 구버전 호스트에서 "likely result in bugs or glitches" [V Purism COMPAT.md]. 따라서 우리는 낮은 moc3 버전(<=5)을 방출하고 5.3 전용 기능(오프스크린, 확장 블렌드)을 쓰지 않는 것이 맞다.
- VTS 호환 파일 세트: model3.json + .moc3 + physics3.json(+ 텍스처) [V-S 검색 결과].

### 5.2 VTube Studio 입력 파라미터와 자동 설정
VTS 입력(웹캠/iOS/Android/MediaPipe 지원 표 기준): FaceAngleX/Y/Z, MouthSmile, MouthOpen, Brows, EyeOpenLeft/Right, EyeLeftX/Y, EyeRightX/Y, BrowLeftY/RightY, CheekPuff(iOS 전용), VoiceVolumePlusMouthOpen 등 [V https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings]. 자동 설정(auto-setup)은 "standard Live2D parameter names and values"를 전제하므로 파라미터 ID나 범위를 바꾸면 자동 설정이 실패한다 [V]. VTS는 MediaPipe 웹캠 트래커도 지원한다(표의 열) [V].

MediaPipe Face Landmarker(웹 JS 지원)는 478개 3D 랜드마크, 52개 블렌드셰이프 점수, 얼굴 변환 행렬을 출력한다(옵션 output_face_blendshapes, output_facial_transformation_matrixes) [V-S https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker]. ARKit 호환 이름은 해당 페이지에서 직접 확인하지 못함 [U]. Kalidokit(MIT, 5.7k stars, 푸시 2025-08)이 MediaPipe/TF.js 얼굴 결과를 Live2D류 값으로 변환하는 선행 구현이다 [V].

제안 매핑(우리 설계, [U]):
- 머리 회전 행렬 -> ParamAngleX/Y/Z, eyeBlinkLeft/Right -> ParamEyeLOpen/ROpen(1-값), jawOpen -> ParamMouthOpenY, mouthSmile - mouthFrown -> ParamMouthForm, browInnerUp/browDown -> ParamBrowLY/RY, eyeLook* -> ParamEyeBallX/Y, 몸 각도는 머리각 x 감쇠, ParamBreath/머리카락은 자동/물리.

### 5.3 Cubism 표준 파라미터 목록 (공식, 2021-08-26 갱신) [V]
출처: https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/ (눈과 입은 닫힘 0, 열림 1이 원칙. *는 필요 시)

| 이름 | ID | 최소 | 기본 | 최대 | 설명 |
|---|---|---|---|---|---|
| Angle X | ParamAngleX | -30 | 0 | 30 | +: 화면 오른쪽을 향함 |
| Angle Y | ParamAngleY | -30 | 0 | 30 | +: 위를 향함 |
| Angle Z | ParamAngleZ | -30 | 0 | 30 | +: 화면 오른쪽으로 기울임 |
| Left eye Open/Close | ParamEyeLOpen | 0 | 1 | 1 | +: 눈을 뜸(더 크게 뜨려면 최대 1.5~2 등) |
| Left eye Smiling | ParamEyeLSmile | 0 | 0 | 1 | +: 웃는 눈 |
| Right eye Open/Close | ParamEyeROpen | 0 | 1 | 1 | 위와 동일 |
| Right eye Smiling | ParamEyeRSmile | 0 | 0 | 1 | |
| Eyeball X | ParamEyeBallX | -1 | 0 | 1 | +: 오른쪽 응시 |
| Eyeball Y | ParamEyeBallY | -1 | 0 | 1 | +: 위 응시 |
| Eyeball scaling* | ParamEyeBallForm | -1 | 0 | 1 | -1 작게, 1 크게 |
| Left eyebrow Up/Down | ParamBrowLY | -1 | 0 | 1 | +: 눈썹 올림 |
| Right eyebrow Up/Down | ParamBrowRY | -1 | 0 | 1 | |
| Left eyebrow Left/Right | ParamBrowLX | -1 | 0 | 1 | -: 눈썹을 모음 |
| Right eyebrow Left/Right | ParamBrowRX | -1 | 0 | 1 | |
| Left eyebrow Angle | ParamBrowLAngle | -1 | 0 | 1 | -: 화남 |
| Right eyebrow Angle | ParamBrowRAngle | -1 | 0 | 1 | |
| Left eyebrow Deformation | ParamBrowLForm | -1 | 0 | 1 | -: 화남 |
| Right eyebrow Deformation | ParamBrowRForm | -1 | 0 | 1 | |
| Mouth Deformation | ParamMouthForm | -1 | 0 | 1 | +: 웃는 입, -: 화난 입 |
| Mouth Open/Close | ParamMouthOpenY | 0 | 0 | 1 | +: 입 벌림(최대 1.5 등 가능) |
| Cheek | ParamCheek | 0 | (캐릭터별) | 1 | +: 홍조 |
| Body rotation X | ParamBodyAngleX | -10 | 0 | 10 | +: 오른쪽 |
| Body rotation Y | ParamBodyAngleY | -10 | 0 | 10 | +: 위 |
| Body rotation Z | ParamBodyAngleZ | -10 | 0 | 10 | +: 오른쪽 기울임 |
| Breath | ParamBreath | 0 | 0 | 1 | +: 숨 들이쉼 |
| Left arm A* / Right arm A* | ParamArmLA / ParamArmRA | -30 | 0 | 30 | + 팔 벌림 |
| Left arm B* / Right arm B* | ParamArmLB / ParamArmRB | -30 | 0 | 30 | |
| Left hand* / Right hand* | ParamHandL / ParamHandR | -10 | 0 | 10 | 손 변형 |
| Hair sway Front | ParamHairFront | -1 | 0 | 1 | 보통 물리가 구동 |
| Hair sway Sideways | ParamHairSide | -1 | 0 | 1 | |
| Hair sway Back | ParamHairBack | -1 | 0 | 1 | |
| Hair sway Fluffy* | ParamHairFluffy | -1 | 0 | 1 | |
| Shrug* | ParamShoulderY | -10 | 0 | 10 | |
| Breast physics* | ParamBustX, ParamBustY | -1 | 0 | 1 | |
| Overall Left/right* | ParamBaseX | -10 | 0 | 10 | 전체 이동 |
| Overall Up/down* | ParamBaseY | -10 | 0 | 10 | |

표준 파라미터 그룹 ID(공식): ParamGroupFace, ParamGroupHead, ParamGroupEyes, ParamGroupEyeballs, ParamGroupBrows, ParamGroupMouth, ParamGroupBody, ParamGroupHands, ParamGroupHandL, ParamGroupHandR, ParamGroupArms, ParamGroupArmL, ParamGroupArmR, ParamGroupLegs, ParamGroupLegL, ParamGroupLegR, ParamGroupSway, ParamGroupExpression, ParamGroupHair, ParamGroupOverall [V].

표준 Part ID: 공식 "표준 파트 목록"은 찾지 못했다 [U: 없는 것으로 보임]. Core/SDK는 파트를 ID 문자열로만 식별하고 pose3.json(예: `Part01ArmLB001`)과 motion3 `PartOpacity` 트랙에서 참조된다 [V CubismSpecs]. 따라서 파트 ID는 자유롭게 정하되 pose3/모션에서 참조하는 ID만 일치시키면 된다. (파라미터 ID 길이는 hexpat상 64바이트 고정 배열 [V].)

우리 1차 리그의 최소 호환 세트(제안, [U]): ParamAngleX/Y/Z, ParamEyeLOpen/ROpen, ParamEyeBallX/Y, ParamBrowLY/RY(+Angle/Form 선택), ParamMouthForm, ParamMouthOpenY, ParamBodyAngleX/Y/Z, ParamBreath, ParamHairFront/Side/Back, (선택) ParamCheek, ParamEyeLSmile/RSmile, ParamArmLA/RA, ParamBaseX/Y. model3.json Groups에 EyeBlink=[ParamEyeLOpen, ParamEyeROpen], LipSync=[ParamMouthOpenY] 지정.

---

## 6. 권고안 (A / B / C)

### 6.1 옵션 정의와 평가

공통 가정: 시니어 엔지니어 2~3명(그래픽스/TS, ML, 리깅 지식 보유). 공수는 내 추정치이며 [U], 앵커는 공개 프로젝트의 속도다(Umamo는 2026-07-13 시작해 약 2.5개월 만에 CMO3/MOC3 읽기/쓰기, psd2live는 2026-09-03 시작해 1개월 만에 v2.0, Stretchy는 30개 세션 동안 역공학/수정 반복). 이들은 AI 코딩 에이전트 사용 비중이 높고 품질은 초기 단계라 "사람 주(person-week)"로 환산하면 오차가 크다.

| 옵션 | 구성 | 공수(pw) | 법적 리스크 | 기술 리스크 | 비고 |
|---|---|---|---|---|---|
| A1 | 자체 moc3 인코더 + Cubism Web SDK/Core로 브라우저 렌더 | 24~36 | 매우 높음: Expandable 승인/분배, "완전 무료 비승인", 2D Creators 조항 | 높음: Core 일관성 검사, 버전 호환 | 출시 전 Live2D 계약이 선행 조건 |
| A2 | 자체 moc3 인코더 + Ayagami/Purism(자체 WASM)로 렌더 | 26~38 | 높음: 계약은 회피하나 분쟁/특허/정책 리스크, 공식 입장 없음 | 높음: 인코더 정확도, 렌더 일치 | A1보다 현실적, 단 오라클/법무 필요 |
| A3 | Cubism Editor를 구동(5.4 External API) | 불가(SaaS) / 사용자 로컬 플러그인이면 6~10 | 서버: 5.1.7 위반. 로컬: 낮음~중간 | API는 alpha, ArtMesh 생성/PSD 임포트 불가 | 타깃 사용자(일반인)와 안 맞음 |
| A4 | PSD(+옵션 cmo3)를 사용자가 Editor에서 마무리 | 3~6(PSD 정리, 네이밍) / cmo3 +6~10 | 낮음(PSD) / 중간(cmo3 역공학) | 낮음 | 사용자에게 Editor 라이선스 부담 |
| B | 자체 포맷(IRR) + 자체 WebGL2/WebGPU 런타임 + 자동 리깅 | 20~32 | 낮음~중간(Live2D 이름/로고 미사용, Core 미사용) | 중간: 자동 리깅 품질이 핵심 | VTube Studio 비호환 |
| C | B + (PSD, .inp, 투명 영상 내보내기) + 법무 게이트 뒤 실험적 moc3 내보내기 | 단계별 합 32~47 | 단계별 노출 증가, 게이트로 통제 | 중간 | 권고 |

pw 분해(B 기준, [U]): 포맷/IRR 설계 2~3, 런타임(메쉬/워프/회전 디포머 체인, 키폼 다차원 보간, 마스크, 드로우 오더, 진자 물리, 모션, MediaPipe 입력) 5~8, 자동 리깅(메쉬 생성, 디포머 위계, 눈/입/머리 키폼 생성, 물리 파라미터 튜닝, 입 안쪽/감은 눈 보강, 실패 감지와 QA) 12~20, 웹 서비스/업로드/뷰어 UI 3~5(위 범위에는 일부 포함). moc3 인코더는 경로 추가 시 4~6(인코더) + 2~3(검증기, 버전 하향 정책) + 1~2(사이드카 JSON) + 2~3(VTube Studio 실기 QA) = 9~14.

### 6.2 단계별 권고 (C안)

0단계(2~3주, 병행): 법무/Live2D 문의(7장), clean-room 규칙 확정, 모델 가중치 라이선스 점검.
- clean-room: moc3/cmo3 인코더 작업자는 Cubism SDK/Editor/Core를 설치하거나 약관에 동의하지 않는다. Stretchy/py-moc3/moc3-reader-re 계열 코드와 문서는 참조하지 않는다. 사용 가능한 근거: OpenL2D hexpat(FDPL), CubismSpecs, Ayagami/Purism/moc3-rs(오픈 구현)를 블랙박스 오라클로 한 자체 실험.
- Umamo/psd2live는 GPL-3.0이다. 서버에서 내부적으로 CLI로 호출하는 것과 브라우저/데스크톱 앱에 포함해 사용자에게 전달하는 것은 법적 취급이 다르다(후자는 소스 공개 의무) [U 일반 지식, 법무 확인].

1단계(MVP, 약 8~12주): 자체 IRR + 웹 런타임
- IRR: JSON(메타/위계/파라미터/키폼) + 아틀라스 PNG. 구조는 Cubism과 동형(ArtMesh/Warp/Rotation/Parameter/Keyform/Mask/DrawOrder/Physics)으로 해 두면 이후 moc3 로워링이 기계적이다(image2live2d와 Umamo의 "Puppet model -> MocLowering" 구조 참고) [V 구조].
- 파라미터 ID는 Cubism 표준 목록 그대로 사용(법적 문제 없음, 호환성/추적 이점). physics3.json 구조도 그대로 채택.
- 렌더링: 자체 TS 런타임. 정확도 교차검증은 Ayagami/Purism으로(같은 모델 포맷 입력이 필요한 단계는 3단계).
- 입력: MediaPipe Face Landmarker + 마우스 추적.

2단계(+3~5주): 내보내기 다양화
- 레이어 PSD(See-through 원본), nijilive/Inochi2D .inp(BSD-2, 단 v0.8 포크/0.9 분기 주의), 투명 WebM/GIF, 우리 포맷.
- "Cubism-ready PSD" 옵션: Editor 임포트 규칙(그룹 최하단만 텍스처, 병합 선행, 이름 규칙)에 맞춘 PSD. 사용자가 자기 Editor에서 모델 템플릿/자동 디포머로 이어 가는 공식 경로. 법적 부담 없음.

3단계(법무 게이트 통과 시, +9~14주): 실험적 moc3 내보내기
- "Unofficial / experimental, not endorsed by Live2D" 표기, 기본 꺼짐, VTube Studio용 파일 세트(moc3 + model3 + physics3 + cdi3 + motion3 + 텍스처).
- 낮은 moc3 버전(우선 3.00~4.00 수준)과 5.3 기능 미사용, 모든 오프셋/카운트 일관성 검증 자동화(자체 검증기 + Ayagami/Purism 로드 + 개인이 개별 확인하는 공식 Consistency Checker는 법무가 허용할 때만).
- 이 단계에서만 Live2D 이름을 설명용으로 사용하고 로고는 쓰지 않는다.

중단/전환 기준(게이트):
- G0: 법무가 "Live2D 호환 파일 생성 + 서비스 제공"의 계약/특허/정책 리스크를 허용 수준으로 판단.
- G1: Live2D가 2D Creators 조항에 대해 "유사 서비스 사전 문의"에 서면 입장을 줌(또는 침묵).
- G2: 실기 QA(VTube Studio 등)에서 인코더가 5개 이상 서로 다른 캐릭터로 오류 없이 로드.
- 어느 게이트도 통과 못 하면 C는 B+2단계에서 멈춘다.

### 6.3 이 권고의 근거 요약
- 기술이 어려워서가 아니라 "법적으로 가장 불확실한 두 조각(Core 렌더, moc3 배포)을 가장 늦게, 옵트인으로" 미루려는 순서다.
- 자동 리깅 품질이 제품 가치의 대부분이고(모든 선행 프로젝트가 초안 수준) 이는 어떤 옵션에서도 필요한 공통 비용이다. 따라서 포맷 선택 때문에 이 투자가 낭비되지 않도록 IRR을 먼저 만든다.
- VTube Studio 호환이 제품의 핵심 가치라면(VTuber 타깃) C의 3단계가 사업적으로 중요하다. 이 경우 Live2D와 사전 협의하는 비용이 크지 않다(Expandable 경로를 쓰지 않아도, 최소한 입장을 확인).

---

## 7. 변호사/Live2D 문의가 필요한 항목

일본 IP 변호사(준거법 일본법, 일본어 원문 EULA) 및 Live2D Inc. SDK 라이선스 팀(Expandable Application 문의 폼 https://www.live2d.jp/eng/application-publication-license/form/ [V 검색 결과])에 확인할 것:

1. Editor/Core를 한 번도 설치하지 않은 팀이 공개 자료로 만든 moc3 인코더와 그 출력 파일 배포가 EULA, 저작권, 부정경쟁방지법, 특허에 비추어 문제 없는가. Live2D가 보유한 특허(범위 미확인)가 파라미터-키폼 보간/디포머 변형 방식을 포괄하는가.
2. Core 없이 오픈 재구현(Ayagami/Purism 등)으로 사용자 모델을 렌더하는 웹 서비스는 Publication License/Expandable 승인 대상인가(Live2D의 서면 입장).
3. Core를 쓰는 경우, 무료 베타를 Expandable로 승인받을 수 있는 "separately specified conditions"가 무엇인가. 광고/구독 수익 처리.
4. "assumed primary use로 2D Creators의 창작성을 해칠 수 있는 서비스" 조항의 해석: 일러스트 1장 -> 자동 퍼핏 서비스가 해당하는가. 해당하지 않는 설계 조건(예: 리거용 보조 도구, 초안 + Editor 이어서 편집)이 있는가.
5. 제품명, 마케팅에서 "Live2D 호환"을 어디까지 쓸 수 있는가.
6. See-through 가중치 사용 위험: 학습 데이터(ArtStation/Booth/DeviantArt 판매 모델 9,102개)의 권리 처리, OpenRAIL++ 용도 제한 전달 의무. 대체/파인튜닝 옵션.
7. Editor를 사용자의 로컬 PC에서 우리 플러그인이 구동하는 구성(bring-your-own-license)의 5.1.7/5.1.9 저촉 여부.
8. GPL-3.0 구성요소(Umamo, psd2live)를 서버 내부 CLI로 호출하는 구성의 의무 범위.

---

## 8. 검증하지 못했거나 불확실한 것 (명시)

- 일본어 원문 EULA는 읽지 않았다(영문은 번역본). 해석은 일본어 기준.
- Live2D Inc.의 특허 목록과 청구항: Justia/PatentGuru 접근 실패(403/468). 존재 여부와 범위 모두 미확인.
- Umamo, psd2live, image2live2d의 moc3가 VTube Studio/Core에서 일반적으로 로드되는지 독립 검증은 하지 못했다. 각 README의 주장만 확인했다. 직접 생성/로드 실험을 하지 않았다.
- Ayagami/Purism이 Live2D로부터 법적 이의를 받았는지 여부: 찾지 못함(부재 증명 아님).
- Warudo/VNyan/Vtuber Maker의 Live2D 지원 여부: 검색 요약만 확인(Warudo/VNyan은 VRM 계열). Vtuber Maker는 미확인. Animaze, nizima LIVE, VUP, PrprLive 등은 이번에 조사하지 않았다.
- 표준 Part ID 목록: 공식 문서에서 찾지 못함(없는 것으로 추정).
- Cubism Editor 5.4 alpha 편집 API의 상세 스펙 전체와 GitHub 샘플(Live2D-Garage/CubismExternalAppPluginSamples, 54alpha 브랜치)은 읽지 않았다. 목록은 개발자 매뉴얼 목차와 MCP 래퍼 문서로 확인.
- 키폼 보간식, 좌표계 세부(워프 격자의 로컬 좌표, 회전 디포머 합성 순서)는 공개 1차 문서가 없어 구현 단계에서 오픈 구현/실험으로 확정해야 한다.
- CartoonAlive/Textoon의 출력 형식과 코드 공개 여부, 저자 소속: 확인하지 못함.
- DragonBones 에디터, Rive 포맷 공개 수준, Inochi2D 자동 리깅 기능 유무는 깊이 확인하지 못함.
- 공수(person-week)는 모두 내 추정이다.
- Live2D의 비공개 로드맵(이미지 -> Live2D 자동화)은 알 수 없다. 공개 뉴스(영문/일문, 2026-07-17까지)에는 없다.

---

## 9. Sources

### Live2D 공식(약관, 문서, 뉴스)
- Core: https://www.live2d.com/eula/live2d-proprietary-software-license-agreement_en.html [V]
- Open Software License: https://www.live2d.com/eula/live2d-open-software-license-agreement_en.html [V]
- Editor EULA: https://www.live2d.com/eula/live2D-editor-software-license-agreement_en.html [V]
- Free Material License: https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/ [V]
- SDK Release License: https://www.live2d.com/en/sdk/license/ [V]
- Expandable Applications: https://www.live2d.com/en/sdk/license/expandable/ [V]
- Running Royalty Plan: https://www.live2d.com/en/sdk/license/running_plan01/ [V]
- 사업 규모 FAQ: https://help.live2d.com/en/sdk/sdk_007/ , https://help.live2d.com/en/sdk/sdk_001/ (검색 결과만 [U])
- AI FAQ: https://help.live2d.com/en/other/other_33/ [V]
- AI Research Policy (nizima): https://docs.nizima.com/en/ai-research-policy/ [V-S]
- 브랜드 가이드: https://www.live2d.jp/brand [V-S]
- CubismSpecs(JSON 스펙): https://github.com/Live2D/CubismSpecs/tree/master/FileFormats [V]
- CubismWebFramework LICENSE: https://github.com/Live2D/CubismWebFramework/blob/develop/LICENSE.md [V], 릴리스 5-r.5 2026-04-02 [V]
- 표준 파라미터: https://docs.live2d.com/en/cubism-editor-manual/standard-parameter-list/ [V]
- 파일 형식: https://docs.live2d.com/en/cubism-editor-manual/file-type-and-extension/ [V-S]
- 용어집: https://docs.live2d.com/en/cubism-editor-manual/glossary/ [V-S]
- 디포머: https://docs.live2d.com/en/cubism-editor-manual/deformer/ [V-S]
- 블렌드 셰이프: https://docs.live2d.com/en/cubism-editor-manual/blend-shape/ [V-S]
- 물리: https://docs.live2d.com/en/cubism-editor-manual/physical-operation-setting/ [V-S]
- PSD 임포트: https://docs.live2d.com/en/cubism-editor-manual/psd-import/ [V-S]
- 모델 템플릿: https://docs.live2d.com/en/cubism-editor-manual/template/ [V-S]
- 5.0/5.1/5.2/5.3 신기능: https://docs.live2d.com/en/cubism-editor-manual/new-function5-0/ , new-function5-1/ , new-function5-2/ , new-function5-3/ [V-S]
- 5.3 SDK 호환(moc3 v6): https://docs.live2d.com/en/cubism-sdk-manual/compatibility-with-cubism-5-3/ [V]
- moc3 내보내기(버전 선택): https://docs.live2d.com/en/cubism-editor-manual/export-moc3-motion3-files/ [V-S]
- Core 취약점 대응: https://docs.live2d.com/en/cubism-editor-manual/addressing-vulnerabilities/ [V-S]
- MOC3 Consistency Checker: https://docs.live2d.com/en/cubism-editor-manual/moc3-consistency-checker/ [V-S]
- FREE/PRO 비교: https://www.live2d.com/en/cubism/comparison/ [V-S]
- External API(안정판): https://docs.live2d.com/en/cubism-editor-manual/external-application-integration-api/ , .../external-application-integration-api-list/ [V/V-S]
- 5.4 alpha 안내: https://www.live2d.com/en/information/cubism-5_4-alpha/ [V]
- 5.4 alpha1 매뉴얼: https://cubism.live2d.com/editor-alpha/doc/manual/alpha1/en/index.html [V]
- 5.4 alpha1 외부 연동 개발자 매뉴얼: https://cubism.live2d.com/editor-alpha/doc/manual/alpha1/en/external-api-intergration/index.html [V]
- 뉴스 목록: https://www.live2d.com/en/information/ , https://www.live2d.com/information/ [V]

### 집행 선례/법적 의견
- FreeLive EULA 위반 통지: https://github.com/UlyssesWu/D2Evil/issues/1 [V]
- D2Evil README(Lincubator 등): https://github.com/UlyssesWu/D2Evil [V]
- Live2D MOC3 Reverse Engineering FAQ(hoshinolina): https://gist.github.com/hoshinolina/50154059c87d4c424827bdbf50fcbff7 [V-S]
- Live2D: A Security Trainwreck(MOC3ingbird 배경): https://undeleted.ronsor.com/live2d-a-security-trainwreck/ (검색 결과만 [U])

### moc3/cmo3 구현
- OpenL2D moc3ingbird(+moc3.hexpat): https://github.com/OpenL2D/moc3ingbird [V]
- Umamo: https://github.com/umamoorg/umamo [V]
- psd2live: https://github.com/tsunehimatoi/psd2live [V]
- image2live2d: https://github.com/Wzhang3912/image2live2d [V]
- image-to-live2d: https://github.com/lvhaojie456/image-to-live2d [V]
- py-moc3: https://github.com/Ludentes/py-moc3 [V]
- moc3-reader-re: https://github.com/QiE2035/moc3-reader-re [V]
- vtubing/moc3: https://github.com/vtubing/moc3 [V]
- moc3-rs: https://github.com/MahouTechnologies/moc3-rs [V]
- Ayagami: https://github.com/AyagamiDev/ayagami [V]
- PurismCore: https://github.com/SakuraMotion/PurismCore [V]
- Ayatsuri2D: https://github.com/Yoru-KenomoVT/ayatsuri_2d [V]
- Stretchy Studio: https://github.com/MangoLion/stretchystudio (docs/live2d-export/*) [V]
- live2d2psd(alksdesu/live2d-tools): https://github.com/alksdesu/live2d-tools [V]
- live2d-agent-kit: https://github.com/Ariakage/live2d-agent-kit [V]
- live2d-from-art: https://github.com/fifteen42/live2d-from-art [V]
- OneClick2D: https://github.com/sweetcornna/OneClick2D [V]
- Cubism External Edit MCP: https://github.com/nana7chi/CubismExternalEditMCP [V]

### See-through 및 관련
- 논문: https://arxiv.org/abs/2602.03749 [V]
- 저장소: https://github.com/shitagaki-lab/see-through [V]
- CubismPartExtr: https://github.com/shitagaki-lab/CubismPartExtr [V]
- HF LayerDiff 3D: https://huggingface.co/layerdifforg/seethroughv0.0.2_layerdiff3d (openrail++) [V]
- HF Marigold: https://huggingface.co/layerdifforg/seethroughv0.0.1_marigold (openrail++) [V]
- HF SAM body parsing: https://huggingface.co/24yearsold/l2d_sam_iter2 (Apache-2.0) [V]
- ComfyUI-See-through: https://github.com/jtydhr88/ComfyUI-See-through [V]
- Anime2.5DRig: https://github.com/852wa/Anime2.5DRig [V]
- PachiPakuGen: https://github.com/kazuya-bros/PachiPakuGen [V]
- PNGAL: https://github.com/1mm-module/PNGAL [V]
- CartoonAlive: https://arxiv.org/abs/2507.17327 [V-S]
- Textoon: https://arxiv.org/abs/2501.10020 [V-S]

### 대안 런타임/포맷
- Inochi2D: https://github.com/Inochi2D/inochi2d , inochi-creator, inochi-session, inox2d(https://github.com/Inochi2D/inox2d) [V]
- INP 스펙: https://docs.inochi2d.com/en/latest/spec/inp/index.html [V-S]
- nijigenerate/nijilive: https://github.com/nijigenerate/nijigenerate , https://github.com/nijigenerate/nijilive [V]
- Spine Runtimes License: https://esotericsoftware.com/spine-runtimes-license [V]
- Rive: https://github.com/rive-app/rive-runtime , https://github.com/rive-app/rive-wasm [V: 저장소 메타]
- DragonBonesJS: https://github.com/DragonBones/DragonBonesJS [V: 저장소 메타]
- pixi-live2d-display: https://github.com/guansss/pixi-live2d-display [V]
- Talking Head Anime 3/4: https://github.com/pkhungurn/talking-head-anime-3-demo , .../talking-head-anime-4-demo [V]
- Animated Drawings: https://github.com/facebookresearch/AnimatedDrawings [V: 저장소 메타]
- Kalidokit: https://github.com/yeemachine/kalidokit [V: 저장소 메타]

### 호환 생태계/트래킹
- VTube Studio wiki(Models): https://github.com/DenchiSoft/VTubeStudio/wiki/Models [V-S]
- VTube Studio Model Settings: https://github.com/DenchiSoft/VTubeStudio/wiki/VTS-Model-Settings [V]
- VTube Studio-Cubism Editor 통신: https://github.com/DenchiSoft/VTubeStudio/wiki/Live2D-Cubism-Editor-Communication [V-S]
- MediaPipe Face Landmarker: https://developers.google.com/edge/mediapipe/solutions/vision/face_landmarker [V-S]
