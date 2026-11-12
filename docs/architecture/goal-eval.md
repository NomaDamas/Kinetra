# 성공 조건 평가기 (J-02a)

- 상태: 구현됨. `packages/judge/src/kinetra_judge/goal.py`(`Goal`, `evaluate_goal`), 테스트 `packages/judge/tests/test_goal_eval.py`(`uv run pytest packages/judge -q -k goal_eval`).
- 근거: 이슈 #167, `docs/plan/studio-plan.md` 4.5절(판정)과 J-06·X-13 행, `client-adapter.md` 3.3(실행 스트림), `break-threshold.md`(X-04b `break` 이벤트), 핵심 가치 V1.
- 범위 밖: 미션 예산과 점수(S2), 조건 블록 편집기와 타임라인 표시(J-02b), Project에 조건을 저장하는 형식과 스키마 출력(J-02b), 몬테카를로 판정(J-01). 실패 원인 분류는 J-06([`failure-cause.md`](failure-cause.md)), 이 조건에서 유도하는 필요조건 스크린은 J-01b([`necessary-screen.md`](necessary-screen.md)).

## 하는 일

`evaluate_goal(goal, started, frames, ended)`은 실행 한 번의 스트림(`RunStarted`, `Frame`들, `RunEnded`; C-05b)을 `check_run`으로 확인한 뒤 `Goal`의 조건마다 `met`(충족), `failed`(실패), `undetermined`(판단 불가)를 낸다. **판정이 아니다**: 결과의 첫 레이블이 "1회 실행의 조건 평가이며 판정이 아닙니다"이고, 판정은 이 평가를 표본마다 부르는 몬테카를로(J-01)다.

조건은 프로젝트의 인스턴스 id를 가리킨다. 평가기는 `RunStarted.bodies`에서 그 인스턴스가 속한 몸을 찾아 그 몸의 자세를 따라간다. 그래서 결합이 풀려 떨어져 나간 부품을 가리키는 조건은 그 조각의 궤적으로 평가된다(X-13, 엔진 실행으로 확인: `packages/engine/tests/test_break_pieces.py`, `break-threshold.md`). 실행에 없는 인스턴스는 `ValueError`다.

| `kind` | 필드 | 충족 | 실패로 확정 |
|---|---|---|---|
| `reach` 도달 | `instance`, `region`(월드 축정렬 상자 `min`/`max` [m]) | 몸의 기준점이 상자 안에 있는 첫 프레임 | 실행이 끝까지(`completed`) 가도록 없음: 마지막 틱 |
| `rotation` 회전각 | `instance`, `axis`(몸 좌표 `x`/`y`/`z`), `angle_deg` | 프레임 사이 회전(상대 쿼터니언의 회전 벡터)의 그 축 성분을 틱 0부터 더한 값의 크기가 `angle_deg` 이상인 첫 프레임 | 실행이 끝까지 가도록 없음: 마지막 틱 |
| `landing` 착지 자세·속도 | `instance`, `max_tilt_deg`, `max_speed_m_s`, `touch`(선택) | 첫 착지에서 기울기 ≤ `max_tilt_deg`, 속력 ≤ `max_speed_m_s` | 첫 착지에서 하나라도 넘음: 착지 틱. 접촉 이벤트는 있는데 착지가 없이 실행이 끝남: 마지막 틱 |
| `time_limit` 시간 한도 | `seconds` | 모든 `reach`·`rotation`·`landing`이 시각(`tick × timestep_s`)이 `seconds` 이하인 틱에 충족. 한도가 두 틱 사이면 앞 틱까지만 든다 | 그중 하나가 한도 뒤에 충족되었거나 실패했거나 한도까지 충족되지 않음: 한도 틱(시각이 `seconds` 이하인 마지막 틱, `floor(seconds / timestep_s)`), 실행이 그보다 먼저 끝났으면 마지막 틱 |
| `no_break` 파단 없음 | `joints`(선택, 비면 모든 결합) | `break` 이벤트 없이 실행이 끝까지 감: 마지막 틱 | 해당 결합의 첫 `break` 이벤트 틱(`load_n`, `threshold_n`을 함께 싣는다) |

- **착지.** `touch` 인스턴스들의 몸(비면 실행의 모든 몸) 중 어느 것도 지면에 닿아 있지 않은 상태에서 한 몸의 지면 `contact` `begin`이 오면 착지다. 틱 0의 `begin`은 놓여 있던 것이지 착지가 아니다. 그래서 바퀴가 닿는 차의 차체 자세를 볼 때는 `touch`를 비우거나 바퀴를 적는다. 기울기는 틱 0에 위를 가리키던 몸 좌표 방향이 착지 시점에 월드 +Z와 이루는 각이다(착지 틱 이하의 마지막 프레임). 속도는 공중에 뜬 틱부터 착지 틱까지의 프레임 중 마지막 셋을 지나는 2차식의 착지 시점 미분이다(일정 가속도면 정확하다). 둘뿐이면 두 프레임의 차분이다.
- **파단과 분리.** `no_break`는 `break` 이벤트(하중이 임계를 넘은 결합 해제, X-04b)만 센다. X-08의 의도한 분리는 `break`가 아닌 별도 이벤트(`separation`)로 오므로 파단으로 세지 않는다.
- **목표 전체.** 조건 하나라도 `failed`면 `failed`이고 그 틱은 **실패로 확정된 가장 이른 틱**이다(J-06이 원인을 그 틱 이하의 사건에서만 뽑는다). 아니고 하나라도 `undetermined`면 `undetermined`, 모두 `met`이면 `met`이고 틱은 마지막으로 충족된 틱이다.

