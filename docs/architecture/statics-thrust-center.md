# 추력중심과 추력선 (X-06)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/statics/thrust_center.py`(`thrust_center`, `ThrustCenter`, `ThrusterForce`), 테스트는 `packages/engine/tests/test_thrust_center.py`. 확인: `uv run pytest packages/engine -q -k thrust_center`.
- 근거: 이슈 #449(PC-02, #422), `docs/research/benchmarks/kerbal-space-program.md` A8·A9(편집기의 추력중심은 스테이징과 상관없이 모든 엔진으로 계산해서 비행과 어긋난다), `thrust.md`(X-01c: 스케줄, 열림, 추진제 질량), `statics-tipover.md`(X-03a: 저장된 자세의 무게중심), `parts-thruster.md`(B-03c: 곡선, 정격 추력, 배지), `client-adapter.md`(파생값 L0), 핵심 가치 V1.
- 범위 밖: 양력중심, 분사 기둥이 이웃 물체를 미는 효과, 화면 표시(B-13), 행성별 추력 대 중량비(X-07).

## 쓰는 법

```python
from kinetra_engine.compiler import compile_thrust
from kinetra_engine.statics import thrust_center
r = thrust_center(compile_thrust(project), t=2.0)   # 스케줄이 있으면 t [s]가 필요하다. 없으면 t를 읽지 않는다
r.force, r.torque, r.center, r.direction, r.moment_arm, r.axial_torque, r.thrusters, r.input_badges
r.grade, r.grade_label, r.basis_note, r.propellant_note, r.assumptions
```

결과는 L0 해석 계산이다(`grade = "L0"`, `grade_label = "해석 계산"`). 시뮬도 판정도 아니다(V1). 좌표는 월드, 단위는 N, N·m, m, kg, s.

## 규칙

- **켜진 추력기만 센다.** 추력기 액추에이터에 명령이 0보다 큰 스케줄 항목이 하나라도 있으면 기준은 `schedule`이고 시점 `t`에 켜진 것만 더한다. 켜짐은 열림(`Opening`, X-01c: 맞닿은 항목은 한 번 연 것)의 `start <= t < end`이고 추력은 `명령 × thrust(t − on)`(부품 곡선, B-03c)이다. 모든 추력기를 한꺼번에 더한 값으로 대신하지 않는다(KSP A9의 어긋남을 하지 않는다).
- **스케줄이 없으면** 기준은 `max_thrust`이고 모든 추력기가 명령 1로 곡선의 가장 높은 값을 낸다. 결과의 `basis_note`가 "스케줄 없음: 모든 추력기 최대 추력 기준"이라고 말한다(B-13이 그대로 표시한다).
- **추진제와 무게중심은 X-01c의 처리 방식을 따른다.** 탱크의 추진제는 그 탱크가 속한 바디의 질량이고 탱크 안쪽에 고르게 퍼져 있다(`ThrustModel.mass_of`). 스케줄 기준에서 탱크는 시작 채움에서 0~`t` 동안 그 탱크를 쓰는 추력기들이 요청한 양(곡선의 정확한 적분 × `propellant_flow / rated_thrust`)을 뺀 만큼 담는다. 같은 탱크를 쓰는 추력기는 같은 비율로 함께 멈추므로(B-03d) 남은 양은 `max(0, 시작 − 요청)`이고, 바닥난 탱크의 추력기는 0을 내며 `tank_empty`로 표시된다. 스케줄이 없으면 소모를 반영하지 않고 `propellant_note`가 "추진제 가득 기준"(탱크마다 설계의 시작 채움량)이라고 말한다.
- **힘.** 모든 바디는 저장된 자세(결합 좌표 0)에 있다(X-03a와 같다). 추력기 하나의 힘은 노즐 점에서 노즐의 힘 방향으로 추력만큼이다(X-01c의 `CompiledThruster.position`, `.direction`). 합력 $F = \sum f_i$, 무게중심 $c$에 대한 토크 $\tau = \sum (p_i - c) \times f_i$.
- **추력선과 추력중심.** $F \ne 0$이면 힘들은 한 직선(렌치의 중심축) 위의 $F$와 그 직선 방향의 짝힘으로 줄어든다. 직선의 방향은 $F/|F|$, 추력중심 `center`는 그 직선에서 무게중심에 가장 가까운 점 $c + F \times \tau / |F|^2$, `moment_arm`은 그 거리, `axial_torque`는 $\tau$의 직선 방향 성분 $(\tau\cdot F)F/|F|^2$이다(힘이 한 평면에 있거나 평행하면 0). **합력이 0이면 짝힘**이고 `center`, `direction`, `moment_arm`, `axial_torque`는 없고 `torque`만 있다(`couple_only`). $|F| \le$ `ZERO_FORCE_RATIO`($10^{-12}$, 수치 선택: 저장된 쿼터니언으로 돌린 방향의 반올림이 $10^{-16}$ 정도) $\times \sum |f_i|$이면 0으로 본다.
- **입력 배지.** `ThrusterForce.badge`는 그 추력 숫자를 읽은 곳의 배지다. 곡선의 마지막 점부터(정상 구간, 그리고 곡선이 정격에서 가장 높은 최대 추력 기준)는 정격 추력(`PartDef`가 곡선 끝을 정격과 같게 한다)이므로 `rated_thrust` 사양의 배지(데이터시트 부품은 `인용`, 사용자가 정하면 `사용자 선언`)이고, 열림 상승 구간은 곡선의 배지다(라이브러리 부품의 상승 모양은 `추정`, `parts-thruster.md`). `input_badges`는 센 추력기들의 서로 다른 배지(`Badge` 순서)다.

