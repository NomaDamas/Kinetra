#!/usr/bin/env python3
"""Measure on-screen change onset vs. planned action time in the FINAL mp4 (frame diff at 20 fps, 160x90 gray).
Also compares audio vs video duration and dumps key frames to out/film/frames_<lang>/. Usage: verify_sync.py [lang]"""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out/film"
lang = (sys.argv[1:] or ["ko"])[0]
tl = json.loads((ROOT / f"apps/web/public/present/timeline.{lang}.json").read_text())
mp4 = OUT / f"kinetra-demo.{lang}.mp4"
FPS, Wd, Ht = 20, 160, 90
raw = subprocess.check_output(["ffmpeg", "-v", "error", "-i", str(mp4), "-vf", f"fps={FPS},scale={Wd}:{Ht},format=gray", "-f", "rawvideo", "-"])
fs = Wd * Ht
frames = [raw[i:i + fs] for i in range(0, len(raw) - fs + 1, fs)]


def diff(a, b):
    return sum(abs(x - y) for x, y in zip(a, b)) / fs


res = []
for a in tl["actions"]:
    t = a["t"]
    i0 = max(0, int((t - 0.6) * FPS)); ref = frames[i0]
    onset = None
    for i in range(i0 + 1, min(len(frames), int((t + 2.5) * FPS))):
        if diff(ref, frames[i]) > 1.5:
            onset = i / FPS; break
    res.append(dict(type=a["type"], line=a["line"], planned=t, onset=onset, offset_ms=None if onset is None else round((onset - t) * 1000)))
fd = OUT / f"frames_{lang}"; fd.mkdir(exist_ok=True)
for r in res:
    if r["onset"] is not None:
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{r['onset'] + 0.4:.2f}", "-i", str(mp4), "-frames:v", "1", str(fd / f"{r['line']}_{r['type']}.png")])
dur = lambda s: float(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", s, "-show_entries", "stream=duration", "-of", "csv=p=0", str(mp4)]).decode().split()[0])
rep = dict(video=dur("v:0"), audio=dur("a:0"), actions=res)
(OUT / f"sync_report.{lang}.json").write_text(json.dumps(rep, indent=1))
for r in res: print(r)
print("video", rep["video"], "audio", rep["audio"], "delta", round(abs(rep["video"] - rep["audio"]), 2))
