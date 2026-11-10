#!/usr/bin/env python3
"""테스트 전용 gh 대체물. FAKE_GH_STATE(JSON 파일)에 라벨·마일스톤을 저장해 상태를 유지한다."""
import json, os, sys

path = os.environ["FAKE_GH_STATE"]
st = json.load(open(path))
a = sys.argv[1:]


def save():
    json.dump(st, open(path, "w"))


def opt(flag):
    return a[a.index(flag) + 1]


if a[:2] == ["repo", "view"]:
    print("o/r")
elif a[:2] == ["label", "list"]:
    print(json.dumps(st["labels"]))
elif a[:2] in (["label", "create"], ["label", "edit"]):
    flags, rest, i = {}, [], 2
    while i < len(a):
        x = a[i]
        if x == "--":  # 이후는 모두 위치 인자
            rest += a[i + 1:]
            break
        if x in ("-R", "--color", "--description"):
            flags[x] = a[i + 1]
            i += 2
            continue
        if x.startswith(("--color=", "--description=")):
            k, v = x.split("=", 1)
            flags[k] = v
        elif x.startswith("-"):
            sys.exit(f"unknown flag: {x}")  # 실제 gh 처럼 옵션 모양 인자를 플래그로 해석한다
        else:
            rest.append(x)
        i += 1
    if len(rest) != 1:
        sys.exit(f"expected exactly one label name, got {rest}")
    name = rest[0]
    cur = next((l for l in st["labels"] if l["name"].lower() == name.lower()), None)
    if a[1] == "create":
        if cur:
            sys.exit("already exists")
        st["labels"].append({"name": name, "color": flags["--color"], "description": flags["--description"]})
    else:
        cur.update(color=flags["--color"], description=flags["--description"])
    save()
elif a[0] == "api" and "--paginate" in a:
    for m in st["milestones"]:
        print(json.dumps(m))
elif a[0] == "api" and "POST" in a:
    fields = dict(x.split("=", 1) for x in a if "=" in x and not x.startswith("repos/"))
    st["milestones"].append({"number": len(st["milestones"]) + 1, "title": fields["title"], "description": fields["description"]})
    save()
elif a[0] == "api" and "PATCH" in a:
    n = int([x for x in a if x.startswith("repos/")][0].rsplit("/", 1)[1])
    next(m for m in st["milestones"] if m["number"] == n)["description"] = opt("-f").split("=", 1)[1]
    save()
else:
    sys.exit(f"fake gh: unsupported {a}")
