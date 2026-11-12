# 행성별 추력 대 중량비와 연소 시간 (X-07)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/statics/twr.py`(`thrust_to_weight`, `ThrustToWeight`, `weakest`), 테스트는 `packages/engine/tests/test_twr.py`. 확인: `uv run pytest packages/engine -q -k twr`.
- 근거: 이슈 #450, `docs/plan/studio-plan.md`의 정역학 행(PC-02로 더한 "행성별 추력 대 중량비·연소 시간", 모두 L0)과 X-07 행("결과 배지는 가장 약한 입력을 따른다"), `docs/research/benchmarks/kerbal-space-program.md` F6, `thrust.md`(X-01c: 탱크 추진제를 질량으로 싣는 규칙), `parts-thruster.md`(B-03c: `rated_thrust`, `propellant_flow`, 유량은 추력에 비례), `parts-battery-tank.md`(B-03d: 탱크 용량), `part-mass.md`(B-01a: `Derivation.input_badges`), `bodies.md`(W-01·W-03a: 중력은 `data/bodies`에서만), 핵심 가치 V1·V5.
- 범위 밖: 단별 델타-v, 궤도 계획, 대기압에 따른 추력 변화, 추력 방향과 추력중심(X-06), 화면 표시(B-14).

## 쓰는 법

```python
from kinetra_engine.statics import thrust_to_weight
r = thrust_to_weight(project.design)          # ThrustToWeight
r.mass, r.thrust, r.ratios, r.burns, r.reason, r.assumptions, r.grade, r.grade_label
```

결과는 L0 "해석 계산"(`grade = "L0"`, `grade_label = "해석 계산"`)이다. 닫힌 식이고 시뮬도 판정도 아니다(V1). 비가 1보다 커도 "뜬다"는 뜻으로 쓰지 않는다.

## 계산

- **추력 대 중량비** = 최대 추력 합 [N] ÷ (총질량 [kg] × 행성 중력 [m/s²]). 행성은 `BODY_IDS` 순서의 지구·화성·달 셋이고, 중력은 `load_body`가 읽은 데이터 파일의 `Quantity`(값·배지·출처)를 그대로 `PlanetRatio.gravity`에 싣는다. 코드에 중력 숫자가 없다(`test_bodies_no_gravity_literal_in_engine_or_client_code`). `bodies_directory`로 다른 디렉터리를 주면 그 파일의 값을 쓴다(테스트가 지구 중력을 두 배로 바꾼 파일로 비가 반이 되는 것을 본다).
- **추력기**는 설계의 추력기 액추에이터(`ActuatorKind.THRUSTER`, 인스턴스당 하나)다. 액추에이터가 없는 추력기 부품은 켜지지 않으므로 세지 않는다. 최대 추력은 명령 1에서 `thrust` 곡선의 최댓값이다(구간별 선형이라 점 하나다). 그것이 곡선의 끝(정상 추력)이면 `rated_thrust` 사양의 값과 배지이고, 곡선이 정상 추력 위로 솟으면 그 꼭대기 값과 곡선의 배지다.
- **총질량** = 인스턴스마다의 질량(`assembly_mass`, B-02: B-01a `mass_properties`, 탱크는 빈 질량) + 탱크 인스턴스마다의 용량(`tank_supply`, 인스턴스 파라미터에서). 추력기가 꺼내 쓰지 않는 탱크도 담은 만큼 무겁다(`thrust.md` 2번과 같다).
- **연소 시간** [s]은 추력기 액추에이터마다 = 그 탱크(`Actuator.supply`)가 가득일 때의 추진제 [kg] ÷ 그 탱크를 쓰는 모든 추력기의 최대 추력에서의 소모율 합 [kg/s]이다. 소모율은 `추력 × propellant_flow / rated_thrust`(B-03c)라서 정격 추력에서는 `propellant_flow` 그대로다. 한 탱크를 함께 쓰는 추력기는 같은 시간을 받고 `shared_with`에 서로의 ID가 있다.

## 값을 내지 않는 경우 (0이나 대체값을 넣지 않는다)

| `reason` | 뜻 | 결과 |
|---|---|---|
| `no_thruster` | 추력기 액추에이터가 없다 | `thrust`는 `None`, `ratios`와 `burns`는 비어 있다. 총질량은 낸다 |
| `no_propellant` | 추력기에 탱크가 없다(`supply`가 `None`, 계량하지 않음) | 그 추력기의 `burn_time`은 `None`. 추력 대 중량비는 낸다 |

소모율이 없는 경우는 생기지 않는다. `PartDef`가 추력기 부품에 양수 `propellant_flow`를 요구한다.

## 배지: 가장 약한 입력

값(`AnalyticValue`)마다 입력별 배지 목록(`InputBadges`)이 실려 오고, 값의 `badge`는 그 전부 가운데 가장 약한 것이다. 계산값이지만 `시뮬`을 붙이지 않는다. `시뮬` 하나로는 입력이 얼마나 좋은지 숨겨지기 때문이다.