## 가정 (`ThrustCenter.assumptions`, 숨기지 않는다)

1. 모든 결합은 저장된 자세(좌표 0)에 고정되고 추력 방향과 작용점도 그 자세의 값이다.
2. 추진제는 탱크 안쪽에 고르게 퍼져 있고 탱크 안에서 움직이지 않는다(X-01c).
3. 추력은 탱크 압력과 주변 압력에 따라 줄지 않는다(B-03c).
4. 추력만 더한다. 중력, 접촉, 모터 토크, 항력은 들어 있지 않다.

## 수계산 대조 (테스트)

부품과 자세는 `test_thrust.py`(X-01c)의 것이다: VACCO 48003040(정격 $F$ = 2.0 lbf = 8.896443230521 N, 유량 0.0267 lbm/s, 7 ms 선형 상승, `인용`/상승 모양 `추정`), 기본 치수의 `tank`, 0.3 × 0.1 × 0.01 m 판 아래 $x = \pm 0.1$ m의 추력기. 노즐이 모두 위나 아래를 향하므로 $(p-c)\times(0,0,f) = ((p-c)_y f, -(p-c)_x f, 0)$이고 무게중심은 $x, y$만 들어간다. 탱크·판·추력기는 각자 세로축에 대칭이라 $c_x = \sum m_i x_i / \sum m_i$.

| 테스트 | 설정 | 손계산 | 허용 |
|---|---|---|---|
| `…one_thruster_through_the_centre_of_mass` | 탱크 아래 축 위의 추력기, 명령 1, $t$ = 2 s | $F$ = (0, 0, $F$), $\tau$ = 0, 선은 $x = y = 0$, 남은 추진제 = 용량 − $F(2 - 0.0035)/v_e$. 상승 중간($t$ = 3.5 ms)은 $F/2$이고 배지 `추정` | 1e-12 |
| `…one_thruster_off_to_the_side` | 판 아래 $x$ = +0.1 하나, 명령 0.5, 탱크 계량, $t$ = 4 s | $m = m_0 - 0.5F(4-0.0035)/v_e$, $c_x = 0.1 M_\mathrm{thruster}/m$, $\tau_y = -(0.1 - c_x) F/2$, 추력중심 $x$ = 0.1, 팔 길이 $0.1 - c_x$ | 상대 1e-9 |
| `…two_symmetric_thrusters_and_only_the_ones_on` | $\pm 0.1$ 둘, 계량 없음 | 둘 다: $2F$, $\tau$ = 0, 선 $x$ = 0. `b`가 5 s부터면 $t$ = 1 s에 `a`만: $F$, $\tau_y = -0.1F$. $t$ = 5.0035 s: $1.5F$, $\tau_y = -0.1F + 0.05F$, 선 $x = 0.05F/1.5F$ | 1e-12 |
| `…opposed_pair_is_a_couple_with_no_center` | 판 아래 +0.1은 위로, 판 위 −0.1은 노즐을 위로 해서 아래로 | $F$ = 0, $\tau$ = (0, $-0.2F$, 0)(어느 점에 대해서든 같다), 추력중심 없음 | 1e-12 |

그 밖에: 스케줄 없는 설계는 최대 추력 기준·추진제 가득 기준 문구와 $2F$, 탱크가 바닥나는 시각($v_e \cdot$ 용량 $/F$ + 3.5 ms = 163.5 s) 뒤에는 추력 0과 `tank_empty`, 정격 추력과 곡선을 `사용자 선언`으로 바꾼 부품은 `사용자 선언` 배지, 스케줄이 있는데 `t`가 없거나 음수면 `ValueError`.

## 한계

- 저장된 자세 하나의 값이다. 실행 중 자세가 바뀌면 추력 방향과 무게중심이 달라진다(그것은 시뮬, X-01c·X-02a가 낸다).
- 바닥나는 탱크는 연속 시간으로 셌다. 시뮬(X-01c)은 바닥나는 단계 하나에서 같은 비율로 나누므로 그 단계 안에서만 다르다.
- 안전선(`docs/process/review-rubric.md` 1번): 게임 수준의 힘과 질량만 다룬다. 추진제 화학, 연소, 노즐 유동은 읽지도 쓰지도 않는다.
