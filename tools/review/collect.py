"""P0-06a 수집: 리뷰어에게 줄 문맥을 한 묶음으로 만든다. 표준 라이브러리만 쓴다.

    uv run python -m review.collect <PR> [--repo OWNER/REPO]      (PYTHONPATH=tools)

묶음(Bundle)에 들어가는 것
    - PR 제목·본문·라벨, `Closes #N` 이슈의 제목·본문·라벨
    - 기준 브랜치(base)의 `docs/plan/values.md`, `docs/process/done-definition.md`
    - 이슈(없으면 PR)의 stage·area 라벨에 맞는 `docs/plan/studio-plan.md` 절 (ALWAYS + STAGE_SECTIONS + AREA_SECTIONS)
    - PR diff: 생성물·lock·번들·에셋은 뺀다(변경 파일 표에는 제외 사유와 함께 남긴다). 순수 삭제 파일은 이름만 남긴다.
      상한(CHUNK_MAX)을 넘으면 파일 단위로 나눠 부분(part) 여러 개로 만든다. 한 파일이 상한보다 크면 그 파일만 자른다.

계획·가치·완료 정의는 PR 머리가 아니라 기준 브랜치에서 읽는다. 리뷰 대상 PR이 심판 기준을 바꾸지 못하게 하려는 것이다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from dataclasses import asdict, dataclass, field
from typing import Callable

from . import common

GhFn = Callable[..., str]

VALUES_PATH = "docs/plan/values.md"
PLAN_PATH = "docs/plan/studio-plan.md"
DONE_PATH = "docs/process/done-definition.md"

CHUNK_MAX = 120_000  # diff 부분 하나의 글자 수 상한
MAX_CHUNKS = 4  # 부분 수 상한. 넘는 파일은 omitted 에 이름만 남긴다
PLAN_MAX = 40_000  # 계획 발췌 전체 글자 수 상한

ALWAYS_SECTIONS = ["## 1.", "## 12."]
STAGE_SECTIONS = {
    "S0-process": ["### S0"],
    "S1-studio": ["## 9.", "### S1"],
    "S2-mission": ["## 10.", "### S2 이후"],
    "S3-manga": ["## 10.", "### S2 이후"],
    "S4-multi": ["## 10.", "### S2 이후"],
    "S5-kit": ["## 10.", "### S2 이후"],
}
AREA_SECTIONS = {
    "process": ["## 13."],
    "design": ["### 4.7", "## 7."],
    "core": ["### 5.1", "### 5.3"],
    "engine": ["### 5.3", "### 5.4"],
    "parts": ["### 5.3", "## 9."],
    "world": ["### 5.3", "## 9."],
    "judge": ["### 4.5", "### 5.3"],
    "web": ["### 4.1", "### 4.2"],
    "xr": ["### 4.3", "### 5.2"],
    "input": ["### 4.3"],
    "ai": ["### 4.4"],
    "media": ["### 4.6"],
    "assets": ["### 5.3", "## 6."],
    "server": ["### 5.3"],
    "biz": ["## 10."],
    "fluid": ["## 15."],
    "combat": ["## 15."],
    "hardware": ["## 15."],
}

_LOCK_NAMES = {"pnpm-lock.yaml", "uv.lock", "package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock", "bun.lockb"}
_GENERATED_NAMES = {"CREDITS.md": "생성물(assets/LEDGER.csv에서 생성)", "pytest-report.xml": "생성물"}
_BUNDLE_DIRS = ("dist", "out", "build")
_BUNDLE_SUFFIXES = (".min.js", ".min.css", ".map")
_BINARY_SUFFIXES = (
    ".glb", ".gltf", ".bin", ".stl", ".step", ".stp", ".obj", ".fbx", ".blend", ".usd", ".usdz",
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".ktx2", ".hdr", ".exr",
    ".mp4", ".webm", ".mov", ".mp3", ".ogg", ".wav", ".woff", ".woff2", ".ttf", ".pdf", ".zip", ".tar", ".gz",
)  # fmt: skip
_LEDGER = "assets/LEDGER.csv"  # 에셋 폴더 안에서도 이것은 리뷰 대상이다


def exclusion_reason(path: str) -> str | None:
    """diff 에서 뺄 파일이면 사유, 아니면 None."""
    parts = path.split("/")
    name = parts[-1]
    low = path.lower()
    if name in _LOCK_NAMES:
        return "lock"
    if name in _GENERATED_NAMES:
        return _GENERATED_NAMES[name]
    if any(p in _BUNDLE_DIRS for p in parts[:-1]) or low.endswith(_BUNDLE_SUFFIXES) or "/public/demo/" in "/" + path:
        return "번들"
    if low.endswith(_BINARY_SUFFIXES):
        return "에셋·바이너리"
    if parts[0] == "assets" and path != _LEDGER and name != ".gitkeep":
        return "에셋"
    return None


@dataclass
class FileChange:
    path: str
    status: str  # added | modified | deleted | renamed
    additions: int
    deletions: int
    excluded: str | None = None  # 제외 사유
    text: str = field(default="", repr=False)  # 이 파일의 diff 본문(제외·삭제면 비어 있음)

    def row(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k != "text"}


@dataclass
class Bundle:
    repo: str
    pr: dict
    issues: list[dict]
    labels: list[str]  # 계획 절을 고른 stage·area 라벨
    values: str | None
    done_definition: str | None
    plan_sections: list[dict]  # {"heading", "text"}
    files: list[dict]
    deleted: list[str]
    omitted: list[dict]  # 상한 때문에 diff 를 못 넣은 파일 {"path","reason"}
    truncated: list[str]  # 한 파일이 상한보다 커서 잘린 파일
    diff_parts: list[str]

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Bundle":
        return cls(**json.loads(text))


# ---------------------------------------------------------------- diff

_C_ESC = {"a": 7, "b": 8, "f": 12, "n": 10, "r": 13, "t": 9, "v": 11, '"': 34, "\\": 92}


def _unquote(text: str, pos: int) -> tuple[str, int]:
    """`text[pos]` 의 `"` 로 시작하는 git C 인용 문자열을 읽어 (값, 끝 다음 위치). 닫는 `"` 가 없거나 모르는 이스케이프면 ValueError."""
    assert text[pos] == '"'
    out = bytearray()
    i = pos + 1
    while i < len(text):
        c = text[i]
        if c == '"':
            return out.decode("utf-8", errors="backslashreplace"), i + 1
        if c != "\\":
            out += c.encode("utf-8")
            i += 1
            continue
        i += 1
        if i >= len(text):
            break
        c = text[i]
        if c in _C_ESC:
            out.append(_C_ESC[c])
            i += 1
        elif c in "01234567":
            j = i
            while j < len(text) and j < i + 3 and text[j] in "01234567":
                j += 1
            val = int(text[i:j], 8)
            if val > 255:
                raise ValueError("8진수 이스케이프가 255를 넘는다")
            out.append(val)
            i = j
        else:
            raise ValueError(f"모르는 이스케이프 \\{c}")
    raise ValueError("닫는 따옴표가 없다")


def parse_header(line: str, block: str = "") -> tuple[str, str]:
    """`diff --git <a경로> <b경로>` 줄에서 (a경로, b경로). git 은 특수문자·비 ASCII 경로를 `"a/\\355..."` 처럼 인용한다.
    인용 안 된 경로는 공백을 품을 수 있어, a·b 가 같으면 그 분할을, 이름이 바뀐 경우는 `rename to` 줄로 푼다. 못 풀면 ReviewError."""
    prefix = "diff --git "
    rest = line[len(prefix):] if line.startswith(prefix) else ""
    try:
        if rest.startswith('"'):
            first, pos = _unquote(rest, 0)
            if rest[pos : pos + 1] != " ":
                raise ValueError("두 번째 경로가 없다")
            second_raw = rest[pos + 1 :]
            second = _unquote(second_raw, 0)[0] if second_raw.startswith('"') else second_raw
        else:
            split = rest.find(' "b/')
            if split > 0 and rest.startswith("a/") and rest.endswith('"'):  # 앞은 평문, 뒤만 인용
                first, second = rest[:split], _unquote(rest, split + 1)[0]
            else:
                cands = [m.start() for m in re.finditer(r" b/", rest)]
                same = [i for i in cands if rest[:i] and rest[2:i] == rest[i + 3 :]] if rest.startswith("a/") else []
                if same:
                    first, second = rest[: same[0]], rest[same[0] + 1 :]
                elif len(cands) == 1 and rest.startswith("a/"):
                    first, second = rest[: cands[0]], rest[cands[0] + 1 :]
                else:
                    mt = re.search(r"^rename to (.*)$", block, re.M)
                    if not mt or not rest.startswith("a/") or not rest.endswith("b/" + _maybe_unquote(mt.group(1))):
                        raise ValueError("경로를 나눌 수 없다")
                    new = _maybe_unquote(mt.group(1))
                    first, second = rest[: len(rest) - len(new) - 3], "b/" + new
        if not (first.startswith("a/") and second.startswith("b/")):
            raise ValueError("a/ b/ 접두사가 없다")
        return first[2:], second[2:]
    except ValueError as e:
        raise common.ReviewError(f"diff 헤더를 해석하지 못했다({e}): {line[:200]}") from None


def _maybe_unquote(text: str) -> str:
    return _unquote(text, 0)[0] if text.startswith('"') else text


def parse_diff(raw: str) -> list[FileChange]:
    files: list[FileChange] = []
    for block in re.split(r"(?=^diff --git )", raw, flags=re.M):
        if not block.strip():
            continue
        lines = block.splitlines()
        if not lines[0].startswith("diff --git "):
            raise common.ReviewError(f"diff 가 `diff --git` 헤더로 시작하지 않는다: {lines[0][:200]}")
        path = parse_header(lines[0], block)[1]
        status = "modified"
        add = dele = 0
        in_hunk = False
        for ln in lines[1:]:
            if ln.startswith("@@"):
                in_hunk = True
            elif not in_hunk:
                if ln.startswith("new file mode"):
                    status = "added"
                elif ln.startswith("deleted file mode"):
                    status = "deleted"
                elif ln.startswith("rename from"):
                    status = "renamed"
            elif ln.startswith("+"):
                add += 1
            elif ln.startswith("-"):
                dele += 1
        fc = FileChange(path, status, add, dele, exclusion_reason(path))
        if fc.excluded is None and status != "deleted":
            fc.text = block if block.endswith("\n") else block + "\n"
        files.append(fc)
    return files


def pack(files: list[FileChange], chunk_max: int = CHUNK_MAX, max_chunks: int = MAX_CHUNKS):
    """diff 본문이 있는 파일을 파일 단위로 chunk_max 이하 부분들에 담는다. (parts, omitted, truncated)"""
    parts: list[list[str]] = []
    sizes: list[int] = []
    omitted: list[dict] = []
    truncated: list[str] = []
    for fc in files:
        if not fc.text:
            continue
        text = fc.text
        if len(text) > chunk_max:
            note = f"\n[이 파일의 diff는 {len(text)}자라 {chunk_max}자에서 잘렸다]\n"
            text = text[: chunk_max - len(note)] + note
            truncated.append(fc.path)
        for i, size in enumerate(sizes):  # 앞 부분부터 채운다(순서 보존보다 부분 수 최소화)
            if size + len(text) <= chunk_max:
                parts[i].append(text)
                sizes[i] += len(text)
                break
        else:
            if len(parts) >= max_chunks:
                omitted.append({"path": fc.path, "reason": f"부분 {max_chunks}개 상한 초과"})
                continue
            parts.append([text])
            sizes.append(len(text))
    return ["".join(p) for p in parts], omitted, truncated


# ---------------------------------------------------------------- 계획 발췌

def _headings(text: str):
    """(줄 번호, 레벨, 줄) — 코드 펜스 안은 건너뛴다."""
    fence = False
    for i, ln in enumerate(text.splitlines()):
        if ln.lstrip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            m = re.match(r"^(#{1,6}) ", ln)
            if m:
                yield i, len(m.group(1)), ln


def section(text: str, prefix: str) -> tuple[str, str] | None:
    """`prefix`(예: "### 4.7", "## 1.")로 시작하는 제목의 절을 (제목, 본문)으로. 없으면 None."""
    lines = text.splitlines()
    heads = list(_headings(text))
    for idx, (i, level, ln) in enumerate(heads):
        if ln.startswith(prefix):
            end = len(lines)
            for j, lv, _ in heads[idx + 1:]:
                if lv <= level:
                    end = j
                    break
            return ln, "\n".join(lines[i:end]).rstrip() + "\n"
    return None


def section_keys(labels: list[str]) -> list[str]:
    keys = list(ALWAYS_SECTIONS)
    for lb in labels:
        if lb.startswith("stage:"):
            keys += STAGE_SECTIONS.get(lb[6:], [])
    for lb in labels:
        if lb.startswith("area:"):
            keys += AREA_SECTIONS.get(lb[5:], [])
    return list(dict.fromkeys(keys))


def plan_excerpt(plan_text: str, labels: list[str], limit: int = PLAN_MAX) -> list[dict]:
    out: list[dict] = []
    used = 0
    for key in section_keys(labels):
        found = section(plan_text, key)
        if found is None:
            raise common.ReviewError(f"{PLAN_PATH} 에 '{key}' 절이 없다. tools/review/collect.py 의 절 매핑을 고쳐야 한다")
        head, body = found
        if used + len(body) > limit:
            body = body[: max(0, limit - used)] + "\n[계획 발췌 상한에서 잘림]\n"
        out.append({"heading": head, "text": body})
        used += len(body)
        if used >= limit:
            break
    return out


# ---------------------------------------------------------------- GitHub

_CLOSES = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s*:?\s+#(\d+)", re.I)
MAX_ISSUES = 3


def linked_issues(body: str | None) -> list[int]:
    seen: list[int] = []
    for m in _CLOSES.finditer(body or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.append(n)
    return seen[:MAX_ISSUES]


def _file_at(gh: GhFn, repo: str, path: str, ref: str) -> str | None:
    try:
        return gh("api", "-H", "Accept: application/vnd.github.raw", f"repos/{repo}/contents/{path}?ref={urllib.parse.quote(ref, safe='/')}")
    except common.ReviewError as e:
        if "404" in str(e) or "Not Found" in str(e):
            return None
        raise


def _required(gh: GhFn, repo: str, path: str, ref: str) -> str:
    """심판 기준 문서. 없거나 비면 문맥 없이 리뷰하지 않고 멈춘다."""
    text = _file_at(gh, repo, path, ref)
    if text is None:
        raise common.ReviewError(f"기준 브랜치 {ref} 에 {path} 가 없다. 필수 문서라 수집을 멈춘다")
    if not text.strip():
        raise common.ReviewError(f"기준 브랜치 {ref} 의 {path} 가 비어 있다. 필수 문서라 수집을 멈춘다")
    return text


def collect(pr_number: int, repo: str, gh: GhFn = common.gh, *, chunk_max: int = CHUNK_MAX, max_chunks: int = MAX_CHUNKS) -> Bundle:
    pr = json.loads(gh("pr", "view", str(pr_number), "-R", repo, "--json", "number,title,body,url,labels,baseRefName,headRefName,headRefOid"))
    pr["labels"] = sorted(lb["name"] for lb in pr.get("labels", []))
    pr["body"] = pr.get("body") or ""
    issues = []
    for n in linked_issues(pr["body"]):
        d = json.loads(gh("issue", "view", str(n), "-R", repo, "--json", "number,title,body,labels"))
        d["labels"] = sorted(lb["name"] for lb in d.get("labels", []))
        d["body"] = d.get("body") or ""
        issues.append(d)
    # stage·area 라벨은 연결 이슈의 것을 우선하고, 이슈에 하나도 없으면(또는 이슈가 없으면) PR 의 것을 쓴다
    labels: list[str] = []
    for src in (*(i["labels"] for i in issues), pr["labels"]):
        labels = [lb for lb in src if lb.startswith(("stage:", "area:"))]
        if labels:
            break

    base = pr["baseRefName"]
    plan = _required(gh, repo, PLAN_PATH, base)
    values = _required(gh, repo, VALUES_PATH, base)
    done = _required(gh, repo, DONE_PATH, base)
    files = parse_diff(gh("pr", "diff", str(pr_number), "-R", repo))
    parts, omitted, truncated = pack(files, chunk_max, max_chunks)
    return Bundle(
        repo=repo,
        pr=pr,
        issues=issues,
        labels=labels,
        values=values,
        done_definition=done,
        plan_sections=plan_excerpt(plan, labels),
        files=[f.row() for f in files],
        deleted=[f.path for f in files if f.status == "deleted" and f.excluded is None],
        omitted=omitted,
        truncated=truncated,
        diff_parts=parts,
    )


# ---------------------------------------------------------------- 렌더

def render(b: Bundle, part: int = 0) -> str:
    """모델에 보낼 사용자 메시지(비밀 마스킹 적용). part 는 diff_parts 의 색인."""
    return common.redact(_render(b, part))


def _render(b: Bundle, part: int) -> str:
    pr = b.pr
    out = [
        f"# PR #{pr['number']}: {pr['title']}",
        f"{pr['url']}\n기준 {pr['baseRefName']} ← {pr['headRefName']} @ {pr['headRefOid'][:12]}\n라벨: {', '.join(pr['labels']) or '(없음)'}",
        "## PR 본문\n" + (pr["body"].strip() or "(비어 있음)"),
    ]
    if b.issues:
        for i in b.issues:
            out.append(f"## 연결 이슈 #{i['number']} {i['title']}\n라벨: {', '.join(i['labels']) or '(없음)'}\n\n{i['body'].strip()}")
    else:
        out.append("## 연결 이슈\n(PR 본문에 `Closes #N` 이 없다)")
    out.append("## 핵심 가치 원본 (docs/plan/values.md, 기준 브랜치)\n" + (b.values.strip() if b.values else "(없음)"))
    out.append("## \"100% 완료\" 정의 (docs/process/done-definition.md, 기준 브랜치)\n" + (b.done_definition.strip() if b.done_definition else "(없음)"))
    out.append(f"## 계획 발췌 (docs/plan/studio-plan.md, 라벨: {', '.join(b.labels) or '없음'})")
    out.extend([s["text"].rstrip() for s in b.plan_sections] or ["(없음)"])
    rows = [
        f"| `{f['path']}` | {f['status']} | +{f['additions']}/-{f['deletions']} | {f['excluded'] or ''} |"
        for f in b.files
    ]
    out.append("## 변경 파일 (제외된 파일은 diff 본문이 없다)\n| 경로 | 상태 | 줄 | 제외 사유 |\n|---|---|---|---|\n" + "\n".join(rows))
    if b.deleted:
        out.append(f"## 삭제된 파일 {len(b.deleted)}개(내용 생략)\n" + "\n".join(b.deleted[:400]))
    if b.omitted:
        out.append("## 상한 때문에 diff 를 못 넣은 파일\n" + "\n".join(f"{o['path']} ({o['reason']})" for o in b.omitted))
    total = max(1, len(b.diff_parts))
    out.append(f"## diff (부분 {part + 1}/{total}; 생성물·lock·번들·에셋 제외)\n" + (b.diff_parts[part] if b.diff_parts else "(diff 본문 없음)"))
    return "\n\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PR 리뷰 문맥 묶음을 JSON 으로 출력한다")
    ap.add_argument("pr", type=int)
    ap.add_argument("--repo", help="OWNER/REPO (기본: 현재 디렉터리의 gh 저장소)")
    ap.add_argument("--prompt", action="store_true", help="JSON 대신 모델에 보낼 본문을 출력한다")
    args = ap.parse_args(argv)
    try:
        b = collect(args.pr, args.repo or common.default_repo())
    except common.ReviewError as e:
        print(f"collect: {common.redact(str(e))}", file=sys.stderr)
        return 1
    sys.stdout.write(common.redact(render(b) if args.prompt else b.to_json() + "\n"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
