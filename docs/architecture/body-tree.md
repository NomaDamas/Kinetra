# 바디 트리와 고정 결합 (X-01a)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/compiler/`(`bodytree.py`, `labels.py`, `mjcf.py`), 테스트는 `packages/engine/tests/test_body_tree.py`. `uv run pytest packages/engine -q -k body_tree`(정규 순서 규칙은 `-k canonical_order`).
- 근거: `docs/decisions/engine.md`(MuJoCo 네이티브 4.0.0이 코어), `collision-proxy.md`(매핑 표), `part-mass.md`, `project-model.md`(결합), 이슈 #123, #511.
- 범위 밖: 힌지·슬라이더의 스프링·댐퍼, 모터와 토크-속도 제한(X-01b), 추력기와 추진제(X-01c), 부품 단위 오류 형식(X-01d), 행성 상수와 `<option>`(W-03a), 접촉 매개변수와 마찰 합성(X-01b), 결합 해제(X-04b). MJCF는 산출물이고 저장 원본이 아니다.

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
- **트리.** 힌지·슬라이더가 강체를 잇는다. 강체와 이 결합은 한 덩어리의 트리여야 한다. 루트는 어느 결합의 `b`쪽도 아닌 강체 가운데 ID가 가장 작은 것이고 자유 관절(`freejoint`)이다. `b`쪽에서 만나는 결합은 뒤집는다: 축과 한계의 부호가 바뀐다(같은 직선, 반대 방향의 좌표). 결합 좌표 0이 저장된 자세다.
- **월드 축.** 결합 축은 `a` 인스턴스 자세 × `a` 스냅 포인트 자세 × `Joint.unit_axis`(`project-model.md`의 B-04a 문단이 이 계산을 X-01a의 몫으로 남겼다)이고 MJCF에는 자식 강체 좌표계로 옮겨 적는다. 결합점은 `a` 스냅 포인트의 월드 위치다. 두 스냅 포인트가 저장된 자세에서 실제로 겹치는지는 배치 검사(C-02c)이고 여기서 다시 보지 않는다. 결합의 `a` 쪽 위치를 기준으로 하므로 `b` 쪽이 어긋나 있어도 컴파일은 저장된 자세를 그대로 쓴다(자세가 권위다).
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
- 구조적 오류는 `CompileError`(인스턴스·결합·부품 ID를 가진다)로 낸다. 오류 형식과 경고의 완성은 X-01d다.
