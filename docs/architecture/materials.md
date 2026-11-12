# 재료 5종과 PBR 슬롯 (B-07)

- 상태: 구현됨. 데이터는 `packages/core/src/kinetra_core/material_catalog.json`, 모델은 `material_catalog.py`(로더 `load_material_catalog()`), `pbr.py`(PBR 슬롯). 테스트는 `packages/core/tests/test_materials.py`(`uv run pytest packages/core -q -k materials`).
- 근거: 이슈 #120, `docs/architecture/project-model.md`(`Material`, 값 배지와 출처), 핵심 가치 V5.
- 범위 밖: 재료 DB 확장(S2; MatWeb 같은 재배포 금지 DB에서 대량으로 옮기는 일은 하지 않는다), 두 재료 쌍별 마찰표, 접촉 마찰 합성(X-01e, 구현됨: [`contact.md`](contact.md)), 이방성·적층 이론, 온도·변형률 속도 의존, 파단 임계 계산(X-04a, 구현됨: [`break-threshold.md`](break-threshold.md)). CFRP의 `yield_strength` 뜻과 강도 기준 혼재는 #481, `Source`의 범위·접근일 필드는 B-07a.

## 숫자는 코드에 없다

수치는 모두 JSON 데이터 파일에 있고 값마다 `Quantity`(값, 단위, 배지, 출처)다. 출처 칸(`source.ref`)에 **고른 값, 출처에 인쇄된 값, 범위, 강도의 기준**이 함께 있다. 접근일은 전부 2026-11-11이다. 인용한 출처는 생산자 데이터시트, 정부(FHWA) 문서, 서적 부록이다. `source.url`은 그 문서를 가리키며, 유료 서적(ASM Handbook)은 URL 없이 서지(ISBN, 쪽)로 인용한다. MatWeb 값은 이 데이터에 없다(아래 "출처 약관 확인").

SI 환산: 1 ksi = 6.894757 MPa, 1 psi = 6.894757 kPa, 1 lb/ft³ = 16.01846 kg/m³.

| 재료 | id | 밀도 kg/m³ | 항복 또는 파단 강도 Pa (기준) | 탄성계수 Pa | 마찰 (건조, 대 강철, 운동) | 마찰 배지 |
|---|---|---|---|---|---|---|
| 알루미늄 6061-T6 | `al6061-t6` | 2700 | 2.76e8 (대표값) | 6.895e10 | 0.38 | `cite` |
| 구조용 강 ASTM A36 | `steel-a36` | 7849 | 2.482e8 (규격 최소) | 1.9995e11 | 0.23 | `estimate`(대용) |
| CFRP (HexPly 8552 / AS4 평직) | `cfrp-8552-as4-pw` | 1570 | 8.28e8 **(파단 강도, 대표값)** | 6.8e10 | 0.44 | `estimate` |
| 티타늄 Ti-6Al-4V (5등급, 어닐링) | `ti-6al-4v` | 4420 | 8.28e8 (규격 최소) | 1.151e11 | 0.32 | `cite` |
| POM 아세탈 (Delrin 150) | `pom-delrin-150` | 1420 | 7.2e7 (대표값) | 3.1e9 | 0.21 | `cite`(일반 아세탈) |

밀도·강도·탄성계수는 다섯 재료 모두 `cite`다.

### 강도의 기준이 섞여 있다 — 재료 사이의 강도 비교는 무효

6061-T6, CFRP, POM은 **대표값(typical)**, A36과 Ti-6Al-4V는 **규격 최소값**이다. 한 기준으로 맞출 수 있는 출처가 없다: 6061-T6의 규격 최소(ASTM B209/B221)는 이번에 생산자 문서로 열지 못했고, A36의 대표값은 FHWA가 "50 ksi에 가까울 수 있다"고만 쓰며 수치를 주지 않고, Ti-6Al-4V와 CFRP는 각각 최소·대표만 인쇄한 시트가 있다. 그래서 `ref`마다 기준(`Basis: TYPICAL` / `Basis: specified MINIMUM`)을 적었고, **이 카탈로그의 강도를 재료끼리 비교하면 안 된다**. 6061-T6(276 MPa)가 A36(248 MPa)보다 커 보이는 것은 기준 차이이지 재료 순위가 아니다. X-04a가 `강도 × 단면적`으로 임계를 낼 때 이 점을 알아야 하며 해결은 #481 범위다.

