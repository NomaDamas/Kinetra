#!/usr/bin/env python3
"""docs/plan/issues.yaml 의 에픽·이슈·하위 이슈를 GitHub 에 등록하고 하위 이슈로 연결한다 (P0-08).

    uv run python scripts/gh/seed_issues.py --dry-run | tail -5      # GitHub 를 읽기만 한다
    uv run python scripts/gh/seed_issues.py                          # 등록, 연결, 의존성 번호 치환
    uv run python scripts/gh/seed_issues.py --only-new               # 이번 실행에서 새로 만든 이슈만 연결·치환

세 단계 (이슈 #1~#364 를 등록할 때 실제로 쓴 스크립트를 옮긴 것이다. 같은 순서와 같은 API)
  1. 등록: 제목이 `[ID]` 로 시작하는 이슈가 이미 있으면 건너뛴다(ID 기준 멱등, 열림·닫힘·PR 제외 모두 조회).
     없으면 yaml 순서대로 만든다. 본문은 yaml 그대로(의존성은 아직 기호 ID).
  2. 연결: `parent` 가 있는 이슈를 부모의 하위 이슈로 잇는다(POST /issues/{부모}/sub_issues, 본문의 sub_issue_id 는
     이슈 번호가 아니라 이슈의 `id`). 이미 같은 부모에 이어져 있으면 건너뛴다. 다른 부모에 이어져 있으면 경고만 하고 건드리지 않는다.
  3. 치환: `depends_on` 의 ID 를 이슈 번호로 바꿔 `## 의존성` 절 맨 위에 `선행: #4 (P0-01b), …` 줄을 넣는다.
     이미 `선행: #<번호>` 줄이 있으면 건너뛴다.

기본은 전체 대조다. 앞선 실행이 1단계 뒤에 끊겼어도 다시 돌리면 빠진 연결·치환을 채운다.
`--only-new` 는 이번 실행에서 만든 이슈에만 2, 3단계를 적용한다(이미 있는 이슈는 연결·본문을 읽지도 고치지도 않는다).

라벨과 마일스톤은 만들지 않는다(`scripts/gh/bootstrap.sh` 몫). yaml 이 쓰는 라벨·마일스톤이 GitHub 에 없으면 아무것도 만들기 전에 실패한다.
같은 `[ID]` 제목의 이슈가 둘 이상이면 번호가 가장 작은 것을 쓰고 경고한다. PR 은 이슈로 세지 않는다(실제 저장소에서 #282 는 [A0-01a] 제목의 PR 이고 이슈 #43 과 겹치지 않는다).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import yaml

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "docs" / "plan" / "issues.yaml"
TITLE_ID_RE = re.compile(r"^\[([A-Za-z0-9\-]+)\]")
ID_RE = re.compile(r"^[A-Za-z0-9\-]+$")
DEP_LINE_RE = re.compile(r"^선행: #[0-9]+", re.MULTILINE)
DEP_HEADING = "## 의존성"
RATE_LIMIT_RE = re.compile(r"secondary rate limit|rate limit|abuse|HTTP 403|HTTP 429", re.IGNORECASE)
MAX_ATTEMPTS = 6
RETRY_WAIT = 60  # 초. 시도마다 곱한다
sleep = time.sleep  # 테스트가 바꾼다


class SpecError(Exception):
    pass


def load_items(path: Path) -> list[dict]:
    """yaml 의 items 를 검증해 돌려준다. 잘못이면 GitHub 를 부르기 전에 SpecError."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not data["items"]:
        raise SpecError(f"{path}: items 가 비어 있거나 리스트가 아니다")
    label_names = {str(l["name"]) for l in data.get("labels") or []}
    milestone_titles = {str(m["title"]) for m in data.get("milestones") or []}
    items, seen = [], set()
    for i, it in enumerate(data["items"]):
        where = f"items[{i}]"
        if not isinstance(it, dict):
            raise SpecError(f"{where}: 맵이 아니다")
        iid = it.get("id")
        if not isinstance(iid, str) or not ID_RE.match(iid):
            raise SpecError(f"{where}: id 는 영문·숫자·`-` 문자열이어야 한다: {iid!r}")
        if iid in seen:
            raise SpecError(f"{where}: id 중복 {iid!r}")
        title, body = it.get("title"), it.get("body")
        if not isinstance(title, str) or not title.startswith(f"[{iid}]"):
            raise SpecError(f"{iid}: title 은 `[{iid}]` 로 시작해야 한다(GitHub 에서 ID 로 찾는 열쇠): {title!r}")
        if not isinstance(body, str) or not body.strip():
            raise SpecError(f"{iid}: body 가 비었다")
        for lab in it.get("labels") or []:
            if lab not in label_names:
                raise SpecError(f"{iid}: yaml labels 에 없는 라벨 {lab!r}")
        ms = it.get("milestone")
        if ms is not None and ms not in milestone_titles:
            raise SpecError(f"{iid}: yaml milestones 에 없는 마일스톤 {ms!r}")
        seen.add(iid)
        items.append(it)
    for it in items:
        parent = it.get("parent")
        if parent is not None and parent not in seen:
            raise SpecError(f"{it['id']}: parent {parent!r} 가 items 에 없다")
        if parent == it["id"]:
            raise SpecError(f"{it['id']}: parent 가 자기 자신이다")
        for dep in it.get("depends_on") or []:
            if dep not in seen:
                raise SpecError(f"{it['id']}: depends_on {dep!r} 가 items 에 없다")
    return items


