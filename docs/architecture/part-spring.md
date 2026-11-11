# 스프링-댐퍼 (B-03e)

- 상태: 구현됨. 모델은 `packages/core/src/kinetra_core/designspec.py`(`JointSpring`, `SpringStiffness`, `SpringDamping`, `Joint.spring`)와 `partdef.py`(`PartRole.SPRING_DAMPER`, 파라미터 이름 `SPRING_STIFFNESS`, `SPRING_DAMPING`). 계산은 `packages/engine/src/kinetra_engine/parts/spring.py`. 부품 정의는 `packages/engine/src/kinetra_engine/parts/library/spring-damper-lc075k06m.json`(같은 파일이 `schemas/examples/PartDef.spring-damper-lc075k06m.json`). 테스트 `packages/engine/tests/test_spring.py`, `packages/core/tests/test_designspec.py`(`spring`), `test_commands.py`(`spring`). `uv run pytest packages/engine -q -k spring`.
- 근거: 이슈 #105(DoD: 강성과 감쇠 파라미터, 질량-스프링 진동 주기를 수계산과 대조), C-01b(#62) 알림("`DesignSpec`에는 스프링-댐퍼 필드가 없다. 결합의 스프링·댐핑 필드와 부품 쪽 정의는 B-03e와 X-01b가 더한다. 결합 좌표 0은 저장된 자세다"), `docs/process/add-part.md`.
- 범위 밖: 연소, 노즐 유동, 타이어 변형. 스프링을 MuJoCo 결합의 `stiffness`·`damping`으로 바꾸는 일(X-01b), 결합의 축과 한계(B-04a), 코일의 모양과 코일 사이 접촉, 비선형(경화) 스프링, 스프링 자체 질량의 반영, 피로·좌굴·고유 진동(서지).

## 모델: 결합에 붙는 스프링

`Joint.spring`은 없을 수 있다(`None`: 스프링도 댐퍼도 없다). 있으면 `JointSpring`이다.

| 필드 | 뜻 | 슬라이더 | 힌지 |
|---|---|---|---|
| `stiffness` | 스프링 상수 k | N/m | N·m/rad |
| `damping` | 점성 감쇠 c | N·s/m | N·m·s/rad |

- 힘(토크) $F = -k\,q - c\,\dot q$. $q$는 결합 좌표이고 **0이 저장된 자세**다(C-01b). 스프링은 부품을 놓은 자세에서 쉰다. 다른 쉼 위치가 필요하면 자세를 옮겨 놓는다(MuJoCo의 `springref`에 해당하는 필드는 없다. X-01b가 0으로 넘긴다).
- 두 값은 각자 `Quantity`라서 **값마다 배지와 출처**가 있다(스프링 상수는 데이터시트의 `인용`이고 감쇠는 `기본값`인 부품이 그 예다). 0 이상이다. 둘 다 0이면 거절한다(아무것도 하지 않는 스프링은 필드를 빼라). 한쪽만 0인 것은 허용한다: 감쇠 0은 순수 스프링, 스프링 상수 0은 순수 댐퍼.
- 단위는 `Unit`에 있고 모델이 쌍으로 확인한다: 스프링 상수가 N/m이면 감쇠는 N·s/m이어야 한다. 결합 종류와 맞지 않으면 사유와 함께 거절한다("the spring of a hinge joint is in 'N*m/rad' and 'N*m*s/rad'"). 고정 결합에는 스프링이 없다(`limits`와 같다).
- 새 단위 `N*m*s/rad`(`Unit.N_M_S_PER_RAD`)를 더했다. N/m, N·s/m, N·m/rad는 이미 있었다.
- 명령은 새로 없다. 스프링을 더하고 빼는 것은 `replace_joint`가 한다(결합을 제자리에서 통째로 바꾼다. 역명령은 이전 결합의 `replace_joint`). 테스트가 더하기, 빼기, 되돌리기를 본다.

## 부품 역할 `spring_damper`

`role: "spring_damper"`인 `PartDef`는 아래를 만족해야 한다(어기면 `PartDef` 검증이 거절한다).

