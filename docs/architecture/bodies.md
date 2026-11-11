# 행성 데이터 3종과 로더 (W-01)

- 상태: 구현됨. 데이터는 `data/bodies/{earth,mars,moon}.json`, 모델과 로더는 `packages/core/src/kinetra_core/bodies.py`(`load_body`, `load_bodies`, `check_world_references`), 테스트는 `packages/core/tests/test_bodies.py`(`uv run pytest packages/core -q -k bodies`).
- 근거: 이슈 #76, 핵심 가치 V1(가정과 한계를 숨기지 않는다)·V5(출처가 있는 수치만), `client-adapter.md` 규칙 C4·P2.
- 범위 밖: 지형 고도 자료, 시각·장소에 따른 대기·바람·낮밤, 행성 상수를 읽는 엔진 코드(W-03a), 가정표의 "근사: 균일 중력" 라벨(W-06).

## 규칙

- 수치는 데이터 파일에만 있다. 코드와 클라이언트에는 중력 값이 없고, 테스트 `test_bodies_no_gravity_literal_in_engine_or_client_code`가 `packages/{core,engine,judge}/src`, `packages/ui`, `apps`, `scripts`의 코드 파일에서 세 행성의 중력과 흔한 반올림값(9.81, 9.8, 3.7, 1.62 …)이 숫자로 나오면 실패한다(주석, 식별자, 더 긴 수는 거른다). 검사기가 정말 잡는지는 심은 리터럴로 따로 시험한다. 이 검사는 문자 그대로의 리터럴만 본다. 계산해서 만든 값(`GM / r**2`)이나 다른 이름은 못 잡는다. 그 경우의 보장은 구조(엔진은 `load_body`로만 읽는다, W-03a)와 검증기(C-02c)다.
- 항목마다 `Quantity`(값, 단위, 배지, 출처). 출처는 `source.ref`(고른 값, 출처가 적은 값, 범위, 교차 확인, 받은 날짜 `accessed 2026-11-11`), `locator`(표·절), `url`이다. `인용`은 위치와 url이 있어야 한다.
- `unverified`: 인용한 숫자가 아닌 항목(`추정` 또는 `기본값`)을 이유와 함께 적는다. 목록이 배지와 어긋나면 로딩이 실패한다(약한 값을 말없이 두거나, 인용한 값을 약하다고 적는 일을 막는다).
- 지면 마찰은 C-01c의 `Assumption`: 공칭값(결정론 탐색)과 분포(몬테카를로), 분포의 수치는 자기 배지와 출처를 가지고, `confidence`로 신뢰를 적는다. 출처가 분포를 주는 경우는 없어서 분포는 모두 `uniform`(출처가 준 두 끝값 사이)이고 배지는 `추정`이다. `high`는 쓰지 않는다.
- 새 단위 `W/m^2`(`Unit.W_PER_M2`)를 더했다(일사). `kinetra_core.Unit`이 닫힌 어휘이기 때문이다.
- 균일 중력과 표면 대기 밀도 하나씩이 모델이다. 지구의 위도별 중력(9.780 ~ 9.832), 화성의 계절별 밀도 범위, 달의 낮밤은 값으로 들어가지 않고 출처 칸에 범위만 적는다.

## 값과 출처 (2026-11-11에 읽음)

| | 지구 | 화성 | 달 |
|---|---|---|---|
| 중력 m/s² | 9.80665 `인용` (NSSDCA 지구, CODATA 2018 표준값, 정확값) | 3.73 `인용` (NSSDCA 화성, 평균) | 1.62 `인용` (NSSDCA 달) |
| 대기 밀도 kg/m³ | 1.217 `인용` (NSSDCA 지구, 표면) | 0.016 `인용` (NSSDCA 화성, ~0.016 ± 0.006) | 0 `기본값`(NSSDCA 달: 희박한 외기권, 질량 밀도는 적혀 있지 않음) |
| 일사 W/m² | 1361.0 `인용` | 586.2 `인용` | 1361.0 `인용` |
| 지면 마찰 공칭 | 0.6494 `추정` = tan 33°(FHWA NHI-06-088 표 5-15, SM-SC) | 0.6619 `추정` = tan 33.5°(MER 바퀴 도랑 30~37°의 가운데, Sullivan 외 LPSC 2010) | 0.7002 `인용` = tan 35°(Lunar Sourcebook 표 9.14, 흙-바퀴 마찰각) |
| 지면 마찰 분포 | uniform 0.5317 ~ 0.7813 `추정` (CL 28° ~ SW 38°) | uniform 0.3249 ~ 0.7536 `추정` (Viking 표류물질 약 18° ~ MER 최대 37°) | uniform 0.5317 ~ 0.9325 `추정` (Apollo 12 진공 직접 전단 28° ~ 윗 15 cm 43°) |
| 지면 마찰 신뢰도 | `low` | `low` | `med` |

