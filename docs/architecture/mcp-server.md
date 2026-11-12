# 명령 계층 MCP 서버 (G-08, G-08a)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/mcp/`(`server.py`, `__main__.py`), 테스트는 `packages/engine/tests/test_mcp_server.py`(`uv run pytest packages/engine -q -k mcp`).
- 근거: `docs/plan/studio-plan.md` 4.4절과 5.3절의 MCP 서버 노출 결정과 불변 결정 2("모든 편집은 Command다(MCP로도 노출)"), `docs/architecture/client-adapter.md` C1과 "프로세스 안의 발행자", `docs/architecture/agent-edit-tools.md`, 이슈 #155, #555.
- 범위 밖: MCP를 통한 판정 변경. 조회 도구(G-02b, [`agent-query-tools.md`](agent-query-tools.md))는 아직 이 서버의 목록에 없다(MCP 노출은 #558). 판정 엔진 자체(J-01)도 이 서버 이슈의 범위 밖이다.

## 규칙

- **같은 도구, 같은 길.** `tools/list`는 `edit_tools.specs()`와 `run_specs()`를 MCP 도구 모양(`name`, `description`, 인자 스키마를 `inputSchema`로)으로 바꾼 것이고 더하거나 빼는 도구가 없다. 편집 `tools/call`은 `HubEditTools(hub, project_id, origin=Origin.MCP).call(name, arguments)`, 실행·판정 요청은 `RunTools(hub, project_id, judge=judge).call(name, arguments)`다. 앱 안의 에이전트가 부르는 것과 같은 함수라서 인자 스키마(`extra="forbid"`), G-04 권한 가드와 문서 쪽 검증을 똑같이 거친다. MCP는 모델의 JSON 인자만 넘기고 다른 키워드 인자는 넘기지 않는다. 테스트는 편집 호출 11건과 실행·판정 요청을 양쪽에서 호출해 결과 JSON과 문서가 같음을 단언한다. 서버는 프로젝트를 쥐지 않고 직접 고치지 않는다.
- **실행이 Hub를 막지 않는다.** stdio는 `McpServer.handle_async`로 요청을 받는다. 편집은 `Hub.publish`가 큐를 쓰는 이벤트 루프에 그대로 두고, `request_run`과 `request_verdict`만 `asyncio.to_thread`의 작업 스레드에서 `RunTools.call`을 실행한다. `RunTools` 자체의 동기 계약과 한 스냅숏 읽기는 바꾸지 않는다. 테스트는 실행이 작업 스레드에서 멈춰 있는 동안 다른 WebSocket 연결이 `hello`·`subscribe`·`snapshot`을 끝내는 것을 본다.
- **미리보기와 판정은 다르다.** `request_run` 결과는 G-02c 그대로 `is_verdict: false`와 `1회 실행. 판정이 아닙니다`를 싣는다. `request_verdict`는 실제 코어 판정기를 받은 서버에서만 성공한다. 현재 stdio 명령은 판정기를 연결하지 않으므로 `ok: false`와 J-01이 없다는 요약으로 명시적으로 거부하며, 미리보기나 가짜 판정을 대신 내지 않는다.
- **발행자는 `mcp`.** 받아들여진 호출은 `Hub.publish`로 들어가 이력 항목의 `origin`과 모든 구독자(Studio 화면)에게 가는 `applied`의 `origin`이 `mcp`다. 한 호출이 이력 한 칸이다(G-02a).
- **판정 변경과 상수 변경은 없다.** 도구 스키마에는 행성 상수(`PLANET_CONSTANT_NAMES`)와 판정 값(`VERDICT_FIELD_NAMES`) 필드가 없고, `request_verdict`는 판정을 요청해 읽을 뿐 쓰지 않는다. 테스트가 `tools/list`의 스키마에서 금지 필드와 판정 변경 도구가 없음을 본다.
- **거부는 도구 결과다.** 검증기의 사유는 `isError: true`인 결과로 돌아간다. `ToolResult.to_json()` 또는 `RunToolResult.to_json()`을 `structuredContent`와 같은 내용의 텍스트(`content[0]`)로 함께 실어 모델이 읽고 다시 시도할 수 있다. 모르는 도구, 객체가 아닌 `arguments`, `params`가 객체가 아님은 JSON-RPC `-32602`, 모르는 메서드는 `-32601`, JSON이 아닌 줄은 `-32700`, JSON-RPC 2.0이 아닌 메시지와 배치(배열)는 `-32600`이다(MCP 2025-11-25 "Error Handling").
- **수명 주기.** `initialize` 전에는 `ping`만 답하고 나머지 요청은 `-32600`이다. 버전은 `2025-11-25`와 `2025-06-18`을 말한다. 클라이언트가 다른 버전을 청하면 가장 새 것으로 답하고 계속할지는 클라이언트가 정한다(MCP "Version Negotiation"). 배치를 허용하던 `2025-03-26` 이하는 일부러 뺐다. 알림(`notifications/initialized`, `notifications/cancelled` 등)과 응답에는 답하지 않는다. 서버가 클라이언트에 보내는 요청은 없다.
- **로컬 전용.** 전송은 stdio 하나다(MCP "stdio"): 클라이언트가 이 프로세스를 띄우고 유일한 상대가 된다. MCP를 위해 여는 소켓이 없다. 한 줄에 UTF-8 JSON-RPC 메시지 하나이고, stdout에는 MCP 메시지만 쓴다. 보내는 줄은 ASCII다(ASCII가 아닌 글자는 JSON의 `\uXXXX` 이스케이프로 쓴다): JSON은 짝 없는 서로게이트(`"\ud800"`)를 쓸 수 있고 요청 id는 그대로 되돌려 보내므로, UTF-8로 인코딩할 수 없는 글이 답에 실려도 서버가 멈추지 않는다(테스트). 실행 명령은 시작할 때 stdout 디스크립터를 따로 떼어 MCP 전송에 쓰고 원래 stdout을 stderr로 돌려, 어떤 `print`도 MCP 스트림을 깨지 않는다. 한 줄은 `MAX_LINE_BYTES`(1 MiB, 값 배지 `기본값`: 문서 채널의 `MAX_MESSAGE_BYTES`와 같게 고른 값)까지이고 넘으면 그 줄 전체를 버리고 id 없는 `-32600` 하나로 답한 뒤 다음 줄을 읽는다.
- **화면과 같은 코어.** `python -m kinetra_engine.mcp --project <파일>`은 프로젝트 파일(C-03 `open_project`)을 `Hub`(C-05a)에 열고, Studio 화면이 따르는 문서 채널을 `ws://127.0.0.1:<port>`(루프백 고정, `--port`, 기본은 빈 포트)에 열고, stdio로 MCP를 받는다. 채널 주소는 stderr에 `document channel ws://127.0.0.1:<port> project <id>`로 나온다. 브라우저 페이지는 `--allowed-origin`으로 준 `Origin`만 붙을 수 있고, `Origin`을 보내지 않는 클라이언트는 언제나 붙는다(`Hub.serve`의 규칙 그대로).

## 쓰는 법 (Claude Code)

```
claude mcp add kinetra -- uv run --directory <저장소> python -m kinetra_engine.mcp --project <파일>.kinetra.json --id desk --port 8799 --allowed-origin http://localhost:5173
```

Claude Code가 서버를 띄우면 편집 도구 13개와 `request_run`, `request_verdict`까지 15개가 `mcp__kinetra__<도구>`로 보인다. Studio 화면은 `ws://127.0.0.1:8799`에 붙어 `desk`를 구독한다.

## SDK를 쓰지 않은 이유

MCP Python SDK(`mcp` 2.3.0, MIT, 라이선스로는 쓸 수 있다)는 stdio 서버에 쓰지 않는 HTTP·인증 의존성(starlette, uvicorn, httpx2, sse-starlette, python-multipart, pyjwt[crypto], opentelemetry-api, jsonschema, anyio 등)을 함께 요구한다. 이 서버에 필요한 것은 한 전송 위의 메서드 네 개(`initialize`, `ping`, `tools/list`, `tools/call`)라서 표준 라이브러리로 직접 구현했다. 새 의존성이 없으므로 원장 행도 없다.

## 한계 (숨기지 않는다)

- 편집은 이 프로세스의 `Hub`에만 있다. Claude Code가 서버를 끝내면 프로세스와 함께 사라진다. 저장은 C-03의 몫이고 이 명령은 저장하지 않는다.
- 이 명령은 그 자체가 프로젝트 하나의 코어다. 이미 떠 있는 다른 코어 프로세스에 붙는 길(문서 채널의 WebSocket 클라이언트로 붙는 MCP 서버)은 없다. S1의 코어 실행 방식이 정해지면 그쪽으로 옮길 수 있게 서버 본체(`McpServer`)는 전송과 떨어져 있다.
- 웹 Studio 화면은 아직 저장소에 없다(`apps/studio`). 그래서 "Studio 화면에 반영"은 부분 충족이다: G-08이 남긴 증거는 화면과 같은 문서 채널을 구독한 클라이언트가 받은 `applied`(`origin: "mcp"`)까지(프로토콜 수준)다. MCP로 낸 편집(Claude Code)이 Studio 화면에 반영되는 녹화/스크린샷은 웹 클라이언트에서 처음 Hub 문서를 그리는 B-05a(#110)의 DoD로 이월했다.
- SIGTERM으로 끝나면 문서 채널의 구독자는 닫기 프레임 없이 끊긴다(재접속 규칙 D6이 처리한다). stdin이 닫히면 정상으로 닫는다.
- Streamable HTTP 전송은 없다(원격 접속, 인증과 함께 정할 일).
