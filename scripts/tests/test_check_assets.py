"""uv run python -m unittest discover -s scripts/tests -v  (저장소 루트에서)

`scripts/check_assets.py` 가 정상 트리를 통과시키고, 원장 누락·파일 누락·해시 불일치 등을 실패시키는지 본다.
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import check_assets as ca  # noqa: E402

credits = ca.credits
SCRIPT = HERE.parent / "check_assets.py"
CONTENT = b"glTF fake bytes"
HASH = "sha256:" + hashlib.sha256(CONTENT).hexdigest()


def row(ident="asset-rock-001", path="assets/props/rock.glb", change="없음", kind="asset", sha=HASH):
    return {
        "에셋 ID": ident,
        "경로": path,
        "원본 URL": "https://example.org/rock",
        "저작자": "Example Author",
        "라이선스(SPDX)": "CC0-1.0",
        "받은 날짜": "2026-01-02",
        "원본 해시": sha,
        "변경 내역": change,
        "용도": "시각",
        "표기 문구": "Rock by Example Author (CC0-1.0)",
        "확인자": "omp",
        "kind": kind,
    }


class Tree:
    """임시 저장소 트리: 파일과 원장, 그 원장에서 만든 CREDITS.md."""

    def __init__(self, test: unittest.TestCase, rows, files=None, credits_md=True):
        d = tempfile.TemporaryDirectory()
        test.addCleanup(d.cleanup)
        self.root = Path(d.name)
        for rel, data in (files if files is not None else {"assets/props/rock.glb": CONTENT}).items():
            self.write(rel, data)
        self.write_ledger(rows)
        if credits_md:
            self.write_credits()

    def write(self, rel: str, data: bytes = CONTENT):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)

    def write_ledger(self, rows):
        import csv

        p = self.root / "assets" / "LEDGER.csv"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(credits.COLUMNS)
            for r in rows:
                w.writerow([r[c] for c in credits.COLUMNS])

    def write_credits(self):
        (self.root / "CREDITS.md").write_text(credits.generate(self.root / "assets" / "LEDGER.csv"), encoding="utf-8")

    def check(self):
        return ca.check(self.root)


class OkTests(unittest.TestCase):
    def test_matching_tree_passes(self):
        rep = Tree(self, [row()]).check()
        self.assertEqual(rep.errors, [])
        self.assertEqual((rep.assets, rep.files, rep.hashed), (1, 1, 1))

    def test_empty_ledger_and_no_assets_passes(self):
        self.assertEqual(Tree(self, [], files={"assets/.gitkeep": b""}).check().errors, [])

    def test_gitkeep_ds_store_and_apps_node_modules_are_not_assets(self):
        files = {
            "assets/props/rock.glb": CONTENT,
            "assets/.gitkeep": b"",
            "assets/props/.DS_Store": b"x",
            "apps/studio/public/.gitkeep": b"",
            "apps/studio/node_modules/pkg/public/z.js": b"x",
        }
        self.assertEqual(Tree(self, [row()], files=files).check().errors, [])

    def test_node_modules_inside_asset_trees_still_needs_a_row(self):
        files = {"assets/props/rock.glb": CONTENT, "apps/studio/public/node_modules/x/y.js": b"x", "assets/node_modules/a.bin": b"x"}
        errors = Tree(self, [row()], files=files).check().errors
        self.assertEqual(sorted(e.split(":")[0] for e in errors), ["apps/studio/public/node_modules/x/y.js", "assets/node_modules/a.bin"])

    def test_modified_asset_skips_hash_and_says_so(self):
        rep = Tree(self, [row(change="리토폴로지 5만 삼각형 이하", sha="sha256:" + "0" * 64)]).check()
        self.assertEqual(rep.errors, [])
        self.assertEqual(rep.hash_skipped, ["asset-rock-001"])
        self.assertEqual(rep.hashed, 0)

    def test_dependency_rows_need_existing_path_but_no_hash_match(self):
        dep = row("dep-x-1.0", "tools/x.py", kind="dependency", sha="sha256:" + "1" * 64)
        files = {"assets/props/rock.glb": CONTENT, "tools/x.py": b"print()"}
        self.assertEqual(Tree(self, [row(), dep], files=files).check().errors, [])


class ViolationTests(unittest.TestCase):
    def assertOneError(self, rep, needle):
        self.assertEqual(len(rep.errors), 1, rep.errors)
        self.assertIn(needle, rep.errors[0])

    def test_ledger_row_without_file(self):
        t = Tree(self, [row()], files={"assets/.gitkeep": b""})
        self.assertOneError(t.check(), "원장에 있는 파일 assets/props/rock.glb 가 없다")

    def test_file_without_ledger_row_under_assets(self):
        t = Tree(self, [row()], files={"assets/props/rock.glb": CONTENT, "assets/hdri/sky.hdr": b"x"})
        self.assertOneError(t.check(), "assets/hdri/sky.hdr: 원장(kind=asset)에 행이 없다")

    def test_file_without_ledger_row_under_apps_public(self):
        files = {"assets/props/rock.glb": CONTENT, "apps/studio/public/logo.png": b"x", "apps/a/b/public/c.svg": b"x"}
        rep = Tree(self, [row()], files=files).check()
        self.assertEqual(sorted(e.split(":")[0] for e in rep.errors), ["apps/a/b/public/c.svg", "apps/studio/public/logo.png"])

    def test_hash_mismatch(self):
        t = Tree(self, [row(sha="sha256:" + "a" * 64)])
        self.assertOneError(t.check(), "해시가 원장과 다르다")
        self.assertIn(HASH, t.check().errors[0])

    def test_changed_file_content_is_caught_by_hash(self):
        t = Tree(self, [row()])
        t.write("assets/props/rock.glb", b"tampered")
        self.assertOneError(t.check(), "해시가 원장과 다르다")

    def test_dependency_path_missing(self):
        dep = row("dep-x-1.0", "tools/x.py", kind="dependency", sha="sha256:" + "1" * 64)
        self.assertOneError(Tree(self, [row(), dep]).check(), "tools/x.py 가 없다")

    def test_dependency_row_does_not_cover_an_asset_file(self):
        dep = row("dep-x-1.0", "assets/props/rock.glb", kind="dependency")
        rep = Tree(self, [dep]).check()
        self.assertOneError(rep, "assets/props/rock.glb: 원장(kind=asset)에 행이 없다")

    def test_path_escaping_root_or_absolute(self):
        for bad in ("../outside.glb", "/etc/passwd", "assets/../../x", "assets\\a.glb", "./assets/props/rock.glb", "assets//props/rock.glb"):
            with self.subTest(bad):
                rep = Tree(self, [row(path=bad)]).check()
                self.assertTrue(any("저장소 안의 상대 경로가 아니다" in e for e in rep.errors), rep.errors)

    def test_asset_path_is_a_directory(self):
        rep = Tree(self, [row(path="assets/props")]).check()
        self.assertTrue(any("파일이 아니다" in e for e in rep.errors), rep.errors)

    def test_two_rows_same_path(self):
        rows = [row(), row("asset-rock-002")]
        self.assertOneError(Tree(self, rows).check(), "도 가리킨다")

    def test_credits_out_of_sync_or_missing(self):
        t = Tree(self, [row()])
        (t.root / "CREDITS.md").write_text("stale\n", encoding="utf-8")
        self.assertOneError(t.check(), "CREDITS.md 가 원장과 다르다")
        (t.root / "CREDITS.md").unlink()
        self.assertOneError(t.check(), "CREDITS.md 가 원장과 다르다")

    def test_bad_ledger_is_reported(self):
        t = Tree(self, [row(sha="nothex")], credits_md=False)
        self.assertOneError(t.check(), "원장을 읽을 수 없다")

    def test_missing_ledger(self):
        t = Tree(self, [row()])
        (t.root / "assets" / "LEDGER.csv").unlink()
        self.assertOneError(t.check(), "원장을 읽을 수 없다")

    def test_all_violations_are_collected(self):
        files = {"assets/a.bin": b"1", "apps/s/public/b.bin": b"2"}
        rep = Tree(self, [row()], files=files).check()
        self.assertEqual(len(rep.errors), 3, rep.errors)  # 파일 누락 1 + 원장 누락 2


class SymlinkTests(unittest.TestCase):
    def link(self, t, rel, target):
        p = t.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.symlink_to(target)

    def outside(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        out = Path(d.name)
        (out / "secret.bin").write_bytes(CONTENT)
        (out / "dir").mkdir()
        (out / "dir" / "unlisted.glb").write_bytes(b"x")
        return out

    def test_directory_symlink_with_unlisted_file_is_a_violation(self):
        out = self.outside()
        t = Tree(self, [row()])
        self.link(t, "assets/linked", out / "dir")
        rep = t.check()
        self.assertEqual(len(rep.errors), 1, rep.errors)
        self.assertIn("assets/linked: 에셋 폴더 안의 심볼릭 링크", rep.errors[0])

    def test_file_symlink_and_broken_symlink_under_assets_and_public(self):
        out = self.outside()
        t = Tree(self, [row()])
        self.link(t, "assets/props/alias.glb", t.root / "assets/props/rock.glb")
        self.link(t, "assets/props/broken.glb", out / "nope")
        self.link(t, "apps/studio/public/x.png", out / "secret.bin")
        got = sorted(e.split(":")[0] for e in t.check().errors)
        self.assertEqual(got, ["apps/studio/public/x.png", "assets/props/alias.glb", "assets/props/broken.glb"])

    def test_apps_subdirectory_symlink_hiding_public_is_a_violation(self):
        t = Tree(self, [row()])
        (t.root / "demo" / "public").mkdir(parents=True)
        (t.root / "demo" / "public" / "unlisted.glb").write_bytes(b"x")
        self.link(t, "apps/demo", "../demo")
        rep = t.check()
        self.assertEqual([e.split(":")[0] for e in rep.errors], ["apps/demo"], rep.errors)

    def test_apps_itself_a_symlink(self):
        out = self.outside()
        t = Tree(self, [row()])
        self.link(t, "apps", out / "dir")
        self.assertEqual([e.split(":")[0] for e in t.check().errors], ["apps"])

    def test_file_symlinks_and_node_modules_symlinks_in_apps_outside_public_are_ignored(self):
        out = self.outside()
        t = Tree(self, [row()])
        self.link(t, "apps/studio/node_modules/pkg", out / "dir")  # pnpm 이 만드는 링크
        self.link(t, "apps/studio/README.md", out / "secret.bin")
        self.assertEqual(t.check().errors, [])

    def test_public_directory_itself_a_symlink(self):
        out = self.outside()
        t = Tree(self, [row()])
        self.link(t, "apps/studio/public", out / "dir")
        self.assertEqual([e.split(":")[0] for e in t.check().errors], ["apps/studio/public"])

    def test_assets_directory_symlink_is_not_followed(self):
        out = self.outside()
        t = Tree(self, [row()])
        import shutil

        shutil.rmtree(t.root / "assets" / "props")
        self.link(t, "assets/props", out / "dir")
        errors = t.check().errors
        self.assertTrue(any(e.startswith("assets/props: 에셋 폴더 안의 심볼릭 링크") for e in errors), errors)
        self.assertFalse(any("unlisted.glb" in e for e in errors), errors)

    def test_ledger_path_through_file_symlink_leaving_root(self):
        out = self.outside()
        t = Tree(self, [row(path="assets/props/rock.glb")], files={})
        self.link(t, "assets/props/rock.glb", out / "secret.bin")
        rep = t.check()
        self.assertTrue(any("저장소 밖을 가리킨다" in e for e in rep.errors), rep.errors)
        self.assertEqual(rep.hashed, 0)

    def test_ledger_path_through_parent_directory_symlink(self):
        out = self.outside()
        t = Tree(self, [row(path="assets/linked/unlisted.glb")], files={})
        self.link(t, "assets/linked", out / "dir")
        rep = t.check()
        self.assertTrue(any("assets/linked/unlisted.glb 가 심볼릭 링크를 지나 저장소 밖을" in e for e in rep.errors), rep.errors)

    def test_dependency_path_symlink_outside_root(self):
        out = self.outside()
        dep = row("dep-x-1.0", "tools/x.py", kind="dependency", sha="sha256:" + "1" * 64)
        t = Tree(self, [row(), dep])
        self.link(t, "tools/x.py", out / "secret.bin")
        self.assertTrue(any("dep-x-1.0" in e and "저장소 밖" in e for e in t.check().errors), t.check().errors)

    def test_symlink_inside_root_for_dependency_is_allowed(self):
        dep = row("dep-x-1.0", "tools/x.py", kind="dependency", sha="sha256:" + "1" * 64)
        t = Tree(self, [row(), dep], files={"assets/props/rock.glb": CONTENT, "tools/real.py": b"x"})
        self.link(t, "tools/x.py", "real.py")
        self.assertEqual(t.check().errors, [])


class CliTests(unittest.TestCase):
    def run_cli(self, root):
        return subprocess.run([sys.executable, str(SCRIPT), "--root", str(root)], capture_output=True, text=True)

    def test_exit_codes_and_messages(self):
        good = Tree(self, [row()])
        r = self.run_cli(good.root)
        self.assertEqual((r.returncode, r.stdout.startswith("ok:")), (0, True), r.stderr)
        good.write("assets/unlisted.bin", b"x")
        r = self.run_cli(good.root)
        self.assertEqual(r.returncode, 1)
        self.assertIn("assets/unlisted.bin", r.stderr)


if __name__ == "__main__":
    unittest.main()
