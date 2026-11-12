# 스프링-댐퍼 (B-03e)

- 상태: 구현됨. 검증은 `packages/core/src/kinetra_core/partdef.py`(`PartRole.SPRING_DAMPER`, `PartDef._check_spring_damper`, 이름 상수 `SPRING_STIFFNESS`, `SPRING_DAMPING`), 계산은 `packages/engine/src/kinetra_engine/parts/springs.py`. 부품 정의는 `packages/engine/src/kinetra_engine/parts/library/spring-damper-lee-lc032b08.json`(같은 파일이 `schemas/examples/PartDef.spring-damper-lee-lc032b08.json`). 테스트 `packages/engine/tests/test_spring_damper.py`, 역할-액추에이터 규칙 쪽은 `packages/core/tests/test_designspec.py`(`uv run pytest packages/engine -q -k spring`).
- 근거: 이슈 #105(DoD: 강성과 감쇠 파라미터, 질량-스프링 진동 주기를 수계산과 대조), C-01b(#62) 알림(`DesignSpec`에는 스프링 필드가 없고 부품 쪽 정의는 이 잎과 X-01b가 더한다), `docs/process/add-part.md`, `part-motor.md`(역할 모델).
- 범위 밖: 연소, 노즐 유동, 타이어 변형. 스프링-댐퍼를 MuJoCo 결합의 `stiffness`/`damping`으로 바꾸는 일과 결합이 부품의 파라미터를 읽는 방법(X-01b), 결합 쪽 스프링 필드, 비선형 스프링(곡선 힘-변위), 코일이 완전히 눌린 뒤의 접촉, 좌굴, 피로.

## 모델: 강성과 감쇠는 부품의 파라미터다

`role: "spring_damper"`인 `PartDef`는 파라미터 두 개가 있어야 한다(어기면 `PartDef` 검증이 거절한다).

| 이름 | 단위 | 요구 | 이유 |
|---|---|---|---|
| `stiffness` | `N/m` | 범위의 최솟값이 0보다 크다 | 강성 0인 스프링은 스프링이 아니다. 어느 범위 값에서도 주기 $2\pi\sqrt{m/k}$가 정의돼야 한다 |
| `damping` | `N*s/m` | 범위의 최솟값이 0 이상이다 | 음의 감쇠는 운동에 에너지를 넣는다. **0은 허용한다**(감쇠 없는 스프링) |

파라미터라서 다른 부품 치수와 같은 규칙을 탄다: 기본값·최솟값·최댓값에 각각 배지와 출처가 있고, 인스턴스가 `Instance.parameters`로 자기 값을 정하며(범위 밖이면 `ShapeError`), 값이 바뀌면 컴파일 캐시 키가 바뀐다. 결합 좌표 0은 저장된 자세이고(`project-model.md`) 스프링의 힘 0점이다.

단위 `N/m`과 `N*s/m`은 C-01a가 `Unit`에 이미 두었다. 코어 모델에는 새 필드가 없으므로 정규 해시의 생략 기본값 목록(`test_hash_omitted_defaults_are_pinned`)과 스키마(`schemas/`)는 바뀌지 않는다. `DesignSpec`의 역할-액추에이터 규칙(`part-motor.md`)은 그대로다. 스프링-댐퍼 부품에 모터 액추에이터를 달면 거절된다.

## 계산 (`kinetra_engine.parts.springs`)

운동 방정식 $m\ddot x + c\dot x + kx = 0$의 교과서 해다. $x$는 결합 좌표 [m], 힘은 $F = -kx - c\dot x$.

- `spring_damper_characteristics(part, parameters=None)`: 기본값 또는 인스턴스 값의 `stiffness`, `damping`. 역할이 `spring_damper`가 아니면 `ValueError`, 범위 밖·단위 틀림·모르는 이름은 `ShapeError`.
- `spring_damper_force(k, c, x, v)`: $-kx - cv$.
- `oscillation(k, c, m)`: 고유 각진동수 $\omega_0=\sqrt{k/m}$, 주기 $T=2\pi/\omega_0$, 감쇠비 $\zeta = c/(2\sqrt{km})$, 임계 감쇠 $2\sqrt{km}$, $\zeta<1$일 때 감쇠 주기 $T_d = T/\sqrt{1-\zeta^2}$($\zeta\ge1$이면 `None`: 진동하지 않는다).

### 주기 검증 (DoD)

테스트는 기대값을 교과서 식으로 손계산해 적고, 같은 파일의 독립 4차 룽게-쿠타 적분기(`simulate`, `springs.py`의 코드를 쓰지 않는다)로 질량이 움직인 궤적을 만들어 **영점 통과 사이의 시간**을 재서 맞춘다. 부품의 `stiffness` 5990 N/m, 0.5 kg이면 $\omega_0=\sqrt{11980}=109.4532$ rad/s, $T=57.4052$ ms; 질량 0.05, 0.5, 5 kg에서 측정 주기가 $2\pi\sqrt{m/k}$와 상대 1e-6 안이다. 기본 감쇠 20 N·s/m이면 $\zeta=0.182727$, $T_d=58.3883$ ms, 한 주기마다 봉우리가 $e^{-2\pi\zeta/\sqrt{1-\zeta^2}}=0.31106$배가 된다(측정과 1e-3 안). 임계 감쇠($c=2\sqrt{km}$)에서는 영점을 지나지 않는다.

