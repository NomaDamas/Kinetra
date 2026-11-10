# Kinetra Studio 디자인 시스템 내보내기 (D0-02c)

**상태: 창업자 승인 대기.** 이 폴더의 값은 모두 **[제안]**이다(값 배지로는 `기본값`). 승인 코멘트가 #33에 달리기 전에는 승인본이 아니다. 승인 뒤에만 D0-02d, D0-03, D1이 이 폴더를 참조한다.

## 출처

- 규격(브리프): `design/briefs/design-system.md` (3절 토큰, 4절 값 배지 5종, 5절 증거 4단계, 6~8절 컴포넌트·상태·접근성, 11절 `/design` 프롬프트).
- Claude Design 산출물 URL: https://claude.ai/artifact/74qVFnKdAiuXfXJTkHSPKR (제목 "Kinetra Studio 디자인 시스템"). 같은 세션 로그의 `https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd`는 새 산출물을 만들 때 읽은 Artifact 유형 안내("from Artifact type")이며 디자인 산출물이 아니다 [추정: 로그 문구 기준].
- 만든 방법: omp가 expect 스크립트로 대화형 `claude`(Claude Code 2.1.322, 모델 Fable 5.2)를 PTY에 띄워 `/design`을 두 번(`/design …`, `claude --continue`) 실행했다. 자세한 기록은 `docs/decisions/design-pty.md`. **D0-02b의 DoD는 "창업자가 만들었다"인데 실제로는 omp가 만들었다.** 이 편차의 수용 여부는 창업자가 정한다.
- 내보내기는 Claude Design이 저장소로 쓰지 않아서(문제 3) Claude Code scratchpad에서 omp가 그대로 복사했다. 파일 내용은 고치지 않았다. 날짜 2026-11-10.

## 파일

| 경로 | 내용 |
|---|---|
| `index.html` | 독립 갤러리 한 파일(296,982바이트). 아트보드 11장을 이어 붙였고 `tokens.css`가 인라인돼 있다. 브라우저에서 바로 열린다 |
| `tokens.json` | 토큰. 키는 규격의 토큰 이름(`color.bg.app`). 값은 모두 [제안] |
| `tokens.css` | 같은 토큰의 CSS 변수(`--kin-color-bg-app`). 점을 하이픈으로 바꾸고 `--kin-` 접두를 붙였다 |
| `source/*.dc.html` | Claude Design 캔버스 형식의 아트보드 원본 11개: `Main`(색), `Tokens-Scale`(타이포·간격·모서리·높이·모션), `ValueBadges`(배지 5종), `Evidence`(증거 4단계), `Controls`, `Inspector`, `ChangeCard`, `VerdictCards`, `AgentBar`, `States`(상태 4종), `A11y` |
| `source/canvas.json` | 아트보드 위치·크기·제목·순서 |
| `source/tools/build_export.py` | Claude Design이 쓴 내보내기 스크립트. `python3 build_export.py <project_dir> <out_dir>` (`project_dir`에 `*.dc.html`, `canvas.json`, `tokens.css`가 있어야 한다) |
| `preview.png` | `index.html`을 헤드리스 Chrome(임시 `--user-data-dir`, 끝나고 삭제)으로 1440×2400에서 찍은 스크린샷. 맨 위 약 2400px(색, 증거 강도 스케일, 값 배지, 타이포그래피, 간격, 크기, 모서리, 높이)만 보인다 |

## 글꼴: 파일은 들어 있지 않다

- 글꼴 파일(woff 등)은 어디에도 포함돼 있지 않다. `index.html`과 `tokens.css`는 글꼴을 **이름으로만** 부른다: UI `Pretendard`(→ `Pretendard Variable`, 시스템 한글 글꼴 순), 수치·코드 `JetBrains Mono`. 둘 다 SIL OFL 1.1이다(브리프 3.4절의 제안).
- Pretendard는 어떤 경로로도 불러오지 않는다. 설치돼 있을 때만 쓰이고 아니면 시스템 글꼴로 바뀐다(갤러리 하단에도 그렇게 적혀 있다).
- JetBrains Mono는 `index.html`의 `<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono…">`로 **Google Fonts에서 받는다.** 오프라인이면 `monospace`로 바뀐다. 이 요청은 갤러리를 열 때 외부로 나간다. 앱에서는 쓰지 않고 자체 호스팅 파일을 원장에 올리는 것이 D0-02d(#34)와 P0-05의 몫이다(브리프 3.4절).
- 따라서 이 PR은 에셋 원장(`assets/LEDGER.csv`) 행을 더하지 않는다. `uv run python scripts/check_assets.py`는 `assets/`와 `apps/**/public/`만 보고(`design/`은 범위 밖), 실행 결과는 `ok: 에셋 행 0, 의존성 행 3, 에셋 파일 0 … CREDITS.md 일치`였다.

## 알려진 불일치 (고치지 않고 적는다)

- `source/`의 `Tokens-Scale`, `Inspector`, `AgentBar` 세 파일은 루트 높이(1160, 980, 900px)가 `canvas.json`의 높이(1100, 920, 840)와 다르다. 그래서 `build_export.py`는 이 `source/`로는 `assert`에서 멈춘다. `index.html`은 `canvas.json`의 높이(min-height 1100, 920, 840)로 만들어진 상태 그대로다. `index.html`이 승인 대상이고, 원본에서 다시 만드는 일은 아직 안 된다. 후속 이슈 #395.
- 값(색, 크기 등)은 Claude Design이 계산했다고 갤러리에 적은 대비 수치를 포함한다. omp는 그 수치를 다시 계산하지 않았다.
