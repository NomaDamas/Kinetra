# 결정: omp가 PTY로 Claude Design(`/design`)을 구동할 수 있는가 (D0-01b)

- 상태: **가능 (조건부)**. 관찰일 2026-11-10.
- 결정권자: 창업자. 기록: omp.
- 대목표·핵심 가치: G0 / V3 한 번에 100%. 이 판정이 없으면 화면 구현 이슈가 참조할 승인된 디자인을 누가 어떻게 만드는지 정해지지 않는다(`docs/plan/studio-plan.md` 7절은 이 칸을 [확인 필요]로 남겼다).

## 판정

omp는 expect 스크립트로 대화형 `claude`를 PTY에 띄워 `/design`을 실제로 실행하고, 브리프(`design/briefs/design-system.md`)에서 디자인 산출물을 만들어 낼 수 있다. 증거는 아래 "시도와 결과"의 두 번의 실행이다. 다만 **조건부**다. 그대로 두면 다음 다섯 문제가 다시 생기므로 "다음에 omp가 따를 운영 절차"를 표준으로 삼는다. 창업자 승인과 `/design-sync` 왕복은 omp가 대신하지 않는다("창업자에게 남는 것").

## 환경 (관찰)

- Claude Code 2.1.322, Ultra 플랜, 모델 Fable 5.2(상태 막대 표시).
- `/design`, `/design-login`, `/design-sync`는 대화형 `claude`에만 있다. 헤드리스 `claude -p`에는 없다(#29 코멘트에 먼저 기록). PTY 시작 직후 `/desig`까지 입력하면 자동완성에 세 명령이 뜬다: `/design`(브리프에서 새 Design 산출물 만들기), `/design-sync`(디자인 시스템 컴포넌트를 claude.ai/design으로 보내기), `/design-login`(`/design-sync`용 claude.ai 계정 인증).

## 시도와 결과

구동기는 expect 스크립트다. 작업 폴더는 `/tmp/kin-design-probe`(신뢰 대화상자를 한 번 통과시킨 폴더. `design/briefs/design-system.md`를 복사해 둠). 스크립트 본문의 핵심 줄만 옮긴다. 로그는 `/tmp/kin-design-run.log`, `/tmp/kin-design-cont.log`다.

### 0. 탐침: 명령이 있는가 (`probe.exp`)

```tcl
spawn -noecho claude
expect -re "trust this folder"     ;# 신뢰 대화상자
sleep 2; send "\033OB"; sleep 1; send "\r"   ;# 아래 화살표 → "Yes, I trust this folder"
expect -timeout 15 -re "(Try|for shortcuts|>)" {}
send "/desig"; sleep 5             ;# 자동완성 목록을 로그에 남긴다
send "\003"; send "\003"           ;# Ctrl-C 두 번으로 종료
```

결과: 자동완성에 `/design`, `/design-sync`, `/design-login`이 나타났다.

### 1. 실행 (`run.exp`)

```tcl
spawn -noecho claude
expect { -re "trust this folder" { sleep 3; send "\033OB"; sleep 2; send "\r"; exp_continue }
         -re "for shortcuts|Try \"" {} }
send "/design Create the Kinetra Studio design system exactly as specified in design/briefs/design-system.md (use the section 11 prompt block). Produce a design artifact I can export."
send "\r"
set timeout 420                    ;# ← 고정 시간 제한 (문제 2)
expect { -re "Do you want to|❯ 1\\. Yes" { sleep 1; send "\r"; exp_continue } timeout {} eof {} }
catch { send "\003" }; catch { send "\003" }
```

결과: Claude Design이 브리프를 읽고, 팔레트의 WCAG 대비를 파이썬 조각으로 계산하고, 산출물 "Kinetra Studio 디자인 시스템"(https://claude.ai/artifact/74qVFnKdAiuXfXJTkHSPKR)을 만들고, 갤러리 아트보드 11장을 캔버스에 올리기 시작했다. 세션 비용 표시는 1분 $0.28, 6분 $1.96, 8분 $2.57. 주간 한도 표시는 "42% left". 420초 제한에서 Ctrl-C로 끊겼다.

### 2. 이어서 실행 (`cont.exp`, `claude --continue`)

```tcl
spawn -noecho claude --continue
expect -re "for shortcuts|Try \"|❯" {}
send "Continue the Kinetra Studio design system artifact you started: finish all gallery artboards from section 11 of design/briefs/design-system.md, then run the self-check list in that section and fix anything that fails. When done, export the design as standalone HTML and save the export files into ./design/exports/design-system/ (create the folder), plus a short ./design/exports/design-system/NOTES.md listing the artifact URL, artboards, and any self-check items that could not be met."
send "\r"
set timeout 1500                   ;# ← 이번에도 고정 시간 제한 (문제 2)
expect { -re "Do you want to|❯ 1\\. Yes" { sleep 1; send "\r"; exp_continue } timeout {} eof {} }
```

결과: 아트보드 11장을 모두 올렸다. 자가 점검에서 갤러리를 독립 HTML로 만드는 자체 스크립트(`tools/build_export.py`)를 쓰고, 설치된 Google Chrome을 헤드리스로 띄워 아트보드마다 자연 높이를 쟀다(모두 `overflowX 0`). 접근성 아트보드를 고쳤다. 주간 한도 표시는 실행 중 omp가 75%→79% 사용으로 읽었다(저장된 로그에서는 재확인하지 못했다. 로그 발췌 참고). 1500초 동안 프롬프트가 다시 나오지 않아 expect 제한에서 끊겼고, **`./design/exports/`는 만들어지지 않았다.** 이 실행의 총 경과 시간은 약 49분이다(끊은 뒤의 멈춤 포함).

### 3. 산출물 회수

저장소에 내보내지 못했으므로 Claude Code의 scratchpad(`/private/tmp/claude-501/-private-tmp-kin-design-probe/<세션>/scratchpad/`)에서 회수했다.

- `kinetra-ds/project/`: `canvas.json`, `tokens.json`, `tokens.css`, 아트보드 11개 `*.dc.html`(Claude Design 캔버스 형식).
- `build/index.html`(296,982바이트, 독립 갤러리), `build/measure.json`.
- `tools/build_export.py`(Claude Design이 직접 쓴 내보내기 스크립트).

omp가 헤드리스 Chrome(임시 `--user-data-dir`)로 `index.html`을 1440×2400으로 찍어 확인했다. 색, 증거 단계(none, L0~L3), 값 배지 5종(`시뮬` `인용` `기본값` `사용자 선언` `추정`), 타이포·간격·크기·모서리·높이·모션이 보였고 값은 모두 [제안]으로 표시돼 있었다. 회수한 파일은 #33(D0-02c) PR이 `design/exports/design-system/`으로 반입한다.

### 로그 발췌 (비밀·세션 식별자 제외, 공백은 TUI 재그리기로 깨진 것을 복원)

```text
# /tmp/kin-design-run.log (1회차)
상태 막대: Fable 5.2 │ ctx 0% │ kin-design-probe │ $0.00 · 1m   Weekly 45% lft
⏺ Artifact(→ new artifact from type https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd)  ⎿ Created
   ⧉ https://claude.ai/artifact/74qVFnKdAiuXfXJTkHSPKR     (제목 "Kinetra Studio 디자인 시스템")
⏺ 브리프의 대비 수치가 계산과 맞는 것을 확인했고, 이제 캔버스에 갤러리 아트보드 11장을 차례로 올리겠습니다.
상태 막대: ctx 11% │ $2.57 · 8m   Weekly 42% left   Resets in 31m
(420초 expect 제한 → Ctrl-C)

# /tmp/kin-design-cont.log (2회차, claude --continue)
⎿ Interrupted · What should Claude do instead?       ← 1회차 끊김이 이어받은 세션 기록에 남아 있음
⏺ 11장을 모두 캔버스에 올렸고, 이제 자기 점검을 돌려 실패 항목을 고친 뒤 독립실행 HTML로 내보내겠습니다.
⏺ Building the standalone … measuring each artboard's natural height in headless Chrome
   $ CHROME="/…/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --hide-scrollbars --window-size=2000,1200 --virtual-time-budget=8000 --du…
상태 막대: $2.57 · 15m   Weekly 36% left   Resets in 23m
⏺ Making 1 scratchpad edit … /private/tmp/claude-501/-private-tmp-kin-design-probe/<세션>/scratchpad/kinetra-ds/project/tokens.json
상태 막대: $13.61 · 39m   Weekly 100% lft           ← 주간 한도 재설정 뒤
(1500초 expect 제한 → Ctrl-C; ./design/exports/ 는 만들어지지 않음)
```

- 이 로그의 주간 한도 값은 42% left → 36% left → (재설정 뒤) 100%다. 앞 절의 "75→79%" 읽기는 omp가 실행 중에 직접 읽어 기록한 값이며 저장된 로그에서는 재확인하지 못했다. 로그에서는 한도가 중간에 재설정돼 실행 전후 차이를 하나로 셀 수 없다.
- 로그 명령 줄은 `--user-data-dir`가 보이는 위치(잘림 전)에서 확인되지 않았다. 문제 5는 이 때문에 "지시가 없었다"는 사실만 주장한다.

## 발견한 문제 5가지

| # | 문제 | 관찰 |
|---|---|---|
| 1 | 신뢰 대화상자가 새 폴더를 막는다 | 처음 보는 폴더에서 "Is this a project you created or one you trust?"가 나오고 기본 선택이 "No, exit"다. 응답하지 않으면 진행되지 않는다 |
| 2 | 이번 스크립트는 완료 감지를 구현하지 않았다 | `run.exp`, `cont.exp`는 고정 제한(420초, 1500초)과 "Do you want to" 응답만 있고 완료 감지가 없다. 두 실행 모두 제한시간에 도달해 Ctrl-C로 끊겼다. 화면 문자열이나 다른 완료 신호가 믿을 만한지는 **미검증**이다 |
| 3 | 프로젝트로 내보내기가 일어나지 않았다 | 산출물은 scratchpad와 claude.ai 산출물에만 있었다. 내보내기 폴더는 만들어지지 않았다. `/design-sync`는 아직 실행하지 않았다 |
| 4 | 창업자의 주간 한도를 쓴다 | 2회차에서 omp가 읽은 값은 약 4포인트(75→79% 사용)이나 로그로 재확인하지 못했다. 세션 비용 표시는 $2.57에서 $13.61(39분 시점)로 올랐다. 주당 omp가 만들 수 있는 화면 수가 한도로 제한된다 [추정] |
| 5 | 임시 프로필 지시 없이 Chrome을 실행했다 | Claude Design이 설치된 Google Chrome을 헤드리스로 측정에 썼고, 로그에 보이는 명령 줄에는 `--user-data-dir`가 없다. 규칙이 막는 것은 창업자의 Chrome 프로필과 실행 중인 Chrome을 건드리는 일이다. 바이너리를 임시 프로필로 헤드리스 실행하는 것은 허용한다(omp의 스크린샷도 이렇게 찍었다). 이번 실행이 기본 프로필을 썼는지는 확인하지 못했다 |

## 다음에 omp가 따를 운영 절차 [제안]

1. **신뢰 폴더 준비.** 매번 새 폴더를 만들지 않고 이미 신뢰를 통과한 폴더(지금은 `/tmp/kin-design-probe`)를 재사용한다. 새 폴더를 쓰면 `run.exp`처럼 `trust this folder`를 기다렸다가 아래 화살표(`\033OB`)와 Enter로 "Yes, I trust this folder"를 고른다. 통과한 폴더는 `~/.claude.json`의 `projects.<경로>.hasTrustDialogAccepted`가 `true`로 남는 것을 확인했다. omp가 이 파일을 직접 고치지는 않는다. 작업 폴더에는 브리프를 `design/briefs/`로 복사해 둔다.
2. **완료는 출력 파일(완료 표식)로 판단한다.** 고정 `timeout`으로 끊지 않는다.
   - 실행 전에 이전 표식 `./design/exports/<이름>/DONE.json`을 지우거나 이름을 바꾼다(옛 표식이 완료로 오인되는 것을 막는다).
   - 구동기가 실행 id(예: `date +%Y%m%dT%H%M%S` 값)를 만들어 프롬프트에 넣는다: "모든 내보내기와 자가 점검이 끝난 **맨 마지막**에, 실행 id `<id>`를 담은 `DONE.json`을 쓴다. 그 전에는 쓰지 않는다."
   - 구동기는 expect 밖 별도 셸에서 `DONE.json`이 있고 그 안의 id가 이번 실행 id와 같은지, 표식에 적힌 파일이 모두 있는지 폴링한다. id가 다르면 완료로 치지 않는다.
   - 보조 신호는 입력 프롬프트(`❯ Try "…"`)가 다시 나타나는 것이다(미검증). 상한 시간은 두되 상한에 닿으면 끊지 않고 상태를 창업자 이슈에 보고한다.
3. **내보내기 위치를 명시한다.** 프롬프트에 "독립 HTML과 토큰 파일을 `./design/exports/<이름>/`에 저장하고, 사용한 `*.dc.html` 원본과 `canvas.json`은 `source/`에 둔다"를 쓴다. 이번처럼 지시를 한 번 더 이어서 줘야 하는 경우를 줄이려고 처음 프롬프트부터 쓴다. 파일이 없으면 scratchpad에서 회수하고 회수 경로를 PR 본문에 적는다.
4. **임시 브라우저 프로필을 지시한다.** 프롬프트에 "브라우저 측정은 임시 `--user-data-dir`(`/tmp` 아래, 끝나면 삭제)를 쓴 헤드리스 Chrome 또는 Chromium으로만 하고, 사용자의 Chrome 프로필이나 실행 중인 Chrome은 건드리지 않는다"를 쓴다. 이번 실행은 이 지시가 없었다. 지시를 따랐는지는 실행 로그의 명령 줄로 확인한다.
5. **주간 한도를 먼저 본다.** 시작 전에 상태 막대의 `Weekly … % left`를 읽어 로그에 남긴다. 남은 비율의 문턱은 창업자가 정한다(제안: 구현 작업이 쓸 몫을 남기도록 낮을 때는 시작하지 않고 이슈에 보고). 끝난 뒤 사용 포인트를 PR 본문에 적는다. 이번 관찰: 1회차 8분에 $2.57(한도 42% left), 2회차 약 49분에 실행 중 읽은 값 약 4포인트(재확인 불가), 세션 비용 표시 $13.61(39분 시점).
6. **끝낸 뒤 검증한다.** 내보낸 `index.html`을 임시 프로필의 헤드리스 Chrome으로 열어 스크린샷을 찍고, 브리프의 자가 점검 항목(배지 5종, 증거 4단계, 금지 문구)을 대조한다. 산출물의 값은 승인 전까지 [제안]이다.

## 창업자에게 남는 것

- **승인.** 디자인 승인본은 `docs/process/review-rubric.md`의 창업자 승인 대상이다. omp가 만든 산출물이라도 승인 코멘트는 창업자가 단다. 승인 전에는 이슈 DoD의 "승인 코멘트가 있다"를 채웠다고 말하지 않는다.
- **`/design-sync`와 `/design-login`.** 이번에는 실행하지 않았다. claude.ai 계정 인증을 포함하므로 D0-02d(#34)에서 한 번 실제로 돌려 보기 전까지는 창업자 몫으로 둔다. 돌려 본 뒤 이 문서를 고친다.
- **주간 한도의 문턱과 사용 허락.** 한도는 창업자의 계정 자원이다.
- 결과가 나쁘거나 위 절차로도 불안정하면 "불가"로 바꾸고 창업자 실행을 표준으로 확정한다(#29 DoD).

## 편차 기록: D0-02b를 omp가 실행했다 (창업자 수용 요청)

#32(D0-02b)의 DoD는 "창업자가 브리프로 디자인 시스템을 만들었다"다. 실제로는 **omp가 PTY로 `/design`을 실행해 만들었고 창업자가 만들지 않았다.** 이 스파이크의 시험 실행이 곧 D0-02b의 산출물이 됐기 때문이다. 이는 DoD 문구와 다르므로 창업자가 (a) 이 편차를 수용하고 #32를 닫을지, (b) 창업자가 직접 다시 만들지 정한다. 어느 쪽이든 디자인의 승인은 #33(D0-02c)에서 창업자가 한다. 이 편차는 PR #33 본문에도 적는다.

## 추가 관찰: D0-03a(SC-01) 실행, 분할 프롬프트와 모델 (2026-11-10)

위 운영 절차를 처음부터 끝까지 한 번 써 봤다. 두 번 실행했고 결과가 달랐다.

| | 1차 (실패) | 2차 (성공) |
|---|---|---|
| 시작 | `claude`(기본 모델), 입력 한 줄로 `/design <긴 지시>` 전송 | `claude --model fable`, 먼저 `/design`만 입력 → 자동완성에 "Make a new Design artifact from a brief"가 뜬 것을 확인 → 짧은 지시(브리프 파일 경로를 가리킴)를 이어 전송 |
| 상태 막대 모델 | Opus 5.5 | Fable 5.2 |
| `/design` 호출 | 안 됨. 모델이 "메시지가 문장 중간에서 시작한다"고 답함. `Artifact(` 줄 없음 | 됨. 로그에 `Artifact(` 줄과 claude.ai/artifact URL이 나옴(유형 안내를 읽는 호출, 그 뒤 새 산출물 호출) |
| 결과 | Claude Code가 빌드 스크립트로 직접 시안을 만듦(Claude Design 산출물 아님) | Claude Design 캔버스 아트보드 14장 + 독립 `index.html` |

- **분할 프롬프트가 필요하다.** 긴 한 줄을 붙여 넣으면 앞의 `/design `이 명령으로 처리되지 않았다(1차). 원인은 [추정]: 긴 입력이 붙여넣기로 처리되며 앞부분이 잘림. `/design`을 먼저 따로 보내 자동완성을 확인한 뒤 짧은 지시를 보내면 호출됐다(2차, 1회 관찰). 지시는 긴 브리프를 붙이지 않고 `design/briefs/<화면>.md` 경로를 가리킨다.
- **모델.** `~/.claude/settings.json`의 `model`이 `opus`이면 기본 세션은 Opus 5.5이고 그 세션에서는 `/design`이 호출되지 않았다(1차). `claude --model fable`은 Fable 5.2로 시작했다. 두 요인(모델, 분할 프롬프트)이 한꺼번에 바뀌었으므로 어느 쪽이 호출 성공의 원인인지는 이 두 번으로는 가를 수 없다 [미검증]. 둘 다 따르는 것을 표준으로 둔다.
- **주간 한도 읽기.** 상태 막대의 `Weekly … % left`는 세션을 띄운 직후에는 나오지 않았다. 세션이 1분쯤 되고 Ctrl-C를 한 번 보내면(종료되지 않고 "Press Ctrl-C again to exit"만 뜸) 나타났다. 구동기는 70초를 기다린 뒤 Ctrl-C 한 번으로 읽는다. 화면 로그에서는 빠른 갱신 때문에 글자가 끊겨, 구동기는 `([0-9]+)% l`로 읽는다.
- **완료 표식이 쓰이지 않았다.** 2차는 `NOTES.md`까지 쓴 뒤 상태 막대 아래에 "You're out of usage credits. Run /usage-credits to keep using Fable 5.2 or /model to switch models"가 나오며 멈췄고 `DONE.json`은 끝내 쓰이지 않았다(`DONE.json` 쓰기는 지시의 마지막 줄이었다). 구동기는 `DONE.json`이 없는 채 34분을 넘겼고 omp가 정지 파일로 끝냈다. 상한 75분에는 닿지 않았다. 내보낸 파일이 모두 있는지는 omp가 직접 확인했다(`index.html`, `source/*.dc.html` 14개와 `canvas.json`, `tools/build_export.py`, `NOTES.md`). 위 절차 2번(완료 표식)은 이번에는 완료 신호로 쓰이지 못했다. 이 메시지가 한도(주간) 소진인지 추가 사용 크레딧만 없다는 뜻인지는 구별하지 못했다 [미검증]. 같은 메시지가 1차 시작 직후에도 "Fast mode disabled · Out of usage credits"로 나왔다.
- **비용.** 2차는 3분에 $2.36, 33분에 $14.42, 35분에 $15.47(상태 막대). 주간 한도 표시는 시작 60% left, 끝 59% left였다. 1차는 18분에 $5.43, 70% → 65% left였다. 같은 계정에서 다른 세션도 돌고 있어 이 표시를 이번 실행만의 사용량으로 읽을 수 없다 [추정].
- **임시 브라우저 프로필.** 2차 `NOTES.md`는 `/tmp/kin-sc01-chrome.*` 임시 프로필을 쓰고 끝나고 지웠다고 적었다. 실행 뒤 그 경로는 남아 있지 않았다. 실행 중 명령 줄 자체는 화면 로그에서 확인하지 못했다.

## 이 문서의 한계

- 관찰은 한 머신, 한 계정, 한 브리프에서 두 번이다. 같은 절차가 다른 화면에서도 같은 비용으로 되는지는 모른다.
- 한도 사용량은 상태 막대 표시에서 읽은 값이며 청구 단위가 아니다.
- 위 운영 절차는 D0-03a(SC-01)에서 처음 끝까지 써 봤고 결과는 위 "추가 관찰"에 있다. 완료 표식(2번)은 아직 정상 종료로 검증되지 않았다.
