# 부품의 시각 glTF와 재질 슬롯 (B-01c)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/parts/visual.py`(파일 만들기)와 `_tessellate.py`(삼각형 분할). 테스트는 `packages/engine/tests/test_gltf.py`(`uv run pytest packages/engine -q -k gltf`), 공식 검증기와 브라우저 증거는 `tools/gltf-check`.
- 근거: 이슈 #94, `docs/architecture/client-adapter.md` A1(시각 메시와 물리 모델은 따로다), 핵심 가치 V5, `docs/architecture/part-mass.md`(같은 레시피), `docs/architecture/materials.md`(PBR 슬롯).
- 범위 밖: 충돌 프록시(B-01b), 캐시(B-01d, `part-cache.md`), 부품 종류(B-02, B-03), STEP·STL 내보내기(HW-02), 텍스처, 빈 곳(`subtract`)을 시각 메시에서 파내는 일(#496, B-01g).

## 쓰는 법

```python
from kinetra_engine.parts import part_glb, part_gltf
glb = part_glb(part_def, material)                    # 바이트(.glb). 파라미터는 PartDef의 기본값
glb = part_glb(part_def, material, {"width": q})      # mass_properties와 같은 덮어쓰기(Quantity, m, 범위 안)
glb = part_glb(part_def, material, pbr=slots)         # 외형(PbrSlots)을 호출자가 정한다. 파일은 pbr_from_catalog: false
document, bin_chunk = part_gltf(part_def, material)   # JSON 문서와 buffers[0]의 바이트
```

같은 정의와 파라미터면 **바이트가 같다**(난수·적응 분할 없음, 부동소수점은 float32로 반올림해 적는다). 레시피를 평가하는 일은 질량·충돌 프록시와 같은 `resolve_shape`다. 그래서 레시피가 없거나 파라미터가 범위 밖이거나 요소가 겹치면 `mass_properties`와 같은 `ShapeError`다(질량을 못 구하는 부품은 그리지도 않는다).

## 파일 구조

- 노드 하나가 부품(`nodes[0]`, 이름은 부품 id), 그 아래 **더한 요소(`operation: add`)마다 노드 하나와 메시 하나**다. 요소의 `position`과 `orientation`이 노드의 `translation`과 `rotation`이고 꼭짓점은 기본형 자신의 좌표다. 한 요소는 한 프리미티브(`TRIANGLES`, `POSITION`, `NORMAL`, 인덱스)다.
- 장면 이름은 `<부품 id>-scene`이고 루트 노드 이름이 부품 id다(로더가 같은 이름을 바꾸지 않도록 다르게 둔다). 재질은 `materials[0]` 하나이고 모든 프리미티브가 쓴다(부품 하나는 재료 하나, B-01a와 같은 규칙). 텍스처·이미지·외부 파일이 없다.
- 좌표: 꼭짓점과 요소 자세는 Project 부품 로컬 좌표(오른손, +Z 위, m)다. glTF는 +Y가 위라서 루트 노드가 x축 둘레 −90° 회전(`-√½, 0, 0, √½`)을 지니고, 그래서 어떤 glTF 뷰어에서도 부품이 바로 선다. Project 좌표로 일하는 클라이언트는 이 회전을 무시하면 된다(`extras.kinetra.frame`에 적었다).
- 길이와 파라미터: 치수와 위치는 `AxisExpr`을 파라미터 값으로 계산한 값이라 파라미터를 바꾸면 메시가 따라 바뀐다(`test_gltf_follows_the_recipe_and_its_parameters`).

## 삼각형 분할 (결정적)

| 기본형 | 분할 | 부피 |
|---|---|---|
| 상자 | 면마다 꼭짓점 4개(평평한 법선), 삼각형 12개 | 정확하다 |
| 원기둥(축은 로컬 z) | 옆면 64분할(부드러운 법선), 뚜껑은 중심점 부채꼴(평평한 법선) | 내접 다각형 기둥: $\tfrac n2 r^2\sin\tfrac{2\pi}{n}\,h$, $n=64$. 참값의 약 99.84% |
| 구 | 경도 48, 위도 24, 극은 부채꼴(퇴화 삼각형 없음), 꼭짓점이 구면 위 | 내접 다면체. 참값보다 작다(약 99.3%) |

분할 수는 `_tessellate.py`의 상수이고 파일의 `extras.kinetra.tessellation`에도 적는다. **그려진 부피는 닫힌 식 부피(`mass_properties`)보다 원기둥·구에서 조금 작다.** 질량·관성은 닫힌 식에서 오고 메시를 읽지 않는다(A1). 테스트가 분할 부피를 내접 다각형의 손계산 식과 $10^{-6}$ 상대 오차로 대조하고, 모든 메시가 닫혀 있고(모든 모서리가 반대 방향으로 정확히 두 번) 부피가 양수(바깥쪽 감김)인지 본다.

## 빈 곳은 파내지 않는다

`operation: subtract` 요소는 **그리지 않는다.** CAD 불리언 없이는 상자에서 구멍을 파낼 수 없다(B-01a의 결정과 같은 이유). 파일은 이를 숨기지 않는다: `nodes[0].extras.kinetra.voids`에 요소 id, 기본형, 치수, 중심(`{x, y, z}`), 방향(`{x, y, z, w}`, Project와 같은 모양)이 있다. **신호는 이 목록 하나다.** 목록이 비어 있지 않으면 그 부품의 그림에는 구멍이 없고 질량만 구멍을 뺀 값이다. 그러니 구멍 난 판은 화면에서 구멍 없는 판으로 보인다.

클라이언트는 목록이 비어 있지 않을 때 "빈 곳 N개 미표시"를 보여야 한다(`client-adapter.md` A7). 증거 페이지(`tools/gltf-check/page`)가 그 예다: 빈 곳을 주황 외곽선으로 그리고 제목 줄에 개수를 적으며 `result.json`의 `undrawn_voids`에 싣는다. 시각 메시에서 실제로 파내는 일은 #496(B-01g)이다(질량·관성의 커널 계산인 #484와 다른 일이다).

## 재질 슬롯

`Material.id`로 B-07 카탈로그를 찾는다(`load_material_catalog().get(id)`). 있으면 그 항목의 `PbrSlots`, 없으면(사용자 선언 재료) **중립 대체 외형**(`#808080`, metallic 0, roughness 0.5, reflectance 0.5, 모두 `default` 배지)이다. 다른 재료의 외형을 빌리지 않는다(`materials.md`의 규칙).

| 슬롯 | glTF |
|---|---|
| `base_color`(sRGB) | `pbrMetallicRoughness.baseColorFactor` = **선형 RGB** $[f(r), f(g), f(b), 1]$, $f(c)=c/12.92$ ($c\le0.04045$), 아니면 $((c+0.055)/1.055)^{2.4}$ (IEC 61966-2-1). sRGB 숫자를 그대로 넣으면 금속이 눈에 띄게 밝아진다(알루미늄 `#e8eaea`의 R은 0.9098이 아니라 0.8070) |
| `metallic`, `roughness` | `metallicFactor`, `roughnessFactor` |
| `reflectance` | glTF core에 대응이 없다. 0.5(F0 0.04, 굴절률 1.5)면 쓰지 않는다(카탈로그 다섯은 모두 0.5). 다른 값이면 `extensionsUsed: ["KHR_materials_ior"]`와 `ior = (1 + 0.4 r) / (1 - 0.4 r)` |

`pbr=`로 외형을 넘기면 카탈로그 대신 그 값을 쓰고 `pbr_from_catalog`는 `false`다(`reflectance`가 0.5가 아닌 외형을 보이려는 고정 파일 `reflectance-ior.glb`가 그렇게 만든다: 유전체 외형이라 `ior`가 그림에 영향을 준다). 값의 배지와 출처는 파일의 `materials[0].extras.kinetra.pbr`에 그대로 실려 간다(V5: 외형도 "측정이 아니라 고른 것"이라는 `default`·`estimate` 배지를 잃지 않는다). `pbr_from_catalog`가 카탈로그 항목인지 아닌지(대체 외형 또는 호출자의 외형) 말한다. 색, 거칠기는 외형 선택이라 이 파일이 재료의 물성을 주장하지 않는다.

## 검증

- **구조 검증(Python, 항상).** `tests/gltf_validate.py`는 명세에서 다시 쓴 독립 점검이다: GLB 컨테이너(길이, 4바이트 정렬, 청크), 접근자 경계와 `min/max`와 실제 값, 법선 길이 1, 인덱스 범위, 퇴화 삼각형 없음, 노드 트리(순환, 부모 하나), 확장 선언과 사용 일치. 고장난 파일을 만들어 이 점검이 실패하는 것도 확인한다.
- **공식 검증기.** `tools/gltf-check`가 Khronos `gltf-validator`(`Apache-2.0 AND BSD-3-Clause AND MIT AND Zlib`, 컴파일된 JS 안의 Dart SDK 등 때문)를 `packages/engine/tests/fixtures/gltf/`의 4개 파일에 돌려 **오류 0, 경고 0**을 요구한다(`pnpm --filter @kinetra/gltf-check validate`, web CI의 `pnpm test`). 파일은 `uv run python packages/engine/tests/gltf_samples.py`가 쓰고, `test_gltf_committed_fixtures_are_current`가 코드와 같은지 지킨다.
- **웹에서 로드한 스크린샷(증거).** `pnpm --filter @kinetra/gltf-check capture`가 같은 파일을 three.js `GLTFLoader`로 읽어 헤드리스 Chromium에서 그리고 `out/gltf-check/parts-gltf.png`와 `result.json`을 남긴다. 카메라는 장면 경계 상자의 꼭짓점 8개가 모두 화면의 92% 안에 들 때까지 물러난다(`max_ndc`를 `result.json`에 싣고 시험이 1 미만을 단언한다). `screenshots` 워크플로가 PR마다 돌려 아티팩트로 올린다. 이 실행은 무거운 실행이라 자원 가드를 거친다(`docs/process/dev-resources.md`).
- 한계: 검증기는 파일이 glTF 명세에 맞는지만 말한다. 보이는 모양이 옳은지는 위의 손계산 부피·법선·자세 테스트와 스크린샷이 본다.
