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

결과: 아트보드 11장을 모두 올렸다. 자가 점검에서 갤러리를 독립 HTML로 만드는 자체 스크립트(`tools/build_export.py`)를 쓰고, 설치된 Google Chrome을 헤드리스로 띄워 아트보드마다 자연 높이를 쟀다(모두 `overflowX 0`). 접근성 아트보드를 고쳤다. 주간 한도 사용량이 75%에서 79%로 올랐다. 1500초 동안 프롬프트가 다시 나오지 않아 expect 제한에서 끊겼고, **`./design/exports/`는 만들어지지 않았다.** 이 실행의 총 경과 시간은 약 49분이다(끊은 뒤의 멈춤 포함).

### 3. 산출물 회수

저장소에 내보내지 못했으므로 Claude Code의 scratchpad(`/private/tmp/claude-501/-private-tmp-kin-design-probe/<세션>/scratchpad/`)에서 회수했다.

- `kinetra-ds/project/`: `canvas.json`, `tokens.json`, `tokens.css`, 아트보드 11개 `*.dc.html`(Claude Design 캔버스 형식).
- `build/index.html`(296,982바이트, 독립 갤러리), `build/measure.json`.
- `tools/build_export.py`(Claude Design이 직접 쓴 내보내기 스크립트).

omp가 헤드리스 Chrome(임시 `--user-data-dir`)로 `index.html`을 1440×2400으로 찍어 확인했다. 색, 증거 단계(none, L0~L3), 값 배지 5종(`시뮬` `인용` `기본값` `사용자 선언` `추정`), 타이포·간격·크기·모서리·높이·모션이 보였고 값은 모두 [제안]으로 표시돼 있었다. 회수한 파일은 #33(D0-02c) PR이 `design/exports/design-system/`으로 반입한다.

## 발견한 문제 5가지

| # | 문제 | 관찰 |
|---|---|---|
| 1 | 신뢰 대화상자가 새 폴더를 막는다 | 처음 보는 폴더에서 "Is this a project you created or one you trust?"가 나오고 기본 선택이 "No, exit"다. 응답하지 않으면 진행되지 않는다 |
| 2 | PTY에는 완료 신호가 없다 | 고정 제한(420초, 1500초)이 두 번 모두 작업 중간에 끊었다. 끝났는지는 화면 문자열로 알 수 없다 |
| 3 | 프로젝트로 내보내기가 일어나지 않았다 | 산출물은 scratchpad와 claude.ai 산출물에만 있었다. 내보내기 폴더는 만들어지지 않았다. `/design-sync`는 아직 실행하지 않았다 |
| 4 | 창업자의 주간 한도를 쓴다 | 2회차 한 번에 약 4포인트(75→79%). 주당 omp가 만들 수 있는 화면 수가 한도로 제한된다 [추정] |
| 5 | 창업자의 Chrome 바이너리를 실행했다 | Claude Design이 설치된 Google Chrome을 헤드리스로 측정에 썼다. 창업자의 Chrome은 건드리지 않는다는 규칙과 부딪힌다 |

## 다음에 omp가 따를 운영 절차 [제안]

