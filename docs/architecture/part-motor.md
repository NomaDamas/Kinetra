# 모터와 토크-속도 곡선 (B-03b)

- 상태: 구현됨. 모델은 `packages/core/src/kinetra_core/curve.py`(`Curve`)와 `partdef.py`(`PartRole`, `PartDef.role`, `PartDef.curves`). 곡선 계산은 `packages/engine/src/kinetra_engine/parts/curves.py`. 부품 정의는 `packages/engine/src/kinetra_engine/parts/library/motor-37d-12v-50-1.json`(같은 파일이 `schemas/examples/PartDef.motor-37d-12v-50-1.json`). 테스트 `packages/engine/tests/test_motor.py`, `packages/core/tests/test_curve.py`(`uv run pytest packages/engine -q -k motor`).
- 근거: 이슈 #102(DoD: 토크-속도 곡선과 질량, 사양은 데이터시트 출처 또는 `사용자 선언`, 무부하 속도와 정지 토크 테스트), C-01a 알려진 확장(곡선), `docs/process/add-part.md`.
- 범위 밖: 연소, 노즐 유동, 타이어 변형. 모터를 MuJoCo 액추에이터로 바꾸는 일과 명령 비율의 뜻(X-01b), 스케줄 편집(B-06d), 배터리 전력(B-03d), 추력기 곡선(B-03c, 같은 `Curve`를 쓴다).

## 곡선 모델 (`Curve`, `NamedCurve`)

`PartDef.curves`는 이름 붙은 곡선의 튜플이다(이름은 `^[a-z][a-z0-9_]{0,63}$`, 한 부품 안에서 유일). 곡선 하나는 `x_unit`, `y_unit`(닫힌 `Unit` 어휘), 점 목록 `points: [{x, y}]`, **곡선 전체에 배지와 출처 하나**다(스냅 포인트의 자세와 같은 규칙). 점이 여러 출처에서 왔으면 `source.ref`에 점마다 어디서 왔는지 적거나 곡선을 나눈다.

- 점은 둘 이상, `x`는 **엄격히 증가**, 모든 수는 유한(JSON Schema `Number`와 같은 strict float).
- 점 사이는 **직선**(구간 선형). **바깥으로 연장하지 않는다**: `kinetra_engine.parts.evaluate(curve, x)`는 `[x_첫째, x_마지막]` 밖에서 `CurveRangeError`(`CurveError`의 하위)를 낸다. 점이 유한하면 값도 항상 유한하다: 보간은 볼록 결합이라 `±1.7e308` 같은 극단에서도 넘치지 않고 두 이웃의 범위 안에 있다(데이터시트가 말하지 않은 곳의 값을 만들지 않는다).
- `인용`이면 `source.locator`나 `url`이 있어야 한다(`Provenance`가 확인). 곡선의 배지는 입력 점에 대한 배지다. 점을 직선으로 이은 값은 모델이다.
- 시간에 따라 변하는 곡선(추력 곡선, B-03c)도 같은 모델이다(`x_unit: s`).

## 부품 역할 (`PartDef.role`)

`PartRole`: `motor`, `thruster`, `wheel`, `battery`, `tank`, `spring_damper`(없을 수 있다. 기본 `None` = 그냥 몸체). 이 PR이 정하는 것은 역할 이름 전체와 `motor`의 요구뿐이다. 다른 역할의 요구는 그 부품 이슈(B-03a, c, d)가 `PartDef`의 같은 검증기에 더한다. `spring_damper`의 요구(파라미터 `stiffness`, `damping`)는 B-03e가 더했다: [`part-spring-damper.md`](part-spring-damper.md).

**`role: "motor"` 인 `PartDef`는 아래를 만족해야 한다**(어기면 `PartDef` 검증이 거절한다):

| 요구 | 이유 |
|---|---|
| 곡선 `torque_speed`가 있다. `x`는 `rad/s`, `y`는 `N*m` | 이름과 단위가 소비자(X-01b, B-06d)와의 계약이다 |
| 첫 점의 속도가 0이고 토크가 양수(정지 토크) | 곡선은 정지에서 시작한다 |
| 마지막 점의 토크가 정확히 0(무부하 속도) | 곡선은 무부하에서 끝난다. 그 속도 너머는 토크 0이다 |
| 속도가 올라갈 때 토크가 오르지 않는다 | 직류 모터의 토크는 속도에 따라 줄어든다. 오르는 곡선은 이 모델이 아는 모터가 아니다 |
| 사양 `rated_voltage`가 있다. 단위 `V`, 양수 | 곡선이 어느 전압에서의 것인지 |

단위 `V`와 `A`를 `Unit`에 더했다(전기 사양용). 곡선은 **명령 1(완전 구동)일 때의 토크 한계**다. 명령 0과 1 사이의 비율과 부호는 X-01b가 정했다: 정격 전압의 비율(PWM 듀티)이고 토크는 $u\,T(s/|u|)$다([`joints-actuators.md`](joints-actuators.md)). `DesignSpec`은 비율만 안다.

### 액추에이터와 역할의 대응 (`designspec.py`)

모터 액추에이터(`ActuatorKind.MOTOR`)는 역할이 `motor`인 부품의 인스턴스에, 추력기 액추에이터는 `thruster`인 부품의 인스턴스에 붙는다. 다른 역할의 부품이면 `DesignSpec` 검증이 부품·인스턴스·액추에이터 id와 함께 거절한다. **역할이 없는 부품은 받는다**(역할이 없던 기존 예시 프로젝트와 사용자 정의 부품을 깨지 않는다). 그런 부품에는 곡선이 없으므로 컴파일러가 "곡선 없음"으로 보고해야 한다(X-01d). 이 틈은 의도한 것이다.

