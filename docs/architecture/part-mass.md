# 형상에서 질량·관성 (B-01a)

- 상태: 구현됨. 모델은 `packages/core/src/kinetra_core/`의 `shape.py`(레시피), `geometry.py`(길이식, 위치, 쿼터니언), `massprops.py`(결과). 계산은 `packages/engine/src/kinetra_engine/parts/mass.py`. 테스트는 `packages/engine/tests/test_inertia.py`, `packages/core/tests/test_shape.py`.
- 근거: `docs/plan/studio-plan.md` 3절(build123d port), 5절, `docs/architecture/client-adapter.md` D4(파생값은 코어가 계산해 배지와 함께 보낸다), 이슈 #92, C-01a의 "알려진 확장"(형상 레시피와 파생값의 입력).
- 범위 밖: 충돌 프록시(B-01b), glTF(B-01c, `part-visual.md`), 캐시(B-01d, `part-cache.md`), 부품 종류와 실재료 값(B-02, B-03, B-07), STEP·STL(HW-02).

## 쓰는 법

```python
from kinetra_engine.parts import mass_properties
result = mass_properties(part_def, material)                  # 파라미터는 PartDef의 기본값
result = mass_properties(part_def, material, {"width": q})   # 덮어쓸 파라미터는 Quantity(m), 범위 안, 자기 배지와 출처를 가진다
```

`PartDef.shape`(없어도 되는 필드)가 레시피다. 결과 `MassProperties`는 `volume`(m^3), `mass`(kg), `center_of_mass`(m, 부품 로컬 좌표), `inertia`(kg·m^2, 무게중심 기준, 부품 축, 행렬 성분 부호: `ixy = -∫xy dm`)와 `derivation`이다. `uv run pytest packages/engine -q -k inertia`.

## 레시피

- 요소(`ShapeComponent`)는 기본형 하나(`box`: 전체 길이 `size_x/y/z`, `cylinder`: `radius`·`length`로 축은 로컬 z, `sphere`: `radius`), `operation`(`add` 재료, `subtract` 빈 곳), 중심 위치, 방향(쿼터니언, 기본 항등)이다.
- 모든 치수와 위치는 `AxisExpr`(`offset + Σ factor × 길이 파라미터`, 스냅 포인트와 같은 식)라서 파라미터를 바꾸면 질량이 따라 바뀐다.
- 레시피 전체에 배지 하나와 출처 하나가 붙는다(스냅 포인트의 자세와 같은 규칙). 누가 이 치수를 정했는지(`사용자 선언`, 도면을 인용한 `인용` 등)를 뜻한다.
- `PartDef` 검증: 치수 식이 참조하는 파라미터는 있어야 하고 길이(m)여야 하며, 모든 치수는 **파라미터의 전 범위에서 0보다 커야** 한다(식이 선형이라 범위 양 끝에서 확인한다).

## 계산

- 부피 $V$: 상자 $abc$, 원기둥 $\pi r^2 h$, 구 $\tfrac43\pi r^3$. 질량 $m=\rho V$ ($\rho$는 `Material.density`).
- 자기 중심 관성: 상자 $\tfrac{m}{12}(b^2+c^2)$ 등, 원기둥 $I_{zz}=\tfrac12 mr^2$, $I_{xx}=I_{yy}=\tfrac{m}{12}(3r^2+h^2)$, 구 $\tfrac25 mr^2$. 요소의 방향 $R$로 $R\,\mathrm{diag}\,R^\top$.
- 합성: 무게중심은 부호 있는 질량의 가중 평균(빈 곳은 음의 질량), 관성은 평행축 정리 $I=I_c+m(d^2\mathbf 1-\mathbf d\mathbf d^\top)$를 더한다(빈 곳은 뺀다).

## 요소는 겹치지 않는 합이다 (가정과 거절)

부피를 부피의 합으로 구하므로 아래가 성립해야 맞다. 모델은 CAD 불리언을 하지 않는다.

1. 더한 요소끼리 내부가 겹치지 않는다. 2. 뺀 요소끼리 겹치지 않는다. 3. 뺀 요소는 더한 요소 하나 안에 완전히 들어 있다.

