# Project 모델과 명령: 단위·좌표·값 배지, 재료·부품·DesignSpec·World·가정표, Command, 되돌리기와 이력, 저장·열기·정의 해시 (C-01a, C-01b, C-01c, C-01d, C-02a, C-02b, C-03)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/`(`conventions.py`, `provenance.py`, `material.py`, `partdef.py`, `designspec.py`, `world.py`, `assumption.py`, `project.py`, `commands.py`, `canonical.py`, `projectfile.py`), 테스트는 `packages/core/tests/test_material_partdef.py`와 `test_designspec.py`, `test_world_assumption.py`, `test_commands.py`, `test_save_hash.py`.
- 근거: `docs/plan/studio-plan.md` 5절, `docs/architecture/client-adapter.md` G4·G6, 이슈 #60의 A0-04 이월 코멘트.
- 범위 밖: MJCF(X-01). JSON Schema와 TS 타입은 코어 모델에서 생성한다(아래 "스키마와 TS 타입", C-01d).

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
- `PartDef`: `parameters`(이름, 단위, 기본값·최소·최대; 최소 <= 기본 <= 최대), `snap_points`(ID, 종류, 받아들이는 종류, 부품 로컬 좌표의 위치 `offset + Σ factor × 길이 파라미터`, 방향 쿼터니언, 배지·출처), `specs`(`SpecDef`: 이름이 붙은 `Quantity`의 튜플, 사양), `shape`(선택, B-01a: 질량·관성 계산의 레시피). `mass_parameter`(선택, B-02c: 질량을 정하는 kg 파라미터의 이름. 있으면 부품의 질량은 그 값이고 재료를 읽지 않는다. [`part-payload.md`](part-payload.md)), `role`(선택, B-03b: `motor` `thruster` `wheel` `battery` `tank` `spring_damper`. 모터는 곡선 `torque_speed`와 사양 `rated_voltage`가 있어야 한다), `curves`(`NamedCurve`의 튜플, B-03b: 점들과 단위, 배지·출처 하나. [`part-motor.md`](part-motor.md)).
- 파라미터를 참조하는 스냅 포인트는 존재하는 길이(m) 파라미터만 가리킬 수 있다. 한 `PartDef` 안에서 파라미터 이름, 스냅 포인트 ID, 사양 이름은 각각 겹치지 않고, 스냅 포인트 ID와 사양 이름은 파라미터 이름과도 겹치지 않는다.
- 모든 모델은 `extra="forbid"`, 불변(`frozen`)이고 컬렉션은 튜플이라 `PartDef`는 해시된다. 순서는 값의 일부로 보존한다(순서가 다르면 다른 값). 정의 해시용 정규 순서는 아래 "저장·열기와 정의 해시"(C-03)가 정한다.

## `DesignSpec` (C-01b)

사용자가 만든 것: 부품 인스턴스, 결합, 액추에이터, 제어 스케줄. 쓰는 `Material`과 `PartDef`를 함께 담는다(계획 5.3절 "프로젝트는 쓰는 부품 정의를 담는다"). 참조(인스턴스 → 부품·재질, 결합 → 스냅 포인트, 액추에이터 → 인스턴스·결합, 스케줄 → 액추에이터)는 검증에서 닫혀 있어야 하고, 끊긴 참조는 관련 ID와 함께 거부된다. 정의가 빠진 프로젝트를 "정의 없음"으로 여는 규칙은 C-06이 이 검사를 완화하며 이 PR 범위 밖이다. 같은 컬렉션 안의 ID(재질·부품·인스턴스·결합·액추에이터)는 겹치지 않는다. 컬렉션은 튜플이고 순서가 값의 일부인 것은 위와 같다.

| 레코드 | 필드 | 규칙 |
|---|---|---|
| `Instance` | `id`, `part`, `parameters`, `material`(없을 수 있음), `pose` | `parameters`는 부품의 파라미터 이름만, 단위가 `ParamDef`와 같고 `[min, max]` 안이며, 같은 이름은 한 번만. 적지 않은 파라미터는 `PartDef` 기본값. 각 값은 `Quantity`(배지·출처 필수) |
| `Pose` | `position`(`WorldPosition`, m, 월드), `orientation`(`{x,y,z,w}` 단위 쿼터니언), `badge`, `source` | 부품 좌표계의 월드 자세. 인스턴스 위치의 저장된 권위는 이 자세다. 배지·출처 하나가 자세 전체를 덮는다(스냅 포인트와 같다) |
| `Joint` | `id`, `kind`(`fixed` `hinge` `slider`), `a`, `b`(`SnapRef`: 인스턴스 ID + 스냅 포인트 ID), `axis`, `limits`, `break_threshold` | 양끝은 서로 다른 인스턴스의 존재하는 스냅 포인트이고 한 스냅 포인트는 결합 하나에만 쓰인다. `a`가 부모, `b`가 자식이다. `axis`(`JointAxis`: 단위 벡터 `x` `y` `z` + `badge` `source`)는 힌지가 도는 축, 슬라이더가 움직이는 방향이고 `a`의 스냅 포인트 좌표계로 적는다. 없으면 그 좌표계의 +Z(`DEFAULT_JOINT_AXIS`, 휠 `hub`·모터 `shaft`가 쓰는 관례)이며 고정 결합에는 축이 없다(적으면 거부). 길이는 1 ± 1e-6이다. 결합 좌표의 0은 저장된 자세다(힌지 0 rad, 슬라이더 0 m). `limits`는 `Quantity` 두 개(`lower < upper`, 같은 단위, 양끝 포함)이고 저장된 자세가 한계 안에 있어야 한다(`lower <= 0 <= upper`): 힌지는 rad, 슬라이더는 m, 고정 결합에는 없다. 없으면 한계가 없다(바퀴 축). `break_threshold`는 `Quantity`(N, > 0)이고 세 종류 모두에 둘 수 있으며 없으면 파단하지 않는다 |
| `Actuator` | `id`, `kind`(`motor` `thruster`), `instance`, `joint` | 모터는 구동할 결합이 있어야 하고(고정 결합이 아니고, `instance`가 그 결합의 한쪽 끝), 추력기에는 결합이 없다. 같은 `kind`·`instance`·`joint`의 액추에이터 둘은 거부한다. 액추에이터 ID가 곧 조종 채널 ID다(`client-adapter.md` I5) |
| `ControlSchedule` | `entries`: `ActuateEntry`(`id`, `actuator`, `start`, `end`[s], `command`, `badge`, `source`) | `0 <= start < end`. `command`는 완전 구동 대비 비율이고 모터는 [-1, 1], 추력기는 [0, 1]. `id`는 스케줄 안에서 유일하다(명령이 항목을 위치가 아니라 ID로 가리킨다, C-02a). 한 액추에이터의 구간은 겹치지 않는다(맞닿는 것은 된다). 배지·출처 하나가 항목을 덮는다 |