| 요구 | 이유 |
|---|---|
| 파라미터 `stiffness`와 `damping`이 있다 | 사용자가 바꾸는 값이다. 이름이 소비자(`joint_spring`, X-01b)와의 계약이다 |
| 단위쌍이 N/m와 N·s/m, 또는 N·m/rad와 N·m·s/rad다 | 선형(슬라이더)과 비틀림(힌지) 두 가지뿐이다 |
| `stiffness`의 최솟값이 0보다 크다 | 스프링이 없는 스프링-댐퍼는 부품이 아니다. 순수 댐퍼는 결합의 `spring`에 스프링 상수 0으로 쓴다 |
| `damping`의 최솟값이 음수가 아니다 | 음의 감쇠는 에너지를 만든다 |

`joint_spring(part, parameters=None)`은 부품의 기본값(또는 인스턴스가 정한 값)을 그 값의 **배지와 출처 그대로** `JointSpring`으로 만든다. 범위 밖, 다른 단위, 모르는 이름은 `mass_properties`와 같은 `ShapeError`다. 부품의 단위쌍이 붙일 결합의 종류와 맞는지는 `Joint`가 확인한다. 부품이 어느 결합에 붙는지를 `DesignSpec`이 따로 검사하지는 않는다(어느 인스턴스의 스프링 값이 어느 결합의 `spring`이 되는지는 사용자의 명령이고, 컴파일러 X-01b/X-01d가 자리를 맞춘다).

## 계산 (`kinetra_engine.parts.spring`)

질량-스프링-댐퍼 계 $I\ddot q + c\dot q + kq = 0$의 닫힌 식과 그 힘 법칙을 직접 적분한 값이다. `inertia`는 슬라이더에서 스프링에 매달린 질량 [kg], 힌지에서 축에 대한 관성모멘트 [kg·m²]다.

- `spring_response(spring, inertia)`: 고유진동수 $\omega_0=\sqrt{k/I}$, 감쇠비 $\zeta=c/(2\sqrt{kI})$, $\zeta<1$이면 감쇠진동수 $\omega_d=\omega_0\sqrt{1-\zeta^2}$와 주기 $T=2\pi/\omega_d$. $\zeta\ge1$이면 진동하지 않아 주기는 `None`이다. 감쇠 없는 주기 $2\pi\sqrt{I/k}$는 `undamped_period`로 따로 준다.
- `integrate(spring, inertia, q0=, v0=, duration=, dt=, force=)`: 고전 RK4로 $I\ddot q=-kq-c\dot q+F$를 적분한다. 닫힌 식을 쓰지 않는다. `force`는 일정한 힘(수직 슬라이더의 무게)이다. `Trajectory.measured_period()`는 위로 올라가며 0(또는 `about`)을 지나는 시각 사이의 평균 간격이다.
- 테스트는 같은 계를 두 길로 본다. (1) 손계산한 주기 $2\pi\sqrt{m/k}$와 (2) 적분한 궤적에서 잰 주기가 상대 오차 $10^{-7}$ 안에서 같다(`k=100, m=1`이면 0.628319 s, `k=4000, m=1`이면 0.099346 s, 라이브러리 부품의 강성 2770 N/m에 2.77 kg이면 0.198692 s). 감쇠 있는 계는 345 직각삼각형(`k=100, m=1, c=12`이면 $\zeta=0.6$, $\omega_d=8$ rad/s 정확히)과 닫힌 해의 점별 비교, 대수 감쇠율($e^{2\pi\zeta/\sqrt{1-\zeta^2}}$)로 본다. 임계 감쇠(c=20)와 과감쇠는 쉼 위치를 넘지 않는다.
- 행성: 무게는 쉼 위치를 $mg/k$만큼 옮길 뿐 주기를 바꾸지 않는다. 지구·화성·달의 중력은 `data/bodies`(W-01)에서 읽는다(이 모듈에 중력 상수가 없다). 같은 서스펜션의 처짐은 달에서 지구의 $1.62/9.80665$배다.
- 스프링 자체의 질량은 더하지 않는다(코일의 질량이 계의 유효 질량에 일부 들어간다는 보정은 하지 않았다). 라이브러리 부품의 질량은 13.6 g이라서 1 kg 이상을 매다는 용도에서는 무시할 만하다. 가벼운 것을 매다는 곳에서는 사용자가 `inertia`에 넣어야 한다.

