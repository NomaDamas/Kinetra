#!/bin/zsh
# usage: measure.sh <source_dir> <out_dir> [plain|webfonts|stress]
# Headless Chrome only, throwaway --user-data-dir under /tmp, deleted afterwards. Never touches the user's Chrome profile.
#   plain     system fallback fonts (what index.html shows when Pretendard/JetBrains Mono are not installed)
#   webfonts  measure page only: FONT_CSS=<local css> with @font-face for JetBrains Mono (the canvas loads it from
#             Google Fonts) and Pretendard (named first in every artboard), pointing at font files saved on disk
#   stress    plain + letter-spacing 1px on every artboard (a stand-in for a wider font)
set -e
SRC=${1:A}; OUT=${2:A}; MODE=${3:-plain}; mkdir -p $OUT
python3 $SRC/tools/build_export.py $SRC $OUT --measure >/dev/null
case $MODE in
  webfonts) INJ="<link rel=\"stylesheet\" href=\"file://${FONT_CSS:?set FONT_CSS}\">" ;;
  stress)   INJ='<style>[data-board] *{letter-spacing:1px!important}</style>' ;;
  *)        INJ='' ;;
esac
python3 - "$OUT/measure.html" "$INJ" <<'PY'
import sys; p, inj = sys.argv[1], sys.argv[2]
s = open(p, encoding='utf-8').read()
s = s.replace('</head>', inj + '</head>', 1)
# report which faces actually loaded, so a failed font fetch is visible in the result
s = s.replace("document.getElementById('out').textContent = 'MEASURE'", "var ff = []; document.fonts.forEach(function (f) { if (f.status === 'loaded') ff.push(f.family + ' ' + f.weight); }); res.push({fonts: ff}); document.getElementById('out').textContent = 'MEASURE'")
s = s.replace("window.addEventListener('load', function () {", "window.addEventListener('load', function () { document.fonts.ready.then(function () { setTimeout(run, 300); }); }); function run() {", 1)
s = s.replace("ENDMEASURE';\n});", "ENDMEASURE';\n}", 1)
open(p, 'w', encoding='utf-8').write(s)
PY
P=$(mktemp -d /tmp/kin-sc03rev2-chrome.XXXXXX)
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu --no-first-run --no-default-browser-check \
  --user-data-dir="$P" --allow-file-access-from-files --window-size=1400,1000 --virtual-time-budget=15000 --dump-dom "file://$OUT/measure.html" > $OUT/dom.html 2>/dev/null || true
rm -rf "$P"
python3 $SRC/tools/read_measure.py $OUT/dom.html $OUT/measure.json
