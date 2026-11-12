# 추력기와 추진제 질량 (X-01c)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/compiler/thrust.py`(`compile_thrust`, `ThrustModel`, `ThrustRun`), 테스트는 `packages/engine/tests/test_thrust.py`. 확인: `uv run pytest packages/engine -q -k thrust`(B-03c의 `test_thruster.py`도 같이 돈다).
- 근거: 이슈 #125(DoD: 제어 스케줄에 따른 추력과 추진제 소모, 질량 변화의 처리 방식과 근거, 무중력 직선 가속의 수계산 대조), `parts-thruster.md`(B-03c: `Thruster`, `burn`), `parts-battery-tank.md`(B-03d: `Supply`, `tank_supply`, "질량 변화를 MJCF에 어떻게 반영할지는 X-01c의 결정"), `body-tree.md`(X-01a: 강체와 질량 합), `missing-definitions.md`(컴파일은 `require_complete`를 먼저 부른다).
- 범위 밖: MJCF를 저장 원본으로 쓰는 것(MJCF는 산출물이다). 실행 API와 스트림(X-02a), 행성 중력과 `<option>`(W-03a), 모터와 결합 액추에이터(X-01b), 부품 단위 오류 형식(X-01d), 추력기 여러 개의 추력중심(X-06), 행성별 추력 대 중량비(X-07).

## 쓰는 법

```python
from kinetra_engine.compiler import ThrustRun, compile_thrust, to_mjcf
model = compile_thrust(project)                       # require_complete(project, "compile") 다음 build_body_tree
mj_model = mujoco.MjModel.from_xml_string(to_mjcf(model.tree))
mj_data = mujoco.MjData(mj_model)
run = ThrustRun(model, mj_model, mj_data)             # 탱크의 추진제를 그 바디에 싣는다(mj_model을 고친다)
step = run.step()                                     # 추력, 추진제 소모, 질량 갱신, mj_step 한 번
```

`ThrustStep`은 그 단계의 시각과 간격, 추력기마다 `ThrusterStep`(충격량 [N·s], 평균 추력 [N], 꺼낸 추진제 [kg], `satisfied`), 탱크마다 남은 추진제 [kg]를 준다. 값은 모두 계산값이다(배지 `시뮬`). 입력의 배지는 부품(`thrust` 곡선, `rated_thrust`, `propellant_flow`, 탱크 파라미터)과 스케줄 항목에 그대로 있다.

## 추력은 제어 스케줄을 따른다

- 추력기 액추에이터(`Actuator.kind = thruster`)는 그 스케줄 항목 동안 켜진다. 명령 `c`(0~1)의 `[start, end)` 구간에서 힘은 `c × thrust(t − on)`이고 `on`은 밸브가 열린 시각이다(곡선의 시간 0, `parts-thruster.md`).
- **맞닿은 항목은 한 번 연 것이다.** 한 액추에이터의 앞 항목의 `end`가 다음 항목의 `start`와 같고 둘 다 명령이 0보다 크면 밸브는 열린 채이고 곡선의 상승이 다시 시작하지 않는다(명령만 바뀐다). 틈이 있거나 명령 0인 항목이 끼면 다음 항목에서 다시 열리고 상승을 다시 한다. 항목 밖의 추력은 0이다. 닫힘 과도는 없다(B-03c가 데이터시트에서 읽지 않았다).
- **한 단계의 충격량은 정확하다.** `[t, t + dt]`(`dt` = `mj_model.opt.timestep`)에서 각 추력기의 충격량은 구간별 선형 곡선의 적분이다(`burn`의 사다리꼴, 표본이 아니다). 항목 경계가 단계 가운데에 있어도 나눠 적분한다. 바디에는 그 충격량을 `dt`로 나눈 힘을 단계 내내 준다. 그래서 한 단계가 주는 운동량은 `dt`와 상관없이 곡선의 그 구간 충격량이다.
- **힘은 노즐에 작용한다.** 방향은 부품의 `nozzle` 스냅 포인트의 −Z(B-03c)를 단계 시작의 바디 자세로 돌린 것이고, 작용점은 노즐이다. `mj_data.xfrc_applied`에 그 힘과 바디 무게중심 둘레의 모멘트를 더하고, `mj_step` 뒤에 그 행을 원래 값으로 되돌린다(다른 쪽이 쓴 값을 지우지 않는다).
- **추진제는 추력에 비례해 꺼낸다**: `mdot = thrust × propellant_flow / rated_thrust`(B-03c). 같은 탱크(`Actuator.supply`)를 쓰는 추력기들은 함께 요청하고, 탱크가 모자라면 그 단계에서 모두 같은 비율 `Draw.satisfied`만큼의 충격량을 낸다(B-03d의 규칙). 탱크는 0 아래로 내려가지 않는다. `supply`가 없는 추력기는 계량하지 않는다(바닥나지 않는다).
- 추력기 액추에이터가 역할이 `thruster`가 아닌 부품에 달리면(역할 없는 부품은 `DesignSpec`이 받는다) 곡선이 없으므로 `CompileError`(인스턴스·부품 ID)다. 오류 형식의 완성은 X-01d다.

