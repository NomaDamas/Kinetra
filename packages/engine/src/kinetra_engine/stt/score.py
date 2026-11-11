"""Scoring for the dictation comparison (I-01a): character and word error rate of recognised text against a reference.

The text normalisation follows the Whisper paper's appendix C procedure in spirit (NFKC, drop marks/symbols/punctuation,
lower-case, collapse whitespace). Numbers are NOT rewritten: "2킬로그램" against "이 킬로그램" counts as errors, because for a
command the digit and the Korean numeral are not interchangeable to the Command validator that reads the text next.

    CER  Levenshtein distance over characters with the spaces removed, divided by the reference length (spacing is a
         frequent Korean variation that does not change a command).
    WER  Levenshtein distance over space-separated words, divided by the reference word count (the paper's protocol).
"""

from __future__ import annotations

import json
import unicodedata
from pathlib import Path
from typing import Sequence


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).lower()
    text = "".join(" " if unicodedata.category(c)[0] in "MSP" else c for c in text)
    return " ".join(text.split())


def edit_distance(a: Sequence, b: Sequence) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def _rate(ref: Sequence, hyp: Sequence) -> float:
    if not ref:
        raise ValueError("reference is empty")
    return edit_distance(ref, hyp) / len(ref)


def cer(reference: str, hypothesis: str) -> float:
    return _rate(normalize(reference).replace(" ", ""), normalize(hypothesis).replace(" ", ""))


def wer(reference: str, hypothesis: str) -> float:
    return _rate(normalize(reference).split(), normalize(hypothesis).split())


def score_results(data: dict) -> dict[str, dict[str, dict[str, float]]]:
    """`{system: {group: {"n", "cer", "wer", "exact"}}}` for a results file (`docs/decisions/stt-results.json`).

    A group's CER/WER are micro-averaged (total edits over total reference length), not a mean of per-clip rates.
    `exact` is the number of clips whose normalised text equals the reference exactly.
    """
    refs = {c["id"]: (c["group"], c["reference"]) for c in data["cases"]}
    out: dict[str, dict[str, dict[str, float]]] = {}
    for name, system in data["systems"].items():
        acc: dict[str, list[float]] = {}
        for cid, (group, ref) in refs.items():
            hyp = system["texts"][cid]
            r_c, h_c = normalize(ref).replace(" ", ""), normalize(hyp).replace(" ", "")
            r_w, h_w = normalize(ref).split(), normalize(hyp).split()
            a = acc.setdefault(group, [0, 0, 0, 0, 0, 0])
            a[0] += 1
            a[1] += edit_distance(r_c, h_c)
            a[2] += len(r_c)
            a[3] += edit_distance(r_w, h_w)
            a[4] += len(r_w)
            a[5] += normalize(ref) == normalize(hyp)
        out[name] = {g: {"n": a[0], "cer": a[1] / a[2], "wer": a[3] / a[4], "exact": a[5]} for g, a in acc.items()}
    return out


def render(data: dict) -> str:
    scores = score_results(data)
    groups = sorted({g for s in scores.values() for g in s})
    lines = ["| 방식 | " + " | ".join(f"{g} CER / WER / 완전 일치" for g in groups) + " |", "|---|" + "---|" * len(groups)]
    for name, s in scores.items():
        cells = [f"{s[g]['cer'] * 100:.1f}% / {s[g]['wer'] * 100:.1f}% / {s[g]['exact']}/{s[g]['n']}" if g in s else "-" for g in groups]
        lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def load(path: Path | str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
