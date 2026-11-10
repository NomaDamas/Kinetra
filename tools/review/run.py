"""P0-06d 실행기 본체: 수집 → 호출 → 게시를 한 번에. 보통은 `scripts/review_pr.sh <PR>` 로 부른다.

    OPENROUTER_API_KEY=... scripts/review_pr.sh <PR> [--repo OWNER/REPO] [--no-post] [--out DIR] [--cost-log FILE]

    - 키는 환경변수 `OPENROUTER_API_KEY` 로만 받는다. 인자·파일로 받는 길이 없다.
    - 표준출력·표준오류는 전부 `redact()` 를 거친다(키 값, `sk-…`, `Bearer …`, GitHub 토큰). 하위 도구의 오류 문장까지 포함한다.
    - 결과 JSON(리뷰 + 토큰 + 비용)은 `--out`(기본 `out/review/`, .gitignore)에 `pr-<N>.json` 으로 남기고, 비용 기록은 `out/review-cost.jsonl`.
    - `--no-post` 는 PR 에 아무것도 쓰지 않고 결과만 출력한다.
종료 코드: 0 성공, 1 실패(메시지는 `run:` 으로 시작), 2 인자 오류.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import call, collect, common, post

DEFAULT_OUT = common.ROOT / "out" / "review"


class _Redacting:
    """쓰는 문자열마다 redact 를 거치는 스트림 래퍼."""

    def __init__(self, inner):
        self._inner = inner

    def write(self, s):
        return self._inner.write(common.redact(s))

    def flush(self):
        self._inner.flush()

    def __getattr__(self, name):
        return getattr(self._inner, name)


def run(pr: int, repo: str, *, do_post: bool = True, out_dir: Path = DEFAULT_OUT, cost_log: Path = call.DEFAULT_COST_LOG, gh=common.gh, transport=call.curl_transport) -> call.Result:
    common.api_key()  # 키가 없으면 gh 호출보다 먼저 멈춘다
    print(f"run: PR #{pr} ({repo}) 수집", file=sys.stderr)
    bundle = collect.collect(pr, repo, gh)
    n_diff = sum(len(p) for p in bundle.diff_parts)
    print(f"run: 수집 완료: 파일 {len(bundle.files)}개, diff {n_diff}자 {len(bundle.diff_parts)}부분, 계획 절 {len(bundle.plan_sections)}개, 이슈 {[i['number'] for i in bundle.issues]}", file=sys.stderr)
    print(f"run: {call.MODEL} reasoning high 호출", file=sys.stderr)
    result = call.review_bundle(bundle, transport=transport, cost_log=cost_log)
    u = result.usage
    cost = "미상" if u.cost_usd is None else f"${u.cost_usd:.4f}"
    print(f"run: 판정 {result.review['verdict']}, 지적 {len(result.review['findings'])}건, 토큰 {u.prompt_tokens}+{u.completion_tokens}(reasoning {u.reasoning_tokens}), 비용 {cost}", file=sys.stderr)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"pr-{pr}.json"
    path.write_text(common.redact(result.to_json()) + "\n", encoding="utf-8")
    print(f"run: 결과 저장 {path}", file=sys.stderr)
    if do_post:
        action, cid = post.post(pr, repo, result, bundle.pr["headRefOid"], gh)
        print(f"run: 코멘트 {'갱신' if action == 'updated' else '생성'}" + (f" (id {cid})" if cid else ""), file=sys.stderr)
    else:
        print("run: --no-post: 게시하지 않았다", file=sys.stderr)
    return result


def main(argv: list[str] | None = None) -> int:
    sys.stdout, sys.stderr = _Redacting(sys.stdout), _Redacting(sys.stderr)
    ap = argparse.ArgumentParser(prog="review_pr.sh", description="PR 하나를 수집·리뷰(OpenRouter gpt-6.1-sol, reasoning high)·게시한다. 키는 환경변수 OPENROUTER_API_KEY")
    ap.add_argument("pr", type=int, help="PR 번호")
    ap.add_argument("--repo", help="OWNER/REPO (기본: 현재 디렉터리의 gh 저장소)")
    ap.add_argument("--no-post", action="store_true", help="PR 에 게시하지 않고 결과만 저장·출력한다")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="결과 JSON 폴더 (기본: out/review)")
    ap.add_argument("--cost-log", type=Path, default=call.DEFAULT_COST_LOG, help="호출마다 토큰·비용을 덧붙이는 JSONL (기본: out/review-cost.jsonl)")
    args = ap.parse_args(argv)
    try:
        result = run(args.pr, args.repo or common.default_repo(), do_post=not args.no_post, out_dir=args.out, cost_log=args.cost_log)
    except common.ReviewError as e:
        print(f"run: {e}", file=sys.stderr)
        return 1
    r = result.review
    print(f"판정: {r['verdict']}")
    print("루브릭: " + " ".join(f"{k}:{v}" for k, v in r["rubric"].items()))
    for f in r["findings"]:
        print(f"- [{f['severity']}] 항목{f['item']} {f['where']}: {f['what']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
