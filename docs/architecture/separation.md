# 분리 이벤트 (X-08)

- 상태: 구현됨. 스케줄 항목은 `packages/core/src/kinetra_core/designspec.py`(`SeparateEntry`, `ScheduleEntry`, `ControlSchedule.separations`), 스트림 이벤트는 `packages/core/src/kinetra_core/frames.py`(`SeparationEvent`, `BreakEvent.reason`), 컴파일과 충격량은 `packages/engine/src/kinetra_engine/compiler/separation.py`, 실행은 `packages/engine/src/kinetra_engine/run/preview.py`(`PreviewRun`의 분리 단계와 `PreviewRun.separate`). 테스트 `packages/engine/tests/test_separation.py`(`uv run pytest packages/engine -q -k separation`).
- 근거: 이슈 #451, 계획 변경 PC-02(창업자 결정 2026-11-11, #422), `docs/plan/studio-plan.md` 4.6절("분리는 같은 결합 해제 경로를 스케줄로 부르는 것이다"), `docs/research/benchmarks/kerbal-space-program.md` A10 / 4.1절 / 7절 4번, 분리기 부품 [`part-separator.md`](part-separator.md)(B-15), 런타임 결합 해제 [`break-threshold.md`](break-threshold.md)(X-04b).
- 범위 밖: 화약·점화의 모델(안전선: 게임 수준의 선언 충격량만), 자동 단 배치, 낙하산, 탐색(CMA-ES)이 분리 시점을 찾는 것(J-01c), 분리 스케줄 편집 화면과 분리 표식(X-09), 조종 입력의 전송 메시지 `control`과 기록·재생(X-02c).

## 스케줄 항목

분리는 **제어 스케줄의 한 항목**이다. 별도의 순서 목록(스테이징)은 없다. `ControlSchedule.entries`는 `type`으로 갈리는 두 종류를 담는다.

| `type` | 필드 | 뜻 |
|---|---|---|
| `actuate` | `id`, `actuator`, `start`, `end` [s], `command` | 액추에이터 명령(X-01b, X-01c) |
| `separate` | `id`, `separator`(분리기 인스턴스 ID), `at` [s] | 그 시점에 분리기를 푼다 |

두 종류 모두 배지·출처 하나가 항목을 덮는다. `DesignSpec`은 `separator`가 있는 인스턴스인지, 그 부품의 역할이 `separator`인지 본다(아니면 `RefError`; 정의가 빠진 자리표시 인스턴스는 C-06 규칙대로 역할을 보지 않는다). 명령 `add_control_entry`·`replace_control_entry`가 두 종류를 다 싣는다. 분리기 인스턴스를 지우면(`remove_instance`) 그 분리 항목도 함께 지워지고 되돌리기가 되살린다.

**컴파일 오류(X-01d 형식).** 분리는 되돌릴 수 없으므로 분리기 하나에 분리 항목은 많아야 하나다. 분리기 ID 순, 그다음 시점 순으로 첫 문제를 낸다.

| 코드 | 언제 | 가리키는 ID |
|---|---|---|
| `separation_unjoined` | 분리 항목이 가리키는 분리기의 `face_b`에 이어진 결합이 없다(풀 결합이 없다) | 분리기 인스턴스, 부품 |
| `separation_conflict` | 한 분리기를 같은 시점에 푸는 항목이 둘 있다(모순된 스케줄) | 분리기와 `face_b` 쪽 인스턴스, 부품, `face_b` 결합 |
| `separation_twice` | 한 분리기를 나중에 다시 푸는 항목이 있다(이미 떨어진 것을 다시 풀 수 없다) | 같은 것 |

## 무엇이 떨어지는가

분리기(B-15)는 `face_a`와 `face_b`의 고정 결합으로 두 부품을 잡는다. 분리는 **`face_b`의 결합**을 푼다. 분리기는 `face_a` 쪽에 남는다. 그래서 분리 뒤에는 두 쪽이 있다: 분리기를 가진 쪽과 떨어져 나간 쪽. 로켓의 아래 단에 분리기를 남기려면 분리기를 뒤집어(`face_b`가 위) 놓는다(테스트의 `stages`).

