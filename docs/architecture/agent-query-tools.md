# 에이전트 조회 도구 (G-02b)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/agent/query_tools.py`, 테스트는 `packages/engine/tests/test_query_tools.py`와 실제 실행 기록을 대조하는 `test_run_tools.py`(`uv run pytest packages/engine -q -k 'query_tools or run_tools'`).
- 근거: `docs/plan/studio-plan.md` 4.4절(에이전트와의 협업, "롤아웃 수치만 인용한 실패 설명"), 이슈 #145(G-02b). 읽는 코어 계산은 B-02 질량([`part-mass.md`](part-mass.md), `assembly_mass`), X-01a 바디 트리([`body-tree.md`](body-tree.md)), X-01c 추진제([`thrust.md`](thrust.md)), X-03a 정역학([`statics-tipover.md`](statics-tipover.md)), X-02a 실행 스트림([`client-adapter.md`](client-adapter.md) 3.3).
- 범위 밖: UI. 편집 도구(G-02a, [`agent-edit-tools.md`](agent-edit-tools.md)), 실행·판정 요청 도구의 동작(G-02c), 실패 설명(G-05, [`agent-explain.md`](agent-explain.md): 이 도구의 수치만 인용한다). MCP 노출과 실제 실행 기록 연결은 #558에서 [`mcp-server.md`](mcp-server.md)와 [`agent-edit-tools.md`](agent-edit-tools.md)에 함께 기록한다.

## 쓰는 법

```python
from kinetra_engine.agent import QueryTools, HubQueryTools
tools = QueryTools()
r = tools.run(project, "mass_properties", "{}")      # QueryResult: ok, tool, summary, data(수치) 또는 reasons
tools.record(started, frames, ended)                 # 끝난 실행 스트림 전체의 요약을 run_id로 보관
tools.run(project, "rollout_summary", {"run_id": "run-1"})
HubQueryTools(hub, "desk").call("statics_check", {}) # Hub 문서의 현재 프로젝트를 읽는다. 발행하지 않는다
```

`query_specs()`는 도구를 `edit_tools.specs()`와 같은 OpenAI 함수 도구 객체로 낸다. `QueryResult.to_json()`이 모델에 돌아가는 내용이다.

## 규칙

- **읽기만 한다.** 조회는 `Command`를 만들지 않고 발행하지 않는다. `run`은 받은 프로젝트를 읽고, `HubQueryTools.call`은 문서의 현재 프로젝트를 읽는다. 개정 번호, 이력, 구독자는 조회를 보지 않는다(테스트). 인자 중 값을 쓸 수 있는 것은 없다: 인자는 `rollout_summary`의 `run_id` 하나뿐이다.
- **코어가 계산하고 도구는 옮긴다.** 모든 수치는 코어 함수가 낸 값을 반올림 없이 옮긴 것이다. 이 모듈은 아무것도 추정하지 않는다. 코어가 수치를 못 내면 코어의 사유로 거부한다: 빠진 정의는 C-06의 `missing_definition`, 컴파일되지 않는 설계는 실행 요청과 같은 사유(`protocol.server.compile_reason`, 채널의 `run`·G-02c `request_run`과 같은 함수: `CompileErrorCode`로 시작하는 문장, `snap_mismatch`·`floating`은 검증기의 `invalid_snap`·`floating`, 나머지는 `invalid_project`), 지면을 파고든 설계의 정역학은 `overlap`.
- **배지가 수치와 함께 간다.** 프로젝트가 가진 값(파라미터, 포즈, 스케줄)은 자기 배지를 그대로 갖는다. 코어가 계산한 값은 `sim`이고 `computed_by`가 어느 계산인지, `input_badges`가 무엇에서 계산했는지의 배지를 적는다(`massprops.py`의 규칙). 정역학은 X-07(`twr.py`)처럼 입력별 배지 행 `inputs`(`mass`: 인스턴스마다 B-01a `Derivation.input_badges`, 질량과 충돌 프록시가 같은 형상·밀도·파라미터에서 나온다; `pose`: 저장된 포즈의 배지; `gravity`: `data/bodies`의 배지, 검사에는 방향만 들어간다)를 싣고 `badge`는 그중 가장 약한 것(`weakest`, `BADGE_STRENGTH` 순)이다. 계산값이 가장 약한 입력보다 나을 수 없기 때문이다.
- **판정이 아니다(V1).** 정역학은 L0 해석 계산이고 `label`(`STATICS_LABEL`)과 X-03a의 가정이 결과에 실린다. 실행 요약은 실행 하나의 기록이고 모든 요약에 `notice` = `ROLLOUT_NOTICE`("1회 실행. 판정이 아닙니다", F6)가 있다. 판정처럼 읽히는 필드는 없다.
- **호출 검사는 편집 도구와 같다(G-02a, G-04).** 인자는 JSON 객체, 스키마는 `extra="forbid"`. 모르는 도구·필드, JSON이 아님, 객체가 아님, id가 아닌 `run_id`는 `invalid_command`. 행성 상수·판정·재료 물성을 가리키는 도구 이름(`set_gravity`)이나 키(`gravity`, `density`, `p_success`)는 스키마보다 먼저 권한 가드가 `forbidden`으로 거부한다.

