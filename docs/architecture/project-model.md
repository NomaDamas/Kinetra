# Project 모델과 명령: 단위·좌표·값 배지, 재료·부품·DesignSpec·World·가정표, Command (C-01a, C-01b, C-01c, C-01d, C-02a)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/`(`conventions.py`, `provenance.py`, `material.py`, `partdef.py`, `designspec.py`, `world.py`, `assumption.py`, `project.py`, `commands.py`), 테스트는 `packages/core/tests/test_material_partdef.py`와 `test_designspec.py`, `test_world_assumption.py`, `test_commands.py`.
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
| `ControlSchedule` | `entries`: `ActuateEntry`(`id`, `actuator`, `start`, `end`[s], `command`, `badge`, `source`) | `0 <= start < end`. `command`는 완전 구동 대비 비율이고 모터는 [-1, 1], 추력기는 [0, 1]. `id`는 스케줄 안에서 유일하다(명령이 항목을 위치가 아니라 ID로 가리킨다, C-02a). 한 액추에이터의 구간은 겹치지 않는다(맞닿는 것은 된다). 배지·출처 하나가 항목을 덮는다 |

- `command`가 1일 때 몇 N·m, 몇 N인지는 부품의 사양(곡선)에서 온다(B-03b, B-03c, X-01b, X-01c). `DesignSpec`은 비율만 안다.
- 자세가 권위다. 결합은 어느 두 스냅 포인트가 한 쌍인지만 말하고 아무것도 옮기지 않는다. 결합한 스냅 포인트가 저장된 자세에서 실제로 겹치는지, 부품이 공중에 떠 있는지는 배치 검사(C-02c 검증기, X-01d 컴파일 오류)이고 `DesignSpec` 검증이 아니다. 4륜차 예시는 조립된 차(바퀴 중심 z = 0.05 m, 오른쪽 모터는 Z축으로 180° 돌림, 맞닿는 스냅 포인트는 서로 `accepts`)이고 `test_designspec_four_wheel_car_is_assembled`가 결합한 모든 쌍이 월드에서 1e-9 안에 겹치는지 검사한다.
- 결합 그래프가 트리(고리 없음, 한 덩어리)인지는 바디 트리를 만드는 X-01a의 규칙이고 컴파일 오류(X-01d)로 낸다. 이 모델은 양끝 존재와 스냅 포인트 중복 사용만 본다.
- 액추에이터 종류와 부품 역할의 대응(모터 부품에 모터, 추력기 부품에 추력기)은 B-03b·B-03c가 부품에 역할을 주면 그때 검사한다.
- 결합의 축, 종류별 자유도, 스냅 호환 태그 검사는 B-04a·B-04b가, 스프링-댐퍼는 B-03e·X-01b가 더한다. 이 PR의 `limits`와 `break_threshold`는 그 필드가 올 자리와 단위 검사까지다. 파단 임계의 계산(물성 × 단면)은 X-04a다. 분리 항목(`type: "separate"`)은 X-08이 `ActuateEntry`와 같은 자리에 더한다.
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

## `Project`와 `Command` (C-02a)

코드는 `kinetra_core/project.py`, `commands.py`, 테스트는 `packages/core/tests/test_commands.py`. 모든 편집은 `Command`다(계획 5.3절, `client-adapter.md` I1). 입력 수단(마우스, 에이전트, 음성, XR, MCP)마다 다른 Command는 없다.

