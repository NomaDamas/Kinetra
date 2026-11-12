# 행성 데이터 3종과 로더 (W-01)

- 상태: 구현됨. 데이터는 `data/bodies/{earth,mars,moon}.json`, 모델과 로더는 `packages/core/src/kinetra_core/bodies.py`(`load_body`, `load_bodies`, `check_world_references`), 테스트는 `packages/core/tests/test_bodies.py`(`uv run pytest packages/core -q -k bodies`).
- 근거: 이슈 #76, 핵심 가치 V1(가정과 한계를 숨기지 않는다)·V5(출처가 있는 수치만), `client-adapter.md` 규칙 C4·P2.
- 범위 밖: 지형 고도 자료, 시각·장소에 따른 대기·바람·낮밤, 가정표의 "근사: 균일 중력" 라벨(W-06). 엔진이 읽는 법은 아래 "엔진이 읽는 법 (W-03a)".

## 규칙

- 수치는 데이터 파일에만 있다. 코드와 클라이언트에는 중력 값이 없다. 테스트 `test_bodies_no_gravity_literal_in_engine_or_client_code`가 `packages`, `apps`, `scripts`, `tools`의 코드 파일(`.py`, `.json`, C 계열 `.ts .tsx .js .mjs .wgsl .glsl` 등, 마크업 `.html .vue .xml`)에서 세 행성의 중력에 1.5% 안으로 가까운 숫자를 값으로 비교해 찾는다(`9.810`, `981e-2`, `0.981e1`, `9.806_65`, `9.81f`, 반올림 9.8, 3.7, 1.6 모두). 주석과 문자열은 파일 종류별 문법으로 먼저 걷어 낸다(`#`은 Python에서만 주석, `//`와 `/* */`는 C 계열에서만; `"#ffffff"`, URL, TS `#private`, GLSL `#define`은 주석이 아니다. JSON은 문자열 값을 걷어 낸다). `tests/`, `node_modules`, `spikes/`, `schemas/`(생성물), `out/`은 건너뛴다. 못 보는 것: 문자열 안의 수(TS의 `"0 0 -9.81"`), 계산해서 만든 값(`GM / r**2`), 같은 상수의 다른 이름. 그 보장은 구조(엔진은 `load_body`로만 읽는다, W-03a)와 검증기(C-02c)다. **예외 표식:** 행의 주석에 `gravity-scan: ok <이유>`가 있으면 그 행은 넘어간다(CSS `lineHeight: 1.62`, 3.7 V 셀 전압 등). 이유가 없으면 예외가 아니다. 검사기 자체는 위 모든 철자와 오탐 사례를 심은 테스트로 시험한다.
- 항목마다 `Quantity`(값, 단위, 배지, 출처). 출처는 `source.ref`(고른 값, 출처가 적은 값, 범위, 교차 확인, 받은 날짜 `accessed YYYY-MM-DD`), `locator`(표·절), `url`이다. `인용`은 위치와 url이 있어야 한다.
- 로더가 지키는 것: 배지는 `cite`, `default`, `estimate`만(행성 상수는 `sim`도 `declared`도 아니다), 지면 마찰 분포는 `uniform` 또는 `normal`(`fixed`나 누락은 퍼짐을 숨기므로 거부), `editable`은 `False`(사용자가 행성을 고치지 않는다, 규칙 C4), `id`는 파일 이름과 같다.
- `unverified`: 인용한 숫자가 아닌 항목(`추정` 또는 `기본값`)을 이유와 함께 적는다. 목록이 배지와 어긋나면 로딩이 실패한다.
- 새 단위 `W/m^2`(`Unit.W_PER_M2`)를 더했다(일사). `kinetra_core.Unit`이 닫힌 어휘이기 때문이다.
- **데이터 위치.** 소스 체크아웃은 `data/bodies`를 읽고, 휠은 같은 파일을 `kinetra_core/bodies_data/`로 싣는다(`packages/core/pyproject.toml`의 hatch `force-include`; 휠을 만들어 파일이 들어간 것을 확인했다). 편집 설치가 아니어도 `load_body`가 찾는다.
- 균일 중력과 표면 대기 밀도 하나씩이 모델이다. 지구의 위도별 중력, 화성의 계절별 밀도, 달의 낮밤은 값으로 들어가지 않고 출처 칸에 범위만 적는다.

