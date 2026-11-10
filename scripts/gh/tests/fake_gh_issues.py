#!/usr/bin/env python3
"""seed_issues 테스트 전용 gh 대체물. FAKE_GH_STATE(JSON)에 이슈를 저장하고 호출을 `calls` 에 기록한다.

지원: repo view / api --paginate --slurp 로 labels, milestones, issues 읽기 /
      POST issues, POST issues/N/sub_issues, PATCH issues/N.
FAKE_GH_FAIL_ONCE 가 "<부분 문자열>" 이면 그 문자열이 든 호출이 첫 번째에 한해 속도 제한으로 실패한다.
"""
import json
import os
import sys

path = os.environ["FAKE_GH_STATE"]
st = json.load(open(path))
a = sys.argv[1:]
st["calls"].append(a)


def save():
    json.dump(st, open(path, "w"))


def stdin_json():
    return json.loads(sys.stdin.read())


def issue_url(n):
    return f"https://api.github.com/repos/o/r/issues/{n}"


fail = os.environ.get("FAKE_GH_FAIL_ONCE")
if fail and fail in " ".join(a) and not st.get("failed_once"):
    st["failed_once"] = True
    save()
    sys.exit(os.environ.get("FAKE_GH_FAIL_MSG", "gh: You have exceeded a secondary rate limit. (HTTP 403)"))

if a[:2] == ["repo", "view"]:
    print("o/r")
elif a[0] == "api" and "--paginate" in a:
    p = next(x for x in a if x.startswith("repos/"))
    if "/labels" in p:
        pages = [[{"name": n} for n in st["labels"]]]
    elif "/milestones" in p:
        pages = [[{"number": i + 1, "title": t} for i, t in enumerate(st["milestones"])]]
    elif "/issues" in p:
        items = []
        for it in sorted(st["issues"], key=lambda x: -x["number"]):  # GitHub 는 최신순
            d = {k: it[k] for k in ("id", "number", "title", "body")}
            p = it.get("parent")
            d["parent_issue_url"] = (p if isinstance(p, str) else issue_url(p)) if p else None
            if it.get("pr"):
                d["pull_request"] = {}
            items.append(d)
        pages = [items[:2], items[2:]]  # 쪽 나눔을 흉내낸다
    else:
        sys.exit(f"fake gh: unsupported {a}")
    print(json.dumps(pages))
elif a[0] == "api" and "POST" in a and a[-3:-1] == ["--input", "-"] or (a[0] == "api" and "POST" in a and "--input" in a):
    p = next(x for x in a if x.startswith("repos/"))
    body = stdin_json()
    if p.endswith("/issues"):
        for lab in body["labels"]:
            if lab not in st["labels"]:
                sys.exit(f"fake gh: 422 unknown label {lab}")
        n = max([i["number"] for i in st["issues"]] + [0]) + 1
        it = {"id": 9000 + n, "number": n, "title": body["title"], "body": body["body"], "parent": None,
              "labels": body["labels"], "milestone": body.get("milestone")}
        st["issues"].append(it)
        save()
        print(json.dumps({"id": it["id"], "number": n}))
    elif p.endswith("/sub_issues"):
        parent = int(p.split("/")[-2])
        child = next(i for i in st["issues"] if i["id"] == body["sub_issue_id"])
        if child["parent"] is not None:
            sys.exit("fake gh: 422 already has a parent")
        child["parent"] = parent
        save()
        print("{}")
    else:
        sys.exit(f"fake gh: unsupported {a}")
elif a[0] == "api" and "PATCH" in a:
    n = int(next(x for x in a if x.startswith("repos/")).rsplit("/", 1)[1])
    body = stdin_json()
    next(i for i in st["issues"] if i["number"] == n)["body"] = body["body"]
    save()
    print("{}")
else:
    sys.exit(f"fake gh: unsupported {a}")
save()
