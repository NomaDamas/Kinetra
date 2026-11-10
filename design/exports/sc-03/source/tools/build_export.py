#!/usr/bin/env python3
"""Kinetra Studio SC-03 (에이전트 바와 변경안 카드): build the standalone HTML gallery from the canvas artboards.

usage: build_export.py <project_dir> <out_dir> [--measure] [--board NAME]
  <project_dir>  folder holding canvas.json and the *.dc.html artboards (this export's source/)
  --measure      write measure.html instead of index.html: same boards plus a script that
                 reports the self-check numbers into <pre id="out"> (read it with headless
                 Chrome --dump-dom; see the bottom of this file)
  --board NAME   write board-<NAME>.html holding that one artboard at 0,0 (for a screenshot)

Adapted from design/exports/sc-01/source/tools/build_export.py. Differences: an artboard may hold
several screens (one [data-screen] per state variant), and the measure script also checks colors
against tokens.json, status.danger use, banned phrases and card-area height.

The output makes no network request: no web font link, no script source, no image.
Fonts are named only (Pretendard, JetBrains Mono) and fall back to system fonts.
"""
import json, re, sys, pathlib

argv = sys.argv[1:]
only = None
if '--board' in argv:
    i = argv.index('--board')
    only = argv[i + 1]
    del argv[i:i + 2]
measure = '--measure' in argv
args = [a for a in argv if not a.startswith('--')]
if len(args) != 2:
    raise SystemExit(__doc__)
project = pathlib.Path(args[0])
out = pathlib.Path(args[1])
out.mkdir(parents=True, exist_ok=True)

canvas = json.loads((project / 'canvas.json').read_text(encoding='utf-8'))
MONO_IN = "'JetBrains Mono',monospace"
MONO_OUT = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace"  # tokens.css --kin-font-mono

# design/exports/design-system/tokens.json: every hex plus the two elevation rgba values
TOKENS = ['#08111F', '#0F1216', '#0F1318', '#151A20', '#1B2129', '#1F252D', '#222A33', '#22324A', '#263039',
          '#26303A', '#2A2444', '#2C2819', '#303B49', '#322858', '#3A1D2E', '#3A4654', '#40327A', '#5B9DFF',
          '#7A899B', '#8FB8E8', '#93A0AE', '#A0ACBB', '#A8CBFF', '#A9B4C0', '#BBAFF3', '#C5D0DC', '#D2BFFF',
          '#D2C6A0', '#E8EDF2', '#EFE6FF', '#F2A8D0', '#F2B84B', '#FF7B72']


def body_of(name: str, src: str) -> str:
    m = re.search(r'</helmet>(.*)</x-dc>', src, re.S)
    if not m:
        raise SystemExit(f'{name}: no <x-dc> body')
    html = m.group(1).strip()
    if '{{' in html or '<sc-' in html or '<dc-import' in html:
        raise SystemExit(f'{name}: template syntax in a static artboard')
    if re.search(r'(src|href)="https?:', html) or 'url(' in html:
        raise SystemExit(f'{name}: external reference in artboard body')
    return html.replace(MONO_IN, MONO_OUT)


def helmet_css(src: str) -> str:
    m = re.search(r'<helmet>.*?<style>(.*?)</style>.*?</helmet>', src, re.S)
    return m.group(1).strip() if m else ''


boards, css = [], None
for name in canvas['order']:
    path = project / name
    if not path.exists():
        raise SystemExit(f'{name}: listed in canvas.json but missing')
    src = path.read_text(encoding='utf-8')
    b = canvas['boards'][name]
    html = body_of(name, src)
    root = re.match(r'<div style="width:(\d+)px;height:(\d+)px;', html)
    if not root:
        raise SystemExit(f'{name}: unexpected root')
    w, h = int(root.group(1)), int(root.group(2))
    assert (w, h) == (b['w'], b['h']), f'{name}: root {w}x{h} != canvas {b["w"]}x{b["h"]}'
    html = html.replace('<div style="', f'<div data-board="{name}" style="', 1)
    this_css = helmet_css(src)
    if css is None:
        css = this_css
    elif this_css != css:
        raise SystemExit(f'{name}: helmet <style> differs from the first artboard')
    boards.append({'name': name, 'id': name.split('.')[0].lower(), 'title': b.get('title', name), 'w': w, 'h': h, 'html': html})

