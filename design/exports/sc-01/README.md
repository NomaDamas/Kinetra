# SC-01 Studio 셸 내보내기 (D0-03a)

**상태: 창업자 승인 대기. 그리고 `/design`(Claude Design)으로 만든 것이 아니다(아래 "편차").** 이 폴더의 값과 문구는 모두 **[제안]**이다. #36의 승인 코멘트가 달리기 전에는 승인본이 아니다.

## 출처

- 규격(브리프): `design/briefs/sc-01.md`. 0절 창업자 지시(기능은 빠짐없이, 화면은 단순하게, 진행형 공개)가 첫 조건이다. 토큰과 컴포넌트는 `design/exports/design-system/`(v0, 승인)을 그대로 쓴다.
- Artifact URL: https://claude.ai/artifact/FpxzXZ2tvGBQ1N9z7rAVm5 (실행한 Claude Code 세션이 만든 비공개 Artifact. `index.html`과 같은 갤러리의 조각판).
- 만든 방법: omp가 `docs/decisions/design-pty.md`의 절차대로 expect로 대화형 `claude`(Claude Code 2.1.322)를 신뢰 폴더 `/tmp/kin-design-probe`에서 띄웠다. 실행 id `sc01-20261110T195110`, 완료는 `DONE.json`의 실행 id 일치로 감지했다(1092초 뒤, 고정 제한으로 끊지 않음).
- 원본 `NOTES.md`(Claude Code가 쓴 자기 점검 표와 편차 13건)와 `DONE.json`은 그대로 들어 있다.

## 편차 (창업자가 수용할지 정한다)

1. **`/design`이 호출되지 않았다.** omp가 보낸 한 줄 프롬프트는 `/design Design screen SC-01 …`로 시작했지만 모델은 "메시지가 문장 중간에서 시작한다"고 답하고 프로젝트 폴더를 먼저 살폈다. 로그에는 `/design` 호출 흔적이 없고, `NOTES.md`도 "이 세션에는 `/design`(Claude Design) 스킬이 없었다"고 적었다. 그래서 Claude Code(상태 막대 모델 **Opus 5.5**, 1·2회차 때의 Fable 5.2가 아님)가 브리프를 읽고 빌드 스크립트(`source/tools/build_sc01.py`)로 아트보드를 직접 만들었다. 형식은 디자인 시스템과 같은 `*.dc.html` + `canvas.json`이지만 **Claude Design의 산출물이 아니다.** 원인은 [추정]: 긴 입력이 붙여넣기로 처리되면서 앞부분(`/design `)이 잘렸다. 다음 실행은 `/design`을 먼저 따로 보내 자동완성을 확인한 뒤 본문을 보내는 것으로 고친다 [제안, 미검증].
2. **글꼴 링크 없음.** 이 갤러리는 외부 요청 없이 열리도록 Google Fonts 링크를 넣지 않았다. 글꼴 파일은 여기에도 들어 있지 않다(이름으로만 참조, 없으면 시스템 글꼴). 외부 URL은 `index.html`에 0건이다. 원장 행은 필요 없다(`scripts/check_assets.py`는 `assets/`와 `apps/**/public/`만 본다).
3. **브라우저 임시 프로필.** 프롬프트에 임시 `--user-data-dir`를 지시했고 `NOTES.md`는 지켰다고 적었다. 실행 로그의 명령 줄에서는 확인하지 못했다(화면 로그에 `user-data-dir` 문자열이 없다). omp는 창업자의 Chrome을 건드리지 않았고, 아래 `preview.png`는 omp가 임시 프로필로 따로 찍었다.
4. 자기 점검의 숫자(상시 조작 요소 S1 = 14 등)는 Claude Code가 낸 값이다. omp는 `build_sc01.py`를 임시 폴더(`source/tools/selfcheck.json`이 없는 새 출력 폴더)에서 돌려 `index.html`이 바이트 단위로 같게 다시 만들어지는 것을 확인했다. 다만 스크립트는 마지막에 `source/tools/selfcheck.json`을 쓰려다 `FileNotFoundError`로 끝났다(출력 폴더에 `source/tools/`가 없었기 때문 [추정]). 조작 요소 수 자체는 다시 세지 않았다. 승인 때 S1을 눈으로 세 주기 바란다.

## 비용과 한도 (상태 막대에서 읽은 값)

| 시점 | 세션 비용 | 주간 한도 |
|---|---|---|
| 실행 전(Ctrl-C 한 번으로 상태 막대를 띄워 읽음) | $0.00 | 70% left |
| 실행 18분 시점 | $5.43 | 65% left |

DONE.json 확인은 1092초(약 18분) 시점이다. 25% 미만이면 중단하는 기준(Main 지시)은 통과했다.

## 파일

| 경로 | 내용 |
|---|---|
| `index.html` | 독립 갤러리(257428바이트). 아트보드 S1~S10 + 자기 점검 표. 외부 요청 없음 |
| `source/S1-Default.dc.html` … `S10-Keyboard.dc.html` | 아트보드 원본 10개(S7은 세 화면을 나란히) |
| `source/canvas.json` | 위치·크기·제목·순서 |
| `source/tools/build_sc01.py`, `selfcheck.json` | 원본과 `index.html`을 만드는 스크립트와 그 점검 결과 |
| `NOTES.md` | Claude Code가 쓴 노트(자기 점검 표, 브리프와 다른 점 13건, 새로 정한 값) |
| `DONE.json` | 완료 표식(실행 id와 파일 목록) |
| `preview.png` | `index.html`을 헤드리스 Chrome(임시 `--user-data-dir`, 끝나고 삭제)으로 1440×2400에서 찍은 스크린샷. 맨 위 약 2400px(S1~S3 일부)만 보인다 |

## 승인 때 봐 달라는 것

- S1(기본 화면)의 상시 조작 요소가 14개 이하이고 `primary`가 하나인지. 기능이 줄었다고 느끼는 곳이 있는지(`NOTES.md`의 기능 도달 단계 표).
- `NOTES.md` "브리프와 다르거나 새로 정한 것"의 [확인 필요] 항목(5, 8, 11번).
