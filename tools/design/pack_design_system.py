#!/usr/bin/env python3
"""디자인 시스템 승인본 폴더의 design-system.zip을 다시 묶는다 (D0-02e).

    uv run python tools/design/pack_design_system.py            # design/exports/design-system/design-system.zip 을 쓴다
    uv run python tools/design/pack_design_system.py --check    # zip 안의 파일 내용이 폴더의 파일과 같은지만 본다

zip에 넣는 것: index.html, tokens.json, tokens.css, source/ 전체. 항목은 이름순, 시각은 2026-11-10 00:00 고정,
deflate 9, 권한 0644. README.md와 preview.png는 넣지 않는다. 압축 바이트는 zlib 버전에 따라 달라질 수 있어서
같은지는 항목 내용으로 비교한다.
"""
import sys
import zipfile
from pathlib import Path

EXPORT = Path(__file__).resolve().parents[2] / "design" / "exports" / "design-system"
FIXED_TIME = (2026, 11, 10, 0, 0, 0)


def members(root: Path = EXPORT) -> list[str]:
    names = ["index.html", "tokens.json", "tokens.css"]
    names += [p.relative_to(root).as_posix() for p in (root / "source").rglob("*") if p.is_file()]
    return sorted(names)


def pack(root: Path = EXPORT, out: Path | None = None) -> Path:
    out = out or root / "design-system.zip"
    with zipfile.ZipFile(out, "w") as z:
        for name in members(root):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            info.create_system = 3
            z.writestr(info, (root / name).read_bytes(), compresslevel=9)
    return out


def check(root: Path = EXPORT) -> list[str]:
    """zip과 폴더가 다른 곳을 문장으로 돌려준다. 비어 있으면 같다."""
    problems = []
    with zipfile.ZipFile(root / "design-system.zip") as z:
        in_zip = {i.filename for i in z.infolist()}
        want = set(members(root))
        problems += [f"zip에 없음: {n}" for n in sorted(want - in_zip)]
        problems += [f"폴더에 없음: {n}" for n in sorted(in_zip - want)]
        problems += [f"내용이 다름: {n}" for n in sorted(want & in_zip) if z.read(n) != (root / n).read_bytes()]
    return problems


if __name__ == "__main__":
    if "--check" in sys.argv:
        found = check()
        print("\n".join(found) if found else "ok: design-system.zip 내용이 폴더와 같다")
        raise SystemExit(1 if found else 0)
    print(pack())
