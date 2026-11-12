#!/bin/sh
# Self-check for SC-04 rev2. Headless Chrome only, throwaway profile under /tmp, deleted afterwards.
# usage: sh source/tools/measure.sh <source_dir> <work_dir>
#   writes <work_dir>/measure.html, dom.html (self-check JSON in <pre id="out">),
#   board-s3.html, probe-s3.html (S3 rank rows vs pinned heads), s3.png
set -e
SRC=$(cd "$1" && pwd); OUT=$(mkdir -p "$2" && cd "$2" && pwd); HERE=$(cd "$(dirname "$0")" && pwd)
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
python3 "$HERE/build_export.py" "$SRC" "$OUT" --measure
python3 "$HERE/build_export.py" "$SRC" "$OUT" --board S3
python3 - "$OUT" <<'PY'
import sys, pathlib
m = pathlib.Path(sys.argv[1]); s = (m / 'board-s3.html').read_text(encoding='utf-8')
js = """<pre id="out"></pre><script>addEventListener('load',function(){var b=document.querySelector('[data-board]');var st=b.querySelector('[data-sticky-heads]');var sc=st.parentElement;var r=function(e){var x=e.getBoundingClientRect();return [Math.round(x.top),Math.round(x.bottom)]};var n=b.querySelector('[data-note]');document.getElementById('out').textContent='PROBE'+JSON.stringify({scroller:r(sc),scrollH:sc.scrollHeight,clientH:sc.clientHeight,sticky:r(st),ranks:[].map.call(b.querySelectorAll('#s3-sens ol>li'),r),noteClient:n.clientHeight,noteScroll:n.scrollHeight})+'END'})</script></body>"""
(m / 'probe-s3.html').write_text(s.replace('</body>', js), encoding='utf-8')
PY
P=$(mktemp -d /tmp/kin-sc04rev2-chrome.XXXXXX)
trap 'rm -rf "$P"' EXIT
F="--headless=new --disable-gpu --no-first-run --no-default-browser-check --user-data-dir=$P --virtual-time-budget=2000"
"$CHROME" $F --window-size=1600,1000 --dump-dom "file://$OUT/measure.html" 2>/dev/null > "$OUT/dom.html"
"$CHROME" $F --window-size=1600,1000 --dump-dom "file://$OUT/probe-s3.html" 2>/dev/null | grep -o 'PROBE{[^<]*END'
"$CHROME" $F --window-size=600,840 --hide-scrollbars --screenshot="$OUT/s3.png" "file://$OUT/board-s3.html" 2>/dev/null
