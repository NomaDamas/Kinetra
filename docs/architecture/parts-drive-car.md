# 구동 부품 통합 시연: 휠·모터·추력기·배터리·탱크·스프링을 단 차 (B-03 에픽, #100)

- 상태: 구현됨. 예시 프로젝트 `schemas/examples/Project.drive-car.json`, 생성기 `packages/engine/tests/drive_car_sample.py`, 테스트 `packages/engine/tests/test_drive_parts.py`(`uv run pytest packages/engine -q -k drive_parts`), 그림 `tools/gltf-check/drive-car.ts`(CI `screenshots` 잡의 `out/gltf-check/drive-car.png`).
- 근거: 이슈 #100의 통합 시연 항목("휠·모터·추력기·배터리·스프링을 단 차가 부품 목록과 사양 출처와 함께 보이는 스크린샷"), B-03a(`parts-wheel.md`), B-03b(`part-motor.md`), B-03c(`parts-thruster.md`), B-03d(`parts-battery-tank.md`), B-03e(`part-spring-damper.md`), B-04a(결합 축, `project-model.md`), 핵심 가치 V2(상상에서 현실까지)와 V5(출처).
- 범위 밖: 연소, 노즐 유동, 타이어 변형(이슈의 범위 밖). 차가 실제로 달리는 시뮬레이션(X-01), 배터리 전압과 모터 정격 전압의 맞춤(아래 "한계"), 스프링-댐퍼를 결합의 강성·감쇠로 거는 일(X-01b), 실제 차량의 치수.

## 설계

한 `Project`다(행성 지구, 지면 z = 0 위에 놓임, x가 앞). 구동 부품은 모두 라이브러리 파일(`parts/library/*.json`) 그대로다(`test_drive_parts_car_has_every_drive_part`가 파일과 `==`인지 본다).

| 인스턴스 | 부품 | 역할 | 재료 | 붙는 곳 |
|---|---|---|---|---|
| `chassis` | `drive-chassis`(이 예시의 부품) | 몸체 | al6061-t6 | 뿌리 |
| `motor-rl`, `motor-rr` | `motor-37d-12v-50-1` | 모터 | 없음(선언 질량) | 차대 `motor-r*`에 고정, 출력축이 바깥(±y) |
| `stub-rl`, `stub-rr` | `drive-stub`(이 예시의 부품) | 몸체 | al6061-t6 | 모터 `shaft`에 **힌지**(모터가 구동) |
| `wheel-rl`, `wheel-rr` | `wheel` | 휠 | pom-delrin-150 | 축 토막 `out`에 고정 |
| `wheel-fl`, `wheel-fr` | `wheel` | 휠 | pom-delrin-150 | 차대 `axle-f*`에 **힌지** |
| `battery` | `battery-pack-4s` | 배터리 | 없음(선언 질량) | 차대 윗면 `battery-seat`에 고정 |
| `tank` | `tank`(반지름 0.035 m, 길이 0.1 m, 사용자 선언) | 탱크 | al6061-t6 | 차대 윗면 `tank-seat`에 고정 |
| `thruster` | `thruster-vacco-48003040` | 추력기 | steel-a36 | 차대 윗면 `thruster-mount`에 고정, 노즐이 뒤(−x) |
| `spring-l`, `spring-r` | `spring-damper-lee-lc032b08` | 스프링-댐퍼 | 없음(선언 질량) | 차대 앞면 `spring-*`에 고정(범퍼) |

- **결합 13개**: 힌지 4개(앞 액슬 둘, 뒤 구동 둘)와 고정 9개. 힌지의 축은 모두 `axis`를 적었고(B-04a, 배지 `사용자 선언`) 월드에서 +y다. 그래서 네 바퀴 모두 양의 각이 차를 앞(+x)으로 굴린다. 오른쪽 모터는 출력축이 −y를 향하므로 축을 `(0, 0, −1)`(축 스냅 좌표계)로 적어 같은 부호를 만든다(`test_drive_parts_every_wheel_turns_on_a_hinge_about_the_axle`).
- **액추에이터 3개**: 모터 둘이 각자의 구동 힌지를 돌리고 `supply`가 `battery`(역할 `battery`), 추력기 하나가 `supply` `tank`(역할 `tank`). 스케줄은 두 모터 0~3 s 명령 1, 추력기 1~2 s 명령 1(시연용 선언값).
- **자세**는 결합으로 푼다: 차대가 뿌리이고, 자식의 위치 = 부모 스냅의 월드 위치 − (자식 방향으로 돌린) 자식 스냅의 로컬 위치. 좌표를 두 번 적지 않는다. 바퀴 중심은 z = 0.05 m(지름 0.1 m)라서 타이어가 바닥에 닿는다.

