# 재료 5종과 PBR 슬롯 (B-07)

- 상태: 구현됨. 데이터는 `packages/core/src/kinetra_core/material_catalog.json`, 모델은 `material_catalog.py`(로더 `load_material_catalog()`), `pbr.py`(PBR 슬롯). 테스트는 `packages/core/tests/test_materials.py`(`uv run pytest packages/core -q -k materials`).
- 근거: 이슈 #120, `docs/architecture/project-model.md`(`Material`, 값 배지와 출처), 핵심 가치 V5.
- 범위 밖: 재료 DB 확장(S2; MatWeb 같은 재배포 금지 DB에서 대량으로 옮기는 일은 하지 않는다), 두 재료 쌍별 마찰표와 접촉 마찰 합성(X-01), 이방성·적층 이론, 온도·변형률 속도 의존, 파단 임계 계산(X-04a). CFRP의 `yield_strength` 뜻은 이월 이슈 #481.

## 숫자는 코드에 없다

수치는 모두 JSON 데이터 파일에 있고 값마다 `Quantity`(값, 단위, 배지, 출처)다. 출처 칸(`source.ref`)에 **고른 값, 출처에 인쇄된 값, 범위**가 함께 있다. 접근일은 전부 2026-11-11이다. 인용한 출처는 제조사·생산자 데이터시트, 정부(FHWA) 문서, 학술 서적 부록이며 `source.url`이 그 문서를 직접 가리킨다. **MatWeb은 인용 출처가 아니다**(아래 "출처 약관 확인").

SI 환산: 1 ksi = 6.894757 MPa, 1 lb/ft³ = 16.01846 kg/m³.

| 재료 | id | 밀도 kg/m³ | 항복 또는 파단 강도 Pa | 탄성계수 Pa | 마찰(건조, 강철 상대, 운동) | 배지 |
|---|---|---|---|---|---|---|
| 알루미늄 6061-T6 | `al6061-t6` | 2700 | 2.76e8 | 6.895e10 | 0.25 | 모두 `cite` |
| 구조용 강 ASTM A36 | `steel-a36` | 7849 | 2.482e8 (규격 최소) | 1.9995e11 | 0.23 | 앞 셋 `cite`, 마찰 `estimate`(대용 값) |
| CFRP (HexPly 8552 / AS4 평직) | `cfrp-8552-as4-pw` | 1570 | 8.28e8 **(파단 강도)** | 6.8e10 | 0.44 | 앞 셋 `cite`, 마찰 `estimate` |
| 티타늄 Ti-6Al-4V (5등급, 어닐링) | `ti-6al-4v` | 4420 | 8.28e8 (규격 최소) | 1.151e11 | 0.32 | 모두 `cite` |
| POM 아세탈 (Delrin 150) | `pom-delrin-150` | 1420 | 7.65e7 | 3.103e9 | 0.20 | 모두 `cite` |

### 출처 약관 확인

