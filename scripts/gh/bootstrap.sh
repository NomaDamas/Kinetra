#!/usr/bin/env bash
# issues.yaml 의 labels / milestones 를 GitHub 에 멱등하게 반영한다 (P0-02).
#   scripts/gh/bootstrap.sh [--dry-run] [--repo OWNER/REPO] [--file PATH]
# 없는 것만 만들고, 있는 라벨의 색·설명(마일스톤은 설명)이 다르면 갱신한다. 삭제는 하지 않는다.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --no-project --quiet --with pyyaml python "$here/bootstrap.py" "$@"
