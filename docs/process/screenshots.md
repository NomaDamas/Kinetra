# 화면 스크린샷 잡 (P0-04d)

화면을 바꾸는 PR의 증거를 사람이 직접 찍지 않게 한다. `screenshots` 워크플로(`.github/workflows/screenshots.yml`)가 PR마다 지정한 HTML 페이지를 헤드리스 Chromium으로 찍어 Actions 아티팩트 `screenshots`로 올린다. 같은 잡이 WebGL이 헤드리스에서 그려진다는 것을 빈 장면의 **픽셀**로 확인한다.

## 찍을 페이지 목록: `.github/screenshots.json`

```json
{ "viewport": { "width": 1280, "height": 800 },
  "screens": [ { "name": "design-system", "path": "design/exports/design-system/index.html", "fullPage": true } ] }
```

- `name`: 파일 이름이 된다(`out/screenshots/<name>.png`). `[A-Za-z0-9][\w.-]*`, 중복 금지.
- `path`: 저장소 기준 상대 경로의 `.html`. `..`, 절대 경로, 심볼릭 링크로 저장소 밖을 가리키는 것은 거부(설정 오류 또는 건너뜀).
- `fullPage`(기본 false) 또는 `selector`(그 요소만) 중 하나. 둘을 같이 못 쓴다.
- **없는 경로는 건너뛰고 로그에 `SKIP <name>: <path> (path not found)`를 남긴다.** 그래서 아직 머지되지 않은 화면(`packages/ui/preview/index.html`, `design/exports/_impl/index.html`)을 미리 적어 둘 수 있다. 하나도 못 찍으면(전부 없음 또는 실패) 잡이 실패한다. 찍기로 한 페이지가 오류로 못 열리면 실패한다.
- 화면을 추가하는 PR은 이 파일에 한 줄을 더한다.

네트워크는 막는다(`http(s)`, WebSocket 중단). 페이지는 로컬 파일만으로 그려지므로 같은 입력은 같은 픽셀이다. 웹 폰트는 시스템 글꼴로 대체된다. 애니메이션과 전환은 끈다.

## 결과 받기

PR의 Actions → `screenshots` 실행 → Artifacts: `screenshots`(PNG들과 `manifest.json`: 이름, 경로, 크기, 바이트, sha256, 건너뜀 사유, 페이지 오류), `webgl`(WebGL 확인 PNG와 `webgl-result.json`, 플래그 탐색 결과). 보관 14일. CLI: `gh run download <run-id> -n screenshots`.

## WebGL 헤드리스 확인

`tools/screenshots/webgl-empty/index.html`: 라이브러리 없는 순수 WebGL. 클리어 색 rgb(26,102,204)에 빨간 삼각형 하나(클립 좌표 (-0.8,-0.8) (0.8,-0.8) (0,0.8)). `tools/screenshots/webgl-check.ts`가 캔버스를 찍어 아래 픽셀을 단언한다. "컨텍스트가 만들어졌다"만으로 통과하지 않는다.

| 단언 | 값 |
|---|---|
| 캔버스 크기 | 256×256 |
| 왼쪽 위 픽셀과 오른쪽 위 픽셀(삼각형 밖) | 클리어 색 ±2, 알파 255 |
| 삼각형 안쪽 픽셀 | 빨강(255,0,0) ±2 |
| 빨간 픽셀 수 | 이론 면적 0.5·(0.8·256)² = 20,972의 ±3% |

단언 자체는 합성 이미지로 오프라인 시험한다(`test/webgl-pixels.test.ts`): 흰색/검은색/투명 빈 캔버스, 삼각형 없는 클리어 색, 다른 색 삼각형, 절반 크기 삼각형은 모두 실패한다.

**필요한 브라우저 플래그: 없음.** Playwright 1.65.0의 `chromium-headless-shell` 158.0.8127.18은 플래그 없이 WebGL을 SwiftShader(ANGLE, Vulkan, 소프트웨어)로 그린다. `webgl --probe`가 네 플래그 묶음(없음, `--use-angle=swiftshader`, `+ --enable-unsafe-swiftshader`, `--use-gl=angle` 포함)을 모두 시험해 출력한다. 측정 결과는 PR 본문과 CI 실행 기록에 있다. 워크플로가 쓰는 묶음은 `webgl-check.ts`의 `WEBGL_FLAGS`다. 플래그가 필요한 러너 이미지가 나오면 그 상수와 이 절만 바꾼다.

## 로컬 실행

브라우저를 띄우는 실행은 무거운 실행이다(`docs/process/dev-resources.md`). 가드 밖에서 시작하면 종료 코드 3으로 거절한다(`CI=true`일 때만 통과).

```bash
pnpm --filter @kinetra/screenshots exec playwright-core install chromium-headless-shell   # 한 번
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/screenshots capture
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/screenshots webgl [--probe]
uv run python tools/dev/resource_guard.py --profile heavy -- pnpm --filter @kinetra/screenshots test:browser
pnpm --filter @kinetra/screenshots test          # 오프라인(브라우저 없음). web 잡의 `pnpm test`가 돈다
```

범위 밖: 배포 파이프라인, 스크린샷 비교(대조는 `tools/design`, `docs/process/design-workflow.md`).
