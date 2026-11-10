#!/bin/zsh
# usage: shot.sh <project_dir> <out_dir> <board> <w> <h>
PROJ=$1; OUT=$2; B=$3; W=$4; H=$5
python3 "$(dirname $0)/build_export.py" "$PROJ" "$OUT" --board "$B" >/dev/null
ID=$(echo ${B%%.*} | tr 'A-Z' 'a-z')
P=$(mktemp -d /tmp/kin-sc02-chrome.XXXXXX)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$P" --window-size=$W,$H --hide-scrollbars --screenshot="$OUT/$ID.png" "file://$OUT/board-$ID.html" 2>/dev/null
rm -rf "$P"; echo "$OUT/$ID.png"
