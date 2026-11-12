# 부품 정의가 빠진 프로젝트 열기 (C-06)

- 상태: 구현됨. 코드는 `packages/core/src/kinetra_core/missing.py`(찾기와 카탈로그 비교), `designspec.py`(참조 검사 완화), `commands.py`(`relink_instance`, `unlink`), `validator.py`(`require_complete`, 새 자리표시 거부), `packages/engine/src/kinetra_engine/parts/library.py`(부품 라이브러리의 해시). 테스트는 `packages/core/tests/test_missing_definition.py`와 `packages/engine/tests/test_library_catalog.py`(`uv run pytest packages/core -q -k missing_definition`).
- 근거: `docs/plan/studio-plan.md` 5.3절 "정의가 빠진 인스턴스는 '정의 없음'으로 남기고(질량·형상을 지어내지 않는다) 실행·판정·내보내기를 사유와 함께 막는다", `docs/research/benchmarks/kerbal-space-program.md` E3~E5(모드를 지우면 크래프트가 안 열린다: 우리는 피한다), 창업자 결정 2026-11-11(#422).
- 값 `V5 깨끗한 출처`와 `V1 정직한 판정`: 빠진 부품을 숨긴 채 판정까지 가지 않고, 없는 부품의 수치를 지어내지 않는다.
- 범위 밖: 외부 플러그인·모드 폴더, 정의의 자동 내려받기, 다른 제품의 파일 형식. 화면(자리표시, 버튼 잠금, 재연결 목록)은 C-07.

## 규칙

1. **프로젝트는 쓰는 정의를 담는다.** `DesignSpec.materials`와 `.parts`가 그것이고 파일은 정의마다 정의 해시를 싣는다(`ProjectFile.definitions`, C-03). 정의는 출처 필드를 가진 채로 담긴다(C-01a).
2. **카탈로그와 다르면 프로젝트의 정의를 쓴다.** 열 때 카탈로그(재료 카탈로그 B-07, 부품 라이브러리 B-02)의 같은 ID와 `definition_hash`가 다르면 프로젝트에 담긴 정의가 그대로 쓰이고, `open_report(project, catalog)`가 `CatalogDifference`(종류, ID, 프로젝트의 해시, 카탈로그의 해시)를 돌려준다. 문구는 "카탈로그와 다름"이다. 카탈로그의 정의로 바꿔 끼우지 않는다. 카탈로그에 없는 ID는 사용자의 것이라 차이가 아니다. 카탈로그는 `{(kind, id): hash}` 사상이다: 재료는 `material_catalog_hashes()`, 부품은 `kinetra_engine.parts.library_hashes()`. (파일의 `definitions[]` 해시는 열 때마다 다시 계산해 대조하므로 `hash_mismatch` 규칙은 그대로다.)
3. **정의가 없는 인스턴스는 자리표시로 열린다.** 인스턴스의 `part`가 프로젝트의 부품 정의에 없거나 `material`이 프로젝트의 재료에 없으면 그 프로젝트는 거부되지 않고 열린다. 그 인스턴스가 자리표시다. 자리표시는 새 레코드가 아니다: 저장된 인스턴스 그대로(ID, 부품 ID, 파라미터 값, 자세, 재료 ID)이고 그 결합, 액추에이터, 스케줄 항목도 그대로 있다. **부품이 빠진** 자리표시는 질량, 관성, 형상, 충돌 도형이 없고 만들지도 않는다. 배치 검사(`validator.py`)는 형상 없는 부품처럼 건너뛴다(`overlap`, `floating`, 그 결합의 스냅 검사 없음. 통과가 아니라 모르는 것이다). **재료만 빠진** 자리표시는 부품이 있으므로 형상과 스냅 포인트가 있고, 배치 검사는 다른 인스턴스처럼 돈다(배치 검사는 형상만 읽고 재료를 읽지 않는다). 정의되지 않는 것은 질량뿐이고(밀도가 없다) 실행은 똑같이 거부된다. 정의가 없어서 확인할 수 없는 것(파라미터 이름·단위·범위, 결합한 스냅 포인트의 존재, 액추에이터 역할)은 정의가 연결될 때 프로젝트 전체 검증에서 확인된다.
4. **닫혀 있는 참조는 그대로다.** 결합 → 인스턴스, 액추에이터 → 인스턴스·결합, 스케줄 → 액추에이터, 지형 소품 → 재료, 한 스냅 포인트는 결합 하나에만. 이것들이 끊기면 정의 문제가 아니라 파일이 깨진 것이라 `invalid_project`로 거부한다.
5. **자리표시가 있으면 컴파일·실행·판정·Halo 내보내기는 거부된다.** `require_complete(project, 작업)`(`BlockedOperation`: `compile` `run` `verdict` `export_halo`)가 `ProjectIncomplete`를 던진다. `missing`은 빠진 정의의 ID 목록(`MissingDefinition`: 종류, ID, 그것을 쓰는 인스턴스)이고 `reasons`는 같은 내용의 `Reason`(`missing_definition`, 참조는 정의, 그다음 인스턴스들)이다. 조용히 빼고 돌리지 않는다. 컴파일과 실행은 X-02a(`kinetra_engine.run`)가 부르고, 판정과 내보내기는 아직 없다(J-*, H-*). 각 잎은 시작할 때 `require_complete`를 부르는 것이 DoD다. 기록된 궤적의 재생은 막지 않는다(C-07): 막는 것은 다시 실행뿐이다.
6. **고치는 길은 모두 Command다.**
   - 다시 연결: `add_part_def` / `add_material_def`로 빠진 ID의 정의를 더하면 그 ID의 자리표시가 모두 정상 인스턴스가 된다. 다른 부품으로 옮기려면 `relink_instance`(`id`, `part`): 인스턴스 하나의 `part`만 바꾼다. 결과는 프로젝트 전체 검증을 거치므로 새 부품에 파라미터나 결합의 스냅 포인트가 맞지 않으면 `invalid_project`로 거부되고 문제의 참조가 사유에 있다. 재료는 `set_instance_material`.
   - 지우기: `remove_instance`는 자리표시도 지운다(결합, 액추에이터, 스케줄 항목과 함께, C-02a).
   - 되돌리기: 위 모두 역명령이 있고, 지운 자리표시와 그 결합은 되돌리면 자리표시로 돌아온다.
7. **명령은 새 자리표시를 만들지 못한다.** `validate_command`는 결과에 `missing_users`가 이전보다 늘었으면 `missing_definition`으로 거부한다(없는 부품의 인스턴스 추가, 쓰이는 정의를 `unlink: true`로 제거 등). 이미 빠진 것은 그대로 두고 다른 곳을 편집할 수 있다(배치 검사의 "새 문제만 거부한다"와 같은 규칙). 되돌리기·다시 실행은 받아들여졌던 상태로 가므로 이 문을 지나지 않는다(`History.undo/redo`는 `apply_command`). 그래서 정의를 더한 명령의 역명령은 `unlink`가 켜진 `remove_part_def` / `remove_material_def`이다: 쓰는 인스턴스가 있어도 정의만 뺀다. `unlink`는 보내는 쪽이 쓸 수 없다. 이 필드를 더한 것은 선택 필드를 더하는 변경이라 파일 `version`을 올리지 않는다(명령은 파일에 저장되지 않는다).
8. **저장 → 열기 왕복에서 자리표시는 보존된다.** 자리표시는 인스턴스이므로 파일 형식도 해시 규칙도 바뀌지 않는다(`version` 1). `definitions[]`에는 프로젝트가 담은 정의만 오고 빠진 정의의 해시는 없다. 다시 저장하면 바이트까지 같다.

## 이 PR이 정하고 문서에 남기는 것

- C-03 리뷰가 C-06에 넘긴 질문: "`Project` 검증과 `_differences`의 '프로젝트가 담지 않은 정의의 해시' 규칙을 바꿔야 한다". 둘 다 바뀌지 않았다. 자리표시는 새 필드가 없고(`extra="forbid"`는 그대로, 무시되는 필드가 없다), `_differences`는 프로젝트가 담은 정의에 대해서만 해시를 요구하므로 빠진 정의를 담은 파일은 `hash_mismatch` 없이 열린다.
- 재료가 빠진 인스턴스도 자리표시다(재료의 질량은 형상과 밀도에서 오므로 없는 재료로는 질량을 못 낸다). 지형 소품의 재료가 빠진 프로젝트는 지금처럼 열리지 않는다: 소품은 인스턴스가 아니고, 소품을 놓는 명령(`add_terrain_prop`, `replace_terrain_prop`, W-05)도 프로젝트에 없는 재료를 가리키면 `Project` 검증에서 거부된다.
- 정의 해시는 이름, 라벨, 출처 문구를 포함한다(C-03). 그래서 이름만 고쳐도 "카탈로그와 다름"이 뜬다. 물리 부분만의 해시는 B-16이 더한다.

## 한계

- 판정과 내보내기는 아직 없어서 그 거부는 `require_complete`와 그 시험(네 작업 모두)으로만 확인된다. 컴파일러(`build_body_tree`, X-01d)는 처음에 `require_complete(project, "compile")`를 부르고 `test_compile_error_a_missing_definition_is_refused_before_compiling`이 이를 본다. 실행은 X-02a의 `kinetra_engine.run`(`compile_project`가 `compile`, `PreviewRun`이 `run`)이 부르고 `test_simulate_stream_compile_and_run_call_require_complete`와 코어 프로토콜의 거부 시험이 본다. 나머지 소비자가 부르는지는 그 잎의 시험이 본다.
- 정의를 "다시 연결"할 원본(카탈로그, 다른 프로젝트의 정의 가져오기)을 찾아 주는 것은 없다(자동 내려받기는 범위 밖). `add_part_def`에 정의를 실어 보내는 것은 클라이언트의 몫이다.
- 배치 검사(`overlap`, `floating`)는 **부품이 빠진** 자리표시를 모르는 것으로 건너뛴다(재료만 빠진 것은 건너뛰지 않는다). 그래서 자리표시가 가려서 `floating`이 나오지 않는 조립이 있을 수 있다. 어차피 실행이 막혀 있고, 정의가 연결되면 검사가 다시 돈다.