MEASURE = r"""
window.addEventListener('load', function () {
  var TOKENS = %TOKENS%;
  var BANNED = ['현실과 동일', '실제와 똑같', '검증됨', '보장', '판정했습니다', '가능하다고 판정', '성공 확인', '통과'];
  function hex2rgb(h) { return 'rgb(' + parseInt(h.slice(1, 3), 16) + ', ' + parseInt(h.slice(3, 5), 16) + ', ' + parseInt(h.slice(5, 7), 16) + ')'; }
  var OK = {}; TOKENS.forEach(function (h) { OK[hex2rgb(h)] = h; });
  OK['rgba(0, 0, 0, 0.6)'] = 'elevation.scrim'; OK['rgba(0, 0, 0, 0.5)'] = 'elevation.3';
  function lum(c) { var a = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; }
  function rgb(s) { var m = /rgba?\(([^)]+)\)/.exec(s); if (!m) return null; var p = m[1].split(',').map(parseFloat); return { c: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; }
  function bgOf(el) { for (var e = el; e; e = e.parentElement) { var b = rgb(getComputedStyle(e).backgroundColor); if (b && b.a > 0.99) return b.c; } return [15, 18, 22]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function shown(el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; }
  function hidden(el) { return !!el.closest('[inert], .kin-sr'); }
  function label(e) { return (e.getAttribute('data-ctl') || e.getAttribute('aria-label') || e.textContent || e.tagName).trim().slice(0, 40); }
  var SEL = 'button, input, select, textarea, a[href], [tabindex="0"]';
  var res = [];
  document.querySelectorAll('[data-board]').forEach(function (board) {
    var p = board.getBoundingClientRect();
    var screens = [].map.call(board.querySelectorAll('[data-screen]'), function (screen) {
      var ctl = [].filter.call(screen.querySelectorAll('[data-ctl]'), function (e) { return shown(e) && !e.closest('[data-transient]') && !hidden(e); });
      var transient = [].filter.call(screen.querySelectorAll('[data-transient] [data-ctl]'), shown);
      var area = screen.querySelector('[aria-label="변경안 카드 영역"]');
      var bar = screen.querySelector('[aria-label="에이전트 바"]');
      return { screen: screen.getAttribute('data-screen'), controls: ctl.length, names: ctl.map(function (e) { return e.getAttribute('data-ctl'); }),
        transient: transient.map(function (e) { return e.getAttribute('data-ctl'); }),
        cardArea: area ? Math.round(area.getBoundingClientRect().height) : null,
        card: area && area.querySelector('section') ? Math.round(area.querySelector('section').getBoundingClientRect().height) : null,
        bar: bar ? Math.round(bar.getBoundingClientRect().height) : null };
    });
    var stray = [].filter.call(board.querySelectorAll(SEL), function (e) {
      return shown(e) && !hidden(e) && !e.closest('[data-ctl]') && e.getAttribute('tabindex') !== '-1';
    }).map(label);
    var small = [].filter.call(board.querySelectorAll('button, input, a[href]'), function (e) {
      if (!shown(e) || hidden(e)) return false; var t = e.closest('label') || e; var r = t.getBoundingClientRect(); return r.width < 23.5 || r.height < 23.5;
    }).map(function (e) { var r = (e.closest('label') || e).getBoundingClientRect(); return label(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); });
    var over = [], clip = [];
    board.querySelectorAll('*').forEach(function (e) {
      if (!shown(e) || hidden(e)) return;
      var r = e.getBoundingClientRect();
      if (r.right > p.right + 0.5 || r.bottom > p.bottom + 0.5 || r.left < p.left - 0.5 || r.top < p.top - 0.5) over.push((e.textContent || e.tagName).trim().slice(0, 30));
      var cs = getComputedStyle(e);
      if ((cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)) clip.push((e.getAttribute('aria-label') || e.tagName) + ' ' + e.scrollWidth + 'x' + e.scrollHeight + ' in ' + e.clientWidth + 'x' + e.clientHeight);
    });
    var minc = 99, bad = [], digits = [], banned = [], w = document.createTreeWalker(board, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) {
      var t = n.nodeValue.trim(); if (!t) continue;
      var el = n.parentElement; if (!shown(el) && !el.closest('.kin-sr')) continue;
      BANNED.forEach(function (b) { if (t.indexOf(b) >= 0) banned.push(b + ' :: ' + t.slice(0, 40)); });
      if (hidden(el)) continue;
      if (/[0-9]/.test(t) && !el.closest('[data-note]')) digits.push(t.slice(0, 50));
      var fg = rgb(getComputedStyle(el).color); if (!fg) continue;
      var c = ratio(fg.c, bgOf(el));
      if (c < minc) minc = c;
      if (c < 4.5) bad.push(t.slice(0, 30) + ' ' + c.toFixed(2));
    }
    var colors = {}, offToken = {}, danger = [];
    board.querySelectorAll('*').forEach(function (e) {
      var cs = getComputedStyle(e);
      var vals = [cs.color, cs.backgroundColor, cs.borderTopColor, cs.borderRightColor, cs.borderBottomColor, cs.borderLeftColor];
      if (cs.outlineStyle !== 'none') vals.push(cs.outlineColor);
      if (/^(path|rect|circle|ellipse|line|polyline|polygon)$/.test(e.tagName)) { vals.push(cs.fill, cs.stroke); }
      var bs = cs.boxShadow; if (bs && bs !== 'none') (bs.match(/rgba?\([^)]+\)/g) || []).forEach(function (v) { vals.push(v); });
      vals.forEach(function (v) {
        if (!v || v === 'none' || v === 'rgba(0, 0, 0, 0)') return;
        if (/^url/.test(v)) return;
        colors[v] = 1;
        if (!OK[v]) offToken[v] = (offToken[v] || '') + (offToken[v] ? '' : (e.tagName + ' ' + label(e)));
        if (v === 'rgb(255, 123, 114)' && danger.indexOf(label(e)) < 0) danger.push(label(e));
      });
    });
    res.push({
      name: board.getAttribute('data-board'), size: [Math.round(p.width), Math.round(p.height)],
      screens: screens,
      primary: [].filter.call(board.querySelectorAll('[data-primary]'), shown).length,
      stray: stray, small: small, overflow: over, clipped: clip,
      minContrast: +minc.toFixed(2), lowContrast: bad,
      colorsUsed: Object.keys(colors).map(function (v) { return OK[v] || v; }), offToken: offToken, danger: danger,
      banned: banned, digits: digits
    });
  });
  document.getElementById('out').textContent = 'MEASURE' + JSON.stringify(res) + 'ENDMEASURE';
});
""".replace('%TOKENS%', json.dumps(TOKENS))

