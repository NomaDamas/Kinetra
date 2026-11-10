# 브라우저 WASM 실행과 네이티브 대비 차이 (A0-01b, 이슈 #44)

측정만 한다. 최적화하지 않았다. `spikes/mujoco-limits/REPORT.md`와 같은 규칙(시드 고정, 부하 기록, 값마다 명령과 머신)을 따른다. 이 보고서의 요약은 `spikes/mujoco-limits/REPORT.md`의 A0-01b 절에도 있다.

## 결론 먼저

- **쓸 수 있는 WASM 바인딩이 지금 있다.** 공식 `@mujoco/mujoco` 4.0.0(Google DeepMind, Apache-2.0, 2026-11-06 게시)이다. 같은 4.0.0 엔진이 들어 있어(`mj_versionString()` → `"4.0.0"`) 네이티브 `mujoco==4.0.0` 휠과 버전이 같다. README는 "아직 WIP", 개발은 주로 Linux + Chrome이라고 적었다.
- **기존 로켓 자동차 모델이 헤드리스 Chromium(Playwright 자체 빌드 158.0.8127.18)에서 그대로 돌았다.** 같은 시간 간격(4 ms), 같은 제어, 같은 시작 상태로 4.5 s(1,125스텝)를 21개 시나리오에서 네이티브와 비교했다.
- **궤적은 비트 단위로 같지 않다.** 21개 시나리오 어디서도 시작 행(0번 행) 말고는 비트 일치가 없다. 그러나 차이는 매우 작다. 전체 궤적 중 **최대 위치 오차 6.14e-6 m, 최대 자세 오차 4.09e-6 rad**(둘 다 레거시 영웅 시나리오 `nominal`, 스텝 1084). 시나리오별 최댓값의 중앙값은 위치 3.08e-11 m, 자세 3.39e-11 rad다. 접촉이 생기기 전 구간(첫 접촉 스텝 이전)의 최대 오차는 21개 전체에서 위치 9.7e-14 m, 자세 1.4e-13 rad였다.
- 오차는 **착지 접촉 뒤에 자란다.** 같은 네이티브끼리 시작 높이만 1e-9 m 흔들어도 최대 위치 오차가 1.0e-2 m, 자세 7.7e-3 rad까지 간다. 그러므로 6e-6 m 차이는 "엔진이 다르다"의 증거가 아니라 "접촉이 있는 이 궤적은 아주 작은 차이를 키운다"와 함께 읽어야 한다(아래 5절).
- **프레임률.** `requestAnimationFrame` 루프(4 ms 스텝 × 프레임당 4~5회 + 캔버스 2D 그리기)에서 **평균 60.00 fps, 프레임 간격 p99 16.8 ms, 20 ms 넘은 프레임 0개**(3회 실행 모두). 프레임당 일(스텝+그리기) 중앙값 0.1 ms, p99 0.3~0.4 ms. 따라잡기 상한에 걸려 시뮬 시간을 버린 프레임은 0개, 버린 시뮬 시간 0 s. 60 fps는 vsync 상한이라 한계가 아니다. 상한 없이 돌린 값은 프레임(스텝 4회 + 그리기)당 약 3.3만~3.5만/s다. 이 머신에서 `mj_step` 순수 처리량은 중앙값 약 17만~18만 스텝/s(실시간 대비 약 700배)이고 같은 모델의 네이티브 Python 루프는 약 20만 스텝/s(약 800배)였다.
- 모든 값은 **[추정: 부하 아래 측정, 한가한 머신 재측정은 확인 필요]** 이다(부하 평균 113~137, 스왑 약 96%. 첫 기록 실행은 139~217이었고 아래에 같이 적었다). 정확도 수치(오차)는 부하와 무관하다. 속도 수치는 부하의 영향을 받는다.
- 이 측정이 보이지 않는 것: 로켓 자동차 1대(자유도 10)만 쟀다. 다물체 규모, 접촉이 많은 장면, WASM 쪽 `MjSpec` 재컴파일, 멀티스레드 빌드, 실제 GPU 렌더링은 재지 않았다. Chromium 외 브라우저(Firefox, Safari)와 다른 OS도 재지 않았다.
- V1: 이 값은 "미리보기 실행이 네이티브와 얼마나 다른가"의 측정이다. 판정이 아니다. 플랜은 이미 브라우저 WASM을 미리보기로만 쓰고 공유 링크는 기록된 궤적을 재생한다고 정했다(`docs/plan/studio-plan.md` 5절 표, 결정론 행).

