# 결정: 음성 받아쓰기 방식 (I-01a)

- 상태: **omp 결정, 구현됨.** 작성일 2026-11-11. 이슈 #158, 부모 I-01 #157. **창업자 승인(approved_by: founder, 2026-11-11, PR #483 코멘트):** 테스트 픽스처 FLAC 3개가 CC-BY-4.0이다(`review-rubric.md`: CC0가 아닌 에셋은 창업자 승인 대상). 표기는 `CREDITS.md`에 있다. 나머지(MIT, Apache-2.0, BSD-3-Clause 의존성, 비용 0)는 승인 대상이 아니다.
- 대목표·핵심 가치: G1 / V2 상상에서 현실까지. 이 결정이 없으면 손을 쓸 수 없을 때, 특히 헤드셋 안에서 에이전트에게 말할 수 없다.
- 표기: 값 배지 `시뮬` `인용` `기본값` `사용자 선언` `추정`. **[추정]** 근거가 약한 판단, **[확인 필요]** 아직 재지 않은 사실.
- 새로 잰 것은 4절뿐이다. 그 외 수치는 출처를 적었다. 출처가 없는 정확도 수치는 쓰지 않았다.

## 결론

**로컬 faster-whisper(Whisper small, CPU int8)로 받아쓴다.** 녹음은 이 머신을 떠나지 않고, 키와 호출 비용이 없고, 오프라인으로 돈다. 대가는 정확도와 속도다. 이 표본에서 로컬 small이 명령 10건 중 5건에서 내용어를 틀렸고(예: "지붕 **질량**을" → "지붕 **진량**을"; 한 건은 "바퀴"→"밖으로"와 "수레"→"수례" 두 낱말), API 세 종은 각각 1건이었다(4.2절). 그래서 구현은 다음을 지킨다.

1. 받아쓴 글은 **신뢰하지 않는 텍스트**다. 확인 단계(I-01b)와 Command 검증기를 거치기 전에는 아무것도 바꾸지 않는다. 삭제류는 확인을 둔다(계획 4.3절).
2. 받아쓰기는 `Transcript(text, language, duration_s, model)` 하나의 계약 뒤에 있다. 정확도가 모자라면 같은 계약 뒤에서 더 큰 로컬 모델(6절)이나 게이트웨이 경유 API로 바꾼다. 호출하는 쪽은 바뀌지 않는다.
3. 숫자와 단위는 인식기마다 다르게 쓴다("2킬로그램" → "2kg", "500뉴턴" → "500N", "30퍼센트" → "30%", "네 개" → "4개"). 이 모듈은 고치지 않는다. 텍스트 경로와 같은 Command 검증기가 읽는다(I-01b, G-03a).

## 1. 비교한 방식과 기준

| 방식 | 무엇 | 비교 방법 |
|---|---|---|
| A. 브라우저 Web Speech API | 브라우저의 `SpeechRecognition` | 문서와 호환성 표(측정하지 않음, 3.1절) |
| B. 로컬 Whisper 계열 OSS | faster-whisper(CTranslate2), 별 1만 개 이상, 허용 라이선스 | 이 저장소 구현을 직접 돌림(4절) |
| C. 제공자 STT | OpenRouter `/audio/transcriptions` | 모델 셋을 같은 입력으로 직접 돌림(4절) |

기준은 이슈가 정한 넷이다: 프라이버시, 비용, 한국어 정확도, 오프라인.

## 2. 비교표

