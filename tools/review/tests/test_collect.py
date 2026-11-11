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


# ---------------------------------------------------------------- 리뷰 반영(#379 Sol 리뷰)

KEY = "sk-or-v1-FAKEKEYFORTESTS0123456789abcdef"


def with_fixture(pr101_dir, monkeypatch, pr=None, diff=None, issue=None, remove=(), write=None):
    if pr is not None:
        d = json.loads((pr101_dir / "pr.json").read_text())
        d.update(pr)
        (pr101_dir / "pr.json").write_text(json.dumps(d))
    if diff is not None:
        (pr101_dir / "diff.patch").write_text(diff, encoding="utf-8")
    if issue is not None:
        (pr101_dir / "issue-77.json").write_text(json.dumps(issue))
    for r in remove:
        (pr101_dir / "contents" / r).unlink()
    for k, v in (write or {}).items():
        (pr101_dir / "contents" / k).write_text(v, encoding="utf-8")
    monkeypatch.setenv("FAKE_GH_DIR", str(pr101_dir))


def test_collect_output_is_redacted_json_and_prompt(fake_env, pr101_dir, monkeypatch, capsys):
    secret_diff = (
        "diff --git a/tools/k.py b/tools/k.py\nindex 1..2 100644\n--- a/tools/k.py\n+++ b/tools/k.py\n@@ -1 +1,3 @@\n"
        f'-x = 1\n+KEY = "{KEY}"\n+H = "Authorization: Bearer abc.def-123-LONGTOKENVALUE0123"\n+T = "ghp_{"a" * 24}"\n'
    )
    with_fixture(pr101_dir, monkeypatch, pr={"body": f"Closes #77\n키 {KEY} sk-live-abcdefgh12345"}, diff=secret_diff)
    for argv in (["101", "--repo", "o/r"], ["101", "--repo", "o/r", "--prompt"]):
        assert collect.main(argv) == 0
        out = capsys.readouterr().out
        for leak in (KEY, "sk-live-abcdefgh12345", "abc.def-123-LONGTOKENVALUE0123", "ghp_" + "a" * 24):
            assert leak not in out, (argv, leak)
        assert "***" in out and "tools/k.py" in out
    assert KEY not in collect.render(build())  # 모델에 보내는 본문도 같다


QUOTED = (
    'diff --git "a/docs/\\355\\225\\234\\352\\270\\200.md" "b/docs/\\355\\225\\234\\352\\270\\200.md"\n'
    "new file mode 100644\nindex 0000000..1111111\n--- /dev/null\n"
    '+++ "b/docs/\\355\\225\\234\\352\\270\\200.md"\n@@ -0,0 +1,2 @@\n+한글\n+본문\n'
    'diff --git "a/tab\\there \\"q\\".txt" "b/tab\\there \\"q\\".txt"\nindex 1..2 100644\n--- "a/tab\\there \\"q\\".txt"\n+++ "b/tab\\there \\"q\\".txt"\n@@ -1 +1 @@\n-a\n+b\n'
    "diff --git a/with space.txt b/with space.txt\nindex 1..2 100644\n--- a/with space.txt\n+++ b/with space.txt\n@@ -1 +1 @@\n-a\n+b\n"
    'diff --git "a/old \\355\\225\\234.py" "b/new \\355\\225\\234.py"\nsimilarity index 90%\nrename from "old \\355\\225\\234.py"\nrename to "new \\355\\225\\234.py"\n--- "a/old \\355\\225\\234.py"\n+++ "b/new \\355\\225\\234.py"\n@@ -1 +1 @@\n-a\n+b\n'
    "diff --git a/plain.py b/plain.py\nindex 1..2 100644\n--- a/plain.py\n+++ b/plain.py\n@@ -1 +1 @@\n-a\n+b\n"
)


def test_collect_quoted_and_special_paths_are_kept():
    files = collect.parse_diff(QUOTED)
    assert [f.path for f in files] == ["docs/한글.md", 'tab\there "q".txt', "with space.txt", "new 한.py", "plain.py"]
    assert [(f.status, f.additions, f.deletions) for f in files] == [("added", 2, 0), ("modified", 1, 1), ("modified", 1, 1), ("renamed", 1, 1), ("modified", 1, 1)]
    assert all(f.text for f in files)  # 본문이 조용히 사라지지 않는다
    parts, omitted, _ = collect.pack(files)
    assert "한글" in parts[0] and "plain.py" in parts[0] and omitted == []


