# 배터리와 탱크 (B-03d)

- 상태: 구현됨. 정의 파일은 `packages/engine/src/kinetra_engine/parts/library/{battery-18650,battery-pack-4s,tank}.json`(`PartDef`, 파일 이름이 부품 id). 잔량 계산은 `packages/engine/src/kinetra_engine/parts/supply.py`(`Supply`, `battery_supply`, `tank_supply`, `electrical_power`, `tank_total_mass`). 모델은 `kinetra_core`의 `PartRole.BATTERY`·`TANK`(`partdef.py`)와 `Actuator.supply`(`designspec.py`). 테스트는 `packages/engine/tests/test_battery_tank.py`(`uv run pytest packages/engine -q -k "battery or tank"`)와 `packages/core/tests/test_supply.py`(`uv run pytest packages/core -q -k supply`). 고정 glb는 `packages/engine/tests/fixtures/gltf/{battery-18650-declared-mass,battery-pack-4s-declared-mass,tank-al6061}.glb`.
- 근거: 이슈 #104(DoD: 용량과 질량, 소모에 따른 잔량, 등속 주행 소모의 수계산 대조), `docs/process/add-part.md`(이 부품들이 따른 절차), `part-payload.md`(선언 질량 `mass_parameter`), 핵심 가치 V5.
- 범위 밖: 연소, 노즐 유동, 타이어 변형(이슈 범위 밖 문구). 모터와 추력기 자체(B-03b, B-03c), 소모를 시간 단계마다 적용하는 시뮬(모터는 X-01b, 추력기는 X-01c, 이 문서의 `Supply`를 부른다), 결합과 스냅 호환 검사(B-04).

## 숫자의 출처 (V5)

| 값 | 배지 | 출처 |
|---|---|---|
| 셀 질량 48.5 g | `인용` | Panasonic NCR18650B 데이터시트 v13.11 R1의 "Weight (max.)". **최댓값**이다. 사양표의 고정 값이라 `mass` 파라미터의 최소=기본=최대로 두었다(사용자가 인용 셀의 질량을 바꾸지 못한다) |
| 셀 공칭 전압 3.6 V | `인용` | 같은 표 "Nominal voltage" |
| 셀 에너지 42 120 J | `추정` | 방법: 최소 용량 3250 mAh × 3.6 V = 11.7 Wh = 42 120 J. 인쇄된 에너지가 아니라 **두 인쇄 값의 곱**이라서 `인용`이 아니다. 전형 용량 3350 mAh면 43 416 J. 교차 점검: 중량 에너지 밀도 243 Wh/kg × 48.5 g = 11.79 Wh(+0.7 %). 용량은 25 °C 값이다. 시트의 각주가 말하는 방전율은 우리가 가진 사본에서 읽히지 않는다. 방전율이 크고 온도가 낮으면 꺼낼 수 있는 에너지가 줄고(시트의 방전 곡선), 이 모델은 그것을 반영하지 않는다 |
| 셀 외형 | `기본값` | 시트의 치수 그림: 지름 최대 18.5 mm, 길이 최대 65.3 mm, 양극 단추 지름 6.6 mm. 단추 높이 1.0 mm는 **우리가 정했다**(시트에 없다). 인쇄된 최댓값이라 실물은 조금 작다 |
| 4S 팩 질량 194 g | `추정` | 4 × 48.5 g. 셀만이다. 실제 팩의 홀더·배선·보호 회로는 질량에 없다 |
| 4S 팩 에너지 168 480 J, 14.4 V | `추정` | 셀 값의 4배(직렬 4개), 4 × 3.6 V. 균형 회로나 보호 회로의 손실은 없다 |
| 탱크의 모든 치수, 벽 두께 3 mm, 추진제 밀도 | `기본값` | Kinetra가 게임 규모에 맞춰 정했다. 데이터시트도 실제 용기도 아니다. 밀도 기본값 1000 kg/m³는 **자리표시자**(액체 정도)이고 어떤 추진제도 뜻하지 않는다. 범위 1~2000 kg/m³는 압축 기체에서 밀한 액체까지를 덮는 모델의 범위다 |

팩은 데이터시트의 한 제품이 아니라 셀 4개의 합성이라서 `인용`을 쓰지 않는다(`derivation.input_badges`는 `기본값`과 `추정`, 테스트가 단언한다). 셀의 `input_badges`는 `인용`과 `기본값`이다(질량은 인용, 외형은 우리 것).

안전선: 탱크는 게임 수준의 일반 저장 용기이고 추진제의 조성, 연소, 엔진 설계 자료는 없다. 어떤 추진제를 담는지 이름 붙이는 필드가 없다.