- `Project` = `design`(`DesignSpec`) + `world`(`World`, 필수) + `assumptions`(`AssumptionTable`). 명령이 적용되는 단위이고 클라이언트가 사본으로 쥐는 문서다(`client-adapter.md` D1). 각 부분의 검사는 그 부분에 있고, `Project`는 부분을 가로지르는 참조 하나만 더한다: 지형 소품의 `material`은 프로젝트의 재료여야 한다. `bodies.check_world_references`(W-01)의 재료 쪽 규칙과 같은 것이고(`world`와 `design.materials`의 ID를 받는다), 행성에 데이터가 있는지는 그 함수와 검증기(C-02c)의 몫으로 `Project`가 검사하지 않는다. 그래서 끊긴 참조(부품 없는 인스턴스, 스냅 포인트 없는 결합, 결합 없는 모터, 액추에이터 없는 스케줄 항목, 재료 없는 소품)를 가진 `Project`는 만들어지지 않는다.
- `apply_command(project, command) -> ApplyResult(project, inverse)`. 입력을 바꾸지 않고, 새 `Project`와 역명령을 돌려준다. 결과는 `Project.model_validate`로 통째로 다시 검증한다(`model_copy`는 검증을 건너뛰므로 쓰지 않는다). 거부되면 `CommandRejected`의 `reasons`(`Reason`: `code`, 읽을 수 있는 문장, `ids`: `{kind, id}` 참조 목록)가 오고 프로젝트는 그대로다(`rejected` 메시지의 내용, `client-adapter.md` 3.2). 코드: `unknown_id`, `duplicate_id`, `in_use`, `index_out_of_range`, `invalid_command`, `invalid_project`(검증기 문장을 그대로 싣고, 끊긴 참조는 그 ID를 `ids`에 싣는다), `not_editable`. `ids`의 `kind`는 `instance`, `joint`, `actuator`, `part`, `material`, `snap_point`(`<인스턴스>/<스냅 포인트>`), `schedule_entry`, `assumption`, `parameter`(`<인스턴스>/<이름>`), `planet`, `prop`이다. ID는 자기 컬렉션 안에서만 유일해서 종류 없는 문자열은 부품 `wheel`과 인스턴스 `wheel`을 구분하지 못한다. 결과 타입은 `ApplyResult`다(`client-adapter.md` 3.1의 `applied` 메시지는 개정 번호와 발행자를 더해 C-05a가 만든다).
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
| `add_*_def`, `replace_part_def`, `replace_material_def`, `remove_*_def` | 프로젝트가 담는 정의(재료·부품). 삭제는 쓰는 곳이 있으면 `in_use`로 거부한다(사용자가 지우지 않은 것을 지우지 않는다). 쓰이는 정의는 삭제할 수 없으므로 명령으로 바꾸는 길은 `replace_*`(같은 ID, 제자리, 목록 위치 유지)뿐이다. 프로젝트 전체를 다시 검증하므로 쓰는 곳을 깨는 정의(인스턴스가 정한 파라미터가 없어짐, 범위 밖이 됨, 결합이 쓰는 스냅 포인트가 없어짐)는 그 사유와 깨진 대상의 참조와 함께 거부된다. 어느 출처가 정의 명령을 보낼 수 있는지는 C-02c | `add`↔`remove` / 이전 정의의 `replace` |
| `batch` | 편집 명령을 순서대로 모두 적용하거나 모두 거부한다(C2). 중첩은 없다. 사유의 문장 앞에 `commands[n] (type):`이 붙는다. **최종 상태만이 아니라 모든 중간 상태가 유효한 `Project`여야 한다**: 한 액추에이터의 두 구간을 맞바꾸는 묶음은 첫 명령에서 겹침으로 거부된다. 줄이거나 지우는 명령을 먼저 두거나 `replace_*`를 쓴다(에이전트 재시도 G-03a, 대칭 복제 B-11이 알아야 한다) | 역명령들의 역순 묶음 |

- 목록 순서는 값의 일부라서 `add_*`는 `index`(없으면 끝)를 받고, 역명령은 원래 자리로 되돌린다.
- 같은 값을 다시 정하는 명령(같은 행성, 같은 재료, 같은 자세)은 수락되고 같은 프로젝트를 돌려준다. 빈 이력 칸과 불필요한 판정 무효화(D5)를 거르는 일은 C-02b가 `결과.project == project`로 판단한다.
- 편집마다 프로젝트 전체를 JSON으로 덤프하고 다시 검증하므로 편집 하나는 프로젝트 크기에 비례하고 묶음은 n배다(리뷰 측정: 인스턴스 200개에서 단일 이동 약 11 ms, 200건 묶음 약 1.1 s; 1,000개에서 25 ms, 4 s). 명령의 모양과 무관한 내부 문제라서 별도 이슈로 추적한다.
- 역명령은 목록의 절대 위치(`index`)를 담는다. 한 줄로 선형인 이력(S1)에서는 역명령이 늘 자기가 계산된 상태에 적용되므로 정확하다. 다른 편집이 끼어드는 사용자별 되돌리기(N-04)는 위치가 아니라 이웃을 가리키는 방식이 필요하다.
- 삭제가 연쇄를 일으켜도 한 명령이고 한 역명령이다(#476 리뷰: 끊긴 상태를 만들지 않는다). 이력에서 한 칸이 되는 묶음 단위는 C-02b가 정한다.
- 이 PR에 없는 것: 발행자와 되돌리기·다시 실행·이력(C-02b), 배치 검사(겹침, 뜬 부품, 스냅 호환)와 행성 상수·물성 DB·판정 결과를 바꾸려는 시도의 거부, `planet`이 `data/bodies`에 있는지, 어느 출처가 정의 명령을 보낼 수 있는지(C-02c), 저장 형식과 정의 해시(C-03), 선로의 메시지(C-05a), 지형 소품 편집(W-05), 수역(FL-02b), 분리 항목(X-08), 정의가 없는 인스턴스(C-06). 이 PR의 예시 수치는 모두 테스트가 선언한 값이다.

## 알려진 확장 (이 PR 범위 밖, 뒤 잎이 더한다)

- 곡선(토크-속도, 추력 곡선): B-03b, B-03c.
- 단위 `kg/s`(추진제 소모율), `N*s`(충격량): 쓰는 잎이 `Unit`에 더한다.
- 형상 레시피와 파생값의 입력: B-01a에서 들어왔다. `PartDef.shape`, `MassProperties.derivation`. `docs/architecture/part-mass.md`.
- 충돌 프록시: B-01b에서 들어왔다. `CollisionProxy`(기본형 지오메트리, 메운 빈 곳, 부피 오차). `docs/architecture/collision-proxy.md`.
- 바인딩 안 된 가정(가정이 설계의 어느 값을 흔드는지)과 가정 단위의 의미 검사: J-01a, L-02.
- PBR 재질 슬롯: B-07(구현됨, [`materials.md`](materials.md)).
- `export_policy`: HW-02a.
- 모델은 불변이지만 `model_copy(update=...)`는 검증을 건너뛴다. 명령 적용기(C-02a)는 JSON 형태로 고친 뒤 `model_validate`로 통째로 다시 검증한다.