# ---------- gh ----------

def gh(*args: str, stdin: str | None = None) -> str:
    """gh 를 부른다. 속도 제한이면 기다렸다 다시 한다. 그 밖의 실패는 RuntimeError."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        r = subprocess.run(["gh", *args], input=stdin, capture_output=True, text=True)
        if r.returncode == 0:
            return r.stdout
        if RATE_LIMIT_RE.search(r.stderr) and attempt < MAX_ATTEMPTS:
            wait = RETRY_WAIT * attempt
            print(f"속도 제한. {wait}초 기다린다({attempt}/{MAX_ATTEMPTS - 1})", file=sys.stderr, flush=True)
            sleep(wait)
            continue
        raise RuntimeError(f"gh {' '.join(args[:4])} 실패 (exit {r.returncode}): {r.stderr.strip()[:400]}")
    raise AssertionError("unreachable")


def gh_json(*args: str, stdin: str | None = None):
    return json.loads(gh(*args, stdin=stdin))


def fetch_repo() -> str:
    return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()


def fetch_pages(path: str) -> list[dict]:
    pages = gh_json("api", "--paginate", "--slurp", path)
    return [x for page in pages for x in page]


def fetch_existing(repo: str, wanted: set[str]) -> dict[str, dict]:
    """ID -> {number, id, parent_number, body}. PR 은 제외한다. 중복 제목은 번호가 작은 쪽."""
    found: dict[str, dict] = {}
    for it in sorted(fetch_pages(f"repos/{repo}/issues?state=all&per_page=100"), key=lambda x: x["number"]):
        if "pull_request" in it:
            continue
        m = TITLE_ID_RE.match(it.get("title") or "")
        if not m or m.group(1) not in wanted:
            continue
        iid = m.group(1)
        if iid in found:
            print(f"경고: [{iid}] 제목의 이슈가 둘 이상이다. #{found[iid]['number']} 를 쓰고 #{it['number']} 는 무시한다", file=sys.stderr)
            continue
        parent_url = it.get("parent_issue_url")
        found[iid] = {
            "number": it["number"],
            "id": it["id"],
            "parent_number": int(parent_url.rsplit("/", 1)[1]) if parent_url else None,
            "body": it.get("body") or "",
            "new": False,
        }
    return found


# ---------- 계획과 적용 ----------

def with_dependency_line(body: str, line: str) -> str:
    if DEP_HEADING in body:
        return re.sub(r"(" + re.escape(DEP_HEADING) + r"[ \t]*\n)", lambda m: m.group(1) + line + "\n", body, count=1)
    return body.rstrip("\n") + f"\n\n{DEP_HEADING}\n{line}\n"


def seed(repo: str, items: list[dict], *, dry_run: bool, only_new: bool, delay: float, out=print) -> dict[str, int]:
    labels = {l["name"].lower() for l in fetch_pages(f"repos/{repo}/labels?per_page=100")}
    milestones = {m["title"]: m["number"] for m in fetch_pages(f"repos/{repo}/milestones?state=all&per_page=100")}
    missing = sorted({lab for it in items for lab in it.get("labels") or [] if lab.lower() not in labels}
                     | {f"milestone:{it['milestone']}" for it in items if it.get("milestone") not in (None, *milestones)})
    if missing:
        raise RuntimeError(f"GitHub 에 없는 라벨·마일스톤: {', '.join(missing)}. 먼저 scripts/gh/bootstrap.sh 를 돌린다")

    would = "would " if dry_run else ""
    existing = fetch_existing(repo, {it["id"] for it in items})
    counts = {"create": 0, "link": 0, "rewrite": 0, "keep": 0}

    # 1. 등록
    created: set[str] = set()
    for it in items:
        if it["id"] in existing:
            continue
        counts["create"] += 1
        created.add(it["id"])
        out(f"{would}create [{it['id']}] ({it.get('kind', '?')})")
        if dry_run:
            existing[it["id"]] = {"number": None, "id": None, "parent_number": None, "body": it["body"], "new": True}
            continue
        payload = {"title": it["title"], "body": it["body"], "labels": it.get("labels") or []}
        if it.get("milestone") is not None:
            payload["milestone"] = milestones[it["milestone"]]
        r = gh_json("api", "-X", "POST", f"repos/{repo}/issues", "--input", "-", stdin=json.dumps(payload))
        existing[it["id"]] = {"number": r["number"], "id": r["id"], "parent_number": None, "body": it["body"], "new": True}
        sleep(delay)

    # 2. 연결, 3. 의존성 번호 치환
    for it in items:
        cur = existing[it["id"]]
        if only_new and it["id"] not in created:
            continue
        done = False
        parent = it.get("parent")
        if parent is not None:
            pnum = existing[parent]["number"]
            if cur["parent_number"] is not None and cur["parent_number"] != pnum:
                print(f"경고: [{it['id']}] 는 이미 #{cur['parent_number']} 의 하위 이슈다. yaml 의 부모 [{parent}] #{pnum} 로 옮기지 않는다", file=sys.stderr)
            elif cur["parent_number"] is None:
                counts["link"] += 1
                done = True
                out(f"{would}link [{it['id']}] -> [{parent}]")
                if not dry_run:
                    gh("api", "-X", "POST", f"repos/{repo}/issues/{pnum}/sub_issues", "--input", "-",
                       stdin=json.dumps({"sub_issue_id": cur["id"]}))
        deps = [d for d in it.get("depends_on") or [] if d in existing]
        if deps and not DEP_LINE_RE.search(cur["body"]):
            counts["rewrite"] += 1
            done = True
            line = "선행: " + ", ".join(f"#{existing[d]['number'] if existing[d]['number'] is not None else '?'} ({d})" for d in deps)
            out(f"{would}rewrite [{it['id']}] {line}")
            if not dry_run:
                gh("api", "-X", "PATCH", f"repos/{repo}/issues/{cur['number']}", "--input", "-",
                   stdin=json.dumps({"body": with_dependency_line(cur["body"], line)}))
        if not done:
            counts["keep"] += 1
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE, help="issues.yaml 경로")
    ap.add_argument("--repo", help="OWNER/REPO (기본: 현재 디렉터리의 gh 저장소)")
    ap.add_argument("--dry-run", action="store_true", help="GitHub 를 읽기만 하고 아무것도 만들거나 고치지 않는다")
    ap.add_argument("--only-new", action="store_true", help="이번 실행에서 새로 만든 이슈에만 연결·치환을 적용한다")
    ap.add_argument("--delay", type=float, default=1.0, help="이슈 하나를 만든 뒤 쉬는 초(기본 1.0, 속도 제한 완화)")
    args = ap.parse_args(argv)
    try:
        items = load_items(args.file)
        repo = args.repo or fetch_repo()
        c = seed(repo, items, dry_run=args.dry_run, only_new=args.only_new, delay=args.delay)
    except (SpecError, RuntimeError) as e:
        print(f"seed_issues: {e}", file=sys.stderr)
        return 1
    print(f"{repo}: items={len(items)} create={c['create']} link={c['link']} rewrite={c['rewrite']} keep={c['keep']}"
          + (" (dry-run)" if args.dry_run else "") + (" (only-new)" if args.only_new else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
