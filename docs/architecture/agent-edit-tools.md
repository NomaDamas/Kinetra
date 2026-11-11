# 에이전트 편집 도구 (G-02a)와 권한 가드 (G-04)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/agent/`(`edit_tools.py`, `snapmath.py`, `guard.py`), 테스트는 `packages/engine/tests/test_edit_tools.py`(`uv run pytest packages/engine -q -k edit_tools`)와 `test_agent_guard.py`(`uv run pytest packages/engine -q -k guard`).
- 근거: `docs/plan/studio-plan.md` 4.4절(에이전트와의 협업)과 위험 3("에이전트가 3D 편집을 망친다": 자유 좌표가 아닌 스냅 포인트 기반 명령), `docs/architecture/client-adapter.md` C1·C4, 이슈 #144(G-02a), #151(G-04).
- 범위 밖: 조회 도구(G-02b), 실행·판정 요청 도구(G-02c), 변경안과 재시도(G-03a), MCP 서버(G-08), UI, 카탈로그 확장.

## 규칙

- **도구 호출은 `Command`일 뿐이다.** 도구는 프로젝트를 고치지 않는다. `EditTools.run(project, tool, arguments)`는 호출을 `Command`(편집 하나 또는 `CommandBatch`)로 바꾸고 `kinetra_core.validate_command`(C-02c: 구조, 정책, 배치)에 넘긴다. 결과는 `ToolResult`: 받아들여지면 `command`와 새 `project`, 거부되면 `reasons`(검증기의 `Reason` 그대로: 코드, 문장, 타입이 있는 참조)다. 에이전트는 사유를 읽고 다시 시도한다(G-03a). `run`은 입력 프로젝트의 순수 함수다.
- **문서에 넣는 길은 `Hub.publish` 하나.** `HubEditTools(hub, project_id).call(tool, arguments)`는 문서의 현재 프로젝트로 호출을 만들고 `Publish`(`origin = agent`, 새 명령 id, 문서의 개정 번호)로 `Hub.publish`에 보낸다. 이력, 개정 번호, `applied` 방송, 문서 쪽 검증은 다른 클라이언트와 같다. 한 호출이 한 칸이라 되돌리기 한 번에 호출 전체가 돌아온다(`add_part`의 정의 추가·재료 추가·인스턴스·결합은 묶음 한 건).
- **위치는 좌표가 아니라 스냅 포인트다.** 부품은 자기 스냅 포인트와 이미 있는 부품의 스냅 포인트를 이름으로 대서 놓는다(`snap_to`), 이미 있는 두 부품은 `connect`로 잇는다. 포즈는 닫힌 식으로 계산한다(`snapmath.py`): 두 스냅 좌표계가 일치(`facing: aligned`)하거나 +Z가 서로 마주 보게(`opposed`) 놓고, 결합 축을 중심으로 90도의 정수 배(`roll_quarter_turns`)만 돌린다. 부품 포즈를 숫자로 받는 도구는 없다. 스냅 대상이 없는 유일한 예외는 지면이다: `on_ground`는 회전 없이 (x, y)에 부품의 가장 낮은 점이 z = 0에 닿게 놓는다(z는 형상에서 계산하고 호출이 줄 수 없다). **형상 레시피가 있는 부품에만 쓴다**: 그래야 검증기가 받침과 겹침을 검사할 수 있다. 형상이 없는 부품은 이유를 말하며 거부하고, 높이를 직접 주는 길은 없다(스냅 포인트로 형상이 있는 부품에 댄다). 회전 없는 배치는 S1에서 충분하다고 정했다.
- **배지.** 호출이 가져온 숫자(파라미터 값, 결합 한계·파단 임계, 스케줄 시각·명령)는 `declared`이고 `source.ref`는 호출의 `source`(사용자의 말이나 이유)나 기본 문장, `declared_by`는 "agent edit tools (G-02a)", `declared_at`은 호출 시각이다. 도구가 스냅 포인트에서 계산한 포즈는 닫힌 식 계산이라 `sim`이고 `source.ref`가 어느 두 스냅 포인트인지 적는다. 한 `Pose`는 배지 하나를 가지므로, 호출이 준 지면 위치 (x, y)가 든 `on_ground`의 포즈는 `declared`(호출의 `source`)이고 `source.ref`에 "z는 형상에서 계산"이라고 적는다. `resnap`은 엄격한 불리언이다(`"true"`, `1`은 거부). `cite`는 쓰지 않는다(도구는 문서를 인용하지 않는다).
- **스키마 위반은 만들기 전에 거부한다.** 인자는 `extra="forbid"`의 엄격한 모델이다. JSON이 아님, 모르는 도구, 모르는 필드, 빠진 필드, 숫자 자리의 문자열·불리언·NaN, id가 아닌 문자열, 범위 밖 `command`는 `invalid_command`이고 문제마다 사유 하나다. 검증기는 호출되지 않는다. 행성 상수와 판정을 실을 필드는 어떤 도구의 스키마에도 없다(테스트가 `PLANET_CONSTANT_NAMES`와 `VERDICT_FIELD_NAMES`를 스키마에서 찾는다). 그런 시도는 스키마보다 먼저 권한 가드가 `forbidden`으로 거부한다(아래 G-04).
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

