# Project 모델: 단위·좌표·값 배지, 재료·부품·DesignSpec·World·가정표 (C-01a, C-01b, C-01c)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/`(`conventions.py`, `provenance.py`, `material.py`, `partdef.py`, `designspec.py`, `world.py`, `assumption.py`), 테스트는 `packages/core/tests/test_material_partdef.py`와 `test_designspec.py`, `test_world_assumption.py`.
- 근거: `docs/plan/studio-plan.md` 5절, `docs/architecture/client-adapter.md` G4·G6, 이슈 #60의 A0-04 이월 코멘트.
- 범위 밖: MJCF(X-01), JSON Schema·TS 파일 생성(C-01d). 모델은 Pydantic v2라서 `model_json_schema()`로 스키마가 이미 나온다. 파일로 내보내는 일은 C-01d다.

## 규약 (확정)

| 항목 | 값 |
|---|---|
| 단위 | SI: m, kg, s, rad. 닫힌 어휘 `Unit`(`kg/m^3`, `Pa`, `N`, `N*m`, `1`(무차원) 등). 어휘에 없는 단위 문자열(`mm`, `deg`, `g/cm^3`)은 검증에서 거부된다 |
| 좌표계 | 오른손 좌표계, +Z가 위 |
| 쿼터니언 | Project JSON에서는 성분 이름이 있는 객체 `{x, y, z, w}`, `w`가 스칼라, 길이 1(허용 오차 1e-6). 배열로 쓰지 않는다. 실행 스트림 프레임(C-05b)은 같은 성분 순서와 뜻만 따르고 인코딩은 C-05b가 정한다 |
| 수 | 유한한 JSON 숫자. 문자열·불리언·NaN·Infinity는 거부 |
| ID | 재료·부품·스냅 포인트·인스턴스·결합·액추에이터·행성·지형 소품 `^[a-z][a-z0-9_-]{0,63}$`(`ID_PATTERN`), 파라미터·사양·종류 태그·가정 키 `^[a-z][a-z0-9_]{0,63}$` |

## 값 배지와 출처

모든 물리 수치는 `Quantity`(값, 단위, 배지, 출처)다. 배지와 출처가 없으면 검증이 거부한다. 배지 JSON 값은 승인된 디자인 시스템의 어휘(`design/exports/design-system/tokens.css`)를 따르고 화면 라벨은 그대로다.

| JSON | 화면 | 뜻 | 근거 팝오버가 읽는 출처 필드 |
|---|---|---|---|
| `sim` | 시뮬 | 엔진이 계산한 값(시뮬 실행, 또는 닫힌 식 계산: 파생 질량·관성). 입력의 배지는 값과 함께 가는 `derivation`에 있다 | `ref`(실행 기록 또는 계산 함수) |
| `cite` | 인용 | 문서·데이터시트에서 옮긴 값. `source.locator`(표, 쪽, 절) 또는 `source.url`이 필요하다 | `ref`(출처), `locator`/`url`, `license`(SPDX 식), 원장 항목 |
| `default` | 기본값 | 우리가 정한 값. `source.ref`에 정한 이유 | `ref`(기본값 표의 항목) |
| `declared` | 사용자 선언 | 사용자가 넣은 값 | `declared_by`, `declared_at`(시간대 있는 시각) |
| `estimate` | 추정 | 근거가 약한 판단 | `ref`(방법 이름과 입력) |

- `source.license`는 `cite`에만, `declared_by`와 `declared_at`은 `declared`에만 쓸 수 있다. 라이선스는 `assets/LEDGER.csv`와 같은 규칙의 SPDX 표현식이다(허용 목록의 식별자, `AND`/`OR`/`WITH`/괄호, `LicenseRef-*`는 `source.ref`에 `LicenseRef 사유: …`가 있을 때만, `NC`·`NONE`·`NOASSERTION`·`UNKNOWN` 거부). 파서는 `tools/assets/credits.py`의 사본(`kinetra_core/spdx.py`)이고 코어가 `tools/`를 import하지 않기 위해서다. 허용 목록·판정이 어긋나면 `tests/test_spdx.py`가 실패한다.
- 자리표시 거부: `ref`, `locator`, `declared_by`는 글자나 숫자가 하나는 있어야 하고, 앞뒤 구두점을 걷어 낸 뒤 `TBD`·`TODO`로 시작하거나 `n/a`, `none`, `unknown`, `없음`, `미정`, `출처 없음` 등과 같으면 거부한다. 목록은 완전하지 않다. 거르지 못한 어림은 리뷰 루브릭 4번이 본다.
- `url`은 `http(s)`이고 호스트가 있으며 공백이 없어야 한다.
- `source.ref`가 가리키는 것이 값을 실제로 뒷받침하는지는 모델이 검사할 수 없다.