- **컴파일.** `face_b`의 고정 결합은 용접하지 않는다(`bodytree._welds`). 두 쪽은 처음부터 두 강체이고 트리에서 그 결합으로 자유도 없이 이어진다. 임계가 있는 고정 결합(X-04b)과 같은 방식이라 강체 목록은 실행 내내 같다(`client-adapter.md` F8). `face_a`의 결합은 임계가 없으면 그대로 용접이다.
- **해제.** X-04b의 경로 그대로다: 트리에서 그 결합이 빠지고(`release`), 모델을 다시 컴파일하고, `carry_state`가 그 틱의 상태를 옮기고, 모터·탱크·항력·프레임이 새 모델을 이름으로 다시 찾는다.
- **분리된 쪽도 같은 월드에서 끝까지 시뮬된다.** 지우지 않는다. 모든 프레임에 두 쪽의 자세가 있고 리플레이(스트림 기록)에 남는다. 떨어져 나간 쪽의 추력기와 모터는 그쪽 액추에이터의 스케줄 항목대로 계속 작동한다.

## 충격량

해제 바로 뒤, 선언 분리 충격량 `J` [N·s](`separation_impulse`, 인스턴스 값 또는 부품 기본값)가 **한 순간에** 두 쪽에 들어간다.

- `face_a` 쪽(분리기의 강체)은 `J · n_a`, `face_b` 쪽은 `J · n_b`를 받는다. `n_a`, `n_b`는 두 면의 바깥 법선(`separator_from_part`의 `direction_a`, `direction_b`)을 지금 자세로 돌린 것이다. 두 법선이 반대이므로 크기가 같고 방향이 반대다.
- 두 충격량은 같은 점, `face_b`의 중심(지금 자세)에 들어간다. 그래서 선운동량과 각운동량이 모두 보존된다.
- 속도 변화는 강체 방정식의 정확한 해다: $\Delta \dot q = M^{-1} J_p^\top p$. MuJoCo의 `mj_applyFT`가 충격량을 일반화 좌표로 옮기고 지금 상태의 질량 행렬(`mj_crb`, `mj_factorM`, `mj_solveM`)이 푼다. 탱크가 그 순간 가진 추진제 질량이 실린 뒤다(`ThrustRun.rebind`).
- `J = 0`이면 결합만 풀리고 밀지 않는다.

손계산(테스트 `test_separation_in_zero_g_matches_the_momentum_hand_calculation`): 무중력에서 상자 `a`(2 kg) + 분리기(0.5 kg)와 상자 `b`(4 kg), `J` = 1 N·s. $v_a = J/(m_a + m_{sep}) = 0.4$ m/s, $v_b = -J/m_b = -0.25$ m/s, 총운동량 $2.5 \times 0.4 - 4 \times 0.25 = 0$. 실행의 매 틱 속도가 1e-9 안에서 맞는다. 이 장면은 행성 중력을 테스트 안에서 0으로 바꾸고(실행이 "미적용: … 중력" 라벨을 단다) 배치 허용 오차(1 µm) 안인 0.5 µm만큼 띄워서, 컴파일은 "땅 위"로 보되 무중력에서 아무것도 땅에 닿지 않게 했다.

## 실행에서의 시점

틱 `k`의 스텝(시각 `t = (k - 1) · timestep_s`에서 시작)을 하기 **전에**, `at <= t`인 아직 안 한 분리 항목을(시점, 분리기 ID 순) 그다음 수동 요청을 처리한다. 액추에이터 명령이 그 스텝부터 적용되는 것과 같은 순간이다. 시간 간격 0.002 s에서 `at` = 0.01 s는 틱 6이다.

- **수동 조종.** `PreviewRun.separate(separator)`는 다음 스텝의 처음에 같은 경로로 분리한다(이벤트의 `entry`는 `null`). 프레임을 읽는 사이에 부르면 마지막으로 읽은 프레임 바로 다음 스텝이다. `PreviewRun.separators`가 분리할 수 있는 분리기(그 `face_b`에 결합이 있는 것)다. 목록에 없는 인스턴스나 이미 분리했거나 요청한 분리기는 `ValueError`로 거부한다(되돌릴 수 없다). 같은 분리기의 스케줄 항목이 수동 분리 뒤에 오면 아무것도 하지 않는다. 키를 이 호출에 잇는 전송 메시지(`control`)와 입력의 기록·재생은 X-02c다.
- **이미 파단으로 풀린 결합.** `face_b`의 결합에 임계가 있어 분리 시점 전에 파단으로 풀렸으면, 분리 항목은 풀 것도 밀 것도 없으므로 이벤트를 내지 않는다.

## 스트림 이벤트와 사유

결합 해제 이벤트는 사유(`reason`)를 싣는다. 두 종류이고 둘 다 `reason`이 필수다.

