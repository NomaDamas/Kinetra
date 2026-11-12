# 지형 소품: 경사로와 턱 (W-05)

- 상태: 구현됨. 컴파일은 `packages/engine/src/kinetra_engine/compiler/terrain.py`(`terrain_geoms`, `TerrainGeom`, `ramp_vertices`, `PROP_GEOM_PREFIX`), MJCF에 쓰는 곳은 `mjcf.py`, 마찰은 `contact.py`(`PropFriction`). 명령은 `packages/core/src/kinetra_core/commands.py`(`AddTerrainProp`, `ReplaceTerrainProp`, `RemoveTerrainProp`). 테스트 `packages/engine/tests/test_terrain_ramp.py`(`uv run pytest packages/engine -q -k ramp`), 명령은 `packages/core/tests/test_commands.py`(`-k terrain_prop`). 결정론적이라 시드가 없다.
- 근거: 이슈 #89, 데이터 모델 `World.terrain_props`(C-01c, `project-model.md`, `kinetra_core/world.py`), 배치 검사(C-02c, `validator._prop_bodies`), 마찰 규칙(X-01e, [`contact.md`](contact.md)), 지면 마찰 분포(W-03c, [`bodies.md`](bodies.md)), MuJoCo 4.0.0 XML reference(`mesh`, `geom`).
- 범위 밖: 자유 지형 편집(높이맵, DEM). 소품의 화면 표시와 조작, 에이전트 편집 도구·MCP의 소품 도구는 #564.

## 쓰는 법

```python
from kinetra_core import validate_command
from kinetra_engine.compiler import build_body_tree, to_mjcf
project = validate_command(project, add_terrain_prop).project   # {"type": "add_terrain_prop", "prop": {...}, "index": None}
tree = build_body_tree(project)                                  # tree.terrain: 소품마다 TerrainGeom (ID 순)
xml = to_mjcf(tree, ground_friction=None)                        # 지면 다음에 소품 geom
```

## 놓기: 명령

| 명령 | 효과 | 역명령 |
|---|---|---|
| `add_terrain_prop`(`prop`, `index`) | 소품을 놓는다. `prop`은 `RampProp`(`kind: "ramp"`, `incline`, `length`, `width`) 또는 `StepProp`(`kind: "step"`, `height`, `length`, `width`), 자세 `placement`(x, y, yaw), 표면 `material` | `remove_terrain_prop` |
| `replace_terrain_prop`(`prop`) | 같은 ID의 소품을 제자리에서 통째로 바꾼다: 옮기기, 돌리기, 크기·경사·높이, 표면 재료 | 이전 소품의 `replace_terrain_prop` |
| `remove_terrain_prop`(`id`) | 소품을 치운다 | 원래 위치(`index`)에 `add_terrain_prop` |

다른 편집과 같은 문을 지난다(`validate_command`, C-02c): 없는 ID는 `unknown_id`, 겹치는 ID는 `duplicate_id`, 프로젝트에 없는 재료는 `invalid_project`, 부품을 파고드는 소품은 `overlap`이다. 행성 상수를 싣는 필드는 소품에 없다(`World`가 거부한다, C4).

## 모양: MJCF geom

좌표계는 `world.py`의 것이고 검증기의 배치 검사가 쓰는 볼록 도형(`convex.Body`의 `wedge`, `box`)과 같은 입체다.

| 소품 | MJCF | 치수 |
|---|---|---|
| 경사로 | `<asset><mesh vertex="..."/>` + `type="mesh"` geom | 바닥 `length` × `width`(z = 0), 높은 끝(local x = +length/2)의 높이 `length·tan(incline)`인 삼각기둥, 꼭짓점 여섯 개 |
| 턱 | `type="box"` geom | 반치수 `(length/2, width/2, height/2)`, 중심 높이 `height/2` |

- 자세: `pos="x y 0"`(턱은 z = `height/2`), `quat="cos(yaw/2) 0 0 sin(yaw/2)"`. 경사로는 local +x 쪽으로 오른다.
- 이름: `__kinetra_prop_<소품 ID>`(경사로의 mesh도 같은 이름). 프로젝트 ID는 `_`로 시작할 수 없어 부품 geom(`<인스턴스>/<프록시 geom>`)이나 다른 이름과 겹치지 않는다.
- `<worldbody>`의 지면 평면 바로 다음, 소품 ID 순(`canonical_order`)이다. 파일의 소품 순서가 달라도 MJCF는 바이트 단위로 같다.
- 월드 geom이라 움직이지 않고 질량이 없다. 한 바디(world)의 geom끼리는 MuJoCo가 충돌시키지 않으므로 소품과 지면, 소품끼리는 접촉하지 않는다.

## 마찰