| | A. Web Speech API | B. 로컬 faster-whisper small | C. 제공자 STT (OpenRouter) |
|---|---|---|---|
| 프라이버시 | Chrome은 오디오를 웹 서비스로 보낸다. MDN: "Your audio is sent to a web service for recognition processing, so it won't work offline"(`인용`). 기기 안 처리 옵션 `processLocally`가 있으나 언어 팩 제공은 [확인 필요] | **녹음이 기기를 떠나지 않는다.** 구현이 파일을 쓰거나 로그를 남기지 않는다(테스트가 확인). 모델을 받을 때만 네트워크를 쓴다 | 오디오가 OpenRouter와 그 뒤의 제공자로 간다. `provider.zdr`, `data_collection: deny`로 제한할 수 있으나 제공자별 보관 정책은 확인하지 않았다 [확인 필요] |
| 비용 | 0 | 0(전기와 시간뿐) | 4.3절. 83초 오디오 15건에 0.0006~0.0058 USD(제공자 보고 `usage.cost`, `인용`) |
| 한국어 정확도 | 근거 없음. 인식기는 브라우저 제공자의 비공개 서비스라 버전과 모델을 알 수 없고 우리가 고정할 수 없다. **측정하지 않았다** | 4절. 같은 계열의 큰 모델이 더 정확하다는 것은 논문에 있다(3.2절) | 4절. 한 가지 모델군(Whisper large-v3, gpt-4o-transcribe, Scribe v2)을 쟀다 |
| 오프라인 | 안 된다(Chrome 서버 방식) | **된다.** 모델을 한 번 받은 뒤 `local_files_only`로만 읽는다 | 안 된다 |
| 재현성 | 브라우저와 서비스가 바뀐다. 헤드셋 브라우저 지원은 [확인 필요] | 고정 리비전과 모델 해시. `temperature=0`이라 같은 빌드에서 같은 입력은 같은 글을 낸다 [추정: 이 머신에서 연속 실행으로만 확인] | 제공자가 모델을 바꿀 수 있다 |
| 키 | 없음 | 없음 | `OPENROUTER_API_KEY`를 코어 프로세스 환경에서만(G-01). 지금 게이트웨이에는 STT 호출이 없다(`chat/completions`만, 5절) |
| 구현 위치 | 클라이언트(브라우저)에 있다. **불변 결정 4**(클라이언트는 어댑터 경계 뒤)와 2(모든 입력은 같은 Command 경로)에서 인식기가 클라이언트마다 갈린다 | 코어. 클라이언트는 녹음만 보낸다 | 코어(게이트웨이) |

### 2.1 라이선스와 규모(B 후보)

| 후보 | 별 | 라이선스 | 비고 |
|---|---|---|---|
| SYSTRAN/faster-whisper | 26,658 | MIT | **채택.** CTranslate2 위의 구현. Python 휠 하나로 설치 |
| ggml-org/whisper.cpp | 55,084 | MIT | C++ 바인딩이 필요하다. 이번에 쓰지 않았다 |
| openai/whisper | 112,400 | MIT | 원본. PyTorch가 필요해 무겁다 |

별 수는 2026-11-11 GitHub API 값이다(`인용`). 모델 가중치는 Whisper 원본 MIT다(OpenAI README, `인용`). 변환본 `Systran/faster-whisper-small`의 모델 카드도 `license: mit`다.

## 3. 한국어 정확도의 외부 근거

### 3.1 Web Speech API

공개된 한국어 정확도 수치를 찾지 못했다. 만들어 쓰지 않는다. 브라우저 지원은 MDN 호환성 데이터(browser-compat-data)에서 Chrome 139부터 접두사 없음, Safari 14.1부터 `webkit` 접두사다(`인용`). Meta Quest 브라우저에서 되는지는 확인하지 못했다 [확인 필요]. 헤드셋이 주 입력 환경이라 이 불확실성만으로도 A는 주 경로가 되기 어렵다.

### 3.2 Whisper 논문의 FLEURS 한국어

Radford et al., *Robust Speech Recognition via Large-Scale Weak Supervision*(arXiv:2212.04356), 부록 D.2.4 표 13에서 한국어 열을 그대로 옮겼다(`인용`). FLEURS는 사람이 낭독한 문장이고 WER(%)은 논문의 정규화와 단어 기준이다.

| 모델 | tiny | base | small | medium | large | large-v2 |
|---|---|---|---|---|---|---|
| FLEURS 한국어 WER | 36.1 | 27.8 | 19.6 | 16.4 | 15.2 | 14.3 |

읽는 법: 우리가 쓰는 small은 같은 계열의 가장 큰 모델(large-v2)보다 논문 수치로 5.3 %p 높다. 그 논문의 수치는 낭독 문장이고 짧은 명령이 아니며, 2022년 모델이다. 우리 환경의 값이 아니다.

## 4. 이 저장소에서 직접 잰 비교

### 4.1 조건과 한계 (먼저 읽는다)

