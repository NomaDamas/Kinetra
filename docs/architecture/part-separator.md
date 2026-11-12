# 분리기 (B-15)

- 상태: 구현됨. 검증은 `packages/core/src/kinetra_core/partdef.py`(`PartRole.SEPARATOR`, `PartDef._check_separator`, 이름 상수 `SEPARATOR_IMPULSE`, `SEPARATOR_FACE_A`, `SEPARATOR_FACE_B`, `SEPARATOR_BADGES`)와 `designspec.py`(분리기에 닿는 결합은 고정, 인스턴스가 쓴 충격량의 배지). 읽기는 `packages/engine/src/kinetra_engine/parts/separator.py`. 부품 정의는 `packages/engine/src/kinetra_engine/parts/library/separator.json`(같은 파일이 `schemas/examples/PartDef.separator.json`). 테스트 `packages/engine/tests/test_separator.py`(`uv run pytest packages/engine -q -k separator`).
- 근거: 이슈 #447, 계획 변경 PC-02(`docs/plan/studio-plan.md` 5.3절), `docs/research/benchmarks/kerbal-space-program.md` A10, `docs/process/add-part.md`, 안전선 `docs/process/review-rubric.md` 1번.
- 범위 밖: 분리 표식(X-09), 화약·연소·점화·가스·스프링의 모델, 낙하산, `export_policy`(HW-02a, S2). 분리 이벤트의 실행(`face_b` 결합이 풀리는 순간, 두 쪽에 충격량이 들어가는 일, 사유 기록)과 분리 스케줄 항목은 X-08이 더했다: [`separation.md`](separation.md).

## 이 부품이 하는 것

분리기는 **두 부품을 고정 결합으로 잇다가 명령을 받으면 그 결합을 푸는** 부품이다. 이 PR(B-15)은 부품의 정의와 검증까지다. 풀리는 일은 X-08이 더했다: 스케줄의 분리 항목이나 수동 요청이 `face_b`의 결합을 풀고, 분리기는 `face_a` 쪽에 남는다([`separation.md`](separation.md)).

| 요소 | 이름 | 내용 |
|---|---|---|
| 역할 | `separator` | `PartRole.SEPARATOR` |
| 질량 | `mass`(kg, `mass_parameter`) | 선언 질량. 재료를 읽지 않는다(`part-payload.md`와 같은 규칙). 기본 0.5 kg(0.01~200)은 `기본값`이고 "자리 표시값"이라고 출처에 쓴다 |
| 치수 | `radius`, `length`(m) | 기본 0.05, 0.04 m. 범위는 우리가 정했고 실제 제품이 아니다(`기본값`) |
| **선언 분리 충격량** | `separation_impulse`(N·s) | 분리 때 두 쪽이 각각 받는 충격량의 크기. **0 허용**, 음수 불가. 기본 0, 범위 0~1000(`기본값`). 사용자가 인스턴스에 적으면 `사용자 선언` |
| 스냅 포인트 | `face_a`, `face_b` | 윗면(+z)과 아랫면(바깥 법선이 -z). 붙잡힌 두 부품이 각각 여기에 고정 결합으로 이어진다. 태그 `surface` |
| 윤곽 | 아래 플랜지, 허리, 위 플랜지(원기둥 셋) | 분리 링 모양. 겹치지 않는 합이고 구멍이 없어 충돌 프록시 부피 오차는 0이다 |

두 면의 규칙(`PartDef`가 강제): `face_a`와 `face_b`의 바깥 법선(스냅 프레임의 +Z)은 서로 **반대 방향**이어야 하고(허용 오차 1e-9, 한쪽 성분의 합이 이를 넘으면 거절), 두 위치의 차는 **파라미터 식으로** `length × (face_a의 법선)`이어야 한다(옆으로 어긋나거나 틈이 있거나 다른 파라미터를 따르면 거절). 그래서 `length`가 범위 어디에 있어도 두 면은 `length`만큼 떨어져 마주 본다. 파라미터 `length`(m)가 없으면 거절한다.

사양(`specs`)은 없다. "사양은 질량, 치수, 선언 분리 충격량뿐"이라는 DoD를 `PartDef`가 강제한다: 분리기는 `specs`도 `curves`도 가질 수 없고, 질량·길이(m)·`separation_impulse` 밖의 파라미터가 있으면 거절된다(`test_separator_adding_a_spec_a_curve_or_a_foreign_parameter_is_rejected`).

## 충격량의 규칙