## 중력의 기준

- 지구 9.80665: CODATA 2018이 정한 **표준값**(자전 포함, 정의라서 측정 평균이 아니다). 팩트시트의 "Surface gravity (mean) 9.820"은 자전을 뺀 GM/R²이고(`fact_notes.html`의 정의), 지면의 물체가 받는 실제 값은 9.780(적도) ~ 9.832(극)다. 표준값은 그 범위 안에 있고 시트에 인쇄돼 있어 `인용`이다.
- 화성 3.73: 시트의 "mean"은 자전을 뺀 GM/R²이고 실제 지면 범위는 3.69(적도) ~ 3.73(극)이다. 3.73은 그 범위의 위쪽 끝이다(지구와 기준이 다르다). 적도 값 3.69는 0.5% 낮고 낙하 시간으로는 0.27% 차이다. JPL의 3.71은 적도 값을 다시 계산한 것이다.
- 달 1.62: 시트의 단일 값. GM/R²는 1.624.
- 세 값 모두 한 행성에 균일한 g 하나로 쓴다(W-06의 라벨). 범위는 샘플링하지 않는다.

## 값과 출처

| | 지구 | 화성 | 달 |
|---|---|---|---|
| 중력 m/s² | 9.80665 `인용` (표준 정의값) | 3.73 `인용` (자전 뺀 GM/R², 범위 3.69~3.73의 위 끝) | 1.62 `인용` |
| 대기 밀도 kg/m³ | 1.217 `인용` | 0.016 `인용` (시트 ~0.016 ± 0.006, 출처가 인쇄한 불확실도) | 0 `기본값`(질량 밀도는 시트에 없음) |
| 일사 W/m² | 1361.0 `인용` | 586.2 `인용` | 1361.0 `인용` |
| 지면 마찰 하한 ~ 상한 | 0.3443 ~ 0.7813 (tan 19° ~ 38°) | 0.3249 ~ 0.7002 (tan 18° ~ 35°) | 0.4142 ~ 0.9004 (tan 22.5° ~ 42°) |
| 지면 마찰 공칭(평균) | 0.5628 | 0.5126 | 0.6573 |
| 모두 `추정`, 신뢰도 | `low` | `low` | `low` |

