# 결합부 임계 하중 (X-04a), 런타임 결합 해제 (X-04b), 시간 간격 불변 기준 (X-10)

- 상태: 구현됨. 임계: `packages/engine/src/kinetra_engine/break_threshold.py`(`critical_load`), 테스트 `packages/engine/tests/test_break_threshold.py`(`uv run pytest packages/engine -q -k break_threshold`). 런타임 해제: `packages/engine/src/kinetra_engine/compiler/breaks.py`와 `run/preview.py`, 테스트 `packages/engine/tests/test_break_runtime.py`(`uv run pytest packages/engine -q -k break_runtime`). 시간 창 평균과 시간 간격 민감 표시(X-10, #453): `packages/core/src/kinetra_core/break_window.py`, `compiler/breaks.py`(`BreakWatch`, `TimestepSensitivity`), 테스트 `packages/engine/tests/test_break_timestep.py`(`uv run pytest packages/engine -q -k break_timestep`), 측정 `docs/research/engine/break-timestep.md`.
- 근거: 이슈 #137, #138, `docs/plan/studio-plan.md` 4.6절("파단은 FEM이 아니라 결합부 임계값(물성 × 단면, '단순화 모델' 표시)"), `materials.md`(강도 기준 혼재), `project-model.md`(`Joint.break_threshold`), `client-adapter.md`(`break` 이벤트, F8), 핵심 가치 V1·V5.
- 범위 밖: FEM, 피로, 균열(이슈). 정지 하중과 임계의 비교(X-03b, 구현됨: [`static-load.md`](static-load.md)). `critical_load`는 하중을 받지 않고 임계만 낸다. 파단 표시는 X-04c.

## 하는 일

`critical_load(material, section, mode, shear_planes=1)`은 한 단면이 견디는 하중 [N]을 `CriticalLoad`로 돌려준다. `.quantity`는 `BreakThreshold`(단위 N, 값 > 0)이므로 그대로 `Joint.break_threshold`에 넣을 수 있다. 이 모듈은 결합의 어느 부분(핀, 볼트, 용접, 부재)이 지배하는지 고르지 않는다. **호출자가 지배하는 단면을 정한다.**

| 모드 | 식 | 출처와 위치 |
|---|---|---|
| `tension`(단면에 수직) | $P_{crit} = S\,A$ | Beer, Johnston, DeWolf, Mazurek, *Mechanics of Materials* 7판(McGraw-Hill, 2015), 1.2A절 "Axial Loading: Normal Stress", 식 (1.5) $\sigma = P/A$ |
| `shear`(단면 안쪽), 한 면 | $V_{crit} = 0.577\,S_y\,A$ | 같은 책 1.2B절 "Shearing Stress", 식 (1.9) $\tau_{ave} = P/A$. 0.577은 Budynas, Nisbett, *Shigley's Mechanical Engineering Design* 9판, 5-5절 "Distortion-Energy Theory for Ductile Materials", 식 (5-21) $S_{sy}=0.577\,S_y$ |
| `shear`, 두 면(`shear_planes=2`) | $V_{crit} = 2\cdot0.577\,S_y\,A$ | Beer 외 1.2B절, 식 (1.10) $\tau_{ave}=F/2A$. `A`는 **한 전단면**의 면적 |

단면 `A` [m²]: `SolidCircle`($\pi d^2/4$), `Rectangle`($w\,h$), `Annulus`($\pi(D^2-d^2)/4$), `DeclaredArea`(직접 준 면적). 치수는 `Quantity`(m, 배지 포함)이다.

강도 $S$는 B-07 카탈로그의 `Material.yield_strength`다. 다섯 재료의 값은 `materials.md` 표에 있다.

## 정직하게 말하는 것

1. **"단순화 모델"** — 모든 결과에 `model = "단순화 모델"`과 레이블이 붙고, `BreakThreshold.source.ref`에도 "단순화 모델 (not FEM)"과 식, 강도, 면적이 적힌다. 배지는 `추정`(`estimate`)이다. 인용한 식으로 계산했지만 이 값은 시험이나 시뮬레이션 결과가 아니다.
2. **강도의 기준이 섞여 있다.** 6061-T6, CFRP, POM은 대표값, A36과 Ti-6Al-4V는 규격 최소값이다(`materials.md`). 모듈은 카탈로그가 `source.ref`에 적은 `Basis: TYPICAL` / `Basis: specified MINIMUM`를 읽어 `strength_basis`와 레이블("강도 기준: 대표값(typical), 보증된 최소가 아님" 등)에 싣는다. 구조화된 필드가 없어서 문자열에서 읽는다(#481). 문구가 없으면 `unstated`라고 말한다. 값을 바꾸거나 보정하지 않는다.
3. **다른 재료의 임계를 비교할 수 없다.** 모든 결과가 "다른 재료의 임계와 비교할 수 없다" 레이블을 갖는다. 같은 단면에서 6061-T6가 A36보다 큰 임계를 내지만(테스트가 고정한다) 기준 차이이지 재료 순위가 아니다.
4. **CFRP는 항복이 아니라 파단 강도다.** 카탈로그의 `yield_strength`가 0° 인장 파단 강도 828 MPa(항복점 없음, #481)이므로 인장 임계에는 쓰되 "파단 강도" 레이블을 붙이고, **전단 모드는 거부한다**(0.577 비는 연성 금속의 항복 이론이라 취성·이방성 복합재에 적용하지 않는다; 이 재료의 전단 강도는 카탈로그에 없다). #481이 필드의 뜻을 정하면 이 읽는 방식을 맞춘다.
5. **가정과 한계**(`CriticalLoad.assumptions`): 단면 위 균일한 공칭 응력(구멍·나사·필릿의 응력 집중 없음), 굽힘·벌어짐·복합 하중 없음, 하중은 스칼라이며 결합의 자유축 방향과 대조하지 않는다, 항복 시작 하중이지 파열 하중이 아니다, 정적 강도만(피로·균열·크리프·온도·변형률 속도·부식 없음), 이방성 없음.

## 손계산 대조 (테스트)

| # | 입력 | 계산 | 값 |
|---|---|---|---|
| 1 | A36 핀 d = 10 mm, 한 면 전단 | $A=\pi(0.005)^2=7.854\times10^{-5}$ m², $V=0.577\times248.2\times10^{6}\times A$ | 11 247.8 N |
| 2 | 6061-T6 막대 20×5 mm, 인장 | $A=1.0\times10^{-4}$ m², $P=276\times10^{6}\times A$ | 27 600 N |
| 3 | Ti-6Al-4V 관 D8/d4 mm, 두 면 전단 | $A=\tfrac{\pi}{4}(0.008^2-0.004^2)=3.770\times10^{-5}$ m², $V=2\times0.577\times828\times10^{6}\times A$ | 36 021.95 N |

식 인용 위치는 위 두 책에서 열어 확인했다: Beer 7판 본문(Internet Archive 전문 텍스트)에서 1.2A·1.2B의 식 번호 (1.5), (1.9), (1.10)을, Shigley 9판(같은 곳)에서 식 (5-20), (5-21)을. 쪽 번호는 판본마다 달라 적지 않았다. 두 책은 교재라서 값을 옮기지 않고 식과 위치만 인용한다.

## 열린 질문

- 이방성(CFRP)과 취성 재료의 강도 필드의 뜻과 기준 혼재의 정리는 #481에서 정한다. 그 결정 전까지 이 모듈은 위 4·2번대로 읽는다.
- 호출 쪽(어느 결합에 어느 단면을 쓰는지)은 이 이슈 밖이다. X-03b·HW-03a가 정한다. X-04b는 저장된 `Joint.break_threshold`를 그대로 읽고 단면을 고르지 않는다. X-03b도 단면을 고르지 않고 결합에 이미 들어 있는 `break_threshold`를 정지 하중과 비교한다([`static-load.md`](static-load.md)).

## 런타임 결합 해제 (X-04b)

실행(`PreviewRun`) 도중 `break_threshold`가 있는 결합의 하중이 임계를 **넘으면**(`load > threshold`) 그 결합이 풀리고, 스트림에 `break` 이벤트(`tick`, `joint`, `load`, `threshold`, 모두 N)가 실린다.

- **컴파일.** 임계가 있는 `fixed` 결합은 두 인스턴스를 한 강체로 용접하지 않는다. 두 쪽은 처음부터 두 강체이고 트리에서 그 고정 결합으로 이어진다(MJCF에서는 관절 요소가 없는 자식 바디: MuJoCo가 부모에 단단히 붙여 둔다). 그래서 강체 목록은 실행 내내 같다(`client-adapter.md` F8: S1의 파단은 결합이 풀리는 것이고 강체 수는 그대로다). 임계가 없는 고정 결합은 전처럼 용접이다. 임계가 있는 고정 결합이 이미 용접된 두 인스턴스를 이으면 `welded_joint`, 고리를 닫으면 `loop` 컴파일 오류다(힌지·슬라이더와 같은 규칙).
- **하중.** 매 틱 `mj_step` 바로 뒤(추력·항력의 `xfrc_applied`와 그 스텝의 질량이 그대로일 때) `mj_rnePostConstraint`로 구한 자식 바디의 `cfrc_int`(부모에게서 받는 공간 힘)의 **힘 부분**이 그 스텝에 결합이 전한 힘이다. 결합이 붙든 부분 트리 전체에 전하는 힘으로, 축 방향(스프링·모터의 힘 포함)과 축에 수직인 성분을 모두 담는다. 토크는 비교하지 않는다(임계가 N이므로). 임계와 비교하는 **하중은 이 힘 벡터를 지난 0.02 s 창으로 평균한 크기**다(X-10, 아래 절).
- **해제.** 같은 틱에 넘은 결합을 결합 ID 순으로 모두 푼다. 트리에서 그 결합이 사라지고 붙들던 바디(그 아래 바디와 함께)는 자유 바디가 된다(`release`). 그 트리로 모델을 다시 컴파일하고 `carry_state`가 그 틱의 상태를 옮긴다: 두 모델에 다 있는 관절은 이름으로 좌표·속도·솔버 웜스타트를, 새 자유 관절은 그 바디 프레임의 월드 자세와 속도를. 모든 바디의 자세와 6차원 속도가 1e-12 안에서 같다(테스트). 풀린 결합의 스프링과 모터는 함께 사라진다(`Drives.without_joints`). 모터·탱크·프레임은 새 모델을 이름으로 다시 찾는다(`DriveRuntime.rebind`, `ThrustRun.rebind`). 궤적 해시는 해제 뒤 새 모델의 일반화 위치로 이어진다.
- **이벤트.** `break` 이벤트의 `tick`은 넘은 틱이고 그 틱 또는 다음 프레임이 싣는다(`previous.tick < event.tick <= frame.tick`). `load`는 그 틱의 창 평균 하중이다. 임계가 있는 결합이 하나라도 있으면 `run_started.model_labels`에 `BREAK_LABEL`("단순화 모델: 결합 파단은 결합을 지나는 힘을 고정된 시간 창으로 평균한 크기 [N]만 임계와 비교한다(토크, 피로, 균열, FEM 없음)")이 붙는다.
- **결정론.** 하중은 엔진 상태에서만 읽고, 푸는 순서는 결합 ID 순이며, 같은 트리는 같은 MJCF 바이트를 낸다. 같은 프로젝트를 두 번 돌리면 프레임·이벤트·궤적 해시가 같다(테스트).

### 시험 (`test_break_runtime.py`)

| 장면 | 임계 | 결과 |
|---|---|---|
| 두 블록 탑(달, 위 블록 4 kg), 정지 | 하중 = m g = 6.48 N(상대 1e-6) | 하중 읽기의 손계산 대조 |
| 같은 탑 | 0.9 m g / 1.5 m g | 풀림 / 유지. 접촉이 자리 잡는 처음 몇 틱은 한 스텝의 힘이 최대 1.17 m g(틱 2에서 측정)를 읽는다. 창 평균은 실행 시작 전의 힘을 0으로 세므로 처음 0.02 s 동안 m g까지 오른다 |
| 낙하 시험: 96 kg 받침에 힌지로 단 팔(수평에서 놓음), 끝(`weld-tip`)과 가운데(`weld-mid`)에 1 kg 블록(지구) | `weld-tip` 2 m g, `weld-mid` 6 m g, `pin` 걸린 무게의 10배 | `weld-tip`만 풀린다(틱 100). 해제 전 블록은 팔에 붙어 있고 뒤에는 떨어져 나간다. 해제가 없을 때 읽은 창 평균 하중의 최댓값: `weld-tip` 31.8 N(3.24 m g; 가벼운 진자의 바닥 장력 3 m g), 나머지는 유지 임계 아래 |
| 같은 낙하, `pin` 1.5배 | — | `pin`이 풀리고 팔과 두 블록이 한 덩어리로 날아가다 지면에 부딪혀 `weld-tip`, 몇 틱 뒤 `weld-mid`가 풀린다(끝 블록이 먼저 닿는다) |
| X-01b 기어모터 리그(지구, 배터리 `b1`을 붙든 `clip`), 0.1 s부터 지시 1 | `clip` 2 N(정지 시 배터리 무게 약 0.48 N, 풀리지 않게 하면 시동 뒤 창 평균 최대 4.45 N) | 모터 시동의 반작용으로 `clip`이 풀린다. 해제 틱 전후로 모터는 토크를 계속 쓰고 힌지 속도가 계속 오르며, 배터리는 초기화되지 않고(매 스텝 남은 에너지 + 쓴 에너지 = 처음 충전량, 남은 양은 오르지 않음) 항력은 새 모델의 모든 바디에 계속 걸린다 |
| X-01c 로켓(달, 탱크-추력기 용접 `w`), 0.1 s부터 점화 | `w` 6.5 N(정지 시 탱크 무게 4.9 N) | 점화로 `w`가 풀린다. 남은 추진제는 해제를 지나도 같은 비율로 계속 줄고, 새 모델의 탱크 바디 질량 − 남은 추진제 = 건조 질량이 매 스텝 같다(새 모델에도 추진제가 실림) |

시드: 미리보기 실행은 무작위를 쓰지 않는다(시드 0). MuJoCo 4.0.0, 시간 간격은 엔진 기본 0.002 s. 틱 번호와 31.8 N, 4.45 N, 1.17 m g는 macOS arm64 개발 머신에서 잰 값이다(값 배지 `시뮬`). 테스트는 이 값 자체가 아니라 풀리는 결합의 집합, 임계와의 대소, 같은 플랫폼에서의 비트 일치를 단언한다(H6). X-10에서 하중이 창 평균으로 바뀌어 `clip`의 임계(5 N → 2 N)와 `pin` 1.5배 낙하의 해제 순서를 고쳤다.

### 한계 (숨기지 않는다)

- 하중은 0.02 s 창의 평균 힘이다. 창보다 짧은 충격은 창에 펼쳐지므로 한 스텝의 순간 힘(약 2배, `break-timestep.md` 2.2절)보다 작게 읽는다. 시간 간격 불변은 아래 절의 측정 범위에서만 확인했다.
- 토크(굽힘)를 비교하지 않는다. 힌지·슬라이더의 축 방향 힘에는 그 결합의 스프링·모터 힘이 들어 있다.
- 풀린 뒤 두 쪽은 부모·자식이 아니므로 서로 충돌한다. 저장된 자세에서 두 쪽의 충돌 프록시가 겹쳐 있으면 해제 순간 접촉이 밀어낸다. 풀린 힌지의 모터는 더 이상 토크를 내지도 배터리를 쓰지도 않는다.
- 용접과 달리 임계가 있는 고정 결합의 두 쪽은 두 바디라서, MuJoCo가 부모·자식 사이만 충돌에서 빼므로 그런 결합이 사슬로 이어지면(A–B–C) A와 C는 풀리기 전에도 서로 충돌한다.
- 해제 이벤트의 사유("임계 초과", "의도한 분리")는 X-08이 더한다.

## 시간 간격 불변 기준 (X-10)

근거: 이슈 #453, `docs/research/benchmarks/kerbal-space-program.md` B1–B3, F7, 4.2절 ②, 7절 6번(PC-02). 측정: [`docs/research/engine/break-timestep.md`](../research/engine/break-timestep.md).

- **창 평균 하중.** `BreakWatch(tree, model, window_s)`는 매 스텝 결합의 힘 벡터를 쌓아 지난 `window_s` 초의 평균(창 안에서 전한 충격량 ÷ 창)의 크기를 하중으로 삼는다. 창이 시간 간격으로 나눠떨어지지 않으면 한 스텝을 더 걸치는 몫만큼 넣고, 실행 시작 전의 힘은 0이다. 해제 뒤 남은 결합은 창을 이어 간다. `BreakWatch.loads`가 마지막 스텝의 창 평균을 결합 ID별로 준다.
- **창 길이.** `kinetra_core.BREAK_LOAD_WINDOW`: 0.02 s, 배지 `기본값`(우리가 고른 값: 기본 접촉의 `solref` 시간 상수와 같다. 표준이나 측정에서 온 값이 아니다), `confidence` low, 읽기 전용. 임계가 있는 결합이 하나라도 있는 설계의 판정 가정표에 엔진 행으로 나온다(`verdict_assumption_table(table, body, design)`, `VerdictAssumptionTable.engine_rows`; 키 `break_load_window`는 프로젝트 가정표가 거부한다, `ENGINE_CONSTANT_NAMES`). 창은 허용하는 가장 큰 시간 간격 `MAX_TIMESTEP_S` = 0.002 s(MuJoCo 기본값)보다 길고, `BreakWatch`는 창이 시간 간격보다 길지 않으면 거부한다.
- **공개 틱과 고정 낮은 스텝.** `compile_project(..., timestep_s=)`는 실제 적분 dt를 받고, `PreviewRun(..., timestep_s=)`는 0보다 크고 0.002 s 이하의 공개 틱 Δ를 받는다. 임계가 있는 실행은 각 공개 틱을 실행 시작에 정한 16개의 같은 낮은 스텝으로 적분하고 실행 중 바꾸지 않는다. 따라서 0.002/0.001/0.0005 s 요청의 실제 적분 dt는 0.000125/0.0000625/0.00003125 s로 1:1/2:1/4를 유지한다. 임계가 없는 실행은 한 틱 한 스텝이다. 모터·추력 스케줄은 `(공개 틱 × 16 + 낮은 스텝) × h`의 같은 절대 시각으로 평가해 누적 `data.time`의 경계 오차를 피한다. 해제 뒤 모델도 같은 실제 dt로 컴파일한다. `platform.compute.timestep_s`가 실제 dt, `substeps_per_tick`이 고정 개수를 기록하고 둘의 곱은 공개 `run_started.timestep_s`다.
- **기준 장면.** 원래 낙하(`weld-tip` 19.6 N·`weld-mid` 58.8 N), 경사로 충돌(`seat` 49.0 N), 추력기 과하중(`w` 6.5 N)과 임계를 바꾸지 않는다. 공개 0.002/0.001/0.0005 s 요청은 위 실제 dt 비율을 유지하며, 풀린 결합 집합과 실제 `BreakEvent.load`의 10 % 이내 차이를 xfail 없이 검사하고 원래 세 장면에서 통과했다. 전체 틱 해제 시절의 45.9 %·19.8 % 실패와 현재 낮은 스텝 측정은 `break-timestep.md` 2절에 구분한다. 같은 장면·같은 설정의 반복 실행은 프레임과 궤적 해시가 같아야 하며 서로 다른 Δ/N의 해시 일치는 요구하지 않는다.
- **약한 증거 표시.** `TimestepSensitivity`가 측정이 기준을 지키지 못한 범위를 본다: 가장 무거운 바디 / 가장 가벼운 바디 > 4096(`MASS_RATIO_LIMIT`), 슬라이더 스프링의 $\omega\,\Delta t$ > 0.776(`SPRING_LIMIT`, $\omega=\sqrt{k/\mu}$, $\mu$는 두 쪽의 축약 질량), 바디 속도 > 512 m/s(`SPEED_LIMIT_M_S`). 스프링 비율은 실제 h가 아니라 공개 Δ를 써서 낮은 스텝 이전 측정 경계를 보수적으로 유지한다. 세 경계는 새 실제 h의 수렴 증거가 아니라 약한 증거 경고다. 셋 다 실행 시작과 풀릴 결합이 남아 있는 동안의 매 스텝에 그때의 모델(해제 뒤 다시 컴파일한 모델, 추진제가 줄어드는 질량 포함)에서 다시 본다. 또 `observe_breaks`가 실제 `break` 하중이 임계를 10 % 넘게(`BREAK_LOAD_SPREAD_LIMIT`) 초과했는지 본다. 비교한 모든 실행의 모든 파단이 이 안에 있으면 하중이 각 임계의 1.0~1.1배 사이이므로 상대 차이 10 %가 수학적으로 보장된다. 반대로 한 실행의 라벨이 없다는 사실만으로 다른 시간 간격과의 비교 통과가 보장되지는 않는다. 하나라도 걸리면 `run_ended.labels`에 "시간 간격 민감: 파단 결과가 약한 증거 (이유; docs/research/engine/break-timestep.md)"가 붙는다. 임계가 있는 결합이 없는 실행에는 붙지 않는다. 시험: 한 스텝짜리 100 N 충격(그 스텝의 힘은 임계 위, 창 평균 약 16.5 N)은 결합을 풀지 않고, 같은 힘이 이어지면 창 평균이 임계를 처음 넘는 6번째 스텝에 풀린다(`test_break_timestep_a_one_step_spike_...`). 해제 뒤 다시 컴파일한 모델이 범위 밖이면 실행 도중에 잡힌다(`test_break_timestep_out_of_range_after_a_recompile_is_caught_mid_run`).
- **보강은 질량이 있는 부품으로만.** 결합은 `fixed`, `hinge`, `slider` 셋뿐이고 두 인스턴스의 스냅 포인트 사이에만 있다. 질량 없는 보강 연결(KSP의 스트럿·오토스트럿)은 스키마에 없다. 빔(B-02a `beam`)으로 보강하면 컴파일된 총질량이 빔의 질량(기본 치수·6061-T6에서 0.7128 kg)만큼 는다(테스트).
- **CB-02.** 고속 충돌 스파이크 결과는 [확인 필요](CB-02 #312 미실행). CB-05b는 S2에서 이 창 평균을 다시 쓴다.
- **한계.** 경계 값은 측정한 장치에서 잰 값이고 그 안이라고 기준을 보장하지 않는다. 회전 결합의 스프링, 얇은 두 바디의 충돌(터널링)은 재지 않았다. 속도는 매 스텝 앞 상태의 `cvel`로 읽는다.
