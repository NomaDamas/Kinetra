# 에이전트 편집 도구 (G-02a)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/agent/`(`edit_tools.py`, `snapmath.py`), 테스트는 `packages/engine/tests/test_edit_tools.py`(`uv run pytest packages/engine -q -k edit_tools`).
- 근거: `docs/plan/studio-plan.md` 4.4절(에이전트와의 협업)과 위험 3("에이전트가 3D 편집을 망친다": 자유 좌표가 아닌 스냅 포인트 기반 명령), `docs/architecture/client-adapter.md` C1·C4, 이슈 #144.
- 범위 밖: 조회 도구(G-02b), 실행·판정 요청 도구(G-02c), 변경안과 재시도(G-03a), 권한 가드와 카탈로그 밖 표시(G-04), MCP 서버(G-08), UI.

## 규칙

- **도구 호출은 `Command`일 뿐이다.** 도구는 프로젝트를 고치지 않는다. `EditTools.run(project, tool, arguments)`는 호출을 `Command`(편집 하나 또는 `CommandBatch`)로 바꾸고 `kinetra_core.validate_command`(C-02c: 구조, 정책, 배치)에 넘긴다. 결과는 `ToolResult`: 받아들여지면 `command`와 새 `project`, 거부되면 `reasons`(검증기의 `Reason` 그대로: 코드, 문장, 타입이 있는 참조)다. 에이전트는 사유를 읽고 다시 시도한다(G-03a). `run`은 입력 프로젝트의 순수 함수다.
- **문서에 넣는 길은 `Hub.publish` 하나.** `HubEditTools(hub, project_id).call(tool, arguments)`는 문서의 현재 프로젝트로 호출을 만들고 `Publish`(`origin = agent`, 새 명령 id, 문서의 개정 번호)로 `Hub.publish`에 보낸다. 이력, 개정 번호, `applied` 방송, 문서 쪽 검증은 다른 클라이언트와 같다. 한 호출이 한 칸이라 되돌리기 한 번에 호출 전체가 돌아온다(`add_part`의 정의 추가·재료 추가·인스턴스·결합은 묶음 한 건).
- **위치는 좌표가 아니라 스냅 포인트다.** 부품은 자기 스냅 포인트와 이미 있는 부품의 스냅 포인트를 이름으로 대서 놓는다(`snap_to`), 이미 있는 두 부품은 `connect`로 잇는다. 포즈는 닫힌 식으로 계산한다(`snapmath.py`): 두 스냅 좌표계가 일치(`facing: aligned`)하거나 +Z가 서로 마주 보게(`opposed`) 놓고, 결합 축을 중심으로 90도의 정수 배(`roll_quarter_turns`)만 돌린다. 부품 포즈를 숫자로 받는 도구는 없다. 스냅 대상이 없는 유일한 예외는 지면이다: `on_ground`는 회전 없이 (x, y)에 부품의 가장 낮은 점이 z = 0에 닿게 놓는다(z는 형상에서 계산하고 호출이 줄 수 없다). **형상 레시피가 있는 부품에만 쓴다**: 그래야 검증기가 받침과 겹침을 검사할 수 있다. 형상이 없는 부품은 이유를 말하며 거부하고, 높이를 직접 주는 길은 없다(스냅 포인트로 형상이 있는 부품에 댄다). 회전 없는 배치는 S1에서 충분하다고 정했다.
- **배지.** 호출이 가져온 숫자(파라미터 값, 결합 한계·파단 임계, 스케줄 시각·명령)는 `declared`이고 `source.ref`는 호출의 `source`(사용자의 말이나 이유)나 기본 문장, `declared_by`는 "agent edit tools (G-02a)", `declared_at`은 호출 시각이다. 도구가 스냅 포인트에서 계산한 포즈는 닫힌 식 계산이라 `sim`이고 `source.ref`가 어느 두 스냅 포인트인지 적는다. 한 `Pose`는 배지 하나를 가지므로, 호출이 준 지면 위치 (x, y)가 든 `on_ground`의 포즈는 `declared`(호출의 `source`)이고 `source.ref`에 "z는 형상에서 계산"이라고 적는다. `resnap`은 엄격한 불리언이다(`"true"`, `1`은 거부). `cite`는 쓰지 않는다(도구는 문서를 인용하지 않는다).
- **스키마 위반은 만들기 전에 거부한다.** 인자는 `extra="forbid"`의 엄격한 모델이다. JSON이 아님, 모르는 도구, 모르는 필드, 빠진 필드, 숫자 자리의 문자열·불리언·NaN, id가 아닌 문자열, 범위 밖 `command`는 `invalid_command`이고 문제마다 사유 하나다. 검증기는 호출되지 않는다. 행성 상수와 판정을 실을 필드는 어떤 도구의 스키마에도 없다(테스트가 `PLANET_CONSTANT_NAMES`와 `VERDICT_FIELD_NAMES`를 스키마에서 찾는다).
- **정의는 라이브러리와 카탈로그에서만 온다.** `add_part`는 부품 id를 받는다. 프로젝트가 같은 id의 정의를 이미 담고 있으면 그것을, 아니면 `packages/engine/src/kinetra_engine/parts/library/<id>.json`의 정의를 같은 묶음에서 더한다. 재료는 프로젝트의 것이거나 `load_material_catalog`의 항목 그대로다. 호출이 부품이나 재료를 정의할 수 없으므로 카탈로그와 부품 정의는 이 도구들로 바뀌지 않는다.
- id를 생략하면 쓰이지 않은 첫 `<부품>-<n>`, `joint-<n>`, `actuator-<n>`, `step-<n>`이다.

