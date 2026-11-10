"""seed_issues 오프라인 테스트(가짜 gh): uv run --with pyyaml python -m unittest discover -s scripts/gh/tests -v"""
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import seed_issues  # noqa: E402

FIXTURE = HERE / "seed_fixture.yaml"
REAL = HERE.parents[2] / "docs" / "plan" / "issues.yaml"
SCRIPT = HERE.parent / "seed_issues.py"


class Env:
    def __init__(self, issues=None, labels=("type:epic", "type:task"), milestones=("S0",), **extra):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        shim = d / "gh"
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{HERE / "fake_gh_issues.py"}" "$@"\n')
        shim.chmod(shim.stat().st_mode | stat.S_IEXEC)
        self.state = d / "state.json"
        self.state.write_text(json.dumps({"labels": list(labels), "milestones": list(milestones),
                                          "issues": issues or [], "calls": []}))
        self.env = {**os.environ, "PATH": f"{d}{os.pathsep}{os.environ['PATH']}", "FAKE_GH_STATE": str(self.state), **extra}

    def run(self, *args, file=FIXTURE, expect=0):
        r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(file), "--delay", "0", *args],
                           env=self.env, capture_output=True, text=True)
        assert r.returncode == expect, (r.returncode, r.stdout, r.stderr)
        return r

    def data(self):
        return json.loads(self.state.read_text())

    def writes(self):
        """읽기가 아닌 호출만(POST/PATCH)."""
        return [c for c in self.data()["calls"] if "POST" in c or "PATCH" in c]

    def close(self):
        self.tmp.cleanup()


def by_title(data):
    return {i["title"].split("]")[0][1:]: i for i in data["issues"]}