## 부품

| id | 역할 | 질량 | 용량 | 파라미터 (기본, 범위) | 스냅 포인트 |
|---|---|---|---|---|---|
| `battery-18650` | `battery` | 선언(`mass_parameter`, 인용 48.5 g) | 사양 `energy_capacity` 42 120 J, `nominal_voltage` 3.6 V | `initial_charge` 1 (0~1) | `plus`, `minus`(종류 `terminal`), `side-xp`, `side-xn`(`face`) |
| `battery-pack-4s` | `battery` | 선언(추정 194 g) | 168 480 J, 14.4 V | `initial_charge` 1 (0~1) | `top`, `bottom`, `side-xp`, `side-xn`(`face`) |
| `tank` | `tank` | 재료의 밀도 × 껍데기 부피(인스턴스의 재료) | 추진제 밀도 × 안쪽 부피 | `radius` 0.06 m (0.03~0.15), `length` 0.2 m (0.05~0.6), `propellant_density` 1000 kg/m³ (1~2000), `initial_fill` 1 (0~1) | `bottom`, `side-xp`, `side-xn`(`face`), `outlet`(`feed`) |

배터리 부품은 에너지를 **사양**(`specs`)으로 가진다. 전기 에너지는 치수에서 나오지 않고 셀 화학과 데이터시트에서 오기 때문이다. 탱크는 사용자가 키우는 용기이므로 용량을 **치수에서 계산한다**: 용량 [kg] = `propellant_density` [kg/m³] × 안쪽 부피 [m³]이고 안쪽 부피는 형상의 `subtract` 요소의 부피다(`PartDef`가 안쪽이 있는 형상과 양의 밀도를 요구한다). 기본값이면 $1000 \times \pi (0.057)^2 \times 0.194 = 1.98016$ kg이다. 탱크를 키우면 담는 양이 따라 커지고 `Supply.input_badges`가 그 입력의 배지를 같이 낸다(계산한 용량은 `시뮬`이다).

`PartDef`가 역할이 요구하는 것을 검사한다(`partdef.py`). 배터리는 `energy_capacity`(J)와 `nominal_voltage`(V) 사양이 양수여야 하고, 탱크는 `subtract` 요소와 `propellant_density`(kg/m³, 전 범위에서 양수)가 있어야 한다. `initial_charge`와 `initial_fill`은 있으면 단위 `1`에 범위가 [0, 1] 안이어야 한다.

## 잔량과 소모 (`supply.py`)

`Supply`는 값이다(불변). `capacity`(단위 J 또는 kg)와 `remaining`을 가지고 `draw(양)`이나 `draw_rate(률, dt)`가 **새 `Supply`와 `Draw`**(요청량, 낸 양, `satisfied` = 낸 양 ÷ 요청량)를 돌려준다. 시뮬레이션이 공급원 인스턴스마다 `Supply` 하나를 쥐고 매 단계 넘기므로, 같은 인스턴스를 `supply`로 가리키는 액추에이터 여럿이 같은 잔량을 쓴다(`test_battery_two_motors_on_one_battery_spend_the_same_stock`).

- 받을 수 없는 요청(음수나 비유한 양·률·시간 간격)은 `SupplyError`(`ValueError`의 하위 클래스)다. `draw_rate`는 `rate`와 `dt`를 따로 검사하므로 `draw_rate(-1.0, 0.0)`도 거부한다(곱 `-0.0`이 양 검사를 통과하던 틈, B-03f).
- 잔량이 모자라면 있는 만큼만 내고 `satisfied < 1`을 알린다. 부르는 쪽은 그 단계의 액추에이터 출력에 `satisfied`를 곱한다(받은 에너지가 절반이면 일을 절반 한다). 잔량은 0 아래로 내려가지 않는다. 다 쓴 공급원은 0을 낸다.
- `electrical_power`는 효율 $\eta$를 아는 소비자를 위한 식 $P_\mathrm{el} = P_\mathrm{mech}/\eta$ ($0<\eta\le 1$)이다. 부하가 모터를 제동하는 구간(기계 동력이 음수)은 0을 꺼내고 **되돌려주지 않는다**(회생 제동은 모델에 없다). 시뮬레이션의 모터(X-01b)는 효율 사양이 없어서 이 식을 쓰지 않고 데이터시트 전류(`no_load_current`, `stall_current`)로 $P = |u|\,V\,I(\tau)$를 꺼낸다([`joints-actuators.md`](joints-actuators.md)).
- 탱크의 질량: `tank_total_mass(건조 질량, 공급)` = 건조 질량 + 남은 추진제. 건조 질량은 `mass_properties(tank, 재료)`의 질량이다. 소모에 따라 총질량이 준다. 이 질량 변화를 엔진 모델에 반영하는 방식은 X-01c가 정했다([`thrust.md`](thrust.md): 추진제는 탱크 안쪽에 고르게 퍼져 있고, 그 바디의 질량·관성을 단계마다 고친다). 무게중심이 추진제와 함께 이동하는 것은 거기에도 없다(`tank_total_mass`는 스칼라 질량만 준다).
- `Actuator.supply`는 인스턴스 id다. 모터의 공급원은 역할 `battery`, 추력기의 공급원은 `tank`인 부품의 인스턴스여야 하고, 역할이 없는 부품과 없는 인스턴스는 거부된다(`DesignSpec` 검증, 거부 사유가 인스턴스·부품·액추에이터 `Ref`를 싣는다). `supply`가 `None`이면 계량하지 않는다. 공급원 인스턴스를 지우면(`remove_instance`) 그것을 쓰던 액추에이터와 그 스케줄 항목이 같은 명령으로 함께 지워지고 되돌리면 모두 돌아온다.