- 명령 10건(`docs/decisions/stt-results.json`의 `cmd01`~`cmd10`)은 **내가 정한 문장이고 macOS `say -v Yuna`가 읽은 합성음**이다. 사람 목소리가 아니다. 화자는 하나(Yuna)다. 다른 한국어 시스템 음성(Flo, Reed, Grandma, Sandy, Shelley, Eddy, Rocko, Grandpa)은 짧은 이름(`say -v Flo`)으로 부르면 이 머신에서 빈 오디오(0.016초)가 나와 처음에는 "쓸 수 없다"고 적었으나, **그 판단은 틀렸다.** 전체 이름(`say -v "Flo (Korean (South Korea))"`)으로 부르면 모두 소리가 나고 같은 문장("이 부품을 더 가볍게 해 줘")이 2.93초로 생성된다(이 머신에서 다시 확인했다). 독립 리뷰는 Flo, Reed, Grandma로 로컬 small이 "질량"을 한 번도 맞히지 못했다고 보고했다("10분 진량을 이 킬로드렘으로 바꿨어" 등). 이 음성들은 품질이 낮은 Eloquence 계열이라 정확도의 근거로는 약하다. 이 문서는 그 음성들로 10건을 다시 재지 않았으므로 **아래 표는 Yuna 한 화자의 값이다.** Apple 소프트웨어 사용권(macOS Sequoia SLA 1.F)은 시스템 음성을 "개인적·비상업적" 용도로만 허용하고 공개 재배포를 허락하지 않으므로 **이 음성 파일은 저장소에 넣지 않았다.**
- 사람 낭독 5건은 FLEURS ko_kr test(`google/fleurs`, CC-BY-4.0, `인용`)의 첫 5문장이다. 명령이 아니라 뉴스·여행 문장이다. **저장소에는 그중 3건의 FLAC만** 테스트 픽스처로 넣었고 원장에 CC-BY-4.0 행이 있다.
- 표본이 작다(15건, 83.4초). 아래 비율은 **이 15건의 값이고 한국어 일반의 정확도가 아니다.** 신뢰구간을 만들지 않았다. 작은 차이는 읽지 않는다.
- 실행은 1회, 머신은 부하가 큰 M2 Pro(load average 16~50, 10코어, 같은 시간대에 다른 작업이 돌았다). **속도는 `추정`이다.**
- 정규화는 `kinetra_engine/stt/score.py`다: NFKC, 기호·문장부호 제거, 소문자, 공백 정리. **숫자는 바꾸지 않는다.** CER은 공백을 뺀 글자 단위이고(띄어쓰기는 명령의 뜻을 바꾸지 않는다) WER은 공백 단위다. 한국어 WER은 띄어쓰기에 민감해 크게 나온다. 같은 수치끼리만 비교한다.
- 재현: `uv run python tools/dev/resource_guard.py --profile heavy -- uv run python tools/stt/compare.py --cases <cases.json> --out docs/decisions/stt-results.json --api-model openai/whisper-large-v3 --api-model openai/gpt-4o-transcribe --api-model elevenlabs/scribe-v2`. 점수는 `python -c "from kinetra_engine.stt import score; print(score.render(score.load('docs/decisions/stt-results.json')))"`. 입력 오디오는 저장소에 없으므로 같은 문장을 `say -v Yuna`로 만들어 `ffmpeg -ar 16000 -ac 1`로 변환한다(`stt-results.json`의 `cases[].reference`).
- 로컬: `Systran/faster-whisper-small@536b0662…`, faster-whisper 1.2.1, CPU int8, beam 5, `temperature=0`, VAD 켬. API는 `language=ko`.

### 4.2 정확도 (`시뮬`: 같은 입력에서 계산한 값)

| 방식 | 명령 10건 CER / WER / 완전 일치(띄어쓰기 구분 · 무시) | FLEURS 5건 CER / WER / 완전 일치(띄어쓰기 구분 · 무시) |
|---|---|---|
| **로컬 faster-whisper small** | 10.3% / 46.6% / 1 · 5 | 3.9% / 35.2% / 0 · 0 |
| API openai/whisper-large-v3 | 6.9% / 41.4% / 0 · 7 | 1.7% / 15.5% / 0 · 3 |
| API openai/gpt-4o-transcribe | 6.9% / 17.2% / 4 · 5 | 3.5% / 16.9% / 1 · 1 |
| API elevenlabs/scribe-v2 | 13.8% / 39.7% / 2 · 5 | 1.3% / 14.1% / 1 · 3 |