- **MatWeb 값은 배포 데이터에 없다.** MatWeb 이용 약관(https://www.matweb.com/reference/terms.aspx)은 데이터베이스와 그 내용의 재배포, 개인·사내 사용 밖의 복제와 카탈로그 구성을 금지한다. 이 저장소는 공개이므로 MatWeb의 값, URL, 아카이브 사본 URL을 `material_catalog.json`에 넣지 않았다. 작업 중 교차 확인으로 참고했을 뿐이며 그 수치를 여기 옮기지 않는다. 테스트 `test_materials_catalog_contains_no_matweb_urls_or_figures`가 카탈로그에 `matweb`, `archive.org`와 MatWeb에서만 읽은 수치가 없음을 지킨다.
- **사실 수치의 인용.** 밀도·강도·탄성계수는 저작물이 아니라 측정된 사실이며, 이 PR은 문서 하나를 복제하지 않고 값 몇 개를 출처 위치와 함께 적었다. 생산자 데이터시트의 약관은 각 PDF의 면책 문구뿐이고 인용을 금지하지 않는다: Kaiser Aluminum은 문서에 약관이 없고, Rolled Alloys는 "신뢰할 만하나 전문 엔지니어링을 대신하지 않는다"고 쓴다. Hexcel(2023)은 "값은 대표값이며 자체 시험을 대신할 수 없다"고 쓴다. FHWA 문서는 정부 간행물이며 "No restrictions"(배포 제한 없음, 보고서 문서 쪽 17·18번 항목)이다. 데이터시트의 면책 문구를 값 옆에 옮겼다(`typical`, `minimum`, `not for design`).
- 사본에 대한 이용 허락이 필요하면 [확인 필요]: Delrin 데이터시트는 Protolabs가 게시한 DuPont/Celanese 시트(`protolabs.com`)이며 제조사 원문 URL이 아니다. 제조사 원문(Celanese)을 열린 URL로 찾지 못해 대신 게시처를 적었다. ASM Handbook Vol. 18 부록(Blau, 1992)은 ASM 유료 문서이고 `source.url`은 ASM 디지털 라이브러리의 서적 페이지다. 값 몇 개의 서지 인용이며 문서를 옮기지 않았다.

### 값을 고른 방법과 범위

- **알루미늄 6061-T6.** Kaiser Aluminum "Rod & Bar Alloy 6061 Technical Data"(KA-RBH-6061-8.10) 1·2쪽의 대표값: 밀도 0.098 lb/in³ = 2.70 Mg/m³, T6·T651 항복 40 ksi = 276 MPa, 탄성계수 **미국 단위 10.0×10³ ksi, 미터 단위 68.3 GPa로 인쇄**(둘이 서로 어긋난다: 10,000 ksi × 6.894757 = 68.95 GPa이므로 인쇄된 68.3 GPa보다 0.95% 크다). 정확한 환산인 68.95 GPa를 골랐다. 같은 회사의 "Sheet, Coil & Plate Alloy 6061"(Rev. 05/06)도 같은 값이다. 대표값이지 보증 최소가 아니다. 탄성계수 범위는 68.3~68.95 GPa.
- **강 A36.** 항복은 SSAB ASTM A36 데이터시트(2019-05-20): 최소 36 ksi = 248.2 MPa, 인장 58~80 ksi. FHWA-HIF-16-002 표 5도 같다(A709 Grade 36). ASTM A36M은 250 MPa로 쓴다. 규격 **최소(하한)** 값이며 FHWA는 요즘 납품되는 Grade 36이 50 ksi에 가까울 수 있다고 쓴다. 탄성계수는 FHWA-HIF-16-002 4.1절: 교량용 모든 구조강에 E = 29,000 ksi = 199.95 GPa. 밀도는 FHWA LRFD 교량 상부구조 참고서(NHI-15047) 표 3.2.1.2-1(AASHTO LRFD 표 3.5.1-1 발췌): 강 0.490 kcf = 7849 kg/m³. **A36 전용 값이 아니라 구조강 설계 단위중량** 이며 보통 7850으로 반올림한다(`ref`에 적었다).
- **CFRP.** Hexcel HexPly 8552 제품 데이터시트(EU판 2023) 3쪽, AS4 3K 평직 프리프레그 AGP193-PW: 적층 밀도 1.57 g/cm³, 0° 인장 강도 828 MPa, 0° 인장 계수 68 GPa(25 °C 건조). 같은 표의 90°는 793 MPa·66 GPa다. 같은 시트의 일방향 AS4는 섬유 방향 2207 MPa·141 GPa, 직각 방향 81 MPa·10 GPa라서 방향에 따라 27배 차이가 난다. 부품 안의 섬유 방향을 모르므로 균형 평직의 면내 값을 골랐다.
- **티타늄 Ti-6Al-4V.** TIMET "TIMETAL 6-4" 데이터시트(TMC-0150): 밀도 0.160 lb/in³ = 4.42 g/cm³(표 2), 어닐링 판·바(ASTM B265/B348)의 **최소** 0.2% 항복 120 ksi = 828 MPa(표 3). Rolled Alloys 데이터시트(Bulletin 1052USe 09/16): 어닐링 바의 대표 항복 128~147 ksi, 탄성계수 16.7×10⁶ psi = 115.1 GPa(STA, 70 °F). TIMET 표 2는 영 계수를 15.5~17.7 Msi(107~122 GPa)로 쓴다(조직과 열처리에 따라). 용체화·시효(STA)의 최소 항복은 150~155 ksi(1034~1068 MPa). 하한(828 MPa)을 골랐고 탄성계수는 115.1 GPa다.
- **POM.** Delrin 150 데이터시트(Protolabs 게시): 비중 1.42 g/cc, 항복 11,100 psi = 76.53 MPa, 인장 계수 450,000 psi = 3.1026 GPa, 동마찰 0.2(대 강철, 40 psi, 50 fpm, ASTM D3702). 시트가 "참고·비교용, 설계 근거로 쓰지 말 것"이라고 적었다. 항복 범위 69~76.5 MPa(69는 HPC Europe Delrin 150 시트의 +23 °C 인장 강도 69 N/mm²), 탄성계수는 같은 시트가 3100 N/mm²로 3.103 GPa와 일치. 열가소성 물성은 23 °C 값이고 온도와 속도에 따라 변하며 크리프는 모형화하지 않는다.

### 마찰 계수

`Material.friction`은 **건조·상온·운동(미끄럼) 쿨롱 계수, 대 강철** 로 다섯 재료에 같은 정의를 쓴다. 값은 시험 방법에 크게 의존하므로 출처도 시험 조건을 함께 적었다. 두 재료가 만나는 접촉에서 어떤 계수를 쓸지는 X-01이 정한다.

- 알루미늄, 티타늄은 ASM Handbook Vol. 18(1992) 부록(P.J. Blau) 표 1의 **같은 시험 장비 행**(General Magnaplate "Friction Data Guide" 1988, 1.96 N, 연삭 시편, 습도 54%, 평판 대 평판): 6061-T6 대 강 1032는 정 0.35·운동 0.25, Ti-6Al-4V 대 강 1032는 0.36·0.32. 범위: 알루미늄은 Engineering ToolBox의 운동 0.47까지, 티타늄은 스테인리스 상대 0.31~0.37.
- **A36 마찰은 `estimate`다.** Blau 표 1에는 강 1032 대 강 1032(운동 0.23)만 있고 A36 값이 없다. 대용 값이므로 `cite`가 아니라 `estimate`로 두었다(`ref`에 "Estimate ... proxy"). 범위: 연강 대 연강 0.62, Engineering ToolBox 0.42.
- POM은 제조사 데이터시트의 동마찰 0.20. 범위 0.20~0.45는 Blau 부록 표 3에서 온다.
- **CFRP 마찰은 `estimate`다.** 이 적층판을 강철과 마찰시켜 잰 공개 값을 열린 문서에서 찾지 못했다. 가장 가까운 것은 Trzepieciński 외, *Int J Adv Manuf Technol* 143 (2026), DOI 10.1007/s00170-026-17653-1이며 일방향 CFRP 시트를 세 가지 강철에 건조 미끄럼시켜 0.286~0.595를 보고한다(초록만 읽었고 본문은 유료). 그 범위의 중앙 0.44를 `estimate`로 넣었다.

## CFRP의 `yield_strength`는 항복이 아니다

CFRP는 항복점이 없다. 선형 탄성으로 올라가다 취성 파단한다. C-01a의 `Material.yield_strength`는 값이 0보다 커야 하므로(검증이 0을 거부한다) 항복강도 대신 **0° 인장 파단 강도 828 MPa** 를 넣고, 출처 메모에 `no yield point`, `tensile STRENGTH at fracture`라고 적었다(`test_materials_cfrp_has_no_yield_so_the_field_says_it_holds_tensile_strength`가 이 문구를 지킨다). 이 값은 판이나 결합부가 하중을 버티는 임계(`강도 [Pa] × 단면적 [m²]`, X-04a)로 읽을 수 있지만 **필드 이름과 값의 뜻이 다르고**, 재료가 이방성인데 스칼라 하나이며, ±45° 같은 방향의 강도는 이 표에 없다. 이 필드의 뜻을 고칠지는 #481에서 정한다. 그 전까지 이 PR은 값을 지어내지 않고 이 사실을 데이터와 문서에 둔다.

## PBR 슬롯

슬롯은 Filament 재질 모델의 표준 매개변수 넷이다: `base_color`(sRGB `#rrggbb`), `metallic`, `roughness`, `reflectance`(0~1 무차원).

**클라이언트 대응(정확히).**

| 슬롯 | glTF 2.0 core | three.js |
|---|---|---|
| `base_color` | `pbrMetallicRoughness.baseColorFactor` | `MeshStandardMaterial.color` |
| `metallic` | `metallicFactor` | `metalness` |
| `roughness` | `roughnessFactor` | `roughness` |
| `reflectance` | **대응 없음.** 유전체 F0는 0.04(굴절률 1.5)로 고정. 다른 값은 확장 `KHR_materials_ior`(`ior`, 기본 1.5) | `MeshStandardMaterial`에 **없음**. `MeshPhysicalMaterial.reflectivity`(기본 0.5 = `ior` 1.5)와 `.ior` |

Filament `reflectance` 0.5는 F0 = 0.16 × 0.5² = 0.04, 곧 굴절률 1.5이므로 카탈로그의 다섯 항목은 모두 0.5라서 glTF core와 `MeshStandardMaterial`이 그대로 맞는다. 0.5가 아닌 값을 쓰려면 클라이언트가 `ior = (1 + 0.4 r) / (1 - 0.4 r)`로 `KHR_materials_ior`나 `MeshPhysicalMaterial`을 써야 한다(F0 = ((ior-1)/(ior+1))²). `metallic = 1`이면 효과가 없다. 근거: https://google.github.io/filament/Filament.html "Reflectance remapping", https://github.com/KhronosGroup/glTF/blob/main/extensions/2.0/Khronos/KHR_materials_ior/README.md, three.js 문서 MeshPhysicalMaterial. 출처: Filament 재질 가이드(https://google.github.io/filament/Filament.html), "Parameterization > Types and ranges"의 표 1개와 "Remapping > Reflectance remapping"의 표 2개(Apache-2.0).

| 재료 | base_color | metallic | roughness | reflectance |
|---|---|---|---|---|
| 알루미늄 | `#e8eaea` (Filament 알루미늄 F0, `cite`) | 1.0 (`cite`) | 0.4 (`default`) | 0.5 (`default`, 금속에서는 효과 없음) |
| 강 | `#c4c6c6` (Filament 철 F0, `cite`) | 1.0 | 0.5 (`default`) | 0.5 |
| 티타늄 | `#c1baaf` (Filament 티타늄 F0, `cite`) | 1.0 | 0.45 (`default`) | 0.5 |
| CFRP | `#1c1d20` (`default`) | 0.0 (`default`) | 0.3 (`default`) | 0.5 (`cite`, Filament 플라스틱 4~5%) |
| POM | `#e9e7e0` (`default`) | 0.0 (`default`) | 0.5 (`default`) | 0.5 (`cite`) |

- 금속의 기본 색은 Filament가 측정에서 계산해 둔 **순금속** F0 색이다. 합금의 색이 아니므로 근사이며 강은 철 행을 썼다(출처 메모에 적었다).
- 거칠기, CFRP·POM의 색은 외형 선택이다. 측정값이 아니므로 `default` 배지와 "a look, not a measurement"를 적었다.
- **텍스처 맵을 쓰지 않는다.** `assets/LEDGER.csv`의 CC0 텍스처는 행성 지면(지구 풀밭, 화성 붉은 흙, 달 레골리스)과 하늘뿐이라 금속·복합재·플라스틱 질감이 없다. 없는 에셋을 새로 들이지 않았고(CC0 아닌 에셋 없음, 원장 행·CREDITS 변경 없음) 그 자리를 변수로 두지도 않았다. 텍스처가 원장에 들어오는 날 슬롯 필드를 더한다. `PbrSlots`가 `extra="forbid"`라서 지금은 경로 필드를 거부한다(테스트 `test_materials_pbr_uses_no_texture_files`).
- 색 공간: `base_color`는 sRGB(디자인 토큰과 같은 표기). 선형 변환은 클라이언트가 한다.

## 라이선스

- 값은 사실 수치이며 문서에서 옮겨 적고 출처 위치와 접근일을 붙였다. 파일을 복제하거나 에셋을 들이지 않았다. 출처 약관 확인은 위 "출처 약관 확인"에 있다.
- `source.license`는 Filament 문서 인용에만 `Apache-2.0`(Filament 저장소 라이선스)을 적었다. 데이터시트와 정부 문서 값에는 적지 않았다(알려진 SPDX 라이선스가 없다).