## 등속 주행 소모의 수계산 (이슈 DoD, `test_battery_constant_speed_drive_consumption_matches_the_hand_calculation`)

반지름 0.05 m 바퀴가 일정한 저항 5 N을 이기며 2 m/s로 간다(선언한 값, 실제 차량이 아니다). 토크 $5\times0.05=0.25$ N·m, 각속도 $2/0.05=40$ rad/s, 기계 동력 $0.25\times40=10$ W. 효율 0.8이면 전지는 $10/0.8=12.5$ W를 낸다. 100초 동안 $12.5\times100=1250$ J이고 남는 것은 $42120-1250=40870$ J(97.03 %). 가득 찬 셀로 $42120/12.5=3369.6$ s를 간다. 같은 소모를 시간 간격 1, 0.1, 0.01, 1/240 s로 나눠 더해도 같은 값이 나온다(상대 1e-9). 마지막 단계에서 모자란 전력은 `satisfied`=0.6으로 드러난다(3369 s 뒤 1 s 단계에서 12.5 J을 요청했고 7.5 J만 남았다).

탱크: 흐름 0.002 kg/s(선언)로 100 s면 0.2 kg이고 남는 양은 $1.98016-0.2$ kg, 비는 데 $1.98016/0.002\approx990.1$ s.

## 근사와 한계 (숨기지 않는다)

- **전압 강하가 없다.** 용량은 J 한 수이고 충전 상태나 방전율, 온도, 노화에 따라 변하지 않는다. 실제 셀은 방전율이 크고 온도가 낮을수록 꺼낼 수 있는 에너지가 준다(시트의 방전 곡선). 모터의 `rated_voltage`와 배터리의 `nominal_voltage`가 달라도 X-01b는 토크 곡선을 바꾸지 않는다(곡선은 정격 전압의 것이다, `joints-actuators.md` 한계).
- **회생이 없다.** 꺼내기만 한다.
- **탱크는 질량만 담는다.** 압력, 온도, 상 변화, 슬로싱이 없고 추진제는 이름 없는 균일 밀도다. 추진제 소모에 따른 무게중심과 관성의 이동은 없다.
- **탱크의 안쪽은 충돌 프록시에서 메워지고 시각 메시에 그려지지 않는다**(`part-mass.md` "못 하는 것", `filled_voids`에 `inside`가 나온다). 프록시 부피는 레시피 부피의 약 6.2배다(`volume_error` 5.19, 상대 오차). 속이 빈 용기에 닿는 물체는 실제보다 단단한 덩어리를 만난다. 빈 곳을 깎은 메시는 #496, 빈 곳이 있는 프록시 분해는 #502(B-01f)가 맡는다.
- 셀 외형은 원기둥 둘(몸통과 단추)이다. 포장 튜브, 음극 쪽 모서리, 절연 링은 없다. 팩은 셀이 맞닿은 2×2 배치이고 홀더와 배선이 없다.
- 스냅 `kind`와 `accepts` 태그(`terminal`, `face`, `feed`)는 B-04b가 호환 규칙을 정하기 전의 첫 제안이다. 탱크 `bottom`은 #567부터 분리기의 `surface` 면과도 맞물리도록 `face`·`surface`를 받는다.
- 질량 분포는 균일하다고 가정한다(`part-payload.md`). 실제 셀의 무게중심은 이 가정의 위치와 다를 수 있다.
