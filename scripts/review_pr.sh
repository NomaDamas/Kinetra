#!/usr/bin/env bash
# PR 하나를 수집 → OpenRouter(openai/gpt-6.1-sol, reasoning high) 리뷰 → PR 코멘트 게시/갱신 (P0-06d).
#   OPENROUTER_API_KEY=... scripts/review_pr.sh <PR> [--repo OWNER/REPO] [--no-post] [--out DIR] [--cost-log FILE]
# 키는 환경변수로만 받는다(인자·파일로 받지 않는다). 출력은 tools/review/run.py 가 키를 가려서 낸다.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/.." && pwd)"

case "${1:-}" in
  ''|-h|--help)
    sed -n '2,4p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    [ -n "${1:-}" ] && exit 0
    exit 2
    ;;
esac

if [ -z "${OPENROUTER_API_KEY:-}" ]; then
  echo "review_pr.sh: OPENROUTER_API_KEY 환경변수가 없다. 키는 환경변수로만 받는다." >&2
  exit 2
fi

cd "$root"
export PYTHONPATH="$root/tools${PYTHONPATH:+:$PYTHONPATH}"
exec uv run --no-project --quiet python -m review.run "$@"
