# SC-02 인스펙터 내보내기 (D0-03b)

**상태: 창업자 승인 대기.** 이 폴더의 배치, 문구, 예시 수치는 모두 **[제안]**이다. #37의 승인 코멘트가 달리기 전에는 승인본이 아니다.

## 출처

- 규격(브리프): `design/briefs/sc-02.md`. 0절 창업자 지시(기능은 빠짐없이, 화면은 단순하게, 진행형 공개)가 첫 조건이다. 토큰과 컴포넌트는 `design/exports/design-system/`(v0), 셸 안의 자리는 `design/exports/sc-01/`(승인, 오른쪽 패널 320 px)을 그대로 쓴다.
- **Claude Design 산출물 URL:** https://claude.ai/artifact/W5F2kNGaJAdKUv1nBEhgdP (제목 "SC-02 인스펙터", 비공개). 로그의 `…QKN21…`은 Artifact 유형 안내(디자인 아님) [추정].
- 만든 방법: omp가 `docs/decisions/design-pty.md` 절차대로 expect로 `claude --model opus`(상태 막대 **Opus 5.5**, Claude Code 2.1.322, 창업자 결정: Fable 크레딧 소진으로 Opus 사용)를 신뢰 폴더 `/tmp/kin-design-probe`에서 띄웠다. 먼저 `/design`만 입력해 자동완성을 확인한 뒤 브리프 경로를 가리키는 짧은 지시를 보냈다. 로그에 `Artifact(` 호출이 3분 안에 나왔다(Claude Design 도구 사용 확인). 실행 id `sc02-20261110T215445`, `DONE.json`의 실행 id가 일치해 2035초(약 34분) 뒤 완료로 판정했다(고정 제한 없음).
- `NOTES.md`와 `DONE.json`은 Claude Design 세션이 쓴 그대로이고 omp가 고치지 않았다.

## 편차 (창업자가 수용할지 정한다)

1. **창업자 대신 omp가 만들었다**(D0-02b, SC-01과 같은 편차. SC-01은 #36 승인 코멘트에서 수용됨).
2. **모델은 Opus 5.5**다(SC-01은 Fable 5.2). Opus 세션에서도 `/design`이 호출되고 Claude Design 캔버스가 만들어졌다. 모델에 따른 품질 차이는 비교하지 않았다.
3. **`preview.png`는 omp가 찍었다**(헤드리스 Chrome, 임시 `--user-data-dir`, 끝나고 삭제). 맨 위 약 2400px(S1, S2 일부, S3 일부)만 보인다.
4. **글꼴.** `index.html`은 외부 요청 0건, 글꼴 파일 없음(Pretendard, JetBrains Mono는 설치돼 있을 때만, 아니면 시스템 글꼴). 캔버스 원본(`source/*.dc.html`)은 디자인 시스템 원본처럼 JetBrains Mono를 Google Fonts에서 부른다. 원장 행은 필요 없다(`scripts/check_assets.py`는 `assets/`와 `apps/**/public/`만 본다).
5. **자기 점검 수치는 Claude Design 세션이 헤드리스 Chrome으로 잰 값이다.** omp는 `build_export.py`를 임시 폴더에서 돌려 `index.html`이 바이트 단위로 같게 다시 만들어지는 것을 확인했고, 조작 요소 수는 다시 세지 않았다. S1은 10개이고 이름이 브리프 5.1절과 같다고 `NOTES.md`가 적었다. 승인 때 눈으로 세 주기 바란다.
6. `NOTES.md`가 [제안]으로 적은 브리프 밖 결정 20건(예: `선언 해제`를 `사용자 선언` 배지 팝오버 안에 둠, 액추에이터 2단계 필드용 `바로 열기` 버튼 3개, 머리 글자를 `type.label`로 낮춤)은 승인 때 함께 봐 달라.

## 비용과 한도 (상태 막대에서 읽은 값)

| 시점 | 세션 비용 | 주간 한도 |
|---|---|---|
| 시작 약 1분 뒤(Ctrl-C 한 번으로 상태 막대를 띄워 읽음) | $0.00 | 41% left |
| 실행 2분 | $0.79 | 41% left |
| 실행 12분 | $2.73 | 41% left |
| 실행 33분(완료 직전) | $9.21 | 37% left |

시작 전 한도가 25% 미만이면 중단하는 기준(Main 지시)은 통과했다. 같은 계정에서 다른 세션도 돌고 있어 주간 한도 표시를 이번 실행만의 사용량으로 읽을 수 없다 [추정].

## 파일

| 경로 | 내용 |
|---|---|
| `index.html` | 독립 갤러리(243147바이트). 아트보드 10장(S1~S10, 상태 변형을 한 보드에 나란히) |
| `source/*.dc.html`, `source/canvas.json` | 캔버스 아트보드 원본 10개와 위치·크기·제목·순서 |
| `source/tools/` | `build_export.py`(원본 → `index.html`), `measure.sh`, `shot.sh` |
| `NOTES.md`, `DONE.json` | Claude Design 세션이 쓴 노트(자기 점검 표, 단계 표, 배지 위치, 브리프 밖 결정)와 완료 표식 |
| `preview.png` | omp가 찍은 스크린샷(1440×2400) |

## 승인 때 봐 달라는 것

- S1(기본 화면)의 상시 조작 요소가 10개 이하이고 인스펙터 안에 `primary`가 없는지. 기능이 줄었다고 느끼는 곳이 있는지(`NOTES.md`의 단계 표).
- 값 배지 5종이 모두 있고 단위나 배지 없는 수치가 없는지. 파단 임계에 "단순화 모델" 라벨이 있는지(S3).
