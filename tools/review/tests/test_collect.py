"""P0-06a: uv run pytest tools/review -q -k collect"""

import json
from pathlib import Path

import pytest

from review import collect, common

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "pr101" / "snapshot.md"


def build(chunk_max=collect.CHUNK_MAX, max_chunks=collect.MAX_CHUNKS):
    return collect.collect(101, "o/r", chunk_max=chunk_max, max_chunks=max_chunks)


def test_collect_bundle_snapshot(fake_env):
    """고정 PR 픽스처의 묶음 스냅샷. 의도한 변경이면 UPDATE_SNAPSHOT=1 로 다시 만든다."""
    text = collect.render(build())
    import os

    if os.environ.get("UPDATE_SNAPSHOT"):
        SNAPSHOT.write_text(text, encoding="utf-8")
    assert text == SNAPSHOT.read_text(encoding="utf-8")


def test_collect_bundle_contents(fake_env):
    b = build()
    assert b.pr["number"] == 101 and b.pr["labels"] == ["type:infra"]
    assert [i["number"] for i in b.issues] == [77]
    assert "샘플 도구가 값을 돌려준다" in b.issues[0]["body"]
    assert b.labels == ["area:process", "stage:S0-process"]  # 이슈 라벨에서 고른다
    assert "V3 한 번에 100%" in b.values
    assert "이슈 DoD 체크박스" in b.done_definition


def test_collect_plan_sections_follow_labels(fake_env):
    heads = [s["heading"] for s in build().plan_sections]
    assert heads == ["## 1. 한 줄 정의", "## 12. 개발 루프", "### S0", "## 13. 비판"]
    texts = "".join(s["text"] for s in build().plan_sections)
    assert "하위 절" in texts  # ## 13 은 ### 13.1 을 품는다
    assert "코드 펜스 안이라" in texts  # 펜스 안의 ## 는 절을 끊지 않는다
    assert "결론 절은 선택되지 않는다" not in texts
    assert "S1 표는 선택되지 않는다" not in texts


def test_collect_every_mapped_section_exists_in_the_real_plan():
    plan = (common.ROOT / collect.PLAN_PATH).read_text(encoding="utf-8")
    keys = set(collect.ALWAYS_SECTIONS)
    for v in (*collect.STAGE_SECTIONS.values(), *collect.AREA_SECTIONS.values()):
        keys.update(v)
    missing = sorted(k for k in keys if collect.section(plan, k) is None)
    assert missing == []


def test_collect_missing_plan_section_is_an_error(fake_env, pr101_dir, monkeypatch):
    (pr101_dir / "contents/docs/plan/studio-plan.md").write_text("# 계획\n\n## 1. 하나\n", encoding="utf-8")
    monkeypatch.setenv("FAKE_GH_DIR", str(pr101_dir))
    with pytest.raises(common.ReviewError, match="12."):
        build()


def test_collect_excludes_generated_lock_bundle_assets(fake_env):
    b = build()
    excluded = {f["path"]: f["excluded"] for f in b.files if f["excluded"]}
    assert excluded == {"CREDITS.md": "생성물(assets/LEDGER.csv에서 생성)", "assets/models/box.glb": "에셋·바이너리", "pnpm-lock.yaml": "lock"}
    joined = "".join(b.diff_parts)
    assert "생성된 줄" not in joined and "lock: b" not in joined and "box.glb" not in joined
    assert "assets/LEDGER.csv" in joined  # 원장은 리뷰 대상이다
    assert "tools/sample/thing.py" in joined and "docs/process/sample.md" in joined


def test_collect_deleted_files_are_listed_without_content(fake_env):
    b = build()
    assert b.deleted == ["old/legacy.py"]
    assert 'print("older")' not in "".join(b.diff_parts)
    rendered = collect.render(b)
    assert "삭제된 파일 1개(내용 생략)\nold/legacy.py" in rendered
    row = next(f for f in b.files if f["path"] == "old/legacy.py")
    assert (row["status"], row["additions"], row["deletions"]) == ("deleted", 0, 2)


def test_collect_counts_added_and_removed_lines(fake_env):
    rows = {f["path"]: (f["status"], f["additions"], f["deletions"]) for f in build().files}
    assert rows["tools/sample/thing.py"] == ("modified", 2, 1)
    assert rows["docs/process/sample.md"] == ("added", 3, 0)


