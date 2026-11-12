# 결합부 정적 하중 대 파단 임계 (X-03b)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/statics/static_load.py`(`static_loads`), 테스트는 `packages/engine/tests/test_static_load.py`(`uv run pytest packages/engine -q -k static_load`).
- 근거: 이슈 #134·#551, `docs/plan/studio-plan.md`의 정역학 행(실행 전 해석 검사, L0), `statics-tipover.md`(X-03a 지면 받침점), `contact.md`와 `compiler/contact.py`(X-01e 실제 MuJoCo 접촉 마찰), `break-threshold.md`(X-04a 임계 [N]), `project-model.md`(`Joint.break_threshold`: 이 값을 넘는 하중에서 결합이 풀린다), `body-tree.md`(결합이 인스턴스 위의 트리), 핵심 가치 V1.
- 범위 밖: 구조 응력 해석(부재 안의 응력, FEM). 런타임에서 결합을 푸는 일(X-04b), 화면 오버레이와 경고 목록(X-03c), 부정정 하중의 유일한 분배 선택.

## 쓰는 법

```python
from kinetra_engine.compiler import build_body_tree
from kinetra_engine.statics import static_loads
s = static_loads(build_body_tree(project))   # StaticLoads, 지면 아래로 파고든 도형이 있으면 TipoverError
s.joint("root").load, .moment, .axis_load, .threshold, .margin, .utilization, .exceeds
s.joint("weld").status                 # indeterminate이면 위 점값은 None
s.joint("weld").force_interval         # LoadInterval(lower, upper)의 월드 x/y/z 튜플 [N]
s.joint("weld").moment_interval        # 같은 형식 [N·m]
s.joint("weld").load_interval          # 힘 크기의 보수적 구간 [N]
s.joint("weld").axis_load_interval     # 힌지·슬라이더 자유축 성분 구간, 고정 결합은 None
s.tolerance                            # 지면 접촉 판정 수치 허용치 [m]; 힘 오차나 물리 침투가 아님
s.exceeding, s.caveats, s.assumptions
```

결과는 L0 해석 계산이다. 시뮬도 판정도 아니다(V1). 세계 좌표, SI(N, N·m, kg, m).

## 규칙

- **매달린 쪽.** 컴파일러는 결합(고정·힌지·슬라이더 모두)이 인스턴스 위의 트리를 이루는 설계만 받으므로(고정 고리·바디 고리·두 덩어리 거부, `body-tree.md`) 결합 하나를 끊으면 인스턴스가 두 쪽으로 갈린다. 강체 묶음이 아니라 인스턴스와 결합으로 나누므로, 임계가 있는 고정 결합을 X-04b가 용접하지 않고 두 강체로 두어도 하중은 같다(테스트). 지면 받침은 X-03a의 받침점(`tipover`의 `contacts`, 충돌 프록시가 z = 0에서 `tolerance` 안)이다.
  - 한쪽만 지면에 닿으면(`hanging`): 닿지 않는 쪽(매달린 쪽)에는 중력과 이 결합의 힘만 걸리므로 그 자유물체도가 하중을 정확히 준다. 힘 $F = (0, 0, -m g)$, 결합점에 대한 모멘트 $M = (c - p) \times F$. $m$과 $c$는 매달린 쪽 인스턴스들의 `MassProperties` 합(프록시에서 구하지 않는다), $p$는 결합 `a` 스냅점의 월드 위치(컴파일러가 결합을 놓는 점), $g$는 컴파일된 트리가 `data/bodies`에서 읽은 그 행성의 중력이다. `force`와 `moment`는 매달린 쪽이 결합(받치는 쪽)에 거는 값이고, 결합은 그 반대로 버틴다.
  - 양쪽 다 닿으면(`indeterminate`): 지면과 결합이 무게를 어떻게 나누는지 강체 정역학으로는 정해지지 않는다(미지 반력이 식보다 많다). `force`, `moment`, `load`, `axis_load`와 그 파생 여유는 계속 `None`이고 `exceeds`는 참이 아니다. 대신 아래 평형·접촉 조건을 만족하는 **모든 분배를 포함하는 구간**을 `force_interval`, `moment_interval`, `load_interval`, `axis_load_interval`로 낸다. 구간의 중간값이나 끝값을 유일한 하중으로 쓰지 않는다. 예: 네 바퀴 카트의 바퀴 축, 바닥에 나란히 놓고 용접한 두 블록.
  - 아무것도 닿지 않으면(`unsupported`): 떠 있거나 지형 소품에만 얹혀 있다(X-03a가 소품을 받침으로 세지 않는다).