계산은 분리 평면(분리축) 검사와 포함 검사로 이를 확인해 **깨지면 `ShapeError`로 거절한다**(조용히 두 번 세지 않는다). 공차는 비교하는 두 요소의 큰 쪽 크기에 비례하고(1e-9), 요소의 위치나 다른 요소와 무관하다. 빈 곳의 원기둥 포함은 림 곡선 $|a+r(\cos t\,p_1+\sin t\,p_2)|^2$의 전역 최댓값을 구간 분할과 이계도함수 상한으로 증명한다(증명 예산을 넘기면 통과가 아니라 거절). 면·모서리가 닿는 것은 겹침이 아니다. 한계(과소 보고가 아니라 과대 거절 쪽): 서로 비스듬한 두 원기둥이 모서리끼리 닿는 경우처럼 검사 방향 집합이 이름 짓지 못하는 접촉은 겹침으로 거절될 수 있다. 이 가정은 결과의 `derivation.assumptions`에 글로 실려 간다.

**물리성 검사.** 위 검사를 통과해도 공차 안으로 튀어나온 빈 곳이나 반올림이 비물리적 텐서를 남길 수 있다. 그래서 마지막에 질량이 양의 유한값인지, 관성의 주모멘트(야코비 고유값)가 음수가 아닌지, 삼각부등식(Ia+Ib≥Ic)을 지키는지를 상대 1e-9로 확인하고 아니면 `ShapeError`(`not physical`)로 거절한다. 컴파일러(X-01a)가 MuJoCo에 넘기기 전에 비물리적 관성을 사유와 함께 막는 용도이고, MuJoCo 쪽 거부 조건과 같은지는 확인하지 않았다 [확인 필요].

**못 하는 것(커널이 필요하다).** 더한 요소에 걸치거나 밖으로 튀어나온 빈 곳(안장 홈, 가장자리 노치), 겹치는 요소의 합집합, 모깎기·모따기·나사산. 이런 부품은 요소를 겹치지 않게 나누어 쓰거나, 불리언이 가능한 형상 커널을 더하는 후속 이슈가 필요하다(아래 결정).

## 선언한 질량 (B-02c)

`PartDef.mass_parameter`가 kg 파라미터 하나를 가리키면 질량은 밀도×부피가 아니라 그 값이다(탑재체, 추, 데이터시트 질량). 레시피는 그 질량이 **어디에** 있는지만 말한다: 순부피에 균일하게 편다(유효 밀도 $\rho_{\mathrm{eff}} = m / V$). 무게중심과 관성은 같은 식에 이 밀도를 넣은 값이고 재료는 읽지 않는다(`material`은 `None`이어도 되고, 주어도 질량에 영향이 없다). `derivation.material_id`는 `None`이고 `derivation.density`는 선언한 값의 배지·출처를 그대로 가진 유효 밀도다. 선언한 질량도 `derivation.parameters`에 자기 배지와 함께 나온다. 균질이라는 가정은 `assumptions`에 그대로 적힌다. 실제 탑재체는 균질하지 않으므로 무게중심 위치는 "균일하다고 가정한 값"이다. 자세한 것: [`part-payload.md`](part-payload.md).

## 계산 근거와 배지 (V5, C-01a 알려진 확장)

결과의 값 네 가지는 모두 배지 `sim`("우리 계산이 낸 값")이고 출처는 계산 함수와 부품·재료 ID다. 그것만으로는 입력이 얼마나 단단했는지가 가려지므로 값은 `derivation`과 함께만 간다.

| `derivation` 필드 | 내용 |
|---|---|
| `shape` | 레시피의 배지와 출처 |
| `density` | 쓴 밀도와 그 배지·출처(`Material.density` 그대로) |
| `parameters` | 쓴 파라미터 값 각각의 `Quantity`(기본값이든 덮어쓴 값이든 자기 배지와 출처 포함) |
| `components` | 요소별 해석된 치수(`dimensions`: 이름·값 튜플. 상자 `size_x/y/z`, 원기둥 `radius`·`length`, 구 `radius`, m; 키가 기본형과 맞지 않으면 검증이 거절), 중심, 방향(쿼터니언), 부피, 질량, 더하기·빼기. 이것만으로 요소의 자기 관성과 평행축 항을 손으로 다시 계산할 수 있다 |
| `input_badges` | 위 입력 배지의 서로 다른 값(배지 순서). 검증이 `shape`·`density`·`parameters`의 배지와 대조해 다르면 거절한다(따로 고칠 수 없다) |
| `assumptions` | 균질 강체, 닫힌 식, 겹치지 않는 합 |

