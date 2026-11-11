# 명령 계층 MCP 서버 (G-08)

- 상태: 구현됨. 코드는 `packages/engine/src/kinetra_engine/mcp/`(`server.py`, `__main__.py`), 테스트는 `packages/engine/tests/test_mcp_server.py`(`uv run pytest packages/engine -q -k mcp`).
- 근거: `docs/plan/studio-plan.md` 4.4절("같은 명령을 MCP 서버로 내보내 Claude Code에서도 Studio를 조작한다")과 불변 결정 2("모든 편집은 Command다(MCP로도 노출)"), `docs/architecture/client-adapter.md` C1과 "프로세스 안의 발행자", `docs/architecture/agent-edit-tools.md`, 이슈 #155.
- 범위 밖: MCP를 통한 판정 변경(이슈의 범위 밖). 조회 도구(G-02b), 실행·판정 요청 도구(G-02c)는 그 이슈들이 도구를 더하면 이 서버의 목록에도 그대로 나온다.

## 규칙

- **같은 도구, 같은 길.** `tools/list`는 `edit_tools.specs()`를 MCP 도구 모양(`name`, `description`, 인자 스키마를 `inputSchema`로)으로 바꾼 것이고 더하거나 빼는 도구가 없다. `tools/call`은 `HubEditTools(hub, project_id, origin=Origin.MCP).call(name, arguments)`다. 앱 안의 에이전트가 부르는 것과 같은 함수라서 인자 스키마(`extra="forbid"`), 도구 안의 검사(`EditTools.run`; G-04의 권한 가드도 이 함수 안에 걸리므로 MCP 경로에 따로 붙일 것이 없다), `validate_command`(C-02c), `Hub.publish` 안의 문서 쪽 검증을 똑같이 거친다. MCP는 모델이 보낸 JSON 인자만 넘기고 다른 키워드 인자는 넘기지 않는다. 테스트는 같은 호출 11건(받아들여질 것 3건, 거부될 것 8건: 겹침, 행성 상수 필드, 판정 필드, 없는 부품, 숫자 자리의 문자열, 범위 밖 파라미터, 없는 재료, 없는 인스턴스)을 두 길로 보내 결과 JSON과 문서가 같음을 단언한다. 서버는 프로젝트를 쥐지 않고 직접 고치지 않는다.
- **발행자는 `mcp`.** 받아들여진 호출은 `Hub.publish`로 들어가 이력 항목의 `origin`과 모든 구독자(Studio 화면)에게 가는 `applied`의 `origin`이 `mcp`다. 한 호출이 이력 한 칸이다(G-02a).
- **판정과 상수는 없다.** 도구 스키마에는 행성 상수(`PLANET_CONSTANT_NAMES`)와 판정(`VERDICT_FIELD_NAMES`) 필드가 없고 서버는 도구를 더하지 않는다. 테스트가 `tools/list`의 스키마에서 그 이름들을 찾는다.
- **거부는 도구 결과다.** 검증기의 사유는 `isError: true`인 결과로 돌아간다. `ToolResult.to_json()`을 `structuredContent`와 같은 내용의 텍스트(`content[0]`)로 함께 실어 모델이 읽고 다시 시도할 수 있다. 모르는 도구, 객체가 아닌 `arguments`, `params`가 객체가 아님은 JSON-RPC `-32602`, 모르는 메서드는 `-32601`, JSON이 아닌 줄은 `-32700`, JSON-RPC 2.0이 아닌 메시지와 배치(배열)는 `-32600`이다(MCP 2025-11-25 "Error Handling").
- **수명 주기.** `initialize` 전에는 `ping`만 답하고 나머지 요청은 `-32600`이다. 버전은 `2025-11-25`와 `2025-06-18`을 말한다. 클라이언트가 다른 버전을 청하면 가장 새 것으로 답하고 계속할지는 클라이언트가 정한다(MCP "Version Negotiation"). 배치를 허용하던 `2025-03-26` 이하는 일부러 뺐다. 알림(`notifications/initialized`, `notifications/cancelled` 등)과 응답에는 답하지 않는다. 서버가 클라이언트에 보내는 요청은 없다.
- **로컬 전용.** 전송은 stdio 하나다(MCP "stdio"): 클라이언트가 이 프로세스를 띄우고 유일한 상대가 된다. MCP를 위해 여는 소켓이 없다. 한 줄에 UTF-8 JSON-RPC 메시지 하나이고, stdout에는 MCP 메시지만 쓴다. 보내는 줄은 ASCII다(ASCII가 아닌 글자는 JSON의 `\uXXXX` 이스케이프로 쓴다): JSON은 짝 없는 서로게이트(`"\ud800"`)를 쓸 수 있고 요청 id는 그대로 되돌려 보내므로, UTF-8로 인코딩할 수 없는 글이 답에 실려도 서버가 멈추지 않는다(테스트). 실행 명령은 시작할 때 stdout 디스크립터를 따로 떼어 MCP 전송에 쓰고 원래 stdout을 stderr로 돌려, 어떤 `print`도 MCP 스트림을 깨지 않는다. 한 줄은 `MAX_LINE_BYTES`(1 MiB, 값 배지 `기본값`: 문서 채널의 `MAX_MESSAGE_BYTES`와 같게 고른 값)까지이고 넘으면 그 줄 전체를 버리고 id 없는 `-32600` 하나로 답한 뒤 다음 줄을 읽는다.
- **화면과 같은 코어.** `python -m kinetra_engine.mcp --project <파일>`은 프로젝트 파일(C-03 `open_project`)을 `Hub`(C-05a)에 열고, Studio 화면이 따르는 문서 채널을 `ws://127.0.0.1:<port>`(루프백 고정, `--port`, 기본은 빈 포트)에 열고, stdio로 MCP를 받는다. 채널 주소는 stderr에 `document channel ws://127.0.0.1:<port> project <id>`로 나온다. 브라우저 페이지는 `--allowed-origin`으로 준 `Origin`만 붙을 수 있고, `Origin`을 보내지 않는 클라이언트는 언제나 붙는다(`Hub.serve`의 규칙 그대로).