출처: NASA NSSDCA 행성 팩트시트 [지구](https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html)(2024-11-15 갱신), [화성](https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html)(2025-05-19), [달](https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html)(2024-01-11), 모두 2026-11-11에 읽음. 교차 확인: JPL SSD [Planetary Physical Parameters](https://ssd.jpl.nasa.gov/planets/phys_par.html)와 [위성 GM](https://ssd.jpl.nasa.gov/sats/phys_par/)(달 GM 4902.800, DE440), NASA Glenn 대기 모델([지구](https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html): h = 0에서 식으로 1.227, 우리 계산; [화성](https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html) 0.0150). 지면 마찰: [FHWA NHI-06-088](https://www.fhwa.dot.gov/engineering/geotech/pubs/nhi06088.pdf) 표 5-15, [Sullivan 외 2010](https://www.lpi.usra.edu/meetings/lpsc2010/pdf/1879.pdf), [Moore 외 1987, USGS PP 1389](https://pubs.usgs.gov/pp/1389/report.pdf), [Lunar Sourcebook 9장](https://www.lpi.usra.edu/publications/books/lunar_sourcebook/pdf/Chapter09.pdf), 계면 마찰 [NAVFAC DM 7.02 표 1](https://www.tugraz.at/fileadmin/user_upload/Institute/IAG/Files/24_NAVFAC_DM_7_02.pdf)(p. 7.2-63, 정부 간행물). NASA 콘텐츠는 미국에서 일반적으로 저작권 대상이 아니다(https://www.nasa.gov/nasa-brand-center/images-and-media/). 값과 위치만 인용했고 문서를 복제하지 않았다.

## 엔진이 읽는 법 (W-03a)

- 코드는 `packages/engine/src/kinetra_engine/compiler/planet.py`(`planet_physics`, `PlanetPhysics`), 테스트는 `packages/engine/tests/test_freefall.py`(`uv run pytest packages/engine -q -k freefall`). 이슈 #83.
- `build_body_tree(project)`가 `project.world.planet`으로 `load_body`를 불러 `BodyTree.planet`(`PlanetPhysics`: 중력과 대기 밀도의 `Quantity`, 배지와 출처 그대로)에 싣는다. 컴파일러가 행성 상수를 얻는 길은 이것 하나다. 데이터가 없거나 읽히지 않는 행성은 `CompileError`다. `bodies_directory`로 다른 디렉터리를 줄 수 있다(시험이 파일의 값을 바꾸면 낙하가 바뀌는 것을 본다).
- MJCF: `<option gravity="0 0 -g" density="0" viscosity="0"/>`. +Z가 위이고 g는 데이터 파일의 값을 `repr`로 적어 같은 double로 읽힌다.
- **대기 밀도는 `BodyTree.planet.atmosphere_density`로 실리고 MuJoCo 매질(`option density`)에는 넣지 않는다.** MuJoCo 매질은 모든 바디에 같은 전역 값이고, 넣으면 관성 상자 항력(항력 계수 1에 해당하는 고정 식, 부력 없음, MuJoCo 4.0.0 `engine_passive.c` `mj_inertiaBoxFluidModel`)이 라벨 없이 붙는다. 항력은 W-03b가 이 밀도로 바디별 힘을 주고 "근사: 집중 항력"으로 표시한다(`docs/research/fluids/mujoco-water.md` 7.1절의 권고, 아래 "집중 항력 (W-03b)"). 공기 저항은 `DragRuntime`으로 스텝을 밟을 때만 걸린다. `mj_step`만 부르면 지구·화성에서도 공기 저항이 없다.
- 자유낙하 대조(정지 상태에서 1 m, 지면에 놓인 0.1 m 정육면체를 실행 초기 조건으로 2 m 올려 바닥에 닿지 않게, MuJoCo 기본 시간 간격 0.002 s와 반암시 오일러): 수계산 t = √(2h/g)는 지구 0.45160 s, 화성 0.73225 s, 달 1.11111 s. 시뮬은 세 행성 모두 수계산보다 0.99962 ~ 0.99998 ms 빠르다(`시뮬`). 적분기가 h_n = g·dt²·n(n+1)/2로 움직이므로 √(T² + dt²/4) − dt/2에서 h를 지나는 것과 맞는다(시간 간격의 1% 안). 시뮬과 수계산의 차이는 적분 오차뿐이고, 같은 식끼리의 대조라서 행성 모델이 현실과 맞는다는 증거는 아니다.

## 집중 항력 (W-03b)

- 코드는 `packages/engine/src/kinetra_engine/compiler/drag.py`(`compile_drag`, `Drag`, `DragRuntime`, `geom_drag_area`, `planet_medium`), 라벨은 `labels.py`(`drag_labels`, `model_labels`), 테스트는 `packages/engine/tests/test_drag.py`(`uv run pytest packages/engine -q -k drag`). 이슈 #84.
- **결정: MuJoCo 유체 모델이 아니라 직접 준 힘.** MuJoCo 매질(`opt.density`, `opt.viscosity`)은 모델 전역 실수 하나라 S2의 수역(물)과 대기를 한 장면에 둘 수 없고, 관성 상자 모델은 계수가 고정이다(`docs/research/fluids/mujoco-water.md` 3.1·7.1절, MuJoCo 4.0.0). 그래서 매질은 0으로 두고(`test_drag_is_not_mujocos_medium`) 바디마다 `F = −½ ρ(x) C_dA |v| v`를 질량중심에 준다. `v`는 질량중심의 월드 속도, `ρ(x) = Drag.medium_density(질량중심 위치)`. S1의 `planet_medium`은 행성 표면 대기 밀도 상수이고, FL-03b는 이 함수만 바꿔 끼운다. 토크·양력·바람은 없다.
- **힘을 주는 경로**: `DragRuntime.step(data)` = `mj_step1` → `xfrc_applied` 힘 행에 더함(+=) → `mj_step2` → 건드린 행을 원래 값으로 되돌림. 현재 스텝의 자세와 속도를 보고, 다른 작성자가 둔 힘은 지우지도 쌓지도 않는다(`test_drag_keeps_a_force_another_writer_put_in_xfrc_applied`). 이 경로는 궤적 해시의 일부다(`docs/decisions/engine.md` 4.4절). 실행 루프(X-02)가 `mj_step` 대신 이것을 불러야 공기 저항이 걸린다.
- **형상의 집중 계수**(`geom_drag_area`): 충돌 프록시 지오메트리마다 세 축 방향에서 본 `C_d × 투영 면적`의 평균, 바디는 그 합. 계수는 Baker 외 1983의 표(Aarønæs 2014 석사논문 표 2-2, 9쪽에 재수록, [PDF](http://publications.lib.chalmers.se/records/fulltext/199998/199998.pdf), 기준 면적은 흐름에 수직인 투영 면적, 2026-11-12에 읽음).

| 지오메트리 | 축별 값 | `C_dA` | 배지 |
|---|---|---|---|
| 구 r | 0.47, πr² | 0.47 πr² | `인용`(표의 구 그대로) |
| 상자 a×b×c | 정육면체 정면 1.05, 각 면 넓이 | 1.05 (ab+bc+ca)/3 | `추정`: 정육면체 값을 모든 상자에 쓴다. 표의 정육면체 모서리 방향 0.80(×√2 a² = 1.13 a²)과는 8% 안이지만 긴 직사각 부재 정면 2.05라 납작하거나 긴 상자는 이보다 항력이 크다 |
| 원통 r, 길이 L | 옆면(긴 막대) 1.20, 2rL 두 축; 끝면(막대) 0.82, πr² 한 축 | (2·1.20·2rL + 0.82 πr²)/3 | `추정`: 표의 원판 정면 1.17이라 짧은 원통은 이보다 크다 |

- **라벨**: 대기 밀도가 0보다 크면(지구, 화성) `model_labels(tree)`에 `근사: 집중 항력`(`kind` `drag`)이 한 줄 들어간다. 판정 가정표의 합성(W-03c)과 실행의 `model_labels`가 이 목록을 쓴다.
- **달은 0이다.** 데이터의 대기 밀도가 0이라 힘이 0이고 `DragRuntime`은 아무것도 더하지 않는다. 궤적이 `mj_step`만 쓴 것과 비트 단위로 같고 라벨도 없다(`test_drag_moon_is_zero_and_the_trajectory_is_the_one_without_drag`).
- **구의 종단속도 대조** (`시뮬`, MuJoCo 4.0.0, 기본 시간 간격 0.002 s, 오일러, 시드 없음·결정론): 반지름 0.05 m 구(시험 값), 재료 밀도 지구 50, 화성 5 kg/m³(시험 값, 몇 초 안에 종단속도에 닿게). 수계산 `v_t = √(2mg / (ρ C_dA))`: 지구 10.69105 m/s, 화성 18.18444 m/s. 정지에서 떨어뜨려 `v(t) = v_t tanh(g t / v_t)`와 비교했다. 8τ(τ = v_t/g; 지구 1.090 s, 화성 4.875 s) 뒤 속도는 수계산보다 상대 2.2×10⁻⁷ 작고(= 1 − tanh 8), 낙하 전체의 최대 차이는 두 행성 모두 0.184·g·Δt(지구 3.6 mm/s, 화성 1.4 mm/s)다. 같은 식끼리의 대조라서 계수가 현실의 물체와 맞는다는 증거는 아니다. 레이놀즈 수는 지구 약 7×10⁴, 화성 약 1.2×10⁵(공기 동점성 1.5×10⁻⁵ m²/s로 우리가 셈, 화성도 같은 값을 쓴 `추정`)이고, 0.47은 이 아임계 영역의 값이다. 매끈한 구는 약 3×10⁵ 이상에서 계수가 크게 떨어진다(NASA Glenn "Shape Effects on Drag": 구 0.07 ~ 0.5).
- **명시적 힘의 시간 간격 한계** (`시뮬`, 위 지구 구, τ = 1.090 s): 선형화하면 한 스텝이 속도 오차에 `1 − hρC_dA|v|/m`을 곱하고, 종단속도 근처에서는 `1 − 2gh/v_t`다. 잰 결과: h = 0.4τ, 0.5τ는 단조 수렴, 0.9τ는 7% 넘어선 뒤 수렴, 1.1τ는 0.49 v_t와 1.33 v_t를 오가는 2스텝 순환으로 수렴하지 않고, 1.5τ는 발산해 MuJoCo가 `mjWARN_BADQACC`를 낸다. 즉 안정 한계는 `h < v_t/g`(일반적으로 `hρC_dA|v|/m < 2`)다. 기본 0.002 s는 이 구의 τ/545다. 실행 중에 이 조건을 검사하지는 않는다.
- **한계**: 방향과 무관한 계수 하나(집중 근사), 지오메트리 사이의 겹침과 가림을 빼지 않아 여러 지오메트리로 된 바디는 항력이 크게 잡힌다, 관절로 이어진 바디도 각자 자기 질량중심 속도로 받는다, 회전 감쇠 없음. 화성 밀도의 불확실도(±37.5%)는 위 "정직성" 절 그대로 판정에 아직 반영되지 않는다.

## 지면 마찰: 규칙 하나, 세 행성

**끝값 규칙.** 그 행성의 대표 표면 물질 분류마다 출처가 인쇄한 대표 각(평균 또는 공칭; 범위만 있으면 그 범위의 중점)을 모으고, 가장 약한 분류를 포함해 **버리는 것 없이** 최솟값과 최댓값의 tan을 끝값으로 한다. 규칙은 모두 `distribution.source.ref`에 분류와 각을 적었다.

| 행성 | 모은 분류와 각(°) | 하한 ~ 상한 |
|---|---|---|
| 지구 | FHWA 표 5-15 USCS 평균: SW 38, SP 37, SM 34, SM-SC 33, SC 31, ML 32, ML-CL 32, CL 28, MH 25, CH 19(GW·GP·GM·GC는 `>`로만 인쇄돼 뺐다) | 19 ~ 38 |
| 화성 | Viking 표류물질 18, 덩어리 30, 혼합 31, 딱지 35(Moore 외 1987 초록); MER 도랑 30~37의 중점 33.5(Sullivan 외 2010) | 18 ~ 35 |
| 달 | Luna 16·20 실험실 20~25의 중점 22.5, Jaffe 13~56의 중점 34.5, Apollo 12 진공 직접 전단 28~35의 중점 31.5, 흙-바퀴 표 9.14의 35, 현장 윗 15 cm 표 9.12의 42 | 22.5 ~ 42 |

이전 판은 행성마다 규칙이 달랐다(지구는 가장 무른 두 분류를 빼고, 화성은 가장 무른 값을 넣고, 달은 범위의 끝을 썼다). 그 차이는 물리가 아니라 고른 방식에서 나왔으므로 한 규칙으로 맞췄다. 달의 하한이 내려간 것은 같은 규칙을 적용한 결과이고, 출처가 "실험실 응력에서 약한 입자가 부서져 낮게 나왔다"고 한 값이 포함된 것도 같은 이유다(그 설명은 `unverified`에 적었다).

**공칭 규칙.** 세 행성 모두 공칭값은 **끝값의 평균**이다(`value.source.ref`에 "Midpoint of the bounds"). 이전 판은 화성 공칭이 분포의 79% 지점이었다. 평균이면 결정론 탐색의 값과 몬테카를로의 평균이 같다. 공칭이 평균인 것은 그 값이 가장 그럴듯하다는 뜻이 아니다. 어느 출처도 가장 그럴듯한 값을 주지 않았다.

**대용 값이며 높은 쪽으로 치우쳐 있다.** 출처들은 흙의 내부 마찰각(Mohr-Coulomb, tan φ)이고 부품이 지면 위에서 미끄러지는 쿨롱 계수가 아니다. 서로 다른 재료의 계면에서는 마찰각 δ가 φ보다 작다(FHWA p. 2-39). NAVFAC DM 7.02 표 1의 계면 계수는 강판 말뚝 대 흙 0.20 ~ 0.40, 거푸집 콘크리트 대 흙 0.25 ~ 0.50, 매스 콘크리트 대 흙 0.30 ~ 0.60이다(미끄러지는 부품이 흙에 닿는 경우의 값이 아니라 구조물 벽면 값이다). 따라서 tan φ는 매끈한 부품에게 **상한**이고, 세 행성 분포는 모두 그 상한 쪽에 있다. 예: 지구 분포의 중간 0.56은 미끄럼 임계각 약 29°이고 계면 값 0.20 ~ 0.60은 11° ~ 31°다. 판정은 접지력을 **과대평가**하는 방향으로 치우친다. 하한을 계면 값까지 넓히지 않은 이유는 이 모델이 계면 재료(사용자 부품의 재질)를 모르기 때문이다. 부품 재질과 지면의 쌍별 마찰은 X-01의 접촉 합성이 맡는다. 이 치우침은 `source.ref`, `unverified`, 이 문서에 적었다. 이전 판의 "어떤 출처도 측정하지 않았다"는 말은 사실이 아니었다(NAVFAC에 계면 계수가 있다). 맞는 말은 "사용자가 만드는 부품과 지면의 계수를 준 출처가 없다"이다.

**분포는 측정된 모집단이 아니다.** 서로 다른 현장·방법에서 나온 대표 각의 최솟값과 최댓값 사이 uniform이다. 어느 출처도 분포를 주지 않았다. 신뢰도는 세 행성 모두 `low`다.

## 가정표에서의 자리 (W-03c의 계약)

프로젝트에 저장되는 `AssumptionTable`은 행성 키(`PLANET_CONSTANT_NAMES`: `ground_friction`, `gravity` …)를 계속 거부한다. 행성 상수는 프로젝트의 가정이 아니라 `data/bodies`의 것이고, 사용자가 프로젝트를 통해 바꿀 수 없어야 한다(규칙 C4). 그래서 `load_body(id).ground_friction`(`Assumption`)은 프로젝트의 표에 들어가지 않는다. **판정에 붙는 가정표는 판정 시점에 만든다:** 프로젝트의 행들에 `data/bodies`에서 읽은 행성의 행들(마찰 분포, 그리고 W-06이 붙이는 "근사: 균일 중력" 라벨)을 더해 합성한다. 합성은 W-03c의 일이다. 행성 행은 읽기 전용(`editable` False)이고 출처 배지는 이 파일의 것을 그대로 보인다. `test_bodies_planet_friction_is_not_a_row_of_the_projects_assumption_table`가 현재의 거부를 고정한다. 이 결정을 바꾸려면 테스트와 이 절을 함께 바꿔야 한다.

## 정직성: 이 값들이 말하지 않는 것

- **화성 마찰은 학회 초록까지만 읽었다.** Sullivan 외 2011(JGR, doi:10.1029/2010JE003625)은 출판사가 자동 접근을 막아 읽지 못했다. 30~37° 범위는 2010 LPSC 초록(표 1과 본문)에서 확인했다. [확인 필요: 2011 논문 본문]
- 달 대기 밀도 0은 모델의 선택이다. 팩트시트의 수 밀도(2×10⁵ 개/cm³)를 입자 질량으로 환산하면 약 5×10⁻¹⁵ kg/m³(우리 계산이고 출처가 적은 값이 아니다)로 지구의 약 4×10⁻¹⁵배이며, 항력이 보이지 않는다.
- **화성 대기 밀도는 고정값이지만 출처가 불확실도를 인쇄했다(±0.006, ±37.5%).** 종단속도로는 약 -15% ~ +26%다. 판정에는 아직 반영되지 않는다. 가정표의 분포로 만드는 일은 후속 이슈다.
- 일사는 대기 밖 값이다. 지구·화성의 지면 일사는 대기, 구름, 먼지로 줄고, 화성은 이심률(0.0935) 때문에 근일점과 원일점에서 490 ~ 713 W/m²로 달라진다(역제곱 환산, 우리 계산). 일사는 지금 판정에 쓰이지 않고 하늘·조명(W-02)의 입력으로 둔다.
- 중력 교차 확인: 화성 3.73(NSSDCA) 대 3.71(JPL 적도) 대 GM/R² 3.728, 달 1.62 대 GM/R² 1.624. 0.6% 안에서 일치한다.

## 교차 참조 (C-01c 이월)

`check_world_references(world, planets=..., materials=...)`: `World.planet`이 `planets`에 없거나 `terrain_props[].material`이 `materials`(프로젝트의 재료 ID, `DesignSpec.materials`)에 없으면 `ValueError`로 문제를 모두 나열한다. 재료가 `None`인 소품(행성 지면)은 재료가 필요 없다. `World`가 이것을 스스로 못 보는 이유는 `world.py` 머리말에 있다. 검증기(C-02c, `validator._world_findings`)가 이 함수를 부른다: 행성 쪽은 `validate_command`가 `unknown_id`로 거부하고, 재료 쪽은 `Project`가 이미 닫는다.
