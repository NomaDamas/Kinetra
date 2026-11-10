# REA로 우리 빌드 점검 1건 (A0-06b, #57)

대목표 G1 · 핵심 가치 V5(깨끗한 출처). 이 기록이 없으면 REA를 허용 범위 안에서 실제로 돌려 본 증거가 없고, 경쟁 제품 연구가 법적 위험이 되거나 아예 못 하게 된다.

수칙은 `docs/process/rea-policy.md`, 허용 목록은 `tools/rea/allowlist.txt`. 이 문서의 값 배지: `시뮬`은 쓰지 않았고, `측정`(이 실행에서 REA 또는 `python3`가 낸 값), `인용`(REA 공식 문서·패키지), `추정`(해석, 부하가 큰 머신의 시간).

## 1. 결론

- **REA 6.8.0(MIT)을 임시 폴더에서 설치해 우리 산출물 한 개를 점검했다.** 저장소 의존성으로 들이지 않았다(원장 행 없음, 3절).
- 대상은 `design/exports/design-system/index.html`(297,023바이트, 갤러리 한 파일)이다. `apps/studio`와 `packages/ui`에는 아직 소스도 빌드 출력도 없고(`package.json`만 있다), main에서 실제로 열리는 웹 산출물은 이 파일뿐이다.
- 점검한 것: 번들 구성(정적, `analyze-web-bundle`, `analyze-javascript-application`, `inspect-web-page`)과 런타임 동작(네트워크 요청, 스크립트, 저장소, 선언한 클릭 동작 `capture-browser-scenario`).
- **이 점검이 찾은 것:** (1) 파일은 인라인 스타일이 절반 이상(52.6 %)이고 색은 토큰 변수가 아니라 16진수로 박혀 있다(`var(--kin-…)` 11회 대 인라인 16진 색 1,562회). (2) 열 때 외부로 요청 2건(Google Fonts CSS와 글꼴 woff2)이 나간다. 갤러리 README가 적은 내용과 같고 REA의 네트워크 관찰이 이를 확인했다. (3) 저장소·콘솔·워커·소스맵 활동은 없다.
- 한계는 6절이다. 실제 `apps/studio` 번들이 아니므로 "우리 웹 번들 점검"의 첫 사례일 뿐이다.

## 2. 대상과 허용 근거

