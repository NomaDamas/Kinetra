#!/bin/zsh
# SC-15 self-check. Headless Chrome only, throwaway profile under /tmp, deleted afterwards.
# usage: zsh measure.sh <project_dir> <work_dir> <tokens.json> [board w h ...]
#   writes <work_dir>/measure.html and dom.html, prints one JSON line per artboard (read_measure.py),
#   then a screenshot <work_dir>/<board>.png for each "board w h" triple given.
set -e
SRC=${1:A}; OUT=${2:A}; TOK=${3:A}; shift 3
HERE=${0:A:h}
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
mkdir -p "$OUT"
python3 "$HERE/build_export.py" "$SRC" "$OUT" --measure --tokens "$TOK" >/dev/null
P=$(mktemp -d /tmp/kin-sc15-chrome.XXXXXX)
trap 'rm -rf "$P"' EXIT
F=(--headless=new --disable-gpu --no-first-run --no-default-browser-check --disable-extensions --user-data-dir="$P")
"$CHROME" $F --window-size=2400,1200 --virtual-time-budget=3000 --dump-dom "file://$OUT/measure.html" 2>/dev/null > "$OUT/dom.html"
while (( $# >= 3 )); do
  B=$1; W=$2; H=$3; shift 3
  python3 "$HERE/build_export.py" "$SRC" "$OUT" --board "$B" >/dev/null
  ID=${${B%%.*}:l}
  "$CHROME" $F --window-size=$W,$H --hide-scrollbars --virtual-time-budget=2000 --screenshot="$OUT/$ID.png" "file://$OUT/board-$ID.html" 2>/dev/null
done
rm -rf "$P"
python3 "$HERE/read_measure.py" "$OUT/dom.html"