BASE = f"""html{{background:#0F1216}}
{css}
"""

if only:
    b = next(x for x in boards if x['name'] == only or x['id'] == only.lower())
    page = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>{b['title']}</title><style>
{BASE}</style></head><body>{b['html']}</body></html>
"""
    target = out / f'board-{b["id"]}.html'
else:
    nav = ''.join(f'<a href="#{b["id"]}">{b["title"]}</a>' for b in boards)
    sections = ''.join(
        f'<section class="kin-board" id="{b["id"]}" aria-label="{b["title"]}"><h2 class="kin-board-title">{b["title"]}</h2>'
        f'<div class="kin-board-scroll" tabindex="0" role="group" aria-label="{b["title"]} 아트보드">{b["html"]}</div></section>'
        for b in boards)
    page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinetra Studio SC-03 에이전트 바와 변경안 카드</title>
<style>
{BASE}body{{background:#0F1216;color:#E8EDF2;font-family:Pretendard,'Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;font-size:13px;line-height:20px}}
a{{color:#5B9DFF}}a:hover{{color:#A8CBFF}}
.kin-top{{padding:24px 16px 8px;max-width:1234px;margin:0 auto}}
.kin-top h1{{margin:0 0 4px;font-size:20px;line-height:28px;font-weight:600}}
.kin-top p{{margin:0 0 12px;color:#A9B4C0}}
.kin-nav{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px}}
.kin-board{{max-width:1234px;margin:0 auto;padding:24px 16px 0}}
.kin-board-title{{margin:0 0 8px;font-size:12px;line-height:16px;font-weight:500;color:#A9B4C0}}
.kin-board-scroll{{overflow-x:auto;border:1px solid #26303A;border-radius:8px}}
.kin-foot{{max-width:1234px;margin:0 auto;padding:24px 16px 48px;color:#A9B4C0;font-size:12px}}
</style>
</head>
<body>
<header class="kin-top">
<h1>Kinetra Studio SC-03 에이전트 바와 변경안 카드</h1>
<p>아트보드 S1~S13. 규격: design/briefs/sc-03.md. 토큰과 컴포넌트: design/exports/design-system/. 셸 안의 자리: design/exports/sc-01/. 폭 1200 px(셸 하단 영역), 바 56 px, 카드 영역 상한 306 px. 각 아트보드 위 40 px 줄과 변형 이름 줄은 주석입니다.</p>
<nav class="kin-nav" aria-label="아트보드 목차">{nav}</nav>
</header>
<main>{sections}</main>
<footer class="kin-foot">독립 실행 HTML 내보내기. 외부 요청이 없습니다. 글꼴 파일은 들어 있지 않고, Pretendard와 JetBrains Mono는 설치되어 있을 때만 쓰입니다.</footer>
{'<pre id="out"></pre>' if measure else ''}{'<script>' + MEASURE + '</script>' if measure else ''}
</body>
</html>
"""
    target = out / ('measure.html' if measure else 'index.html')
target.write_text(page, encoding='utf-8')
print(target, len(page.encode('utf-8')))

# Measuring (headless Chrome only, throwaway profile under /tmp, deleted afterwards):
#   P=$(mktemp -d /tmp/kin-sc03-chrome.XXXXXX)
#   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
#     --no-first-run --no-default-browser-check --user-data-dir="$P" --window-size=1400,1000 \
#     --virtual-time-budget=2000 --dump-dom "file://$OUT/measure.html" > dom.html; rm -rf "$P"