## 도구

| 도구 | 만드는 명령 |
|---|---|
| `add_part` | `add_part_def`(필요하면), `add_material_def`(필요하면), `add_instance`, `add_joint`(스냅에 놓을 때) |
| `remove_part` | `remove_instance`(결합, 액추에이터, 스케줄 항목이 함께 지워진다) |
| `set_parameter`, `clear_parameter` | `set_parameter`/`clear_parameter`와, `resnap`(기본 켜짐)이면 맞물림을 지키는 `move_instance`들 |
| `set_material` | `set_instance_material`(카탈로그 재료면 `add_material_def` 먼저) |
| `connect` | (`move: assembly`면 둘째 부품과 거기 이어진 것들의 `move_instance`) + `add_joint` |
| `set_joint`, `remove_joint` | `replace_joint`, `remove_joint` |
| `add_actuator`, `remove_actuator` | `add_actuator`, `remove_actuator` |
| `schedule_command`, `change_command`, `remove_command` | `add_control_entry`, `replace_control_entry`, `remove_control_entry` |

`specs()`는 도구를 OpenAI 함수 도구 객체(`Gateway.chat`이 `tools`로 싣는 모양)로 낸다. 호출은 도구 이름과 모델의 `tool_calls`에 오는 JSON 인자 문자열이다. 이 모듈은 환경변수도 키도 읽지 않는다(키는 G-01의 것).

## 한계 (숨기지 않는다)

- 파라미터를 바꾸면 그 인스턴스를 자기가 매달린 결합(`b` 쪽)에 다시 맞추고(결합이 없으면 지면에 놓여 있던 경우 다시 지면에), 그 인스턴스에서 다른 결합으로 매달린 조립체를 같은 양만큼 옮긴다(스냅 포인트는 움직여도 방향은 안 바뀌므로 평행이동이다). 결합이 두 쪽에서 닫힌 고리는 옮기지 않고, 검증기가 어느 결합이 만나지 않는지 말하며 거부한다.
- `connect`는 둘째 부품의 조립체를 강체로 옮긴다. 이미 다른 결합으로 이어진 두 부품을 잇는 것(고리)은 거부한다.
- 스냅 좌표계의 방향이 어떤 쌍에서 서로 맞는지는 B-04a·B-04b의 규칙이다. 도구는 두 가지(`aligned`, `opposed`)와 90도 단위의 회전만 낸다. 다른 각도로 놓는 도구는 없다.
- 지면에 놓는 것은 형상이 있고 회전 없는 부품뿐이다(S1 결정). 눕히거나 세우려면 스냅 포인트로 다른 부품에 대서 놓는다.
- 스냅 방향의 `facing`은 B-04b가 호환 규칙을 정하면 그 규칙에서 고르게 바꾼다(#108에 남겼다).
- 검증기의 한계는 그대로다: 형상 레시피가 없는 부품은 겹침·뜸 검사에서 빠진다(`project-model.md` 검증기).
- 도구 스키마에 안전선(CB-07a)의 금지 범주 필드는 없다. 그 가드와 평가 세트는 CB-07a의 몫이다.
