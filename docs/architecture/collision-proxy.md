# 충돌 프록시 (B-01b)

- 상태: 구현됨. 모델은 `packages/core/src/kinetra_core/collision.py`(`CollisionProxy`), 계산은 `packages/engine/src/kinetra_engine/parts/collision.py`(`collision_proxy`), 형상 레시피를 값으로 풀고 검사하는 공통 부분은 `parts/_shape.py`(B-01a의 `mass_properties`와 같이 쓴다). 테스트는 `packages/engine/tests/test_proxy.py`. `uv run pytest packages/engine -q -k proxy`.
- 근거: `docs/architecture/part-mass.md`(레시피와 겹치지 않는 합), `docs/architecture/client-adapter.md` A1(물리에 쓰는 충돌 프록시의 형상은 엔진 중립 데이터로 온다, MJCF 조각이 아니다), `docs/decisions/engine.md`(MuJoCo 코어), 이슈 #93.
- 범위 밖: MJCF 매핑(X-01a), 시각 glTF(B-01c), 캐시(B-01d), 가져온 메시의 프록시(L-02b), 부품 종류(B-02, B-03).

## 쓰는 법

```python
from kinetra_engine.parts import collision_proxy
proxy = collision_proxy(part_def)                  # 파라미터는 PartDef의 기본값
proxy = collision_proxy(part_def, {"width": q})    # mass_properties와 같은 덮어쓰기 규칙
```

결과 `CollisionProxy`: `geoms`(`ProxyGeom`: 기본형 `box`·`cylinder`·`sphere`, 풀어낸 치수 `dimensions`, 부품 로컬 좌표의 `center`, `orientation`, `volume`), `filled_voids`(프록시가 메운 빈 곳), `proxy_volume`, `recipe_volume`, `volume_error`, `derivation`.

## 만드는 규칙

- **더한 요소 하나 = 프록시 기본형 하나.** 같은 기본형, 같은 치수, 같은 중심, 같은 방향을 그대로 옮긴다(`ProxyGeom.id`는 요소 `id`). 기본형은 모두 볼록하고 MuJoCo 지오메트리 하나에 대응하지만 **값은 그대로 넘어가지 않는다**(아래 매핑 표). 이 PR은 MJCF를 만들지 않고 MuJoCo를 돌려 보지도 않았다.
- **시각 메시를 충돌에 쓰지 않는다.** 입력은 형상 레시피뿐이고 glTF는 읽지 않는다. 결과 타입에는 메시 종류가 없다(`primitive`는 `box`·`cylinder`·`sphere` 세 값뿐이라 `mesh`와 `trimesh`는 검증에서 거절된다). 볼록체(`convex`)는 거절 목록에 굳히지 않았다. 가져온 메시의 프록시(L-02b)와 FL-03a가 필요하면 이 타입에 값을 더한다.
- **레시피 검사는 질량 계산과 같다.** 파라미터 단위·범위, 치수 양수, 더한 요소끼리 겹치지 않음, 뺀 요소는 더한 요소 하나 안에 있음을 `mass_properties`와 같은 코드(`_shape.resolve_shape`)로 확인하고 깨지면 `ShapeError`로 거절한다. `recipe_volume`도 `mass_properties`와 같은 부호 있는 합(`_shape.signed_volumes`, 레시피 순서)이라 질량은 되는데 프록시는 안 되는 레시피(반대도)는 없고 두 부피는 비트까지 같다. 더한 부피와 뺀 부피를 따로 더해 빼면 작은 잔여 재료가 반올림으로 사라지므로 그렇게 하지 않는다(테스트 `..._survives_cancellation`).

## 빈 곳(`subtract`)은 프록시에서 메워진다 (근사, 숨기지 않는다)

볼록한 기본형은 구멍을 가질 수 없다. 그래서 뺀 요소는 프록시에 들어가지 않는다. 구멍, 보어, 포켓은 **프록시에서 막힌 채로** 있고 다음을 한다.

