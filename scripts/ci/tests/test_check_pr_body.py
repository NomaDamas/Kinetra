"""uv run python -m unittest discover -s scripts/ci/tests -p "test_*.py" -v  (저장소 루트에서)

`scripts/ci/check_pr_body.py` 의 정상 예시 1종과 위반 예시(제목 없음, 원문 아님, Closes 없음 등)를 검사한다.
예시 본문은 `scripts/ci/tests/pr_body/` 에 파일로 있다.
"""
import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import check_pr_body as c  # noqa: E402

EXAMPLES = HERE / "pr_body"
VALUES = c.load_values()
V3 = "**V3 한 번에 100%** — 작은 단위를 증거와 함께 완전히 끝낸다. 부분 완성은 미완성이다."


def example(name: str) -> str:
    return (EXAMPLES / name).read_text(encoding="utf-8")


def body(goal="G0 — 대목표를 적었다.", value=f"> {V3} — 이 PR이 없으면: 표류한다.", link="Closes #13") -> str:
    parts = []
    if goal is not None:
        parts.append(f"## 대목표\n{goal}")
    if value is not None:
        parts.append(f"## 핵심 가치\n{value}")
    if link is not None:
        parts.append(f"## 문제\n{link}")
    return "\n".join(parts) + "\n"


class ExampleFileTests(unittest.TestCase):
    def test_good_example_passes(self):
        self.assertEqual(c.check(example("ok.md"), VALUES), [])

    def test_violating_examples_fail_with_the_expected_reason(self):
        cases = {
            "bad_no_goal.md": "`## 대목표` 제목이 없다",
            "bad_paraphrased_value.md": "원문 그대로",
            "bad_no_closes.md": "`Closes #N` 또는 `Refs #N`",
        }
        for name, needle in cases.items():
            with self.subTest(name):
                errors = c.check(example(name), VALUES)
                self.assertEqual(len(errors), 1, errors)
                self.assertIn(needle, errors[0])

    def test_pull_request_template_itself_is_rejected(self):
        template = (c.ROOT / ".github" / "pull_request_template.md").read_text(encoding="utf-8")
        errors = c.check(template, VALUES)
        self.assertTrue(any("원문 그대로" in e for e in errors), errors)
        self.assertTrue(any("Closes #N" in e for e in errors), errors)


