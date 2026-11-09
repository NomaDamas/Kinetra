#!/usr/bin/env python3
"""Record the presenter in film mode with Playwright (system Chrome), then mux narration + subtitles with ffmpeg.
Prereq: cd apps/web && pnpm exec vite build -c vite.present.config.ts ; python3 tools/film/build_audio.py
Usage: tools/film/.venv/bin/python tools/film/record.py [ko|en]
Outputs out/film/kinetra-demo.<lang>.mp4, .srt, sync_log.<lang>.json"""
import functools, http.server, json, subprocess, sys, threading, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
SITE = ROOT / "out/film/site"
OUT = ROOT / "out/film"
PUB = ROOT / "apps/web/public/present"
W, H = 1280, 720
HANGUL_FONT = "Apple SD Gothic Neo"


def srt_time(s):
    ms = int(round(s * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); sec, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{sec:02},{ms:03}"


def main(lang):
    tl = json.loads((PUB / f"timeline.{lang}.json").read_text())
    shutil_sync(PUB, SITE / "present")  # make sure site has the latest timeline/audio
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(SITE))
    handler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    vdir = OUT / f"video_{lang}"
    for f in vdir.glob("*.webm") if vdir.exists() else []:
        f.unlink()
    with sync_playwright() as p:
        # Playwright launch() starts its OWN Chrome with a fresh temp profile; never attach to or kill the user's Chrome.
        b = p.chromium.launch(channel="chrome", headless=False, args=["--use-gl=angle", "--use-angle=metal", "--ignore-gpu-blocklist", "--autoplay-policy=no-user-gesture-required"])
        t_ctx = time.time()
        ctx = b.new_context(viewport={"width": W, "height": H}, record_video_dir=str(vdir), record_video_size={"width": W, "height": H})
        page = ctx.new_page()
        page.goto(f"http://127.0.0.1:{port}/present.html?film=1&lang={lang}")
        page.wait_for_function("typeof window.__filmStart === 'function'")
        page.wait_for_timeout(1500)  # app + bundle loaded
        t_wall0 = time.time()
        page.evaluate("window.__filmStart()")
        page.wait_for_function("window.__filmDone === true", timeout=int((tl["total"] + 60) * 1000), polling=500)
        page.wait_for_timeout(500)
        log = page.evaluate("window.__filmLog")
        wall = time.time() - t_wall0
        vpath = page.video.path()
        ctx.close(); b.close()
    srv.shutdown()
    (OUT / f"sync_log.{lang}.json").write_text(json.dumps(dict(video_t0=t_wall0 - t_ctx, wall=wall,  log=log), indent=1))
    print("recorded", vpath, "wall", round(wall, 1), "actions fired", len(log), "ok", sum(1 for l in log if l["ok"]))
    return vpath


def shutil_sync(src, dst):
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())


if __name__ == "__main__":
    lang = (sys.argv[1:] or ["ko"])[0]
    main(lang)