## 계산 (`kinetra_engine.parts.curves`)

- `evaluate(curve, x)`: 구간 선형 보간. 점에서 정확하다. 범위 밖은 오류.
- `motor_characteristics(part)`: 정지 토크(첫 점의 토크), 무부하 속도(마지막 점의 속도), 정격 전압. 곡선과 사양에서 읽을 뿐 다른 값을 만들지 않는다.
- `motor_torque_limit(part, speed)`: 속도 `speed`[rad/s]에서 완전 구동의 토크 한계 [N*m]. `|speed|`로 곡선을 읽고 방향은 상관없다. 무부하 속도 이상에서는 0을 낸다(곡선이 거기서 0으로 끝난다. 제동·회생 사분면은 이 모델에 없다).

## 라이브러리 부품: `motor-37d-12v-50-1`

Pololu 37D 금속 기어모터, 12 V, 50:1, 64 CPR 엔코더, 헬리컬 피니언(Pololu 품목 #4753, 날짜 데이터시트 rev 1.2 2020-01). **모든 사양 수치는 `인용`이고 출처 위치(데이터시트 표·쪽, 제품 사양 페이지 항목, 치수 도면)가 값마다 `source.locator`와 `url`에 있다.** 이 PR이 우리가 정한 값은 스냅 포인트 둘의 자세뿐이고 `사용자 선언`이다.

| 값 | 수치 | 출처 |
|---|---|---|
| 정격 전압 | 12 V | 데이터시트 성능 요약표 |
| 무부하 속도 | 200 rpm = 20.9440 rad/s | 같은 표 |
| 정지 토크 | 210 kg⋅mm = 2.05940 N⋅m | 같은 표의 "Stall Extrapolation". kg⋅mm를 kgf⋅mm로 읽어 9.80665×10⁻³ N·m를 곱했다 |
| 무부하 전류 / 정지 전류 | 0.2 A / 5.5 A | 같은 표(정지 전류는 외삽. 13쪽 그래프는 5.4 A) |
| 연속 부하 권장 상한 | 100 kg⋅mm = 0.980665 N⋅m | 같은 표의 주(2) |
| 기어비 | 50 | 같은 표(제품 페이지의 정확한 값 (25×30×25×40)/(10×10×15×10)) |
| 질량 | 205 g | 제품 사양 페이지의 Weight. `mass_parameter`(B-02c)로 선언: 최소=기본=최대 0.205 kg이라 고정값이다 |
| 외형 | 축 지름 6 mm × 16 mm, 보스 지름 12 mm × 6 mm, 기어박스 지름 36.8 mm × 24.0 mm, 모터 지름 34.8 mm × 30.7 mm, 엔코더 지름 34.0 mm × 15.4 mm | 치수 도면(2020-01-10). 원기둥 5개의 합 |

`torque_speed` 곡선은 **두 점**이다: (0, 2.0594 N·m)와 (20.944 rad/s, 0). 데이터시트의 요약표 값(정지 외삽과 무부하)을 직선으로 이은 직류 모터 모델이다. 데이터시트 13쪽 그래프도 속도를 토크의 직선으로 그린다. 그래프의 점을 읽어 곡선을 늘리지 않았다(눈대중 수치를 `인용`으로 쓰지 않으려는 것).

### 한계 (숨기지 않는다)

- **정지 토크는 이론적 외삽이다.** 데이터시트가 말하듯 실제 유닛은 모터가 가열되면서 그보다 먼저 멈추고 정지 토크도 줄어든다. 곡선의 첫 점은 "정지 토크 사양"이지 장시간 낼 수 있는 토크가 아니다. 연속 부하 상한(100 kg⋅mm)은 사양 `continuous_torque_limit`에 따로 있고 이 PR의 계산은 그 값으로 곡선을 자르지 않는다(자르는 정책은 소비자 몫이다).
- **직선 모델과 데이터시트의 최대 출력점이 다르다.** 데이터시트 13쪽은 100 kg⋅mm에서 98 rpm(최대 출력 10 W)이라 적었는데, 이 곡선은 그 토크에서 200×(1−100/210) = 104.8 rpm을 준다(약 6.9 % 빠르다). 직선 모델의 최대 출력은 $T_0\omega_0/4 = 10.78$ W다. `test_motor_model_against_the_datasheets_max_power_point_differs_by_the_documented_amount`가 이 차이를 고정한다.
- 전류·효율·전기 시정수는 곡선에 없다(`rated_voltage`, `no_load_current`, `stall_current`는 사양으로만 있다). 배터리 소모는 X-01b가 두 전류 사양을 이은 직선으로 계산한다([`joints-actuators.md`](joints-actuators.md)).
- 외형은 원기둥 다섯 개다. 축의 D자 평면, M3 구멍 여섯 개, 단자, 엔코더 덮개의 모양, 선은 그리지 않았다. 외형이 부품의 윤곽으로 읽히는지는 PR의 캡처로 사람이 판단한다(`add-part.md` 5절). 질량은 205 g을 형상 부피에 **균일하게** 편 것이라 무게중심(-33.2 mm, 면판 뒤)과 관성은 그 가정의 값이다.
- 모터를 구동할 관절에 대한 기어박스 방향(출력축 +z)은 스냅 포인트 `shaft`(`kind: shaft`)가 정한다. 관절의 축은 결합의 `axis` 필드(B-04a, `project-model.md`)이고, 적지 않으면 `a` 스냅 좌표계의 +Z라서 `shaft`의 +Z와 같은 방향이다.