X-01e의 규칙 그대로다([`contact.md`](contact.md)): 소품 geom 하나에 계수 하나, 두 면 중 작은 쪽(min, priority로 강제).

| 소품의 `material` | 계수 | 출처 |
|---|---|---|
| 재료 ID | `Material.friction` | 재료의 배지·출처 그대로(`PropFriction.quantity`) |
| `None` | 행성 지면의 계수: 공칭(`data/bodies`) 또는 `to_mjcf(..., ground_friction=μ)`로 들어온 몬테카를로 표본(W-03c) | 행성의 `ground_friction` 가정(`ContactFriction.ground_assumption`) |

재료가 없는 소품은 "행성의 지면"이라는 데이터 모델의 뜻(C-01c) 그대로라서 지면 평면과 같은 double을 받는다. 표본이 바뀌면 지면과 그런 소품이 함께 바뀐다.

## 시험 (DoD 증거)

블록은 0.1 × 0.1 × 0.02 m 판(78.7°까지 넘어지지 않는다), 재료는 시험이 선언한 마찰 1.0(세 행성 지면 상한 0.9004와 강 A36 0.23보다 커서 **경사로 표면이 정한다**). 경사로는 길이 3 m, 폭 1 m, 블록은 경사면 가운데에 면이 닿게 놓는다. 중력은 행성 그대로 수직이고 경사는 컴파일된 경사로 geom이다(X-01e의 시험은 중력을 돌렸다). 표면 두 가지: 재료 없음(행성 지면 공칭: 지구 0.5628, 화성 0.5126, 달 0.6573)과 카탈로그 강 A36(0.23).

| 시험 | 기대(손계산) | 측정(`시뮬`, MuJoCo 4.0.0, 기본 시간 간격 0.002 s) |
|---|---|---|
| 미끄럼 시작 각, 2 표면 × 3 행성(경사로 `incline` 이분법, 0.02° 간격, 0.2 ~ 0.6 s의 "가속도 > 1e-3 g"를 미끄럼으로) | $\theta_s = \tan^{-1}\mu$ | +0.039° ~ +0.055°(문턱 1e-3 g 자체가 약 0.05°의 기울기), 허용 0.1° |
| $\theta_s + 5°$, yaw 2.1 rad로 돌린 경사로에서 경사 방향 가속도 | $a = g(\sin\theta - \mu\cos\theta)$, 역산한 μ | 상대 -3.8e-4 ~ +3.3e-4, 허용 1e-3. 접촉은 경사로 geom과 블록뿐이고 접촉 계수는 정확히 μ |
| 재료 없는 경사로에 지면 분포 양 끝을 `ground_friction`으로 | 역산한 μ = 그 끝값 | 1.6e-3 안(지구 high 0.7813, 경사 43°), 허용 3e-3 |
| $\tan\theta = 0.9\mu$, 2 표면 × 3 행성 | 가속하지 않음 | $|a|/g$ < 6e-9 |
| 놓인 모양(경사로 yaw 0.6, 턱 yaw -0.3) | 꼭짓점·반치수·자세가 파라미터 그대로 | 턱 1e-15 안, 경사로 꼭짓점 2.4e-8 m 안(아래 한계) |
| 높이 0.25 m 턱 위의 블록(달), 1 s | 턱 윗면에 머문다 | 0.018 mm 아래(소프트 접촉의 침투), 접촉은 턱 geom뿐 |
| 명령으로 놓고(`batch`), 경사를 바꾸고, 치우기 | 모델이 따라온다, 블록을 파고드는 턱은 `overlap` | 일치 |

재현: `uv run pytest packages/engine -q -k ramp`(시드 없음), `uv run pytest packages/core -q -k terrain_prop`.

## 한계 (숨기지 않는다)

- **경사로 꼭짓점은 단정밀도다.** MuJoCo는 mesh 꼭짓점을 float32로 저장한다(`mesh_vert`). 놓인 꼭짓점이 저장된 double과 최대 2.4e-8 m 다르다(위 시험). 경사각으로는 1e-8 rad 수준이다.
- 경사로의 높은 끝은 수직 벽이다(삼각기둥). 소품끼리 겹치는지는 검사하지 않는다(두 소품은 서로 닿지 않는 월드 geom이고, 겹친 모양의 합집합이 지형이 된다).
- 접촉의 한계는 X-01e의 것 그대로다: 정지·운동 구분 없는 계수 하나, 정지 마찰 범위 안의 느린 미끄럼, 구름 저항 없음. 재료 없는 소품의 계수는 흙의 tan φ라 매끈한 부품에게는 상한이다(`bodies.md`).
- 소품은 평평한 지면(z = 0) 위에만 놓인다. 소품 위에 소품을 쌓는 높이는 없다.
