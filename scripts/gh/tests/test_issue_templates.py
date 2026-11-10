"""이슈 양식 검증(오프라인): uv run --with pyyaml python -m unittest discover -s scripts/gh/tests -v

GitHub issue forms 스키마 규칙(필수 키, body 요소 type/id/label, id 유일성, 드롭다운 옵션)과
Kinetra 규칙(필수 항목과 순서, values.md와 일치, 존재하는 라벨)을 검사한다.
"""
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
DIR = ROOT / ".github" / "ISSUE_TEMPLATE"
FORMS = ["epic", "work", "asset", "research", "design"]
ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
TYPES = {"markdown", "textarea", "input", "dropdown", "checkboxes"}
# 대목표 → 대목표 연결 → 핵심 가치 → 핵심 가치 원문 → 이것이 없으면 → 문제 → DoD → 범위 밖 → 검증 방법 → 의존성 (이 순서의 부분열)
COMMON_ORDER = [
    ("goal", "대목표"),
    ("goal-link", "대목표 연결"),
    ("values", "핵심 가치"),
    ("values-quote", "핵심 가치 원문"),
    ("without-this", "이것이 없으면 대목표의 무엇이 막히는가"),
    ("problem", "문제"),
    ("dod", "완료 정의 (DoD)"),
    ("out-of-scope", "범위 밖"),
    ("verification", "검증 방법"),
    ("dependencies", "의존성"),
]
EXTRA = {
    "asset": ["asset-id", "source-url", "author", "license", "usage", "attribution", "ledger", "license-gate"],
    "research": ["question", "measurement"],
    "design": ["brief-path", "export-path"],
}


def load(name):
    return yaml.safe_load((DIR / f"{name}.yml").read_text(encoding="utf-8"))


def label_names():
    spec = yaml.safe_load((ROOT / "docs" / "plan" / "issues.yaml").read_text(encoding="utf-8"))
    return {l["name"] for l in spec["labels"]}


class IssueFormTests(unittest.TestCase):
    def test_config_disables_blank_issues(self):
        cfg = yaml.safe_load((DIR / "config.yml").read_text(encoding="utf-8"))
        self.assertIs(cfg["blank_issues_enabled"], False)

    def test_only_expected_files(self):
        self.assertEqual(sorted(p.name for p in DIR.iterdir()), sorted([f"{f}.yml" for f in FORMS] + ["config.yml"]))

    def test_schema(self):
        known = label_names()
        names = set()
        for f in FORMS:
            with self.subTest(form=f):
                d = load(f)
                for key in ("name", "description", "body"):
                    self.assertIn(key, d)
                self.assertTrue(d["name"].strip())
                self.assertNotIn(d["name"], names)
                names.add(d["name"])
                self.assertTrue(d["description"].strip())
                for l in d.get("labels", []):
                    self.assertIn(l, known)
                body = d["body"]
                self.assertIsInstance(body, list)
                self.assertTrue(any(e["type"] != "markdown" for e in body))
                ids, labels = set(), set()
                for e in body:
                    self.assertIn(e["type"], TYPES)
                    a = e["attributes"]
                    if e["type"] == "markdown":
                        self.assertTrue(a["value"].strip())
                        self.assertNotIn("id", e)
                        self.assertNotIn("validations", e)
                        continue
                    self.assertRegex(e["id"], ID_RE)
                    self.assertNotIn(e["id"], ids)
                    ids.add(e["id"])
                    self.assertTrue(a["label"].strip())
                    self.assertNotIn(a["label"], labels)
                    labels.add(a["label"])
                    if e["type"] == "dropdown":
                        opts = a["options"]
                        self.assertTrue(opts and len(opts) == len(set(opts)))
                        self.assertNotIn("None", opts)
                        self.assertTrue(all(isinstance(o, str) and o.strip() for o in opts))
                    if e["type"] == "checkboxes":
                        self.assertTrue(a["options"])
                        for o in a["options"]:
                            self.assertTrue(o["label"].strip())
                    if e["type"] != "checkboxes":
                        self.assertIn("validations", e)
                    # 하나도 빠짐없이 필수다
                    if e["type"] == "checkboxes":
                        self.assertTrue(all(o.get("required") is True for o in a["options"]))
                    else:
                        self.assertIs(e["validations"]["required"], True)

    def test_required_fields_in_order(self):
        for f in FORMS:
            with self.subTest(form=f):
                els = [e for e in load(f)["body"] if e["type"] != "markdown"]
                ids = [e["id"] for e in els]
                pos = []
                for id_, label in COMMON_ORDER:
                    self.assertIn(id_, ids)
                    e = els[ids.index(id_)]
                    self.assertEqual(e["attributes"]["label"], label)
                    pos.append(ids.index(id_))
                self.assertEqual(pos, sorted(pos))
                for x in EXTRA.get(f, []):
                    self.assertIn(x, ids)
                    self.assertGreater(ids.index(x), pos[-1])  # 공통 항목 뒤에 온다

    def test_goal_and_values_match_values_md(self):
        text = (ROOT / "docs" / "plan" / "values.md").read_text(encoding="utf-8")
        goals = re.findall(r"^- \*\*(G\d)\*\* (.+)$", text, re.M)
        vals = re.findall(r"^- \*\*(V\d) ([^*]+)\*\*", text, re.M)
        self.assertEqual((len(goals), len(vals)), (6, 5))
        for f in FORMS:
            with self.subTest(form=f):
                by_id = {e["id"]: e for e in load(f)["body"] if "id" in e}
                self.assertEqual(by_id["goal"]["attributes"]["options"], [f"{c} {t}" for c, t in goals])
                self.assertEqual(by_id["values"]["attributes"]["options"], [f"{c} {t}" for c, t in vals])
                self.assertIs(by_id["values"]["attributes"].get("multiple"), True)
                # "이것이 없으면" 한 줄은 input이다
                self.assertEqual(by_id["without-this"]["type"], "input")


if __name__ == "__main__":
    unittest.main()