## 권한 가드 (G-04)

에이전트 경로(`EditTools.run`, 그리고 그것을 부르는 `HubEditTools.call`과 MCP 서버 G-08)로 행성 상수, 물성 DB(재료 카탈로그), 판정을 바꿀 수 없다. 보장은 구조다: 도구 스키마에 그런 필드가 없고(`extra="forbid"`), 도구가 만드는 명령은 닫힌 `Command` 합집합이며, `validate_command`(C-02c)가 카탈로그 재료를 다른 수치로 바꾸거나 카탈로그 출처를 다른 수치로 쓰는 명령을 출처(origin)와 상관없이 거부한다. `guard.py`가 더하는 것은 시도를 시도라고 말하는 것이다: 오타처럼 보이는 `invalid_command`가 아니라 `forbidden`과 이유를 돌려주어 에이전트가 말만 바꿔 다시 시도하지 않게 한다. 스키마 검사 전에, 검증기를 부르지 않고 거부하는 것:

| 시도 | 예 |
|---|---|
| 없는 도구인데 이름이 행성 상수, 카탈로그, 판정, 재료, 재료 물성을 가리킴(`guard_tool`) | `set_gravity`, `edit_material_catalog`, `set_verdict`, `write_p_success`, `set_density`, `add_material` |
| 어느 깊이든 키가 행성 상수(`PLANET_CONSTANT_NAMES`), 판정 필드(`VERDICT_FIELD_NAMES`), 재료 물성(`density`, `yield_strength`, `elastic_modulus`, `friction`)이거나, 여러 단어로 된 그 이름을 포함하거나, `FORBIDDEN_WORDS`의 단어를 가짐(`guard_arguments`) | `gravity`, `place.joint.P_Success`, `surfaceGravity`, `parameters.g`, `catalog_entry` |
| id 자리에 정의: `part`나 `material`이 객체나 목록 | `{"part": {"id": "mine", ...}}` |
| 사용자를 대신 말하는 키: `origin`, `badge`, confirm/confirmed/confirmation이 든 키 | `{"origin": "mouse"}`, `{"badge": "cite"}`, `{"userConfirmation": "yes"}` |

이름은 camelCase를 쪼개고 영숫자가 아닌 글자를 `_`로 바꾸고 소문자로 맞춘 뒤 비교한다. 한 단어 이름이 긴 키 안에 든 것은 잡지 않는다(탱크의 `propellant_density`는 재료의 `density`가 아니다). 도구 필드와 라이브러리 부품의 파라미터 이름은 가드에 걸리지 않는다(테스트가 확인한다). 값은 읽지 않는다: `source` 문장은 사용자의 말이다.

## 카탈로그 밖 표시와 사용자 확인 (G-04)

카탈로그는 이미 있는 것만 쓰고 표시 문구도 이미 있는 것을 쓴다. 받아들여진 호출의 `ToolResult.out_of_catalog`는 그 호출이 새로 들인 `OutOfCatalog` 목록이다(호출 뒤 프로젝트의 발견에서 호출 전 프로젝트의 발견을 뺀 것). 발견은 그 정의를 쓰는 인스턴스마다 하나라서, 카탈로그 밖 부품의 둘째 인스턴스를 더하면 다시 나오고, 이미 있던 인스턴스를 고치는 호출에서는 나오지 않는다.

| 종류(`kind`) | 무엇 | 카탈로그 | 문구(`label`) |
|---|---|---|---|
| `thrust` | 추력기의 `rated_thrust`가 인용 범위(0.01~8.896 N) 밖 | B-03c `thruster_catalog.json`, `catalog_finding` | `catalog_finding(part).label` 그대로. 선언한 8 kN이면 `카탈로그 밖 · 사용자 선언` |
| `differs` | 프로젝트가 담은 부품·재료 정의가 같은 id의 카탈로그 정의와 다름 | 부품 라이브러리, 재료 카탈로그(C-06 `catalog_differences`) | `카탈로그와 다름`, 문장은 `CatalogDifference.message` |
| `spec` | 부품 라이브러리에 없는 부품의 사양(추력기의 정격 추력은 위 범위로 판단) | 부품 라이브러리 | `카탈로그 밖 · <그 사양의 배지>` |
| `material` | 재료 카탈로그에 없는 재료의 물성 넷 | 재료 카탈로그(B-07) | `카탈로그 밖 · <그 물성의 배지>`(예: 기본값이면 `카탈로그 밖 · 기본값`) |