"완전 일치"는 정규화한 글이 참조와 같은 건수다. 앞 숫자는 띄어쓰기까지 같아야 하는 값(`score.render`가 내는 값), 뒤 숫자는 띄어쓰기를 뺀 값이다. 이 문서는 CER에서 띄어쓰기를 명령의 뜻과 무관하다고 보아 뺐으므로 뒤 숫자가 CER과 같은 기준이다. 예: whisper-large-v3의 앞 숫자 0/10은 대부분 "만들어 줘"를 "만들어줘"로 붙인 차이다.

명령 10건에서 **뜻이 바뀌는 내용어 오류**를 파일에서 세었다(띄어쓰기, 마침표, 단위 표기 차이는 세지 않았다).

| 방식 | 내용어 오류가 있는 명령 | 어떤 오류 |
|---|---|---|
| 로컬 small | 5/10 | "바퀴"→"밖으로", "질량"→"진량"(2건), "판정"→"한정", "복제해서"→"복제에서" |
| API whisper-large-v3 | 1/10 | "질량"→"진량" |
| API gpt-4o-transcribe | 1/10 | "달 중력"→"탈중력" |
| API scribe-v2 | 1/10 | "달 중력에서 다시 실행해 줘"→"네."(문장 전체를 놓침) |

읽는 법:

- **로컬 small은 이 표본에서 가장 틀린다.** "질량"은 이 제품의 핵심 낱말이다. "삭제해 줘"(cmd07)는 맞았지만 "판정해 줘"가 "한정해줘"가 되면 엉뚱한 명령이 된다. 그래서 확인 단계가 필수다.
- 같은 모델군이라도 크기가 정확도를 가른다: 로컬 small과 API whisper-large-v3는 둘 다 Whisper인데 FLEURS 5건 CER이 3.9% 대 1.7%다. 3.2절의 논문 방향과 같다.
- API 사이에 순위가 일관되지 않는다(명령에서는 gpt-4o-transcribe, 낭독에서는 scribe-v2가 낫다). 15건으로 API끼리 가를 수 없다.
- 단위 표기: API와 로컬 모두 "2kg", "500N", "30%"처럼 기호로 쓰는 경우가 있다. 숫자를 "네 개"(gpt-4o, scribe)로 쓰기도 하고 "4개"(whisper)로 쓰기도 한다. 위 CER에는 그 차이가 오류로 들어가 있다.

### 4.3 속도와 비용 (`추정`, 부하 아래 1회)

| 방식 | 명령 10건 처리 시간 중앙값 / 최대 (오디오 1.9~3.6초) | FLEURS 5건 중앙값 / 최대 (오디오 8.9~12.5초) | 비용(15건, 83.4초 오디오) |
|---|---|---|---|
| 로컬 small(CPU int8, 모델은 메모리에 올린 뒤) | 4.20 s / 5.39 s | 4.37 s / 5.29 s | 0 |
| API whisper-large-v3 | 1.28 s / 2.26 s | 3.70 s / 5.46 s | 0.000626 USD |
| API gpt-4o-transcribe | 1.29 s / 1.46 s | 1.47 s / 1.63 s | 0.0058 USD |
| API scribe-v2 | 0.97 s / 1.22 s | 1.45 s / 1.77 s | 0.005098 USD |

- 비용은 응답의 `usage.cost`(제공자 보고, `인용`)를 더한 값이다. 오디오 1분으로 환산하면(`계산`) whisper-large-v3 약 0.00045, gpt-4o-transcribe 약 0.0042, scribe-v2 약 0.0037 USD다. 한 번 말하는 명령이 3초라면 0.0002 USD 안팎이다. **비용 자체는 문제가 되는 크기가 아니다.** 로컬을 고른 이유는 비용이 아니라 프라이버시와 오프라인이다.
- 로컬은 명령 한 건에 약 4초가 걸렸다. 누르고 말하기에는 느리다. 부하가 큰 머신의 값이라 한가한 머신에서는 줄 수 있다 [확인 필요]. 줄지 않으면 6절의 대안을 쓴다.
- API 측정에는 비교용 도구 `tools/stt/compare.py`가 키를 환경에서 읽어 `Authorization` 헤더에만 넣었다(출력에서 가린다). 이 호출은 게이트웨이의 예산과 비용 원장을 거치지 않았다. 총 0.0115 USD다(`계산`: 표의 합).