## 추진제 소모에 따른 질량 변화 (이슈 DoD의 결정과 근거)

**legacy를 확인했다.** `legacy-v0` 태그의 로켓 자동차(`packages/engine/src/kinetra_engine/templates/rocket_car.py`)는 모듈 설명에 "constant mass (fuel only accounted)"라고 적었고, 차량 질량을 바꾸지 않은 채 끝난 뒤 `fuel = impulse / (isp * G0)`로 추진제를 셌다(`git show legacy-v0:packages/engine/src/kinetra_engine/templates/rocket_car.py`). **이식하지 않았다.** 탱크의 추진제가 건조 질량과 비슷하거나 더 무거우면 속도가 질량비만큼 틀린다. 테스트의 기체(질량비 $m_0/m_1 = 2.41$)에서 고정 질량의 답 $J/m_0$은 로켓 방정식의 답보다 30 % 넘게 작다(`test_thrust_zero_gravity_straight_line_burn_to_empty_matches_the_rocket_equation`이 단언한다).

**근사.** 탱크의 추진제를 그 탱크가 속한 바디의 질량으로 싣고, 단계마다 컴파일된 모델의 `body_mass`, `body_ipos`, `body_inertia`, `body_iquat`를 그 자리에서 고친다(다시 컴파일하지 않는다. MuJoCo는 매 단계 이 값을 읽는다).

1. **추진제는 탱크 안쪽에 고르게 퍼져 있다.** 안쪽은 형상의 `subtract` 요소이고(B-03d가 용량을 같은 부피로 계산한다), 밀도는 `남은 양 / 안쪽 부피`다. 그래서 추진제의 무게중심은 안쪽의 도심이고 탱크가 비어도 **움직이지 않으며**, 그 둘레의 관성은 `남은 양 × 안쪽의 kg당 관성`이다. B-03d의 "균일 밀도, 슬로싱 없음"과 같은 가정이다.
2. **바디의 질량·무게중심·관성 = 건조 바디(X-01a의 `MassProperties` 합) + 그 바디에 있는 모든 탱크 인스턴스의 추진제**(평행축 정리, `math.fsum`). 추력기가 꺼내 쓰지 않는 탱크도 담은 만큼 무겁다. 관성 행렬을 `body_inertia`와 `body_iquat`로 바꾸는 것은 MuJoCo 자신의 `mju_eig3`이다(컴파일러가 `fullinertia`에 쓰는 것과 같다. 빈 탱크로 다시 쓰면 컴파일된 값이 나오는지 테스트가 본다).
3. **한 단계 동안 바디는 그 단계 소모 전후의 평균 추진제를 싣고**, `mj_step` 뒤에는 남은 양을 싣는다. 일정한 유량이면 한 단계의 속도 변화 $J/(m - \Delta m/2)$가 정확한 값 $(J/\Delta m)\ln(m/(m-\Delta m))$과 $\Delta m$의 2차까지 같다. 시작 질량을 쓰면 1차 오차가 남는다.
4. **질량이 바뀔 때 속도는 그대로다.** 추력이 배기가 가져가는 운동량을 이미 담고 있으므로 가변 질량의 운동방정식은 $m\,dv/dt = F$이고 속도는 연속이다.

`to_mjcf(model.tree)`만으로 쓴 MJCF는 건조 질량이다(X-01a). 시작 시점의 추진제는 `ThrustRun`이 첫 단계 전에 싣는다.

## 수계산 대조 (이슈 DoD)