### 이 예시의 부품 둘 (왜 라이브러리 판이 아닌가)

- **`drive-chassis`**: 판(0.36 × 0.24 × 0.008 m)과 뒤 모터를 위에서 잡는 행거 상자 둘. 라이브러리 `plate`의 스냅은 `face`·`edge`뿐이라 모터(`motor_mount`), 바퀴(`shaft`를 받는 `axle_mount`), 스프링(`spring_end`)이 붙을 곳이 없고, 스냅 하나는 결합 하나만 쓴다(`DesignSpec`). 그래서 같은 판 모양에 차가 쓰는 스냅 아홉 개를 적은 부품을 예시 안에 두었다. 모양·스냅·치수 모두 `사용자 선언`이다. 판 위 받침이 여러 개 필요한 일과 스냅 태그의 맞춤 규칙은 B-04b(#108)의 몫이다.
- **`drive-stub`**: 모터 출력축 끝에서 바퀴 안쪽 허브 끝까지의 반지름 4 mm 막대. 라이브러리 바퀴의 허브는 속이 찬 원기둥이고 모터의 `shaft` 스냅은 축의 한가운데라, 바퀴를 축에 바로 걸면 축이 바퀴 속을 지난다. `check_placement`는 그것을 정확히 `overlap`이라 부른다(이 PR에서 확인: 폭 0.01·0.02·0.04 m 어느 것도 겹친다). 그래서 뒤 바퀴는 모터 → (힌지) → 축 토막 → (고정) → 바퀴로 붙고, 모터 액추에이터는 그 힌지를 구동한다(모터 인스턴스가 결합의 한 끝이어야 한다는 `Actuator` 규칙). 막대는 축 끝·허브 끝과 면으로 닿을 뿐 겹치지 않는다.

## 검사 (`test_drive_parts.py`, 14개)

1. **배치가 유효하다**: `check_placement(project) == ()` — 결합한 스냅이 만나고, 겹침이 없고, 지면 아래가 없고, 떠 있는 것이 없다.
2. **명령으로 지을 수 있다**: 빈 프로젝트에서 재료 셋, 부품 정의 여덟, "굴러가는 차대"(차대·모터·축 토막·바퀴와 그 결합) 한 묶음, 나머지 부품마다 [인스턴스, 결합] 묶음, 액추에이터, 스케줄을 차례로 `validate_command`에 넣어 모든 단계가 통과하고 결과가 예시와 바이트까지 같다. 차대 혼자는 떠 있으므로(`floating`) 첫 묶음이 바퀴까지 함께 놓는다.
3. **거절도 한다**: 앞바퀴를 5 mm 옮기면 `invalid_snap`, 추력기가 배터리를 `supply`로 쓰면 거절된다.
4. **역할과 공급**: 휠 넷, 모터 둘, 추력기·배터리·탱크 하나씩, 스프링-댐퍼 둘. 모터의 공급은 `battery` 역할, 추력기의 공급은 `tank` 역할이고 추력(부품 −z)이 +x를 민다.
5. **사양 표가 부품 정의와 같다**: 표의 각 행(이름, 값, 단위, 배지, 출처 `ref`·`locator`·`url`)을 라이브러리 파일을 **JSON으로 직접 읽은 값**과 대조한다(표를 만든 코드를 거치지 않는다). 인용 값은 위치(locator 또는 url)가 있다.
6. **값이 데이터시트와 같다**(손으로 다시 적은 값, 상대 1e-12):

| 부품 | 사양 | 값 | 배지 | 손계산 |
|---|---|---|---|---|
| 휠 | `tread_friction_static` / `kinetic` | 1.0 / 0.7 | 인용 | OpenStax 표 5.1 고무-마른 콘크리트 |
| 모터 | `rated_voltage` | 12 V | 인용 | Pololu 37D |
| 모터 | 정지 토크(`torque_speed` 곡선의 0 rad/s 점) | 2.0593965 N·m | 인용 | 210 kgf·mm × 9.80665×10⁻³, 사양 `stall_torque`와 `==` |
| 추력기 | `rated_thrust` | 8.896443 N | 인용 | 2 lbf × 4.4482216152605 |
| 배터리 팩 | `nominal_voltage` | 14.4 V | 추정 | 4 × 3.6 V |
| 배터리 팩 | `energy_capacity` | 168 480 J | 추정 | 4 × 3250 mAh × 3.6 V |
| 탱크 | 추진제 용량(`tank_supply`) | 0.3023971 kg | 시뮬 | 1000 kg/m³ × π × 0.032² × 0.094 m³ |
| 스프링-댐퍼 | `stiffness` | 5990 N/m | 인용 | Lee Spring 5.99 N/mm |
| 스프링-댐퍼 | `damping` | 20 N·s/m | 기본값 | Kinetra 시작값(측정 아님) |

7. 예시 파일, 인스턴스별 glb, `manifest.json`이 코드가 오늘 쓰는 것과 같다(생성기를 다시 돌리라는 메시지로 실패한다).

## CI의 그림

`screenshots` 잡이 `pnpm --filter @kinetra/gltf-check capture:drive-car`를 돈다. `page/drive-car.html`이 인스턴스마다 glb를 pose대로 놓고(B-02 뼈대와 같은 코드: `page/assembly.js`의 `projectFrame`, `placeInstances`, `fitCamera`. `skeleton.js`도 이것을 쓰도록 옮겼다) 옆 표에 부품 목록(부품, 역할, 수, 인스턴스)과 위 사양 행(값, 단위, 배지 색 칩과 한국어 이름, 출처 앞 110자와 locator, 셀의 title에 출처 전문)을 쓴다. 표의 모든 값은 생성기가 부품 정의에서 읽어 쓴 `manifest.json`의 것이다. `drive-car.ts`가 단언한다: 14개가 모두 pose의 자리에 있다, 지면 아래가 없고 차가 바닥에 선다(테셀레이션 때문에 1 mm 허용), 부품 목록이 모든 인스턴스를 덮는다, 사양 행마다 값·표시 문자열·배지·출처가 manifest와 같다, 그려진 픽셀이 있고 잘린 곳이 없다. 결과는 `drive-car.png`와 `drive-car-result.json`(`problems: []`).

## 한계 (숨기지 않는다)

- **전압이 맞지 않는다.** 배터리 팩 공칭 14.4 V(추정)는 모터 정격 12 V(인용)보다 20 % 높다. 라이브러리에 12 V 공급원이 없다(셀 3.6 V, 4S 팩 14.4 V). 공급 모델(B-03d)은 에너지(J)만 세고 전압을 맞추지 않으므로 이 예시는 전압이 맞는다고 주장하지 않는다. 표는 두 값을 그대로 보여 준다.
- **뒤 바퀴의 힌지는 축 토막에 있다**(위 "이 예시의 부품 둘"). 앞 바퀴는 차대에 바로 힌지로 걸린다.
- **스프링-댐퍼는 범퍼로 고정 결합되어 있다.** 스프링이 두 몸체 사이에서 결합의 강성·감쇠로 작동하는 것은 X-01b의 몫이고, 여기서는 그 부품의 사양을 보이는 것까지다.
- 치수, 자세, 탱크 크기, 스케줄은 이 예시의 `사용자 선언` 값이고 실제 차량의 값이 아니다.

## 다시 만들기

```bash
uv run python packages/engine/tests/drive_car_sample.py   # 예시, glb, manifest 다시 쓰기 (결정적)
uv run pytest packages/engine -q -k drive_parts
uv run python packages/core/scripts/validate_examples.py
```