`HubEditTools.call(tool, arguments, *, confirmed=())`는 발견이 있는 호출을 그 발견이 모두 `confirmed`에 있을 때만 발행한다. 아니면 아무것도 발행하지 않고 `ok=False`, `needs_confirmation=True`, `out_of_catalog`, 적용할 `command`와 그 뒤 `project`(미리보기용)를 돌려준다. 사용자가 문구를 보고 확인하면 같은 호출을 `confirmed=result.out_of_catalog`로 다시 부른다. `confirmed`는 메서드의 키워드 인자이고 호출 인자가 아니어서 모델이 스스로 확인할 수 없다(그런 키는 가드가 거부한다). 다른 호출의 확인(다른 인스턴스의 발견)은 넘어오지 않는다. 부품의 파라미터 범위를 넘는 값은 표시하지 않고 검증기가 거절한다(DoD의 "거절하거나").

우회 시도 테스트 다섯 종(`test_guard_bypass_1`~`5`): 금지된 이름의 도구, 실제 도구에 숨긴 행성 상수·판정 키, 재료 카탈로그 변경(도구로, 그리고 `origin = agent`로 직접 보낸 명령으로), 지어낸 부품, 사용자를 대신한 확인·출처·배지. 각각 순수 도구와 `Hub` 양쪽에서 거부되고 개정 번호, 프로젝트, 판정 상태, 카탈로그가 그대로인지 본다.

## 한계 (숨기지 않는다)

- 파라미터를 바꾸면 그 인스턴스를 자기가 매달린 결합(`b` 쪽)에 다시 맞추고(결합이 없으면 지면에 놓여 있던 경우 다시 지면에), 그 인스턴스에서 다른 결합으로 매달린 조립체를 같은 양만큼 옮긴다(스냅 포인트는 움직여도 방향은 안 바뀌므로 평행이동이다). 결합이 두 쪽에서 닫힌 고리는 옮기지 않고, 검증기가 어느 결합이 만나지 않는지 말하며 거부한다.
- `connect`는 둘째 부품의 조립체를 강체로 옮긴다. 이미 다른 결합으로 이어진 두 부품을 잇는 것(고리)은 거부한다.
- 스냅 좌표계의 방향이 어떤 쌍에서 서로 맞는지는 B-04a·B-04b의 규칙이다. 도구는 두 가지(`aligned`, `opposed`)와 90도 단위의 회전만 낸다. 다른 각도로 놓는 도구는 없다.
- 지면에 놓는 것은 형상이 있고 회전 없는 부품뿐이다(S1 결정). 눕히거나 세우려면 스냅 포인트로 다른 부품에 대서 놓는다.
- 스냅 방향의 `facing`은 B-04b가 호환 규칙을 정하면 그 규칙에서 고르게 바꾼다(#108에 남겼다).
- 검증기의 한계는 그대로다: 형상 레시피가 없는 부품은 겹침·뜸 검사에서 빠진다(`project-model.md` 검증기).
- 도구 스키마에 안전선(CB-07a)의 금지 범주 필드는 없다. 그 가드와 평가 세트는 CB-07a의 몫이다.
- (G-04) 가드와 카탈로그 밖 확인은 도구 경로의 것이다. 도구를 거치지 않고 `Hub.publish`에 직접 보낸 명령은 출처가 `agent`여도 검증기(C-02c)만 거친다: 행성 상수·판정·카탈로그 재료 변경은 거기서도 `forbidden`이지만, 사용자가 쓰는 길인 `add_part_def`·`replace_part_def`는 출처로 막지 않는다(검증기는 출처를 받지 않는다). 그래서 에이전트와 MCP 서버(G-08)는 `HubEditTools`로만 문서를 고친다.
- (G-04) 카탈로그 범위가 정의된 사양은 추력기의 정격 추력뿐이다(B-03c). 라이브러리에 있는 다른 부품의 사양은 라이브러리 자체가 카탈로그이고, 라이브러리에 없는 부품은 사양마다 `카탈로그 밖 · <배지>`로 표시한다. 카탈로그 확장은 이 이슈의 범위 밖이다.
