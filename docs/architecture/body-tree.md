# 바디 트리와 고정 결합 (X-01a), 컴파일 오류 (X-01d)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/compiler/`(`bodytree.py`, `labels.py`, `mjcf.py`, 오류는 `errors.py`·`checks.py`), 테스트는 `packages/engine/tests/test_body_tree.py`, `test_compile_errors.py`. `uv run pytest packages/engine -q -k body_tree`(정규 순서 규칙은 `-k canonical_order`, 컴파일 오류는 `-k compile_error`).
- 근거: `docs/decisions/engine.md`(MuJoCo 네이티브 4.0.0이 코어), `collision-proxy.md`(매핑 표), `part-mass.md`, `project-model.md`(결합), `missing-definitions.md`(`require_complete`), `part-motor.md`(역할 없는 부품의 "곡선 없음"), 이슈 #123, #126, #511.
- 범위 밖: 힌지·슬라이더의 스프링·댐퍼, 모터와 토크-속도 제한(X-01b), 추력기와 추진제(X-01c), 행성 상수와 `<option>`(W-03a), 접촉 매개변수와 마찰 합성(X-01b), 결합 해제(X-04b), 정역학 경고와 한 목록으로 합치기(X-11). MJCF는 산출물이고 저장 원본이 아니다.

## 쓰는 법

```python
from kinetra_engine.compiler import build_body_tree, proxy_labels, to_mjcf
tree = build_body_tree(project, cache=None, tolerance=None)   # BodyTree, 아니면 CompileError
xml = to_mjcf(tree)                                            # MJCF 문자열
labels = proxy_labels(tree)                                    # 근사 라벨(ModelLabel)
```

## 규칙

