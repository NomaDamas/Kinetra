"""uv run python -m unittest discover -s scripts/tests -p "test_scene_assets.py" -v  (저장소 루트에서)

W-02d: `assets/scene/` 의 지면 재질과 하늘은 Poly Haven·ambientCG 의 CC0 자료만이고, 행성마다 지면과 하늘이 있으며,
크기가 작다(텍스처 한 변 2048 이하, HDRI 가로 2048 이하). 원장 대조는 `scripts/check_assets.py` 가 하고, 여기서는 이 폴더의 정책만 본다.
표준 라이브러리만 쓴다.
"""

import struct
import sys
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "assets"))
import credits  # noqa: E402

SCENE = "assets/scene/"
PLANETS = ("earth", "mars", "moon")
CC0_HOSTS = {"polyhaven.com", "api.polyhaven.com", "dl.polyhaven.org", "ambientcg.com", "docs.ambientcg.com"}
MAX_SIDE = 2048
MAX_BYTES = 4 * 1024 * 1024


def jpeg_size(data: bytes) -> tuple[int, int]:
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            raise ValueError("JPEG 마커가 아니다")
        marker = data[i + 1]
        (length,) = struct.unpack(">H", data[i + 2 : i + 4])
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5 : i + 9])
            return w, h
        i += 2 + length
    raise ValueError("JPEG 크기 표지가 없다")


def radiance_size(data: bytes) -> tuple[int, int]:
    end = data.index(b"\n\n") + 2
    line = data[end : data.index(b"\n", end)].split()
    return int(line[3]), int(line[1])  # `-Y h +X w`


def exr_size(data: bytes) -> tuple[int, int]:
    i = 8
    while data[i] != 0:
        j = data.index(b"\0", i)
        name = data[i:j]
        k = data.index(b"\0", j + 1)
        (size,) = struct.unpack("<i", data[k + 1 : k + 5])
        value = data[k + 5 : k + 5 + size]
        if name == b"dataWindow":
            x0, y0, x1, y1 = struct.unpack("<4i", value)
            return x1 - x0 + 1, y1 - y0 + 1
        i = k + 5 + size
    raise ValueError("EXR dataWindow 가 없다")


class SceneAssetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        rows = credits.read_ledger(ROOT / "assets" / "LEDGER.csv")
        cls.rows = [r for r in rows if r["kind"] == "asset" and r["경로"].startswith(SCENE)]

    def test_every_planet_has_ground_maps_and_a_sky(self):
        for planet in PLANETS:
            paths = [r["경로"] for r in self.rows if r["경로"].startswith(f"{SCENE}{planet}/")]
            for suffix in ("_diff_1k.jpg", "_nor_gl_1k.jpg", "_rough_1k.jpg"):
                self.assertEqual(sum(p.endswith(suffix) for p in paths), 1, f"{planet}: {suffix}")
            self.assertEqual(sum(p.endswith((".hdr", ".exr")) for p in paths), 1, f"{planet}: HDRI")

    def test_only_cc0_from_polyhaven_or_ambientcg(self):
        self.assertTrue(self.rows)
        for r in self.rows:
            where = r["에셋 ID"]
            self.assertEqual(r["라이선스(SPDX)"], "CC0-1.0", where)
            hosts = {urlparse(u).hostname for u in r["원본 URL"].split()}
            self.assertTrue(hosts and hosts <= CC0_HOSTS, f"{where}: {hosts}")
            self.assertTrue(r["변경 내역"].startswith("없음"), f"{where}: 수정 없이 쓴 파일이어야 해시가 대조된다")

    def test_files_are_small(self):
        readers = {".jpg": jpeg_size, ".hdr": radiance_size, ".exr": exr_size}
        for r in self.rows:
            p = ROOT / r["경로"]
            self.assertLessEqual(p.stat().st_size, MAX_BYTES, r["경로"])
            w, h = readers[p.suffix](p.read_bytes())
            self.assertLessEqual(max(w, h), MAX_SIDE, f"{r['경로']}: {w}x{h}")


if __name__ == "__main__":
    unittest.main()