## 쓰는 법 (Claude Code)

```
claude mcp add kinetra -- uv run --directory <저장소> python -m kinetra_engine.mcp --project <파일>.kinetra.json --id desk --port 8799 --allowed-origin http://localhost:5173
```

Claude Code가 서버를 띄우면 도구 13개가 `mcp__kinetra__<도구>`로 보인다. Studio 화면은 `ws://127.0.0.1:8799`에 붙어 `desk`를 구독한다.

## SDK를 쓰지 않은 이유

MCP Python SDK(`mcp` 2.3.0, MIT, 라이선스로는 쓸 수 있다)는 stdio 서버에 쓰지 않는 HTTP·인증 의존성(starlette, uvicorn, httpx2, sse-starlette, python-multipart, pyjwt[crypto], opentelemetry-api, jsonschema, anyio 등)을 함께 요구한다. 이 서버에 필요한 것은 한 전송 위의 메서드 네 개(`initialize`, `ping`, `tools/list`, `tools/call`)라서 표준 라이브러리로 직접 구현했다. 새 의존성이 없으므로 원장 행도 없다.

## 한계 (숨기지 않는다)

- 편집은 이 프로세스의 `Hub`에만 있다. Claude Code가 서버를 끝내면 프로세스와 함께 사라진다. 저장은 C-03의 몫이고 이 명령은 저장하지 않는다.
- 이 명령은 그 자체가 프로젝트 하나의 코어다. 이미 떠 있는 다른 코어 프로세스에 붙는 길(문서 채널의 WebSocket 클라이언트로 붙는 MCP 서버)은 없다. S1의 코어 실행 방식이 정해지면 그쪽으로 옮길 수 있게 서버 본체(`McpServer`)는 전송과 떨어져 있다.
- 웹 Studio 화면은 아직 저장소에 없다(`apps/studio`). 그래서 "Studio 화면에 반영"은 부분 충족이다: G-08이 남긴 증거는 화면과 같은 문서 채널을 구독한 클라이언트가 받은 `applied`(`origin: "mcp"`)까지(프로토콜 수준)다. MCP로 낸 편집(Claude Code)이 Studio 화면에 반영되는 녹화/스크린샷은 웹 클라이언트에서 처음 Hub 문서를 그리는 B-05a(#110)의 DoD로 이월했다.
- SIGTERM으로 끝나면 문서 채널의 구독자는 닫기 프레임 없이 끊긴다(재접속 규칙 D6이 처리한다). stdin이 닫히면 정상으로 닫는다.
- Streamable HTTP 전송은 없다(원격 접속, 인증과 함께 정할 일).