## 모델

- `Material`: `density`(kg/m^3, > 0), `yield_strength`(Pa, > 0), `elastic_modulus`(Pa, > 0), `friction`(무차원 쿨롱 계수, >= 0). 필드마다 단위와 범위가 타입에 있어 오류가 그 필드를 가리키고 JSON Schema에 `const`/`exclusiveMinimum`이 실린다. 두 재료의 접촉 마찰을 어떻게 합치는지는 컴파일러(X-01)가 정한다. 실제 재료 5종의 값은 B-07이 출처와 함께 채웠다: [`materials.md`](materials.md).
- `PartDef`: `parameters`(이름, 단위, 기본값·최소·최대; 최소 <= 기본 <= 최대), `snap_points`(ID, 종류, 받아들이는 종류, 부품 로컬 좌표의 위치 `offset + Σ factor × 길이 파라미터`, 방향 쿼터니언, 배지·출처), `specs`(`SpecDef`: 이름이 붙은 `Quantity`의 튜플, 사양), `shape`(선택, B-01a: 질량·관성 계산의 레시피).
- 파라미터를 참조하는 스냅 포인트는 존재하는 길이(m) 파라미터만 가리킬 수 있다. 한 `PartDef` 안에서 파라미터 이름, 스냅 포인트 ID, 사양 이름은 각각 겹치지 않고, 스냅 포인트 ID와 사양 이름은 파라미터 이름과도 겹치지 않는다.
- 모든 모델은 `extra="forbid"`, 불변(`frozen`)이고 컬렉션은 튜플이라 `PartDef`는 해시된다. 순서는 값의 일부로 보존한다(순서가 다르면 다른 값). 정의 해시용 정규 순서는 C-03이 정한다.

## `DesignSpec` (C-01b)

사용자가 만든 것: 부품 인스턴스, 결합, 액추에이터, 제어 스케줄. 쓰는 `Material`과 `PartDef`를 함께 담는다(계획 5.3절 "프로젝트는 쓰는 부품 정의를 담는다"). 참조(인스턴스 → 부품·재질, 결합 → 스냅 포인트, 액추에이터 → 인스턴스·결합, 스케줄 → 액추에이터)는 검증에서 닫혀 있어야 하고, 끊긴 참조는 관련 ID와 함께 거부된다. 정의가 빠진 프로젝트를 "정의 없음"으로 여는 규칙은 C-06이 이 검사를 완화하며 이 PR 범위 밖이다. 같은 컬렉션 안의 ID(재질·부품·인스턴스·결합·액추에이터)는 겹치지 않는다. 컬렉션은 튜플이고 순서가 값의 일부인 것은 위와 같다.

