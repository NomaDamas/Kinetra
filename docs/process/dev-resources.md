# 개발 자원 규칙 (P0-09)

개발 머신은 SSD 여유가 20 GiB 안팎이고 스왑이 거의 가득 차 있다(창업자 보고, 아래 측정과 일치). 무거운 실행이 머신을 멈추거나 디스크를 채우면 잎을 한 번에 끝내지 못하고, 실패 원인이 코드인지 머신인지 가를 수 없다. 이 문서는 그것을 막는 규칙이다. 근거: `docs/plan/studio-plan.md` 15.6절.

## 규칙

1. **무거운 실행은 한 번에 하나.** 에이전트와 사람을 합쳐 이 머신에서 동시에 둘을 돌리지 않는다. 다른 무거운 프로세스가 도는 중이면 기다린다.
2. **실행 전에 가드를 통과한다.** `uv run python tools/dev/resource_guard.py --profile heavy`가 0으로 끝나야 한다. 2(차단)이거나 3(측정 실패)이면 돌리지 않는다. 측정 못 한 것을 통과로 치지 않는다.
3. **차단되면 아래 정리 절차를 따른 뒤 다시 잰다.** 임계를 낮추어 통과시키지 않는다. 임계는 아래 근거 표를 바꾸는 PR로만 바꾼다.
4. **경고는 통과이지만 PR의 "검증 방법"에 수치를 적는다.** 이 머신은 스왑이 늘 90% 안팎이라 경고가 기본 상태다.
5. **측정 기록을 남긴다.** 무거운 실행의 PR 본문에 아래 양식을 붙인다. 가드가 실행을 감싸면(`-- 명령`) 표가 자동으로 나온다.

## 가드 사용

```bash
uv run python tools/dev/resource_guard.py --profile heavy; echo $?     # 측정만. 0 통과(경고 포함), 2 차단, 3 측정 실패
uv run python tools/dev/resource_guard.py --profile heavy --json        # 기계가 읽는 출력
uv run python tools/dev/resource_guard.py --profile heavy -- <명령...>  # 통과하면 명령을 돌리고 전·후·최악 표를 남긴다. 명령의 종료 코드를 돌려준다
uv run pytest tools/dev -q                                              # 가짜 측정값으로 차단·경고·통과를 단언하는 테스트
```

- 재는 것: 저장소가 있는 볼륨의 SSD 여유(`--path`로 바꿈), 스왑 사용량과 사용률, 메모리 압력 단계.
- macOS는 `sysctl vm.swapusage`와 `kern.memorystatus_vm_pressure_level`(1=normal, 2=warn, 4=critical)을 읽는다. Linux는 `/proc/meminfo`의 스왑과 `/proc/pressure/memory`의 `full avg10`을 읽는다(PSI가 꺼진 커널이라 파일이 없거나 권한이 없어 읽지 못하면 측정 실패로 종료 코드 3이고 명령은 시작하지 않는다. 못 잰 압력을 통과로 치지 않는다). Linux 경로는 파서와, 플랫폼·`/proc` 읽기를 가짜로 바꾼 `collect` 테스트로 확인했고, 진짜 Linux 읽기는 CI 러너(`engine.yml`의 `uv run pytest tools/dev`)에서만 돈다. 이 머신(macOS)에서는 진짜 Linux 읽기를 돌려 보지 않았다.
- 단위는 GiB(2**30 바이트)로 통일했다(출력, 설정 키 `*_gib`, 문서). `vm.swapusage`의 M과 `df -h`의 G도 2진 단위다.
- 설정값이 유한한 숫자가 아니거나 범위(SSD 0 이상, 퍼센트 0~100)를 벗어나거나 PSI warn > critical, 압력 warn > block이면 종료 코드 3이다.
- `-- 명령` 실행 중 측정이 실패하면 명령을 프로세스 그룹째 끝내고 종료 코드 3이다: 그룹에 TERM을 보내 최대 10초 그룹이 비기를 기다리고(리더가 먼저 끝나도 손자까지 본다), 남았으면 그룹에 KILL. 가드가 SIGTERM·SIGINT를 받아도 같은 정리를 하고 128+신호 번호로 끝난다(실행 중에만 핸들러를 걸고 끝나면 이전 핸들러로 되돌린다). 자식은 새 세션에서 시작한다.
- 설정의 `profiles`나 고른 프로필이 TOML 테이블이 아니면 종료 코드 3이다.
- 다른 도구에서는 `import resource_guard; resource_guard.guard_or_exit("heavy")`로 부른다. 이미 `-- 명령`으로 가드를 통과해 시작된 자식 프로세스는 `KINETRA_GUARD_PASSED=1`을 받아 같은 표를 다시 찍지 않는다.