이 검증은 **식과 파라미터의 계약**이다. MuJoCo 결합 위의 같은 시험(컴파일된 모델의 진동 주기, 감쇠 주기와 봉우리 비)은 X-01b가 했다: [`joints-actuators.md`](joints-actuators.md).

## 라이브러리 부품: `spring-damper-lee-lc032b08`

Lee Spring 표준 압축 스프링 `LC 032B 08 S316`(스테인리스 316, 평연삭 끝)의 제품 페이지 값에 감쇠 파라미터를 더한 부품이다. 페이지: <https://www.leespring.com/compression-specific/331081>(2026-11-12 확인).

| 값 | 수치 | 배지 | 출처 |
|---|---|---|---|
| `stiffness`(기본) | 5990 N/m | `인용` | 페이지 "Rate (N/mm): 5.99"(34.2 lb/in) |
| 자유 길이, 솔리드 높이 | 19.05 mm, 11.43 mm | `인용` | 같은 페이지 |
| 바깥지름, 선지름 | 4.57 mm, 0.81 mm | `인용` | 같은 페이지 |
| 유효·전체 감김 수 | 11.82, 13.82 | `인용` | 같은 페이지 |
| 솔리드 높이 하중 | 45.64 N | `인용` | 같은 페이지 |
| `stiffness` 범위 | 100 ~ 100000 N/m | `기본값` | Kinetra가 고른 게임 규모 서스펜션 조절 범위. 데이터시트 값이 아니다 |
| `damping`(기본, 범위) | 20 N·s/m, 0 ~ 500 N·s/m | `기본값` | **코일 스프링의 데이터시트에는 감쇠가 없다.** 20 N·s/m은 0.5 kg 하중에서 감쇠비 약 0.18이 되게 Kinetra가 고른 시작값이고 측정이 아니다. 출처 문구에 식을 적었다 |
| `mass` | 0.673 g | `추정` | 페이지에 무게가 없다. 선 길이 $\pi(OD-d)\times$전체 감김 수 = 163.25 mm, 선 부피 $\frac{\pi}{4}d^2 L = 84.1$ mm³, 밀도 8000 kg/m³(오스테나이트계 스테인리스 일반값이고 공급자 값이 아니다). 최소=기본=최대라 고정이다 |
| 스냅 포인트 `end_a`, `end_b` | z = ∓9.525 mm | `사용자 선언` | 스프링 축 양끝 면의 중심(부품 원점은 자유 길이의 가운데, 축은 z) |

`stiffness` 5990 N/m는 코일식 $k = Gd^4/(8D^3n)$와도 맞춰 봤다: $d=0.81$ mm, $D=OD-d=3.76$ mm, $n=11.82$, $G=69$ GPa(316 스테인리스 일반값)이면 5909 N/m로 페이지 값보다 1.4 % 낮다. 페이지가 적은 비율 허용차(3.42 lb/in, 10 %) 안이다(`test_spring_rate_agrees_with_the_coil_formula_within_the_catalogue_tolerance`). 이 계산은 인용 값을 대신하지 않는 교차 검증이다.

### 한계 (숨기지 않는다)

- **외형은 원판 7장이다.** 감긴 선(나선)은 그리지 않는다. 바깥지름 4.57 mm, 자유 길이 19.05 mm의 포락선 안에 코일 한 바퀴 분량의 두께(자유 길이/13)로 감김을 나타낸 도식이다. 모양이 스프링으로 읽히는지는 PR의 캡처로 사람이 판단한다(`add-part.md` 5절). 질량 0.673 g은 이 원판 부피에 균일하게 편 것이라 관성은 그 가정의 값이다(실제 코일은 속이 비어 있다).
- **선형 스프링이다.** 힘은 변위에 비례한다. 실제 압축 스프링은 솔리드 높이 근처(변위 7.62 mm = 자유 길이 − 솔리드 높이)에서 접촉하고 끝 감김에서 비선형이다. 이 모델은 그 너머를 말하지 않는다(범위를 결합 한계로 제한하는 것은 사용자의 `Joint.limits`다).
- **감쇠는 점성(속도에 비례)이다.** 실제 댐퍼는 속도에 비선형이거나 마찰(쿨롱)이 섞인다. 20 N·s/m는 측정이 아니므로 사용자가 조절한다.
- 인용한 강성은 제조 허용차 ±10 %(페이지의 `p_rate_tolerance`) 안의 공칭 값이다. 몬테카를로의 파라미터 분포(M)는 이 허용차를 쓸 수 있으나 이 PR은 분포를 정하지 않는다.
- 부품은 한 쪽 끝에서 다른 쪽 끝으로의 축 방향 스프링 하나다. X-01b가 이것을 자기 스냅 포인트에 걸린 슬라이더 하나의 `stiffness`·`damping`으로 건다([`joints-actuators.md`](joints-actuators.md)). 휨·비틀림 스프링은 없다.

## 이 PR이 다른 문서에 한 일

`project-model.md`의 `PartDef.role` 항목과 "스프링-댐퍼는 B-03e·X-01b가 더한다" 문장, `part-motor.md`의 역할 절, `add-part.md`의 역할 절이 이 문서를 가리킨다.