| 레코드 | 필드 | 규칙 |
|---|---|---|
| `Instance` | `id`, `part`, `parameters`, `material`(없을 수 있음), `pose` | `parameters`는 부품의 파라미터 이름만, 단위가 `ParamDef`와 같고 `[min, max]` 안이며, 같은 이름은 한 번만. 적지 않은 파라미터는 `PartDef` 기본값. 각 값은 `Quantity`(배지·출처 필수) |
| `Pose` | `position`(`WorldPosition`, m, 월드), `orientation`(`{x,y,z,w}` 단위 쿼터니언), `badge`, `source` | 부품 좌표계의 월드 자세. 인스턴스 위치의 저장된 권위는 이 자세다. 배지·출처 하나가 자세 전체를 덮는다(스냅 포인트와 같다) |
| `Joint` | `id`, `kind`(`fixed` `hinge` `slider`), `a`, `b`(`SnapRef`: 인스턴스 ID + 스냅 포인트 ID), `limits`, `break_threshold` | 양끝은 서로 다른 인스턴스의 존재하는 스냅 포인트이고 한 스냅 포인트는 결합 하나에만 쓰인다. `a`가 부모, `b`가 자식이다. 결합 좌표의 0은 저장된 자세다(힌지 0 rad, 슬라이더 0 m). `limits`는 `Quantity` 두 개(`lower < upper`, 같은 단위): 힌지는 rad, 슬라이더는 m, 고정 결합에는 없다. `break_threshold`는 `Quantity`(N, > 0)이고 없으면 파단하지 않는다 |
| `Actuator` | `id`, `kind`(`motor` `thruster`), `instance`, `joint` | 모터는 구동할 결합이 있어야 하고(고정 결합이 아니고, `instance`가 그 결합의 한쪽 끝), 추력기에는 결합이 없다. 같은 `kind`·`instance`·`joint`의 액추에이터 둘은 거부한다. 액추에이터 ID가 곧 조종 채널 ID다(`client-adapter.md` I5) |
| `ControlSchedule` | `entries`: `ActuateEntry`(`actuator`, `start`, `end`[s], `command`, `badge`, `source`) | `0 <= start < end`. `command`는 완전 구동 대비 비율이고 모터는 [-1, 1], 추력기는 [0, 1]. 한 액추에이터의 구간은 겹치지 않는다(맞닿는 것은 된다). 배지·출처 하나가 항목을 덮는다 |

- `command`가 1일 때 몇 N·m, 몇 N인지는 부품의 사양(곡선)에서 온다(B-03b, B-03c, X-01b, X-01c). `DesignSpec`은 비율만 안다.
- 자세가 권위다. 결합은 어느 두 스냅 포인트가 한 쌍인지만 말하고 아무것도 옮기지 않는다. 결합한 스냅 포인트가 저장된 자세에서 실제로 겹치는지, 부품이 공중에 떠 있는지는 배치 검사(C-02c 검증기, X-01d 컴파일 오류)이고 `DesignSpec` 검증이 아니다. 4륜차 예시는 조립된 차(바퀴 중심 z = 0.05 m, 오른쪽 모터는 Z축으로 180° 돌림, 맞닿는 스냅 포인트는 서로 `accepts`)이고 `test_designspec_four_wheel_car_is_assembled`가 결합한 모든 쌍이 월드에서 1e-9 안에 겹치는지 검사한다.
- 결합 그래프가 트리(고리 없음, 한 덩어리)인지는 바디 트리를 만드는 X-01a의 규칙이고 컴파일 오류(X-01d)로 낸다. 이 모델은 양끝 존재와 스냅 포인트 중복 사용만 본다.
- 액추에이터 종류와 부품 역할의 대응(모터 부품에 모터, 추력기 부품에 추력기)은 B-03b·B-03c가 부품에 역할을 주면 그때 검사한다.
- 결합의 축, 종류별 자유도, 스냅 호환 태그 검사는 B-04a·B-04b가, 스프링-댐퍼는 B-03e·X-01b가 더한다. 이 PR의 `limits`와 `break_threshold`는 그 필드가 올 자리와 단위 검사까지다. 파단 임계의 계산(물성 × 단면)은 X-04a다. 분리 항목(`type: "separate"`)은 X-08이 `ActuateEntry`와 같은 자리에 더한다.
- 이 PR의 수치는 모두 테스트가 선언한 값(`사용자 선언`)이다. 실부품 수치는 이 PR에 없다.

## World와 가정표 (C-01c)

코드는 `kinetra_core/world.py`, `assumption.py`, 테스트는 `packages/core/tests/test_world_assumption.py`. 이 PR에는 행성 수치가 없다. 행성 데이터와 로더는 W-01이다.