부품은 라이브러리의 VACCO 48003040(정격 2.0 lbf = 8.896443230521 N, 유량 0.0267 lbm/s, 열림 7 ms, `인용`)과 기본 치수의 `tank`(`al6061-t6`, 추진제 밀도 1000 kg/m³ `기본값` 자리표시자, 용량 $1000 \times \pi (0.057)^2 \times 0.194 = 1.98016$ kg)다. 자세·스케줄·채움은 테스트가 정했다(`사용자 선언`). 중력은 0이고 MJCF에 바닥이 없다. 배기 속도 $v_e = F/\dot m = 734.6$ m/s.

로켓 방정식: 유량이 추력에 비례하므로 $m\,dv = F\,dt = -v_e\,dm$이고 $\Delta v = v_e \ln(m_0/m_1)$이다. **추력 곡선의 모양(7 ms 상승)과 상관없이** 성립한다.

| 테스트 | 설정 | 손계산 | 허용 |
|---|---|---|---|
| `…burn_to_empty_matches_the_rocket_equation` | 탱크 위에 추력기, 명령 1로 0~200 s, `dt` 0.01 s | $\Delta v = v_e \ln(m_0 / m_\mathrm{dry})$. 쓴 추진제 = 용량, 충격량 = $v_e \times$ 용량, 바닥나는 시각 $t = v_e \cdot 용량 / F + 0.0035$ s(163.5 s)가 `satisfied < 1`인 유일한 단계 안 | 상대 1e-8(관측 3e-10) |
| `…half_command_for_thirty_seconds…` | 명령 0.5로 0~30 s, `dt` 0.01과 0.002 s | $J = 0.5 F (30 - 0.0035)$, $m_\mathrm{used} = J/v_e$, $\Delta v = v_e\ln(m_0/(m_0 - m_\mathrm{used}))$, 30 s 뒤 소모 0 | 상대 1e-9(관측 3e-11, 1e-12) |
| `…two_thrusters_share_one_tank…` | 판 아래 ±0.1 m에 둘, 1/4 채운 탱크 하나 | 둘이 같이 비우므로 반의 시간, $\Delta v = v_e \ln(m_0/(m_0 - 0.25\cdot 용량))$, 회전 없음 | 상대 1e-8 |
| `…off_axis_thrust_turns_the_body` | 판 아래 +0.1 m에 하나, 계량 없음, 0.5 s | 모멘트의 y 성분 $-c_x F$가 바디에 고정되고 y가 주축이므로 $\omega_y = -c_x J / I_{yy}$ | 상대 1e-9 |

건조 질량은 손으로 쓴 껍데기 부피 × 2700 kg/m³와 데이터시트 무게 0.83 lbm이고 MuJoCo 모델의 `body_mass`와 1e-12로 맞는다. 모든 고정물은 결합한 스냅 포인트가 월드에서 만나고 바닥에 서 있다(`check_placement`가 아무것도 내지 않는다).

## 한계 (숨기지 않는다)

- **추진제가 탱크 안에서 움직이지 않는다.** 슬로싱, 가속에 따른 쏠림, 비어 가며 무게중심이 내려가는 것이 없다(1번 가정).
- **추력이 탱크 압력에 따라 줄지 않는다**(B-03c의 한계 그대로). 같은 이유로 탱크가 비기 직전까지 정상 추력이다.
- **MuJoCo가 컴파일할 때 구한 제약 가중치(`body_invweight0`, `dof_invweight0`)는 다시 구하지 않는다.** 이 값은 접촉과 한계의 부드러움 크기만 정한다. 질량이 크게 바뀐 바디의 접촉은 컴파일 시점의 질량에 맞춘 부드러움을 쓴다.
- **자유 관절의 선속도는 바디 좌표계 원점의 속도다.** 회전하는 바디의 무게중심이 그 좌표계에서 옮겨 가면(탱크가 축에서 떨어진 바디가 소모할 때) 무게중심 속도를 연속으로 잇는 작은 보정을 하지 않는다. 축 위의 탱크(테스트의 직선 가속)에는 영향이 없다.
- 단계 안에서 탱크가 바닥나면 그 단계 전체에 같은 비율 `satisfied`를 곱한다(바닥나는 순간에서 끊지 않는다). 충격량과 소모량의 합은 맞고, 힘이 그 단계 안에서 고르게 퍼진다.
- 바닥나는 시각은 손계산과 한 단계 안에서만 맞춘다.
- 안전선(`docs/process/review-rubric.md` 1번): 추력기는 행동하는 힘 하나와 그에 비례하는 질량 유량이다. 추진제 화학, 연소, 노즐 유동은 읽지도 쓰지도 않는다.