- 단위 `N*s`(`Unit.N_S`, B-03c가 더했다). 음수는 정의(`min`)에서도 인스턴스 값에서도 거절한다. 인스턴스 값은 범위 검사(`DesignSpec`, `ShapeError`)에서 걸린다.
- 배지는 `사용자 선언`(`declared`)과 `기본값`(`default`)만 허용한다. `인용`, `추정`, `시뮬`은 정의에서도 인스턴스에서도 거절한다(`DesignSpec`는 `RefError`, `separator_from_part`는 `SeparatorError`). **충격량만이 아니라 분리기의 모든 파라미터(질량, 반지름, 길이)의 기본값·최솟값·최댓값과 인스턴스 값이 이 규칙을 따른다**(DoD: 질량·치수·충격량이 `사용자 선언` 또는 `기본값`). 이유: 분리 충격량은 어떤 출처도 없는 숫자이고, 약한 배지를 인용처럼 보이게 하지 않는다(V5). 배지와 출처가 없는 `Quantity`는 모델 전체의 규칙으로 거절된다.
- 충격량 0은 "결합만 풀리고 밀지 않는다"이다.
- 방향: `separator_from_part`가 돌려주는 `direction_a`, `direction_b`는 두 면의 바깥 법선(부품 프레임의 단위 벡터)이다. 두 쪽이 받는 충격량은 `impulse × direction`이고 크기가 같고 방향이 반대다(운동량 보존). 두 면은 서로 반대쪽을 본다. 이 값을 두 몸체에 넣는 일은 X-08이 더했다(`compiler/separation.py`의 `push_apart`, `face_b` 중심 한 점에).

## 에너지원은 스키마에 없다

분리기에는 무엇이 미는지(화약, 가스, 스프링 …)를 말하는 필드가 없다. `PartDef`의 스키마에 그런 이름이 없고(`test_separator_the_schema_and_the_result_have_no_field_for_an_energy_source`가 `PartDef` 스키마의 모든 필드 이름과 `Separator` 결과의 필드 이름에 금지어가 없음을 검사한다), 분리기에 추가 사양·곡선·길이 밖의 파라미터를 달면 정의가 거절된다. 선언 충격량은 에너지가 아니라 한 숫자이고, 어떻게 만들어지는지는 모형 밖이다. 화약·점화 장치의 조성과 설계는 다루지 않는다(`studio-plan.md` 15.3절 안전선과 같은 방식). 안전선을 넘는 자료(조성, 배합, 점화 회로)는 이 저장소에 없다.

## 가정표

`separation_assumption(separator)`는 충격량을 가정표의 한 행으로 낸다: 라벨 **"단순화 모델: 선언 분리 충격량"**, 값은 충격량 자신의 배지와 출처, 분포는 고정, `editable` 기본(참). 신뢰도는 정의의 자리 표시값(`기본값`)이면 `low`, 사용자가 선언했으면 `med`다. `high`는 없다: 선언한 숫자가 실제 기구가 내는 값과 같은지 아무것도 확인하지 않는다. 이 행을 가정표에 싣는 쪽(W-06, J 계열)은 이 함수를 쓴다.

## 결합 규칙 (`DesignSpec`)

분리기의 스냅 포인트에 닿는 결합은 **고정(`fixed`)** 이어야 한다. 힌지나 슬라이더로 이으면 `RefError`다. 푸는 일이 "고정 결합 해제"라는 DoD의 문장을 모델에서 지킨 것이다. 결합 하나가 분리기를 잡는 두 면 중 어느 쪽이든 각각 한 번만 쓰인다는 기존 규칙(스냅 포인트 하나에 결합 하나)이 그대로 적용된다. 분리 뒤 무엇이 남는지, 결합이 나무를 이루는지는 X-01a의 일이다.

## 분리 전 총질량·무게중심

분리 전에 분리기는 그냥 질량이 선언된 부품이다. 총질량과 무게중심은 몸체마다의 합이다: $M = \sum m_i$, $z_c = \sum m_i z_i / M$. `test_separator_total_mass_and_centre_of_mass_before_release_are_the_sum_of_the_parts`가 탑재체 둘 사이에 분리기를 끼우고 고정 결합 둘로 이은 `DesignSpec`(3 kg, 0.5 kg, 2 kg)을 `kinetra_engine.parts.assembly_mass`(B-02)에 넣어 총질량 5.5 kg을, 그 인스턴스별 `MassProperties`와 인스턴스 자세로 무게중심을 구해 윤곽 부피로 손계산한 값과 1e-12에서 맞춘다(스택의 스냅 프레임이 저장 자세에서 맞는지도 확인한다). 분리 뒤 남은 쪽의 합은 X-08이 시험한다(`test_separation_remaining_side_mass_and_centre_of_mass_are_the_sums_of_its_parts`).

## 한계

- 선언 충격량은 순간 충격량이다. 밀어내는 시간 모양, 충돌, 충격 하중, 붙잡는 하드웨어의 질량 분포는 없다. 질량은 윤곽의 순부피에 균일하게 펴진다(`part-payload.md`의 균일 가정).
- 치수와 윤곽은 우리가 그렸다. 실제 분리 기구가 아니다.
- 선언 충격량이 두 쪽의 질량에 비해 크면 분리 뒤 속도가 크다. 그 값이 현실적인지는 이 부품이 판단하지 않는다.

## 쓰지 않은 것

화약, 연소, 점화, 가스, 스프링의 모델과 필드. 낙하산. 분리 표식(X-09). 대결 부품 여부(`export_policy`)는 HW-02a(S2)가 정하며 이 부품은 그 필드도 값도 갖지 않는다(`test_separator_is_not_a_versus_part_and_has_no_export_policy_field`).
