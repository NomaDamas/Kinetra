# 구조 부품 통합 시연: 뼈대의 총질량 (B-02 에픽, #96)

- 상태: 구현됨. 예시 프로젝트 `schemas/examples/Project.structural-skeleton.json`, 계산 `packages/engine/src/kinetra_engine/parts/assembly.py`(`assembly_mass`), 생성기 `packages/engine/tests/skeleton_sample.py`, 테스트 `packages/engine/tests/test_structural.py`(`uv run pytest packages/engine -q -k structural`), 그림 `tools/gltf-check/skeleton.ts`(CI `screenshots` 잡의 `out/gltf-check/skeleton.png`).
- 근거: 이슈 #96의 통합 시연 항목("빔·판·차체 쉘·탑재체로 만든 뼈대의 총질량이 합산과 맞는 스크린샷"), B-02a(`parts-beam-plate.md`), B-02b(`parts-shell.md`), B-02c(`part-payload.md`), 핵심 가치 V2(상상에서 현실까지)와 V5(출처).
- 범위 밖: 조립체의 무게중심과 관성(자세의 회전이 필요하다: X-01), 추진제나 배터리 잔량이 더하는 질량(`tank_total_mass`, B-03d), 결합의 동작(B-04), 실제 차량의 치수.

## 설계

한 `Project`다(행성 지구, 지면 z = 0 위에 놓임). 부품 정의는 라이브러리 파일(`parts/library/*.json`) 그대로이고 재료는 B-07 카탈로그의 `al6061-t6`(밀도 2700 kg/m³, `인용`)다.

| 인스턴스 | 부품 | 재료 | 인스턴스가 정한 값 | 질량 [kg] | 손계산 |
|---|---|---|---|---|---|
| `keel-beam` | `beam` | al6061-t6 | `length` 0.4 m | 0.57024 | 2700 × (2 × 0.4·0.04·0.004 + 0.4·0.004·0.052) |
| `deck-plate` | `plate` | al6061-t6 | `length` 0.5, `width` 0.3 m | 2.2383 | 2700 × (슬랩 + 긴 테 둘 + 짧은 테 둘) |
| `body-shell` | `shell` | al6061-t6 | (기본 치수) | 2.376 | 2700 × 8.8×10⁻⁴ m³ |
| `payload-main` | `payload` | 없음 | `mass` 3.0 kg (**사용자 선언**) | 3.0 | 선언한 값 |
| `payload-mount` | `payload-mount` | al6061-t6 | (기본 치수) | 0.3241728 | 2700 × (바닥판 + 레일 둘 + 끝벽 둘) |
| `payload-sensor` | `payload` | 없음 | `mass` 0.75 kg (**사용자 선언**), 치수 0.1×0.07×0.05 m | 0.75 | 선언한 값 |
| `boom-beam` | `beam` | al6061-t6 | `length` 0.3 m | 0.42768 | 위 빔과 같은 단면 |
| **총질량** | | | | **9.6863928** | 위 일곱 값의 합 |

결합 여섯 개는 모두 `fixed`이고 서로의 스냅 포인트를 받는 쌍이다: 키엘 빔 `top` ↔ 판 `bottom`, 판 `top` ↔ 쉘 `underside`, 쉘 `bed` ↔ 주 탑재체 `base`, 탑재체 `top` ↔ 고정대 `bottom`, 고정대 `seat` ↔ 센서 탑재체 `base`, 판 `edge-xp` ↔ 붐 빔 `end-a`. 자세는 모두 항등 방향이고 위치는 결합으로 푼다(부모 스냅의 월드 위치 − 자식 스냅의 로컬 위치). 그래서 좌표를 두 번 적지 않고, `check_placement`가 빈 결과를 돌려준다(스냅이 맞고, 겹침 없고, 바닥에 닿음). 모든 치수는 이 예시가 정한 `사용자 선언` 값이고 실제 차량의 값이 아니다. 인스턴스가 정한 파라미터의 출처 문구가 그렇게 말한다.

## 총질량 = 부품 질량의 합

`assembly_mass(design, cache=None)`는 인스턴스마다 `mass_properties(부품, 재료, 인스턴스 파라미터)`를 부르고(`PartCache`를 주면 그것을 거친다) 질량의 합을 돌려준다. 합은 `math.fsum`이라서 "그 부동소수점 수들의 정확한 합을 한 번 반올림한 값"이고 인스턴스 순서에 의존하지 않는다. 총질량에 더하거나 빼는 것은 없다: 결합, 자세, 고정대의 스냅은 질량이 없다. 결과(`AssemblyMass`)의 `total`은 배지 `시뮬`이고 입력의 배지(`인용`: 밀도, `기본값`: 형상 레시피, `사용자 선언`: 탑재체 질량과 길이)는 `input_badges`와 인스턴스별 `derivation`에 남는다. 재료가 없는 부품은 `ShapeError`가 인스턴스 id와 함께 난다.

테스트(`test_structural.py`)가 보는 것:

1. 인스턴스 질량이 손계산(분수 연산으로 쓴 상자 부피 × 밀도, 쉘은 `parts-shell.md`의 부피)과 1e-12 상대 오차로 같다.
2. 각 인스턴스의 결과가 `mass_properties`를 직접 부른 결과와 `==`이다.
3. **총질량이 `math.fsum(각 질량)`과 정확히 같다**(`==`)이고 손으로 쓴 합 9.6863928 kg과 같다.
4. 인스턴스 순서를 뒤집어도, 결합을 지워도, 캐시를 거쳐도 총질량이 그대로이다.
5. `set_parameter`로 빔 길이를 바꾸면 총질량이 손계산한 만큼만 바뀐다.
6. 예시 파일, 인스턴스별 glb, `manifest.json`이 코드가 오늘 쓰는 것과 같다(생성기를 다시 돌리라는 메시지로 실패한다).

## CI의 그림

`screenshots` 잡이 `pnpm --filter @kinetra/gltf-check capture:skeleton`을 돈다. `tools/gltf-check/page/skeleton.html`이 인스턴스마다 glb를 three.js `GLTFLoader`로 읽어 **인스턴스의 pose대로** 놓고(프로젝트 좌표 +Z 위를 한 그룹으로 three.js의 +Y 위로 돌린다. 파일의 Z→Y 루트 회전은 이 그룹이 대신하므로 버린다. 배치 코드는 B-03이 `page/assembly.js`로 뺐다), 캔버스 아래 표에 부품별 질량과 총질량을 쓴다. 표의 숫자는 엔진이 쓴 `manifest.json`의 값이다. `skeleton.ts`가 단언한다: 그려진 인스턴스 id 집합이 manifest의 7개와 같고(빠짐·추가·중복 없음) 각각 **같은 id의 manifest pose** 자리에 있다(페이지가 보고한 pose를 믿지 않는다: `assembly.ts`의 `placementProblems`), 질량도 id로 맞춘다, 지면 아래로 내려간 것이 없고 뼈대가 바닥에 닿는다, 페이지가 다시 더한 합이 엔진의 총질량과 같다, 표의 총질량 글자와 행 수가 맞다, 그려진 픽셀이 있고 잘림이 없다. 결과는 아티팩트 `screenshots`의 `gltf-check/skeleton.png`와 `skeleton-result.json`이다. 그림은 시각 메시이고 판정이 아니다(구멍은 파이지 않는다: `part-visual.md`).

## 다시 만들기

```bash
uv run python packages/engine/tests/skeleton_sample.py   # 예시, glb, manifest 다시 쓰기
uv run pytest packages/engine -q -k structural
uv run python packages/core/scripts/validate_examples.py
```