## 1. 바인딩 조사

| 후보 | 출처 | 버전(조사일 2026-11-10) | 라이선스 | 상태 | 이번에 측정했나 |
|---|---|---|---|---|---|
| **`@mujoco/mujoco`** | 공식. `google-deepmind/mujoco`의 `wasm/` ([npm](https://www.npmjs.com/package/@mujoco/mujoco), [소스](https://github.com/google-deepmind/mujoco/tree/main/wasm)) | **4.0.0** (npm `latest`, 저장소 릴리스 4.0.0 = 2026-11-06T15:39:53Z, npm modified 2026-11-06) | **Apache-2.0** (`package.json`, 저장소 LICENSE) | 공식. README "These bindings are still a WIP." 단일 스레드 빌드와 `/mt` 멀티스레드 빌드(COOP/COEP 필요)를 같이 싣는다. 타입 정의 포함 | **예** (단일 스레드 빌드) |
| `mujoco-js` | 같은 저장소의 `wasm/package`로 표시, 다른 npm 이름 ([npm](https://www.npmjs.com/package/mujoco-js)) | 0.0.7 (2026-03-05 수정, 2025-10-22 생성) | Apache-2.0 | `@mujoco/mujoco`보다 이전·별도 게시. 이 이름의 게시자는 `manevicreativa`(Google 계정 아님) | 아니오. 메타데이터만 봤다 |
| `zalo/mujoco_wasm` | 커뮤니티 ([GitHub](https://github.com/zalo/mujoco_wasm)) | 패키지 3.12.0, 마지막 푸시 2026-08-23 (MuJoCo 3.12 업그레이드) | MIT | 별 498, 보관 안 됨. 렌더 데모 중심 | 아니오. 메타데이터만 봤다 |
| npm `mujoco_wasm` | — | — | — | 2026-02-24에 게시 취소됨(registry 404 "Unpublished") | — |

선택 근거: 공식이고 Apache-2.0이며 네이티브와 같은 4.0.0 엔진이라 네이티브 대비 차이를 "엔진 버전 차이"와 섞지 않는다. 커뮤니티 두 후보는 측정하지 않았다. 바인딩 선택은 이 측정이 한 것이 아니라 조사 결과다.

**패키지 내용**(`npm pack @mujoco/mujoco@4.0.0`, tgz sha256 `66b97038b28d323dee676cf6c696074ef57e5e6f62521a5f48045ebaebdd27a0`): `mujoco.wasm` 11,200,612 B(gzip 2,787,204 B), `mujoco.js` 294,200 B(gzip 68,695 B), `mt/mujoco.wasm` 11,298,295 B(미측정). gzip은 `gzip -c`의 기본 레벨 값이다.

## 2. 모델과 제어의 출처 (V5)

`legacy-v0` 태그(`6065cca852a8b25af0ddc7ddb147e207d4383237`, 2026-11-10)에는 MJCF 파일이 따로 없다. 로켓 자동차 MJCF는 `packages/engine/src/kinetra_engine/templates/rocket_car.py`의 `build_mjcf()`가 문자열로 만든다(파일 sha256 `27dc2a7008b50695dfdebaf527df682ae7f05826e1a349d25b8778494614ca18`, `git show legacy-v0:…`로 읽은 바이트).

- `spikes/mujoco-wasm/model/rocket_car.xml` = 그 파일 41~143줄(상수, 추진기 배치, `build_mjcf`)을 `exec`해서 얻은 문자열. 수정 없음. sha256 `83b4990f9e0cb742f41299886410132641f42f42ef8e1d13ea9bb49909932cd9`. 이것은 `legacy-v0:apps/web/public/demo/roadster/traj_8000.json`의 `model_hash`와 **같다**(`gen_reference.py`가 시작할 때 이 값과 대조하고 다르면 종료한다).
- 모델: 차체 1,220 kg + 바퀴 4개(각 20 kg, 힌지), 노즐 18개(`motor`, `gear="0 0 1 0 0 0"`, ctrlrange 0~1), `integrator=implicitfast`, `timestep=0.004`, 중력 9.80665. 두 쪽 모두 컴파일 뒤에 `actuator_gear[:, 2] = 8000`(노즐당 8,000 N)을 쓰고 `mj_setConst`를 부른다(레거시 `Rig.model`과 같은 방식).
- 제어: `traj_8000.json`의 `meta.params`(영웅 8,000 N 시나리오의 창 7개). 창→노즐 풀이(WIN_GROUP, GROUP_OF, `controls()`)를 `gen_reference.py`가 복사했다. 창 규칙은 `t >= ts and t < ts+dur`다.
- 시작 상태: 램프 끝(속도 22 m/s, 각 25°, 높이 2.2 m, 바퀴 `v/0.32` rad/s). 레거시 `Rig.x0`와 같다.
- 확인: `uv run spikes/mujoco-wasm/check_legacy_bundle.py`는 이 재현이 레거시 번들(`traj_8000.json`, 5스텝마다 차체 자세, 소수 4~5자리 반올림)과 같은 실행임을 보인다. 번들의 자세는 `mj_step` 직전에 읽은 것이라 한 스텝 앞 행과 비교하면 **최대 위치 차 4.996e-5 m, 쿼터니언 차 4.993e-6**이고 이것은 반올림 단위(5e-5, 5e-6)와 같다. 같은 비교를 한 스텝 어긋나게 하면 0.08 m 차이가 난다. 즉 위의 한 스텝 어긋남 해석이 맞다. (번들의 `meta.note`는 `success=True`라고 적었다. 이 PR은 판정을 다시 내리지 않았다. 판정은 이 측정의 일이 아니다.)
- 변형 20개(`var1`~`var20`): 같은 창에서 시작 시각 ±20 ms, 스로틀 ×0.95~1.05를 `numpy.random.default_rng(0)`으로 뽑았다. **이것은 내가 만든 변형이지 레거시 결과가 아니다.** 접촉이 다른 모양이 되도록 더했다(첫 접촉 스텝 468~556, 접촉 스텝 수 40~335).
- 네이티브 전용 대조 2개: `nominal`에서 시작 높이만 +1e-12 m, +1e-9 m 흔든 네이티브 실행(WASM 쪽 아님). 네이티브가 작은 흔들림에 얼마나 민감한가를 가리는 척도다.

## 3. 방법

| 항목 | 값 |
|---|---|
| 네이티브 기준 | `uv run spikes/mujoco-wasm/gen_reference.py` (PEP 723 고정: `mujoco==4.0.0`, `numpy==2.5.4`, 이 머신 Python 3.12.11). 시나리오 23개를 각각 **두 번** 돌려 비트 단위로 같음을 확인한 뒤(`native_repeat_bitwise_equal`) `reference/native_qpos.f64`(리틀엔디언 float64, 시나리오당 1,126행 × 11) 와 `reference/manifest.json`에 저장 |
| WASM | `@mujoco/mujoco@4.0.0` 단일 스레드 빌드, 헤드리스 Chromium(`playwright@1.65.0`의 `chromium-headless-shell` 158.0.8127.18), 일회용 사용자 폴더(Playwright가 만들고 닫을 때 지움). 창업자의 Chrome은 쓰지 않았다 |
| 같은 입력 | 제어 배열을 JS에서 같은 규칙으로 다시 만들고 float64 바이트의 sha256을 네이티브 것과 비교: **21개 시나리오 모두 일치**(`ctrl_equal`). 시작 `qpos0`/`qvel0`은 manifest의 double 그대로(JSON 왕복에서 값이 같다) |
| 스텝 | 시간 간격 0.004, 1,125스텝. `d.ctrl`을 스텝마다 쓰고 `mj_step` 1회. 기록: 0스텝 전과 매 스텝 뒤 `qpos`(1,126행) |
| 시드 | 0 (변형 뽑기). 물리는 시드가 없는 결정론적 실행 |
| 위치 오차 | 행마다 `‖qpos[0:3]_wasm − qpos[0:3]_native‖₂` (m), 1,126행 중 최댓값 |
| 자세 오차 | 행마다 루트 쿼터니언의 측지 각 `2·atan2(‖vec(a*·b)‖, |w(a*·b)|)` (rad, q와 −q는 같은 회전). 1,126행 중 최댓값. `src/compare.js`, 단위 테스트 있음 |
| 바퀴 각 오차 | 별도 열: 바퀴 4개 각도 차 `|Δθ|`의 최댓값(rad) |
| 접촉 전/후 | 네이티브 기준의 첫 접촉 스텝(`ncon>0`)을 경계로 나눠 각각의 최댓값을 기록. WASM의 첫 접촉 스텝도 기록해 같음을 확인 |
| 처리량(`bare`) | `ctrl` 쓰기 + `mj_step`만, 기록 없음, `performance.now`, 새 모델·데이터로 7회 반복 중앙값 |
| 프레임 루프(`frames`) | `requestAnimationFrame`으로 실시간을 누적해 4 ms가 쌓일 때마다 `mj_step` 1회(프레임당 최대 25회로 따라잡기 제한. 제한에 걸린 프레임 수와 버린 시뮬 시간을 `src/accumulator.js`의 `planFrame`이 계산해 기록), 프레임마다 캔버스 2D로 차체 상자 옆모습을 그림. 시나리오를 3번 이어 재생(약 13.5 s). 프레임 간격과 프레임당 일(스텝+그리기)을 기록 |
| 상한 없는 루프(`uncapped`) | 같은 일(스텝 4회 + 그리기)을 vsync를 기다리지 않고 연달아 3 시나리오분 |
| 반복 | 브라우저 쪽 측정 전체를 별도 프로세스로 **3번**(`wasm-chromium-run1~3.json`). 입력 무결성 검사(아래)와 따라잡기 계수를 넣고, 마지막으로 기준 궤적 해시 검사를 넣은 뒤 같은 명령으로 3번 다시 돌린 값이 기록된 값이다 |
| 입력 무결성 | 측정 전에 페이지가 받은 모델 파일의 sha256이 `manifest.model_sha256`과 레거시 `model_hash`(`manifest.legacy_model_hash`) 둘 다와 같은지, 시나리오마다 JS가 다시 만든 제어 배열의 sha256이 네이티브의 `ctrl_sha256`과 같은지, 비교에 쓰려고 받은 네이티브 기준 궤적(`native_qpos.f64`)의 시나리오별 sha256이 manifest의 `qpos_sha256`과 같은지 확인한다. 비교 수학은 어느 쪽 궤적에든 NaN/Infinity가 있으면 작은 오차로 세지 않고 오류를 던진다. 하나라도 다르면 예외를 던지고 페이지는 `window.__A0_01B_ERROR`만 남기며 `measure.mjs`는 결과 파일을 쓰지 않고 종료 코드 1이다. 결과 JSON의 `integrity`에 통과 기록(`model_hash_ok`, `reference_hash_ok_scenarios`=23, `control_hash_ok_scenarios`=21) |
| 가드 | 매번 `resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm measure`. `measure.mjs`는 가드 밖에서 시작하면 종료 코드 2로 거절한다 |

재현:

```
# 네이티브 기준 다시 만들기(결과 파일이 같아야 한다: manifest의 qpos_sha256)
uv run spikes/mujoco-wasm/gen_reference.py --bench
# 설치(저장소 루트의 워크스페이스와 따로 선다: spikes/mujoco-wasm/pnpm-workspace.yaml)
pnpm --dir spikes/mujoco-wasm install --frozen-lockfile
pnpm --dir spikes/mujoco-wasm exec playwright install chromium-headless-shell
# 측정 페이지 띄우기(이슈의 검증 명령). http://127.0.0.1:5174/ 에서 자동 실행, ?manual=1 이면 버튼
pnpm --dir spikes/mujoco-wasm dev
# 헤드리스로 측정해 results/*.json 쓰기(무거운 실행: 가드 아래에서)
RESULT_NAME=wasm-chromium-run1.json uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm measure
# 하니스 점검(오프라인)
pnpm --dir spikes/mujoco-wasm test                 # 21건: 비교 수학(비유한 값 거부 포함), 서버, 무결성 해시(모델·제어·기준 궤적), 따라잡기 계수
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/mujoco-wasm test:browser   # 4건: 변조한 모델·제어는 오류, 결과 없음
uv run spikes/mujoco-wasm/tests/test_gen_reference.py
uv run spikes/mujoco-wasm/check_legacy_bundle.py
```

## 4. 머신과 소프트웨어

| 항목 | 값 | 출처 |
|---|---|---|
| CPU / 코어 | Apple M2 Pro, 논리 10 | `sysctl machdep.cpu.brand_string`, `os.cpus()` |
| OS | macOS 15.6.1 (Darwin 24.6.0 arm64) | `platform`, `os.release()` |
| 네이티브 | Python 3.12.11, NumPy 2.5.4, mujoco 4.0.0 (PyPI 휠) | `manifest.json` |
| WASM | `@mujoco/mujoco` 4.0.0 (`mj_versionString()` = "4.0.0") | `results/wasm-chromium-run*.json` |
| 브라우저 | Chromium Headless Shell 158.0.8127.18 (Playwright 1.65.0), Node v22.22.2 | 같은 JSON |
| 브라우저 상태 | `crossOriginIsolated=false`(단일 스레드 빌드), `devicePixelRatio=1`, 헤드리스(소프트웨어 렌더) | 같은 JSON |

**부하(이 값들이 [추정]인 이유).** 이 머신은 다른 에이전트의 작업으로 늘 바쁘다.

| 실행 | load average 1분 (전 → 후) | 스왑 사용 |
|---|---|---|
| 네이티브 기준 `--bench` | 51.1 (측정 직전 `os.getloadavg()`) | 약 23.0/24.0 GiB |
| 브라우저 run1 (마지막 재실행, 기록된 값) | 137 → 134 | 약 17.4/18.0 GiB |
| 브라우저 run2 | 129 → 126 | 약 17.3/18.0 GiB |
| 브라우저 run3 | 124 → 113 | 약 17.2/18.0 GiB |
| (이전에 기록한 실행들: 첫 커밋 139~217, 두 번째 커밋 133~138) | | |

10코어에 부하 113~217이므로 **속도 수치는 한가한 머신보다 낮게 나왔을 가능성이 크다**(얼마나인지는 재지 못했다). 정확도 수치는 부하와 무관하다(같은 스텝 수의 부동소수 결과이기 때문이다). Chromium의 `performance.now()`는 `crossOriginIsolated`가 아니면 해상도가 거칠다(결과값이 6.2, 6.3, 6.4… ms처럼 0.1 ms 단위로 나왔다). 그래서 스텝 하나의 시간은 재지 않았고 1,125스텝 묶음의 시간만 쟀다.

## 5. 결과

### 5.1 궤적 차이 (WASM − 네이티브), 3번 브라우저 실행 모두 같은 값

위치/자세/바퀴 각은 3번 실행에서 모든 시나리오가 소수 끝자리까지 같았고, 각 시나리오의 WASM `qpos` 전체의 sha256도 21개 모두 3번 사이에서 같았다(`wasm_qpos_sha256`). 같은 페이지 안에서 같은 시나리오를 두 번 돌린 WASM 결과도 21개 모두 비트 일치다(`wasm_repeat_bitwise_equal`). 즉 **이 Chromium·이 머신에서 WASM은 자기 자신과 결정론적이다.**

| 항목 | `nominal`(영웅 8,000 N) | 21개 시나리오 전체에서 |
|---|---|---|
| 최대 위치 오차 | **6.144e-6 m** (스텝 1084) | 최댓값 6.144e-6 m(`nominal`). 다음 6.673e-8(`var3`), 6.063e-8(`var16`). 시나리오별 최댓값의 중앙값 3.08e-11 m, 최솟값 1.2e-13 m(`var18`) |
| 최대 자세 오차 | **4.093e-6 rad** (스텝 1084) | 최댓값 4.093e-6 rad(`nominal`). 다음 6.794e-8(`var16`), 5.548e-8(`var3`), 1.470e-8(`var1`). 중앙값 3.39e-11 rad |
| 접촉 전(0 ~ 첫 접촉 직전 행)의 최대 위치/자세 오차 | 6.5e-14 m / 6.6e-14 rad | 9.73e-14 m / 1.41e-13 rad |
| 접촉 뒤(첫 접촉 행부터)의 최대 위치/자세 오차 | 6.14e-6 m / 4.09e-6 rad | `nominal`과 같은 시나리오가 최대 |
| 마지막 행 위치/자세 오차 | 1.97e-6 m / 1.42e-7 rad | 최대 1.97e-6 m(`nominal`) |
| 바퀴 각 최대 오차 | 3.99e-4 rad (스텝 1085) | 최대 3.99e-4 rad(`nominal`) |
| 첫 접촉 스텝(네이티브 / WASM) | 551 / 551 | 21개 모두 같음 |
| 비트 일치 | 0번 행만 | 21개 모두 0번 행만(전체 일치 0개) |
| 위치 오차가 처음 1e-9 m를 넘은 스텝 | 904 | 시나리오마다 다름(안 넘은 것도 있음) |
| 위치 오차가 처음 1e-6 m를 넘은 스텝 | 1030 | `nominal`만 넘었다 |
| 위치 오차 1e-3 m, 1e-2 m, 1e-1 m를 넘음 | 없음 | 없음 |

`nominal`의 `max_ang`이 위치 최대와 같은 스텝 1084에서 나온다. 두 값 모두 첫 접촉(스텝 551) 뒤 약 530스텝(2.1 s) 지난 지점이다. 그 사이 차체는 착지하고 튀고 구른다.

### 5.2 네이티브끼리의 민감도(대조)

`nominal`과 같은 제어에서 시작 높이만 흔든 네이티브 실행을 네이티브 `nominal`과 비교했다.

| 흔들림 | 접촉 전 최대 위치 오차 | 전체 최대 위치 오차 | 전체 최대 자세 오차 | 마지막 행 위치 오차 |
|---|---|---|---|---|
| +1e-12 m | 1.0e-12 m | 6.36e-7 m | 4.22e-7 rad | 2.09e-7 m |
| +1e-9 m | 1.0e-9 m | 1.01e-2 m | 7.67e-3 rad | 9.81e-4 m |

접촉 전에는 오차가 흔든 크기 그대로 머문다(날아가는 구간은 접촉이 없고 오차가 자라지 않는다). 접촉이 시작되면 오차가 크게 자란다. WASM 대 네이티브의 6.1e-6 m는 이 두 흔들림이 만든 오차 사이(6.4e-7 m ~ 1.0e-2 m)에 있다. 이것은 "WASM 쪽 차이의 크기가 시작 높이 1e-12~1e-9 m의 흔들림이 만드는 정도의 오차와 같은 자릿수"라는 뜻일 뿐, 원인이 부동소수 연산 순서인지 컴파일러 옵션인지 라이브러리 구현 차이인지는 **조사하지 않았다**(출처 불명 [확인 필요]). 접촉 전 오차가 1e-13 근처에 머문다는 사실이 접촉이 없는 구간에서 두 엔진의 연산이 거의 같음을 말한다.

### 5.3 프레임률과 처리량

| 지표 | run1 | run2 | run3 | 비고 |
|---|---|---|---|---|
| 엔진 불러오기(wasm 컴파일+초기화, 로컬 파일) | 66 ms | 74 ms | 66 ms | 네트워크 전송 없음. 전송량은 gzip 약 2.86 MB |
| `mj_step` 순수 처리량 (중앙값, 7회 반복) | 167,910 스텝/s | 167,910 | 178,571 | 1,125스텝에 6.3~6.7 ms. 실시간 대비 672~714배 |
| `requestAnimationFrame` 평균 fps | 60.00 | 60.00 | 60.00 | 811프레임, 모두 vsync 상한. 한계가 아니다 |
| 프레임 간격 중앙값 / p95 / p99 / 최대 | 16.7 / 16.8 / 16.8 / 16.8 ms | 16.7 / 16.7 / 16.8 / 16.8 | 16.7 / 16.7 / 16.8 / 16.8 | 20 ms 넘은 프레임 0, 33 ms 넘은 프레임 0 (세 번 모두) |
| 프레임당 일(스텝 4~5회+그리기) 중앙값 / p99 / 최대 | 0.1 / 0.4 / 2.0 ms | 0.1 / 0.3 / 1.2 | 0.1 / 0.3 / 0.7 | 프레임 예산 16.7 ms 대비 |
| 따라잡기 상한(프레임당 25스텝)에 걸려 시뮬 시간을 버린 프레임 수 / 버린 시뮬 시간 합 | 0 / 0.0000 s | 0 / 0.0000 s | 0 / 0.0000 s | `catchup_capped_frames`, `catchup_dropped_sim_s`. 프레임 간격이 100 ms를 넘어 잘린 시간과 25스텝 뒤에 남아 버린 시간의 합. 즉 이 실행에서 시뮬은 한 번도 실시간에 뒤처지지 않았다 |
| 시뮬 시간 / 벽시계 | 1.000 | 1.000 | 1.000 | 13.516 s 시뮬 = 13.516 s 벽시계(3,379스텝) |
| 상한 없는 프레임(스텝 4회+그리기) | 33,320/s | 34,691/s | 34,979/s | 같은 일을 연달아. 값이 흔들리는 것은 부하와 거친 타이머 때문. 자릿수로만 읽는다 |
| 네이티브 Python 루프(같은 모델, ctrl+`mj_step`) | 199,664 스텝/s (중앙값 5.63 ms/1,125스텝, 5회 반복, 최대 18.1 ms) | | | `gen_reference.py --bench`, 부하 51. WASM 쪽과 같은 루프지만 Python 호출 비용이 섞여 있고 부하가 다르다. 둘의 비율(약 0.85~0.9)을 성능 비교로 쓰지 않는다 |

- `mj_step`당 약 5.8 µs(= 1/173,000 s)다. 프레임 하나(4스텝)는 약 23 µs이고 vsync 예산 16.7 ms의 0.14%다. **이 모델에서는 프레임률이 물리가 아니라 화면 갱신에 묶인다.**
- 그리기는 12개 선분의 캔버스 2D 옆모습이다. 실제 3D 렌더러(WebGL, Three.js)는 쓰지 않았고 헤드리스라 GPU 가속도 없다. 렌더 비용은 A0-02a(#47)의 범위다.
- 프레임 간격의 상위 꼬리(p99 16.8 ms)가 좁은 것은 헤드리스 Chromium의 rAF가 안정적이라는 뜻이다. 보이는 화면이 있는 브라우저, 다른 모니터 주사율, 백그라운드 탭(스로틀)은 재지 않았다.

### 5.4 결정론에 관해 (플랜 5절의 [확인 필요] 한 줄에 대한 데이터)

플랜은 "플랫폼 간, WASM과 네이티브 간은 [확인 필요]"라고 적었다. 이 측정이 주는 것은 다음이다.

- **같은 빌드끼리는 결정론적이다**: 네이티브 2회 비트 일치(23개 시나리오), WASM 같은 페이지 2회 비트 일치(21개), WASM 별도 프로세스 3회 비트 일치(21개).
- **WASM과 네이티브는 비트가 다르다**: 접촉이 있는 4.5 s 궤적에서 최대 6.1e-6 m / 4.1e-6 rad 차이(위). 그러므로 "공유 링크는 다시 시뮬하지 않고 기록된 궤적을 재생한다"는 플랜의 결정은 이 데이터와 맞는다. 브라우저에서 다시 돌려 얻은 결과를 네이티브 판정과 같다고 표시하면 안 된다.
- 이 측정은 한 OS, 한 CPU, 한 브라우저 빌드다. 다른 플랫폼 간 일치는 말하지 않는다.

## 6. DoD 대조

| DoD | 증거 |
|---|---|
| 기존 로켓 자동차 모델을 브라우저에서 실행해 프레임률을 측정했다 | 5.3절, `results/wasm-chromium-run1~3.json`(`frames`, `uncapped`, `bare`), 화면 `results/page.png` |
| 네이티브와의 궤적 차이(최대 위치·자세 오차)를 수치로 기록했다 | 5.1절: 최대 위치 6.144e-6 m, 최대 자세 4.093e-6 rad. 방법 3절 |
| 바인딩의 출처, 버전, 라이선스를 적었다 | 1절. 원장 행 `dep-mujoco-wasm-4.0.0`, `dep-playwright-1.65.0`(`assets/LEDGER.csv`, `CREDITS.md`) |

## 7. 알려진 한계 (정직성)

- 부하 113~217, 스왑 91~96%에서 쟀다. 속도 수치(5.3절)는 [추정]이고 한가한 머신 재측정은 [확인 필요]다.
- 장면은 로켓 자동차 1대(자유도 10, 접촉 몇 개)다. 강체 200개 같은 규모의 WASM 속도는 재지 않았다(A0-01a의 네이티브 값과 비교할 수 없다).
- WASM의 `MjSpec` 재컴파일(A0-01c의 "웹 쪽 재컴파일은 A0-01b의 범위" 문장)은 이 이슈 DoD에 없어서 재지 않았다. 필요하면 새 이슈가 필요하다.
- 멀티스레드 빌드(`@mujoco/mujoco/mt`, COOP/COEP와 `SharedArrayBuffer` 필요)는 쓰지 않았다.
- 브라우저는 헤드리스 Chromium 하나다. Firefox, Safari, 모바일, Windows는 재지 않았다. 공식 README는 Windows가 실험적이라고 적었다.
- 오차의 원인(연산 순서, 컴파일 옵션, 수학 라이브러리 구현)은 조사하지 않았다. 5.2절의 대조는 자릿수 비교다.
- `mujoco-js`와 `zalo/mujoco_wasm`은 메타데이터만 봤고 실행하지 않았다. 둘이 같은 결과를 내는지 모른다.
- 변형 20개는 내가 만든 것이다. 레거시의 것이 아니다. 접촉이 다른 모양이 되게 한 표본이고 확률 분포가 아니다. 이 숫자를 "WASM 오차의 분포"로 읽지 않는다.
- 위 6.1e-6 m는 이 한 시나리오(영웅 8,000 N)의 최댓값이다. 다른 제어에서는 더 크게 자랄 수 있다. 네이티브끼리 1e-9 m 흔들림이 1e-2 m가 되었음이 보여 주듯 접촉 뒤 증폭은 크다.
- 측정 중 자원 가드가 SSD 여유 7.4~9.7 GiB(임계 10 GiB 미만)로 차단했다. 임계는 건드리지 않았다. 내 임시 폴더(`/tmp/mjprobe`)를 지우고 `uv cache prune`(490 MiB), `pnpm store prune`으로 쓰이지 않는 캐시를 정리한 뒤 여유가 10 GiB를 넘을 때까지 기다려 다시 돌렸다.

## 8. 의존성 라이선스

| 의존성 | 라이선스 | 출처 | 원장 행 |
|---|---|---|---|
| `@mujoco/mujoco` 4.0.0 | Apache-2.0 | https://github.com/google-deepmind/mujoco/tree/4.0.0/wasm , https://www.npmjs.com/package/@mujoco/mujoco | `dep-mujoco-wasm-4.0.0` |
| `playwright` 1.65.0 (+ `playwright-core` 1.65.0) | Apache-2.0 | https://github.com/microsoft/playwright | `dep-playwright-1.65.0` |
| Chrome Headless Shell 158.0.8127.18 (Playwright `chromium-headless-shell` revision 1254) | **BSD-3-Clause**(Chromium 소스의 최상위 `LICENSE`, 저작권 "The Chromium Authors", 2026-11-10에 https://chromium.googlesource.com/chromium/src/+/main/LICENSE 에서 본문 확인). 바이너리는 제3자 구성요소(Skia, V8, ICU, FFmpeg 등)를 함께 싣고 각자의 라이선스를 따른다. 그 목록(`chrome://credits`에 해당)은 이 측정에서 확인하지 않았다 [확인 필요]. 개발 도구로만 쓰고 배포하지 않는다 | 저장소에 넣지 않음. `playwright install`이 `cdn.playwright.dev`에서 받는다(리비전은 https://github.com/microsoft/playwright/blob/v1.65.0/packages/playwright-core/browsers.json 에서 확인). 원장 행은 만들지 않았다: 에셋도 저장소 의존성도 아닌 실행 도구이고 파일이 저장소에 없다 |
| `mujoco` 4.0.0, `numpy` 2.5.4 (네이티브 기준) | Apache-2.0, BSD-3-Clause | A0-01a와 같다 | `dep-mujoco-4.0.0`, `dep-numpy-2.5.4` |

`spikes/mujoco-wasm`은 저장소의 pnpm 워크스페이스(`apps/*`, `packages/ui`) 밖의 독립 프로젝트다(`pnpm-workspace.yaml`이 `packages: []`). 그래서 루트 `pnpm lint/build/test`와 CI의 `web` 잡은 이 폴더를 실행하지 않고, 웹 CI 가드(`check_web_scripts.mjs`)의 대상도 아니다. 이 폴더의 테스트는 CI에서 돌지 않는 로컬 점검이다(`spikes/mujoco-limits`의 `test_scale.py`와 같은 관례: 스파이크는 측정만 하고 하니스 점검은 로컬에서 돌린다). 마지막으로 돌린 명령과 결과: `pnpm --dir spikes/mujoco-wasm test` 21건 통과, `test:browser`(가드 아래, 헤드리스 Chromium) 4건 통과, `uv run spikes/mujoco-wasm/tests/test_gen_reference.py` 6건 통과, `uv run spikes/mujoco-wasm/check_legacy_bundle.py` 통과.