| 항목 | 값 |
|---|---|
| 대상 | `design/exports/design-system/index.html` (우리 저장소, D0-02c 내보내기). sha256 `42184fee52a5c2937d28f5568b15bc2f7ab0a6f2853649e53a63206df0021237` |
| 허용 목록 줄 | `allow \| own-build \| apps/studio (웹 번들 산출물 …) \| own` |
| 편차 | 줄의 대상 문구는 `apps/studio`다. 그 폴더에는 아직 빌드 출력이 없어서, 같은 줄의 취지("우리 저장소에서 우리가 만든 산출물, 번들 크기·구성, 런타임 동작")에 드는 우리 산출물 중 실제로 열리는 것을 골랐다. 이 파일은 Claude Design이 만든 산출물을 omp가 그대로 복사한 것이다(`design/exports/design-system/README.md`). **허용 목록에 `design/exports/**`를 더했다(창업자 승인 2026-11-10 (#410 코멘트)).** 이 점검은 그 줄이 생기기 전에 시작했고, 변경은 같은 브랜치의 별도 커밋이다(`rea-policy.md` "허용 목록 변경 절차") |
| 번들 속 서드파티 | 글꼴 JetBrains Mono(SIL OFL 1.1, 브리프 3.4절)를 브라우저가 Google Fonts에서 받는다. REA는 이를 **관찰만** 했다(요청 기록). 그 내용(글꼴 CSS·파일)을 분석하거나 저장소에 옮기지 않았다 |
| 금지 행위 | 독점 제품이 아니다. 디컴파일·에셋 추출·DRM 우회 없음. 결과 JSON은 저장소에 올리지 않았다(임시 폴더에서 삭제) |
| 브라우저 | 사람이 쓰는 Chrome은 건드리지 않았다. Playwright 설치본 `chromium_headless_shell-1254`(HeadlessChrome 158.0.8127.18)만 썼고 DevTools 포트는 `127.0.0.1`, 프로필은 던지는 `--user-data-dir`(끝나고 삭제), 대상 서버는 `127.0.0.1`의 `python3 -m http.server` |

## 3. REA 확인과 설치

| 항목 | 값 | 출처 |
|---|---|---|
| 공식 출처 | https://github.com/morluto/rea, npm `rea-agents` | `인용`: README의 "Get REA from" |
| 라이선스 | MIT(저장소 LICENSE, npm 메타데이터 `license = MIT`, 패키지 안 `LICENSE`) | `측정`: `npm view rea-agents license` |
| 배포본 | `rea-agents@6.8.0`, 압축 해제 49.3 MB, 파일 2,398개, 직접 의존 약 40개(`playwright-core`, `ws`, `zod`, `@babel/parser` 등) | `측정`: `npm view` |
| 서드파티 고지 | 패키지가 `THIRD_PARTY_NOTICES.md`와 `licenses/`를 싣는다. 선택 의존 `frida`는 LGPL-2.0 WITH WxWindows-exception-3.1로 적혀 있고 설치돼 있었다. 우리는 REA를 재배포하지 않고 연구용으로 실행만 했다 | `인용`: `THIRD_PARTY_NOTICES.md` |
| 무게 | 설치 후 `node_modules` 164 MiB, npm 캐시(`~/.npm/_cacache`) 163 MiB(다른 설치분 포함) | `측정`: `du` |
| 요구 Node | `^22.23.4 \|\| ^24.22.1 \|\| >=26.12.1`. 이 머신은 v22.22.2(npm 10.9.7)라 `EBADENGINE` 경고가 났고 `rea doctor`의 `node` 검사는 실패로 나왔다. 그럼에도 아래 명령은 모두 동작했다. 요구 버전 미만에서의 동작은 보증되지 않는다 | `측정` |
| 무겁지 않은가 | 네이티브 분석 엔진(Hopper, Ghidra, IDA)은 웹 점검에 필요 없다(`doctor`가 모두 `missing_analysis_engine`으로 보고했고 쓰지 않았다). 무거운 설치가 아니라서 중단 조건에 걸리지 않았다 | `측정`, `인용`: README "What you can analyze" |

설치 명령(임시 폴더 `/tmp/rea-probe`, 저장소 밖, 자원 가드 아래, 2026-11-10):

```bash
uv run python tools/dev/resource_guard.py --profile heavy -- sh -c \
  'cd /tmp/rea-probe && npm init -y >/dev/null && npm install --no-audit --no-fund --ignore-scripts rea-agents@6.8.0'
```

`--ignore-scripts`로 설치 스크립트는 돌리지 않았다. **`rea setup`(에이전트 설정에 MCP 서버를 등록하는 단계)은 하지 않았다.** 에이전트 설정 파일을 건드리지 않으려는 것이고, 점검은 CLI(`npx rea …`)로 했다.

| 항목 | 전 | 후 | 변화 | 실행 중 최악 |
|---|---|---|---|---|
| SSD 여유 GiB | 15.91 | 15.35 | −0.55 | 15.35 |
| 스왑 사용 GiB | 15.68 | 15.68 | +0.00 | 15.68 |
| 스왑 사용률 % | 92.2 | 92.2 | +0.0 | |
| 메모리 압력 | normal | normal | | |

가드 `통과(경고 있음: 스왑 사용률 92.2 %)`, 임계 배지 `기본값`, 프로필 `heavy`, 18.5초, 종료 코드 0.

**원장:** REA는 저장소 의존성이 아니라 임시 폴더에서만 쓴 도구다. `package.json`, `uv.lock`, `pnpm-lock.yaml`을 건드리지 않았으므로 `assets/LEDGER.csv`에 행을 더하지 않았고 `CREDITS.md`도 그대로다(`rea-policy.md`: "새 의존성이 되는 경우" 원장). 저장소 의존성으로 승격하려면 `dependency` 행과 `CREDITS.md` 재생성이 필요하다.

## 4. 한 일과 결과

CLI는 모두 `/tmp/rea-probe`에서 `npx rea …`로 돌렸다. 대상 페이지는 `http://127.0.0.1:8765/index.html`(저장소의 `design/exports/design-system/`을 루프백으로 서빙).

### 4.1 번들 구성

| 명령 | 결과 (`측정`) |
|---|---|
| `rea list-browser-targets http://127.0.0.1:9333 --allowed-origins http://127.0.0.1:8765` | 대상 페이지 1개 확인. (`--allowed-origins`는 JSON 배열이 아니라 원점 문자열 하나로 받는다. 배열로 주면 `invalid_value`) |
| `rea analyze-web-bundle … --observation-ms 1500 --format json` | 스크립트 관찰 1, 분석 1, 분석 완결(`completeness.status = complete`), 파싱 실패 0, 방문한 AST 노드 395. 라우트 0, 엔드포인트 후보 0, 청크 간선 0, 소스맵 `not_requested`, WebMCP 선언 0. 스크립트 소스 아티팩트 2,143바이트(`text/javascript`, utf-8) |
| `rea analyze-javascript-application <index.html만 복사한 폴더>` | 관련 파일 1, 읽은 텍스트 297,023바이트, 모듈 0, 파싱된 JavaScript 파일 0(HTML 한 파일이라 REA가 JS 모듈로 보지 않음), 무결성 모순 0, 한계 7개. 이 명령은 번들이 아니라 파일 구성을 보는 용도라 이 대상에서는 정보가 거의 없다 |
| `python3`로 직접 센 구성 | 아래 표. REA 출력이 아니라 HTML 텍스트를 정규식으로 센 값이다 |

`index.html`의 구성(`측정`, `python3` 정규식, 바이트는 UTF-8):

| 구성 | 개수 | 바이트 | 전체 대비 |
|---|---|---|---|
| 전체 | | 297,023 | 100 % |
| 인라인 `style="…"` 속성 | 1,759 | 156,224 | 52.6 % |
| 인라인 `<svg>` | 220 | 46,836 | 15.8 % |
| `<style>` 블록(`:root` 토큰 변수 75개) | 1 | 4,953 | 1.7 % |
| `<script>`(모드 전환기 동작) | 1 | 2,143 | 0.7 % |
| `<img>` 또는 `data:` URI | 0 | 0 | 0 % |

- 토큰 변수 `var(--kin-…)` 사용은 11회뿐이고, 인라인 스타일 속의 16진 색은 1,562회다. 갤러리의 아트보드가 토큰을 변수로 참조하지 않고 값을 복사했다는 뜻이다. D0-02d가 이 파일을 컴포넌트로 옮길 때 토큰 참조로 바꿔야 한다는 근거다(`추정`: 해석. 원인은 확인하지 않았다).
- DOM(`inspect-web-page`, 2초 관찰): 노드 4,612개(텍스트 2,151, `div` 769, `span` 695, `path` 221, `svg` 220, `button` 218, `h2` 56, `section` 49, `input` 26 …), 접근성 노드 4,466개. 아트보드는 `section` 49개, `role="tab"` 10개와 `role="tablist"` 2개가 있다.

### 4.2 런타임 동작

| 관찰 | 결과 (`측정`) |
|---|---|
| 네트워크(`capture-browser-scenario`, 런치 모드) | 요청 3건, 모두 200: ① 문서 `http://127.0.0.1:8765/index.html`, ② 스타일시트 `https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap`, ③ 글꼴 `https://fonts.gstatic.com/s/jetbrainsmono/v24/….woff2`. 외부로 나가는 요청이 2건이다. Pretendard는 어떤 경로로도 요청되지 않았다(README와 일치) |
| 스크립트 | 1개, 길이 2,113자, 모듈 아님, 소스맵 URL 없음 |
| 저장소 | 사용량 0 바이트, `localStorage`·`sessionStorage`·IndexedDB·캐시 이름 모두 0(값은 REA가 가린다) |
| 콘솔·워커·웹소켓 | 콘솔 이벤트 0, 워커 0, 웹소켓 연결 0(2초 관찰) |
| 선언한 동작 | 시나리오 한 건: 모드 목록이 보일 때까지 대기 → 두 번째 탭 클릭 → 0.5초 대기. 세 단계 모두 `completed`(각 39 ms, 120 ms, 504 ms), 시나리오 시작 `goto`는 2.9초 `[추정]`(부하) |
| 관찰의 완전성 | 네트워크를 켠 실행에서 REA가 `completeness.status = incomplete`, `missing_sections = [events]`로 표시했다(이유는 출력이 설명하지 않아 모른다 [확인 필요]). 네트워크를 켜지 않은 실행은 `complete`였다 |

**클릭의 효과(탭 선택 상태가 바뀌었는지)는 이 실행으로 확인하지 못했다.** 단계 기록은 "선언한 동작이 수행됐다"만 말한다. 단계별 DOM·접근성 캡처 옵션을 시도했지만 입력 계약이 받지 않아(`unknown_argument`) 넣지 못했고, 대신 `aria-selected`를 기다리는 `wait_for`를 더하는 방법은 쓰지 않았다.

### 4.3 막힌 곳과 REA의 입력 계약 (다음 사람을 위해)

- 첫 클릭 시나리오는 `[role=tab]` 선택자가 9개 요소에 걸려 REA(Playwright)가 strict mode 위반으로 `failed`로 기록했다. 내 선택자 실수다. 고유 선택자(`[data-live=mode] [role=tab]:nth-of-type(2)`)로 고쳤다. REA는 실패한 단계 뒤의 단계를 `cancelled`로 기록하고 실행 전체를 `incomplete`로 표시했다. 즉 실패가 조용히 묻히지 않는다.
- `capture-browser-scenario` 입력: `{browser:{mode:"launch",executable_path}, start_url:{url}, capture:{network:{…}}, actions:[{step_id, action, locator:{kind:"css",selector}, timeout_ms …}]}`. `wait_for_timeout`은 `timeout_ms`가 아니라 `duration_ms`다. 도움말(`--help`)과 `--schema`는 입력 JSON 내부를 설명하지 않는다. 계약은 REA의 오류 메시지와 `skills/reverse-engineer-anything/references/*.md`에서 알아냈다.
- `analyze-web-bundle --detail summary`는 `--evidence_output`이 필수이고 `--view`도 요구했다. 단순히 `--detail complete`(기본)로 돌리는 편이 낫다.

## 5. 재현

```bash
# 설치(3절). 저장소 밖에서만.
REPO=$(git rev-parse --show-toplevel)     # 저장소 안에서 먼저 한 번 실행해 둔다
# 대상 서버와 브라우저(루프백, 던지는 프로필)
(cd "$REPO/design/exports/design-system" && python3 -m http.server 8765 --bind 127.0.0.1) &
"$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1254/chrome-headless-shell-mac-arm64/chrome-headless-shell" \
  --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1 \
  --user-data-dir=/tmp/rea-chrome-profile --no-first-run about:blank &
curl -s -X PUT "http://127.0.0.1:9333/json/new?http://127.0.0.1:8765/index.html"   # 대상 탭 만들기
# /tmp/rea-probe 에서
npx rea list-browser-targets http://127.0.0.1:9333 --allowed-origins http://127.0.0.1:8765 --format json
npx rea analyze-web-bundle http://127.0.0.1:9333 <targetId> --allowed-origins http://127.0.0.1:8765 --observation-ms 1500 --format json
npx rea inspect-web-page   http://127.0.0.1:9333 <targetId> --allowed-origins http://127.0.0.1:8765 --observation-ms 2000 --format json
# 시나리오: $REPO/docs/research/rea/own-build-scenario.json. executable_path 자리표시자는 임시 사본에서 바꾼다(저장소 파일은 그대로).
# 4.2절의 요청 3건은 이 파일(네트워크 캡처 켬)의 결과다. `capture` 키를 지우면 4.2절의 "단계 3개 completed, 완결" 실행이 된다.
CHROME="$HOME/Library/Caches/ms-playwright/chromium_headless_shell-1254/chrome-headless-shell-mac-arm64/chrome-headless-shell"
python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); d["browser"]["executable_path"]=sys.argv[2]; json.dump(d,open(sys.argv[3],"w"))' \
  "$REPO/docs/research/rea/own-build-scenario.json" "$CHROME" /tmp/rea-scenario.json
npx rea capture-browser-scenario /tmp/rea-scenario.json --format json
npx rea analyze-javascript-application <index.html만 복사한 폴더> --format json
```

결과 JSON(`page.json` 1.1 MB 등)은 저장소에 올리지 않았고 끝난 뒤 지웠다(경로가 이 머신의 임시 폴더이고 DOM 전체가 들어 있어서 크다). 이 문서의 모든 수치는 위 명령의 출력과 같은 날 센 값이다. 난수가 없어 시드는 없다.

머신: Apple M2 Pro, macOS 15.6.1(Darwin 24.6.0), Node v22.22.2, npm 10.9.7, Python 3.10.11(구성 계산용), rea-agents 6.8.0, HeadlessChrome 158.0.8127.18. 부하는 이 실행 중에는 재지 않았다. 같은 날 앞선 측정에서 부하 평균이 100대였으므로 시간(ms, 초)은 `추정`이다.

## 6. 한계

- 대상이 `apps/studio`의 빌드 출력이 아니라 정적 갤러리 HTML 한 파일이다. 번들러 출력(청크, 소스맵, 라우트)을 점검한 것이 아니다. `apps/studio`에 빌드가 생기면(S1) 같은 명령으로 다시 점검해야 하고, 그때는 청크 간선·소스맵·번들 크기 추이를 볼 수 있다.
- 스크립트가 1개(2,143바이트)라 REA의 JavaScript 분석(AST 395 노드)은 거의 비어 있다. 이 점검의 가치는 구성(HTML·CSS·SVG 비중)과 런타임 요청 확인이다.
- 클릭 효과는 확인하지 못했다(4.2절). 네트워크 캡처의 `incomplete` 이유도 모른다.
- Node 22.22.2는 REA의 지원 하한(22.23.4) 미만이다. 이 점검의 모든 명령은 동작했지만 지원 범위 밖의 환경이다.
- REA의 CLI 입력 계약이 도움말에 충분히 적혀 있지 않아 시행착오가 있었다. 에이전트가 MCP로 쓰면 스키마가 노출될 수 있으나 이 점검은 MCP를 쓰지 않았다 [확인 필요].
- 이 문서는 법률 자문이 아니다. 상표·특허와 표현의 경계는 [확인 필요]다.

## 7. 이월

- `apps/studio`의 첫 빌드 출력이 생기면 이 점검을 되풀이한다(S1, 새 이슈로). 허용 목록 줄의 대상 문구를 "디자인 시스템 내보내기 등 우리 저장소의 웹 산출물"까지 넓힐지는 창업자가 정한다.
- 갤러리의 인라인 색 대 토큰 변수 문제는 D0-02d(#34)의 입력으로 알린다.
