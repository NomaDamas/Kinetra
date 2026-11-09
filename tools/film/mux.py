#!/usr/bin/env python3
"""Mux recorded webm + narration m4a, write SRT, burn subs (Hangul font) -> out/film/kinetra-demo.<lang>.mp4.
Trims the video head so film clock t=0 == output t=0 (offset = video_t0 from sync_log)."""
import json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "out/film"
PUB = ROOT / "apps/web/public/present"
FONT = "Apple SD Gothic Neo"


def st(s):
    ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


lang = (sys.argv[1:] or ["ko"])[0]
tl = json.loads((PUB / f"timeline.{lang}.json").read_text())
sl = json.loads((OUT / f"sync_log.{lang}.json").read_text())
off = sl["video_t0"]
webm = sorted((OUT / f"video_{lang}").glob("*.webm"), key=lambda p: p.stat().st_mtime)[-1]
srt = OUT / f"kinetra-demo.{lang}.srt"
srt.write_text("".join(f"{i+1}\n{st(l['start'])} --> {st(l['end'])}\n{l['text']}\n\n" for i, l in enumerate(tl["lines"])))
out = OUT / f"kinetra-demo.{lang}.mp4"
# subtitles: only burn if the pitch UI already shows them (presenter shows its own subtitle bar), so keep a clean mp4 + soft subs
subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{off:.3f}", "-i", str(webm), "-i", str(PUB / f"narration.{lang}.m4a"), "-i", str(srt),
                "-map", "0:v", "-map", "1:a", "-map", "2:s", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "20", "-r", "30", "-c:a", "aac", "-c:s", "mov_text",
                "-metadata:s:s:0", f"language={'kor' if lang == 'ko' else 'eng'}", str(out)], check=True)
dur = lambda p, s="": float(subprocess.check_output(["ffprobe", "-v", "error", "-select_streams", s or "v:0", "-show_entries", "stream=duration", "-of", "csv=p=0", str(p)]).decode().split()[0])
print(out, "video", dur(out, "v:0"), "audio", dur(out, "a:0"), "film total", tl["total"], "video_t0 offset", off)