## 도구

| 도구 | 코어 계산 | 내는 것 |
|---|---|---|
| `list_parts` | 프로젝트 그대로(컴파일 없음) | 행성; 인스턴스마다 부품, 부품 이름·역할, 재료, 파라미터(값·단위·배지), 포즈(위치 m, 쿼터니언, 배지), 스냅 포인트 id; 결합(종류, 양쪽 스냅, 한계, 파단 임계); 액추에이터; 제어 스케줄(항목마다 `type`: `actuate`는 시작·끝 s, 명령, 배지; `separate`는 분리기와 시점 s, 배지, X-08). 정의가 빠진 인스턴스는 `missing_definition`(`part`/`material`)이고 스냅 포인트를 지어내지 않는다 |
| `mass_properties` | `compile_thrust`의 바디 트리(인스턴스마다 B-02 `mass_properties`를 저장된 포즈에 놓은 것)와 탱크의 `Supply` | 인스턴스마다 질량 kg와 월드 무게중심 m, 입력 배지; `dry`(건조 질량과 무게중심, `math.fsum`); `propellant`(탱크마다 실행 시작 때 든 양 `Supply.remaining`과 용량); `with_propellant`(추진제를 탱크 안쪽 중심 `PropellantStore.centroid`에 더한 질량과 무게중심) |
| `statics_check` | X-03a `tipover`(같은 바디 트리) | 입력별 배지 `inputs`와 가장 약한 배지 `badge`, 질량, 무게중심, 투영점, 높이, 받침 종류(`none`/`point`/`segment`/`polygon`), 받침점 수, 지지 다각형 꼭짓점(인스턴스·geom·좌표), 변마다 거리와 각(rad, deg), 여유 m, 전복각(rad, deg), `stable`, 근사와 가정 |
| `rollout_summary` | `summarize_rollout`: 기록된 실행 스트림(`run_started`, 프레임, `run_ended`) | 실행 id·종류·개정·정의 해시·행성·시드·시간 간격·프레임 간격, 프레임 수, 끝 틱과 시각, 종료 사유, 궤적 증거 `trajectory`(해시와 플랫폼 태그 한 객체, `run_ended.end.trajectory` 그대로: H1, 태그 없는 해시는 내지 않는다. 실패한 실행은 `null`), 모델 라벨; 강체마다 시작·끝 위치, 변위, 거리, 수평 거리, 가장 낮은·높은 z와 그 틱, 끝과 최대 기울기(deg); 이벤트 종류별 수, 파단(`breaks`, 사유 `over_threshold`)·의도한 분리(`separations`, X-08)·조건 충족 이벤트 전체, 시작된 접촉 수; 지금 조회한 설계에서 돌린 실행인지(`current_design`: `definition_hash`와 `project_hash`가 같음) |

