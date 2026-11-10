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
elif a[:2] == ["label", "create"]:
    if any(l["name"].lower() == a[2].lower() for l in st["labels"]):
        sys.exit("already exists")
    st["labels"].append({"name": a[2], "color": opt("--color"), "description": opt("--description")})
    save()
elif a[:2] == ["label", "edit"]:
    l = next(l for l in st["labels"] if l["name"].lower() == a[2].lower())
    l.update(color=opt("--color"), description=opt("--description"))
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