출처: NASA NSSDCA 행성 팩트시트 [지구](https://nssdc.gsfc.nasa.gov/planetary/factsheet/earthfact.html)(2024-11-15 갱신), [화성](https://nssdc.gsfc.nasa.gov/planetary/factsheet/marsfact.html)(2025-05-19), [달](https://nssdc.gsfc.nasa.gov/planetary/factsheet/moonfact.html)(2024-01-11). 교차 확인: JPL SSD [Planetary Physical Parameters](https://ssd.jpl.nasa.gov/planets/phys_par.html)(화성 적도 중력 3.71)와 [위성 GM](https://ssd.jpl.nasa.gov/sats/phys_par/)(달 GM 4902.800 km³/s², DE440)로 GM/R² 계산, NASA Glenn 대기 모델([지구](https://www.grc.nasa.gov/www/k-12/airplane/atmosmet.html) 1.225, [화성](https://www.grc.nasa.gov/www/k-12/airplane/atmosmrm.html) 0.0150 kg/m³). 지면 마찰: [FHWA NHI-06-088](https://www.fhwa.dot.gov/engineering/geotech/pubs/nhi06088.pdf)(정부 간행물), [Sullivan 외 2010](https://www.lpi.usra.edu/meetings/lpsc2010/pdf/1879.pdf), [Moore 외 1987, USGS PP 1389](https://pubs.usgs.gov/pp/1389/report.pdf), [Lunar Sourcebook 9장](https://www.lpi.usra.edu/publications/books/lunar_sourcebook/pdf/Chapter09.pdf), [Connolly·Carrier 2023](https://ntrs.nasa.gov/api/citations/20220014634/downloads/Final%20IEEE%20paper%20formatted%20footnote%20added.pdf). NASA 문서의 사실 수치를 쪽·표 위치와 함께 적었고 문서를 복제하지 않았다(NASA 콘텐츠는 미국에서 일반적으로 저작권 대상이 아니다. https://www.nasa.gov/nasa-brand-center/images-and-media/).

## 정직성: 이 값들이 말하지 않는 것

- **지면 마찰은 세 행성 모두 대용 값이다.** 출처들은 흙의 내부 마찰각(Mohr-Coulomb)을 재거나 추정한 것이지 부품이나 바퀴가 지면 위에서 미끄러지는 쿨롱 계수가 아니다. tan φ는 같은 흙끼리의 마찰이고, 바퀴와 흙 사이 마찰각(달 표 9.14의 φb)조차 Costes 외의 Surveyor 자료 기반 계획값이다. 그래서 지구·화성은 공칭도 `추정`이고, 달은 공칭만 `인용`이며 분포는 `추정`이다. 단단한 지면(콘크리트, 아스팔트)은 지구 값에 들어 있지 않다.
- **분포는 측정된 모집단이 아니다.** 서로 다른 현장·방법의 두 값을 끝값으로 잡은 uniform이다. 몬테카를로의 마찰 분포가 이 폭이라는 사실이 판정 카드의 가정표에 보여야 한다(J-04b). 평균과 표준편차를 주는 출처는 찾지 못했다.
- **화성 마찰은 학회 초록까지만 읽었다.** Sullivan 외 2011(JGR, doi:10.1029/2010JE003625)은 출판사가 자동 접근을 막아 읽지 못했다. 30~37° 범위는 2010 LPSC 초록(표 1과 본문)에서 확인했다. [확인 필요: 2011 논문 본문]
- 달 대기 밀도 0은 모델의 선택이다. 팩트시트의 수 밀도(2×10⁵ 개/cm³)를 입자 질량으로 환산하면 약 5×10⁻¹⁵ kg/m³(우리 계산이고 출처가 적은 값이 아니다)로 지구의 약 4×10⁻¹⁵배이며, 항력이 보이지 않는다.
- 일사는 대기 밖 값이다. 지구·화성의 지면 일사는 대기, 구름, 먼지로 줄고, 화성은 이심률(0.0935) 때문에 근일점과 원일점에서 490 ~ 713 W/m²로 달라진다(역제곱 환산, 우리 계산). 일사는 지금 판정에 쓰이지 않고 하늘·조명(W-02)의 입력으로 둔다.
- 중력 교차 확인: 화성 3.73(NSSDCA) 대 3.71(JPL 적도) 대 GM/R² 3.728, 달 1.62 대 GM/R² 1.624. 0.6% 안에서 일치한다.

## 교차 참조 (C-01c 이월)

`check_world_references(world, planets=..., materials=...)`: `World.planet`이 `planets`에 없거나 `terrain_props[].material`이 `materials`(프로젝트의 재료 ID, `DesignSpec.materials`)에 없으면 `ValueError`로 문제를 모두 나열한다. 재료가 `None`인 소품(행성 지면)은 재료가 필요 없다. `World`가 이것을 스스로 못 보는 이유는 `world.py` 머리말에 있다. 검증기(C-02c)가 이 함수를 부른다.
