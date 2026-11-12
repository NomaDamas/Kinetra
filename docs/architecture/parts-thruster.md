# 추력기 부품 (B-03c)

게임 수준의 일반 추력원이다. 추력 곡선, 방향, 추진제 소모율만 갖는다. 근거: 이슈 #103, `docs/process/add-part.md`, 안전선 `docs/process/review-rubric.md` 1번. 코드: `packages/core/src/kinetra_core/partdef.py`(`PartRole.THRUSTER`와 검사 `_check_thruster`), `packages/engine/src/kinetra_engine/parts/thruster.py`, 부품 정의 `parts/library/thruster-vacco-48003040.json`, 카탈로그 범위 `parts/thruster_catalog.json`, 테스트 `packages/engine/tests/test_thruster.py`. 확인: `uv run pytest packages/engine -q -k thruster`.

## 이 부품이 하는 것

`PartDef.role = "thruster"`인 부품은 정의 검증에서 다음을 갖춰야 한다(없으면 `PartDef`가 거절한다).

| 요소 | 이름 | 내용 |
|---|---|---|
| 곡선 | `thrust` | x = 명령이 켜진 뒤 시간 [s], y = 명령 1에서의 추력 [N]. 시간 0에서 시작, 음수 없음, 마지막 점은 양의 정상 추력 |
| 사양 | `rated_thrust` | 정상 추력 [N]. 곡선의 마지막 점과 같아야 한다 |
| 사양 | `propellant_flow` | 정상 추력에서의 추진제 질량 유량 [kg/s] |
| 사양(선택) | `opening_response` | 명령에서 정상 추력까지 걸리는 시간 [s]. 있으면 곡선이 처음 정상 추력에 닿는 시간과 같아야 한다(둘이 다른 상승을 말할 수 없다) |
| 스냅 포인트 | `nozzle` | 노즐 출구. 이 프레임의 +Z가 배기 방향이고 부품이 받는 힘은 -Z 쪽이다 |

`DesignSpec`은 추력기 액추에이터를 `thruster` 역할의 부품에만 단다(B-03b가 넣은 검사). 명령 `c`(스케줄 항목의 `command`, 0~1)는 곡선 전체를 `c`배 한다: 힘 = `c × thrust(t)`.

## 계산 (`kinetra_engine.parts`)

- `thruster_from_part(part)` → `Thruster`: 곡선, 정상 추력, 유량, 노즐 위치, 힘의 방향(부품 프레임의 단위 벡터).
- `Thruster.thrust(t, command)`, `.force(t, command)`, `.mass_flow(t, command)`. 곡선 구간 안은 선형 보간, 마지막 점 뒤는 마지막 값을 유지한다(연소는 표보다 길 수 있다), 시간 0 앞은 0이다. 명령이 [0, 1] 밖이면 `ThrusterError`.
- 추진제 소모는 추력에 비례한다: `mdot = thrust × propellant_flow / rated_thrust`. 그래서 유효 배기 속도 `rated_thrust / propellant_flow`와 비추력 `rated_thrust / (propellant_flow × g0)`가 부품마다 하나다.
- `burn(th, duration, command, propellant)` → `Burn`: 명령을 `duration` 동안 유지할 때의 충격량 [N·s]과 추진제 사용량 [kg]. **구간별 선형 곡선의 사다리꼴 적분이라 정확하다**(스텝 적분이 아니다). 추진제가 모자라면 그 시각에 멈추고(`depleted`), 남은 양보다 더 쓰지 않는다. 결과의 배지는 `sim`이다.
- 충격량 = 추력 × 시간: 정상 추력 `F`, 상승 시간 `T₀`이면 `J = F (T − T₀/2)`. `test_thruster_impulse_is_thrust_times_time_with_the_ramp_taken_out`가 손계산과 1e-12 상대 오차로 맞추고, `test_thruster_impulse_is_the_numerical_integral_of_the_thrust`가 중점법 수치 적분과, `test_thruster_impulse_equals_exhaust_velocity_times_propellant_used`가 `J = v_e · m_used`와 맞춘다.

추진제 질량이 줄어 차체 질량이 바뀌는 처리, 탱크에서 꺼내 쓰는 연결, MJCF 힘 적용은 이 잎이 하지 않는다. X-01c가 `Burn`의 적분으로 스케줄의 충격량을 구하고 `Supply`에서 추진제를 꺼내며 바디 질량을 고친다([`thrust.md`](thrust.md)).

## 카탈로그 밖 · 사용자 선언