class RuleTests(unittest.TestCase):
    def test_values_md_has_five_values(self):
        self.assertEqual(len(VALUES), 5)
        self.assertTrue(VALUES[0].startswith("V1 정직한 판정 — "))

    def test_each_of_v1_to_v5_is_accepted_as_quote(self):
        for v in VALUES:
            with self.subTest(v[:2]):
                self.assertEqual(c.check(body(value=f"> **{v[:2]}**{v[2:]} — 없으면: 막힌다"), VALUES), [])

    def test_empty_or_missing_body_fails(self):
        for text in ("", None, "\n\n"):
            with self.subTest(repr(text)):
                self.assertGreaterEqual(len(c.check(text, VALUES)), 3)

    def test_missing_goal_heading_or_empty_goal(self):
        self.assertTrue(any("대목표" in e for e in c.check(body(goal=None), VALUES)))
        self.assertTrue(any("비었다" in e for e in c.check(body(goal=""), VALUES)))

    def test_missing_values_heading(self):
        self.assertTrue(any("`## 핵심 가치` 제목이 없다" in e for e in c.check(body(value=None), VALUES)))

    def test_quote_must_be_verbatim_and_a_blockquote(self):
        altered = V3.replace("끝낸다", "끝낸다고 한다")
        self.assertTrue(c.check(body(value=f"> {altered}"), VALUES))
        self.assertTrue(c.check(body(value=V3), VALUES), "인용(`> `)이 아닌 본문은 인용이 아니다")
        self.assertTrue(c.check(body(value="> **V3 한 번에 100%**"), VALUES), "이름만 쓴 것은 원문이 아니다")

    def test_markup_and_spacing_do_not_matter(self):
        plain = V3.replace("**", "").replace(" ", "  ")
        self.assertEqual(c.check(body(value=f">{plain}"), VALUES), [])

    def test_closes_forms(self):
        for link in ("Closes #13", "Refs #13", "Closes #1"):
            with self.subTest(link):
                self.assertEqual(c.check(body(link=link), VALUES), [])
        for link in ("Closes #", "Closes #<잎 이슈 하나>", "closes #13", "Closes: #13", "Closes #13, #14", "see #13", "Closes #abc"):
            with self.subTest(link):
                self.assertTrue(c.check(body(link=link), VALUES))

    def test_two_closes_fail_but_closes_plus_refs_pass(self):
        self.assertTrue(any("하나만" in e for e in c.check(body(link="Closes #13\nCloses #14"), VALUES)))
        self.assertEqual(c.check(body(link="Closes #13\nRefs #8"), VALUES), [])

    def test_order_is_enforced(self):
        swapped = f"## 핵심 가치\n> {V3}\n## 대목표\nG0 — x\n## 문제\nCloses #13\n"
        self.assertTrue(any("대목표" in e and "앞에" in e for e in c.check(swapped, VALUES)))
        link_first = f"Closes #13\n## 대목표\nG0 — x\n## 핵심 가치\n> {V3}\n"
        self.assertTrue(any("뒤에 와야" in e for e in c.check(link_first, VALUES)))

    def test_comments_and_code_blocks_do_not_count(self):
        hidden = f"<!--\n## 대목표\nG0\n## 핵심 가치\n> {V3}\nCloses #13\n-->\n"
        self.assertGreaterEqual(len(c.check(hidden, VALUES)), 3)
        fenced = f"```\n## 대목표\nG0\n## 핵심 가치\n> {V3}\nCloses #13\n```\n"
        self.assertGreaterEqual(len(c.check(fenced, VALUES)), 3)

    def test_crlf_body(self):
        self.assertEqual(c.check(body().replace("\n", "\r\n"), VALUES), [])

    def test_quote_in_other_section_does_not_count(self):
        text = f"## 대목표\nG0\n## 핵심 가치\n없음\n## 문제\n> {V3}\nCloses #13\n"
        self.assertTrue(any("핵심 가치" in e for e in c.check(text, VALUES)))


class CliTests(unittest.TestCase):
    def run_main(self, argv, env=None):
        out, err = io.StringIO(), io.StringIO()
        old = dict(os.environ)
        os.environ.pop("PR_BODY", None)
        os.environ.update(env or {})
        try:
            with redirect_stdout(out), redirect_stderr(err):
                code = c.main(argv)
        finally:
            os.environ.clear()
            os.environ.update(old)
        return code, out.getvalue(), err.getvalue()

    def test_body_file_good_and_bad(self):
        self.assertEqual(self.run_main(["--body-file", str(EXAMPLES / "ok.md")])[0], 0)
        code, _, err = self.run_main(["--body-file", str(EXAMPLES / "bad_no_goal.md")])
        self.assertEqual(code, 1)
        self.assertIn("## 대목표", err)

    def test_env_body(self):
        self.assertEqual(self.run_main([], {"PR_BODY": example("ok.md")})[0], 0)
        self.assertEqual(self.run_main([], {"PR_BODY": ""})[0], 1)

    def test_no_input_is_usage_error(self):
        self.assertEqual(self.run_main([])[0], 2)

    def test_subprocess_exit_codes(self):
        script = str(HERE.parent / "check_pr_body.py")
        ok = subprocess.run([sys.executable, script, "--body-file", str(EXAMPLES / "ok.md")], capture_output=True, text=True)
        bad = subprocess.run([sys.executable, script, "--body-file", str(EXAMPLES / "bad_no_closes.md")], capture_output=True, text=True)
        self.assertEqual((ok.returncode, bad.returncode), (0, 1), bad.stderr)

    def test_broken_values_file_is_error(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "values.md"
            p.write_text("# x\n", encoding="utf-8")
            self.assertEqual(self.run_main(["--values", str(p), "--body-file", str(EXAMPLES / "ok.md")])[0], 2)


if __name__ == "__main__":
    unittest.main()
