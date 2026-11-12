# 접촉 매개변수와 마찰 합성 (X-01e)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/compiler/contact.py`(`contact_friction`, `ContactFriction`, `GeomFriction`, `CONTACT_PARAMETERS`, `contact_labels`), MJCF에 쓰는 곳은 `mjcf.py`(`to_mjcf(tree, ..., ground_friction=None)`), 행성 지면 마찰은 `planet.py`(`PlanetPhysics.ground_friction`). 테스트 `packages/engine/tests/test_contact_friction.py`(`uv run pytest packages/engine -q -k contact_friction`). 결정론적이라 시드가 없다(난수를 쓰지 않는다).
- 근거: 이슈 #545, `materials.md`(`Material.friction`, 마찰 계수 절), `parts-wheel.md`(트레드 마찰 사양), `bodies.md`(지면 마찰 분포와 "tan φ는 상한"), `body-tree.md`, MuJoCo 문서 [XML reference](https://mujoco.readthedocs.io/en/stable/XMLreference.html)(`geom/friction`·`priority`·`condim`, `option/cone`·`impratio`)와 [Modeling: Contact parameters, Slow slippage](https://mujoco.readthedocs.io/en/stable/modeling.html), 2026-11-12에 읽음. MuJoCo는 4.0.0(`docs/decisions/engine.md`).
- 범위 밖: 지면 마찰의 분포에서 표본을 뽑는 일, 몬테카를로, 판정 가정표의 행성 행 합성(W-03c). 두 재료 쌍별 마찰표(재료 DB, S2). 타이어 변형·미끄럼비 곡선.
- 지형 소품(W-05, [`terrain-props.md`](terrain-props.md)): 경사로·턱 geom도 같은 규칙을 탄다. 재료가 있으면 `Material.friction`, 없으면(`material` None) 행성 지면이라 지면 평면과 같은 계수(공칭 또는 `ground_friction` 표본)다. `ContactFriction.props`(`PropFriction`)가 소품마다 출처(`ground`/`material`)와 계수를 갖고, priority 순위에 소품 계수도 들어간다.
- 실행(X-02a `PreviewRun`): `run_started.model_labels`가 `model_labels(tree)`(`proxy_labels`, `contact_labels`, W-03b의 `drag_labels` 순)를 싣는다. 컴파일된 모델에 지면이 있으므로 "미적용: 지면 없음" 라벨은 나오지 않는다(`test_simulate_stream`이 둘 다 확인).

## 쓰는 법

```python
from kinetra_engine.compiler import build_body_tree, contact_friction, contact_labels, to_mjcf
tree = build_body_tree(project)
xml = to_mjcf(tree, drives=..., ground_friction=None)   # 지면 평면 + geom마다 friction·priority + 접촉 매개변수
friction = contact_friction(tree, ground_friction=None)  # geom별 μ와 출처, 지면 μ와 행성 Assumption
labels = contact_labels(friction)                        # 근사 라벨(ModelLabel, kind "contact")
```

`ground_friction`은 지면의 계수다. `None`이면 행성의 공칭(`data/bodies`의 `ground_friction.value`)이고, 몬테카를로 표본(W-03c)은 이 인자로 들어간다. 행성 분포의 지지 밖 값(uniform이면 `[low, high]` 밖, normal이면 clip 밖)은 `ValueError`다. 표본은 행성 데이터에서만 오고 호출하는 쪽이 고르지 않는다(규칙 C4).

## geom 하나의 마찰

인스턴스마다 쿨롱 계수 하나를 정하고 그 인스턴스의 충돌 프록시 geom 모두에 준다. 위에서부터 처음 맞는 것:

| 순서 | 조건 | μ | 배지·출처 |
|---|---|---|---|
| 1 | 부품 사양에 `tread_friction_kinetic`이 있다(B-03a 휠) | 그 사양 값(휠 0.7) | 사양의 배지·출처 그대로(`cite`, OpenStax 표 5.1) |
| 2 | 인스턴스에 재료가 있다 | `Material.friction` | 재료의 배지·출처 그대로(B-07) |
| 3 | 둘 다 없다(선언 질량 부품: 모터, 배터리, 밸러스트 …) | 1 | `기본값`: MuJoCo `geom/friction`의 기본 미끄럼 계수, 라벨이 붙는다 |