`thruster_catalog.json`은 공개 데이터시트 둘에서 읽은 냉가스 추력기의 정격 추력 8개(Moog Form 500-1171 0121의 10 mN, 16 mN, 40 mN, 120 mN, 0.9 N, 3.6 N, VACCO의 5.0 N과 8.896 N)이고 모두 `인용`이며 쪽·표 위치와 URL이 있다. 이 값들의 최솟값~최댓값(0.01~8.896 N)이 "카탈로그 안"의 뜻이다. 구매 카탈로그가 아니다(가격·재고 없음).

`catalog_finding(part)`는 부품의 `rated_thrust`가 그 범위 안인지 알려 주고 배지에 붙일 문구(`label`)를 준다.

- 범위 밖이면 거절하지 않고 `카탈로그 밖 · <배지>`를 낸다. 예: 선언한 8 kN → `카탈로그 밖 · 사용자 선언`(`schemas/examples/PartDef.thruster-declared-8kn.json`). 판정은 선언만큼만 맞다.
- 범위 안이어도 배지는 자기 것이다. 선언한 3 N은 `사용자 선언`이지 `인용`이 아니다(`test_thruster_declared_value_inside_the_range_stays_declared`).
- 수식어를 그리는 쪽은 `ValueBadge`(D0-02d, `qualifier`)다. 이 계산은 문구만 낸다.
- 에이전트 경로(G-04, `kinetra_engine/agent/guard.py`)는 이 문구를 그대로 `ToolResult.out_of_catalog`에 싣고, 사용자가 확인하기 전에는 문서에 발행하지 않는다(`docs/architecture/agent-edit-tools.md`).

## 라이브러리 부품: VACCO 48003040 (`thruster-vacco-48003040`)

| 값 | 크기 | 배지 | 위치 |
|---|---|---|---|
| 추력 | 2.0 lbf = 8.896443230521 N | 인용 | 데이터시트 "Thrust @ 250 psia GN2 Inlet 2.0 lbf" |
| 유량 | 0.0267 lbm/s = 0.012110916279 kg/s | 인용 | "Flow 0.0267 lbm/sec GN2 @ 235 psia inlet". 추력은 250 psia, 유량은 235 psia에서 잰 값이라 조건이 다르다 |
| 질량 | 0.83 lbm = 0.37648166710 kg | 인용 | "Weight 0.83 lbm" |
| 열림·닫힘 응답 | 7 ms, 4 ms | 인용 | "Response" |
| 추력 곡선의 모양 | 0에서 정상 추력까지 7 ms 동안 선형 | **추정** | 데이터시트는 열림 시간만 주고 상승의 모양은 주지 않는다 |
| 외형 | 원통 셋(밸브 몸통, 목, 종) | **추정** | 데이터시트에 치수가 없다. 몸통 길이를 풀어 `steel-a36`로 데이터시트 질량이 나오게 했다 |

그 비추력은 2.0/0.0267 = 74.9 s이다. 단위 변환은 정의값(1 lbf = 4.4482216152605 N, 1 lbm = 0.45359237 kg)이다. 데이터시트가 말하지 않는 것은 쓰지 않았다: 입구 압력에 따른 추력 변화(그림만 있고 표가 없다), 닫힘 과도 응답.

한계(결과에 그대로 나온다): 냉가스 추력기의 일반 모델이다. 탱크 압력이 내려가며 추력이 줄어드는 것, 대기압에 따른 추력 변화, 연소, 노즐 유동, 열은 없다. 외형은 실물과 다르다(원통 셋, 모깎기 없음). 재료는 데이터시트의 CRES(내식강)가 아니라 카탈로그의 `steel-a36`이다.

## 안전선

추력기는 "행동하는 힘 하나"이다. 부품 정의에 추진제의 종류, 조성, 연소실, 노즐 유동 값이 없다. `test_thruster_part_has_no_propellant_chemistry_field`가 사양·곡선 이름에 그런 말이 없는지 검사한다. 쓰는 것은 질량 유량과 정상 추력뿐이고, 로켓 엔진 설계 자료는 없다. 선언한 8 kN 예시는 사용자가 정한 게임 수준의 숫자이고 실제 엔진을 뜻하지 않으며, 추진제 유량은 인용한 VACCO 부품의 비추력과 같게 선언해 비례시킨 값이다(그렇게 선언했다고 출처 문구에 적었다).

## 쓰지 않은 것

연소, 노즐 유동, 타이어 변형(이슈 범위 밖), 입구 압력·주변 압력에 따른 추력, 닫힘 과도, 추력 잡음(몬테카를로가 가정표에서 뽑는다), 추력기 여러 개의 합(X-06).
