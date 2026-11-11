"""승인본의 source/ 로 index.html 을 다시 만들면 바이트가 같다 (D0-02e, #395).

    uv run pytest tools/design/tests -q   (저장소 루트에서)

원본 build_export.py 를 단언 그대로 돌린다. 느슨하게 고친 사본을 쓰지 않는다.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import pack_design_system as pack  # noqa: E402

EXPORT = pack.EXPORT
SOURCE = EXPORT / "source"
BUILDER = SOURCE / "tools" / "build_export.py"


def test_build_export_reproduces_index_html_byte_for_byte(tmp_path):
    result = subprocess.run(
        [sys.executable, str(BUILDER), str(SOURCE), str(tmp_path)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "index.html").read_bytes() == (EXPORT / "index.html").read_bytes()


def test_artboard_root_heights_match_canvas_json():
    canvas = json.loads((SOURCE / "canvas.json").read_text(encoding="utf-8"))
    assert set(canvas["order"]) == set(canvas["boards"])
    for name in canvas["order"]:
        text = (SOURCE / name).read_text(encoding="utf-8")
        root = re.search(r'<div style="width:(\d+)px;height:(\d+)px;', text)
        assert root, name
        board = canvas["boards"][name]
        assert (int(root[1]), int(root[2])) == (board["w"], board["h"]), name
        preview = re.search(r'"\$preview":\{"width":(\d+),"height":(\d+)\}', text)
        assert preview, name
        assert (int(preview[1]), int(preview[2])) == (board["w"], board["h"]), name


def test_zip_contents_match_folder():
    assert pack.check() == []
