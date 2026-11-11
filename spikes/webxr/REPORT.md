# WebXR 스파이크: pmndrs/xr로 부품 하나를 잡아 옮기기, 에뮬레이터를 Playwright로 구동 (A0-02b, 이슈 #48)

측정만 한다. 제품 UI가 아니다(범위 밖). 이 폴더는 저장소 루트 워크스페이스와 따로 서는 pnpm 프로젝트다(`pnpm-workspace.yaml`의 `packages: []`). 이슈 본문의 검증 명령은 `pnpm --dir spikes/web-limits xr`로 적혀 있으나 그 폴더는 없고 이 스파이크는 `spikes/webxr`에 있다. 같은 일을 하는 명령은 아래 "재현"의 `pnpm --dir spikes/webxr xr`다.

## 결론 먼저

- **된다.** 헤드셋 없이, Playwright 자체 헤드리스 Chromium(Chrome Headless Shell 158.0.8127.18, `playwright-core` 1.65.0) 안에서 Meta의 WebXR 에뮬레이터 IWER 2.8.0(Meta Quest 3 프로필)이 `immersive-vr` 세션을 열었고, `@pmndrs/xr` 6.6.32가 컨트롤러 두 개를 읽었다. 스크립트가 오른쪽 컨트롤러를 부품 위로 옮기고, 쥐기(squeeze)를 누르고, 세 구간으로 옮기고, 놓았다. `@pmndrs/handle` 6.6.32의 `HandleStore`가 부품(0.2 m 정육면체)을 따라 움직였다.
- **최종 위치 단언을 통과했다.** 부품 시작 (0.25, 1.2, −0.4) m. 컨트롤러가 명령받은 이동량 (0.2, 0.2, −0.25) m. 부품 최종 (0.4499999880794095, 1.3999999284753808, −0.6499999403985841) m. 이동한 거리 0.3775 m.
  - 단언 1(컨트롤러 실제 이동량 기준): 부품 최종 = 시작 + (놓기 직전 그립 위치 − 쥔 순간 그립 위치). 최대 축 오차 3.2e-12 m. 부품이 컨트롤러를 따라간다는 것을 보이지만 같은 값에서 나온 두 양의 비교라 약한 단언이다.
  - 단언 2(스크립트가 명령한 이동량 기준, 독립 기준): 부품 최종 = 시작 + 명령한 이동량. 최대 축 오차 **7.15e-8 m**. 허용 오차는 1e-4 m(0.1 mm)로 정했다. IWER는 포즈를 float32 행렬로 들고 있어 1 m에서 1e-7 안팎의 오차가 나오므로 그 1,000배다. 이 허용치는 내가 고른 값이고 어떤 표준에서 온 것이 아니다.
  - 같은 장면을 3번 별도 프로세스로 돌렸고 단언 2의 오차(7.152e-8 m)와 이동 거리(0.37749 m)는 3번 모두 같았다.
- **Playwright가 에뮬레이터를 구동할 수 있다.** 필요했던 것은 둘이다: ① Chromium은 헤드리스 셸에서도 자체 `navigator.xr`을 갖고 있어(이 실행에서 `native_navigator_xr_before_install: true`) IWER를 `installRuntime({ forceInstall: true })`로 설치해야 한다. 그냥 설치하면 IWER가 기존 것을 두고 경고만 한다. ② 세션 진입은 `page.click()`으로 사용자 제스처를 줘서 시작했다. 컨트롤러는 `page.evaluate`로 IWER의 `device.controllers.right.position.set(...)`, `updateButtonValue("squeeze", 1)`을 불러 움직였다. 둘 다 `docs/process/dev-resources.md`의 선행 측정과 같은 결론이다.
- **헤드셋 프레임률: [확인 필요].** 헤드셋이 없다. 아래 헤드리스 프레임 간격은 소프트웨어 렌더 헤드리스 Chromium의 `requestAnimationFrame` 간격이고 헤드셋 프레임률의 증거가 아니다(5절).
- **한 번도 하지 않은 것:** 스테레오 렌더(`stereoEnabled` 기본값 false), 손 추적, 레이 포인터(트리거)로 잡기, 실제 GPU, Chromium 외 브라우저, 실제 Quest 브라우저, 부품 여러 개, 물리 엔진과의 연결. 부품은 핸들이 직접 옮긴 것이지 시뮬이 옮긴 것이 아니다. 이것은 "입력이 들어와 부품이 움직인다"의 증거이고 어셈블리나 판정의 증거가 아니다(V1).