def test_collect_quoted_deleted_and_excluded_paths():
    raw = 'diff --git "a/\\355\\225\\234.glb" "b/\\355\\225\\234.glb"\nnew file mode 100644\nBinary files /dev/null and "b/\\355\\225\\234.glb" differ\n'
    (f,) = collect.parse_diff(raw)
    assert f.path == "한.glb" and f.excluded == "에셋·바이너리" and f.text == ""


@pytest.mark.parametrize(
    "line",
    ['diff --git "a/x b/x', 'diff --git "a/x\\q" "b/x"', 'diff --git "a/x\\777" "b/x"', "diff --git garbage", 'diff --git "a/x"', "diff --git a/x c/x"],
)
def test_collect_unparseable_header_is_an_error_not_skipped(line):
    with pytest.raises(common.ReviewError, match="헤더"):
        collect.parse_diff(line + "\nindex 1..2\n")


def test_collect_text_before_first_header_is_an_error():
    with pytest.raises(common.ReviewError, match="헤더로 시작하지"):
        collect.parse_diff("junk\n")


def test_collect_bad_header_stops_collect(fake_env, pr101_dir, monkeypatch):
    with_fixture(pr101_dir, monkeypatch, diff="diff --git garbage\n")
    with pytest.raises(common.ReviewError, match="헤더"):
        build()


@pytest.mark.parametrize("name", ["docs/plan/studio-plan.md", "docs/plan/values.md", "docs/process/done-definition.md"])
def test_collect_missing_required_file_404_is_an_error(fake_env, pr101_dir, monkeypatch, name):
    with_fixture(pr101_dir, monkeypatch, remove=[name])
    with pytest.raises(common.ReviewError, match=name.split("/")[-1] + ".*없다"):
        build()


@pytest.mark.parametrize("name", ["docs/plan/studio-plan.md", "docs/plan/values.md", "docs/process/done-definition.md"])
@pytest.mark.parametrize("content", ["", "  \n\n"])
def test_collect_empty_required_file_is_an_error(fake_env, pr101_dir, monkeypatch, name, content):
    with_fixture(pr101_dir, monkeypatch, write={name: content})
    with pytest.raises(common.ReviewError, match="비어 있다"):
        build()


def test_collect_issue_without_stage_area_labels_falls_back_to_pr_labels(fake_env, pr101_dir, monkeypatch):
    issue = {"number": 77, "title": "라벨 없는 이슈", "body": "본문", "labels": [{"name": "type:infra"}, {"name": "prio:P0"}]}
    with_fixture(pr101_dir, monkeypatch, issue=issue, pr={"labels": [{"name": "area:web"}, {"name": "stage:S1-studio"}, {"name": "type:infra"}]})
    b = build()
    assert [i["number"] for i in b.issues] == [77]
    assert b.labels == ["area:web", "stage:S1-studio"]
    heads = [s["heading"] for s in b.plan_sections]
    assert "### 4.1 화면 구조" in heads and "## 9. MVP 범위" in heads and "### S0" not in heads


def test_collect_issue_labels_win_over_pr_labels_and_first_labelled_issue_is_used(fake_env, pr101_dir, monkeypatch):
    with_fixture(pr101_dir, monkeypatch, pr={"labels": [{"name": "area:web"}]})
    assert build().labels == ["area:process", "stage:S0-process"]  # 이슈 라벨이 우선


# ---------------------------------------------------------------- 2차 리뷰 반영

PAT = "github_pat_11ABCDEFG0abcdefghij_KLMNOPQRSTUVWXYZ0123456789abcdefghijklmnopqrstuvwxyz"