모든 필드가 튜플·불변이라 `MassProperties`는 해시된다. 캐시(B-01d, `part-cache.md`)의 키는 이 결과가 아니라 입력(정의, 재료, 파라미터)이다. 덮어쓴 파라미터는 `ParamValue` 같은 하위 클래스로 와도 평범한 `Quantity`로 바꿔 담아 JSON 왕복이 같다. `MassProperties`의 `badge`는 `sim` 하나로 고정되어 있어 `cite`나 `declared`로 위조할 수 없다(검증이 거절한다). 선언한 밀도로 낸 질량은 그 선언만큼만 맞다. 입력 배지를 하나로 합치는 규칙(X-07의 "가장 약한 입력", [`thrust-to-weight.md`](thrust-to-weight.md))은 소비하는 쪽이 정한다. 이 모듈은 순위를 정하지 않고 입력 배지를 그대로 내놓는다.

## 검증

- 변이 점검: `ixy` 평행축 부호, `iyz` 인덱스, 겹침 바디의 역회전, `_check_physical` 호출 삭제를 각각 넣으면 `test_inertia.py`가 실패한다.
- 겹침 공차는 상대 1e-9라서 맞닿게 놓으려는 돌린 요소를 7자리 정도로 적으면 반올림 방향에 따라 겹침으로 거절될 수 있다(`0.1414214` 통과, `0.1414213` 거절). 부품을 손으로 적는 B-02, B-03이 알아야 하고 `docs/process/add-part.md`의 "맞닿은 요소"에 규칙을 적었다(멀어지는 쪽으로 올림은 3~12자리 모두 통과, 내림은 7·8자리에서 거절, `repr(float)` 전체는 통과).

- 해석해가 있는 형상 3종(상자, 원기둥, 구)을 손계산 값과 $10^{-9}$ 상대 오차로 비교한다. 이어 L자 두 상자(평행축), 구멍 난 판, 두꺼운 관, 회전한 원기둥·상자(곱 관성 부호)도 손계산 값과 비교한다.
- 독립 수치 적분(z 방향 현을 격자 위에서 적분하는 방식이라 닫힌 식을 쓰지 않는다)과 상자+보어+옆으로 누운 막대+구의 합성체를 부피·무게중심·관성 모두 1% 이하로 비교한다.
- 겹침·포함 거절, 파라미터 범위, 배지 위조 거절, JSON 왕복, 결정론.

## 결정: B-01a는 build123d 없이 닫힌 식으로 구현한다 (확정)

- **상태: 확정.** #480 봇 리뷰 트리아지에서 omp가 수용했다(2026-11-11, `needs-founder` 아님). 이슈 DoD 문구는 "`PartDef` → build123d 형상 → 부피 × 밀도"였지만, DoD의 목적(형상에서 질량·관성)은 상자·원기둥·구에 대해 닫힌 식으로 정확히 충족된다.
- **커널이 필요하지 않다.** 상자·원기둥·구와 평행축 합성은 닫힌 식이라 커널 없이 정확하다. 커널의 값은 같은 식의 결과이거나 근사라서 해석해 기준을 대신하지 못한다.
- **자원 가드가 막았다.** 작성 시점 `resource_guard.py --profile heavy`는 SSD 여유 6.3 GiB로 차단(종료 코드 2)이었고 규칙 3에 따라 임계를 낮추지 않았다. 설치는 하지 않았다.
- **크기 [계산: PyPI 메타데이터, macOS arm64, cp312].** build123d 0.13.0 휠 0.37 MiB(라이선스 Apache-2.0). 닫힌 의존성 58개, 휠 합계 약 202 MiB: `threejs-materials` 85 MiB, `cadquery-ocp-novtk` 60 MiB(Apache-2.0), `scipy` 19 MiB, `scikit-learn` 7 MiB, `sympy` 6 MiB, `numpy` 5 MiB 등. 원장 행 58개가 필요하고 `lib3mf`는 macOS arm64 휠 크기를 확인하지 못했다. 설치해서 잰 값이 아니다.
- **레거시 `cad.py`는 질량을 계산하지 않았다.** 그것은 STEP·STL 내보내기(`write_part`)이고 부피만 반환했다. 이식할 질량 코드가 없다. 내보내기는 HW-02의 일이다.
- **후속: [#484 (B-01e) build123d 커널로 임의 형상 질량·관성](https://github.com/NomaDamas/Kinetra/issues/484).** 커널이 필요한 곳(겹치거나 걸친 빈 곳, 모깎기)은 거기서 자원 가드를 통과한 머신에 build123d를 더하고, 이 모듈의 닫힌 식과 커널 부피를 대조한다. 닫힌 식은 그때도 해석해 기준으로 남는다. STEP·STL은 HW-02, glTF는 B-01c.