## 1. 무엇을 만들었나

| 파일 | 하는 일 |
|---|---|
| `src/scene.js` | 부품(`BoxGeometry` 0.2 m)과 `makeGrabbable`: `HandleStore`를 `rotate:false, scale:false, multitouch:false`로 만들어 부품에 묶는다. `pointerEventsType = { allow: "grab" }`라 쥐기 포인터만 부품을 잡는다 |
| `src/app.js` | 브라우저 페이지. IWER 설치, `createXRStore`(`@pmndrs/xr`), 애니메이션 루프에서 `store.update`와 `handle.update`. 시험 상태는 `window.__xr`(JSON 가능), 살아 있는 객체는 `window.__xrObjects` |
| `build.mjs` | esbuild로 번들(코드 분할). `@pmndrs/xr`이 자기 에뮬레이터를 지연 로딩하는 조각을 `emulate:false`라 받지 않는다(아래 3절) |
| `serve.mjs` | 루프백 정적 서버. `dist/`와 `/profiles/*`(`fixtures/profiles`, 컨트롤러 입력 프로필 JSON)를 따로 준다 |
| `driver.mjs` | Playwright 쪽: 번들, 서버, 브라우저, 세션 진입, 컨트롤러 스크립트, 단언 13개(`checks`), 증거 JSON |
| `run-xr.mjs` | `pnpm xr`의 진입점. 가드 밖이면 종료 코드 3 |
| `guard.mjs` | 가드 규칙 한 곳: `CI=true` 또는 `KINETRA_GUARD_PASSED=1` |
| `tests/offline.test.mjs` | 20건, 브라우저 없음(CI의 `spikes` 잡이 돈다) |
| `tests/browser-xr.test.mjs` | 1건, 브라우저. 가드 밖이면 import 시점에 예외 |
| `results/a0-02b-xr.json` | 기록된 실행의 증거 |
| `fixtures/profiles/` | `@webxr-input-profiles/assets` 1.0.20의 JSON 두 개(`profilesList.json`, `meta-quest-touch-plus/profile.json`). 원본 해시는 `assets/LEDGER.csv`에 있고 tarball의 같은 파일 sha256과 일치함을 확인했다. 컨트롤러 3D 모델(.glb)은 넣지 않았다 |

`@pmndrs/xr`은 기본으로 컨트롤러 입력 프로필을 CDN(`cdn.jsdelivr.net`)에서 받는다. 이 테스트는 `baseAssetPath`를 로컬 서버로 돌려 네트워크 없이 돈다. 실행이 요청한 경로는 `results/a0-02b-xr.json`의 `requested_paths`에 있고 출처(origin)는 루프백 하나뿐이다(`no request left loopback` 단언).

## 2. 방법

장면(`driver.mjs`의 `runXr`):