## 라이브러리 부품: `spring-damper-lc075k06m`

Lee Spring 재고 압축 스프링 LC 075K 06 M(음선 ASTM A228, 양끝 평면 연삭). 제조사 제품 페이지의 값이고 값마다 출처 위치가 `source.locator`와 `url`에 있다(<https://www.leespring.com/product/compression-spring-lc075k06m-music-wire>, 2026-11-12에 읽음).

| 값 | 수치 | 배지 | 출처·이유 |
|---|---|---|---|
| 스프링 상수(기본값) | 2.77 N/mm = 2770 N/m | 인용 | 페이지의 "Rate (N/mm) 2.77"(15.82 lb/in, 공차 10 %) |
| 스프링 상수의 범위 | 100 ~ 100000 N/m | 기본값 | 우리가 정했다. 제품 한계가 아니다 |
| 감쇠(기본값) | 20 N·s/m | 기본값 | **우리가 정했다**. 페이지에 댐퍼가 없다. 1 kg에 매달았을 때 감쇠비 약 0.19가 되는 값으로, 새 댐퍼가 눈에 보이게 감쇠하라고 정했다 |
| 감쇠의 범위 | 0 ~ 2000 N·s/m | 기본값 | 우리가 정했다 |
| 질량 | 0.03 lb = 0.0136078 kg | 추정 | 페이지의 Weight 0.03 lb(소수 둘째 자리라 0.025~0.035 lb 안의 값이다). 스프링 하나의 질량이고 댐퍼 몸체의 질량은 어느 데이터시트에도 없어서 넣지 않았다. 반올림을 지우지 않았다. 사용자가 실제 질량을 선언한다(범위 0.001 ~ 2 kg) |
| 외형 | 자유 길이 50.8 mm, 바깥지름 21.46 mm, 선지름 1.91 mm | 추정(형상) | 페이지의 치수. 코일은 그리지 않았다: 여덟 개의 원판(바깥지름 × 선지름 두께)을 심 위에 쌓은 윤곽이고 끝판(지름 25 mm, 4 mm)과 심 반지름(4 mm)은 우리가 정했다 |

스냅 포인트 `end_a`(z = 0, 아래 끝판의 바닥 면)와 `end_b`(z = 0.0588 m, 위 끝판의 윗면)는 `사용자 선언`이다(`kind: spring_mount`, 받아들이는 태그 `spring_mount`, `surface`).

### 한계 (숨기지 않는다)

- **스프링 상수는 이 스프링 하나의 값이다.** 같은 이름으로 파는 다른 길이·선지름의 스프링은 다른 상수를 가진다. 파라미터의 범위(100~100000 N/m)는 "이 부품을 어떻게 쓰든 되는 범위"일 뿐 제품군의 범위가 아니다. 사용자가 바꾼 값은 인스턴스의 `ParamValue`가 가진 자기 배지(보통 `사용자 선언`)를 단다.
- **선형 스프링이다.** 실제 압축 스프링은 완전히 눌리면(밀착 높이 16.81 mm) 딱딱해지고 늘어나면 소성 변형한다. 이 모델은 결합의 `limits`로 이동 범위를 자르는 것 말고는 그 끝을 모른다. 밀착 높이에 맞춘 한계는 사용자가 정한다.
- **감쇠는 점성(속도에 비례)이다.** 실제 댐퍼는 속도에 따라 비선형이고 압축과 신장이 다르다. 20 N·s/m는 어떤 실제 댐퍼의 측정도 아니다.
- **외형은 윤곽이다.** 코일을 그리지 않았다(`add-part.md` 5절). 외형이 부품의 윤곽으로 읽히는지는 PR의 캡처로 사람이 판단한다.
- 스프링 상수의 공차(±10 %)를 몬테카를로로 흔드는 일은 이 PR에 없다(J-02의 가정표가 한다).