@pytest.mark.parametrize(
    "path,reason",
    [
        ("uv.lock", "lock"),
        ("apps/studio/pnpm-lock.yaml", "lock"),
        ("apps/studio/dist/app.js", "번들"),
        ("apps/studio/public/demo/a.json", "번들"),
        ("x/app.min.js", "번들"),
        ("assets/models/a.json", "에셋"),
        ("docs/pic.PNG", "에셋·바이너리"),
        ("assets/LEDGER.csv", None),
        ("docs/process/review-rubric.md", None),
        ("tools/review/collect.py", None),
    ],
)
def test_collect_exclusion_reason(path, reason):
    assert collect.exclusion_reason(path) == reason


def _file(path, n):
    return collect.FileChange(path, "modified", n, 0, None, f"diff --git a/{path} b/{path}\n" + "+" * n + "\n")


def test_collect_over_limit_splits_by_file_not_mid_file():
    files = [_file("a.py", 60), _file("b.py", 60), _file("c.py", 60)]
    parts, omitted, truncated = collect.pack(files, chunk_max=150, max_chunks=4)
    assert len(parts) == 3 and omitted == [] and truncated == []
    for p, name in zip(parts, "abc"):
        assert p.count("diff --git") == 1 and f"a/{name}.py" in p  # 파일이 부분 사이에서 쪼개지지 않는다
    assert all(len(p) <= 150 for p in parts)


def test_collect_small_files_share_a_part():
    files = [_file(f"f{i}.py", 20) for i in range(5)]
    parts, _, _ = collect.pack(files, chunk_max=200, max_chunks=4)
    assert len(parts) == 2 and sum(p.count("diff --git") for p in parts) == 5


def test_collect_single_oversized_file_is_truncated_and_named():
    parts, omitted, truncated = collect.pack([_file("big.py", 1000)], chunk_max=300, max_chunks=4)
    assert len(parts) == 1 and len(parts[0]) <= 300 and "잘렸다" in parts[0]
    assert truncated == ["big.py"] and omitted == []


def test_collect_part_limit_lists_omitted_files():
    files = [_file(f"f{i}.py", 100) for i in range(4)]
    parts, omitted, _ = collect.pack(files, chunk_max=150, max_chunks=2)
    assert len(parts) == 2
    assert [o["path"] for o in omitted] == ["f2.py", "f3.py"]


def test_collect_render_each_part(fake_env):
    b = build(chunk_max=420, max_chunks=4)
    assert len(b.diff_parts) >= 2
    for i in range(len(b.diff_parts)):
        assert f"부분 {i + 1}/{len(b.diff_parts)}" in collect.render(b, i)


def test_collect_bundle_json_roundtrip(fake_env):
    b = build()
    assert collect.Bundle.from_json(b.to_json()) == b
    assert json.loads(b.to_json())["pr"]["number"] == 101


def test_collect_linked_issues():
    f = collect.linked_issues
    assert f("Closes #5") == [5]
    assert f("closes: #5, fixes #6, Resolved #5") == [5, 6]
    assert f("see #9") == [] and f(None) == []
    assert f("Closes #1 Closes #2 Closes #3 Closes #4") == [1, 2, 3]


def test_collect_missing_issue_is_an_error(fake_env, pr101_dir, monkeypatch):
    pr = json.loads((pr101_dir / "pr.json").read_text())
    pr["body"] = "Closes #999"
    (pr101_dir / "pr.json").write_text(json.dumps(pr))
    monkeypatch.setenv("FAKE_GH_DIR", str(pr101_dir))
    with pytest.raises(common.ReviewError, match="issue"):
        build()


def test_collect_no_linked_issue_uses_pr_labels(fake_env, pr101_dir, monkeypatch):
    pr = json.loads((pr101_dir / "pr.json").read_text())
    pr.update(body="본문", labels=[{"name": "area:web"}, {"name": "stage:S1-studio"}])
    (pr101_dir / "pr.json").write_text(json.dumps(pr))
    monkeypatch.setenv("FAKE_GH_DIR", str(pr101_dir))
    b = build()
    assert b.issues == [] and b.labels == ["area:web", "stage:S1-studio"]
    assert "`Closes #N` 이 없다" in collect.render(b)


def test_collect_reads_plan_from_base_not_head(fake_env):
    log = Path(__import__("os").environ["FAKE_GH_LOG"])
    build()
    calls = [json.loads(ln) for ln in log.read_text().splitlines()]
    contents = [c[-1] for c in calls if c[0] == "api"]
    assert contents and all(c.endswith("?ref=main") for c in contents)


def test_collect_cli_prints_json(fake_env, capsys):
    assert collect.main(["101", "--repo", "o/r"]) == 0
    assert json.loads(capsys.readouterr().out)["pr"]["number"] == 101