1. 페이지를 열고 IWER를 설치한다. `navigator.xr instanceof XRSystem`이고 UA에 `Quest 3`가 있음을 확인한다.
2. `#enter`를 클릭해 `store.enterVR()`. 컨트롤러 두 개(`left`, `right`)가 `@pmndrs/xr`에 보일 때까지 기다린다. 프로필은 `meta-quest-touch-plus` → `oculus-touch-v3` → `oculus-touch` → `generic-trigger-squeeze-thumbstick`로 보고됐다.
3. 오른쪽 컨트롤러를 부품 시작 위치로 옮긴다(그립 위치는 컨트롤러 위치에서 IWER 프로필의 그립 오프셋만큼 떨어져 (0.2540, 1.1841, −0.3504) m가 됐다. 쥐기 구(반지름 0.07 m)가 0.2 m 정육면체와 겹친다).
4. 쥐기 없이 컨트롤러만 0.05 m 옮겨 본다. 부품은 그대로여야 한다(`part unmoved by an un-squeezed controller`).
5. 쥐기 값 1 → 핸들 상호작용 시작(`state.first`)을 기다린다.
6. 컨트롤러를 3구간(`MOVE_LEGS`: (0.3, 0.15, −0.1), (0, 0.1, −0.2), (−0.1, −0.05, 0.05) m)으로 옮긴다. 구간마다 6걸음, 걸음마다 프레임 하나를 기다린다. 합계 (0.2, 0.2, −0.25) m.
7. 쥐기 값 0 → 상호작용 끝(`state.last`). 부품 위치를 읽고, 컨트롤러를 더 옮긴 뒤에도 부품이 그대로인지 읽는다.
8. 세션 프레임 120개의 간격을 요약한다.

`@pmndrs/xr`의 오른쪽 컨트롤러 입력이 `squeezestart`/`squeezeend` 이벤트가 되고, `@pmndrs/pointer-events`의 쥐기 포인터(`createGrabPointer`, 구 교차)가 `pointerdown`/`pointermove`/`pointerup`을 부품에 보내고, `HandleStore`가 그것을 부품 위치로 바꾼다. 이 연결은 라이브러리의 기본 동작이고 이 스파이크가 쓴 것은 그 위의 몇 줄(`src/app.js`)이다.

## 3. 결과

기록된 실행: `results/a0-02b-xr.json`. 13개 단언 모두 통과(`checks`). 명령과 자원 표는 5절.

| 항목 | 값 |
|---|---|
| 브라우저 | Chromium Headless Shell 158.0.8127.18 (`playwright-core` 1.65.0) |
| 에뮬레이터 | IWER 2.8.0, Meta Quest 3 프로필, `forceInstall` |
| 세션 | `immersive-vr`, 컨트롤러 `left,right` |
| 부품 시작 | (0.25, 1.2, −0.4) m |
| 부품 최종 | (0.44999999, 1.39999993, −0.64999994) m |
| 컨트롤러 그립 이동량(읽은 값) | (0.19999999, 0.19999993, −0.24999994) m |
| 명령한 이동량 | (0.2, 0.2, −0.25) m |
| 최대 축 오차: 부품 대 (시작 + 읽은 그립 이동량) | 3.2e-12 m |
| 최대 축 오차: 부품 대 (시작 + 명령한 이동량) | 7.15e-8 m (허용 1e-4 m) |
| 이동 거리 | 0.3775 m |
| 쥐기 시작/끝 횟수 | 1 / 1 |
| 쥐기 없이 컨트롤러만 이동 | 부품 변화 0 |
| 놓은 뒤 컨트롤러 이동 | 부품 변화 0 |
| 번들 | `app.js` 89,817 B(gzip 27,274 B), `chunk-23YDDPVT.js`(three.js와 IWER 런타임이 든 공유 조각) 1,002,224 B(gzip 263,220 B). `emulate-*.js`(`@pmndrs/xr`의 자체 에뮬레이터, 개발 UI와 React 포함) 909,738 B와 합성 환경 `*_room-*.js` 5개는 만들어졌으나 이 실행은 요청하지 않았다 |
| 요청한 URL | `/`, `/app.js`, `/chunk-23YDDPVT.js`, `/chunk-OOJM4CTU.js`, `/profiles/profilesList.json`, `/profiles/meta-quest-touch-plus/profile.json` (모두 `127.0.0.1`) |

같은 명령을 별도 프로세스로 2번 더 돌렸을 때(`xr`, 결과 파일은 남기지 않았다) 13개 단언이 모두 통과했고 단언 2의 오차 7.152e-8 m와 이동 거리 0.37749 m는 같았다. 브라우저 테스트(`test:browser`)도 1건 통과했다.