@pytest.mark.parametrize(
    "token",
    [PAT, "ghp_" + "a" * 36, "gho_" + "b" * 36, "ghs_" + "c" * 36, "ghu_" + "d" * 36, "ghr_" + "e" * 36],
)
def test_collect_redacts_github_tokens_everywhere(fake_env, pr101_dir, monkeypatch, capsys, token):
    diff = f'diff --git a/t.py b/t.py\nindex 1..2 100644\n--- a/t.py\n+++ b/t.py\n@@ -1 +1,2 @@\n-a\n+T = "{token}"\n'
    with_fixture(pr101_dir, monkeypatch, pr={"body": f"Closes #77\n{token}", "title": f"제목 {token}"}, diff=diff)
    b = build()
    assert token not in collect.render(b) and token not in b.to_json()
    for argv in (["101", "--repo", "o/r"], ["101", "--repo", "o/r", "--prompt"]):
        assert collect.main(argv) == 0
        assert token not in capsys.readouterr().out


def test_collect_json_is_redacted_before_serialization_and_parses(fake_env, pr101_dir, monkeypatch, capsys):
    # 따옴표·역슬래시·개행이 섞인 비밀 주변 문자열도 JSON 이 깨지지 않아야 한다
    body = f'Closes #77\n"Authorization: Bearer abc.def-LONGTOKENVALUE012345"\\n 끝 {KEY} {PAT}\nquote " back \\ slash'
    diff = f'diff --git a/t.py b/t.py\nindex 1..2 100644\n--- a/t.py\n+++ b/t.py\n@@ -1 +1,2 @@\n-a\n+K = "Bearer zzz.yyy-LONGTOKENVALUE0123456"; X = "{KEY}"\n'
    with_fixture(pr101_dir, monkeypatch, pr={"body": body}, diff=diff)
    assert collect.main(["101", "--repo", "o/r"]) == 0
    out = capsys.readouterr().out
    data = json.loads(out)  # 파싱된다
    for leak in (KEY, PAT, "abc.def-LONGTOKENVALUE012345", "zzz.yyy-LONGTOKENVALUE0123456"):
        assert leak not in out and leak not in json.dumps(data, ensure_ascii=False)
    assert "***" in data["pr"]["body"] and 'quote " back \\ slash' in data["pr"]["body"]


def test_collect_redact_obj_handles_nesting_and_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    got = common.redact_obj({"a": [KEY, {KEY: ("x", KEY)}], "n": 3, "b": None})
    assert got == {"a": ["***", {"***": ["x", "***"]}], "n": 3, "b": None}


PLAN = "# P\n\n## 1. A\n\n" + "가" * 300 + "\n\n## 12. B\n\n" + "나" * 300 + "\n\n## 13. C\n\n" + "다" * 300 + "\n"


def test_collect_plan_cap_names_truncated_and_omitted_sections():
    out, omitted = collect.plan_excerpt(PLAN, ["area:process"], limit=400)
    assert [s["heading"] for s in out] == ["## 1. A", "## 12. B"]
    assert omitted == ["## 12. B (잘림)", "## 13. C (생략)"]
    assert "상한에서 잘림" in out[1]["text"]
    full, none = collect.plan_excerpt(PLAN, ["area:process"], limit=10_000)
    assert none == [] and len(full) == 3


def test_collect_plan_cap_with_missing_later_section_is_an_error_not_an_omission():
    plan = "# P\n\n## 1. A\n\n" + "가" * 300 + "\n\n## 12. B\n\n" + "나" * 300 + "\n"  # 13절 없음
    with pytest.raises(common.ReviewError, match="## 13."):
        collect.plan_excerpt(plan, ["area:process"], limit=100)  # 상한이 작아도 존재 검사가 먼저다


def test_collect_render_lists_plan_omitted(fake_env):
    b = build()
    b.plan_omitted = ["## 13. 비판 (생략)"]
    assert "상한 때문에 잘리거나 빠진 절\n## 13. 비판 (생략)" in collect.render(b)