- **운동 계수 하나.** MuJoCo는 접촉마다 미끄럼 계수 하나만 쓴다(정지·운동 구분 없음). `Material.friction`은 운동 계수이고 휠도 운동 계수(0.7)를 쓴다. 트레드의 정지 마찰 1.0은 쓰지 않는다. 미끄럼이 시작되는 각이 정지 계수가 아니라 운동 계수로 정해지므로 오르막 그립은 낮은 쪽이다(라벨).
- **트레드 사양이 재료보다 앞선다.** 휠은 재료가 림(POM 0.21)이고 땅에 닿는 것은 고무 트레드다. 사양이 부품 단위라서 휠의 일곱 원기둥 모두가 0.7을 받는다. 평지에서는 `tire`만 닿지만(`parts-wheel.md`) 턱에 림이 닿으면 림도 0.7이다(라벨).
- 재료가 있어도 사양이 없는 부품은 재료 값이다. 사양 이름은 `TREAD_FRICTION_SPEC`이고 휠이 아니어도 이 사양을 내는 부품은 같은 규칙을 탄다.

## 두 면의 합성: 작은 쪽(min)

접촉하는 두 면의 계수가 $\mu_1, \mu_2$이면 접촉의 계수는 $\min(\mu_1, \mu_2)$이다. 부품끼리도, 부품과 지면도, 부품과 지형 소품도 같다.

- **MuJoCo의 기본은 max다.** 두 geom의 `priority`가 같으면 원소별 최댓값, 다르면 높은 priority geom의 값을 쓴다(Modeling, "Contact parameters"). 컴파일러는 모델의 서로 다른 계수(지면 포함)를 큰 것부터 줄 세워 그 순번을 `priority`로 준다. 작은 계수일수록 priority가 높아 접촉마다 작은 쪽이 이긴다. 계수가 같으면 priority도 같고 max = min이다. 테스트가 모든 geom 쌍에 대해 MuJoCo 규칙으로 고른 값이 min임을, 그리고 실행 중 `data.contact[].friction`이 정확히 min임을 확인한다.
- **왜 min인가.** (1) 지면 값 tan φ는 흙 대 흙의 내부 마찰각이고 부품이 흙 위를 미끄러질 때의 계면 값의 **상한**이다(`bodies.md`: 계면 δ < φ). max는 0.21인 POM 부품에게 흙의 0.56을 줘 이 상한을 무시한다. (2) 판정이 묻는 것은 주로 그립(오르막, 제동)이고 작은 계수가 그쪽의 보수적인 값이다. (3) 재료 값은 "대 강철"의 쌍 값이다(`materials.md`). 두 재료가 만나는 실제 값은 표에 없고 어느 규칙도 물리적으로 맞다고 말할 수 없다. 그래서 규칙을 라벨로 드러낸다.
- 다른 엔진의 관례(곱, 기하평균, 산술평균)도 물리 근거가 없다. min을 고른 이유는 위의 상한과 보수성이다.

예(공칭 지면): 강 A36 블록(0.23)은 세 행성 모두 0.23(부품이 정한다), 휠 트레드(0.7)는 지구 0.5628, 화성 0.5126, 달 0.6573(지면이 정한다). 지면 분포의 상한(달 0.9004)이 트레드 0.7보다 크므로 W-03c의 표본이 0.7을 넘으면 휠의 계수는 0.7에서 멈춘다.

## 접촉 매개변수

`to_mjcf`가 `<option cone="elliptic">`과 `<default><geom condim solref solimp/></default>`로 모든 geom에 같은 값을 쓴다. 같은 값이라 priority가 이 값들을 바꾸지 않는다. `CONTACT_PARAMETERS`가 값마다 배지와 출처를 갖는다.

| 매개변수 | 값 | 배지 | 뜻과 이유 |
|---|---|---|---|
| `condim` | 3 | `기본값` | 법선력과 접평면의 미끄럼 마찰. 비틀림·구름 마찰이 없어 구름 저항이 0이다(라벨) |
| `cone` | `elliptic` | `추정`(Kinetra의 선택) | MuJoCo 기본은 `pyramidal`. 타원 원뿔은 모든 접선 방향에서 $|f_t| \le \mu f_n$인 쿨롱 원뿔이고, 피라미드는 모서리 밖 방향에서 원뿔 안쪽에 있어 미끄럼 각이 접촉 좌표계 방향에 따라 달라진다. MuJoCo 문서: "Elliptic cones are a better model of the physical reality" |
| `solref` | `0.02 1` | `기본값` | 소프트 접촉의 시간 상수 0.02 s, 감쇠비 1 |
| `solimp` | `0.9 0.95 0.001 0.5 2` | `기본값` | 침투 1 mm에 걸친 임피던스 0.9 ~ 0.95 |