### 이것이 보이지 않는 것

- **부품을 옮긴 것은 핸들(입력 → 위치 복사)이지 시뮬이 아니다.** 판정과 무관하다. 어셈블리, 관절, 충돌과의 연결은 XR-01 이후의 일이다.
- 컨트롤러는 사람이 아니라 스크립트가 움직였다. 사람의 손떨림, 지연, 프레임 누락은 없다. 걸음마다 프레임 하나를 기다렸으므로 "빠르게 움직이는 컨트롤러"에서의 동작은 모른다.
- 단언 1은 약하다(부품이 같은 그립 포즈를 따라가므로 거의 같은 값이다). 독립 기준인 단언 2가 이 스파이크의 실질 증거다.
- `@pmndrs/xr`의 자체 에뮬레이터(`emulate` 옵션, 개발 UI 포함)는 쓰지 않았다(`emulate: false`). 이유는 시험이 IWER 장치 객체를 직접 쥐어야 해서다. 자체 에뮬레이터 경로가 이 헤드리스 셸에서 되는지는 **시험하지 않았다** [확인 필요].
- 컨트롤러 3D 모델(`.glb`)을 받지 않고(`model:false`) 입력 프로필 JSON만 받았다. 모델 로딩 경로는 이 시험에 없다.

## 4. 헤드셋 프레임률 [확인 필요]

헤드셋이 없다. 이 문서에 헤드셋 프레임률은 없다.

참고로 기록된 값(헤드리스 소프트웨어 렌더, 640×360 캔버스, 모노, 세션 프레임 120개):

| 항목 | 값 |
|---|---|
| 평균 프레임 간격 | 16.66 ms (60.0 fps) |
| p50 / p99 / 최대 간격 | 16.7 / 17.3 / 17.8 ms |
| IWER가 세션에 설정한 명목 프레임률(`session.frameRate`) | 120 Hz (장치 설정의 값을 읽은 것. 측정이 아니다) |

60.0 fps는 헤드리스 Chromium의 `requestAnimationFrame`이 60 Hz로 도는 값이고(`mujoco-wasm` 스파이크의 같은 헤드리스 셸 값도 60.00 fps였다) 장면이 빨라서가 아니라 vsync 상한이다. 에뮬레이터의 120 Hz는 장치 프로필이 정한 숫자일 뿐 이 실행이 그 속도로 그렸다는 뜻이 아니다. 실기 프레임률은 Quest 3 같은 기기에서 같은 페이지를 LAN HTTPS로 열어(XR-01c의 일) 재야 한다.

## 5. 재현

```bash
# 설치(저장소 루트 워크스페이스와 따로: pnpm-workspace.yaml 의 packages: [])
pnpm --dir spikes/webxr install --frozen-lockfile
# 브라우저는 Playwright 캐시의 chromium-headless-shell 을 쓴다. 없으면 한 번:
pnpm --dir spikes/webxr exec playwright-core install chromium-headless-shell
# 오프라인 시험(20건, 브라우저 없음). CI 의 spikes 잡이 돈다
pnpm --dir spikes/webxr test
# 장면 실행과 증거 JSON(무거운 실행: 가드 아래에서)
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/webxr xr --out results/a0-02b-xr.json
# 브라우저 시험(1건)
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --dir spikes/webxr test:browser
```

가드 밖에서 `xr`을 시작하면 종료 코드 3이고 브라우저를 띄우지 않는다. `test:browser`는 import 시점에 예외로 멈춘다. 둘 다 `CI=true` 또는 `KINETRA_GUARD_PASSED=1`이면 시작한다(`tools/screenshots/capture.ts`와 같은 규칙). `docs/process/dev-resources.md`의 진입점 표에 이 줄을 이어 두었다.

### 자원 기록

| 항목 | 전 | 후 | 변화 | 실행 중 최악 |
|---|---|---|---|---|
| SSD 여유 GiB | 12.95 | 12.95 | -0.00 | 12.95 |
| 스왑 사용 GiB | 13.30 | 13.30 | +0.00 | 13.30 |
| 스왑 사용률 % | 88.7 | 88.7 | +0.0 | |
| 메모리 압력 | normal | normal | | |