- `filled_voids`에 뺀 요소마다 id, 기본형, 부피를 적는다.
- 프록시 부피는 레시피 부피보다 작을 수 없다(과소가 아니라 과대). `volume_error = (proxy_volume - recipe_volume) / recipe_volume`, 0 이상이고 빈 곳이 없으면 정확히 0이다. `recipe_volume`은 `mass_properties`가 내는 `volume`과 비트까지 같다(테스트로 대조).
- 검증이 `proxy_volume = Σ geoms 부피`, `proxy_volume - recipe_volume = Σ filled_voids 부피`, `volume_error` 식을 확인한다. 값 하나만 고쳐서는 위조되지 않는다. `FilledVoid`에는 치수가 없어서 `filled_voids[].volume`, `recipe_volume`, `volume_error`를 함께 맞춰 고치면 검증을 통과한다. 이 모델은 계산 결과의 일관성을 확인하지 위변조를 막는 서명이 아니다.
- 모든 값의 배지는 `sim`이고 출처는 계산 함수다. 입력(레시피, 쓴 파라미터)의 배지는 `derivation`에 있다(`massprops.py`와 같은 방식). `derivation.assumptions`에 "빈 곳을 메웠다"가 글로 실린다.

**알려진 한계(근사의 크기).** 오차는 빈 곳의 부피 비율로 정직하게 보고되지만 접촉 기하는 부피 오차보다 더 틀린다. 관(tube)의 프록시는 속이 찬 원기둥이라 안에 들어가는 물체가 들어가지 못하고(위 테스트의 관은 부피로 +178%), 구멍 난 판의 구멍으로 막대가 들어갈 수 없다. 부피 오차가 작아도 이 접촉은 틀린다. 이 근사가 사용자와 판정에 보이도록 X-01a([#123](https://github.com/NomaDamas/Kinetra/issues/123))의 DoD에 라벨 "근사: 충돌 프록시가 빈 곳을 메움(+N%)"이 컴파일 라벨과 가정표에 나오고 테스트가 있다는 줄을 더했다. `filled_voids`가 비어 있지 않으면 이 라벨이 붙는다. 이 PR은 라벨을 만들지 않는다. X-01a가 보여 준다. 빈 곳을 살리려면 겹치지 않는 볼록 조각으로 나누어 더하는 분해가 필요하다. 그것은 이 이슈 밖이고 새 이슈로 남겼다(#486, 아래 후속). 접촉이 필요 없는 같은 바디 안에서는 영향이 없고, 안으로 들어가는 접촉에서만 틀린다.

## 부피 오차 보고

`volume_error`는 프록시와 원형상(레시피)의 부피 차이를 무차원 비율로 보고한다. 기본형끼리는 닫힌 식이라(상자 $abc$, 원기둥 $\pi r^2 h$, 구 $\tfrac43\pi r^3$) 더한 요소는 오차가 0이고, 오차는 메운 빈 곳에서만 나온다. 그 외의 근사(모깎기, 모따기, 나사산)는 레시피에 없으므로 이 숫자에 들어 있지 않다. 레시피에 없는 것은 "원형상"에도 없다.

## 검증

- 부품 3종(상자 블록, 눕힌 원기둥+구, 구멍 난 판)과 관(빈 곳이 부피를 두 배 넘게 늘리는 경우)의 프록시를 손계산 부피와 $10^{-9}$ 상대 오차로 비교한다.
- 독립 점 검사(역회전으로 기본형 좌표로 옮겨 판정, 닫힌 식과 무관): 상자+눕힌 보어+기둥+구 합성체에서 레시피 안의 모든 표본 점이 프록시 안에 있고(프록시는 레시피를 덮는다), 몬테카를로 부피(시드 고정, 12만 점)가 보고한 `proxy_volume`과 `recipe_volume`에 2% 안에서 맞는다.
- 거절(파라미터 범위·이름·단위, 형상 없음, 겹침, 빈 곳 포함 위반, 전부 제거), 위조 거절(배지, 부피 합, 오차 식, 단위, 치수 키, 입력 배지, 중복 id, 빈 지오메트리, 메시 종류), JSON 왕복, 결정론, 해시.

## 후속

- 빈 곳이 있는 부품의 프록시 분해(관, 구멍 난 판을 속이 빈 채로): [#486 (B-01f)](https://github.com/NomaDamas/Kinetra/issues/486).
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
