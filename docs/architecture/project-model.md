# Project 모델: 단위·좌표·값 배지 (C-01a)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/`(`conventions.py`, `provenance.py`, `material.py`, `partdef.py`), 테스트는 `packages/core/tests/test_material_partdef.py`.
- 근거: `docs/plan/studio-plan.md` 5절, `docs/architecture/client-adapter.md` G4·G6, 이슈 #60의 A0-04 이월 코멘트.
- 범위 밖: MJCF(X-01), 인스턴스·결합(C-01b), World·가정표(C-01c), JSON Schema·TS 파일 생성(C-01d). 모델은 Pydantic v2라서 `model_json_schema()`로 스키마가 이미 나온다. 파일로 내보내는 일은 C-01d다.

## 규약 (확정)

| 항목 | 값 |
|---|---|
| 단위 | SI: m, kg, s, rad. 닫힌 어휘 `Unit`(`kg/m^3`, `Pa`, `N`, `N*m`, `1`(무차원) 등). 어휘에 없는 단위 문자열(`mm`, `deg`, `g/cm^3`)은 검증에서 거부된다 |
| 좌표계 | 오른손 좌표계, +Z가 위 |
| 쿼터니언 | Project JSON에서는 성분 이름이 있는 객체 `{x, y, z, w}`, `w`가 스칼라, 길이 1(허용 오차 1e-6). 배열로 쓰지 않는다. 실행 스트림 프레임(C-05b)은 같은 성분 순서와 뜻만 따르고 인코딩은 C-05b가 정한다 |
| 수 | 유한한 JSON 숫자. 문자열·불리언·NaN·Infinity는 거부 |
| ID | 재료·부품·스냅 포인트 `^[a-z][a-z0-9_-]{0,63}$`, 파라미터·사양·종류 태그 `^[a-z][a-z0-9_]{0,63}$` |

## 값 배지와 출처

모든 물리 수치는 `Quantity`(값, 단위, 배지, 출처)다. 배지와 출처가 없으면 검증이 거부한다. 배지 JSON 값은 승인된 디자인 시스템의 어휘(`design/exports/design-system/tokens.css`)를 따르고 화면 라벨은 그대로다.

| JSON | 화면 | 뜻 | 근거 팝오버가 읽는 출처 필드 |
|---|---|---|---|
| `sim` | 시뮬 | 시뮬 실행에서 나온 값 | `ref`(실행 기록) |
| `cite` | 인용 | 문서·데이터시트에서 옮긴 값. `source.locator`(표, 쪽, 절) 또는 `source.url`이 필요하다 | `ref`(출처), `locator`/`url`, `license`(SPDX 식), 원장 항목 |
| `default` | 기본값 | 우리가 정한 값. `source.ref`에 정한 이유 | `ref`(기본값 표의 항목) |
| `declared` | 사용자 선언 | 사용자가 넣은 값 | `declared_by`, `declared_at`(시간대 있는 시각) |
| `estimate` | 추정 | 근거가 약한 판단 | `ref`(방법 이름과 입력) |

- `source.license`는 `cite`에만, `declared_by`와 `declared_at`은 `declared`에만 쓸 수 있다. 라이선스는 SPDX 표현식이고 `NONE`·`NOASSERTION`·`UNKNOWN`은 거부한다.
- 자리표시 거부: `ref`, `locator`, `declared_by`는 글자나 숫자가 하나는 있어야 하고, 앞뒤 구두점을 걷어 낸 뒤 `TBD`·`TODO`로 시작하거나 `n/a`, `none`, `unknown`, `없음`, `미정`, `출처 없음` 등과 같으면 거부한다. 목록은 완전하지 않다. 거르지 못한 어림은 리뷰 루브릭 4번이 본다.
- `url`은 `http(s)`이고 호스트가 있으며 공백이 없어야 한다.
- `source.ref`가 가리키는 것이 값을 실제로 뒷받침하는지는 모델이 검사할 수 없다.

## 모델

- `Material`: `density`(kg/m^3, > 0), `yield_strength`(Pa, > 0), `elastic_modulus`(Pa, > 0), `friction`(무차원 쿨롱 계수, >= 0). 필드마다 단위와 범위가 타입에 있어 오류가 그 필드를 가리키고 JSON Schema에 `const`/`exclusiveMinimum`이 실린다. 두 재료의 접촉 마찰을 어떻게 합치는지는 컴파일러(X-01)가 정한다. 실제 재료 5종의 값은 B-07이 출처와 함께 채운다. 이 PR에는 실재료 수치가 없다.
- `PartDef`: `parameters`(이름, 단위, 기본값·최소·최대; 최소 <= 기본 <= 최대), `snap_points`(ID, 종류, 받아들이는 종류, 부품 로컬 좌표의 위치 `offset + Σ factor × 길이 파라미터`, 방향 쿼터니언, 배지·출처), `specs`(`SpecDef`: 이름이 붙은 `Quantity`의 튜플, 사양).
- 파라미터를 참조하는 스냅 포인트는 존재하는 길이(m) 파라미터만 가리킬 수 있다. 한 `PartDef` 안에서 파라미터 이름, 스냅 포인트 ID, 사양 이름은 각각 겹치지 않고, 스냅 포인트 ID와 사양 이름은 파라미터 이름과도 겹치지 않는다.
- 모든 모델은 `extra="forbid"`, 불변(`frozen`)이고 컬렉션은 튜플이라 `PartDef`는 해시된다. 순서는 값의 일부로 보존한다(순서가 다르면 다른 값). 정의 해시용 정규 순서는 C-03이 정한다.

## 알려진 확장 (이 PR 범위 밖, 뒤 잎이 더한다)

- 곡선(토크-속도, 추력 곡선): B-03b, B-03c.
- 단위 `kg/s`(추진제 소모율), `N*s`(충격량): 쓰는 잎이 `Unit`에 더한다.
- 형상 레시피와 파생값의 입력: B-01a.
- PBR 재질 슬롯: B-07.
- `export_policy`: HW-02a.
- 모델은 불변이지만 `model_copy(update=...)`는 검증을 건너뛴다. 명령 적용기(C-02a)는 바꾼 뒤 `model_validate`로 다시 검증해야 한다.
