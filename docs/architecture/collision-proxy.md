# 충돌 프록시 (B-01b, B-01f)

- 상태: 구현됨. 모델은 `packages/core/src/kinetra_core/collision.py`(`CollisionProxy`), 계산은 `packages/engine/src/kinetra_engine/parts/collision.py`(`collision_proxy`), 형상 레시피를 값으로 풀고 검사하는 공통 부분은 `parts/_shape.py`(B-01a의 `mass_properties`와 같이 쓴다). 테스트는 `packages/engine/tests/test_proxy.py`. `uv run pytest packages/engine -q -k proxy`. B-01f(#486)가 관통 보어(관, 구멍 난 판)를 비운 채 상자 조각으로 분해하는 경로를 더했다(`parts/_decompose.py`).
- 근거: `docs/architecture/part-mass.md`(레시피와 겹치지 않는 합), `docs/architecture/client-adapter.md` A1(물리에 쓰는 충돌 프록시의 형상은 엔진 중립 데이터로 온다, MJCF 조각이 아니다), `docs/decisions/engine.md`(MuJoCo 코어), 이슈 #93.
- 범위 밖: MJCF 매핑(X-01a), 시각 glTF(B-01c), 캐시(B-01d, `part-cache.md`), 가져온 메시의 프록시(L-02b), 부품 종류(B-02, B-03).

## 쓰는 법

```python
from kinetra_engine.parts import collision_proxy
proxy = collision_proxy(part_def)                  # 파라미터는 PartDef의 기본값
proxy = collision_proxy(part_def, {"width": q})    # mass_properties와 같은 덮어쓰기 규칙
proxy = collision_proxy(part_def, tolerance=0.05)  # 분해 허용 오차(기본 DEFAULT_TOLERANCE = 0.10, 배지 default)
proxy = collision_proxy(part_def, on_unsupported="reject")  # 분해할 수 없는 빈 곳을 메우지 않고 거절
```

결과 `CollisionProxy`: `geoms`(`ProxyGeom`: 기본형 `box`·`cylinder`·`sphere`, 풀어낸 치수 `dimensions`, 부품 로컬 좌표의 `center`, `orientation`, `volume`, 속한 레시피 요소 `component`), `filled_voids`(프록시가 메운 빈 곳), `decomposed_voids`(조각 사이에 비워 둔 빈 곳, B-01f), `proxy_volume`, `recipe_volume`, `volume_error`(**부호 있음**), `derivation`(`method`: `added-primitives` 또는 `void-decomposition`, 분해일 때 배지가 붙은 `tolerance`).

## 만드는 규칙

- **더한 요소 하나 = 프록시 기본형 하나.** 같은 기본형, 같은 치수, 같은 중심, 같은 방향을 그대로 옮긴다(`ProxyGeom.id`는 요소 `id`). 기본형은 모두 볼록하고 MuJoCo 지오메트리 하나에 대응하지만 **값은 그대로 넘어가지 않는다**(아래 매핑 표). 이 PR은 MJCF를 만들지 않고 MuJoCo를 돌려 보지도 않았다.
- **시각 메시를 충돌에 쓰지 않는다.** 입력은 형상 레시피뿐이고 glTF는 읽지 않는다. 결과 타입에는 메시 종류가 없다(`primitive`는 `box`·`cylinder`·`sphere` 세 값뿐이라 `mesh`와 `trimesh`는 검증에서 거절된다). 볼록체(`convex`)는 거절 목록에 굳히지 않았다. 가져온 메시의 프록시(L-02b)와 FL-03a가 필요하면 이 타입에 값을 더한다.
- **레시피 검사는 질량 계산과 같다.** 파라미터 단위·범위, 치수 양수, 더한 요소끼리 겹치지 않음, 뺀 요소는 더한 요소 하나 안에 있음을 `mass_properties`와 같은 코드(`_shape.resolve_shape`)로 확인하고 깨지면 `ShapeError`로 거절한다. `recipe_volume`도 `mass_properties`와 같은 부호 있는 합(`_shape.signed_volumes`, 레시피 순서)이라 질량은 되는데 프록시는 안 되는 레시피(반대도)는 없고 두 부피는 비트까지 같다. 더한 부피와 뺀 부피를 따로 더해 빼면 작은 잔여 재료가 반올림으로 사라지므로 그렇게 하지 않는다(테스트 `..._survives_cancellation`).

## 빈 곳의 처리: 빈 곳 하나씩 (B-01f)

빈 곳마다 따로 정한다. 한 부품에 분해하는 빈 곳과 메우는 빈 곳이 같이 있을 수 있다(`derivation.method`는 분해가 하나라도 있으면 `void-decomposition`, 아니면 `added-primitives`).

| 빈 곳 | 처리 | 오차 |
|---|---|---|
| **관통 보어**이고 호스트의 유일한 빈 곳: 상자의 한 축과 평행하고 상자를 끝까지 뚫는 원기둥(판), 또는 원기둥의 축과 평행하고 같은 길이인 원기둥(관, 축이 어긋나도 된다) | 분해(`decomposed_voids`): 판은 `strips`, 관은 `ring` | 호스트마다 `|error| <= tolerance` |
| 그 밖: 막힌 포켓, 구, 비스듬한 구멍, 한 호스트에 빈 곳 둘 이상 | 메움(`filled_voids`), 이유는 `derivation.assumptions`에 `Void 'x' was filled, not decomposed: ...` | 메운 부피(0 이상) |

- **`on_unsupported`**: `collision_proxy(..., on_unsupported="fill" | "reject")`, 기본 `fill`(B-01b가 받던 부품이 프록시를 잃지 않는다). `reject`는 메워야 하는 빈 곳을 id와 이유와 함께 `ShapeError`로 거절한다. 결정은 omp(#502 트리아지). 거절하지 않고 메우면 그 오차는 `volume_error`와 X-01a 라벨에 나온다.
- **`tolerance`**: 호스트 하나의 `|(조각 합집합 - (호스트 - 보어)) / (호스트 - 보어)|`의 상한. **부품 전체 부피가 아니라 호스트마다** 지킨다(큰 받침 옆의 얇은 관이 뚫린 채 통과하지 못한다, `test_a_big_base_cannot_hide_a_badly_decomposed_tube`). `derivation.tolerance`는 배지가 붙은 `Quantity`(단위 `1`): 인자를 안 주면 `DEFAULT_TOLERANCE = 0.10`과 배지 `default`(출처 "정한 값, 근거 없음"), 숫자를 주면 `declared`, `Quantity`를 주면 그 배지. 못 맞추면 `ShapeError`로 거절하고 사유(조각 수 한계, 얼마나 놓치는지)를 쓴다.
- **안쪽 근사.** 모든 조각이 레시피의 재료 안(호스트 안, 보어 밖)에 있다. 합집합이 레시피의 부분집합이라 호스트의 오차는 0 이하고 크기는 놓친 비율이다. 보어에 들어가는 물체는 프록시의 보어에도 들어간다. 오차는 조각에서 닫힌 식으로 계산하고 표본을 뽑지 않는다.
- **한 호스트의 조각 수와 합집합.** 부품의 `proxy_volume`은 복사한 요소의 부피와 분해한 호스트의 **합집합 부피**의 합이다(관의 상자는 서로 겹치므로 조각 부피의 합이 아니다). 판의 띠는 내부가 겹치지 않아 합과 같다. 이슈 DoD가 충돌에서 조각이 겹쳐도 된다고 했고, 질량·무게중심·관성은 프록시 조각에서 구하지 않고 `MassProperties`(B-01a)에서만 온다(`test_decomposition_leaves_mass_to_mass_properties`).

### 판: 띠 (`strips`)

단면(직사각형 - 원)을 보어 위의 `y_c - r cos(pi m / n)`(`m = 0..n`, `n` 짝수)과 판 가장자리에서 자른다. 보어 중심선도 경계라 띠 안에서 원호는 단조다. 보어에 닿는 띠는 보어 양옆 상자 둘, 안 닿는 띠는 상자 하나. 각 상자는 띠 양끝 중 호스트의 **더 좁은** 폭과 보어의 **더 넓은** 현을 쓴다. **가까운 경계는 합친다**: 띠의 두께(`j` 방향)는 보어 반지름의 `MIN_STRIP_FRACTION = 2 %` 이상이다(`test_plate_strips_are_disjoint_and_never_thinner_than_the_stated_minimum`, `test_strip_boundaries_closer_than_the_minimum_are_merged_and_the_error_still_holds`). 다른 두 치수는 실제 벽 두께와 판 두께라 그보다 얇을 수 있다.

손계산(`test_plate_hand_checked_volume_with_four_strips`): 300 x 200 x 20 mm 판, 반지름 50 mm 구멍, 구멍 중심 x = 50 mm. `n = 4`, 경계 y = -100, -50, -35.36, 0, 35.36, 50, 100 mm. 바깥 두 띠는 폭 300 mm, 가운데 네 띠는 구멍 쪽 현이 `c = 50/sqrt 2 = 35.36`, `50 mm`. 프록시 `0.02 x (2 x 0.05 x 0.3 + 2 x (0.05 - c)(0.3 - 2c) + 2c (0.3 - 2 x 0.05)) = 1.017157e-3 m^3`, 레시피 `0.0012 - pi 0.0025 0.02 = 1.04292e-3 m^3`, 오차 -2.47 %, 상자 10개.

### 관: 상자 고리 (`ring`)

관(바깥 반지름 R, 보어 반지름 r)은 접선 방향으로 돌린 상자 `N`개(폭 `w`, 반지름 방향 `[r, b]`, `b = sqrt(R^2 - w^2/4)`)다. 안쪽 면은 보어의 접선 위(정`N`각형의 변), 바깥 모서리는 바깥 원 위에 있다. 이웃 상자끼리 겹치므로 합집합 부피는 `N (stave - 이웃과의 겹침)`의 닫힌 식이다.

- **벽이 닫혀 있다**(`ring.wall_closed`): 축에서 나간 모든 반직선이 벽에 한 번 들어가고 한 번 나온다(반지름 방향 틈이 없다). 닫히지 않는 `w`는 쓰지 않고, 닫히는 `w`가 없으면 거절한다. 모델이 `wall_closed = False`를 거절하고, **조각 수가 `ring.staves`와 같고 조각이 2 pi / N의 정수배씩 돌아간 같은 크기의 상자로 한 원 위에 모두 있는지** 확인한다(조각을 지운 열린 고리는 `wall_closed`를 주장해도 검증에서 거절된다). 독립 검사(`test_tube_is_a_closed_ring...`)는 720개 반직선을 직접 따라가며 확인한다.
- **편심 관.** 보어 축이 관의 축에서 `e`만큼 어긋나면 고리는 **보어의 축** 둘레에, 바깥 반지름 `R - e`(보어 축 둘레에서 관 안에 들어가는 가장 큰 원)로 만든다. 관 밖으로 나가지 않고, 벽이 두꺼운 쪽을 놓치며 그만큼이 오차에 들어간다(`test_an_eccentric_tube_...`: 프록시 점 중 레시피 밖은 0개, 표본 6만 점). `R - e <= r`이면 거절. `outer_deviation`은 `e`를 더해 보고한다(상한).
- **`w` 선택.** `N`마다 `w`를 `2 r tan(pi/N)`의 1.01 ~ 1.90배에서 훑어 합집합이 가장 큰 닫힌 `w`를 쓰고, 허용 오차를 만족하는 가장 작은 `N`을 쓴다(6 ~ 96).
- **보고하는 편차.** `ring.inner_deviation`: 프록시의 보어 벽이 실제 보어에서 벽 쪽으로 밀려난 최대 거리 `r (1/cos(pi/N) - 1)`. `ring.outer_deviation`: 프록시의 바깥 면이 실제 바깥 원통 안으로 들어간 최대 거리(상자 사이 홈의 깊이). 독립 이분법 검사로 확인한다(`abs=2e-6`).

측정(R = 50 mm, 길이 500 mm, 이 브랜치에서 `collision_proxy`로 잰 값):

| 보어 r | 허용 오차 | 상자 수 | 오차 | 보어 벽 편차 | 바깥 면 편차 |
|---|---|---|---|---|---|
| 40 mm | 0.10 (기본) | 16 | -9.03 % | 0.78 mm | 1.88 mm |
| 40 mm | 0.05 | 22 | -4.87 % | 0.41 mm | 1.10 mm |
| 45 mm | 0.10 | 22 | -9.84 % | 0.46 mm | 0.90 mm |
| 47.5 mm | 0.10 | 32 | -9.47 % | 0.23 mm | 0.36 mm |
| 30 mm | 0.20 | 7 | -19.96 % | 3.30 mm | 7.05 mm |

보어가 바깥 반지름의 약 1/3 이하면(r = 15 mm) 상자 6 ~ 96개로 10 %를 못 맞춰 거절한다(허용 오차를 올리면 통과). 띠 방식(B-01f 첫 구현)은 같은 R/r = 1.25 관에 상자 120개가 필요했다.

### 한계

- 판의 보어 안쪽 면은 계단이고 관의 안쪽 면은 정다각형이다. 보어를 따라 미끄러지는 접촉과 보어 안쪽 마찰은 매끈한 원통과 다르다. 관의 바깥 면도 상자 사이 홈(위 표의 `outer_deviation`)만큼 안으로 들어가고, 굴러가는 관은 위 표만큼 출렁인다.
- 한 호스트에 빈 곳 둘 이상, 막힌 포켓, 구, 비스듬한 구멍은 분해하지 않는다.
- 조각이 많아지면 접촉 계산이 느려질 수 있다 [확인 필요: X-01a/X-04에서 MuJoCo로 잰다. 이 PR은 MuJoCo를 돌리지 않았다].
- 축 평행 판정: 보어 축이 호스트 축에서 벗어나는 횡방향 거리(길이의 절반 x 벗어난 성분)가 보어 반지름의 `1e-9` 배 이하일 때만 평행으로 본다. 이 안에서는 안쪽 근사가 깨지지 않는다.

## 메우는 경로 (`added-primitives`, B-01b) (근사, 숨기지 않는다)

볼록한 기본형은 구멍을 가질 수 없다. 그래서 뺀 요소는 프록시에 들어가지 않는다. 구멍, 보어, 포켓은 **프록시에서 막힌 채로** 있고 다음을 한다.

- `filled_voids`에 뺀 요소마다 id, 기본형, 부피를 적는다.
- 이 경로에서 프록시 부피는 레시피 부피보다 작을 수 없다(과소가 아니라 과대). `volume_error = (proxy_volume - recipe_volume) / recipe_volume`, 0 이상이고 빈 곳이 없으면 정확히 0이다(분해 경로의 오차는 부호가 있다). `recipe_volume`은 `mass_properties`가 내는 `volume`과 비트까지 같다(테스트로 대조).
- 검증이 `proxy_volume = Σ geoms 부피`, `proxy_volume - recipe_volume = Σ filled_voids 부피`, `volume_error` 식을 확인한다. 값 하나만 고쳐서는 위조되지 않는다. `FilledVoid`에는 치수가 없어서 `filled_voids[].volume`, `recipe_volume`, `volume_error`를 함께 맞춰 고치면 검증을 통과한다. 이 모델은 계산 결과의 일관성을 확인하지 위변조를 막는 서명이 아니다.
- 모든 값의 배지는 `sim`이고 출처는 계산 함수다. 입력(레시피, 쓴 파라미터)의 배지는 `derivation`에 있다(`massprops.py`와 같은 방식). `derivation.assumptions`에 "빈 곳을 메웠다"가 글로 실린다.

**알려진 한계(근사의 크기).** 오차는 빈 곳의 부피 비율로 정직하게 보고되지만 접촉 기하는 부피 오차보다 더 틀린다. 메우는 경로에서 관(tube)의 프록시는 속이 찬 원기둥이라 안에 들어가는 물체가 들어가지 못하고(관은 부피로 +178%), 구멍 난 판의 구멍으로 막대가 들어갈 수 없다. 관통 보어는 B-01f의 분해 경로가 이를 고친다. 부피 오차가 작아도 이 접촉은 틀린다. 이 근사가 사용자와 판정에 보이도록 X-01a([#123](https://github.com/NomaDamas/Kinetra/issues/123))의 DoD에 라벨 "근사: 충돌 프록시가 빈 곳을 메움(+N%)"이 컴파일 라벨과 가정표에 나오고 테스트가 있다는 줄을 더했다. `filled_voids`가 비어 있지 않으면 이 라벨이 붙는다. 메운 빈 곳의 라벨 N은 메운 빈 곳 부피의 합 / `recipe_volume`이지 전체 `volume_error`가 아니다(메움과 분해가 한 부품에 섞이면 전체 `volume_error`는 상쇄돼 0이나 음수일 수 있다). 분해한 빈 곳(`decomposed_voids`)에는 X-01a가 다른 라벨을 붙인다: "근사: 충돌 프록시가 빈 곳을 상자 조각으로 근사함(오차 N%, 허용 오차 T%, 기본값)"(N은 호스트의 `error`, T는 `derivation.tolerance`, 끝의 "기본값"은 배지가 `default`일 때). X-01a DoD(`issues.yaml`, #123)에 이 줄이 들어 있다(B-01f). 이 PR은 라벨을 만들지 않는다. X-01a가 보여 준다. 빈 곳을 살리려면 겹치지 않는 볼록 조각으로 나누어 더하는 분해가 필요하다. 그것은 이 이슈 밖이고 새 이슈로 남겼다(#486, 아래 후속). 접촉이 필요 없는 같은 바디 안에서는 영향이 없고, 안으로 들어가는 접촉에서만 틀린다.

## 부피 오차 보고

`volume_error`는 프록시와 원형상(레시피)의 부피 차이를 무차원 비율로, **부호를 지켜** 보고한다(과대 +, 과소 -). 기본형끼리는 닫힌 식이라(상자 $abc$, 원기둥 $\pi r^2 h$, 구 $\tfrac43\pi r^3$) 더한 요소는 오차가 0이고, 오차는 메운 빈 곳에서만 나온다. 그 외의 근사(모깎기, 모따기, 나사산)는 레시피에 없으므로 이 숫자에 들어 있지 않다. 레시피에 없는 것은 "원형상"에도 없다.

## 검증

- 분해(B-01f): 구멍 난 판과 관에서 보어 중심선 위의 점이 프록시 밖이고 벽 가운데 점은 안, 오차의 부호(음수)와 크기가 손계산과 허용 오차에 맞음, 판의 띠는 내부가 겹치지 않고 최소 두께 이상, 관의 고리는 반직선 720개가 벽에 한 번 들어가 한 번 나옴, 시드 고정 몬테카를로(6만 점)로 "프록시 점은 모두 레시피 안", "놓친 비율이 보고한 오차와 표본 오차 안에서 같음", 호스트별 허용 오차(큰 받침 + 관), 조각 id 충돌(형제 `plate_p0`, 62자 공통 접두사), 빈 곳 하나씩 처리와 `on_unsupported`, 허용 오차 배지, 위조 거절.

- 부품 3종(상자 블록, 눕힌 원기둥+구, 구멍 난 판)과 관(빈 곳이 부피를 두 배 넘게 늘리는 경우)의 프록시를 손계산 부피와 $10^{-9}$ 상대 오차로 비교한다.
- 독립 점 검사(역회전으로 기본형 좌표로 옮겨 판정, 닫힌 식과 무관): 상자+눕힌 보어+기둥+구 합성체에서 레시피 안의 모든 표본 점이 프록시 안에 있고(프록시는 레시피를 덮는다), 몬테카를로 부피(시드 고정, 12만 점)가 보고한 `proxy_volume`과 `recipe_volume`에 2% 안에서 맞는다.
- 거절(파라미터 범위·이름·단위, 형상 없음, 겹침, 빈 곳 포함 위반, 전부 제거), 위조 거절(배지, 부피 합, 오차 식, 단위, 치수 키, 입력 배지, 중복 id, 빈 지오메트리, 메시 종류), JSON 왕복, 결정론, 해시.

## 후속

- 빈 곳의 분해는 [#486 (B-01f)](https://github.com/NomaDamas/Kinetra/issues/486)이 했다(관통 보어만).
- MJCF 지오메트리 매핑: X-01a. 아래 표는 MuJoCo 문서(`doc/XMLreference.rst`의 `geom`)의 규약과 이 모델을 글로 대조한 것이고 MuJoCo를 돌려 확인하지 않았다 [확인 필요: X-01a가 시험한다].

## MuJoCo 매핑 (X-01a가 따른다, 값이 그대로 넘어가지 않는다)

| 이 모델(`ProxyGeom`) | MuJoCo `geom` |
|---|---|
| `box`, `size_x/y/z` = **전체 길이** | `type="box"`, `size="size_x/2 size_y/2 size_z/2"` (반치수) |
| `cylinder`, `radius`, `length` = **전체 길이**, 축은 로컬 z | `type="cylinder"`, `size="radius length/2"` (반지름, 반길이), 축은 geom의 z |
| `sphere`, `radius` | `type="sphere"`, `size="radius"` |
| `center` (x, y, z) [m] | `pos="x y z"` |
| `orientation` `{x, y, z, w}` | `quat="w x y z"` (MuJoCo는 스칼라가 앞이다) |

- 부피, 질량, 관성은 프록시 지오메트리에서 구하지 않는다. MuJoCo가 `geom`의 `density`로 질량을 계산하게 두면 메운 빈 곳이 질량에 들어간다. 바디의 질량, 무게중심, 관성은 항상 `MassProperties`(B-01a)에서 와서 `inertial`로 명시한다.
- 소비하는 쪽이 MJCF 원본을 저장하지 않는다는 규칙(`client-adapter.md` A1)은 그대로다. 이 표는 컴파일러가 산출물을 만들 때의 변환이다.