- **임계와 비교.** `Joint.break_threshold`는 힘 [N] 하나다(X-04a). 그래서 크기 $|F|$(`load`)만 비교한다: `margin` = 임계 − 하중 [N], `utilization` = 하중 / 임계, `exceeds` = 하중 > 임계(임계는 그 값을 *넘는* 하중에서 풀린다는 뜻이라 같으면 넘지 않는다). 모멘트는 값으로 내지만 비교하지 않는다. 힘 임계는 굽힘을 말하지 않고, X-04a의 임계는 굽힘이 없다고 가정한다. 임계가 없는 결합은 끊어지지 않으므로(`Joint`) 여유가 없다(`None`).
- **자유축.** 힌지는 축 둘레 모멘트를, 슬라이더는 축 방향 힘을 버티지 못한다. `axis_load`는 하중의 그 성분이다(힌지: $M \cdot \hat{u}$ [N·m], 슬라이더: $F \cdot \hat{u}$ [N], $\hat{u}$는 `a` 스냅 틀의 결합 축을 월드로 옮긴 것, 부호는 그 축 방향). 모터·제한·스프링이 이만큼 버텨야 설계가 저장된 자세에 머문다. 0이 아니면 무언가 붙잡지 않는 한 결합이 움직인다.
- **정지하지 않는 설계.** 지면에 닿는데 X-03a가 안정이 아니라고 하면(여유 0 이하) 그 자세로 정지해 있지 않다. 하중은 그 자세로 붙잡아 둔 값이고 `caveats`가 그렇게 말한다.

## 부정정 구간의 방법·가정·출처 (#551)

결합의 `b` 쪽을 자유물체로 놓고, 그쪽 지면 받침점 $r_i$의 반력을 $R_i$, 그쪽 무게를 $W_b=(0,0,-m_bg)$라 한다. `b` 쪽이 `a` 쪽에 거는 힘과 결합점 $p$ 둘레 모멘트는 평형식에서

$$F=\sum_iR_i+W_b,\qquad M=\sum_i(r_i-p)\times R_i+(c_b-p)\times W_b.$$

