"""P0-06c 코멘트 게시: 리뷰 결과를 PR 코멘트 하나로 남기고, 다시 실행하면 그 코멘트를 갱신한다. 표준 라이브러리와 `gh` 만 쓴다.

    PYTHONPATH=tools uv run python -m review.post <PR> [--result result.json|-] [--repo OWNER/REPO] [--dry-run]

    - 코멘트 첫 줄은 마커 `<!-- kinetra-review-bot -->`. 같은 PR 에서 마커로 시작하고 **지금 gh 로 로그인한 계정이 쓴** 코멘트를 찾아
      있으면 PATCH(갱신), 없으면 `gh pr comment` 로 만든다. 다른 사람이 마커를 흉내 내 올린 코멘트는 건드리지 않는다.
    - 같은 계정의 마커 코멘트가 여럿이면 가장 오래된 것을 갱신한다(자동으로 지우지 않는다).
    - 모델 출력은 표 안에서 깨지지 않게 이스케이프하고(`|`, 줄바꿈, `@` 멘션, 마커), GitHub 코멘트 상한(65536자) 안으로 자른다.
    - 모든 문자열은 `redact()` 를 거친다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Callable

from . import call, common

MARKER = "<!-- kinetra-review-bot -->"
MAX_COMMENT = 60_000  # GitHub 상한 65536 에서 여유를 둔다

GhFn = Callable[..., str]

_VERDICT_KO = {"approve": "승인", "changes": "수정 요청", "block": "차단"}
_ICON = {"pass": "pass", "concern": "concern", "block": "block"}


def esc(text: str) -> str:
    """표 칸에 넣을 문자열: 마크다운 표·멘션·마커를 무력화한다."""
    t = common.redact(str(text)).replace(MARKER, "")
    t = re.sub(r"<!--|-->", "", t)
    t = t.replace("|", "\\|").replace("@", "@\u200b")
    t = re.sub(r"\s*\n\s*", "<br>", t.strip())
    return t


def code(text: str) -> str:
    """표 칸에 넣는 코드 조각. 백틱은 작은따옴표로, `|` 는 `\\|` 로 바꿔 칸이 밀리지 않게 한다(GFM 은 코드 안에서도 `\\|` 를 `|` 로 읽는다)."""
    t = common.redact(str(text)).replace("`", "'").replace("|", "\\|")
    return "`" + re.sub(r"\s+", " ", t).strip() + "`"


def render_comment(result: call.Result, items: dict[str, str], head_sha: str | None = None) -> str:
    r = result.review
    u = result.usage
    cost = u.cost_text()
    lines = [
        MARKER,
        f"## Sol 리뷰 · 판정 `{r['verdict']}` ({_VERDICT_KO[r['verdict']]})",
        "",
        esc(r["summary"]).replace("<br>", "\n"),
        "",
        "| 항목 | 판정 |",
        "|---|---|",
        *(f"| {k}. {esc(items.get(k, ''))} | {_ICON[r['rubric'][k]]} |" for k in r["rubric"]),
        "",
    ]
    if r["findings"]:
        lines += ["| 심각도 | 항목 | 위치 | 내용 | 이유 | 제안 |", "|---|---|---|---|---|---|"]
        lines += [
            f"| {f['severity']} | {f['item']} | {code(f['where'])} | {esc(f['what'])} | {esc(f['why'])} | {esc(f['fix'])} |"
            for f in r["findings"]
        ]
    else:
        lines.append("지적 없음.")
    sha = f" · 대상 `{head_sha[:12]}`" if head_sha else ""
    lines += [
        "",
        f"<sub>{esc(result.model)}, reasoning high{sha} · 모델 요청 {result.attempts}회 · 토큰 {u.prompt_tokens}+{u.completion_tokens}(reasoning {u.reasoning_tokens}) · 비용 {cost} · diff 부분 {result.parts}개</sub>",
    ]
    text = "\n".join(lines) + "\n"
    if len(text) > MAX_COMMENT:
        cut = "\n\n_(코멘트 상한 때문에 잘렸다. 전체는 실행 로그의 JSON 에 있다)_\n"
        text = text[: MAX_COMMENT - len(cut)] + cut
    return text


def whoami(gh: GhFn) -> str:
    login = gh("api", "user", "--jq", ".login").strip()
    if not login:
        raise common.ReviewError("gh 로그인 계정을 알 수 없다(gh auth login)")
    return login


def find_comment(pr: int, repo: str, gh: GhFn) -> int | None:
    """내 계정이 쓴 마커 코멘트 중 가장 오래된 것의 id. 없으면 None."""
    me = whoami(gh)
    pages = json.loads(gh("api", "--paginate", "--slurp", f"repos/{repo}/issues/{pr}/comments?per_page=100"))
    mine = [
        c["id"]
        for page in pages
        for c in page
        if (c.get("body") or "").startswith(MARKER) and (c.get("user") or {}).get("login") == me
    ]
    return min(mine) if mine else None


def upsert(pr: int, repo: str, body: str, gh: GhFn = common.gh) -> tuple[str, int | None]:
    """('created'|'updated', 코멘트 id 또는 None). 갱신은 PATCH, 생성은 `gh pr comment`."""
    existing = find_comment(pr, repo, gh)
    if existing is not None:
        gh("api", "-X", "PATCH", f"repos/{repo}/issues/comments/{existing}", "--input", "-", input=json.dumps({"body": body}, ensure_ascii=False))
        return "updated", existing
    gh("pr", "comment", str(pr), "-R", repo, "--body-file", "-", input=body)
    return "created", None


def post(pr: int, repo: str, result: call.Result, head_sha: str | None = None, gh: GhFn = common.gh, *, rubric_path=call.RUBRIC_PATH) -> tuple[str, int | None]:
    items, _ = call.load_rubric(rubric_path)
    return upsert(pr, repo, render_comment(result, items, head_sha), gh)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="리뷰 결과 JSON(call 의 출력)을 PR 코멘트 하나로 게시·갱신한다")
    ap.add_argument("pr", type=int)
    ap.add_argument("--result", default="-", help="call 이 출력한 JSON 파일(기본: 표준입력)")
    ap.add_argument("--repo", help="OWNER/REPO (기본: 현재 디렉터리의 gh 저장소)")
    ap.add_argument("--head-sha", help="리뷰한 커밋(코멘트 하단에 표시)")
    ap.add_argument("--dry-run", action="store_true", help="게시하지 않고 코멘트 본문만 출력")
    args = ap.parse_args(argv)
    try:
        text = sys.stdin.read() if args.result == "-" else open(args.result, encoding="utf-8").read()
        result = call.Result.from_json(text)
        if args.dry_run:
            items, _ = call.load_rubric()
            sys.stdout.write(render_comment(result, items, args.head_sha))
            return 0
        repo = args.repo or common.default_repo()
        action, cid = post(args.pr, repo, result, args.head_sha)
    except (common.ReviewError, OSError, ValueError, KeyError, TypeError) as e:
        print(f"post: {common.redact(str(e))}", file=sys.stderr)
        return 1
    print(f"post: PR #{args.pr} 코멘트 {'갱신' if action == 'updated' else '생성'}" + (f" (id {cid})" if cid else ""), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