## 5. 구현

위치: `packages/engine/src/kinetra_engine/stt/`.

| 파일 | 역할 |
|---|---|
| `transcriber.py` | `Transcriber.transcribe(bytes 또는 경로, language="ko") -> Transcript`. 모델 고정·검증·로딩, 입력 한도, 디코딩(PyAV) |
| `score.py` | CER/WER 계산과 표 만들기(4절의 점수) |
| `__main__.py` | `python -m kinetra_engine.stt fetch` 모델 받기, `transcribe FILE` 한 건 받아쓰기 |
| `tools/stt/compare.py` | 4절의 비교 실행기(제품 코드가 아님) |

규칙(테스트가 확인한다):

- **모델은 고정이다.** `Systran/faster-whisper-small`의 커밋 `536b0662742c02347bc0e980a01041f333bce120`. **네 파일 모두** sha256을 고정했다(`MODEL_HASHES`: `config.json`, `model.bin` `3e305921…d671`(483,546,902 B, Hugging Face의 LFS 해시와 같음), `tokenizer.json`, `vocabulary.txt`). 받은 직후와 `Transcriber`를 만들 때마다 검사하고, 파일이 없거나 바뀌었거나 잘렸으면 모델을 로더에 넘기지 않고 `ModelMissing`이다. 해시를 통과하고도 라이브러리가 읽지 못하는 모델도 `ModelMissing`으로 바뀐다(맨 라이브러리 오류가 새지 않는다). `model.bin`만 보던 첫 구현은 `tokenizer.json`을 바꿔도 통과했다.
- **`Transcriber`는 네트워크를 쓰지 않는다.** `local_files_only=True`. 모델이 없으면 받지 않고 `ModelMissing`으로 멈춘다. 받는 것은 `fetch`뿐이고 저장소 밖(`~/.cache/huggingface` 또는 `KINETRA_STT_MODEL_DIR`)에 둔다. `fetch`는 자원 가드 밖에서 시작하면 종료 코드 2로 거절한다(`dev-resources.md` 진입점 목록).
- **키가 없다.** 이 경로에는 `OPENROUTER_API_KEY`도 HTTP 클라이언트도 없다. 요구 "키는 환경으로만, 게이트웨이를 통해서"는 이 경로에서는 키가 필요 없다는 뜻으로 충족된다. 게이트웨이(`kinetra_engine.gateway`)는 지금 `chat/completions`만 부른다. API 경로를 추가한다면 `Gateway`에 `/audio/transcriptions` 호출을 더해 같은 예산·원장·마스킹을 거쳐야 하고, 이번 PR은 그것을 하지 않았다.
- **입력 한도**: 25 MiB(OpenRouter 멀티파트 상한과 같게), 60초(`기본값`, 명령은 몇 초). 길이 한도는 컨테이너가 선언한 길이로 디코딩 전에 거절하고, 길이를 선언하지 않는 입력은 60초를 넘는 순간 디코딩을 멈춘다(전체를 디코딩하지 않는다). 한도 초과와 디코딩 실패는 `AudioRejected`이고 메시지에 파일 경로나 내용이 들어가지 않는다.
- **저장하지 않는다.** 오디오는 메모리에서 디코딩하고 글은 반환만 한다. 로그를 남기지 않는다.
- **`transcribe`는 블로킹이고 진행 표시와 취소가 없다.** 이 머신의 부하 아래에서 명령 한 건에 약 4초, 독립 리뷰의 부하(load average 45~50)에서 예열 뒤 9~12초 낭독 한 건에 약 21초가 걸렸다(`추정`). I-01b는 요청 경로 밖(스레드나 작업 큐)에서 부르고 자체 진행 표시와 취소를 가져야 한다.
- **경계.** 녹음 바이트가 클라이언트에서 코어로 간다. `docs/architecture/client-adapter.md` 2절과 3.5절(규칙 I6)을 이에 맞게 고쳤다: 코어가 받는 명령 입력은 "확인된 문장" 하나뿐이고 녹음은 인식 요청이다. 전송 방식(다섯 계약 밖의 요청인지, 메시지와 한도)은 **I-01b(#159)가 정한다** [확인 필요].
- **디코더는 로컬 오디오 컨테이너만 연다.** FFmpeg는 내용으로 형식을 고르므로 SDP 본문 110바이트를 `transcribe(bytes)`에 주면 UDP 소켓을 열고 패킷을 기다리며 멈췄고, `ffconcat` 본문은 작업 디렉터리의 다른 파일을 읽었다(독립 리뷰가 재현). `av.open`에 `format_whitelist=wav,flac,mp3,ogg,matroska,webm,mov,mp4,m4a,3gp,3g2,mj2,aac`와 `protocol_whitelist=file`을 준다. 그 밖의 형식은 `AudioRejected`다. 테스트는 SDP와 `ffconcat`·m3u 본문이 거절되고 소켓·파일 기술자가 늘지 않으며 디코더가 시간 안에 돌아옴을 확인한다(화이트리스트를 끄면 이 테스트가 실패하는 것을 확인했다).
- 디코딩: PyAV가 wav, flac, mp3, ogg, webm/opus, m4a, aac를 읽는다(브라우저 `MediaRecorder` 출력 포함 [확인 필요: 웹 클라이언트와의 연결은 I-01b]).
- 의존성: 직접 의존성 faster-whisper 1.2.1, av(`>=11,<19`)와 그 추이 의존성 전부(ctranslate2, onnxruntime, tokenizers, huggingface-hub, numpy, tqdm, protobuf, httpx2 계열, hf-xet, click, fsspec, filelock, flatbuffers, anyio, h11, idna, truststore)가 원장 `dependency` 행으로 있다(`uv.lock`의 새 패키지 하나당 한 행). 모델 가중치(MIT)와 FLEURS 픽스처 3개(CC-BY-4.0)는 별도 행이다. 라이선스는 대부분 MIT, BSD-3-Clause, Apache-2.0이고 예외는 `tqdm`(MPL-2.0 AND MIT), PyAV 휠(위)과 ctranslate2의 Linux 휠(아래)이다. **`av`는 `<19`로 제한했다.** faster-whisper 1.2.1이 av 19가 없앤 `av.open(metadata_errors=...)`를 부른다(av 19.0.2에서 `TypeError`로 재현). **PyAV 휠의 라이선스는 BSD-3-Clause 하나가 아니다.** PyAV 코드는 BSD-3-Clause이고 번들 FFmpeg는 `--enable-version3`(LGPL-3.0-or-later, `avcodec_license()`가 `LGPL version 3 or later`, `--enable-gpl` 없음)이지만, 같은 휠에 별도 공유 라이브러리로 libx264와 libx265(GPL-2.0-or-later)가 들어 있고 libavcodec이 링크한다(macOS arm64 휠과 Linux x86-64 휠 모두). 상류 유지보수자는 휠을 "LGPLv2.1+ OR GPLv2+"로 설명한다(PyAV-Org/PyAV#2270). 원장에는 `BSD-3-Clause AND (LGPL-2.1-or-later OR GPL-2.0-or-later)`로 적었다. 받아쓰기는 비디오 코덱을 쓰지 않지만 `import av`가 GPL 라이브러리를 프로세스에 올린다. 개발 환경에서는 문제를 만들지 않으나 **설치 프로그램·컨테이너 이미지·호스팅 빌드로 배포하기 전에 창업자가 정해야 한다: 이슈 #490 [I-01c].** 선택지는 GPL 없이 PyAV 직접 빌드, 다른 LGPL/BSD 디코더, GPL 수용이다.

테스트(`uv run pytest packages/engine -q -k stt`): 가짜 모델로 계약·한도·고정·오프라인 규칙을 확인하고, **고정 음성 픽스처**(`packages/engine/tests/fixtures/stt/`의 FLEURS 3건)는 실제 모델이 캐시에 있을 때 인식 결과를 기록값과 같은지 본다. 모델이 없는 머신(CI 포함)에서는 건너뛰고 이유를 출력한다. 모델은 462 MiB라 CI에서 받지 않는다. 기록값(`expected.json`)은 이 머신의 첫 실행에서 나온 글이고 정답이 아니다. 기준은 참조 문장과의 CER 0.1 이하(`기본값`, 회귀 경계이지 정확도 주장이 아니다, **모든 플랫폼**)와, **기록한 플랫폼에서만** 기록한 글의 일치다. `expected.json`의 `recorded_on`(Darwin-arm64, ctranslate2 4.9.0, CPU int8)이 플랫폼 태그이고 `engine.md` 5.4절의 "기록값은 기준 플랫폼의 값, 다른 플랫폼은 허용 한계" 방식을 따른다. Linux(MKL) 값은 측정하지 않았다 [확인 필요]. 이 테스트는 모델이 캐시에 있어야 하므로 CI에서는 건너뛴다(CI에서 돌리려면 리비전을 키로 한 모델 캐시가 필요하다).

## 6. 닫지 않은 것

| 빈칸 | 영향 | 닫는 곳 |
|---|---|---|
| 사람 목소리의 짧은 한국어 명령 정확도. 이번 명령 10건은 합성음 하나다 | 4.2절의 비율은 실제 사용자를 대표하지 않는다. 마이크 잡음, 헤드셋 마이크, 억양이 빠졌다 | I-01b의 통합 시연 "한국어 명령 10건의 인식 기록"(부모 I-01 DoD). 사람이 읽은 녹음으로 다시 잰다 |
| 로컬 모델 크기. small만 쟀다. medium, large-v3, large-v3-turbo는 받지 않았다(자원 가드: SSD 여유가 10 GiB 근처라 1.5 GiB 이상 모델을 받으면 이후 무거운 실행이 막힌다) | 명령 오류율이 높으면 크기를 올리는 것이 첫 수단이다. 속도는 더 느려진다. `MODEL_REPO`, `MODEL_REVISION`, `MODEL_SHA256` 세 줄을 바꾸는 일이다 | 디스크 여유가 생긴 뒤 같은 `compare.py`로 |
| 로컬 속도. 부하가 큰 머신 1회 약 4초 | 누르고 말하기의 체감 | 한가한 머신, Apple Silicon GPU/MPS 경로(ctranslate2가 실험적 MPS를 알린다. 시험하지 않았다) |
| Web Speech의 한국어 정확도와 Quest 브라우저 지원 | 결정은 프라이버시와 오프라인에서 이미 갈린다 | 필요하면 헤드셋 확보(`headset.md`) 뒤 |
| 제공자 STT의 데이터 보관 정책 | API를 쓰기로 할 때만 필요 | 그때 |
| 소리가 거의 없거나 한국어가 아닌 입력에 그럴듯한 문장이 나온다. 리뷰어가 0.73초짜리 한국어 아닌 소리에 로컬 small이 "다음 영상에서 만나요!"를 냈다고 보고했다(재현하지 않음) | 버튼을 잘못 눌러도 문장이 나온다. 위 "신뢰하지 않는 텍스트 + 확인 단계" 결정의 이유다. 짧은 입력(`duration_s`)을 I-01b가 경고로 쓸 수 있다 | I-01b |
| 숫자·단위 정규화("2kg" ↔ "2킬로그램", "네 개" ↔ "4개") | 받아쓴 글이 Command 검증기에서 거부될 수 있다 | I-01b 또는 G-03a. 이 이슈의 범위 밖이라 코드를 넣지 않았다 |
| 대화형 음성, 화자 구분, 상시 청취 | 범위 밖(이슈) | S2 이후 |

## 7. 근거 목록

- OpenAI Whisper 논문, arXiv:2212.04356, 표 13(FLEURS WER)과 부록 C의 정규화.
- MDN, `SpeechRecognition`(서버 처리 주의 문구, `processLocally`). MDN browser-compat-data `api/SpeechRecognition.json`.
- OpenRouter 문서: Speech-to-Text(`/api/v1/audio/transcriptions`, 입력 형식, 25 MB 멀티파트 상한, `provider.zdr`), 모델 목록 API `output_modalities=transcription`.
- FLEURS: Conneau et al., arXiv:2205.12446, 데이터 카드의 CC-BY-4.0.
- GitHub API: faster-whisper, whisper.cpp, openai/whisper의 별 수와 라이선스.
- Hugging Face: `Systran/faster-whisper-small` 모델 카드(MIT), 커밋 `536b0662…`, LFS 해시.
- Apple macOS Sequoia 소프트웨어 사용권 1.F(시스템 음성의 용도 제한). 이 머신의 `/Library/Documentation/License.lpdf`.
