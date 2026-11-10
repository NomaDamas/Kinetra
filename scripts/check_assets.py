"""에셋과 원장 `assets/LEDGER.csv` 가 서로 어긋나지 않았는지 검사한다 (P0-05b). 표준 라이브러리만 쓴다.

    uv run python scripts/check_assets.py            # 저장소 루트의 원장을 검사한다
    uv run python scripts/check_assets.py --root DIR # 다른 저장소 트리를 검사한다(테스트용)

원장 읽기와 열·SPDX·날짜·해시 형식 검증은 `tools/assets/credits.py` 를 그대로 쓴다. 그 위에 더하는 검사:

    1. 원장 행 → 파일: `kind=asset` 행의 `경로` 는 저장소 안(루트 상대, `..` 와 절대 경로 없음)의 실제 파일이다.
       `kind=dependency` 행의 `경로` 도 실제로 있어야 한다(파일 또는 폴더).
    2. 파일 → 원장 행: `assets/` 와 `apps/**/public/` 아래의 모든 파일은 `kind=asset` 행의 `경로` 하나와 같다.
       (`assets/LEDGER.csv`, `.gitkeep`, `.DS_Store`, `node_modules/` 는 에셋이 아니다.)
    3. 해시: `변경 내역` 이 `없음` 으로 시작하는 asset 행은 파일의 sha256 이 `원본 해시` 와 같아야 한다.
       변경한 에셋(`변경 내역` 이 `없음` 이 아님)은 `원본 해시` 가 받은 원본의 것이라 저장소의 파일과 비교할 수 없다.
       그 행은 해시를 비교하지 않고 건너뛴 사실을 출력한다(성공 줄에 개수를 적는다).
    4. 같은 `경로` 를 가리키는 asset 행이 둘이면 실패한다.
    5. `CREDITS.md` 가 원장에서 만든 것과 같다(`tools/assets/credits.py --check` 와 같은 비교).

위반은 모두 모아 출력하고 하나라도 있으면 종료 코드 1이다. 원장 자체가 잘못이면 그 오류를 출력하고 1이다.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import credits  # noqa: E402

ASSET_DIR = "assets"
IGNORED_NAMES = frozenset({".gitkeep", ".DS_Store"})
IGNORED_DIRS = frozenset({"node_modules"})
LEDGER_REL = "assets/LEDGER.csv"
UNCHANGED_PREFIX = "없음"


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    assets: int = 0
    dependencies: int = 0
    hashed: int = 0
    hash_skipped: list[str] = field(default_factory=list)
    files: int = 0


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def normalize_rel(raw: str) -> str | None:
    """원장의 `경로` 를 저장소 루트 상대 POSIX 경로로 만든다. 저장소 밖을 가리키면 None."""
    if "\\" in raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        return None
    parts = raw.split("/")
    if any(p in ("", ".", "..") for p in parts):
        return None
    return "/".join(parts)


def product_files(root: Path) -> list[str]:
    """에셋이어야 하는 파일: `assets/` 와 `apps/**/public/` 아래의 파일(루트 상대 POSIX 경로)."""
    roots = [root / ASSET_DIR]
    apps = root / "apps"
    if apps.is_dir():
        roots += [p for p in sorted(apps.rglob("public")) if p.is_dir() and not set(p.relative_to(root).parts) & IGNORED_DIRS]
    found: set[str] = set()
    for base in roots:
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            rel = p.relative_to(root)
            if not p.is_file() or p.name in IGNORED_NAMES or set(rel.parts) & IGNORED_DIRS:
                continue
            found.add(rel.as_posix())
    found.discard(LEDGER_REL)
    return sorted(found)


def check(root: Path) -> Report:
    report = Report()
    ledger = root / ASSET_DIR / "LEDGER.csv"
    try:
        rows = credits.read_ledger(ledger)
    except (credits.LedgerError, OSError) as e:
        report.errors.append(f"원장을 읽을 수 없다: {e}")
        return report

    asset_paths: dict[str, str] = {}
    for row in rows:
        ident, raw, kind = row["에셋 ID"], row["경로"], row["kind"]
        rel = normalize_rel(raw)
        if rel is None:
            report.errors.append(f"{ident}: 경로 {raw!r} 가 저장소 안의 상대 경로가 아니다(절대 경로, '.', '..', 빈 칸, '\\' 금지)")
            continue
        target = root / rel
        if kind == "dependency":
            report.dependencies += 1
            if not target.exists():
                report.errors.append(f"{ident}: 의존성을 쓰는 경로 {rel} 가 없다")
            continue

        report.assets += 1
        if rel in asset_paths:
            report.errors.append(f"{ident}: 경로 {rel} 를 {asset_paths[rel]} 도 가리킨다(에셋 하나에 행 하나)")
            continue
        asset_paths[rel] = ident
        if not target.exists():
            report.errors.append(f"{ident}: 원장에 있는 파일 {rel} 가 없다")
        elif not target.is_file():
            report.errors.append(f"{ident}: 경로 {rel} 는 파일이 아니다(에셋은 파일 하나씩 적는다)")
        elif row["변경 내역"].startswith(UNCHANGED_PREFIX):
            report.hashed += 1
            actual = sha256_of(target)
            if actual != row["원본 해시"]:
                report.errors.append(f"{ident}: {rel} 의 해시가 원장과 다르다. 원장 {row['원본 해시']}, 실제 {actual}")
        else:
            report.hash_skipped.append(ident)

    files = product_files(root)
    report.files = len(files)
    for rel in files:
        if rel not in asset_paths:
            report.errors.append(f"{rel}: 원장(kind=asset)에 행이 없다. 출처와 라이선스를 {LEDGER_REL} 에 적는다")

    try:
        expected = credits.render(rows)
    except Exception as e:  # render 는 검증된 행만 받는다. 방어적으로 오류를 위반으로 바꾼다.
        report.errors.append(f"CREDITS.md 를 만들지 못했다: {e}")
    else:
        out = root / "CREDITS.md"
        current = out.read_text(encoding="utf-8") if out.exists() else None
        if current != expected:
            report.errors.append("CREDITS.md 가 원장과 다르다. `uv run python tools/assets/credits.py` 로 다시 만든다")
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT, help="검사할 저장소 루트(기본: 이 저장소)")
    args = ap.parse_args(argv)
    report = check(args.root.resolve())
    if report.errors:
        print(f"원장 검사 실패: 위반 {len(report.errors)}건", file=sys.stderr)
        for e in report.errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    skipped = f", 변경한 에셋이라 해시 비교를 건너뜀 {len(report.hash_skipped)}건" if report.hash_skipped else ""
    print(
        f"ok: 에셋 행 {report.assets}, 의존성 행 {report.dependencies}, 에셋 파일 {report.files}, "
        f"해시 대조 {report.hashed}건{skipped}, CREDITS.md 일치"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