## 임계값 (`tools/dev/resource_guard.toml`)

값은 설정 파일에만 있고 출력에 `기본값` 배지가 붙는다. 배지는 "우리가 정한 값"이지 측정으로 검증한 인용이 아니라는 뜻이다.

| 항목 | 임계 | 동작 | 배지 | 근거 |
|---|---|---|---|---|
| SSD 여유 | 10 GiB 미만 | 차단 | `기본값` | 이 머신의 여유는 측정 기간 17.8~21.0 GiB. 아래 XR 에뮬레이터 1회는 SSD를 거의 쓰지 않았다(변화 -0.00~+0.31 GiB, 다른 프로세스의 잡음 범위). 설치(uv 캐시 4.6 GiB, pnpm 저장소 1.8 GiB)와 브라우저 내려받기가 실제로 먹는 쪽이라 10 GiB는 그 한 번을 더 받아도 남는 선이다. 18 GiB 이상으로 올리면 지금 머신의 모든 실행이 막힌다 |
| 스왑 사용률 | 90% 이상 | 경고 | `기본값` | 같은 기간 스왑은 총 17~19 GiB 중 16.2~17.9 GiB(91~95%)였고 실행과 무관하게 ±1 GiB 흔들렸다. 차단으로 두면 이 머신에서 아무것도 못 돌린다. 스왑이 가득 찬 상태가 실제 위험인지는 메모리 압력이 말해 준다 |
| 메모리 압력 | `critical`이면 차단, `warn` 이상이면 경고 | | `기본값` | 스왑 95%, 부하 평균 80~120인데도 macOS 압력 단계는 측정 내내 1(normal)이었다. 그래서 스왑이 아니라 압력 단계를 차단 기준으로 둔다 |
| Linux PSI | `full avg10` 5.0 이상 warn, 20.0 이상 critical | | `기본값` | **측정하지 않은 값**이다. Linux 머신이 생기면 다시 정한다 [확인 필요] |

**이번 재설정의 결론: 세 임계 모두 [제안] 그대로 유지한다.** 측정이 [제안]을 뒤집지 않았다. 단 아래 측정은 1회·최소 장면이라 "XR 에뮬레이터는 가볍다"의 증거가 아니다.

## 측정: 이 머신의 XR 에뮬레이터 1회 (2026-11-10)

