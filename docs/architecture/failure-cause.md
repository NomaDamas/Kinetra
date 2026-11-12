# 실패 원인 분류기 (J-06)

- 상태: 구현됨. 분류기 `packages/judge/src/kinetra_judge/failure_cause.py`(`classify_failure_causes`), 실행 관측 `packages/engine/src/kinetra_engine/run/failure_observations.py`, 테스트 `packages/judge/tests/test_failure_cause.py`.
- 근거: 이슈 #458, `studio-plan.md` 4.6절과 16절 PC-02, J-02a(`goal-eval.md`), X-03a, X-04b, X-01c, X-08.
- 범위 밖: 자동 수정 제안, 화면 표시(J-04d), 인과 추론. 이 결과는 **1회 실행 기록이며 판정이 아니다**.

## 관측 사건과 원인의 경계

`PreviewRun`은 성공 조건과 무관하게 실제 public tick의 엔진 상태에서 `overturn`, `slip`, `torque_shortage`, `propellant_depleted`를 기록한다. 결합 해제는 기존 `break`와 `separation`을 그대로 쓴다. 이들은 모두 `frame.events`의 **관측 사건**이지 그 자체로 실패 원인이 아니다. 관측은 시뮬을 바꾸지 않으며, 결합 해제 뒤의 최종 모델·상태를 읽는다.

`classify_failure_causes(goal, started, frames, ended)`는 먼저 `check_run`과 J-02a `evaluate_goal`을 적용한다.

- `goal=None`, `met`, `undetermined`: `causes=()`, `unclassified=False`.
- `failed`: J-02a가 처음 실패로 확정한 `result.tick` **이하**의 사걸만 후보로 한다. 시간 한도 실패의 시점도 J-02a가 정한 값(한도 틱 또는 실행 끝)을 그대로 쓴다. 뒤의 사건은 실행 기록에 남지만 원인이 되지 않는다.
- 후보가 없으면 `unclassified=True`다. 없는 원인을 만들지 않는다. 여러 원인은 `(tick, kind, subject, related)` 순으로 모두 낸다.
- 결과의 `rule`은 "성공 조건 실패 시점 또는 그 이전의 임계 초과 관측"이라는 규칙과 "인과를 증명한 것이 아니다"를 함께 싣는다. `is_verdict=False`, `badge="sim"`이며 각 측정값·임계값도 `sim` 배지를 가진다. G-05는 이 구조화 데이터를 인용할 수 있다.

## 다섯 묶음과 판정식

| 원인 `kind` | 실행 관측과 원인 자격 | `measured` | `threshold` |
|---|---|---|---|
| `overturn` 전복 | **지면 접촉 중** 전체 질량중심의 XY 투영이 지지 접촉점 볼록 껍질 밖(부호 거리 `< 0 m`). 공중에서는 마지막 지면 지지 다각형에 대한 관측을 남기되 `grounded=False`라 원인에서 제외 | 부호 지지 여유 [m] | `0 m` |
| `slip` 슬립 | 접촉 쌍의 접선력 크기 합 `F_t > 0`이고 `F_t >= Σ μ_i F_n,i`. 쿨롱 솔버는 붙는 데 필요한 더 큰 힘 대신 원뿔 경계로 포화하므로 경계 도달과 수치 초과를 모두 기록 | 접선력 합 [N] | 마찰 한계 합 [N] |
| `torque_shortage` 토크 부족 | 명령의 영속도 요구 `abs(command) × T_stall`이 현재 회전 속도의 토크–속도 곡선과 공급 충족률을 적용한 가능 토크보다 큼 | 요구 토크 [N*m] | 가능 토크 [N*m] |
| `propellant_depleted` 추진제 고갈 | 추력 요구가 있는 스텝에 탱크 잔량 `0 kg`이고 공급 충족률 `< 1`(`unmet=True`). 요구를 모두 공급하고 스케줄 연소가 끝날 때 정확히 빈 경우도 사건으로 남기지만 `unmet=False`라 제외 | 요구 평균 추력 [N] | 공급 가능 평균 추력 [N] |
| `break` 파단 | `reason="over_threshold"`인 `break`만. 결합 ID(`subject`)를 쓰고 부품 ID로 바꾸지 않음 | 결합 하중 [N] | 결합 임계 [N] |

`separation`(`reason="intended_separation"`)은 스케줄이든 수동 입력이든 파단이 아니다. 정상 2단 분리 뒤 다른 결합에 `break`가 오면 그 결합만 분류한다.

### 임계 대비 여유 비율

넷(슬립·토크 부족·추진제 고갈·파단)은 요구가 0이 아닌 사걸만 원인으로 하므로 같은 식을 쓴다.

```text
margin_ratio = (threshold - measured) / abs(measured)
```

음수는 요구가 한계를 넘은 정도다. 예: 접선력 12 N과 한계 10 N은 `(10-12)/12 = -1/6`, 결합 하중 2 N과 임계 1 N은 `(1-2)/2 = -1/2`다. 추진제 고갈의 `details.remaining_kg`는 잔량 0을 별도로 보존한다.

전복은 0 임계로 나눌 수 없으므로 측정한 기하 길이로 정규화한다.

```text
L = max(지지 다각형 지름, 질량중심 투영–지지점 중심 거리)  [m]
margin_ratio = signed_support_margin / L
```

`details.reference_length_m`에 L을 싣는다. 지지 다각형·부호 거리는 X-03a와 같은 볼록 껍질·선분 거리 식을 쓰지만, 정적 저장 자세가 아니라 각 public tick의 실제 접촉점과 추진제 질량을 반영한 질량중심을 읽는다는 차이가 있다.

## 실행 원천과 한계

- 전복·슬립: MuJoCo 접촉 위치와 `mj_contactForce`, 컴파일된 접촉 마찰계수, 현재 강체 질량·자세. 지지 다각형은 지면 접촉만 만든다. 공중 관측의 다각형은 마지막 지면 지지이며 현재 접촉이라고 주장하지 않는다.
- 토크: `DriveRuntime.apply`가 실제로 쓴 명령·속도·공급 충족률의 `last_steps`. 요구 토크는 하중 추정이 아니라 명령의 영속도 요구라는 정의를 결과 `criterion`에도 쓴다.
- 추진제: `ThrustRun.begin_step`이 반환한 요구 추력·실제 추력·공급 충족률·탱크 잔량. 탱크 ID를 추정하지 않고 `ThrusterStep.supply`가 운다.
- 파단·분리: X-04b/X-08의 기존 이벤트를 다시 계산하지 않는다.
- 모든 판독은 1회 실행의 수치다. 이 목록은 사건 시간상 선행 관계를 좁혀 줄 뿐 물리적 인과 증명이나 몬테카를로 판정을 대신하지 않는다.

## 검증 장면

`uv run pytest packages/judge -q -k failure_cause`

고정 시드 458의 `PreviewRun` 여섯 장면은 전복(오버행), 슬립(강철 경사면), 토크 부족(모터), 추진제 고갈(저충전 탱크), 파단(낮은 결합 임계), 분류되지 않음(지지된 정지 블록)이다. 별도 닫힌 식 궤적에서 두 수계산, 성공·목표 없음·판단 불가, 공중 전복 관측, 정상 연소 종료, 실패 뒤 파단, 정상 2단 분리와 이후 다른 결합 파단을 검사한다.