- **정규 순서(#511).** 컴파일러는 프로젝트를 `kinetra_core.canonical_order`로만 읽는다. 인스턴스, 결합, 형상 요소, 스냅 포인트, 파라미터가 모두 ID 순이다. `project_hash`가 같은 두 프로젝트는 비트 단위로 같은 MJCF와 같은 `MassProperties`를 낸다. 바디 트리의 루트, 형제 순서, geom 순서도 ID 순이다.
- **강체.** `fixed` 결합으로 이어진 인스턴스는 한 강체다(스트림 프레임이 강체를 인스턴스 목록으로 가리키는 것과 같다, `client-adapter.md` F8). 강체 ID는 그 묶음의 가장 작은 인스턴스 ID이고 강체의 좌표계는 그 인스턴스의 것이다. 질량·무게중심·관성은 인스턴스의 `MassProperties`의 합이다(`math.fsum`, 평행축 정리, 강체 좌표계). **프록시에서 구하지 않는다.**
- **트리.** 힌지·슬라이더가 강체를 잇는다. 강체와 이 결합은 한 덩어리의 트리여야 한다. 루트는 어느 결합의 `b`쪽도 아닌 강체 가운데 ID가 가장 작은 것이고 자유 관절(`freejoint`, 이름 `__kinetra_root_<강체 ID>`: 프로젝트 ID는 `_`로 시작할 수 없어 결합 ID와 겹치지 않는다)이다. `b`쪽에서 만나는 결합은 축의 부호만 바꾼다: `a`에 대해 `b`가 q만큼 도는 것은 `b`에 대해 `a`가 반대 축으로 q만큼 도는 것이므로 좌표와 한계는 프로젝트의 결합 그대로다(테스트: 같은 힌지를 양쪽에서 만나도 상대 운동과 범위가 같다). 결합 좌표 0이 저장된 자세다.
- **월드 축.** 결합 축은 `a` 인스턴스 자세 × `a` 스냅 포인트 자세 × `Joint.unit_axis`(`project-model.md`의 B-04a 문단이 이 계산을 X-01a의 몫으로 남겼다)이고 MJCF에는 자식 강체 좌표계로 옮겨 적는다. 결합점은 `a` 스냅 포인트의 월드 위치다. 두 스냅 포인트가 저장된 자세에서 만나지 않거나 `b` 스냅 좌표계로 읽은 축이 다른 직선이면 컴파일 오류다(아래 X-01d). 그래서 `a` 쪽을 기준으로 써도 `b` 쪽과 같은 점, 같은 직선이다(자세가 권위다).
- **프록시 → `geom`**(`collision-proxy.md`의 매핑 표): 상자는 반치수, 원기둥은 `(반지름, 반길이)`, 구는 반지름, 중심은 `pos`, 방향은 `quat="w x y z"`. 강체 안의 다른 인스턴스의 geom은 강체 좌표계로 옮긴다. `geom` 이름은 `<인스턴스>/<프록시 geom id>`.
- **`<inertial>`.** `mass`, `pos`(`MassProperties.center_of_mass`), `fullinertia`(`Ixx Iyy Izz Ixy Ixz Iyz`, 질량 중심 둘레, 강체 축)를 `MassProperties`에서 명시한다. `inertiafromgeom="false"`라 `<inertial>`이 없는 바디는 MuJoCo가 거절한다(프록시의 메운 빈 곳이 질량에 들어가지 않는다는 보증).
- **MJCF에 아직 없는 것**: `<option>`(중력, 시간 간격, 적분기), 접촉 매개변수, 액추에이터, 결합의 스프링·댐퍼. 그래서 이 MJCF는 "그 행성의 물리"가 아니라 구조(바디, 결합, 질량, 충돌 도형)다. `break_threshold`와 액추에이터는 이 MJCF에 들어가지 않는다(각각 X-04b, X-01b가 더한다).

## 근사 라벨

프록시는 볼록한 기본형이라 구멍을 가질 수 없다. 컴파일은 그 근사를 라벨로 낸다(`ModelLabel.text`는 가정표와 `run_started.model_labels`에 그대로 실린다, `client-adapter.md` D4). 라벨은 인스턴스 ID 순, 한 인스턴스에서는 (a) 다음 (b)를 호스트 ID 순으로 낸다.

| | 조건 | 텍스트 | N |
|---|---|---|---|
| (a) 메움 | `CollisionProxy.filled_voids`가 비어 있지 않음 | `근사: 충돌 프록시가 빈 곳을 메움(+N%)` | 메운 빈 곳 부피의 합 / `recipe_volume` × 100. **`volume_error`가 아니다**: 한 부품에 분해한 호스트가 있으면 `volume_error`는 메운 부피와 분해로 놓친 부피가 상쇄돼 0이나 음수일 수 있다 |
| (b) 분해 | `decomposed_voids`가 비어 있지 않음 | `근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함(오차 N%, 허용 오차 T%[, 기본값])` | 호스트마다 그 `decomposed_voids[].error` × 100(부호 있음), T = `derivation.tolerance` × 100, 배지가 `default`면 `, 기본값` |

빈 곳이 없는 부품에는 라벨이 없다. 수치는 유효숫자 세 자리다(`+7%`, `-2.47%`, `10%`).

## 한계와 열린 질문 (숨기지 않는다)

- 이 MJCF를 돌려 본 것은 적재(`MjModel.from_xml_string`)와 `mj_forward`까지다. 접촉과 구름은 X-01b·X-02의 몫이고 이 PR은 시뮬레이션 궤적을 주장하지 않는다.
- 같은 인스턴스를 두 번 컴파일하지 않으려면 `cache`(`PartCache`)를 넘긴다. 캐시 키는 `part_key`(엄격)다. 정규 순서로 읽은 부품은 순서만 다른 정의가 같은 키에 닿는다.
- 구조적 오류도 아래의 `CompileError`다.

## 컴파일 오류 (X-01d)

컴파일이 거부되면 어느 부품 때문인지 알 수 있어야 한다. `build_body_tree`의 거부는 하나의 `CompileError`(`kinetra_engine.compiler`)이고 다음을 가진다.

- `code`: `CompileErrorCode`(아래 표의 닫힌 목록). `str(error)`: 사유 문장(영어, 고칠 길 포함).
- `instances`, `parts`, `joints`, `actuators`: 사유가 가리키는 ID. `parts`는 그 인스턴스들의 부품(처음 나온 순서로 한 번씩)이라 인스턴스를 가리키는 오류는 늘 부품도 가리킨다. ID는 각 컬렉션 안에서만 유일하다.
- 빠진 정의(자리표시, C-06)는 컴파일 오류가 아니라 그 전에 `require_complete(project, "compile")`가 `ProjectIncomplete`로 거부한다(`missing-definitions.md`). 아무것도 읽기 전이다.

검사 순서는 고정이고 처음 걸린 하나를 낸다: 부품 → 액추에이터 → 스냅 → 축 → 트리 → 뜸. 한 단계 안에서는 ID 순이다(정규 순서).

| code | 언제 | ID |
|---|---|---|
| `no_instance` | 인스턴스가 없다 | — |
| `part` | 부품이 그 인스턴스의 파라미터에서 컴파일되지 않는다(형상 레시피, 질량. 예: 재료도 선언 질량도 없음) | 인스턴스, 부품 |
| `no_curve` | 역할이 없는 부품의 인스턴스에 액추에이터가 붙었다. 모터는 곡선 `torque_speed`, 추력기는 `thrust`가 없다(`DesignSpec`은 역할 없는 부품을 일부러 받는다, `part-motor.md`) | 액추에이터, 인스턴스, 부품, 모터의 결합 |
| `snap_mismatch` | 결합한 두 스냅 포인트가 서로의 종류를 받지 않거나 저장된 자세에서 만나지 않는다. 문장은 검증기(C-02c `check_placement`)의 `invalid_snap` 문장 그대로다 | 결합, 양끝 인스턴스, 부품 |
| `axis_mismatch` | 힌지·슬라이더의 `unit_axis`를 `a`와 `b` 스냅 좌표계에서 각각 월드로 옮긴 두 방향이 한 직선이 아니다(방향은 반대여도 된다) | 결합, 양끝 인스턴스, 부품 |
| `fixed_loop` | 고정 결합이 고정 결합의 고리를 닫는다 | 결합, 인스턴스, 부품 |
| `welded_joint` | 힌지·슬라이더가 이미 한 강체로 용접된 두 인스턴스를 잇는다 | 결합, 인스턴스, 부품 |
| `loop` | 힌지·슬라이더가 강체 사이에 고리를 닫는다 | 결합, 인스턴스, 부품 |
| `not_one_piece` | 조립이 결합 없이 두 덩어리 이상이다 | 두 덩어리의 대표 인스턴스, 부품 |
| `floating` | 조립이 지면에도 지형 소품에도 닿지 않는다. 문장은 검증기의 `floating` 문장 + "시작 높이는 아직 프로젝트에 없다(J-02)" | 인스턴스, 부품 |

결정(X-01a 리뷰와 C-02c가 남긴 것):

- **스냅 어긋남과 뜸은 검증기와 한 규칙이다.** 컴파일은 `check_placement`(허용 오차 `PLACEMENT_TOLERANCE` = 1 µm)를 그대로 부르고 그 `invalid_snap`·`floating`만 오류로 바꾼다. 그래서 검증기가 받아들인 편집은 배치 때문에 컴파일에서 막히지 않고, 검증기는 명령이 새로 만든 문제만 거부하므로 파일에서 연 어긋난 프로젝트는 여기서 막힌다. X-01a는 `a` 쪽 스냅 위치로 컴파일하고 `b` 쪽 어긋남을 조용히 넘겼다. 이제 넘기지 않는다.
- **겹침(`overlap`)은 컴파일 오류가 아니다.** 검증기의 발견으로 남는다. 형상 레시피가 없는 부품은 도형이 없어 검증기가 그 덩어리를 뜬 것으로 부르지 않고(통과가 아니라 모르는 것) 컴파일도 그렇다.
- **뜬 조립은 거부한다.** 프로젝트에는 아직 시작 높이가 없다(J-02). 공중에서 떨어뜨리는 시나리오는 J-02가 시작 높이를 더할 때 이 규칙을 바꾼다.
- **축.** 맞물리는 스냅 좌표계는 서로 마주볼 수 있어 반대 방향은 같은 직선이다(4륜차 예시의 오른쪽 모터: `a`에서 -Y, `b`에서 +Y). 허용 오차 `AXIS_TOLERANCE` = 1e-6은 두 방향 사이 각의 사인 상한이고 `PLACEMENT_TOLERANCE`처럼 저장된 double을 위한 수치 허용치이지 물리적 주장이 아니다.
- 오류는 하나씩 낸다(처음 걸린 것). 모든 문제를 한 목록으로 모으고 정역학 경고와 합치는 것은 X-11이다.