| 값 | 입력 |
|---|---|
| 총질량 | `dry_mass`(인스턴스마다 B-01a `Derivation.input_badges`: 형상, 밀도, 파라미터. 선언한 질량은 `사용자 선언`), `propellant`(탱크 용량의 `Supply.input_badges`: 형상, 추진제 밀도, 파라미터) |
| 추력 대 중량비 | `gravity`(데이터 파일), `mass`(위의 둘을 합친 것), `thrust`(사양 또는 곡선) |
| 최대 추력 합 | `thrust` |
| 소모율 | `propellant_flow`(사양). 곡선이 솟을 때는 `thrust`도(곡선과 `rated_thrust`) |
| 연소 시간 | `propellant`, 그 탱크를 쓰는 추력기들의 `propellant_flow`(와 솟는 곡선의 `thrust`) |

**순서**(`BADGE_STRENGTH`, 강한 것부터, `Badge` 정의 순서와 같다): `인용` > `기본값` > `사용자 선언` > `추정`. 인용은 위치가 있는 출처에서 옮긴 값, 기본값은 우리가 이유를 적어 정한 값, 사용자 선언은 사용자의 말(결과는 그 선언만큼만 맞다), 추정은 근거가 약한 판단이다(`project-model.md` 배지 표). `시뮬`이 입력으로 오는 것은 부품이 계산값을 사양으로 적었을 때뿐이고, 그 입력이 보이지 않으므로 맨 앞에 둔다. 이 순서는 이 이슈가 정한 것이다 [제안].

테스트의 라이브러리 로켓(VACCO 48003040 + 기본 `tank`)에서 추력은 `인용`이지만 결과는 `추정`이다. VACCO의 외형이 `추정`(데이터시트에 치수가 없다)이라 건조 질량이 `추정`을 담기 때문이다. 추진제 밀도는 자리표시 `기본값`이라 연소 시간은 `기본값`이다. 선언한 8 kN 추력기(`schemas/examples/PartDef.thruster-declared-8kn.json`)로 바꾸면 추력·연소 시간·비가 모두 `사용자 선언`이다.

## 가정 (`ThrustToWeight.assumptions`, 숨기지 않는다)

1. 추진제 가득: 모든 탱크 인스턴스가 용량만큼 찼다. 시작 채움 `initial_fill`은 읽지 않는다(덜 채운 설계에서는 실제보다 무겁게, 연소 시간은 길게 나온다).
2. 최대 추력: 모든 추력기가 명령 1에서 곡선의 최댓값을 낸다. 스케줄은 읽지 않는다.
3. 대기에 따른 추력 변화 없음.
4. 평지의 균일 중력: 행성마다 `data/bodies`의 g 하나.
5. 모든 추력이 중력 반대쪽 한 선 위에 있다: 크기를 더한다. 방향과 추력중심은 보지 않는다(X-06).

## 수계산 대조 (테스트)

설계는 X-01c의 로켓이다(`test_thrust.py`의 `rocket`: 기본 크기 `tank`를 VACCO 위에 얹고 배기는 아래). 질량은 그 테스트가 MuJoCo `body_mass`와 1e-12로 맞춘 손계산이다: $m = m_\mathrm{tank} + m_\mathrm{thruster} + 용량$, 용량 $= 1000 \times \pi (0.057)^2 \times 0.194 = 1.98016$ kg, $F$ = 2.0 lbf = 8.896443230521 N, 유량 0.0267 lbm/s. 중력은 `bodies.md`의 9.80665, 3.73, 1.62 m/s²을 테스트에 적었다(데이터가 바뀌면 여기서도 실패한다).

| 테스트 | 손계산 | 허용 |
|---|---|---|
| `…matches_the_hand_calculation_on_each_planet[earth/mars/moon]` | $F / (m\,g_p)$, 세 행성 | 상대 1e-12 |
| `…mass_thrust_burn_time…` | 연소 시간 = 용량 ÷ 유량 = 163.50 s, $\mathrm{TWR}_p \cdot g_p$가 세 행성에서 같다 | 상대 1e-12 |
| `…two_thrusters_on_one_tank…` | 판 아래 둘: 추력 $2F$, 질량에 판과 추력기 둘, 연소 시간 = 용량 ÷ $2 \times$ 유량 | 상대 1e-12 |
| `…curve_peak_above_the_rated_thrust…` | 곡선이 $1.5F$로 솟으면 최대 추력 $1.5F$(곡선 배지), 유량 $1.5\times$, 연소 시간 = 용량 ÷ $1.5\times$ 유량 | 상대 1e-12 |

그 밖에: 추력기 없는 설계(`no_thruster`, 비 없음), 탱크 없는 추력기(`no_propellant`, 비는 있음), 배지 전파와 가장 약한 입력, 데이터 파일을 바꾸면 비가 바뀌는 것, 가정과 등급.
