"""P0-06d: uv run pytest tools/review -q -k run   (scripts/review_pr.sh 를 진짜로 실행하되 gh·curl 은 가짜)"""

import json
import os
import subprocess
from pathlib import Path

import pytest

from review import common, post, run
from review.conftest import FAKE_KEY

SCRIPT = common.ROOT / "scripts" / "review_pr.sh"


def sh(tmp_path, *args, env_extra=None, drop_key=False):
    env = dict(os.environ)
    if drop_key:
        env.pop("OPENROUTER_API_KEY", None)
    env.update(env_extra or {})
    return subprocess.run(
        [str(SCRIPT), *args, "--out", str(tmp_path / "out"), "--cost-log", str(tmp_path / "cost.jsonl")],
        capture_output=True, text=True, env=env, cwd=common.ROOT, timeout=120,
    )  # fmt: skip


def comments(fake_env):
    return json.loads(Path(fake_env).read_text())["comments"]


def test_run_one_command_does_collect_call_post(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    p = sh(tmp_path, "101", "--repo", "o/r")
    assert p.returncode == 0, p.stderr
    assert "수집 완료" in p.stderr and "gpt-6.1-sol reasoning high" in p.stderr and "코멘트 생성" in p.stderr
    assert "토큰 1200+800(reasoning 500)" in p.stderr and "$0.0123" in p.stderr
    assert "판정: changes" in p.stdout and "[concern] 항목1 tools/x.py:3" in p.stdout
    (c,) = comments(fake_env)
    assert c["body"].startswith(post.MARKER)
    saved = json.loads((tmp_path / "out" / "pr-101.json").read_text())
    assert saved["review"]["verdict"] == "changes" and saved["usage"]["cost_usd"] == pytest.approx(0.0123)
    assert (tmp_path / "cost.jsonl").read_text().count("\n") == 1


def test_run_twice_updates_the_same_comment(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json", "ok.json")
    assert sh(tmp_path, "101", "--repo", "o/r").returncode == 0
    p = sh(tmp_path, "101", "--repo", "o/r")
    assert p.returncode == 0 and "코멘트 갱신" in p.stderr
    assert len(comments(fake_env)) == 1


def test_run_key_never_in_output_files_logs_or_argv(fake_env, curl_queue, tmp_path):
    """성공 경로와 실패 경로 모두에서 키가 어디에도 남지 않는다. 가짜 curl 은 서버처럼 키를 되돌려 말한다."""
    curl_queue("ok.json")
    ok = sh(tmp_path, "101", "--repo", "o/r")
    echo = {"status": 500, "body": f"error: invalid key {FAKE_KEY} / Authorization: Bearer {FAKE_KEY}"}
    q = Path(os.environ["FAKE_CURL_QUEUE"])
    for i in (3, 4):
        (q / f"{i}.json").write_text(json.dumps(echo))
    (q / "count").write_text("2")
    bad = sh(tmp_path, "101", "--repo", "o/r")
    assert bad.returncode == 1 and "run:" in bad.stderr and "***" in bad.stderr
    everything = ok.stdout + ok.stderr + bad.stdout + bad.stderr
    for f in (tmp_path / "out").rglob("*"):
        if f.is_file():
            everything += f.read_text()
    everything += (tmp_path / "cost.jsonl").read_text() + json.dumps(comments(fake_env))
    gh_log = Path(os.environ["FAKE_GH_LOG"]).read_text()
    curl_argv = "".join(json.dumps(c["argv"]) for c in curl_queue.log())
    assert FAKE_KEY not in everything and FAKE_KEY not in gh_log and FAKE_KEY not in curl_argv


def test_run_missing_key_stops_before_anything(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    p = sh(tmp_path, "101", "--repo", "o/r", drop_key=True)
    assert p.returncode == 2 and "OPENROUTER_API_KEY" in p.stderr
    assert curl_queue.count == 0 and not (tmp_path / "out").exists()
    assert not Path(os.environ["FAKE_GH_LOG"]).exists()  # gh 도 부르지 않았다


def test_run_no_post_does_not_touch_the_pr(fake_env, curl_queue, tmp_path):
    curl_queue("ok.json")
    p = sh(tmp_path, "101", "--repo", "o/r", "--no-post")
    assert p.returncode == 0 and "게시하지 않았다" in p.stderr
    assert not Path(fake_env).exists() and (tmp_path / "out" / "pr-101.json").exists()
    assert not any(json.loads(ln)[:2] == ["pr", "comment"] for ln in Path(os.environ["FAKE_GH_LOG"]).read_text().splitlines())


def test_run_failed_review_posts_nothing(fake_env, curl_queue, tmp_path):
    curl_queue("http_401.json")
    p = sh(tmp_path, "101", "--repo", "o/r")
    assert p.returncode == 1 and "HTTP 401" in p.stderr
    assert not Path(fake_env).exists() and not (tmp_path / "out" / "pr-101.json").exists()


def test_run_usage_and_bad_args(tmp_path):
    p = subprocess.run([str(SCRIPT)], capture_output=True, text=True, cwd=common.ROOT)
    assert p.returncode == 2 and "scripts/review_pr.sh" in p.stdout + p.stderr
    p = subprocess.run([str(SCRIPT), "--help"], capture_output=True, text=True, cwd=common.ROOT)
    assert p.returncode == 0 and "OPENROUTER_API_KEY" in p.stdout
    p = subprocess.run([str(SCRIPT), "abc"], capture_output=True, text=True, cwd=common.ROOT, env={**os.environ, "OPENROUTER_API_KEY": "x"})
    assert p.returncode == 2


def test_run_redacting_stream_masks_key_and_tokens(monkeypatch, capsys):
    import io, sys

    monkeypatch.setenv("OPENROUTER_API_KEY", FAKE_KEY)
    buf = io.StringIO()
    w = run._Redacting(buf)
    w.write(f"key={FAKE_KEY} Bearer abc.def sk-or-v1-zzzzzzzzzzzz ghp_{'a' * 20}\n")
    assert buf.getvalue() == "key=*** *** *** ***\n"


def test_run_script_never_takes_the_key_as_an_argument():
    for f in (SCRIPT, common.ROOT / "tools/review/run.py"):
        text = f.read_text(encoding="utf-8")
        assert "--key" not in text and "--api-key" not in text and "set -x" not in text
    assert 'OPENROUTER_API_KEY:-' in SCRIPT.read_text(encoding="utf-8")