- 머신: macOS 24.6 arm64, SSD 461 GiB(여유 18~21 GiB), 스왑 총 17~19 GiB, 부하 평균 약 80~120(다른 에이전트 작업이 동시에 돌고 있었다. 그래서 변화량은 잡음이 크다).
- 에뮬레이터: IWER 2.8.0(`npm view iwer license` → MIT, 번들 7.1 MB), Meta Quest 3 프로필, `installRuntime({ forceInstall: true })`. Chrome 157 헤드리스(SwiftShader), `Runtime.evaluate`로 사용자 제스처를 주어 `immersive-vr` 세션 진입 → 300프레임 `getViewerPose` + WebGL clear → 세션 종료. 임시 폴더 `/tmp/xr-probe`에서 돌렸고 저장소에는 넣지 않았다(의존성이 아니라 측정용이다).
- **이것은 A0-02b(#48)의 `@pmndrs/xr` 장면이 아니다.** 에뮬레이터 런타임과 브라우저만 잰 하한이다. 실제 장면이 들어가면 더 클 수 있다. A0-02b가 가드 아래에서 같은 양식으로 다시 잰다.

| 항목 | 전 | 후 | 변화 | 실행 중 최악 |
|---|---|---|---|---|
| SSD 여유 GiB | 17.84 | 18.15 | +0.31 | 17.84 |
| 스왑 사용 GiB | 17.32 | 17.32 | +0.00 | 17.32 |
| 스왑 사용률 % | 91.2 | 91.2 | +0.0 | |
| 메모리 압력 | normal | normal | | |

- 결과: 세션 진입 성공, 300프레임, 5.5~6.2초(헤드리스 소프트웨어 렌더, 프레임률 증거가 아님). 헤드리스 Chrome 프로세스 합계 RSS 최대 704 MiB(0.7초 간격 표본 12회, `ps`).
- 첫 시도 두 번은 에뮬레이터가 안 떴다(사용자 제스처 필요, 이미 있는 네이티브 `navigator.xr` 때문에 `forceInstall` 필요). 위 표는 성공한 실행의 것이다. 이 두 조건은 A0-02b가 알아야 한다.
- 같은 기간 강체 1,000개 `scale.py`(0.2 s 시뮬)도 가드 아래에서 1회 돌렸고 SSD·스왑 변화는 0이었다. 0.2 s는 측정 장면이 아니라 배선 확인이다.
- 한계: 1회. 스왑은 다른 프로세스가 ±1 GiB 흔들어서 실행 한 번의 영향이 잡음에 묻힌다. 이 표로 임계를 낮추거나 올릴 근거는 없다.

## 진입점 목록

무거운 실행은 아래 네 가지다. 진입점은 시작하기 **전에** 가드를 부른다. 이미 있는 것은 이 PR에서 연결했다. 아직 없는 것은 만드는 이슈가 같은 방식으로 연결한다(그 이슈의 본문은 여기서 고치지 않았다).

| 무거운 실행 | 진입점 | 가드 | 이슈 |
|---|---|---|---|
| 강체 1,000개 이상 스케일 측정 | `spikes/mujoco-limits/scale.py` (`--bodies` 또는 `--break-pile`에 1,000 이상) | **연결됨.** 시작 전에 `guard_or_exit("heavy")`. 차단이면 종료 코드 2로 아무것도 재지 않고 끝난다. 테스트: `spikes/mujoco-limits/test_scale.py`의 `CliTest` | #43, #282 (A0-01a) |
| XR 에뮬레이터 테스트 | `spikes/webxr/run-xr.mjs`(`pnpm --dir spikes/webxr xr`)와 `spikes/webxr/tests/browser-xr.test.mjs`(`test:browser`) | **연결됨.** `CI=true` 또는 `KINETRA_GUARD_PASSED=1`(가드가 `-- 명령`으로 감쌀 때 설정)이 아니면 시작하지 않는다(`run-xr.mjs`는 종료 코드 3, 브라우저 시험은 import 시점에 예외). 테스트: `spikes/webxr/tests/offline.test.mjs` | #48 (A0-02b). #205 (XR-01b)가 같은 방식으로 잇는다 |
| 브라우저 렌더·스트림·공유 페이지 측정 | `spikes/web-client/measure-pose.mjs`(A0-02a), `measure-replay.mjs`(A0-02c) | **연결됨.** 가드 밖에서 시작하면 종료 코드 2로 거절한다(`KINETRA_GUARD_PASSED`). 실행: `resource_guard.py --profile heavy -- pnpm --dir spikes/web-client measure:pose` | #47 (A0-02a), #49 (A0-02c) |
| 부품 glTF 브라우저 증거 | `tools/gltf-check/capture.ts`(`pnpm --filter @kinetra/gltf-check capture`), `test/capture.browser.ts`(`test:browser`) | **연결됨.** `CI=true` 또는 `KINETRA_GUARD_PASSED=1`이 아니면 종료 코드 3(캡처), import 시점 예외(브라우저 시험). 오프라인 시험은 `test/capture.test.ts` | #94 (B-01c) |
| 영상 인코딩 | 아직 없음 | 프레임 캡처·mp4 내보내기 진입점이 시작 전에 부른다 | #190 (H-01b), #195 (H-02d) |
| 유체 연구 실행 | 아직 없음. Genesis·Taichi는 가드를 통과할 때만 설치하고 돌린다 | 실행기가 시작 전에 부른다 | #305 (FL-06), #307 (FL-08) |

새 무거운 실행을 만들면 이 표에 한 줄을 더한다. 표에 없는 무거운 실행은 규칙 위반이다.

## 차단됐을 때의 정리 절차

먼저 무엇이 먹는지 본다: `df -h /`, `du -sh /tmp/kin-* ~/.cache/uv ~/Library/pnpm ~/Library/Caches/ms-playwright`. 위에서부터 하고, 한 단계마다 가드를 다시 돌린다. **내 것이 아닌 것은 지우지 않는다.** 다른 사람이나 에이전트의 worktree는 그 주인이 정리한다.

1. **임시 worktree.** 머지됐거나 버린 브랜치의 worktree를 지운다: `git worktree list`, `git worktree remove /tmp/kin-<branch>`, `git worktree prune`. 안에서 `.venv`와 `node_modules`가 가장 크다. 커밋 안 한 변경이 있으면 먼저 확인한다.
2. **uv 캐시.** `uv cache prune`(쓰이지 않는 것만). 더 필요하면 `uv cache clean`(전부, 다음 실행에서 다시 받는다). 위치: `uv cache dir`.
3. **pnpm 저장소.** `pnpm store prune`(어디서도 안 쓰는 패키지만). 위치: `pnpm store path`.
4. **Playwright 브라우저.** `~/Library/Caches/ms-playwright`(Linux는 `~/.cache/ms-playwright`) 아래 오래된 브라우저 폴더를 지운다. 다음 `playwright install`이 필요한 것만 다시 받는다.
5. **스파이크 산출물.** `spikes/*/results`의 큰 파일, `out/`, `MUJOCO_LOG.TXT`, 임시 영상과 프레임 폴더. 저장소에 커밋된 결과(`REPORT.md`가 인용하는 JSON)는 지우지 않는다. 커밋 안 된 것(`git clean -ndX`로 미리 본다)만 지운다.
6. **스왑.** 스왑은 지울 수 없다. 다른 무거운 프로세스(브라우저 탭, 에뮬레이터, 다른 에이전트의 실행)를 끝낸다. 압력이 `critical`이면 그것이 풀릴 때까지 기다린다.

다 해도 차단이면 실행하지 않고 이슈에 현재 수치를 적어 창업자에게 올린다. 다른 머신이나 클라우드, 증설은 창업자가 정한다(`docs/plan/studio-plan.md` 15.6절).

## 측정 기록 양식

무거운 실행의 PR 본문 "검증 방법"에 붙인다. `-- 명령`을 쓰면 표는 자동으로 나온다.

```
### 자원 기록
- 실행: <명령 전체>, <날짜>
- 가드: <통과 | 경고(항목) >, 임계 배지 [기본값], 프로필 heavy
- 머신: <OS>, SSD 여유 <전> GiB, 스왑 <사용>/<총> GiB, 부하 평균 <값>

| 항목 | 전 | 후 | 변화 | 실행 중 최악 |
|---|---|---|---|---|
| SSD 여유 GiB | | | | |
| 스왑 사용 GiB | | | | |
| 스왑 사용률 % | | | | |
| 메모리 압력 | | | | |

- 소요 시간: <초>, 종료 코드: <값>
- 한계: <잡음, 동시에 돌던 것, 반복 횟수>
```