class SeedTests(unittest.TestCase):
    def setUp(self):
        self.e = Env()
        self.addCleanup(self.e.close)

    def test_creates_all_links_parents_and_rewrites_dependencies(self):
        r = self.e.run()
        self.assertIn("items=4 create=4 link=3 rewrite=2 keep=", r.stdout)
        d = self.e.data()
        it = by_title(d)
        self.assertEqual(len(d["issues"]), 4)
        n = {k: v["number"] for k, v in it.items()}
        self.assertIsNone(it["E1"]["parent"])
        self.assertEqual(it["E1-01"]["parent"], n["E1"])
        self.assertEqual(it["E1-02"]["parent"], n["E1-01"])  # 하위의 하위도 부모 이슈로 연결
        self.assertEqual(it["E1-03"]["parent"], n["E1"])
        calls = self.e.writes()
        self.assertEqual(sum(1 for c in calls if "POST" in c and c[-3].endswith("/issues")), 4)
        self.assertEqual(sum(1 for c in calls if any(x.endswith("/sub_issues") for x in c)), 3)
        self.assertEqual(sum(1 for c in calls if "PATCH" in c), 2)  # 의존성 있는 이슈 둘
        # 의존성 번호 치환: 있는 절은 맨 위에 줄을 넣고, 없는 본문은 절을 덧붙인다
        self.assertTrue(it["E1-02"]["body"].startswith("## 문제\nq\n## 의존성\n선행: #%d (E1-01), #%d (E1)\n선행: E1-01" % (n["E1-01"], n["E1"])))
        self.assertTrue(it["E1-03"]["body"].endswith("## 의존성\n선행: #%d (E1-02)\n" % n["E1-02"]))
        self.assertEqual(it["E1-01"]["body"], "## 문제\np\n## 의존성\n선행: 없음 / 후속: E1-02")  # 의존성 없음: 본문 그대로
        # 마일스톤 번호와 라벨이 payload 로 갔다
        self.assertEqual(it["E1"]["milestone"], 1)
        self.assertEqual(it["E1-01"]["labels"], ["type:task"])

    def test_rerun_creates_nothing_and_changes_nothing(self):
        self.e.run()
        before = self.e.data()
        n_calls = len(before["calls"])
        r = self.e.run()
        self.assertIn("create=0 link=0 rewrite=0 keep=4", r.stdout)
        after = self.e.data()
        self.assertEqual({k: v for k, v in after.items() if k != "calls"}, {k: v for k, v in before.items() if k != "calls"})
        new_calls = after["calls"][n_calls:]
        self.assertFalse([c for c in new_calls if "POST" in c or "PATCH" in c], "두 번째 실행은 쓰기 호출이 없어야 한다")

    def test_dry_run_prints_plan_and_writes_nothing(self):
        r = self.e.run("--dry-run")
        self.assertIn("(dry-run)", r.stdout)
        self.assertIn("would create [E1]", r.stdout)
        self.assertIn("would link [E1-02] -> [E1-01]", r.stdout)
        self.assertIn("create=4 link=3 rewrite=2", r.stdout)
        self.assertEqual(self.e.data()["issues"], [])
        self.assertEqual(self.e.writes(), [])

    def test_resume_after_partial_run_fills_only_what_is_missing(self):
        # 앞선 실행이 E1, E1-01 만 만들고 끊겼다(연결·치환 전)
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "## 대목표\nG0\n## 의존성\n선행: 없음", "parent": None},
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "## 문제\np\n## 의존성\n선행: 없음 / 후속: E1-02", "parent": None},
        ])
        self.addCleanup(e.close)
        r = e.run()
        self.assertIn("create=2 link=3 rewrite=2", r.stdout)
        d = e.data()
        self.assertEqual(len(d["issues"]), 4)
        self.assertEqual(sorted(i["title"] for i in d["issues"]).count("[E1] epic"), 1)
        self.assertEqual(by_title(d)["E1-01"]["parent"], 1)

    def test_only_new_touches_only_issues_created_in_this_run(self):
        # E1-01 은 이미 있고 연결이 안 된 채다. --only-new 는 건드리지 않는다.
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "## 대목표\nG0", "parent": None},
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "## 문제\np", "parent": None},
        ])
        self.addCleanup(e.close)
        r = e.run("--only-new")
        self.assertIn("(only-new)", r.stdout)
        self.assertIn("create=2 link=2 rewrite=2", r.stdout)  # E1-02 -> E1-01, E1-03 -> E1
        d = e.data()
        it = by_title(d)
        self.assertIsNone(it["E1-01"]["parent"], "이미 있던 이슈는 연결하지 않는다")
        self.assertEqual(it["E1-01"]["body"], "## 문제\np")
        self.assertEqual(it["E1-02"]["parent"], 2)
        self.assertEqual(it["E1-03"]["parent"], 1)
        patched = [c for c in e.writes() if "PATCH" in c]
        self.assertEqual({c[c.index("-X") + 2].rsplit("/", 1)[1] for c in patched}, {str(it["E1-02"]["number"]), str(it["E1-03"]["number"])})

    def test_crlf_and_eof_heading_bodies_are_patched_once_then_rerun_is_zero_writes(self):
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "## 대목표\r\nG0\r\n## 의존성\r\n선행: 없음", "parent": None},
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "## 문제\r\np\r\n## 의존성", "parent": None},
            {"id": 9003, "number": 3, "title": "[E1-02] second", "body": "## 문제\nq\n## 의존성", "parent": None},
            {"id": 9004, "number": 4, "title": "[E1-03] third", "body": "## 문제\r\nr", "parent": None},
        ])
        self.addCleanup(e.close)
        e.run()
        it = by_title(e.data())
        self.assertEqual(it["E1-02"]["body"], "## 문제\nq\n## 의존성\n선행: #2 (E1-01), #1 (E1)\n")
        self.assertEqual(it["E1-03"]["body"], "## 문제\r\nr\r\n\r\n## 의존성\r\n선행: #3 (E1-02)\r\n")
        self.assertEqual(it["E1-03"]["body"].count("\n") - it["E1-03"]["body"].count("\r\n"), 0)  # 줄바꿈이 섞이지 않았다
        n = len(e.data()["calls"])
        e.run()
        again = e.data()["calls"][n:]
        self.assertEqual([c for c in again if "POST" in c or "PATCH" in c], [], "두 번째 실행은 쓰기가 없어야 한다")

    def test_existing_dependency_line_is_not_duplicated(self):
        self.e.run()
        d = self.e.data()
        it = by_title(d)
        self.assertEqual(it["E1-02"]["body"].count("선행: #"), 1)

    def test_existing_issue_in_other_parent_is_left_alone_with_warning(self):
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "b", "parent": None},
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "b", "parent": 77},
        ])
        self.addCleanup(e.close)
        r = e.run()
        self.assertIn("이미 repos/o/r/issues/77 의 하위 이슈다", r.stderr)
        self.assertEqual(by_title(e.data())["E1-01"]["parent"], 77)

    def test_same_number_parent_in_another_repo_is_not_relinked(self):
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "b", "parent": None},
            # 부모 번호는 #1 로 같지만 다른 저장소의 이슈다
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "b",
             "parent": "https://api.github.com/repos/other/repo/issues/1"},
        ])
        self.addCleanup(e.close)
        r = e.run("--repo", "o/r")
        self.assertIn("이미 repos/other/repo/issues/1 의 하위 이슈다", r.stderr)
        # 이 저장소의 #1 아래로 잇는 호출은 새로 만든 E1-03 하나뿐이다. E1-01 은 다시 잇지 않는다
        links = [c for c in e.data()["calls"] if "repos/o/r/issues/1/sub_issues" in c]
        self.assertEqual(len(links), 1)
        self.assertEqual(by_title(e.data())["E1-03"]["parent"], 1)
        self.assertEqual(by_title(e.data())["E1-01"]["parent"], "https://api.github.com/repos/other/repo/issues/1")

    def test_same_repo_parent_compares_case_insensitively_and_is_kept(self):
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "b", "parent": None},
            {"id": 9002, "number": 2, "title": "[E1-01] first", "body": "b",
             "parent": "https://api.github.com/repos/O/R/issues/1"},
        ])
        self.addCleanup(e.close)
        r = e.run("--repo", "o/r")
        self.assertNotIn("이미", r.stderr)

    def test_invalid_delay_fails_before_any_github_call(self):
        for bad in ("-1", "nan", "inf", "-inf", "abc"):
            with self.subTest(bad):
                e = Env()
                self.addCleanup(e.close)
                r = subprocess.run([sys.executable, str(SCRIPT), "--file", str(FIXTURE), "--delay", bad],
                                   env=e.env, capture_output=True, text=True)
                self.assertNotEqual(r.returncode, 0)
                self.assertIn("--delay", r.stderr)
                self.assertEqual(e.data()["calls"], [], "gh 를 한 번도 부르면 안 된다")

    def test_zero_delay_is_accepted(self):
        e = Env()
        self.addCleanup(e.close)
        e.run("--dry-run")  # Env.run 은 --delay 0 을 준다

    def test_pull_requests_are_not_issues(self):
        e = Env(issues=[{"id": 9001, "number": 1, "title": "[E1] pr with same title", "body": "b", "parent": None, "pr": True}])
        self.addCleanup(e.close)
        r = e.run()
        self.assertIn("create=4", r.stdout)

    def test_duplicate_titles_use_lowest_number_and_warn(self):
        e = Env(issues=[
            {"id": 9001, "number": 1, "title": "[E1] epic", "body": "b", "parent": None},
            {"id": 9005, "number": 5, "title": "[E1] epic again", "body": "b", "parent": None},
        ])
        self.addCleanup(e.close)
        r = e.run()
        self.assertIn("[E1] 제목의 이슈가 둘 이상", r.stderr)
        self.assertIn("create=3", r.stdout)
        self.assertEqual(by_title(e.data())["E1-01"]["parent"], 1)

    def test_missing_label_or_milestone_fails_before_creating_anything(self):
        for kw in ({"labels": ("type:epic",)}, {"milestones": ()}):
            e = Env(**kw)
            self.addCleanup(e.close)
            r = e.run(expect=1)
            self.assertIn("bootstrap.sh", r.stderr)
            self.assertEqual(e.writes(), [])

    def test_rate_limit_is_retried(self):
        e = Env(FAKE_GH_FAIL_ONCE="POST repos/o/r/issues")
        self.addCleanup(e.close)
        code = (
            "import sys; sys.path.insert(0, %r); import seed_issues as s; s.sleep = lambda x: None; "
            "sys.exit(s.main(['--file', %r, '--delay', '0']))" % (str(HERE.parent), str(FIXTURE))
        )
        r = subprocess.run([sys.executable, "-c", code], env=e.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("속도 제한", r.stderr)
        self.assertEqual(len(e.data()["issues"]), 4)

    def failing_post_calls(self, msg):
        e = Env(FAKE_GH_FAIL_ONCE="POST repos/o/r/issues", FAKE_GH_FAIL_MSG=msg)
        self.addCleanup(e.close)
        code = (
            "import sys; sys.path.insert(0, %r); import seed_issues as s; s.sleep = lambda x: None; "
            "sys.exit(s.main(['--file', %r, '--delay', '0']))" % (str(HERE.parent), str(FIXTURE))
        )
        r = subprocess.run([sys.executable, "-c", code], env=e.env, capture_output=True, text=True)
        posts = [c for c in e.data()["calls"] if "POST" in c and any(x.endswith("/issues") for x in c)]
        return r, posts, e

    def test_plain_permission_403_is_one_call_and_fails(self):
        for msg in ("gh: Resource not accessible by personal access token (HTTP 403)",
                    "gh: Must have admin rights to Repository. (HTTP 403)",
                    "HTTP 422: Validation Failed"):
            with self.subTest(msg):
                r, posts, e = self.failing_post_calls(msg)
                self.assertEqual(r.returncode, 1, r.stdout)
                self.assertEqual(len(posts), 1, "속도 제한이 아니면 다시 부르지 않는다")
                self.assertNotIn("속도 제한", r.stderr)
                self.assertIn("seed_issues: gh api -X POST repos/o/r/issues", r.stderr)
                self.assertEqual(e.data()["issues"], [])

    def test_rate_limit_responses_are_retried(self):
        for msg in ("gh: You have exceeded a secondary rate limit. (HTTP 403)",
                    "gh: API rate limit exceeded for user ID 1. (HTTP 403)",
                    "HTTP 403\nx-ratelimit-remaining: 0",
                    "HTTP 403\nRetry-After: 30",
                    "gh: Too Many Requests (HTTP 429)"):
            with self.subTest(msg):
                r, posts, e = self.failing_post_calls(msg)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertGreater(len(posts), 4, "한 번 실패한 호출을 다시 불렀어야 한다")
                self.assertIn("속도 제한", r.stderr)
                self.assertEqual(len(e.data()["issues"]), 4)


class SpecValidationTests(unittest.TestCase):
    def load(self, text):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as f:
            f.write(text)
        try:
            return seed_issues.load_items(Path(f.name))
        finally:
            os.unlink(f.name)

    BASE = ("labels: [{name: a, color: 111111, description: d}]\nmilestones: [{title: M, description: d}]\nitems:\n")

    def item(self, **over):
        d = {"id": "X-1", "title": "[X-1] t", "body": "b", "labels": ["a"], "milestone": "M", "parent": None, "depends_on": []}
        d.update(over)
        return "  - " + json.dumps(d, ensure_ascii=False) + "\n"

    def test_real_issues_yaml_loads(self):
        items = seed_issues.load_items(REAL)
        self.assertGreater(len(items), 300)
        self.assertEqual(len({i["id"] for i in items}), len(items))

    def test_rejects_bad_specs(self):
        cases = {
            "title prefix": self.item(title="[Y-1] t"),
            "duplicate id": self.item() + self.item(),
            "unknown label": self.item(labels=["zzz"]),
            "unknown milestone": self.item(milestone="Q"),
            "unknown parent": self.item(parent="NOPE"),
            "self parent": self.item(parent="X-1"),
            "unknown dep": self.item(depends_on=["NOPE"]),
            "empty body": self.item(body=" "),
            "bad id": self.item(id="a b", title="[a b] t"),
        }
        for name, text in cases.items():
            with self.subTest(name), self.assertRaises(seed_issues.SpecError):
                self.load(self.BASE + text)

    def test_dependency_heading_line_wise(self):
        f = seed_issues.with_dependency_line
        L = "선행: #1 (X)"
        # CRLF 본문: 제목을 찾고 줄바꿈 방식을 따른다
        self.assertEqual(f("a\r\n## 의존성\r\n선행: 없음", L), "a\r\n## 의존성\r\n" + L + "\r\n선행: 없음")
        # 제목이 파일 끝에 있고 줄바꿈이 없다
        self.assertEqual(f("a\n## 의존성", L), "a\n## 의존성\n" + L + "\n")
        self.assertEqual(f("a\r\n## 의존성", L), "a\r\n## 의존성\r\n" + L + "\r\n")
        self.assertEqual(f("a\n## 의존성\n", L), "a\n## 의존성\n" + L + "\n")
        # 제목 뒤 공백
        self.assertEqual(f("## 의존성  \nb", L), "## 의존성  \n" + L + "\nb")
        # 제목이 아닌 줄(문장 속, 더 깊은 제목, 인용)은 제목이 아니다 -> 절을 덧붙인다
        for body in ("본문에 ## 의존성 이라고 씀", "### 의존성\nx", "> ## 의존성\nx", "## 의존성 메모\nx"):
            out = f(body, L)
            self.assertTrue(out.startswith(body.rstrip("\n")), body)
            self.assertTrue(out.endswith("\n\n## 의존성\n" + L + "\n"), (body, out))

    def test_with_dependency_line(self):
        f = seed_issues.with_dependency_line
        self.assertEqual(f("a\n## 의존성\nb", "선행: #1 (X)"), "a\n## 의존성\n선행: #1 (X)\nb")
        self.assertEqual(f("a", "선행: #1 (X)"), "a\n\n## 의존성\n선행: #1 (X)\n")
        self.assertEqual(f("## 의존성\n\\1", "선행: #1 (X)"), "## 의존성\n선행: #1 (X)\n\\1")  # 역참조 문자가 안전하다


if __name__ == "__main__":
    unittest.main()
