# SC-01 Studio 셸 내보내기 (D0-03a)

**상태: 창업자 승인됨** (https://github.com/NomaDamas/Kinetra/issues/36#issuecomment-6767800144, 2026-11-10). 이 폴더의 치수와 문구는 모두 **[제안]**이다.

## 출처

- 규격(브리프): `design/briefs/sc-01.md`. 0절 창업자 지시(기능은 빠짐없이, 화면은 단순하게, 진행형 공개)가 첫 조건이다. 토큰과 컴포넌트는 `design/exports/design-system/`(v0, 승인)을 그대로 쓴다.
- **Claude Design 산출물 URL:** https://claude.ai/artifact/PQb3gPuTCNykoYGurUn9Af (제목 "SC-01 Studio 셸", 비공개). 같은 세션 로그의 `https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd`는 새 산출물을 만들 때 읽는 Artifact 유형 안내이며 디자인 산출물이 아니다 [추정: 로그 문구 기준].
- 만든 방법: omp가 `docs/decisions/design-pty.md` 절차대로 expect로 `claude --model fable`(상태 막대 **Fable 5.2**, Claude Code 2.1.322)을 신뢰 폴더 `/tmp/kin-design-probe`에서 띄웠다. 먼저 `/design`만 입력해 자동완성("Make a new Design artifact from a brief")을 확인한 뒤, 브리프 파일 경로를 가리키는 짧은 지시를 보냈다. 로그에 `Artifact(` 호출이 나왔다(Claude Design 도구 사용 확인). 실행 id `sc01b-20261110T203657`.
- 이 폴더의 `NOTES.md`는 Claude Design(Claude Code 세션)이 쓴 것이고 omp가 고치지 않았다.
- 이전 시도(PR 처음 커밋)는 `/design`이 호출되지 않은 채 Claude Code(Opus 5.5)가 직접 만든 것이라 이 폴더에서 **교체**했다. 이유와 비교는 `docs/decisions/design-pty.md` "추가 관찰".

## 편차 (창업자가 수용할지 정한다)

1. **`DONE.json`이 없다.** 지시의 마지막 줄이었지만 세션이 `NOTES.md`를 쓴 뒤 "You're out of usage credits"(사용 크레딧 소진) 메시지와 함께 멈췄다. omp가 정지 파일로 세션을 끝냈다. 대신 omp가 `NOTES.md`의 파일 표와 폴더를 직접 대조했다: `index.html`, `source/*.dc.html` 14개, `source/canvas.json`, `source/tools/build_export.py`, `NOTES.md`가 있다(`NOTES.md`가 표에 적은 `DONE.json`만 없음). 아트보드 파일들은 마지막 수정 시각이 `index.html` 이전이라 쓰는 중에 끊긴 흔적은 보이지 않는다.
2. **`preview.png`는 omp가 찍었다**(헤드리스 Chrome, 임시 `--user-data-dir`, 끝나고 삭제). 맨 위 약 2400px(S1~S3 일부)만 보인다. 주석 줄의 긴 글자(상시 조작 요소 수 설명)가 오른쪽에서 잘려 보이는데 `index.html` 자체의 그림이다. 아트보드 밖으로 넘치는 요소는 없다고 `NOTES.md`가 적었으나 omp는 다시 재지 않았다.
3. **이 계정에 Design System 유형 산출물이 없어** 캔버스에 디자인 시스템 기록을 달지 못했다(`NOTES.md` 15번). 색과 치수는 토큰 값을 글자 그대로 썼다.
4. **글꼴.** 이 `index.html`은 외부 요청이 0건이고 글꼴 파일이 없다(Pretendard, JetBrains Mono는 설치돼 있을 때만, 아니면 시스템 글꼴). 캔버스 원본(`source/*.dc.html` 14개)은 디자인 시스템 원본처럼 JetBrains Mono 스타일시트를 Google Fonts에서 부른다(원격 참조, 저장소에 글꼴 파일 없음). 원장 행이 없는 이유는 검사 범위가 아니라 **이 저장소가 글꼴 파일을 배포하지 않기 때문**이다. 앱(C-04)이 글꼴 파일을 `apps/**/public/`에 넣는 순간 두 글꼴(SIL OFL 1.1)의 원장 행이 필요하다.
5. **이 폴더의 자기 점검 수치는 Claude Design 세션이 낸 값이다.** omp는 `build_export.py`를 임시 폴더에서 돌려 `index.html`이 바이트 단위로 같게 다시 만들어지는 것(재생성 성공)을 확인했다. 조작 요소 수는 다시 세지 않았다. S1은 14개이고 `NOTES.md`가 "부품 목록 안의 `인용` 배지를 목록 하나에 넣어 센 해석"을 [확인 필요]로 적었다. 승인 때 S1을 눈으로 세 주기 바란다.
6. **리뷰에서 나온 디자인 지적(승인 뒤라 이 내보내기는 고치지 않고 구현에 넘김).** ① S1의 클릭 가능한 `인용` 배지를 상시 조작 요소 수에 넣을지 브리프 규칙과 어긋날 수 있다 — C-04 구현 때 브리프 5.1의 계산 규칙으로 다시 센다. ② S9(엔진 오프라인)의 비활성 사유 툴팁이 상단바 행 안에 줄바꿈 없이 놓여 좁은 폭에서 다른 요소를 밀 수 있다 — 구현에서는 상단바 밖 오버레이로 띄운다. 둘 다 D0-04 디자인 대조의 예외 목록에 사유와 함께 적는다.

## 비용과 한도 (상태 막대에서 읽은 값)

| 시점 | 세션 비용 | 주간 한도 |
|---|---|---|
| 시작 1분 뒤(Ctrl-C 한 번으로 상태 막대를 띄워 읽음) | $0.00 | 60% left |
| 실행 3분 | $2.36 | 59~60% left |
| 실행 33분 | $14.42 | 60% left |
| 실행 35분(멈춘 시점) | $15.47 | 59% left |

같은 계정에서 다른 세션이 함께 돌고 있어 주간 한도 표시를 이번 실행만의 사용량으로 읽을 수 없다 [추정]. 시작 전 한도(25% 미만이면 중단)는 통과했다.

## 파일

| 경로 | 내용 |
|---|---|
| `index.html` | 독립 갤러리(253306바이트). 아트보드 14장(S1~S10, S7은 a·b·c 세 장, 보충 A·B) |
| `source/*.dc.html`, `source/canvas.json` | 캔버스 아트보드 원본 14개와 위치·크기·제목·순서 |
| `source/tools/build_export.py` | 원본에서 `index.html`을 만드는 스크립트: `python3 source/tools/build_export.py source <out_dir>` |
| `NOTES.md` | Claude Design 세션이 쓴 노트: 자기 점검 표, 기능 도달 단계, 브리프에서 벗어난 곳 15건 |
| `preview.png` | omp가 찍은 스크린샷(1440×2400) |

## 승인 때 봐 달라고 한 것 (승인됨)

- S1(기본 화면)의 상시 조작 요소가 14개 이하이고 `primary`가 하나인지. 기능이 줄었다고 느끼는 곳이 있는지(`NOTES.md`의 기능 도달 단계 표).
- `NOTES.md` "새로 정한 값과 브리프에서 벗어난 곳"의 항목: 보충 아트보드 2장 추가(1번), 에이전트 바의 `보내기` 버튼 없음(4번, SC-03에서 정함), S8 컴파일 중 주 행동 활성(13번).