| `kind` | `reason` | 뜻(표시) | 필드 |
|---|---|---|---|
| `break` | `over_threshold` | 임계 초과 | `tick`, `joint`, `load` [N], `threshold` [N] |
| `separation` | `intended_separation` | 의도한 분리 | `tick`, `separator`, `joint`, `entry`(스케줄 항목 ID 또는 `null`), `impulse` [N·s] |

**분리로 풀린 결합은 파단으로 기록되지 않는다**: `break` 이벤트가 나오지 않는다(테스트). 파단을 세는 쪽(J-06 실패 원인, J-02a "파단 없음" 조건)은 `kind == "break"`만 센다. 이벤트의 `tick`은 분리된 상태의 첫 틱이고, 그 틱 또는 다음 프레임이 싣는다(`previous.tick < event.tick <= frame.tick`). 이진 프레임에도 그대로 실린다. 분리기가 하나라도 결합을 잡고 있으면 `run_started.model_labels`에 `SEPARATION_LABEL`("단순화 모델: 의도한 분리는 선언 분리 충격량을 한 순간에 분리 면 중심에서 두 쪽에 크기가 같고 방향이 반대로 준다(밀어내는 시간 모양, 충격 하중, 에너지원 없음)")이 붙는다.

## 결정론

분리 시점은 스케줄과 틱 번호로만 정해지고, 해제는 X-04b와 같은 재컴파일(같은 트리는 같은 MJCF)이며, 충격량은 엔진 상태에서만 계산한다. 같은 프로젝트를 두 번 돌리면 프레임·이벤트·궤적 해시가 같다(테스트). 분리 시점이 바뀌면 해시가 바뀐다.

## 시험 (`test_separation.py`)

| 장면 | 확인하는 것 |
|---|---|
| 무중력, 상자-분리기-상자를 x축으로(위 손계산) | 분리 전 정지, 분리 뒤 $v_a$, $v_b$와 총운동량 0(1e-9), 이벤트 틱 6 |
| 같은 장면을 달에서 | 사유 `intended_separation`, `break` 없음, 이진 프레임 왕복, 라벨, 두 쪽이 끝까지 프레임에 있음, 반복 실행의 프레임·해시 동일, 시점이 다르면 해시가 다름 |
| 해제한 트리를 다시 컴파일 | 남은 쪽의 부분 트리 질량 2.5 kg과 무게중심 x = (2 × 0.12 + 0.5 × 0)/2.5 = 0.096 m, 떨어진 쪽 4 kg(1e-12) |
| 수동 요청을 틱 5 프레임 뒤에 | 스케줄 0.01 s와 같은 프레임, `entry` = `null`, 두 번째 요청 거부 |
| `J` = 0 | 결합만 풀리고 아무것도 움직이지 않음 |
| 달, 부스터 위에 뒤집힌 분리기, 위 단 지붕에 라이브러리 추력기(노즐 위) | 위 단이 떠나고(이벤트 틱 26), 0.1~0.15 s 분사로 위 단의 수직 속도가 분사 없는 실행보다 추력 충격량(`CompiledThruster.impulse`)/질량만큼 줄어든다(상대 1e-3) |
| 라이브러리 추력기 부스터–뒤집힌 분리기–탱크와 옆면 추력기로 이룬 위 단(#567) | 사용자 정의 상자 없이 `compile_project`를 통과하고, `face_b` 결합이 틱 6에 풀려 위 단이 위로 이동하며 두 쪽이 끝 프레임까지 남는다 |
| 모순 스케줄 | 같은 시점 두 항목 `separation_conflict`, 나중의 두 번째 `separation_twice`, `face_b`가 빈 분리기 `separation_unjoined` |

시드: 미리보기 실행은 무작위를 쓰지 않는다(시드 0). MuJoCo 4.0.0, 시간 간격은 엔진 기본 0.002 s. 수치는 모두 테스트가 정한 값(`사용자 선언`)과 그로부터의 손계산이다.

## 한계 (숨기지 않는다)

- 선언 충격량은 순간이다. 밀어내는 시간 모양, 충격 하중, 분리 기구의 질량 분포는 없다(B-15). 충격량이 무엇으로 만들어지는지는 모형 밖이고 화약·점화의 필드와 모델은 없다.
- 분리기는 늘 `face_a` 쪽에 남는다. 두 결합을 다 풀어 분리기를 세 번째 조각으로 내보내는 일은 없다.
- 분리 직후 두 쪽은 맞닿아 있고 부모·자식이 아니므로 서로 충돌한다. 충격량이 작거나 다른 힘(중력, 추력)이 둘을 다시 붙이면 접촉이 밀어낸다.
