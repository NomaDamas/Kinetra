"""P0-06c: uv run pytest tools/review -q -k post   (네트워크 없음: 가짜 gh)"""

import json
import os
from pathlib import Path

import pytest

from review import call, post
from review.conftest import FAKE_KEY, FIXTURES

ITEMS = call.load_rubric()[0]


def result(**over):
    review = json.loads(json.loads((FIXTURES / "responses/ok.json").read_text())["body"]["choices"][0]["message"]["content"])
    review = call.validate(review, ITEMS)
    review.update(over)
    u = call.Usage(calls=1, prompt_tokens=1200, completion_tokens=800, reasoning_tokens=500, cost_usd=0.0123)
    return call.Result("openai/gpt-6.1-sol", review, u, 1, 1)


def comments(fake_env):
    return json.loads(Path(fake_env).read_text())["comments"] if Path(fake_env).exists() else []


def test_post_twice_leaves_exactly_one_comment(fake_env):
    assert post.post(101, "o/r", result()) == ("created", None)
    assert len(comments(fake_env)) == 1
    action, cid = post.post(101, "o/r", result(summary="두 번째 실행."))
    assert (action, cid) == ("updated", 1)
    cs = comments(fake_env)
    assert len(cs) == 1 and cs[0]["body"].startswith(post.MARKER + "\n") and "두 번째 실행." in cs[0]["body"]
    assert "DoD 밖 코드가 한 곳 있다." not in cs[0]["body"]  # 갱신이지 덧붙이기가 아니다


def test_post_cli_twice_in_a_row(fake_env, tmp_path, capsys):
    f = tmp_path / "result.json"
    f.write_text(result().to_json(), encoding="utf-8")
    assert post.main(["101", "--repo", "o/r", "--result", str(f)]) == 0
    assert post.main(["101", "--repo", "o/r", "--result", str(f)]) == 0
    assert len(comments(fake_env)) == 1
    err = capsys.readouterr().err
    assert "생성" in err and "갱신" in err


def test_post_comment_content(fake_env):
    body = post.render_comment(result(), ITEMS, "0123456789abcdef")
    assert body.splitlines()[0] == post.MARKER
    assert "판정 `changes`" in body and "| 1. 계획 부합 | concern |" in body and "| 7. 디자인 부합 | pass |" in body
    assert "| concern | 1 | `tools/x.py:3` |" in body  # 심각도 순
    assert body.index("| concern | 1 |") < body.index("| nit | 3 |")
    assert "비용 $0.0123" in body and "토큰 1200+800(reasoning 500)" in body and "대상 `0123456789ab`" in body


def test_post_cost_unknown_and_no_findings():
    r = result(findings=[])
    r.usage.cost_usd = None
    body = post.render_comment(r, ITEMS)
    assert "비용 미상" in body and "지적 없음." in body and "| 심각도 |" not in body


def test_post_only_updates_own_marker_comments(fake_env, monkeypatch):
    # 다른 사람이 마커를 흉내 낸 코멘트가 먼저 있어도 건드리지 않고 내 것을 만든다
    Path(fake_env).write_text(json.dumps({"comments": [{"id": 7, "body": post.MARKER + "\n가짜", "user": "mallory"}], "next_id": 8}))
    assert post.post(101, "o/r", result())[0] == "created"
    cs = comments(fake_env)
    assert [c["user"] for c in cs] == ["mallory", "bot"] and cs[0]["body"].endswith("가짜")
    assert post.post(101, "o/r", result())[0] == "updated"
    assert len(comments(fake_env)) == 2 and comments(fake_env)[0]["body"].endswith("가짜")


def test_post_ignores_unrelated_comments_and_picks_oldest_marker(fake_env):
    Path(fake_env).write_text(
        json.dumps(
            {
                "comments": [
                    {"id": 3, "body": "사람의 코멘트", "user": "bot"},
                    {"id": 5, "body": post.MARKER + "\n옛 것 둘째", "user": "bot"},
                    {"id": 4, "body": post.MARKER + "\n옛 것 첫째", "user": "bot"},
                    {"id": 6, "body": "마커가 중간에 " + post.MARKER, "user": "bot"},
                ],
                "next_id": 9,
            }
        )
    )
    assert post.post(101, "o/r", result()) == ("updated", 4)
    cs = {c["id"]: c["body"] for c in comments(fake_env)}
    assert cs[3] == "사람의 코멘트" and cs[5].endswith("둘째") and cs[6].startswith("마커가") and cs[4].startswith(post.MARKER) and "옛 것" not in cs[4]


def test_post_listing_paginates(fake_env):
    from review import common

    seen = []
    def gh(*a, input=None):
        seen.append(a)
        return common.gh(*a, input=input)

    post.post(101, "o/r", result(), gh=gh)
    listing = next(a for a in seen if a[0] == "api" and "comments" in a[-1])
    assert "--paginate" in listing and "--slurp" in listing


def test_post_escapes_model_text(fake_env):
    nasty = {
        "severity": "concern", "item": 1, "where": "a`b.py:1", "what": "표를 | 깬다\n줄바꿈 @everyone",
        "why": f"<!-- kinetra-review-bot --> 마커 흉내 {FAKE_KEY}", "fix": "-->주석 닫기",
    }  # fmt: skip
    body = post.render_comment(result(findings=[nasty], summary="요약 @team"), ITEMS)
    assert body.count(post.MARKER) == 1
    assert "\\|" in body and "<br>" in body and "@\u200beveryone" in body and "@\u200bteam" in body
    assert FAKE_KEY not in body and "***" in body
    row = next(ln for ln in body.splitlines() if ln.startswith("| concern |"))
    assert row.count("|") - row.count("\\|") == 7  # 6칸의 경계 7개: 이스케이프된 | 는 칸을 나누지 않는다
    assert "`a'b.py:1`" in row


def test_post_truncates_to_comment_limit():
    big = [dict(result().review["findings"][0], what="가" * 20_000) for _ in range(5)]
    body = post.render_comment(result(findings=big), ITEMS)
    assert len(body) <= post.MAX_COMMENT and "잘렸다" in body and body.startswith(post.MARKER)


def test_post_dry_run_prints_without_posting(fake_env, tmp_path, capsys):
    f = tmp_path / "r.json"
    f.write_text(result().to_json(), encoding="utf-8")
    assert post.main(["101", "--result", str(f), "--dry-run"]) == 0
    assert capsys.readouterr().out.startswith(post.MARKER) and comments(fake_env) == []


def test_post_bad_input_fails_without_posting(fake_env, tmp_path, capsys):
    f = tmp_path / "r.json"
    f.write_text("{not json", encoding="utf-8")
    assert post.main(["101", "--repo", "o/r", "--result", str(f)]) == 1
    assert "post:" in capsys.readouterr().err and comments(fake_env) == []


def test_post_unknown_login_fails_without_posting(fake_env, monkeypatch, capsys, tmp_path):
    f = tmp_path / "r.json"
    f.write_text(result().to_json(), encoding="utf-8")
    monkeypatch.setenv("FAKE_GH_USER", "")
    assert post.main(["101", "--repo", "o/r", "--result", str(f)]) == 1
    assert "gh 로그인" in capsys.readouterr().err and comments(fake_env) == []