- `command`가 1일 때 몇 N·m, 몇 N인지는 부품의 사양(곡선)에서 온다(B-03b, B-03c, X-01b, X-01c). `DesignSpec`은 비율만 안다.
- 자세가 권위다. 결합은 어느 두 스냅 포인트가 한 쌍인지만 말하고 아무것도 옮기지 않는다. 결합한 스냅 포인트가 저장된 자세에서 실제로 겹치는지, 부품이 공중에 떠 있는지는 배치 검사(C-02c 검증기, X-01d 컴파일 오류)이고 `DesignSpec` 검증이 아니다. 4륜차 예시는 조립된 차(바퀴 중심 z = 0.05 m, 오른쪽 모터는 Z축으로 180° 돌림, 맞닿는 스냅 포인트는 서로 `accepts`)이고 `test_designspec_four_wheel_car_is_assembled`가 결합한 모든 쌍이 월드에서 1e-9 안에 겹치는지 검사한다.
- 결합 그래프가 트리(고리 없음, 한 덩어리)인지는 바디 트리를 만드는 X-01a의 규칙이고 컴파일 오류(X-01d)로 낸다. 이 모델은 양끝 존재와 스냅 포인트 중복 사용만 본다.
- 액추에이터 종류와 부품 역할의 대응: 모터 액추에이터는 역할이 `motor`인 부품의 인스턴스에, 추력기는 `thruster`인 부품에 붙는다(B-03b, `part-motor.md`). 다른 역할이면 거절하고, 역할이 없는 부품은 받는다.
- 결합의 종류별 자유도(B-04a): `b`가 `a`에 대해 갖는 자유도는 고정 0, 힌지 회전 1(축 둘레), 슬라이더 이동 1(축 방향)이다(`joint_dof(kind)` → `JointDof(rotational, translational)`). `Joint.displacement(coordinate)`는 결합 좌표 하나에서 `b`가 저장된 자세에서 얼마나 옮겨 가는지 `(R, t)`(`a` 스냅 좌표계, 힌지는 `a`의 축을 지나는 점 둘레 오른손 회전, 슬라이더는 축 방향 이동)로 돌려주고, 좌표 0은 `(I, 0)`이다. 한계 밖이거나 유한하지 않은 좌표, 고정 결합의 0이 아닌 좌표는 오류다. 축의 부호를 뒤집으면 같은 직선에 좌표(와 한계, 모터 명령)의 부호만 뒤집힌다. 월드에서의 축(`a` 인스턴스 자세 × `a` 스냅 자세 × 축)과 두 스냅 방향이 이 축과 맞는지는 바디 트리를 만드는 X-01a와 컴파일 오류 X-01d의 몫이다. 스냅 호환 태그 검사는 B-04b, 스프링-댐퍼는 B-03e·X-01b가 더한다. `break_threshold`는 필드와 단위(N, > 0) 검사까지이고 파단 임계의 계산(물성 × 단면)은 X-04a, 파단 판정은 X-04다. 분리 항목(`type: "separate"`)은 X-08이 `ActuateEntry`와 같은 자리에 더한다.
- `axis`는 B-04a가 더한 선택 필드라 없는 값은 정규 형태에서 빠지고(`Joint.axis` 기본값 `None`이 `OMITTED_DEFAULTS`에 고정됨) 축이 없는 옛 파일의 해시는 그대로다. 예시 3종(`DesignSpec.four-wheel-car`, `Project.four-wheel-car`, `Project.rocket-car-skeleton`)의 힌지는 `a`의 스냅 포인트 좌표계가 항등이라 `(0, 1, 0)`을 `axis`로 적었다(`사용자 선언`). 월드에서는 바퀴 축인 Y 직선이고, 모터를 Z축으로 180° 돌린 오른쪽은 방향이 -Y다. 그래서 예시 해시 둘이 바뀌었다. 저장 형식 `version`은 그대로다: 필드를 더했을 뿐 규칙이 바뀐 것이 아니다.
- 이 PR의 수치는 모두 테스트가 선언한 값(`사용자 선언`)이다. 실부품 수치는 이 PR에 없다.

## World와 가정표 (C-01c)

코드는 `kinetra_core/world.py`, `assumption.py`, 테스트는 `packages/core/tests/test_world_assumption.py`. 이 PR에는 행성 수치가 없다. 행성 데이터와 로더는 W-01이고 [`bodies.md`](bodies.md)에 있다.

