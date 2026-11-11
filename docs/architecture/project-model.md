# Project 모델: 단위·좌표·값 배지 (C-01a)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/`(`conventions.py`, `provenance.py`, `material.py`, `partdef.py`), 테스트는 `packages/core/tests/test_material_partdef.py`.
- 근거: `docs/plan/studio-plan.md` 5절, `docs/architecture/client-adapter.md` G4·G6, 이슈 #60의 A0-04 이월 코멘트.
- 범위 밖: MJCF(X-01), 인스턴스·결합(C-01b), World·가정표(C-01c), JSON Schema·TS 파일 생성(C-01d). 모델은 Pydantic v2라서 `model_json_schema()`로 스키마가 이미 나온다. 파일로 내보내는 일은 C-01d다.

## 규약 (확정)

| 항목 | 값 |
|---|---|
| 단위 | SI: m, kg, s, rad. 닫힌 어휘 `Unit`(`kg/m^3`, `Pa`, `N`, `N*m`, `1`(무차원) 등). 어휘에 없는 단위 문자열(`mm`, `deg`, `g/cm^3`)은 검증에서 거부된다 |
| 좌표계 | 오른손 좌표계, +Z가 위 |
| 쿼터니언 | 성분 이름이 있는 객체 `{x, y, z, w}`, `w`가 스칼라, 길이 1(허용 오차 1e-6). 배열로 쓰지 않는다 |
| 수 | 유한한 JSON 숫자. 문자열·불리언·NaN·Infinity는 거부 |

## 값 배지와 출처

모든 물리 수치는 `Quantity`(값, 단위, 배지, 출처)다. 배지와 출처가 없거나 출처가 자리표시(`TBD`, `n/a`, `없음`, 빈 문자열 등)이면 검증이 거부한다.

| JSON | 화면 | 뜻 |
|---|---|---|
| `simulated` | 시뮬 | 시뮬 실행에서 나온 값 |
| `cited` | 인용 | 문서·데이터시트에서 옮긴 값. `source.locator`(표, 쪽, 절) 또는 `source.url`이 필요하다 |
| `default` | 기본값 | 우리가 정한 값. `source.ref`에 정한 이유 |
| `user_declared` | 사용자 선언 | 사용자가 넣은 값 |
| `estimated` | 추정 | 근거가 약한 판단 |

`source.ref`가 가리키는 것이 값을 실제로 뒷받침하는지는 모델이 검사할 수 없다. 리뷰 루브릭 4번이 본다.

## 모델

- `Material`: `density`(kg/m^3, > 0), `yield_strength`(Pa, > 0), `elastic_modulus`(Pa, > 0), `friction`(무차원 쿨롱 계수, >= 0). 두 재료의 접촉 마찰을 어떻게 합치는지는 컴파일러(X-01)가 정한다. 실제 재료 5종의 값은 B-07이 출처와 함께 채운다. 이 PR에는 실재료 수치가 없다.
- `PartDef`: `parameters`(이름, 단위, 기본값·최소·최대; 최소 <= 기본 <= 최대), `snap_points`(ID, 종류, 받아들이는 종류, 부품 로컬 좌표의 위치 `offset + Σ factor × 길이 파라미터`, 방향 쿼터니언, 배지·출처), `specs`(이름 → `Quantity`, 사양).
- 파라미터를 참조하는 스냅 포인트는 존재하는 길이(m) 파라미터만 가리킬 수 있다. 같은 `PartDef` 안에서 파라미터 이름과 스냅 포인트 ID는 겹치지 않는다.
- 모든 모델은 `extra="forbid"`, 불변(`frozen`)이다.