설계 전체의 힘 평형에서는 결합을 통해 서로 미치는 힘이 상쇄되므로 전체 지면 수직 반력의 합은 전체 무게 $W$다. 각 받침점에서는 $R_{i,z}\ge0$이고 $\sqrt{R_{i,x}^2+R_{i,y}^2}\le\mu_iR_{i,z}$다. $\mu_i=\min(\mu_{geom},\mu_{ground})$는 추정치를 새로 넣은 값이 아니라 `contact_friction(tree)`가 실제 MJCF에 쓰는 명목 지면 마찰과 도형 마찰의 조합이다. 이는 MuJoCo `condim=3`(수직력과 미끄럼 마찰, 비틀림·구름 마찰 없음) 및 elliptic cone 설정과 같다. 출처: `docs/architecture/contact.md`, `compiler/contact.py`, [MuJoCo contact computation](https://mujoco.readthedocs.io/en/stable/computation/index.html#contact), [XML geom/solref/solimp](https://mujoco.readthedocs.io/en/stable/XMLreference.html#body-geom)(MuJoCo 4.0.0, 2026-11-12 확인).

구현은 이 조건을 더 넓은 성분별 부등식으로 완화한다. 예를 들어 $0\le\sum_iR_{i,z}\le W$에서 $F_z$의 끝은 $-m_bg$와 $W-m_bg$이고, 접선 성분의 절댓값 상한은 $\max_i\mu_iW$다. 모멘트는 $d=r_i-p$의 좌표별 최소·최대 레버와 같은 수직 반력 상한으로 묶는다. 마찰 원뿔의 $x/y$ 결합과 받침점 사이 상관을 버리므로 **보수적이지만 가장 좁은 구간은 아니다**. 힘 크기 구간은 이 성분 상자와 원점 사이 최소·최대 거리, 자유축 구간은 성분 구간의 축 투영이다. 부동소수 끝은 `math.nextafter`로 바깥에 한 ULP 벌린다.

접촉 `solref/solimp`가 정하는 강성·침투나 제작 오차·예압을 임의로 고르지 않는다. 구간은 모든 강성 선택의 정적 평형을 포함하지만 그중 하나를 예측하지 않는다. **유일한 값에 필요한 추가 입력**은 접점별 법선·접선 강성(또는 변형)과 초기 침투·예압 및 그것을 결합 변형과 함께 푸는 모델이다. 그 입력이 없으므로 유일한 분배, 구간 기반 `margin/utilization/exceeds`는 만들지 않는다.

## 가정 (`StaticLoads.assumptions`, 숨기지 않는다)

1. 모든 결합은 저장된 자세(좌표 0)에 고정되고 설계는 정지해 있다.
2. 하중은 중력뿐이다(추력, 모터 토크, 스프링 예압, 가속, 항력 없음).
3. 지면은 z = 0 평면이고 지형 소품은 받침으로 세지 않는다.
4. 한쪽만 지면에 닿으면 지면에 닿지 않는 쪽의 무게를 그 결합이 모두 진다.
5. 양쪽이 닿은 부정정 결합은 유일한 힘 대신 구간을 낸다. X-03a 받침점의 법선력은 0 이상, 접선력은 실제 모델의 쿨롱 마찰 원뿔 안에 있고 전체 지면 수직 반력의 합은 전체 무게다. 접촉 강성·침투·분배는 고르지 않으며 구간은 보수적 상·하한일 뿐 파단 여부가 아니다.
6. 임계는 힘 [N] 하나라 정정(`hanging`) 하중의 크기만 비교한다. 굽힘 모멘트와 하중 방향은 비교하지 않는다(X-04a 단순화 모델).
7. `StaticLoads.tolerance`는 저장된 좌표의 지면 접촉 판정에 쓰는 수치 허용치 [m]다. 물리 침투나 하중의 정확도 주장이 아니다.

## 손계산 대조 (테스트)

외팔보: 0.4 m 정육면체 벽(64 kg)이 지면에 있고, +x 면 높이 0.3 m에 0.6 × 0.1 × 0.1 m 팔(6 kg, 등분포 $w L$)을 용접하고, 팔 끝에 0.1 m 정육면체 끝 하중(1 kg)을 용접했다. 밀도 1000 kg/m³, 치수는 테스트가 정한 값(사용자 선언). $g$는 `load_body`로 `data/bodies`에서 읽는다(지구 9.80665 m/s², 인용 배지).

| 사례 | 손계산 | 결과 |
|---|---|---|
| 뿌리 결합(벽–팔) | 전단 $V = wL + P = 7g$, 모멘트 $M = wL^2/2 + P(L + 0.05) = g(6 \times 0.3 + 1 \times 0.65) = 2.45g$, +y 방향 | 같음(상대 1e-12) |
| 끝 결합(팔–끝 하중) | $V = 1g$, $M = 1g \times 0.05$ | 같음 |
| 뿌리에 A36 핀 d 1 mm 한 면 전단 임계(X-04a) | $0.577 \times 248.2\times10^6 \times \pi(0.0005)^2 = 112.48$ N, 여유 $112.48 - 7g$ > 0 | 같음, 넘지 않음 |
| 끝에 선언 임계 5 N | 여유 $5 - g$ < 0 | 같음, `exceeds`, `exceeding`에 이것만 |
| 같은 외팔보를 달에서 | $V = 7 g_{moon}$, $M = 2.45 g_{moon}$ | 같음 |
| 뿌리를 +y 축 힌지로 | 자유축 성분 $= M_y = 2.45g$ | 같음. +x 축(팔 방향) 힌지는 0 |
| 바닥에 나란히 용접한 0.2 m 정육면체 두 개(각 8 kg) | $W=16g$, $F_x,F_y\in[-16\mu g,16\mu g]$, $F_z\in[-8g,8g]$ | 같음(상대 1e-12) |
| 같은 두 블록의 모멘트 | $M_x\in[-1.6(1+\mu)g,1.6(1+\mu)g]$, $M_y\in[-(2.4+1.6\mu)g,(0.8+1.6\mu)g]$, $M_z\in[-4.8\mu g,4.8\mu g]$ | 같음 |
| 같은 두 블록의 힘 크기·+y 힌지 | $|F|\in[0,g\sqrt{2(16\mu)^2+8^2}]$, 힌지 구간은 위 $M_y$와 같음 | 같음. 점값 `load/axis_load`는 여전히 `None` |

두 블록 손계산에서 $\mu$는 도형 기본 마찰 1과 지구 지면 마찰 중 작은 값이고, 결합점은 $(0.1,0,0.1)$ m다. 오른쪽 블록 받침점의 상대 좌표는 $dx\in\{0,0.2\}$, $dy\in\{-0.1,0.1\}$, $dz=-0.1$ m다. 치수·밀도는 테스트가 정한 값(사용자 선언), $\mu$와 $g$는 `data/bodies` 및 MuJoCo 기본값에서 읽는다. 유일한 분배를 고르지 않고 반력 합의 범위만 대입한다.

그 밖에: 임계가 하중과 같으면 넘지 않고, 매달린 쪽이 결합의 `a` 쪽이어도 같은 하중이며, 임계가 있는 두 용접 때문에 강체가 1개에서 3개로 갈린 같은 외팔보도 힘·모멘트·지지 여유가 같고, 바닥에 나란히 용접한 두 블록은 `indeterminate`, 턱 위에만 얹힌 설계는 `unsupported`, X-03a의 넘어가는 받침+팔은 하중을 내면서 `caveats`로 정지하지 않는다고 말한다.

## 한계

- 부정정 결합은 보수적 구간만 낸다. 유일한 하중·여유·파단 여부는 접촉 강성(또는 변형), 초기 침투·예압과 결합 변형 모델이라는 추가 입력 없이는 정할 수 없다.
- 구간은 X-03a의 접촉 프록시 받침점을 쓰므로 원판의 내접 다각형 근사와 `tolerance` 안 점 합치기 근사를 그대로 잇는다. 마찰 원뿔과 반력 상관을 성분 구간으로 완화했으므로 실제 가능 영역보다 넓을 수 있다.
- 결합 하중은 결합부의 힘이지 부재 안의 응력이 아니다(구조 응력 해석은 범위 밖).
- 결과를 화면에 그리는 것과 경고 문구는 X-03c다.
