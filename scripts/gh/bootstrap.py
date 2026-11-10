#!/usr/bin/env python3
"""docs/plan/issues.yaml 의 labels, milestones 를 GitHub 에 멱등하게 반영한다.

- 없으면 만든다(label create / POST milestones).
- 있는데 색·설명이 다르면 갱신한다(label edit / PATCH milestones).
- 같으면 아무것도 하지 않는다. 삭제는 하지 않는다.
- 라벨 이름은 GitHub 처럼 대소문자 무시로 비교한다. 마일스톤은 제목 정확 일치(상태 open/closed 모두 조회).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

DEFAULT_FILE = Path(__file__).resolve().parents[2] / "docs" / "plan" / "issues.yaml"
COLOR_RE = re.compile(r"^[0-9a-fA-F]{6}$")
LABEL_DESC_MAX = 100
MILESTONE_DESC_MAX = 1000


class SpecError(Exception):
    pass


def _text(value, where: str, *, required: bool) -> str:
    """YAML 스칼라를 문자열로 정규화한다. 따옴표 없는 정수(예: title: 2)는 "2"로 본다.
    bool, float, 리스트, 맵은 거부한다(`yes`가 True가 되거나 1.10이 1.1이 되는 식의 조용한 변형 방지)."""
    if value is None:
        value = ""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise SpecError(f"{where}: 문자열이어야 한다(받은 값 {value!r}, 형식 {type(value).__name__}). 따옴표로 감싸라")
    text = str(value).strip()
    if required and not text:
        raise SpecError(f"{where}: 비어 있다")
    return text


def load_spec(path: Path) -> tuple[list[dict], list[dict]]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SpecError(f"{path}: 최상위가 맵이 아니다")
    labels, milestones = data.get("labels"), data.get("milestones")
    if not isinstance(labels, list) or not isinstance(milestones, list) or not labels or not milestones:
        raise SpecError(f"{path}: labels, milestones 가 비어 있거나 리스트가 아니다")
    seen: set[str] = set()
    out_labels = []
    for i, lab in enumerate(labels):
        if not isinstance(lab, dict):
            raise SpecError(f"labels[{i}]: 맵이 아니다")
        name = _text(lab.get("name"), f"labels[{i}].name", required=True)
        color = _text(lab.get("color"), f"label {name!r}.color", required=True).lstrip("#")
        desc = _text(lab.get("description"), f"label {name!r}.description", required=False)
        if name.lower() in seen:
            raise SpecError(f"labels: 중복 이름 {name!r}")
        seen.add(name.lower())
        if not COLOR_RE.match(color):
            raise SpecError(f"label {name!r}: color 는 6자리 hex 여야 한다: {color!r}")
        if len(desc) > LABEL_DESC_MAX:
            raise SpecError(f"label {name!r}: description {len(desc)}자 > {LABEL_DESC_MAX}")
        out_labels.append({"name": name, "color": color.lower(), "description": desc})
    seen = set()
    out_ms = []
    for i, ms in enumerate(milestones):
        if not isinstance(ms, dict):
            raise SpecError(f"milestones[{i}]: 맵이 아니다")
        title = _text(ms.get("title"), f"milestones[{i}].title", required=True)
        desc = _text(ms.get("description"), f"milestone {title!r}.description", required=False)
        if title in seen:
            raise SpecError(f"milestones: 중복 제목 {title!r}")
        seen.add(title)
        if len(desc) > MILESTONE_DESC_MAX:
            raise SpecError(f"milestone {title!r}: description 너무 길다")
        out_ms.append({"title": title, "description": desc})
    return out_labels, out_ms


def gh(*args: str) -> str:
    r = subprocess.run(["gh", *args], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} 실패 (exit {r.returncode}): {r.stderr.strip()}")
    return r.stdout


def fetch_repo() -> str:
    return gh("repo", "view", "--json", "nameWithOwner", "--jq", ".nameWithOwner").strip()


def fetch_labels(repo: str) -> list[dict]:
    return json.loads(gh("label", "list", "-R", repo, "--limit", "1000", "--json", "name,color,description"))


def fetch_milestones(repo: str) -> list[dict]:
    out = gh("api", "--paginate", f"repos/{repo}/milestones?state=all&per_page=100", "--jq", ".[]")
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def plan(labels, milestones, have_labels, have_milestones) -> list[tuple]:
    """('create'|'update'|'keep', kind, spec[, number]) 목록."""
    by_name = {l["name"].lower(): l for l in have_labels}
    by_title = {m["title"]: m for m in have_milestones}
    actions: list[tuple] = []
    for want in labels:
        cur = by_name.get(want["name"].lower())
        if cur is None:
            actions.append(("create", "label", want))
        elif (cur.get("color") or "").lower() != want["color"] or (cur.get("description") or "") != want["description"]:
            actions.append(("update", "label", want))
        else:
            actions.append(("keep", "label", want))
    for want in milestones:
        cur = by_title.get(want["title"])
        if cur is None:
            actions.append(("create", "milestone", want))
        elif (cur.get("description") or "") != want["description"]:
            actions.append(("update", "milestone", want, cur["number"]))
        else:
            actions.append(("keep", "milestone", want, cur["number"]))
    return actions


def apply(repo: str, actions: list[tuple]) -> None:
    for act in actions:
        op, kind, spec = act[0], act[1], act[2]
        if op == "keep":
            continue
        if kind == "label":
            verb = "create" if op == "create" else "edit"
            gh("label", verb, spec["name"], "-R", repo, "--color", spec["color"], "--description", spec["description"])
        elif op == "create":
            gh("api", "-X", "POST", f"repos/{repo}/milestones", "-f", f"title={spec['title']}", "-f", f"description={spec['description']}")
        else:
            gh("api", "-X", "PATCH", f"repos/{repo}/milestones/{act[3]}", "-f", f"description={spec['description']}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE, help="issues.yaml 경로")
    ap.add_argument("--repo", help="OWNER/REPO (기본: 현재 디렉터리의 gh 저장소)")
    ap.add_argument("--dry-run", action="store_true", help="GitHub 를 읽기만 하고 변경하지 않는다")
    args = ap.parse_args(argv)
    try:
        labels, milestones = load_spec(args.file)
        repo = args.repo or fetch_repo()
        actions = plan(labels, milestones, fetch_labels(repo), fetch_milestones(repo))
        for act in actions:
            if act[0] != "keep":
                name = act[2].get("name") or act[2]["title"]
                print(f"{'would ' if args.dry_run else ''}{act[0]} {act[1]}: {name}")
        if not args.dry_run:
            apply(repo, actions)
    except (SpecError, RuntimeError) as e:
        print(f"bootstrap: {e}", file=sys.stderr)
        return 1
    n = {(o, k): sum(1 for a in actions if a[0] == o and a[1] == k) for o in ("create", "update", "keep") for k in ("label", "milestone")}
    print(
        f"{repo}: labels create={n['create','label']} update={n['update','label']} keep={n['keep','label']}; "
        f"milestones create={n['create','milestone']} update={n['update','milestone']} keep={n['keep','milestone']}"
        + (" (dry-run)" if args.dry_run else "")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