- `World`: `planet`(ID 하나)과 `terrain_props`(경사로 `RampProp`, 턱 `StepProp`; `kind`로 구분하고 `kind`는 필수다). 중력, 대기 밀도, 지면 마찰, 일사는 행성의 상수라서 `data/bodies`(W-01)에만 있고 엔진만 읽는다(`client-adapter.md` 규칙 C4). `World`에는 그 값을 담을 필드가 없고, `gravity`, `g`, `air_density`, `ground_friction`, `insolation` 같은 이름(`PLANET_CONSTANT_NAMES`)이 오면 이유를 말하며 거부한다. 이 목록은 친절일 뿐이고(목록에 없는 이름은 `extra="forbid"`가 거부한다) 보장은 구조에서 나온다: 엔진은 행성 상수를 `data/bodies`에서만 읽고(W-03a) 검증기가 바꾸려는 명령을 거부한다(C-02c). `planet`이 `data/bodies`에 있는지와 `material`이 프로젝트의 재료인지는 `World` 혼자 알 수 없어서 검증기(#68)와 교차 참조 규칙(#76)이 본다.
- 지형 소품: 평지는 z = 0 평면이고, 소품은 중심 (`x`, `y`)[m]과 +Z 둘레 회전 `yaw`[rad]로 놓는 `length` x `width` 직사각형이다. 놓는 자세 `placement`(x, y, yaw)는 `SnapPoint` 자세처럼 배지와 출처 하나가 통째로 덮는다. 크기(`length`, `width`, `incline`, `height`)는 각각 `Quantity`(배지·출처 필수)다. 경사로는 `incline`(rad, 0 초과 pi/2 미만)이고 `length`는 수평 길이다(높이는 `length * tan(incline)`로 파생하며 저장하지 않는다). 턱은 `height`(m, > 0). 표면 재료는 `material` ID로 참조하고(마찰은 재료의 것이다) `None`이면 행성 지면이다(마찰은 행성 데이터). 소품 ID는 월드 안에서 겹치지 않는다. 형상과 MJCF는 W-05, X-01이다.
- 가정표: legacy `SpecSheet`의 `Assumption`(`legacy-v0:schemas/spec_sheet.schema.json`)을 옮겼다. `key`, `label`, `value`(공칭값, 결정론 탐색용), `distribution`(몬테카를로가 뽑는 분포: `fixed`, `uniform`, `normal`; 모델 이름은 `FixedDistribution` 등, `kind` 필수), `confidence`(`low`/`med`/`high`), `editable`은 그대로다. 바뀐 점: legacy의 `value`+`unit`+`source`(자유 문자열)는 `value: Quantity`(값, 닫힌 단위, 배지, 구조화된 출처) 하나가 됐고, `uniform`과 `normal`의 수치는 그 자체로 새 수치라서 각자 배지와 출처를 가진다(공칭값을 인용했다고 퍼짐까지 인용한 것은 아니다). 분포의 수치는 `value.unit` 단위다(단위가 그 가정에 맞는지는 검사하지 않는다). 공칭값은 분포의 지지 안에 있어야 한다(`uniform`: `low <= value <= high`, `normal`: `clip_low`/`clip_high`가 있으면 그 안; 클립이 없는 `normal`은 제한 없음). `label`은 1~100자이고 공백뿐이면 거부한다. `AssumptionTable`은 키가 겹치지 않고 순서를 보존하며, 행성 상수 이름의 키(`gravity` 등)를 거부한다. 이것도 친절일 뿐이고 `Assumption` 하나만 만들 때는 검사하지 않는다(보장은 위와 같다). legacy `SpecSheet`의 부품, 탐색 범위, 성공 기준, 템플릿은 옮기지 않았다(다른 잎의 일이다).
- 모델 라벨("근사: 균일 중력" 등)은 W-03b, W-06이 더한다.

## 스키마와 TS 타입 (C-01d)

모델이 단일 원본이다. `schemas/`는 거기서 생성한 것이라 손으로 고치지 않는다.

```
uv run python packages/core/scripts/export_schemas.py          # schemas/ 를 다시 쓴다
uv run python packages/core/scripts/export_schemas.py --check  # 쓰지 않고 차이만 본다(CI, engine 워크플로)
```

- 무엇을 내보내는가는 어디에도 적혀 있지 않다. 스크립트는 `kinetra_core.__all__`의 pydantic 모델, enum, 유니온 별칭(`Distribution`, `TerrainProp`)을 모두 가져온다. 뒤 잎이 `kinetra_core/__init__.py`에 모델을 내보내면 스크립트를 고치지 않아도 스키마와 타입이 생긴다. 상수, 함수, 예외는 스키마가 없어서 건너뛴다. 모델도 enum도 아닌 클래스를 내보내면 내보내기가 실패한다(클라이언트가 볼 수 있는 것이 타입 없이 남지 않게). 같은 이름의 서로 다른 스키마도 실패한다. 판별 유니온(`discriminator`)의 멤버가 태그(`kind`, `type`)를 `required`로 갖지 않거나(태그 필드에 기본값을 둔 경우) 단일 리터럴이 아니어도 실패한다. 태그 없는 문서가 스키마를 통과해 어느 멤버인지 정하지 못하는 일을 막는다.
- `schemas/<Name>.schema.json`: 이름 하나마다 JSON Schema(draft 2020-12) 한 파일. `$defs`를 포함해 혼자 쓸 수 있다. 입력 검증 모드(코어가 받아들이는 JSON)이고 `const`/`exclusiveMinimum`/`pattern`으로 단위, 범위, ID 형식이 실린다.
- `schemas/types.ts`: 모든 이름의 TypeScript `interface`/`type`(`packages/core/scripts/schema_to_ts.py`). 기본값이 있는 필드는 선택(`?`)이다. 코어가 빠진 것을 채워 주기 때문이다. 단위는 필드마다 리터럴 타입(`unit: "kg/m^3"`), 배지와 단위 어휘는 닫힌 유니온이다. 변환기가 모르는 스키마 키워드를 만나면 경로와 함께 실패한다(조용히 느슨한 타입을 내지 않는다).
- 타입은 모양만 안다. 교차 검사(참조가 닫혀 있는가, 쿼터니언이 단위 길이인가, 자리표시 출처인가)는 코어의 검증기가 한다. 클라이언트는 타입으로 읽고 쓰되 판정은 코어에 맡긴다.
- 웹: `schemas/`는 pnpm 워크스페이스 패키지 `@kinetra/schemas`(`types`는 `types.ts`, `@kinetra/schemas/<Name>.schema.json`으로 스키마도 가져온다)이고 `apps/studio`가 의존한다. `pnpm lint`가 `tsc`로 타입을, `pnpm test`가 `schemas/test/types.test.ts`를 돈다.
- `schemas/examples/<Name>.<설명>.json`은 손으로 쓴 예시다(`DesignSpec.four-wheel-car`, `Material.example`, `PartDef.block-with-hole`(형상 포함), `World.ramp-and-step`, `AssumptionTable.vehicle-mass`, `CommandBatch.move-and-select-planet`). `packages/core/tests/test_schema_export.py`가 예시마다 JSON Schema(`jsonschema`)와 모델 둘 다 통과하는지 보고, 잘못된 입력(출처 없음, 모르는 배지, 틀린 단위, 범위 밖, 배열 쿼터니언, 모르는 필드)을 둘 다 거부하는지 본다. 예시의 수치는 실부품 데이터가 아니다. 대부분 `사용자 선언`이고 일부는 `기본값`(`Material.example`과 4륜차 예시의 재료 마찰)과 `추정`(가정표의 퍼짐)이며 출처 문구에 "예시"라고 적었다.
- 새 모델을 더한 PR은 `export_schemas.py`를 돌려 `schemas/`를 같이 커밋한다. 안 하면 CI의 `--check`와 `test_committed_schemas_match_the_models`가 실패한다.

## 예시 프로젝트 (C-01 에픽 통합, #60)

`schemas/examples/Project.<설명>.json` 셋이 에픽의 통합 시연이다. `Project`는 `design`과 `assumptions`(둘 다 생략하면 빈 값)와 필수인 `world`를 가진다.

| 파일 | 내용 |
|---|---|
| `Project.four-wheel-car.json` | 4륜차(`DesignSpec.four-wheel-car`의 조립된 차) + 지구 + 경사로 하나 + 차량 질량 가정. 모터 둘이 힌지 둘을 구동한다 |
| `Project.rocket-car-skeleton.json` | 섀시 + 바퀴 넷(액슬 힌지 넷) + 로켓 부품 하나(고정 결합) + 달. 추력기 액추에이터 하나(`kind: thruster`, 결합 없음, C-01b)와 그 스케줄 항목(`command` = 1, 0~2 s). 로켓의 `rated_thrust` 사양(`SpecDef`)은 선언값이다. 뼈대라서 성능을 주장하지 않는다 |
| `Project.empty.json` | `{"world": {"planet": "earth"}}`. 부품·결합·가정이 없는 프로젝트 |

- 검증: `uv run python packages/core/scripts/validate_examples.py`. `schemas/examples/*.json`을 모두 JSON Schema(`jsonschema`)와 Pydantic 모델 둘 다로 검사하고, `Project`는 `world.planet`이 `data/bodies`에 있는지와 지형 소품의 재료가 프로젝트의 것인지도 `check_world_references`로 본다. 필수 예시 셋이 하나라도 없거나 로켓 자동차에 스케줄된 추력기가 없으면 실패한다. CI는 `engine` 워크플로에서 돈다. `packages/core/tests/test_examples.py`가 같은 스크립트와 예시의 내용(조립 일치, 되돌리기 가능한 명령 적용, 배지)을 시험한다.
- TS: `schemas/test/examples.test.ts`가 세 예시를 `@kinetra/schemas`의 `Project` 타입으로 읽는다(`pnpm build`가 타입을, `pnpm test`가 값을 본다). 타입은 모양만 안다. 유효성 판정은 위 스크립트가 한다.
- 예시의 수치는 모두 `사용자 선언`(`kinetra-docs`)이거나 `기본값`/`추정`이고 출처 문구에 "illustrative"가 있다. 실부품 수치도 성능 주장도 아니다.

## `Project`와 `Command` (C-02a)

코드는 `kinetra_core/project.py`, `commands.py`, 테스트는 `packages/core/tests/test_commands.py`. 모든 편집은 `Command`다(계획 5.3절, `client-adapter.md` I1). 입력 수단(마우스, 에이전트, 음성, XR, MCP)마다 다른 Command는 없다.

- `Project` = `design`(`DesignSpec`) + `world`(`World`, 필수) + `assumptions`(`AssumptionTable`). 명령이 적용되는 단위이고 클라이언트가 사본으로 쥐는 문서다(`client-adapter.md` D1). 각 부분의 검사는 그 부분에 있고, `Project`는 부분을 가로지르는 참조 하나만 더한다: 지형 소품의 `material`은 프로젝트의 재료여야 한다. `bodies.check_world_references`(W-01)의 재료 쪽 규칙과 같은 것이고(`world`와 `design.materials`의 ID를 받는다), 행성에 데이터가 있는지는 그 함수와 검증기(C-02c)의 몫으로 `Project`가 검사하지 않는다. 그래서 끊긴 참조(부품 없는 인스턴스, 스냅 포인트 없는 결합, 결합 없는 모터, 액추에이터 없는 스케줄 항목, 재료 없는 소품)를 가진 `Project`는 만들어지지 않는다.
- `apply_command(project, command) -> ApplyResult(project, inverse)`. 입력을 바꾸지 않고, 새 `Project`와 역명령을 돌려준다. 결과는 `Project.model_validate`로 통째로 다시 검증한다(`model_copy`는 검증을 건너뛰므로 쓰지 않는다). 거부되면 `CommandRejected`의 `reasons`(`Reason`: `code`, 읽을 수 있는 문장, `ids`: `{kind, id}` 참조 목록)가 오고 프로젝트는 그대로다(`rejected` 메시지의 내용, `client-adapter.md` 3.2). 코드: `unknown_id`, `duplicate_id`, `in_use`, `index_out_of_range`, `invalid_command`, `invalid_project`(검증기 문장을 그대로 싣고, 끊긴 참조는 그 ID를 `ids`에 싣는다), `not_editable`, 그리고 검증기(C-02c)의 `forbidden`, `invalid_snap`, `overlap`, `floating`. `ids`의 `kind`는 `instance`, `joint`, `actuator`, `part`, `material`, `snap_point`(`<인스턴스>/<스냅 포인트>`), `schedule_entry`, `assumption`, `parameter`(`<인스턴스>/<이름>`), `planet`, `prop`이다. ID는 자기 컬렉션 안에서만 유일해서 종류 없는 문자열은 부품 `wheel`과 인스턴스 `wheel`을 구분하지 못한다. 결과 타입은 `ApplyResult`다(`client-adapter.md` 3.1의 `applied` 메시지는 개정 번호와 발행자를 더해 C-05a가 만든다).
- 역명령을 적용하면 원본과 같은 프로젝트가 된다(모든 컬렉션의 순서까지). 역명령의 역명령은 같은 편집을 다시 한다(다시 실행). 테스트가 명령마다 이를 본다.
- 명령은 기존 항목을 ID로 가리킨다(위치로 가리키지 않는다). 부분 수락(C2)이나 낡은 기준 개정(C5)에서 위치로 가리키는 명령은 유효한 채로 다른 항목을 고친다. `index`는 `add_*`가 새 항목을 어디에 넣을지만 뜻한다.
- `type` 태그가 필수인 판별 유니온 `Command`(`schemas/Command.schema.json`, `types.ts`의 `Command`). 명령은 문서의 말로 쓴다(ID, 파라미터 이름, SI 값과 배지·출처; I2). 누가 보냈는지는 명령에 없고 이력 기록(C-02b)이 갖는다.

| 명령 | 효과 | 역명령 |
|---|---|---|
| `add_instance` / `remove_instance` | 부품 인스턴스 추가·삭제. 삭제는 그 인스턴스의 결합, 그 인스턴스나 그 결합에 달린 액추에이터, 그 액추에이터의 스케줄 항목을 같은 명령에서 함께 지운다 | `remove_instance` / 묶음(`add_instance`, 지운 결합·액추에이터·항목을 원래 위치에 다시 추가) |
| `move_instance` | 인스턴스의 저장된 월드 자세를 바꾼다. 결합한 짝은 따라오지 않는다(자세가 권위). 짝이 따라오게 하려면 묶음으로 보낸다 | 이전 자세의 `move_instance` |
| `set_parameter` / `clear_parameter` | 인스턴스의 파라미터 값을 정하거나(단위·범위는 `PartDef`의 것) 지워 기본값으로 되돌린다 | 이전 값의 `set_parameter`, 또는 `clear_parameter`(지운 자리에 `index`) |
| `set_instance_material` | 인스턴스에 프로젝트의 재료를 지정(`None`이면 없음) | 이전 재료 |
| `add_joint` / `replace_joint` / `remove_joint` | 결합·해제. `replace_joint`는 같은 ID의 결합을 제자리에서 통째로 바꾼다(한계, 파단 임계, 종류, 끝): 목록 위치와 그 결합의 액추에이터·항목이 그대로이고, 모터가 서 있던 결합이 고정 결합이 되는 식으로 달린 것을 깨면 거부된다. 해제는 그 결합을 모터가 구동하던 액추에이터와 그 항목을 함께 지운다 | `remove_joint` / 이전 결합의 `replace_joint` / 묶음 |
| `add_actuator` / `remove_actuator` | 액추에이터. 삭제는 그 스케줄 항목도 지운다 | `remove_actuator` / 묶음 |
| `add_control_entry`, `remove_control_entry`(`id`), `replace_control_entry`(`entry.id`가 같은 항목을 제자리에서) | 제어 스케줄 항목. `add`의 `index`는 위치일 뿐이다 | `remove`의 역은 원래 위치에 `add` |
| `add_assumption`, `set_assumption`(같은 `key`를 제자리에서 교체), `remove_assumption`(`key`) | 가정표 편집. `editable: false`인 가정은 바꾸거나 지울 수 없고(`not_editable`), `set_assumption`으로 `editable`을 뒤집을 수 없으며 `editable: false`인 가정을 새로 넣을 수도 없다(넣으면 다시 바꿀 수 없어 역명령이 성립하지 않는다) | 서로의 역 |
| `select_planet` | `world.planet`을 ID로 바꾼다. 행성 상수는 어떤 명령에도 실리지 않는다(`client-adapter.md` C4) | 이전 행성 |
| `add_*_def`, `replace_part_def`, `replace_material_def`, `remove_*_def` | 프로젝트가 담는 정의(재료·부품). 삭제는 쓰는 곳이 있으면 `in_use`로 거부한다(사용자가 지우지 않은 것을 지우지 않는다). 쓰이는 정의는 삭제할 수 없으므로 명령으로 바꾸는 길은 `replace_*`(같은 ID, 제자리, 목록 위치 유지)뿐이다. 프로젝트 전체를 다시 검증하므로 쓰는 곳을 깨는 정의(인스턴스가 정한 파라미터가 없어짐, 범위 밖이 됨, 결합이 쓰는 스냅 포인트가 없어짐)는 그 사유와 깨진 대상의 참조와 함께 거부된다. 출처(발행자)로 허용을 나누지 않는다: 검증기는 발행자를 받지 않는다(C-02c) | `add`↔`remove` / 이전 정의의 `replace` |
| `batch` | 편집 명령을 순서대로 모두 적용하거나 모두 거부한다(C2). 중첩은 없다. 사유의 문장 앞에 `commands[n] (type):`이 붙는다. **최종 상태만이 아니라 모든 중간 상태가 유효한 `Project`여야 한다**: 한 액추에이터의 두 구간을 맞바꾸는 묶음은 첫 명령에서 겹침으로 거부된다. 줄이거나 지우는 명령을 먼저 두거나 `replace_*`를 쓴다(에이전트 재시도 G-03a, 대칭 복제 B-11이 알아야 한다) | 역명령들의 역순 묶음 |

- 목록 순서는 값의 일부라서 `add_*`는 `index`(없으면 끝)를 받고, 역명령은 원래 자리로 되돌린다.
- 같은 값을 다시 정하는 명령(같은 행성, 같은 재료, 같은 자세)은 수락되고 같은 프로젝트를 돌려준다. 빈 이력 칸과 불필요한 판정 무효화(D5)를 거르는 일은 C-02b가 `결과.project == project`로 판단하고, 그 판단은 아래 "되돌리기와 이력"에 있다.
- 편집마다 프로젝트 전체를 JSON으로 덤프하고 다시 검증하므로 편집 하나는 프로젝트 크기에 비례하고 묶음은 n배다(리뷰 측정: 인스턴스 200개에서 단일 이동 약 11 ms, 200건 묶음 약 1.1 s; 1,000개에서 25 ms, 4 s). 명령의 모양과 무관한 내부 문제라서 별도 이슈로 추적한다.
- 역명령은 목록의 절대 위치(`index`)를 담는다. 한 줄로 선형인 이력(S1)에서는 역명령이 늘 자기가 계산된 상태에 적용되므로 정확하다. 다른 편집이 끼어드는 사용자별 되돌리기(N-04)는 위치가 아니라 이웃을 가리키는 방식이 필요하다.
- 삭제가 연쇄를 일으켜도 한 명령이고 한 역명령이다(#476 리뷰: 끊긴 상태를 만들지 않는다). 이력에서 한 칸이 되는 단위는 아래 "되돌리기와 이력"이 정한다.
- 이 PR에 없는 것: 배치 검사와 행성 상수·물성 DB·판정 결과를 바꾸려는 시도의 거부(C-02c, 아래 "검증기"), 지형 소품 편집(W-05), 수역(FL-02b), 분리 항목(X-08), 정의가 없는 인스턴스(C-06). 이 PR의 예시 수치는 모두 테스트가 선언한 값이다.

## 되돌리기와 이력 (C-02b)

코드는 `kinetra_core/history.py`, 테스트는 `packages/core/tests/test_history.py`(`uv run pytest packages/core -q -k history`). `apply_command`가 돌려주는 `(project, inverse)` 위에 선 값 객체 하나다. 모든 메서드가 입력을 바꾸지 않고 새 값을 돌려준다.

- `History`(`entries`, `cursor`): `entries[:cursor]`가 적용된 칸, 그 뒤가 되돌려서 다시 실행할 수 있는 칸이다. `execute(project, command, origin)`, `undo(project)`, `redo(project)`는 `EditResult(project, history, entry)`를 돌려준다. 프로젝트와 이력은 한 쌍이다: 이력은 자기가 실행해 온 프로젝트에만 맞는다(보관은 문서의 주인인 C-05a가 한 몸으로 한다).
- **한 칸 = 명령 하나.** 편집 하나는 한 칸이고 `batch`는 안에 몇 개가 있든 한 칸이라서 되돌리기 한 번에 묶음 전체가 돌아오고 다시 실행 한 번에 전체가 다시 된다(`client-adapter.md` C2, I4: 이력의 한 칸은 사용자가 확정한 동작 하나). 기즈모로 조립체를 옮기는 일, 방사 대칭 복제, 수락한 에이전트 변경안은 보내는 쪽이 묶음 한 건으로 만든다. 칸을 나중에 합치는 호출은 없다.
- **출처는 명령이 아니라 기록에 있다.** `HistoryEntry`(`origin`, `command`, `inverse`)의 `origin`은 `Origin`(`mouse`, `agent`, `voice`, `xr`, `mcp`; `client-adapter.md` 3.5의 입력 수단)이다. 같은 명령은 어느 출처에서 와도 같은 편집이고 같은 적용기를 거친다(I1, C1). 이력은 출처로 무엇을 허용할지 정하지 않는다(C-02c). 되돌리기와 다시 실행은 새 칸이 아니고 되돌리거나 다시 한 칸의 출처를 그대로 가진다.
- 칸은 보낸 명령과 적용기가 계산한 역명령을 함께 쥔다. 되돌리기는 저장된 역명령을, 다시 실행은 저장된 명령을 적용한다. 둘 다 계산된 바로 그 상태에 적용되므로(선형 이력) 위치 `index`가 어긋나지 않는다.
- **바꾸는 것이 없는 명령은 칸을 만들지 않는다.** 적용 결과가 입력과 같으면(같은 행성, 같은 자세, 옮겼다 되돌리는 묶음) 명령은 수락되지만 이력은 그대로이고 `EditResult.entry`는 `None`이다. 아무것도 하지 않는 되돌리기 단계를 막고, 되돌려 둔 칸(다시 실행할 칸)을 잃지 않으며, C-05a가 개정 번호와 판정 상태(D5)를 건드리지 않을 근거가 된다.
- 되돌린 뒤 문서를 실제로 바꾸는 새 명령이 오면 다시 실행할 칸은 버려진다(새 상태에 맞지 않는다).
- 거부된 명령은 아무것도 바꾸지 않는다(`CommandRejected`). 되돌릴 것이 없을 때의 `undo`와 다시 할 것이 없을 때의 `redo`도 같은 길로 거부한다(`nothing_to_undo`, `nothing_to_redo`).
- 이력 길이의 상한은 없다. 계획과 이슈 어디에도 숫자가 없어서 만들어 쓰지 않았다. 칸당 명령 둘을 쥔다. 상한은 보관하는 C-05a가 정한다. 저장 파일에는 넣지 않는다(아래 C-03).
- 이 PR에 없는 것: 개정 번호와 `applied` 메시지(C-05a), 여러 사용자의 사용자별 되돌리기(N-04), 출처별 허용 정책(C-02c), 시각(벽시계 시각은 결정론 문서에 두지 않는다).

## 저장·열기와 정의 해시 (C-03)

코드는 `kinetra_core/canonical.py`(정규 형식과 해시), `projectfile.py`(파일), 테스트는 `packages/core/tests/test_save_hash.py`(`uv run pytest packages/core -q -k "save or hash"`). 클라우드 저장과 계정은 범위 밖이다.

### 파일

프로젝트 파일은 UTF-8 JSON 문서 하나이고 이름은 `*.kinetra.json`이 관례다(`PROJECT_FILE_SUFFIX`). 모양은 `ProjectFile`(`schemas/ProjectFile.schema.json`, 예시 `schemas/examples/ProjectFile.four-wheel-car.json`)이다.

| 필드 | 뜻 |
|---|---|
| `format`, `version` | `"kinetra-project"`, `1`. 읽는 쪽이 모르는 `version`은 다른 것을 읽기 전에 거부한다(`unsupported_version`). 버전은 봉투와 정규 규칙을 가리키고, 모델이 기존 데이터의 뜻을 바꿀 때도 올린다(필드의 이름·뜻·삭제 변경). **기본값이 있는 선택 필드를 더하는 것은 올리지 않는다**: 새 빌드는 이전 파일을 그대로 열고(없는 필드는 기본값) 해시도 같다(기본값은 해시에서 빠진다). 대신 새 빌드가 쓴 파일(`null`인 새 필드까지 쓴다)을 이전 빌드는 열지 못한다(아래 "앞으로 호환이 없다"). B-02c의 `PartDef.mass_parameter`가 그 경우이고, 고정한 v1 파일은 그대로 열리며 해시가 같다(`test_save_open_reads_the_frozen_v1_file`). **모델의 기본값을 바꾸는 것도 형식 변경이다**(해시가 기본값인 필드를 빼므로 기본값은 규칙의 일부다): 버전을 올리고, 새 읽기는 이전 버전의 파일을 그 버전의 규칙으로 대조한 뒤 이관한다. 정규 규칙이 생략하는 기본값 표는 `test_hash_omitted_defaults_are_pinned`가 고정하고, 다시 만들지 않는 v1 파일 `packages/core/tests/fixtures/project-file-v1.kinetra.json`이 `test_save_open_reads_the_frozen_v1_file`로 "v1은 지금도 열린다"를 지킨다 |
| `project` | `Project` 그대로. 컬렉션 순서는 사용자가 가진 순서를 보존한다(순서는 값의 일부) |
| `project_hash` | 프로젝트 전체의 해시(정규 형식) |
| `definitions` | 프로젝트가 담은 재료와 부품 정의마다 `{kind, id, hash}`. 프로젝트의 순서(재료, 그다음 부품)를 따른다. 계획 5.3절의 "쓰는 부품 정의를 정의 해시와 함께 담는다"의 해시다. 카탈로그와 비교해 "카탈로그와 다름"을 알리는 것은 C-06이다 |

- `save_project(project, path)`는 대상의 실제 경로(`realpath`: 심볼릭 링크는 따라가서 링크가 가리키는 파일이 갱신되고 링크는 남는다)와 같은 폴더에, 무작위 이름(`.kinetra-<16자리 16진>.tmp`)으로 배타 생성(`O_EXCL`: 같은 경로를 동시에 저장해도 임시 파일을 같이 쓰지 않고, 미리 심어 둔 링크를 따라가지 않는다)한 파일에 쓰고, 임시 파일은 소유자만 읽고 쓰게(0600) 만들어 내용이 대상보다 넓게 열린 순간이 없게 한 뒤 쓴 다음에 원래 파일의 권한 비트(새 파일이면 umask를 뺀 기본값)를 옮기고, 장치까지 내린 뒤(`fsync`, macOS는 드라이브 캐시까지 비우는 `F_FULLFSYNC`) `os.replace`로 바꾼다. 쓰다 실패하거나 프로세스가 끊겨도 이전 파일이 그대로 남고 임시 파일은 지운다. 같은 경로를 동시에 두 번 저장하면 각각 온전한 파일을 쓰고 마지막 교체가 이긴다(섞이지 않는다). 약속하지 않는 것: 전원이 나갈 때 디렉터리 항목까지 남는지(폴더는 `fsync`하지 않는다), Windows에서 다른 프로세스가 연 파일을 바꾸는 일(실패하고 이전 파일은 남는다). `open_project(path)` / `parse_project(bytes|str)`는 읽어서 `ProjectFile`을 돌려주거나 `ProjectFileError(code, ...)`를 던진다. `dump_project`는 파일의 바이트다.
- **저장 → 열기 → 저장이 바이트 단위로 같다.** 같은 `Project`는 같은 바이트다(모델의 필드 순서, 들여쓰기 2칸, `ensure_ascii` 끔, 끝에 개행 하나, 파이썬의 가장 짧은 왕복 숫자 표기). 다른 프로그램이 쓴 파일(키 순서, 공백, 컬렉션 순서가 다른 것)은 열리고, 처음 저장할 때 이 형식으로 정리되며 그 뒤로 안정이다. 바이트 보존은 이 모듈이 쓴 파일에 대한 약속이다.
- 열 때 해시를 읽은 프로젝트와 대조한다. 저장한 뒤 손으로 고쳤거나 잘렸거나 정규 규칙을 따르지 않는 쓰기 도구가 만든 파일은 `hash_mismatch`로 거부하고 무엇이 다른지 적는다. 조용히 열지 않는다. 사유는 `not_json`(JSON이 아님, 잘림, 중복 키, `NaN`/`Infinity`), `not_a_project_file`, `unsupported_version`, `invalid_project`(검증기의 문장), `hash_mismatch`다.
- 해시는 서명이 아니다. 값을 바꾸고 해시도 맞게 다시 쓴 파일은 다른 프로젝트의 올바른 파일이다. 해시는 같은지 다른지만 말한다.
- JSON 내보내기: `export_json(project)`는 봉투와 해시 없이 `Project`만 같은 서식으로 내놓는다(`schemas/Project.schema.json`이 설명하는 문서, `Project.model_validate_json`으로 열린다).
- **v1에는 앞으로 호환이 없다(결정).** 모든 모델이 `extra="forbid"`이고 쓰기는 `null`인 필드까지 전부 쓴다. 선택 필드를 하나 더한 빌드의 파일을 이전 빌드가 열면 `version`이 1이어도 `invalid_project`(\"Extra inputs are not permitted\")다. 일부러 그렇게 정했다: 기본값이 있는 선택 필드를 더해도 `version`은 그대로이므로(위 표) 이전 빌드는 새 빌드의 파일을 `invalid_project`로 거부한다. 그 값이 하는 일을 바꾸는 변경(필드 이름·뜻·삭제, 기본값, 정규 규칙)은 `version`을 올려 모르는 버전을 `version`으로 먼저 정확한 사유와 함께 거부한다. `client-adapter.md` G5(모르는 선택 필드는 무시)는 선로 프로토콜의 규칙이고 이 파일의 규칙이 아니다. 해시가 기본값 필드를 빼는 것은 이 규칙과 모순이 아니다: 해시는 \"같은 값인가\"를, 파일은 \"이 빌드가 아는 것만 담았는가\"를 말한다. C-06(#455)은 `Project` 검증을 완화해 빠진 정의를 담게 하고 `_differences`의 \"프로젝트가 담지 않은 정의의 해시\" 규칙도 바꿔야 하는데, 조용히 무시하는 필드를 만들지 않는 이 규칙을 지키고 그 변경에 필요한 이관을 함께 가져온다.
- 이력(C-02b)은 저장하지 않는다. 역명령은 계산된 그 상태에서만 맞는 절대 위치를 담아서, 프로젝트 없는 이력도 다른 프로젝트의 이력도 쓸모없다. 다시 연 프로젝트는 빈 `History`로 시작한다. 개정 번호, 발행자, 시각도 없다(저장 파일은 문서이고 사건이 아니다; 벽시계 시각은 의미가 없다, `client-adapter.md` F2).

### 정규 형식과 해시

해시는 "같은 것"을 말한다. 표시만 다른 두 값(목록 순서, 키 순서, 공백, `1`과 `1.0`, 시각을 쓴 UTC 오프셋)은 같은 해시이고 나머지가 다른 두 값은 다른 해시다. `project_hash(project)`와 `definition_hash(PartDef | Material)`는 `sha256:` + 아래 정규 텍스트의 UTF-8 바이트의 소문자 16진 SHA-256이다. 해시는 알고리즘만 싣고 규칙은 싣지 않는다: 규칙이 바뀌면 파일 `version`을 올린다.

- **키**: JSON 객체의 키는 UTF-16 코드 단위 순으로 정렬한다(RFC 8785). 필수가 아닌 필드가 기본값이면 빼서, 뒤 잎이 선택 필드를 더해도 그 필드를 건드리지 않은 값의 해시가 바뀌지 않는다(`client-adapter.md` G5). 그래서 `{"design": {"materials": []}}`와 `design` 생략은 같은 해시이고, 항등 방향을 명시한 형상 요소와 생략한 것도 같다.
- **컬렉션 순서**: 항목을 이름 붙이는 키로, **필드마다** 정렬한다(`canonical._ORDER`는 (소유 모델, 필드 이름)이 키다). `DesignSpec`의 재료·부품·인스턴스·결합·액추에이터, `ControlSchedule.entries`, `World.terrain_props`는 `id`; `PartDef.parameters`·`specs`와 `Instance.parameters`는 `name`; `PartDef.snap_points`와 `Shape.components`는 `id`; `PartDef.curves`(B-03b)는 `name`, `Curve.points`는 `x`(엄격히 증가하므로 전순서이고 보존된다); `AssumptionTable.assumptions`는 `key`; `SnapPoint.accepts`는 태그 값; `AxisExpr.terms`는 `(param, factor)`. 모든 컬렉션 항목은 그 컬렉션 안에서 유일한 키를 가지므로(모델이 검사한다) 순서는 전순서다. ID와 이름은 ASCII 패턴이라 코드 포인트 순과 UTF-16 코드 단위 순이 같다: TS 클라이언트는 `localeCompare`가 아니라 코드 단위 비교(`<`)를 써야 한다(`a_b`와 `a-b`의 순서가 로캘마다 다르다). 컬렉션이 아닌 것의 순서는 의미라서 그대로다: 결합의 `a`(부모)와 `b`(자식), 쿼터니언 성분, 위치 성분.
- **새 컬렉션은 순서를 정해야 한다**: 등록되지 않은 튜플 필드를 만나면 파일 순서로 해시하지 않고 `CanonicalError`를 던진다. 키가 항목 타입이 아니라 필드에 걸려 있어서 다른 필드가 `tuple[str, ...]`를 등록했다는 이유로 순서가 의미인 목록(경유 ID 목록, 분리 순서)이 조용히 정렬되지 않는다. `Project`에서 닿는 모든 튜플 필드가 `_ORDER`에 있고 `_ORDER`에 튜플이 아닌 필드가 없는지 `test_hash_every_collection_of_the_project_model_has_a_canonical_order`가 모델을 훑어 검사하고(뒤 잎의 새 튜플 필드에서 실패한다), 순서가 의미인 필드는 등록하지 않는 새 규칙(파일 버전)으로 다룬다. 시각이 UTC로 쓸 수 없는 범위(0001-01-01 +09:00 등)면 `CanonicalError`다.
- **숫자**: ECMAScript `Number.prototype.toString`(RFC 8785 3.2.2.3)과 같은 글자다. 같은 double로 읽히는 가장 짧은 자릿수, `1.0`은 `1`, `-0.0`은 `0`, 1e-6 미만과 1e21 이상은 지수 표기(`1e-7`, `1e+21`). 테스트 벡터는 JavaScript(Bun)의 `String(x)`에서 얻었고 같은 규칙으로 해시하는 TS 클라이언트는 같은 글자를 얻는다. 유한하지 않은 수는 모델이 이미 거부한다.
- **시각**: `declared_at`은 UTC로 바꿔 `YYYY-MM-DDTHH:MM:SS[.f]Z`로 쓴다(소수부 끝의 0은 뗀다). 같은 순간은 오프셋이 달라도 같은 해시다.
- **문자열**: RFC 8785의 이스케이프(`"`, `\`, 제어 문자만)이고 글자 그대로 UTF-8이다. 앞뒤 공백을 자르거나 유니코드 정규화를 하지 않는다: 다른 문자열은 다른 값이다. 토큰 사이에 공백이 없다.
- **정의 해시**: `PartDef`나 `Material` 하나의 필드만 해시한다. 어느 프로젝트의 몇 번째에 있는지는 해시에 들어가지 않는다. 같은 ID의 재료와 부품은 필드가 달라 해시가 다르다.

한계(`canonical.py` 머리말): 해시가 같은 두 프로젝트는 문서로서 같고 엔진 입력으로서 비트가 같다는 약속이 아니다. 인스턴스를 목록 순서로 더하는 엔진의 부동소수점 합은 순서가 다르면 끝자리가 다를 수 있고 MuJoCo는 바디 순서로 풀이를 한다(리뷰 측정: 형상 요소 5개의 120가지 순서에서 `definition_hash`는 1개, `MassProperties`의 비트는 5가지). 정규 순서로 컴파일하는 규칙은 #511이 맡는다. 그 전까지 **저장소에 정의 해시가 둘이다**: 이 문서의 `definition_hash`(순서 무관: "같은 정의인가", C-06의 카탈로그 비교와 파일의 `definitions`)와 B-01d의 `part_key`(`kinetra_engine.parts.cache`, 엄격: 순서·문구까지 다르면 다른 키, 부품 캐시). 컴파일 결과의 캐시 키로 `definition_hash`를 쓰면 안 된다. 판정 캐시(J)와 `run_started`의 키도 `project_hash` 하나로는 안 되고 (프로젝트 해시, 플랫폼 태그, 시드, 계산 설정)이어야 한다(행성 상수는 `data/bodies`에, 엔진 빌드는 태그에 있다). 해시는 서명이 아니라서 서버는 받은 해시를 믿지 말고 다시 계산한다. 이름·출처 문구·`declared_at`·배지도 해시에 들어가므로 이름만 고쳐도 해시가 바뀐다(안전한 쪽의 오류; 물리 부분만의 해시는 B-16이 필드 거르개로 더한다). 궤적 해시는 X-02d, 에셋 내용 해시는 A2의 몫이다.

## 선로의 메시지 (C-05a)

`Command`와 `ApplyResult`를 선로에 올리는 메시지(`hello` `subscribe` `snapshot` `resumed` `applied` `publish` `accepted` `rejected` `request` `error`)는 `kinetra_core/protocol.py`에 있고 `schemas/`에 `ClientMessage`, `ServerMessage`로 생성된다. `ApplyResult`(프로젝트 + 역명령)는 그대로 적용기의 값이고, 선로의 `applied`(개정 번호, 발행자, 바뀐 구역)는 `Applied`로 이름이 다르다. 규칙과 필드는 [`client-adapter.md`](client-adapter.md) 3.1~3.2 확정.

- 이력 길이의 상한은 없다. 계획과 이슈 어디에도 숫자가 없어서 만들어 쓰지 않았다. 칸당 명령 둘을 쥔다. 상한이나 저장 여부는 보관하는 C-03, C-05a가 정한다.
- 이 PR에 없는 것: 개정 번호와 `applied` 메시지(C-05a), 이력의 저장 형식과 해시(C-03), 여러 사용자의 사용자별 되돌리기(N-04), 출처별 허용 정책(없다: 검증기는 발행자를 받지 않는다, C-02c), 시각(벽시계 시각은 결정론 문서에 두지 않는다).

## 검증기 (C-02c)

코드는 `kinetra_core/validator.py`(충돌 도형 검사는 `convex.py`, B-01a에서 엔진에서 옮겨 옴), 테스트는 `packages/core/tests/test_validator.py`. 모든 편집이 지나는 한 문이다(`client-adapter.md` C1, C4). **발행자를 받지 않는다**: 마우스, 에이전트, 음성, XR, MCP가 같은 답을 받는다(발행자는 이력의 기록이다, C-02b).

- `parse_command(json) -> Command`: 어느 클라이언트의 JSON이든 명령 하나가 되거나 `CommandRejected`. 스키마 위반은 `invalid_command`(문제마다 사유 하나). 행성 상수(`PLANET_CONSTANT_NAMES`)나 판정(`verdict`, `p_success`, `ci`)을 싣거나 그런 이름의 `type`(`set_gravity`, `set_verdict` ...)은 `forbidden`이고 이유를 말한다. 보장은 구조에서 나온다(명령 유니온이 닫혀 있고 `extra="forbid"`라서 상수를 실을 필드가 없다). 이름 목록은 사유를 정확히 쓰기 위한 것이다.
- `validate_command(project, command) -> ApplyResult`: `apply_command`에 정책과 배치 검사를 더한다. C-02b 이력, C-05a 선로, G-02a 도구가 `apply_command` 대신 이것을 부른다.
- `check_placement(project) -> tuple[Reason, ...]`: 프로젝트가 가진 배치 문제 전부.

| 코드 | 거부하는 경우 |
|---|---|
| `forbidden` | 위의 행성 상수·판정 시도, 행성 상수 이름의 가정 키, 재료 카탈로그(`load_material_catalog`)의 ID를 쓰면서 카탈로그 정의와 다른 재료, 또는 카탈로그에 없는 ID인데 `cite` 속성이 카탈로그가 인용한 출처를 다른 수치로 쓰는 재료(`add_material_def`, `replace_material_def`). 사용자 자신의 재료는 `declared`(또는 자기 출처의 `cite`)로 얼마든지 쓸 수 있다 |
| `unknown_id`(ref `planet`) | `world.planet`이 `data/bodies`의 행성이 아님(`check_world_references`, C-01c 이월 1). 지형 소품의 `material`이 프로젝트의 재료인지(이월 2)는 `Project`가 이미 닫는다 |
| `invalid_snap` | 결합한 두 스냅 포인트가 서로의 `kind`를 받아들이지 않음, 또는 저장된 자세에서 만나지 않음(결합은 아무것도 옮기지 않는다) |
| `overlap` | 두 인스턴스의 충돌 도형이 파고듦, 또는 지면(z = 0) 아래로 내려감 |
| `floating` | 결합이나 접촉으로 이어진 한 덩어리가 지면이나 지형 소품에 닿지 않음 |

배치 규칙과 한계(숨기지 않는다):

- 인스턴스의 도형은 부품 형상 레시피의 `add` 요소를 인스턴스의 파라미터와 월드 자세에 놓은 것이다(충돌 프록시가 복사하는 것과 같은 기본형, 빈 곳은 메운다). **형상 레시피가 없는 부품은 도형이 없어** `overlap`, `floating`으로 판단하지 않고, 도형 없는 인스턴스와 결합한 덩어리는 뜬 것으로 부르지 않는다. 통과가 아니라 모르는 것이다. 4륜차 예시(형상 없음)는 스냅 검사만 받는다.
- 겹침은 `convex.separated`(질량 계산이 쓰는 같은 분리 평면 검사)다. 맞닿음은 겹침이 아니다. 기울어진 두 원기둥이 모서리끼리 거의 닿는 경우는 겹침으로 거부될 수 있다(거부이지 조용한 통과가 아니다).
- 지형 소품은 월드 규약 그대로의 볼록 도형이다(경사로: `length` 진행 × `width` × 높이 `length*tan(incline)`인 쐐기, 턱: 상자, 둘 다 `yaw`로 돌림). 부품이 소품을 파고들면(턱 안, 경사면 아래) `overlap`(ref: 인스턴스와 `prop`)이고 받침이 아니다. 닿기만 하면 받침이다. 지면 높이를 가진 시작 자세(낙하 시나리오)는 J-02의 몫이라 이 검사에는 없고, 공중에 놓인 조립 전체는 `floating`이다.
- **되돌리기와 다시 실행은 배치 검사를 다시 하지 않는다.** `History.undo/redo`(C-02b)는 `apply_command`만 부른다. 되돌리기는 이전에 받아들여진 상태로, 다시 실행은 받아들여진 명령으로 돌아가는 것이라서(선형 이력, 역명령은 계산된 바로 그 상태에 적용된다) 배치 규칙이 그 사이에 바뀌지 않는 한 같은 답이다. 이미 겹친 프로젝트를 고친 편집을 되돌리면 겹친 상태가 돌아오는데, 그 상태는 사용자가 가졌던 것이다("새로 만든 문제만 거부한다"의 같은 근거). 새 편집은 문을 지난다: `History.execute`가 `validate_command`를 부르므로 거부된 명령(`forbidden`, `overlap` ...)은 프로젝트도 이력도 바꾸지 못한다(`test_history_execute_*`).
- 허용 오차 `PLACEMENT_TOLERANCE` = 1 µm는 저장된 double을 위한 수치 허용치이지 물리적 주장이 아니다.
- **명령이 새로 만든 문제만 거부한다.** 이미 겹침이 있는 프로젝트(파일에서 연 것)도 다른 곳은 고칠 수 있다. 묶음은 구조(`apply_command`)를 단계마다, 배치는 **끝 상태**로 본다: `add_instance` 뒤 `add_joint`, 조립 전체의 이동이 중간 상태가 헐거워도 된다.
- 스냅의 방향(쿼터니언)과 결합 축은 비교하지 않는다(결합 축의 월드 방향은 X-01a, 스냅 호환은 B-04b). 컴파일 오류는 X-01d, 지형 소품 편집은 W-05.

## 알려진 확장 (이 PR 범위 밖, 뒤 잎이 더한다)

- 곡선(토크-속도, 추력 곡선): B-03b에서 들어왔다. `Curve`, `PartDef.curves`, 모터 `torque_speed`. [`part-motor.md`](part-motor.md). 추력 곡선은 B-03c에서 들어왔다(`thrust`).
- 단위 `V`, `A`는 B-03b가 더했다. `kg/s`(추진제 소모율), `N*s`(충격량)는 B-03c가 더했다(`KG_PER_S`, `N_S`).
- 추력기 부품: B-03c. `PartRole.THRUSTER`의 요건(`thrust` 곡선, `rated_thrust`·`propellant_flow` 사양, `nozzle` 스냅 포인트), 엔진 쪽 계산과 카탈로그 범위. `docs/architecture/parts-thruster.md`.
- 형상 레시피와 파생값의 입력: B-01a에서 들어왔다. `PartDef.shape`, `MassProperties.derivation`. `docs/architecture/part-mass.md`. 같은 레시피에서 시각 glTF와 재질 슬롯: B-01c, `docs/architecture/part-visual.md`.
- 충돌 프록시: B-01b에서 들어왔다. `CollisionProxy`(기본형 지오메트리, 메운 빈 곳 또는 B-01f의 분해한 빈 곳, 부호 있는 부피 오차). `docs/architecture/collision-proxy.md`.
- 컴파일 캐시와 부품 추가 절차서: B-01d. `docs/architecture/part-cache.md`, `docs/process/add-part.md`.
- 구조 부품 빔과 판: B-02a. 정의는 `packages/engine/src/kinetra_engine/parts/library/`. `docs/architecture/parts-beam-plate.md`.
- 구동 부품 휠: B-03a. 정의는 같은 디렉터리의 `wheel.json`. `docs/architecture/parts-wheel.md`.
- 바인딩 안 된 가정(가정이 설계의 어느 값을 흔드는지)과 가정 단위의 의미 검사: J-01a, L-02.
- PBR 재질 슬롯: B-07(구현됨, [`materials.md`](materials.md)).
- `export_policy`: HW-02a.
- 모델은 불변이지만 `model_copy(update=...)`는 검증을 건너뛴다. 명령 적용기(C-02a)는 JSON 형태로 고친 뒤 `model_validate`로 통째로 다시 검증한다.
