# 몬테카를로 판정: p_success와 95% 신뢰구간 (J-01a)

- 상태: 구현됨. `packages/judge/src/kinetra_judge/mc.py`(`sample_assumptions`, `wilson_ci`, `monte_carlo`, `run_verdict`, `Verdict`, `compare_verdicts`, `goal_hash`, `assumptions_hash`), 엔진 쪽은 `PreviewRun(..., ground_friction=μ, assumption_values=표본)`(`packages/engine/src/kinetra_engine/run/preview.py`), 코어 바인딩은 `kinetra_core.assumption`과 `apply_assumption_values`다. 테스트 `packages/judge/tests/test_mc.py`(`uv run pytest packages/judge -q -k mc`).
- 근거: 이슈 #162와 #571, `docs/plan/studio-plan.md` 4.5절과 J-01 행, `docs/decisions/engine.md` 5.4절(H1~H6), 조건 평가기([`goal-eval.md`](goal-eval.md), J-02a), 판정 가정표의 합성([`bodies.md`](bodies.md) W-03c), 핵심 가치 V1. legacy 원본은 `legacy-v0:packages/engine/src/kinetra_engine/mc.py`.
- 범위 밖: 민감도 순위(J-03, legacy의 한 번에 하나씩 흔들기), 실패 원인 묶음 집계(J-06), 판정 카드 화면(J-04a), 에이전트 도구에 판정기 연결(J-01d), 가정표 편집 화면(J-04b), 기준 플랫폼(#478).

## 하는 일

`run_verdict(project, goal, n=, seed=, duration_s=, project_id=, revision=)`가 판정 하나를 낸다.

1. 판정 가정표를 만든다: `verdict_assumption_table(project.assumptions, load_body(planet))`(행성 행 다음 프로젝트 행, W-03c).
2. 행마다 표본 `n`개를 뽑는다(`sample_assumptions`). legacy와 같다: 행마다 자기 스트림 `np.random.default_rng(derive_seed(seed, "assumption", key))`를 쓰므로 행을 더하거나 빼도 다른 행의 표본이 바뀌지 않는다. `fixed`는 공칭, `uniform`은 `uniform(low, high, n)`, `normal`은 `normal(mean, std, n)`을 `clip_low`/`clip_high`로 자른다.
3. 표본 i마다 엔진을 한 번 돌린다: `PreviewRun` 종류 `verdict_sample`, 실행 id `verdict-{seed}-{i}`, 판정의 시드, 틱마다 프레임(조건을 틱 단위로 본다, goal-eval.md 2), 지면 마찰은 그 표본의 `ground_friction`이다. 바인딩된 프로젝트 행은 `apply_assumption_values`가 만든 표본별 컴파일 입력에 실제로 들어간다(`assumption_values=values`). 원 프로젝트와 그 정의 해시는 바꾸지 않으며, 결합이 풀려 다시 컴파일할 때도 표본이 적용된 바디 트리와 같은 지면 마찰을 유지한다. 바인딩되지 않은 행은 컴파일 입력을 바꾸지 않는다.
4. 스트림마다 `evaluate_goal`(J-02a)이 `met`, `failed`, `undetermined`를 낸다. p_success = `met / (met + failed)`, 95% 신뢰구간은 같은 분모의 Wilson 점수 구간(z = 1.959963984540054, p를 품도록 넓힌다. legacy `wilson_ci`).

`monte_carlo(table, goal, n=, seed=, duration_s=, applied=, run_sample=)`는 엔진과 무관한 같은 루프다. `run_sample(i, values)`가 실행 스트림 하나를 돌려준다. 표본마다 실제로 돈 길이(`last_tick × timestep_s`)를 확인한다: 요청한 `duration_s`가 끝나는 틱(`end_tick(duration_s, timestep_s)`)에서 끝나지 않은 실행(더 짧게 끝났거나 그 전에 멈췄거나 더 길게 돈 실행)이 하나라도 있으면 판정을 만들지 않는다(`ValueError`). 엔진이 계속할 수 없었던 실행(`failed`)만 더 일찍 끝날 수 있고, 그 표본은 세되 정해지지 않은 조건 때문에 `undetermined`가 된다. 그래서 기록한 `duration_s`는 모든 표본이 실제로 돈 길이다.

## 기록 (`Verdict`)

| 필드 | 뜻 |
|---|---|
| `p_success`, `ci_low`, `ci_high`, `ci_method` `wilson_95` | 판단된 표본(`n_met + n_failed`)의 비율과 구간. 판단된 표본이 없으면 셋 다 `null` |
| `n_samples`, `n_met`, `n_failed`, `n_undetermined` | 표본 수와 결과별 개수. 합이 `n_samples`가 아니면 거부 |
| 요청(`REQUEST_FIELDS`): `definition_hash`(프로젝트), `goal_hash`(조건 집합의 정규 JSON SHA-256), `assumptions_hash`(판정 가정표: 행성과 행 전체의 정규 JSON SHA-256), `duration_s`, `timestep_s`, `n_samples`, `seed` | 일곱 값이 모두 같을 때만 두 판정이 서로의 재현이다. `planet`도 기록한다(가정표 해시에 든다) |
| `platform` | 표본 실행의 플랫폼 태그(H1). 필수이고, 표본 사이에 태그가 다르면 판정을 만들지 않는다(`ValueError`) |
| `sampled`, `sampled_values`, `not_applied` | 분포가 있는 행 중에서 모델에 표본이 들어간 행과 들어가지 않은 행. `sampled_values`는 `sampled` 각 행의 실제 표본 `n_samples`개를 실행 순서대로, 행의 단위로 기록한다 |
| `model_labels`, `labels` | 실행들의 모델 라벨(처음 나온 순서)과 판정의 라벨 |
| `badge` `sim` | 모든 수치는 시뮬 표본에서 셌다 |

`Verdict`는 숫자가 서로 맞지 않으면(예: p_success가 `n_met / (n_met + n_failed)`가 아님, 구간이 그 Wilson 구간이 아님) 만들어지지 않는다. `sampled_values`도 `sampled`와 정확히 같은 행을 갖고 각 행이 `n_samples`개의 값을 가져야 한다.

## 정직하게 말하는 것

1. **판정은 표본 실행에서만 나온다(V1).** 종류가 `verdict_sample`이 아닌 실행(미리보기)은 세지 않고 거부한다. 판정 라벨: "몬테카를로 판정: 가정표의 분포에서 뽑은 표본마다 시뮬을 한 번씩 돌려 성공 조건을 평가했다".
2. **흔들지 않은 가정을 숨기지 않는다.** 바인딩 존재만으로 적용했다고 말하지 않는다. 표본별 컴파일의 질량·형상 파생 입력, 접촉 마찰, 결합 기하, 스프링과 실제 구동 스케줄의 추력·전원 입력을 확인한다. 사용하지 않는 부품·재료·설명용 사양, 다른 사양에 가려진 재료 마찰, 실행 구간에 켜지지 않는 추력기의 추력 사양은 `not_applied`다. 모델이 실제 읽는 행만 `sampled`와 `sampled_values`에 넣는다. 미바인딩 행도 계속 `not_applied`와 "미적용" 라벨로 밝힌다.
3. **판단 불가는 분모에서 뺀다.** 실행이 멈췄거나 엔진이 계속할 수 없어 조건이 정해지지 않은 표본은 `n_undetermined`로 세고 p와 구간에서 뺀 뒤 "판단 불가 k개 표본은 p_success와 신뢰구간의 분모에서 뺐다" 라벨을 단다. 판단 불가가 실패와 상관되면 p는 치우친다. 그래서 개수를 함께 싣는다.
4. **구간은 표본 수의 불확실성만 담는다.** 라벨: "95% 신뢰구간은 Wilson 점수 구간이다. 표본 수에서 오는 불확실성만 담고 모델의 근사에서 오는 오차는 담지 않는다".

## 플랫폼 태그와 재현 (engine.md 5.4, A0-05)

- **H1.** 판정은 표본 실행의 플랫폼 태그와 함께 기록된다. 태그가 없는 기록은 `Verdict`가 아니다.
- **H2, H5.** `compare_verdicts(a, b)`는 `VerdictComparisonResult(status, differs)`를 낸다. 요청 필드가 하나라도 다르거나 태그가 다르면 p_success를 보지 않고 `not_comparable`이고, `differs`에 다른 요청 필드(그 순서대로)와 태그가 다르면 `platform`을 싣는다. 모두 같으면 기록 전체가 같을 때 `match`(`differs` 빔), 아니면 `mismatch`(다른 기록 필드). 라벨: "이 p_success는 함께 기록한 플랫폼 태그에서 낸 값이다. 태그가 다른 실행의 p_success와 같은 값이라고 보지 않는다".
- **H6, 시드 고정 재현.** 테스트는 한 프로세스(같은 태그) 안에서 같은 요청을 두 번 돌려 기록 전체가 비트 단위로 같음(`match`)을 단언한다. "태그가 같으면 결과가 같다"는 가정은 #432가 검증한다.
- **커밋한 기준값 없음.** 기준 플랫폼(Linux x86-64 고정 이미지, H3)은 아직 없다(#478 열림). 그래서 저장소에 p_success 기록값을 커밋하지 않았고, 태그가 다른 실행을 허용 한계로 비교하는 테스트도 없다. 기준값과 그 비교는 기준 플랫폼이 선 뒤에 그 플랫폼에서 내서 태그와 함께 커밋한다(J-05).

## 손계산 대조 (테스트)

마찰 1.0(모든 행성 지면보다 크다)인 0.1 × 0.1 × 0.02 m 판을 재료 없는 30° 경사로(길이 3 m) 가운데에 놓는다. 쌍의 마찰은 경사로 표면, 곧 지구 지면 마찰 U(0.3443, 0.7813)의 표본이다(`terrain-props.md`). 판은 μ < tan 30° = 0.5774이면 미끄러지고 크면 버틴다(W-05가 미끄러지는 각을 atan(μ)의 1.6e-3 안에서 쟀다). 성공 조건은 "1 s 안에 판의 기준점이 x로 0.02 m 내려간다".

| 항목 | 값 |
|---|---|
| 시드, 표본 수 | 17, 12 |
| 뽑힌 μ와 tan 30°의 최소 거리 | 0.03 이상(테스트가 먼저 단언한다) |
| 미끄러짐 | Δμ ≥ 0.03이면 가속도 ≥ g cos 30° × 0.03 = 0.25 m/s², 0.2 s 안정 뒤에도 1 s까지 경사면으로 약 0.08 m |
| 버팀 | 소프트 접촉의 기어감 ≤ 1.8e-3 m/s(W-05), 1 s에 2 mm 미만 |
| 기대 | `n_met` = tan 30°보다 작은 μ의 개수, p_success = 그 개수 / 12, 구간 = `wilson_ci(그 개수, 12)` |

Wilson 구간은 닫힌 식으로 대조한다: k = 0, n = 10의 위 끝 z²/(n + z²) = 0.27753, k = 5, n = 10의 구간 [0.236594, 0.763406].

바인딩 양 끝 대조(#571): 같은 30° 경사로에 재료 마찰 1.0인 판을 놓고, 경사로 재료의 마찰에 `material_property` 바인딩을 둔다. 접촉 쌍의 마찰은 `min(1.0, 표본)`이다. 분포의 아래 끝 0.1에서는 $a=g(\sin30°-0.1\cos30°)=4.06\,\mathrm{m/s^2}$라 1 s 안에 0.02 m보다 훨씬 멀리 미끄러지고, 위 끝 1.0은 $\tan30°$보다 커서 버틴다. 테스트는 표본화 함수에서 이 행만 선언한 분포의 두 끝으로 고정하고(다른 행의 독립 시드 스트림은 그대로), 실제 `run_verdict` 컴파일·엔진·조건 평가로 성공 1개·실패 1개와 `sampled_values=(0.1,1.0)`을 단언한다. 수치는 실제 재료 인용이 아니라 테스트가 선언한 값과 추정 분포다.
