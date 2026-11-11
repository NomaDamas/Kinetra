#!/bin/zsh
# usage: measure.sh <project_dir> <out_dir>   (headless Chrome, throwaway profile under /tmp, deleted afterwards)
set -e
PROJ=$1; OUT=$2
python3 "$(dirname $0)/build_export.py" "$PROJ" "$OUT" --measure --tokens "${0:A:h}/../../../design-system/tokens.json"
P=$(mktemp -d /tmp/kin-sc02rev2-chrome.XXXXXX)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$P" --window-size=2200,1000 --virtual-time-budget=2000 --dump-dom "file://$OUT/measure.html" 2>/dev/null > "$OUT/dom.html" || true
rm -rf "$P"
ls -d /tmp/kin-sc02rev2-chrome.* 2>/dev/null && echo "PROFILE LEFT" || echo "profile deleted"
python3 - "$OUT/dom.html" <<'PY'
import sys, re, json, html
t = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'MEASURE(.*?)ENDMEASURE', t, re.S)
data = json.loads(html.unescape(m.group(1)))
for b in data:
    print(json.dumps(b, ensure_ascii=False))
PY
