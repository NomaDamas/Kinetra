#!/usr/bin/env python3
"""TTS per narration line with macOS `say`, measure with ffprobe, write timeline + concatenated narration.
Usage: build_audio.py [ko|en ...]   Cached by sha1(voice, rate, text) under out/film/cache."""
import hashlib, json, subprocess, sys, wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs/pitch/script.json"
PUB = ROOT / "apps/web/public/present"
CACHE = ROOT / "out/film/cache"
VOICES = {"ko": ("Yuna", 185), "en": ("Samantha", 175)}
LEAD = 1.2        # silence before first line
GAP_LINE = 0.45   # between lines in a scene
GAP_SCENE = 1.0   # between scenes
TAIL = 1.5
SR = 22050


def run(*a):
    subprocess.run(a, check=True)


def dur(p):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)]).decode())


def synth(lang, text):
    voice, rate = VOICES[lang]
    h = hashlib.sha1(f"{voice}|{rate}|{text}".encode()).hexdigest()[:16]
    CACHE.mkdir(parents=True, exist_ok=True)
    wav = CACHE / f"{lang}_{h}.wav"
    if not wav.exists():
        aiff = CACHE / f"{lang}_{h}.aiff"
        run("say", "-v", voice, "-r", str(rate), "-o", str(aiff), text)
        run("ffmpeg", "-y", "-v", "error", "-i", str(aiff), "-ar", str(SR), "-ac", "1", "-sample_fmt", "s16", str(wav))
        aiff.unlink()
    return wav


def build(lang):
    sc = json.loads(SCRIPT.read_text())
    t = LEAD
    lines, scenes, actions, wavs = [], [], [], []
    cur_t = 0.0
    segs = []  # (start, wav)
    for si, s in enumerate(sc["scenes"]):
        s_start = t if si else 0.0
        scenes.append(dict(id=s["id"], title=s["title"], slide=s["slide"], start=s_start))
        for li, n in enumerate(s["narration"]):
            w = synth(lang, n[lang])
            d = dur(w)
            lines.append(dict(id=n["id"], scene=s["id"], text=n[lang], start=round(t, 3), dur=round(d, 3), end=round(t + d, 3)))
            segs.append((t, w))
            for a in n["actions"]:
                actions.append(dict(a, t=round(t + a["at"], 3), line=n["id"], scene=s["id"]))
            t += d + (GAP_LINE if li < len(s["narration"]) - 1 else GAP_SCENE)
    total = round(t - GAP_SCENE + TAIL, 3)
    # concatenated narration at exact start offsets (sample-accurate)
    frames = bytearray(b"\x00\x00" * int(total * SR))
    for st, w in segs:
        with wave.open(str(w)) as wf:
            assert wf.getframerate() == SR and wf.getnchannels() == 1
            raw = wf.readframes(wf.getnframes())
        o = int(round(st * SR)) * 2
        frames[o:o + len(raw)] = raw
    PUB.mkdir(parents=True, exist_ok=True)
    wavp = PUB / f"narration.{lang}.wav"
    with wave.open(str(wavp), "wb") as wf:
        wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(SR); wf.writeframes(bytes(frames))
    m4a = PUB / f"narration.{lang}.m4a"
    run("ffmpeg", "-y", "-v", "error", "-i", str(wavp), "-c:a", "aac", "-b:a", "96k", str(m4a))
    wavp.unlink()
    tl = dict(lang=lang, voice=VOICES[lang][0], rate=VOICES[lang][1], total=total, audio=f"/present/narration.{lang}.m4a",
              tag=sc["meta"]["tag_ko" if lang == "ko" else "tag_en"], scenes=scenes, lines=lines, actions=sorted(actions, key=lambda a: a["t"]))
    (PUB / f"timeline.{lang}.json").write_text(json.dumps(tl, ensure_ascii=False, indent=1))
    print(lang, "total", total, "s; lines", len(lines), "actions", len(actions), "audio", round(dur(m4a), 2), "s")


if __name__ == "__main__":
    for l in (sys.argv[1:] or ["ko", "en"]):
        build(l)