쓰지 않은 것: `impratio`(기본 1 그대로, 테스트가 확인), `margin`·`gap`(0), `noslip_iterations`(0), 명시적 `<pair>`. `impratio`를 올리면 아래의 느린 미끄럼이 줄지만(작업 중 0.1 m 정육면체로 재 보니 10배에 느린 미끄럼 속도가 10분의 1; 테스트에는 없다) MuJoCo 문서는 "올려라"만 쓰고 값을 주지 않아 고를 근거가 없다. 대신 라벨로 드러낸다.

## 근사 라벨

`contact_labels(friction)`이 낸다(`ModelLabel.kind = "contact"`). 모델 전체에 셋, 인스턴스 ID 순으로 해당하는 인스턴스마다 하나.

| 범위 | 텍스트 |
|---|---|
| 모델 | `근사: 접촉 마찰은 두 면 중 작은 계수, 정지·운동 구분 없이 운동 마찰 계수 하나` |
| 모델 | `근사: 소프트 접촉이라 정지 마찰 범위 안에서도 느리게 미끄러짐` |
| 모델 | `근사: 구름·비틀림 마찰 없음(미끄럼 마찰만)` |
| 트레드 사양 인스턴스 | `근사: <인스턴스>의 모든 접촉 면에 트레드 마찰 <μ>` |
| 재료도 사양도 없는 인스턴스 | `기본값: <인스턴스>의 마찰 1(재료도 트레드 사양도 없음, MuJoCo 기본값)` |

지면 마찰의 분포 행은 행성의 것이라 판정 가정표에서 W-03c가 합친다(`bodies.md`).

## 시험 (DoD 증거)

경사는 행성 중력을 y축 둘레로 θ 돌린 $g(\sin\theta, 0, -\cos\theta)$다(X-01b 구름 시험과 같은 방식, 블록은 지면에 닿은 조립체). 블록은 0.1 × 0.1 × 0.02 m 판이라 78.7°까지 넘어지지 않는다. 두 재료 조합: 카탈로그 강 A36(0.23, 세 행성 지면보다 작아 **부품이 정한다**)과 시험이 선언한 1.0(세 행성 지면보다 커서 **지면이 정한다**).

| 시험 | 기대(손계산) | 측정 |
|---|---|---|
| 미끄럼 시작 각, 2 조합 × 3 행성(이분법, 0.02° 간격, "가속도 > 1e-3 g"를 미끄럼으로) | $\theta_s = \tan^{-1}\mu_{합성}$ | 여섯 경우 모두 +0.049°(문턱 1e-3 g 자체가 약 0.05°의 기울기), 허용 0.1° |
| $\theta_s + 5°$에서의 가속도 | $a = g(\sin\theta - \mu\cos\theta)$, 역산한 μ | 상대 -1.5e-4 ~ +3.3e-4, 허용 1e-3. 접촉 계수는 정확히 min |
| 지면 분포 양 끝(low, high)을 `ground_friction`으로 | 역산한 μ = 그 끝값 | 1.6e-3 안(지구 high 0.7813, 경사 43°), 허용 3e-3 |
| $\tan\theta = 0.9\mu$에서 1 s | 가속하지 않음 | $|a|/g$ < 1e-8, 느린 미끄럼 0.52(지구), 0.20(화성), 0.087(달) mm/s |
| 모든 geom 쌍(휠 + 지면, 3 행성) | MuJoCo 규칙으로 고른 값 = min | 일치 |

재현: `uv run pytest packages/engine -q -k contact_friction`. 시드 없음.

## 한계 (숨기지 않는다)

- **합성 규칙은 물리 법칙이 아니라 선택이다.** 재료 값은 대 강철이고 지면 값은 흙의 내부 마찰각이라 두 면의 실제 계면 값은 어디에도 없다. min은 상한과 보수성 때문에 골랐다.
- **정지 마찰이 없다.** 운동 계수 하나라서 정지 마찰이 더 큰 실제(트레드 1.0 대 0.7) 보다 미끄럼이 일찍 시작된다.
- **느린 미끄럼.** MuJoCo의 소프트 접촉은 정지 마찰 범위 안에서도 정확히 멈추지 않는다(Modeling, "Slow slippage"). 위 측정으로 지구에서 0.1 m 판이 1 s에 약 0.5 mm 미만이고 중력이 작을수록 느리다. 긴 실행에서는 누적된다.
- **구름 저항이 없다**(condim 3). 평지에서 굴러가는 휠은 공기 항력(W-03b) 말고는 멈추게 하는 힘이 없다.
- 휠의 림·허브도 트레드 계수를 받는다(사양이 부품 단위).
- 재료도 사양도 없는 부품은 MuJoCo 기본값 1을 쓴다. 출처가 있는 측정값이 아니라 엔진의 기본값이다(라벨).