@pytest.mark.parametrize(
    "plan,present,absent",
    [
        # 틸드 펜스
        ("## 1. A\n~~~\n## 안\n~~~\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 더 긴 백틱 펜스 안의 짧은 ``` 는 닫지 않는다
        ("## 1. A\n````\n```\n## 안\n```\n````\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 다른 문자는 닫지 않는다
        ("## 1. A\n```\n~~~\n## 안\n```\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 닫는 줄에 정보 문자열이 있으면 닫지 않는다
        ("## 1. A\n```\n```js\n## 안\n```\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 들여쓰기 3칸까지는 펜스
        ("## 1. A\n   ```\n## 안\n   ```\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 정보 문자열이 있는 여는 펜스
        ("## 1. A\n```python\n## 안\n```\n## 2. B\n", ["## 1.", "## 2."], ["## 안"]),
        # 닫히지 않은 펜스는 끝까지
        ("## 1. A\n```\n## 안\n## 2. B\n", ["## 1."], ["## 안", "## 2."]),
        # 백틱 펜스 여는 줄의 정보 문자열에 백틱이 있으면 펜스가 아니다(인라인 코드)
        ("## 1. A\n``` a `b`\n## 2. B\n", ["## 1.", "## 2."], []),
    ],
)
def test_collect_fence_tracking(plan, present, absent):
    heads = [ln for _, _, ln in collect._headings(plan)]
    for p in present:
        assert any(h.startswith(p) for h in heads), (p, heads)
    for a in absent:
        assert not any(h.startswith(a) for h in heads), (a, heads)


# ---------------------------------------------------------------- #428 마스킹이 코드 표현식을 바꾸지 않는다

CODE_EXPRESSIONS = [
    'headers = {"Authorization": f"Bearer {self._key}"}',
    'h = f"Bearer {key}"',
    'h = "Bearer " + os.environ["OPENROUTER_API_KEY"]',
    'h = "Bearer %s" % self._key',
    "curl -H 'Authorization: Bearer $OPENROUTER_API_KEY'",
    'h = f"Bearer {self._openrouter_api_key}"',
    "Authorization: Bearer self._openrouter_api_key_value",
    "Bearer token",
]


@pytest.mark.parametrize("code", CODE_EXPRESSIONS)
def test_redact_keeps_code_expressions_with_bearer(code, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert common.redact(code) == code
    assert common.redact_report(code) == (code, 0, [])


SECRET_SHAPED = [
    "sk-or-v1-" + "ab12" * 8,
    "github_pat_" + "A1b2C3d4E5" * 4,
    "ghp_" + "a" * 24,
]


@pytest.mark.parametrize("secret", SECRET_SHAPED)
def test_redact_masks_real_secret_shapes(secret, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    for text in (secret, f"Authorization: Bearer {secret}"):
        got = common.redact(text)
        assert secret not in got and "***" in got


def test_redact_masks_long_bearer_token_but_keeps_header_name(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    tok = "eyJhbGciOiJIUzI1NiJ9.e30.abc123def456ghi789"
    assert common.redact(f'curl -H "Authorization: Bearer {tok}"') == 'curl -H "Authorization: ***"'


def test_redact_report_counts_places_and_lines(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    text = f'a = 1\nh = f"Bearer {{self._key}}"\nk = "{KEY}"\nt = "ghp_{"b" * 24}" ; u = "ghp_{"c" * 24}"\n'
    out, n, lines = common.redact_report(text)
    assert n == 3 and lines == [3, 4]
    assert out.splitlines()[1] == 'h = f"Bearer {self._key}"'
    assert KEY not in out and "ghp_" not in out


def test_redact_report_does_not_double_count_overlapping_matches(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", KEY)
    out, n, lines = common.redact_report(f"Authorization: Bearer {KEY}\n")
    assert (n, lines) == (1, [1]) and KEY not in out


def test_render_without_masking_has_no_note(fake_env):
    text = collect.render(build())
    assert "마스킹 안내" not in text


def test_render_adds_masking_note_with_count_and_lines(fake_env, pr101_dir, monkeypatch):
    diff = (
        "diff --git a/t.py b/t.py\nindex 1..2 100644\n--- a/t.py\n+++ b/t.py\n@@ -1 +1,3 @@\n-a\n"
        '+H = f"Bearer {self._key}"\n+T = "ghp_' + "a" * 24 + '"\n'
    )
    with_fixture(pr101_dir, monkeypatch, diff=diff)
    text = collect.render(build())
    body, note = text.split("## 마스킹 안내\n")
    assert 'H = f"Bearer {self._key}"' in body and "ghp_" not in text
    assert "1곳" in note and "줄 1개" in note
    line_no = body.split("\n").index('+T = "***"') + 1
    assert f"- 줄 {line_no}: " in note and '+T = "***"' in note
    assert "결함으로 지적하지 않는다" in note


def test_system_prompt_explains_masking_note():
    from review import call

    assert "마스킹 안내" in call.INSTRUCTIONS