명령 `pnpm --dir spikes/webxr xr --out results/a0-02b-xr.json`, 종료 코드 0, 4.9 s(번들 포함). 같은 가드 아래의 `test:browser`는 5.2 s였고 이 실행의 가드 결과는 `통과(경고 있음)`(메모리 압력 `warn`)였다. 이 실행 직전까지 SSD 여유가 10 GiB 아래(1.0~2.9 GiB)여서 가드가 차단했고, 임계를 건드리지 않은 채 다른 작업이 공간을 비울 때까지 가드를 반복해 재서 통과한 첫 실행이 위 표다. 이 머신의 다른 에이전트가 같은 시간에 돌고 있었으므로 변화량은 잡음 범위다. 이 장면 하나로 "XR 에뮬레이터는 가볍다"를 말할 수 없다(장면은 부품 1개, 640×360).

## 6. 의존성과 라이선스 (V5)

모두 `assets/LEDGER.csv`의 `dependency` 행(받은 날짜 2026-11-11, 원본 해시는 `npm pack`한 tarball의 sha256)과 `CREDITS.md`에 있다. 직접 의존성: `@pmndrs/xr`, `@pmndrs/handle`, `@pmndrs/pointer-events`, `three`, `iwer`, `esbuild`(개발), `playwright-core`(개발, 기존 행 `dep-playwright-core-1.65.0` 재사용), 입력 프로필 JSON(`@webxr-input-profiles/assets` 1.0.20).

- `@pmndrs/*` 세 패키지의 `package.json` `license` 필드는 `SEE LICENSE IN LICENSE`이고 패키지에 든 `LICENSE` 파일 본문은 MIT 조항이다(저작권자 Bela Bohlender, Coconut Capital). 원장에는 파일 본문에 따라 `MIT`로 적었다. `pnpm licenses`는 이 셋을 `Unknown`으로 보고한다.
- 추이 의존성 중 MIT가 아닌 것: `webxr-layers-polyfill` 1.1.0 (Apache-2.0, IWER의 의존성이라 IWER와 함께 번들된다), `@fortawesome/free-solid-svg-icons` (CC-BY-4.0 AND MIT, `@iwer/devui`의 의존성이라 `emulate` 지연 조각에만 들어간다. 이 실행은 그 조각을 요청하지 않았다). 이 스파이크는 어떤 것도 저장소에 복사하지 않는다(번들은 `dist/`이고 `.gitignore`다). 원장의 `dep-iwer-2.8.0` 행과 이 문단에 적었고 별도 원장 행은 만들지 않았다.
- `three`가 둘 설치된다: 직접 의존성 0.187.0과 `@iwer/devui`·`@iwer/sem`이 끌어오는 0.165.0. 후자는 `emulate` 조각 안에만 있다.

## 7. 다음 일에 넘기는 것

- **XR-01b(에뮬레이터 개발·CI 경로):** 이 스파이크의 `driver.mjs`가 그 경로의 뼈대다. 알아야 할 것: `forceInstall`, 사용자 제스처, 컨트롤러 입력 프로필을 로컬에서 줄 것, `emulate:false`로 이중 설치를 피할 것. CI에서 돌릴지(GitHub Actions의 Ubuntu 헤드리스 Chromium + SwiftShader)는 이 스파이크가 **확인하지 않았다**. 이 실행은 macOS arm64 한 대뿐이다 [확인 필요]. `spikes` 잡은 `test:browser`를 돌리지 않는다.
- **XR-01c(헤드셋 접속):** 실기 프레임률과 컨트롤러 모델 로딩은 거기서.
- DoD 밖에서 보인 것: 이슈 본문의 검증 명령이 `spikes/web-limits`를 가리킨다(이 폴더는 `spikes/webxr`). 이슈 본문은 고치지 않았다.