- **기울기.** 첫 프레임의 자세에서 그 프레임의 자세로 돈 회전이 월드 위쪽(+Z)을 돌린 각이다: $\arccos((R_1 R_0^\top)_{zz})$. 연직축 둘레로만 돈 것은 0이다(테스트: 마지막 자세를 x축 둘레로 0.4 rad 돌리면 22.918°).
- **실행 기록.** `record`는 `check_run`을 통과한 온전한 스트림만 받고(끝 프레임이 빠지면 `ValueError`) 요약만 `run_id`로 JSON 문장으로 보관한다. G-02c `RunTools(..., queries=tools)`가 끝낸 실제 실행도 자동으로 같은 `record`에 기록하므로 실행 요청 뒤 별도 복사나 수동 기록 없이 `rollout_summary`로 읽는다(`test_run_tools_a_finished_run_records_its_whole_stream_in_the_shared_query_tools`). `record`와 모든 조회는 매번 새 객체를 돌려주므로 받은 쪽이 고쳐도 기록은 바뀌지 않는다(테스트). 같은 `run_id`를 다시 기록하면 새 것이 옛 것을 바꾼다. `run_id`를 빼면 가장 최근 기록이다. 기록이 없거나 모르는 id는 `unknown_id`. 작업 스레드의 기록 추가·교체와 이벤트 루프의 읽기는 한 잠금으로 보호한다.

## 코어와 일치 (테스트)

| 시험 | 대조 |
|---|---|
| `list_parts` | 프로젝트의 인스턴스·결합·액추에이터·스케줄과 배지, 부품 정의의 스냅 포인트 |
| `mass_properties`, 4륜 카트(X-03a 손계산 2) | `assembly_mass` 합(상대 1e-15), `tipover` 무게중심(상대 1e-12), 손계산 Σm, Σmc/Σm(상대 1e-12), 인스턴스마다 `mass_properties` 그대로 |
| `mass_properties`, 탱크 위 추력기(X-01c 픽스처) | `tank_supply().remaining`, test_thrust의 손 질량 $M_\text{tank}+M_\text{thruster}(+\text{capacity})$(상대 1e-12), `ThrustModel.mass_of`, 추진제를 탱크 원점에 더한 무게중심 |
| `statics_check`, 카트와 내민 팔 | `tipover`의 모든 필드와 같음, 내민 팔은 여유 -0.08 m, 불안정 |
| `statics_check` 입력 배지, 카트와 탱크 위 추력기 | 카트: `mass`·`pose` `declared`, `gravity` `cite`(지구 데이터), `badge` `declared`. 추력기: `mass` = 바디 트리 인스턴스들의 `Derivation.input_badges`, `badge` = 가장 약한 것 |
| `rollout_summary`, X-02a 탑(`test_simulate_stream`의 픽스처) 실행 | 스트림의 첫·끝 포즈, 최저·최고 z, 궤적 해시와 플랫폼 태그(`run_ended`·`run_started`의 태그 그대로), 끝 틱·시각, 모델 라벨과 같음 |

## 한계 (숨기지 않는다)

- 실행 요약의 최저·최고 높이와 기울기는 받은 프레임(`frame_every_ticks` 틱마다와 끝 틱)에서만 읽었다. 프레임 사이 틱의 극값은 보지 않는다(`sampling` 문장이 요약에 있다). 위치는 강체 프레임 원점(가장 작은 ID 인스턴스의 프레임)의 위치이고 강체의 무게중심이 아니다.
- 실행 요약은 기록된 실행만 읽는다. MCP 서버(G-08)의 도구 목록에 조회 도구를 싣는 것과, 실행 요청 도구(G-02c)·Hub가 끝난 실행을 `record`하는 연결은 #558이다.
- 정역학 검사는 X-03a의 지지 다각형과 전복각뿐이다. 결합부 정적 하중(X-03b)은 그 잎이 들어오면 더한다. `statics_check`의 질량은 X-03a 그대로 건조 질량이다(탱크의 추진제를 넣지 않는다); 추진제를 넣은 무게중심은 `mass_properties`의 `with_propellant`다.
- 질량과 정역학은 컴파일되는 설계에서만 나온다(바디 트리가 필요하다). 컴파일되지 않는 설계는 컴파일러의 사유로 거부되고, 부품 목록은 언제나 나온다.
- 배터리 에너지 같은 다른 공급원의 양은 내지 않는다(DoD 밖).