### 출처 약관 확인

- **MatWeb 값은 배포 데이터에 없다.** MatWeb 이용 약관(https://www.matweb.com/reference/terms.aspx)은 데이터베이스와 그 내용의 재배포, 개인·사내 사용 밖의 복제와 카탈로그 구성을 금지한다. 이 저장소는 공개이므로 MatWeb의 값, URL, 아카이브 사본 URL을 `material_catalog.json`에 넣지 않았다. 작업 중 교차 확인으로 참고했을 뿐이며 그 수치를 여기 옮기지 않는다. 테스트 `test_materials_catalog_contains_no_matweb_urls_or_figures`가 카탈로그에 `matweb`, `archive.org`가 없음을 지킨다.
- **사실 수치의 인용.** 밀도·강도·탄성계수는 저작물이 아니라 측정된 사실이며, 이 PR은 문서 하나를 복제하지 않고 값 몇 개를 출처 위치와 함께 적었다. 출처마다 약관이 다르다:
  - Kaiser Aluminum 기술 자료: 문서에 이용 약관이 없다. 면책 문구 없이 "Typical"로 표시된 값.
  - TIMET 데이터시트(TMC-0150, 2000): "신뢰할 만한 출처에서 파생했고 특정 용도는 기술 서비스와 상의하라"는 문구뿐이다. Rolled Alloys 시트: "신뢰할 만하나 전문 엔지니어링을 대신하지 않는다", 보증 없음.
  - SSAB A36 데이터시트: 이용 약관 없음(규격 값).
  - FHWA-HIF-16-002: 18번 항목 "No restrictions. This document is available to the public through the National Technical Information Service". FHWA NHI-15-047: 18번 항목은 "이 보고서는 NHI Bookstore에서 공개된다"고만 쓰며 사용 제한 문구는 없다. 둘 다 미국 정부 간행물이다.
  - Hexcel HexPly 8552(2023): "값은 대표값이며 자체 시험을 대신할 수 없다", 보증 없음.
  - DuPont Delrin 150 NC010 Product Information(2006, Boedeker 배포본): "값은 사양 한계나 설계의 유일한 근거로 쓰지 말 것". 이 PDF의 배포 URL은 제3자(Thomasnet CDN)다. DuPont 소유 URL을 열린 곳에서 찾지 못했다 [확인 필요]. 2018·2020판은 같은 값(항복 73 MPa, 계수 3100 MPa, 밀도 1420)이고 제3자 사본만 확인했다. Delrin 사업은 DuPont에서 분리되어 지분 대부분이 2023년에 TJC로 넘어갔다고 보도되었으나 시트의 소유 주체를 확인하지 못했으므로 "제조사 시트"라고 쓰지 않고 **DuPont이 발행한 시트의 제3자 배포본**이라고 쓴다.
  - ASM Handbook Vol. 18 부록: 유료 서적이다. URL 없이 서지와 쪽(pp. 70-75)으로 인용한다. 공개된 사본(특허심판원 제출 증거물, 쪽 70-75)에서 표를 대조했다. 값 몇 개의 인용이며 표를 옮기지 않았다.
- 데이터시트의 면책 문구는 값 옆에 옮겼다(`typical`, `minimum`, `not for design`).

### 값을 고른 방법과 범위

- **알루미늄 6061-T6.** Kaiser Aluminum "Rod & Bar Alloy 6061 Technical Data"(KA-RBH-6061-8.10) 1·2쪽의 대표값: 밀도 0.098 lb/in³ = 2.70 Mg/m³, T6·T651 항복 40 ksi = 276 MPa, 탄성계수 **미국 단위 10.0×10³ ksi, 미터 단위 68.3 GPa로 인쇄**(둘이 어긋난다: 10,000 ksi × 6.894757 = 68.95 GPa는 인쇄된 68.3 GPa보다 0.95% 크다). 정확한 환산인 68.95 GPa를 골랐고 범위는 68.3~68.95 GPa다.
- **강 A36.** 항복은 SSAB ASTM A36 데이터시트(2019-05-20): 최소 36 ksi = 248.2 MPa, 인장 58~80 ksi. FHWA-HIF-16-002 표 5도 같다(A709 Grade 36). ASTM A36M은 250 MPa로 쓴다. 탄성계수는 FHWA-HIF-16-002 4.1절: 교량용 모든 구조강에 E = 29,000 ksi = 199.95 GPa. 밀도는 FHWA NHI-15-047 표 3.2.1.2-1(AASHTO LRFD 표 3.5.1-1 발췌): 강 0.490 kcf = 7849 kg/m³. **A36 전용 값이 아니라 구조강 설계 단위중량**이며 보통 7850으로 반올림한다.
- **CFRP.** Hexcel HexPly 8552 제품 데이터시트(EU판 2023) 3쪽, AS4 3K 평직 프리프레그 AGP193-PW: 적층 밀도 1.57 g/cm³, 0° 인장 강도 828 MPa, 0° 인장 계수 68 GPa(25 °C 건조). 90°는 793 MPa·66 GPa다. 같은 시트의 일방향 AS4는 섬유 방향 2207 MPa·141 GPa, 직각 방향 81 MPa·10 GPa라서 방향에 따라 27배 차이가 난다. 섬유 방향을 모르므로 균형 평직의 면내 값을 골랐다.
- **티타늄 Ti-6Al-4V.** TIMET "TIMETAL 6-4" 데이터시트(TMC-0150): 밀도 0.160 lb/in³ = 4.42 g/cm³(표 2), 어닐링 판·바(ASTM B265/B348)의 **최소** 0.2% 항복 120 ksi = 828 MPa(표 3). 같은 표의 용체화·시효(STA)의 최소 항복은 두께 3 in까지 130~155 ksi(896~1068 MPa)다. Rolled Alloys(Bulletin 1052USe 09/16): 어닐링 바의 대표 항복 128~147 ksi, 탄성계수 16.7×10⁶ psi = 115.1 GPa(STA, 70 °F). TIMET 표 2는 영 계수를 15.5~17.7 Msi(107~122 GPa)로 쓴다(조직과 열처리에 따라). 하한(828 MPa)과 115.1 GPa를 골랐다.
- **POM.** DuPont Delrin 150 NC010 Product Information(2006): 항복 72 MPa(ISO 527), 인장 계수 3100 MPa, 밀도 1420 kg/m³(ISO 1183). 항복 범위 69~76.5 MPa(DuPont 2018판 73 MPa, 작성자 미상 유통사 시트 76.5 MPa, HPC Europe 69 N/mm²). 열가소성 물성은 23 °C 값이고 온도·속도에 따라 변하며 크리프는 모형화하지 않는다.

### 마찰 계수

`Material.friction`은 **건조·상온·운동(미끄럼) 쿨롱 계수, 대 강철**이다. 값은 시험 방법에 크게 의존하고 다섯 값은 서로 다른 세 가지 시험에서 왔다: 평판 대 평판 1.96 N(알루미늄·강·티타늄, Magnaplate 1988), 스러스트 와셔 0.28 MPa(POM, ICI Lubricomp 자료), 스트립 드로잉 4~12 MPa(CFRP). Blau 서문은 이 표를 "아주 대략의 길잡이"라고 쓴다. **값끼리 서열을 매기지 말 것.** 두 면이 만나는 접촉의 계수는 두 값 중 작은 쪽이다(X-01e, [`contact.md`](contact.md)).

**고르는 규칙(하나).** Blau 표 1에서 *강 1032를 고정, 대상 재료를 이동*시킨 행의 **운동** 계수를 쓴다. 폴리머는 같은 방향(강 고정, 폴리머 이동)의 행을 쓴다.

| 재료 | 쓴 행 | 규칙 방향 | 반대 방향 |
|---|---|---|---|
| 알루미늄 6061-T6 | 표 1, 강 1032 / Al 6061-T6: 정 0.47, 운동 **0.38** | 0.38 | Al 고정 / 강 이동: 0.35, 0.25 |
| 강 A36 | 표 1, 강 1032 / 강 1032: 정 0.31, 운동 **0.23** (A36이 아니라 대용) | 0.23 | 같은 재료 쌍(방향 없음) |
| 티타늄 Ti-6Al-4V | 표 1, 강 1032 / Ti-6Al-4V: 정 0.36, 운동 **0.32** | 0.32 | Ti 고정 / 강 1032 이동 행은 표에 없다 |
| POM | 표 3, 강(연강) / 아세탈: 정 0.14, 운동 **0.21** (일반 아세탈, Delrin 150 아님) | 0.21 | 유통사 Delrin 150 시트의 동마찰 0.2(ASTM D3702), POM 대 강 52100: 0.45 |
| CFRP | 규칙을 적용할 수 없다: 위 표에 없다. 아래 | | |

알루미늄 값이 이전 판의 0.25에서 0.38로 바뀐 이유는 이 규칙이다. 같은 장비에서 알루미늄을 티타늄과 같은 방향으로 잰 행이 0.38이다(순서가 알루미늄 0.38 > 티타늄 0.32로 뒤집혔다). 각 `ref`에 반대 방향 값과 범위를 적었다. 범위의 다른 값은 Engineering ToolBox(알루미늄 대 연강 운동 0.47; 강 대 강 0.42)와 Blau 표 1의 연강 대 연강 0.62(Archard, 핀-링)다.

- **A36 마찰은 `estimate`다.** Blau 표에 A36이 없어 강 1032의 값을 대용으로 쓴다(`ref`에 "PROXY").
- **CFRP 마찰은 `estimate`다.** 이 적층판을 강철과 마찰시켜 잰 공개 값을 열린 문서에서 찾지 못했다. 가장 가까운 것은 Trzepieciński 외, *Int J Adv Manuf Technol* 143 (2026), DOI 10.1007/s00170-026-17653-1이며 일방향 CFRP 시트를 **DMLS로 3D 프린트한** 스테인리스·합금강(CX, 20MnCr5, 15MnCr4) 상대재와 건조 미끄럼시켜 0.286~0.595를 보고한다(초록만 읽었고 본문은 유료). 그 범위의 중앙 0.44를 넣었다.

## CFRP의 `yield_strength`는 항복이 아니다

CFRP는 항복점이 없다. 선형 탄성으로 올라가다 취성 파단한다. C-01a의 `Material.yield_strength`는 값이 0보다 커야 하므로 항복강도 대신 **0° 인장 파단 강도 828 MPa**를 넣고, 출처 메모에 `no yield point`, `tensile STRENGTH at fracture`라고 적었다(테스트가 이 문구를 지킨다). 이 값은 파단 임계(`강도 [Pa] × 단면적 [m²]`, X-04a)로 읽을 수 있지만 **필드 이름과 값의 뜻이 다르고**, 재료가 이방성인데 스칼라 하나이며, ±45° 같은 방향의 강도는 이 표에 없다. 필드의 뜻과 위의 강도 기준 혼재는 #481에서 정한다.

## PBR 슬롯

슬롯은 Filament 재질 모델의 표준 매개변수 넷이다: `base_color`(sRGB `#rrggbb`), `metallic`, `roughness`, `reflectance`(0~1 무차원).

**클라이언트 대응(정확히).**

| 슬롯 | glTF 2.0 core | three.js |
|---|---|---|
| `base_color` | `pbrMetallicRoughness.baseColorFactor` = **선형 RGB**. `base_color`(sRGB)를 `srgb_to_linear`로 바꿔 `[r, g, b, 1]`로 넣는다. sRGB 값을 그대로 넣으면 금속이 눈에 띄게 밝아진다 | `MeshStandardMaterial.color`. `color.set("#rrggbb")`는 색 관리가 변환한다. sRGB 숫자를 `setRGB`로 그대로 넣으면 안 된다 |
| `metallic` | `metallicFactor` | `metalness` |
| `roughness` | `roughnessFactor` (세 체계 모두 지각 거칠기라 그대로) | `roughness` |
| `reflectance` | **대응 없음.** 유전체 F0는 0.04(굴절률 1.5)로 고정. 다른 값은 확장 `KHR_materials_ior`(`ior`, 기본 1.5) | `MeshStandardMaterial`에 **없음**. `MeshPhysicalMaterial.reflectivity`(기본 0.5 = `ior` 1.5)와 `.ior` |

Filament `reflectance` 0.5는 F0 = 0.16 × 0.5² = 0.04, 곧 굴절률 1.5이므로 카탈로그의 다섯 항목은 모두 0.5라서 glTF core와 `MeshStandardMaterial`이 그대로 맞는다. 0.5가 아닌 값은 클라이언트가 `ior = (1 + 0.4 r) / (1 - 0.4 r)`로 `KHR_materials_ior`나 `MeshPhysicalMaterial`을 써야 한다(F0 = ((ior-1)/(ior+1))²). `metallic = 1`이면 효과가 없다. 근거: Filament 재질 가이드(https://google.github.io/filament/Filament.html, Apache-2.0)의 "Types and ranges"와 "Reflectance remapping", glTF `KHR_materials_ior`, three.js `MeshPhysicalMaterial` 문서.

| 재료 | base_color | metallic | roughness | reflectance |
|---|---|---|---|---|
| 알루미늄 | `#e8eaea` (Filament 순알루미늄 F0, `estimate`) | 1.0 (`cite`) | 0.4 (`default`) | 0.5 (`default`, 금속에서는 효과 없음) |
| 강 | `#c4c6c6` (Filament 순철 F0, `estimate`) | 1.0 | 0.5 (`default`) | 0.5 |
| 티타늄 | `#c1baaf` (Filament 순티타늄 F0, `estimate`) | 1.0 | 0.45 (`default`) | 0.5 |
| CFRP | `#1c1d20` (`default`) | 0.0 (`default`) | 0.3 (`default`) | 0.5 (`cite`, Filament 플라스틱 4~5%) |
| POM | `#e9e7e0` (`default`) | 0.0 (`default`) | 0.5 (`default`) | 0.5 (`cite`) |

- 금속의 기본 색은 Filament가 측정에서 계산한 **순금속** F0 색이다. 합금의 색이 아니므로 A36 마찰의 대용 값과 같은 이유로 `estimate`다. 거칠기와 CFRP·POM의 색은 외형 선택이라 `default`다("a look, not a measurement").
- **찾는 법.** 카탈로그는 `Material.id`로 찾는다: `DesignSpec.materials`에 든 재료의 외형은 클라이언트가 `load_material_catalog().get(material.id)`로 얻는다. **카탈로그에 없는 재료**(사용자 선언 재료)는 PBR 항목이 없고, 클라이언트는 중립 대체 외형을 쓴다: 중간 회색 유전체(`#808080`, metallic 0, roughness 0.5, reflectance 0.5). 다른 재료의 외형을 빌려 쓰지 않는다.
- **텍스처 맵을 쓰지 않는다.** `assets/LEDGER.csv`의 CC0 텍스처는 행성 지면과 하늘뿐이라 금속·복합재·플라스틱 질감이 없다. 새 에셋을 들이지 않았고(원장·CREDITS 변경 없음) 텍스처 경로 필드도 두지 않았다. `PbrSlots`가 `extra="forbid"`라서 경로 필드는 거부된다(테스트 `test_materials_pbr_uses_no_texture_files`). 텍스처가 원장에 들어오는 날 슬롯 필드를 더한다.
- 색 공간: `base_color`는 sRGB(디자인 토큰과 같은 표기).

## 라이선스

- 값은 사실 수치이며 문서에서 옮겨 적고 출처 위치와 접근일을 붙였다. 파일을 복제하거나 에셋을 들이지 않았다. 출처 약관 확인은 위 "출처 약관 확인"에 있다.
- `source.license`는 Filament 문서 인용(`metallic`, `reflectance`)에만 `Apache-2.0`(Filament 저장소 라이선스)을 적었다. 데이터시트와 정부 문서 값에는 적지 않았다(알려진 SPDX 라이선스가 없다).