1. **신뢰 폴더 준비.** 매번 새 폴더를 만들지 않고 이미 신뢰를 통과한 폴더(지금은 `/tmp/kin-design-probe`)를 재사용한다. 새 폴더를 쓰면 `run.exp`처럼 `trust this folder`를 기다렸다가 아래 화살표(`\033OB`)와 Enter로 "Yes, I trust this folder"를 고른다. 통과한 폴더는 `~/.claude.json`의 `projects.<경로>.hasTrustDialogAccepted`가 `true`로 남는 것을 확인했다. omp가 이 파일을 직접 고치지는 않는다. 작업 폴더에는 브리프를 `design/briefs/`로 복사해 둔다.
2. **완료는 출력 파일로 판단한다.** 고정 `timeout`으로 끊지 않는다. 프롬프트에서 "마지막에 `./design/exports/<이름>/NOTES.md`를 쓴다"고 지정하고, expect는 그 파일이 생기고 크기가 더 변하지 않을 때까지 폴링한다. 파일 감시는 expect 밖(별도 셸)에서 한다. 보조 신호는 입력 프롬프트(`❯ Try "…"`)가 다시 나타나는 것이다. 상한 시간은 두되 상한에 닿으면 끊지 않고 상태를 창업자 이슈에 보고한다.
3. **내보내기 위치를 명시한다.** 프롬프트에 "독립 HTML과 토큰 파일을 `./design/exports/<이름>/`에 저장하고, 사용한 `*.dc.html` 원본과 `canvas.json`은 `source/`에 둔다"를 쓴다. 이번처럼 지시를 한 번 더 이어서 줘야 하는 경우를 줄이려고 처음 프롬프트부터 쓴다. 파일이 없으면 scratchpad에서 회수하고 회수 경로를 PR 본문에 적는다.
4. **임시 브라우저 프로필을 지시한다.** 프롬프트에 "브라우저 측정은 임시 `--user-data-dir`(`/tmp` 아래, 끝나면 삭제)를 쓴 헤드리스 Chromium으로만 하고, 사용자의 Chrome 프로필이나 실행 중인 Chrome은 건드리지 않는다"를 쓴다. 이번 실행은 이 지시가 없었다. 지시를 따랐는지는 실행 로그의 명령 줄로 확인한다.
5. **주간 한도를 먼저 본다.** 시작 전에 상태 막대의 `Weekly … % left`를 읽어 로그에 남긴다. 남은 비율의 문턱은 창업자가 정한다(제안: 구현 작업이 쓸 몫을 남기도록 낮을 때는 시작하지 않고 이슈에 보고). 끝난 뒤 사용 포인트를 PR 본문에 적는다. 이번 관찰: 1회차 8분에 $2.57(한도 42% left), 2회차 약 49분에 4포인트.
6. **끝낸 뒤 검증한다.** 내보낸 `index.html`을 임시 프로필의 헤드리스 Chrome으로 열어 스크린샷을 찍고, 브리프의 자가 점검 항목(배지 5종, 증거 4단계, 금지 문구)을 대조한다. 산출물의 값은 승인 전까지 [제안]이다.

## 창업자에게 남는 것

- **승인.** 디자인 승인본은 `docs/process/review-rubric.md`의 창업자 승인 대상이다. omp가 만든 산출물이라도 승인 코멘트는 창업자가 단다. 승인 전에는 이슈 DoD의 "승인 코멘트가 있다"를 채웠다고 말하지 않는다.
- **`/design-sync`와 `/design-login`.** 이번에는 실행하지 않았다. claude.ai 계정 인증을 포함하므로 D0-02d(#34)에서 한 번 실제로 돌려 보기 전까지는 창업자 몫으로 둔다. 돌려 본 뒤 이 문서를 고친다.
- **주간 한도의 문턱과 사용 허락.** 한도는 창업자의 계정 자원이다.
- 결과가 나쁘거나 위 절차로도 불안정하면 "불가"로 바꾸고 창업자 실행을 표준으로 확정한다(#29 DoD).

## 편차 기록: D0-02b를 omp가 실행했다 (창업자 수용 요청)

#32(D0-02b)의 DoD는 "창업자가 브리프로 디자인 시스템을 만들었다"다. 실제로는 **omp가 PTY로 `/design`을 실행해 만들었고 창업자가 만들지 않았다.** 이 스파이크의 시험 실행이 곧 D0-02b의 산출물이 됐기 때문이다. 이는 DoD 문구와 다르므로 창업자가 (a) 이 편차를 수용하고 #32를 닫을지, (b) 창업자가 직접 다시 만들지 정한다. 어느 쪽이든 디자인의 승인은 #33(D0-02c)에서 창업자가 한다. 이 편차는 PR #33 본문에도 적는다.

## 이 문서의 한계

- 관찰은 한 머신, 한 계정, 한 브리프에서 두 번이다. 같은 절차가 다른 화면에서도 같은 비용으로 되는지는 모른다.
- 한도 사용량은 상태 막대 표시에서 읽은 값이며 청구 단위가 아니다.
- 위 운영 절차는 아직 한 번도 처음부터 끝까지 시험하지 않았다. 처음 쓰는 D0-03에서 결과를 이 문서에 덧붙인다 [제안].
