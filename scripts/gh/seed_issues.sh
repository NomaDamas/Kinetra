#!/usr/bin/env bash
# issues.yaml 의 에픽·이슈·하위 이슈를 GitHub 에 등록한다 (P0-08).
#   scripts/gh/seed_issues.sh [--dry-run] [--only-new] [--repo OWNER/REPO] [--file PATH]
# 라벨·마일스톤은 먼저 scripts/gh/bootstrap.sh 로 만든다.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec uv run --no-project --quiet --with pyyaml python "$here/seed_issues.py" "$@"
