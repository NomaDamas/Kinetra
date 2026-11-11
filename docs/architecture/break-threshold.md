# 결합부 임계 하중 (X-04a)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/break_threshold.py`(`critical_load`), 테스트는 `packages/engine/tests/test_break_threshold.py`(`uv run pytest packages/engine -q -k break_threshold`).
- 근거: 이슈 #137, `docs/plan/studio-plan.md` 4.6절("파단은 FEM이 아니라 결합부 임계값(물성 × 단면, '단순화 모델' 표시)"), `materials.md`(강도 기준 혼재), `project-model.md`(`Joint.break_threshold`), 핵심 가치 V1·V5.
- 범위 밖: FEM, 피로, 균열(이슈). 런타임에서 결합을 푸는 일(X-04b), 정지 하중과 임계의 비교(X-03b). 이 모듈은 하중을 받지 않고 임계만 낸다.

## 하는 일

`critical_load(material, section, mode, shear_planes=1)`은 한 단면이 견디는 하중 [N]을 `CriticalLoad`로 돌려준다. `.quantity`는 `BreakThreshold`(단위 N, 값 > 0)이므로 그대로 `Joint.break_threshold`에 넣을 수 있다. 이 모듈은 결합의 어느 부분(핀, 볼트, 용접, 부재)이 지배하는지 고르지 않는다. **호출자가 지배하는 단면을 정한다.**

| 모드 | 식 | 출처와 위치 |
|---|---|---|
| `tension`(단면에 수직) | $P_{crit} = S\,A$ | Beer, Johnston, DeWolf, Mazurek, *Mechanics of Materials* 7판(McGraw-Hill, 2015), 1.2A절 "Axial Loading: Normal Stress", 식 (1.5) $\sigma = P/A$ |
| `shear`(단면 안쪽), 한 면 | $V_{crit} = 0.577\,S_y\,A$ | 같은 책 1.2B절 "Shearing Stress", 식 (1.9) $\tau_{ave} = P/A$. 0.577은 Budynas, Nisbett, *Shigley's Mechanical Engineering Design* 9판, 5-5절 "Distortion-Energy Theory for Ductile Materials", 식 (5-21) $S_{sy}=0.577\,S_y$ |
| `shear`, 두 면(`shear_planes=2`) | $V_{crit} = 2\cdot0.577\,S_y\,A$ | Beer 외 1.2B절, 식 (1.10) $\tau_{ave}=F/2A$. `A`는 **한 전단면**의 면적 |

단면 `A` [m²]: `SolidCircle`($\pi d^2/4$), `Rectangle`($w\,h$), `Annulus`($\pi(D^2-d^2)/4$), `DeclaredArea`(직접 준 면적). 치수는 `Quantity`(m, 배지 포함)이다.

강도 $S$는 B-07 카탈로그의 `Material.yield_strength`다. 다섯 재료의 값은 `materials.md` 표에 있다.

## 정직하게 말하는 것

1. **"단순화 모델"** — 모든 결과에 `model = "단순화 모델"`과 레이블이 붙고, `BreakThreshold.source.ref`에도 "단순화 모델 (not FEM)"과 식, 강도, 면적이 적힌다. 배지는 `추정`(`estimate`)이다. 인용한 식으로 계산했지만 이 값은 시험이나 시뮬레이션 결과가 아니다.
2. **강도의 기준이 섞여 있다.** 6061-T6, CFRP, POM은 대표값, A36과 Ti-6Al-4V는 규격 최소값이다(`materials.md`). 모듈은 카탈로그가 `source.ref`에 적은 `Basis: TYPICAL` / `Basis: specified MINIMUM`를 읽어 `strength_basis`와 레이블("강도 기준: 대표값(typical), 보증된 최소가 아님" 등)에 싣는다. 구조화된 필드가 없어서 문자열에서 읽는다(#481). 문구가 없으면 `unstated`라고 말한다. 값을 바꾸거나 보정하지 않는다.
3. **다른 재료의 임계를 비교할 수 없다.** 모든 결과가 "다른 재료의 임계와 비교할 수 없다" 레이블을 갖는다. 같은 단면에서 6061-T6가 A36보다 큰 임계를 내지만(테스트가 고정한다) 기준 차이이지 재료 순위가 아니다.
4. **CFRP는 항복이 아니라 파단 강도다.** 카탈로그의 `yield_strength`가 0° 인장 파단 강도 828 MPa(항복점 없음, #481)이므로 인장 임계에는 쓰되 "파단 강도" 레이블을 붙이고, **전단 모드는 거부한다**(0.577 비는 연성 금속의 항복 이론이라 취성·이방성 복합재에 적용하지 않는다; 이 재료의 전단 강도는 카탈로그에 없다). #481이 필드의 뜻을 정하면 이 읽는 방식을 맞춘다.
5. **가정과 한계**(`CriticalLoad.assumptions`): 단면 위 균일한 공칭 응력(구멍·나사·필릿의 응력 집중 없음), 굽힘·벌어짐·복합 하중 없음, 하중은 스칼라이며 결합의 자유축 방향과 대조하지 않는다, 항복 시작 하중이지 파열 하중이 아니다, 정적 강도만(피로·균열·크리프·온도·변형률 속도·부식 없음), 이방성 없음.

## 손계산 대조 (테스트)

| # | 입력 | 계산 | 값 |
|---|---|---|---|
| 1 | A36 핀 d = 10 mm, 한 면 전단 | $A=\pi(0.005)^2=7.854\times10^{-5}$ m², $V=0.577\times248.2\times10^{6}\times A$ | 11 247.8 N |
| 2 | 6061-T6 막대 20×5 mm, 인장 | $A=1.0\times10^{-4}$ m², $P=276\times10^{6}\times A$ | 27 600 N |
| 3 | Ti-6Al-4V 관 D8/d4 mm, 두 면 전단 | $A=\tfrac{\pi}{4}(0.008^2-0.004^2)=3.770\times10^{-5}$ m², $V=2\times0.577\times828\times10^{6}\times A$ | 36 021.95 N |

식 인용 위치는 위 두 책에서 열어 확인했다: Beer 7판 본문(Internet Archive 전문 텍스트)에서 1.2A·1.2B의 식 번호 (1.5), (1.9), (1.10)을, Shigley 9판(같은 곳)에서 식 (5-20), (5-21)을. 쪽 번호는 판본마다 달라 적지 않았다. 두 책은 교재라서 값을 옮기지 않고 식과 위치만 인용한다.

## 열린 질문

- 이방성(CFRP)과 취성 재료의 강도 필드의 뜻과 기준 혼재의 정리는 #481에서 정한다. 그 결정 전까지 이 모듈은 위 4·2번대로 읽는다.
- 호출 쪽(어느 결합에 어느 단면을 쓰는지)은 이 이슈 밖이다. X-03b·X-04b·HW-03a가 정한다.