## 정직하게 말하는 것

1. **판단 불가를 추측으로 채우지 않는다.** 실행이 멈췄거나(`stopped`) 엔진이 계속할 수 없었으면(`failed`) 그때까지 결정되지 않은 조건은 `undetermined`다(이미 실패로 확정된 조건은 그대로 목표를 실패시킨다). 착지 조건은 스트림에 접촉 이벤트가 하나도 없으면 `undetermined`다: "닿지 않았다"와 "닿음을 알리지 않았다"를 스트림이 구분하지 못한다. 코어의 실행(`PreviewRun`)은 #562부터 몸–지면, 몸–소품, 몸–몸 접촉의 `begin`/`end`를 싣는다(`client-adapter.md`의 X-02a "스트림", 규칙은 `kinetra_engine/run/contacts.py`). 그래서 엔진 실행의 착지 조건은 `met`/`failed`로 결정된다(`packages/engine/tests/test_contact_events.py`). 공중 구간의 프레임이 둘보다 적으면 속도를 낼 수 없어 `undetermined`다. 단 그때도 기울기가 이미 한도를 넘었으면 `failed`다(가릴 수 있는 실패를 판단 불가로 두지 않는다).
2. **표본화.** 도달, 회전, 착지 자세는 프레임(`frame_every_ticks`마다)의 자세로 본다. 프레임 사이에 잠깐 상자를 지나간 것은 보지 못하고, 충족 틱은 실제 순간 다음의 첫 프레임이다. 결과에 `sample_interval_s`와 레이블이 실린다. 회전은 프레임 사이의 회전이 반 바퀴(π)보다 작다고 본다. 판정 표본(J-01)은 `frame_every_ticks=1`로 돌려 틱 단위로 볼 수 있다.
3. **몸의 기준점.** 도달과 착지 속도는 인스턴스가 속한 몸의 기준점(가장 작은 id 인스턴스의 원점, `bodytree.py`) 위치로 본다. 용접된 다른 인스턴스의 점이 아니다. 레이블로 싣는다.
4. **값의 출처.** 측정값(`measured`, 키 이름이 단위로 끝난다)은 모두 실행 스트림에서 읽었다(배지 `sim`). 한도(`angle_deg`, `max_tilt_deg`, `max_speed_m_s`, `seconds`, 상자)는 사용자가 정하는 값이고 평가기에 기본값이 없다.

## 손계산 대조 (테스트)

테스트의 두 궤적은 닫힌 식이다: 지면에 놓인 차(몸 `car`와 그 아래 바퀴 몸 `wheel-1`)가 발사 속도 (`vx`, `vz0`)로 떠서 지구 표면 중력(9.80665 m/s², `data/bodies/earth.json`)의 포물선을 날며 몸 y축으로 일정하게 돌고, 처음 높이로 돌아온 틱(바퀴의 지면 `begin`)에 멈춘다. `timestep_s` 0.002, 4틱마다 프레임, 750틱.

| 궤적 | 입력 | 착지 틱 | 결과 |
|---|---|---|---|
| 성공 | `vx` 1.5, `vz0` 4 m/s, 한 바퀴 | ⌈2·4/9.80665/0.002⌉ = 408 | 도달 336(x ≥ 1.0 m는 333.3틱), 회전 388(340°는 385.3틱, 342.4°), 착지 기울기 0°, 수직 속력 9.80665·0.816 − 4 = 4.0022 m/s, 속력 4.274 m/s ≤ 5, 시간 한도 408 ≤ 500, 파단 없음 750 → `met` |
| 실패 | `vx` 0.2, `vz0` 6 m/s, 3/4바퀴, 결합 `mount` 200틱 파단 | ⌈2·6/9.80665/0.002⌉ = 612 | 도달·회전(270°) 750에 실패, 착지 기울기 90°·속력 6.0 m/s로 612에 실패, 시간 한도 500에 실패, 파단 200 → `failed`, 틱 200 |

엔진 실행 한 번(지면에 놓인 0.1 m 정육면체, 지구, 1 s)도 평가한다: 도달은 틱 0에 충족, 회전은 끝에 실패, 그래서 시간 한도는 한도 틱에 실패, 파단 없음은 충족. 착지는 엔진 실행으로도 결정된다(#562, `test_contact_events.py`): 1 m 높이 소품 벽에 붙어 떨어지는 0.1 m 정육면체의 지면 `begin`은 틱 226(반암시 오일러 손계산, 자유낙하 0.4516 s = 225.8틱), 속력은 √(2gh) = 4.43 m/s 근처라 한도 5 m/s면 `met`, 4 m/s면 `failed`(틱 226).