- `World`: `planet`(ID 하나)과 `terrain_props`(경사로 `RampProp`, 턱 `StepProp`; `kind`로 구분하고 `kind`는 필수다). 중력, 대기 밀도, 지면 마찰, 일사는 행성의 상수라서 `data/bodies`(W-01)에만 있고 엔진만 읽는다(`client-adapter.md` 규칙 C4). `World`에는 그 값을 담을 필드가 없고, `gravity`, `g`, `air_density`, `ground_friction`, `insolation` 같은 이름(`PLANET_CONSTANT_NAMES`)이 오면 이유를 말하며 거부한다. 이 목록은 친절일 뿐이고(목록에 없는 이름은 `extra="forbid"`가 거부한다) 보장은 구조에서 나온다: 엔진은 행성 상수를 `data/bodies`에서만 읽고(W-03a) 검증기가 바꾸려는 명령을 거부한다(C-02c). `planet`이 `data/bodies`에 있는지와 `material`이 프로젝트의 재료인지는 `World` 혼자 알 수 없어서 검증기(#68)와 교차 참조 규칙(#76)이 본다.
- 지형 소품: 평지는 z = 0 평면이고, 소품은 중심 (`x`, `y`)[m]과 +Z 둘레 회전 `yaw`[rad]로 놓는 `length` x `width` 직사각형이다. 놓는 자세 `placement`(x, y, yaw)는 `SnapPoint` 자세처럼 배지와 출처 하나가 통째로 덮는다. 크기(`length`, `width`, `incline`, `height`)는 각각 `Quantity`(배지·출처 필수)다. 경사로는 `incline`(rad, 0 초과 pi/2 미만)이고 `length`는 수평 길이다(높이는 `length * tan(incline)`로 파생하며 저장하지 않는다). 턱은 `height`(m, > 0). 표면 재료는 `material` ID로 참조하고(마찰은 재료의 것이다) `None`이면 행성 지면이다(마찰은 행성 데이터). 소품 ID는 월드 안에서 겹치지 않는다. 형상과 MJCF는 W-05, X-01이다.
- 가정표: legacy `SpecSheet`의 `Assumption`(`legacy-v0:schemas/spec_sheet.schema.json`)을 옮겼다. `key`, `label`, `value`(공칭값, 결정론 탐색용), `distribution`(몬테카를로가 뽑는 분포: `fixed`, `uniform`, `normal`; 모델 이름은 `FixedDistribution` 등, `kind` 필수), `confidence`(`low`/`med`/`high`), `editable`은 그대로다. 바뀐 점: legacy의 `value`+`unit`+`source`(자유 문자열)는 `value: Quantity`(값, 닫힌 단위, 배지, 구조화된 출처) 하나가 됐고, `uniform`과 `normal`의 수치는 그 자체로 새 수치라서 각자 배지와 출처를 가진다(공칭값을 인용했다고 퍼짐까지 인용한 것은 아니다). 분포의 수치는 `value.unit` 단위다(단위가 그 가정에 맞는지는 검사하지 않는다). 공칭값은 분포의 지지 안에 있어야 한다(`uniform`: `low <= value <= high`, `normal`: `clip_low`/`clip_high`가 있으면 그 안; 클립이 없는 `normal`은 제한 없음). `label`은 1~100자이고 공백뿐이면 거부한다. `AssumptionTable`은 키가 겹치지 않고 순서를 보존하며, 행성 상수 이름의 키(`gravity` 등)를 거부한다. 이것도 친절일 뿐이고 `Assumption` 하나만 만들 때는 검사하지 않는다(보장은 위와 같다). legacy `SpecSheet`의 부품, 탐색 범위, 성공 기준, 템플릿은 옮기지 않았다(다른 잎의 일이다).
- 모델 라벨("근사: 균일 중력" 등)은 W-03b, W-06이 더한다.

## 알려진 확장 (이 PR 범위 밖, 뒤 잎이 더한다)

- 곡선(토크-속도, 추력 곡선): B-03b, B-03c.
- 단위 `kg/s`(추진제 소모율), `N*s`(충격량): 쓰는 잎이 `Unit`에 더한다.
- 형상 레시피와 파생값의 입력: B-01a에서 들어왔다. `PartDef.shape`, `MassProperties.derivation`. `docs/architecture/part-mass.md`.
- 충돌 프록시: B-01b에서 들어왔다. `CollisionProxy`(기본형 지오메트리, 메운 빈 곳, 부피 오차). `docs/architecture/collision-proxy.md`.
- 바인딩 안 된 가정(가정이 설계의 어느 값을 흔드는지)과 가정 단위의 의미 검사: J-01a, L-02.
- PBR 재질 슬롯: B-07(구현됨, [`materials.md`](materials.md)).
- `export_policy`: HW-02a.
- 모델은 불변이지만 `model_copy(update=...)`는 검증을 건너뛴다. 명령 적용기(C-02a)는 바꾼 뒤 `model_validate`로 다시 검증해야 한다.
