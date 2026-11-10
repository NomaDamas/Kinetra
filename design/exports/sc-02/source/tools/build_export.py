#!/usr/bin/env python3
"""Kinetra Studio SC-02 (인스펙터): build the standalone HTML gallery from the canvas artboards.

usage: build_export.py <project_dir> <out_dir> [--measure] [--tokens PATH] [--board NAME]
  <project_dir>  folder holding canvas.json and the *.dc.html artboards (this export's source/)
  --measure      write measure.html instead of index.html: same boards plus a script that
                 reports the self-check numbers into <pre id="out"> (read it with headless
                 Chrome --dump-dom; see the bottom of this file)
  --tokens PATH  design-system tokens.json; with --measure, every colour used is checked against it
  --board NAME   write board-<NAME>.html holding that one artboard at 0,0 (for a screenshot)

Adapted from design/exports/sc-01/source/tools/build_export.py.
The output makes no network request: no web font link, no script source, no image.
Fonts are named only (Pretendard, JetBrains Mono) and fall back to system fonts.
"""
import json, re, sys, pathlib

argv = sys.argv[1:]
only = tokens_path = None
for flag in ('--board', '--tokens'):
    if flag in argv:
        i = argv.index(flag)
        if flag == '--board':
            only = argv[i + 1]
        else:
            tokens_path = argv[i + 1]
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

# design-system.md 9절 + sc-02.md 6절. "확정" alone is allowed (the user confirms a value with Enter);
# the banned form is the agent confirming a value or a verdict.
BANNED = ['현실과 동일', '실제와 똑같이', '검증됨', '보장', '확정했', '판정했', 'FEM', '정밀 해석입니다']


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


boards, css, banned_hits = [], None, []
for name in canvas['order']:
    path = project / name
    if not path.exists():
        raise SystemExit(f'{name}: listed in canvas.json but missing')
    src = path.read_text(encoding='utf-8')
    b = canvas['boards'][name]
    html = body_of(name, src)
    text = re.sub(r'<[^>]+>', ' ', html)
    for word in BANNED:
        if word in text:
            banned_hits.append(f'{name}: {word}')
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

tokens = []
if tokens_path:
    tok = json.loads(pathlib.Path(tokens_path).read_text(encoding='utf-8'))
    tokens = sorted({v.upper() for k, v in tok.items() if isinstance(v, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', v)})

MEASURE = r"""
window.addEventListener('load', function () {
  var TOKENS = __TOKENS__;
  var BANNED = __BANNED__;
  function lum(c) { var a = c.map(function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }); return 0.2126 * a[0] + 0.7152 * a[1] + 0.0722 * a[2]; }
  function rgb(s) { var m = /rgba?\(([^)]+)\)/.exec(s); if (!m) return null; var p = m[1].split(',').map(parseFloat); return { c: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; }
  function hex(c) { return '#' + c.map(function (v) { return ('0' + Math.round(v).toString(16)).slice(-2); }).join('').toUpperCase(); }
  function bgOf(el) { for (var e = el; e; e = e.parentElement) { var b = rgb(getComputedStyle(e).backgroundColor); if (b && b.a > 0.99) return b.c; } return [15, 18, 22]; }
  function ratio(a, b) { var x = lum(a), y = lum(b); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); }
  function shown(el) { var r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; }
  function label(e) { return (e.getAttribute('data-ctl') || e.getAttribute('aria-label') || e.textContent || e.tagName).trim().slice(0, 40); }
  var SEL = 'button, input, select, textarea, a[href], [tabindex="0"]';
  var res = [];
  document.querySelectorAll('[data-board]').forEach(function (board) {
    var p = board.getBoundingClientRect();
    var ctl = [].filter.call(board.querySelectorAll('[data-ctl]'), function (e) { return shown(e) && !e.closest('[data-transient]'); });
    var transient = [].filter.call(board.querySelectorAll('[data-transient] [data-ctl]'), shown);
    var stray = [].filter.call(board.querySelectorAll(SEL), function (e) { return shown(e) && !e.hasAttribute('data-ctl'); }).map(label);
    var small = [].filter.call(board.querySelectorAll('button, input, select, a[href]'), function (e) {
      if (!shown(e)) return false; var r = e.getBoundingClientRect(); return r.width < 23.5 || r.height < 23.5;
    }).map(function (e) { var r = e.getBoundingClientRect(); return label(e) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height); });
    var over = [], clip = [];
    board.querySelectorAll('*').forEach(function (e) {
      if (!shown(e)) return;
      var r = e.getBoundingClientRect();
      if (r.right > p.right + 0.5 || r.bottom > p.bottom + 0.5 || r.left < p.left - 0.5) over.push(label(e));
      var cs = getComputedStyle(e);
      if (e.tagName !== 'SELECT' && e.tagName !== 'INPUT' && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)) clip.push(label(e) + ' ' + e.scrollWidth + 'x' + e.scrollHeight + ' in ' + e.clientWidth + 'x' + e.clientHeight);
      if (e.children.length === 0 && e.clientWidth > 0 && cs.overflowX === 'visible' && e.scrollWidth > e.clientWidth + 1) clip.push('spills its box: ' + label(e) + ' ' + e.scrollWidth + '>' + e.clientWidth);
      if ((e.tagName === 'INPUT' || e.tagName === 'SELECT') && e.scrollWidth > e.clientWidth + 1) clip.push('text cut: ' + label(e) + ' ' + e.scrollWidth + '>' + e.clientWidth);
    });
    // panel content must fit its 790 px height: every child of a panel inside the panel box
    var panels = [].map.call(board.querySelectorAll('[data-panel]'), function (pn) {
      var r = pn.getBoundingClientRect(), spill = [];
      pn.querySelectorAll('*').forEach(function (e) { if (!shown(e)) return; var q = e.getBoundingClientRect(); if (q.bottom > r.bottom + 0.5 || q.right > r.right + 0.5) spill.push(label(e)); });
      return { id: pn.getAttribute('data-panel'), w: Math.round(r.width), h: Math.round(r.height), ctl: [].filter.call(pn.querySelectorAll('[data-ctl]'), function (e) { return shown(e) && !e.closest('[data-transient]'); }).length, spill: spill.slice(0, 5) };
    });
    var minc = 99, bad = [], w = document.createTreeWalker(board, NodeFilter.SHOW_TEXT), n;
    while ((n = w.nextNode())) {
      if (!n.nodeValue.trim()) continue;
      var el = n.parentElement; if (!shown(el)) continue;
      var fg = rgb(getComputedStyle(el).color); if (!fg) continue;
      var c = ratio(fg.c, bgOf(el));
      if (c < minc) minc = c;
      if (c < 4.5) bad.push(n.nodeValue.trim().slice(0, 30) + ' ' + c.toFixed(2));
    }
    var colors = {}, offToken = {}, danger = [];
    board.querySelectorAll('*').forEach(function (e) {
      if (!shown(e)) return;
      var cs = getComputedStyle(e);
      var props = { color: cs.color, background: cs.backgroundColor, outline: cs.outlineStyle !== 'none' ? cs.outlineColor : '' };
      ['Top', 'Right', 'Bottom', 'Left'].forEach(function (s) { if (cs['border' + s + 'Style'] !== 'none' && parseFloat(cs['border' + s + 'Width']) > 0) props['border' + s] = cs['border' + s + 'Color']; });
      if (e instanceof SVGElement) { props.fill = cs.fill; props.stroke = cs.stroke; }
      Object.keys(props).forEach(function (k) {
        var v = rgb(props[k] || ''); if (!v || v.a === 0) return;
        var h = hex(v.c); colors[h] = 1;
        if (TOKENS.length && TOKENS.indexOf(h) < 0 && !(h === '#000000' && v.a < 1)) offToken[h + ' ' + k] = 1;
        if (h === '#FF7B72') danger.push(k + ' on ' + e.tagName.toLowerCase() + (e.id ? '#' + e.id : ''));
      });
    });
    var txt = board.textContent;
    res.push({
      name: board.getAttribute('data-board'),
      controls: ctl.length, names: ctl.map(function (e) { return e.getAttribute('data-ctl'); }),
      transient: transient.map(function (e) { return e.getAttribute('data-ctl'); }),
      primary: [].filter.call(board.querySelectorAll('[data-primary]'), shown).length,
      badges: [].map.call(board.querySelectorAll('[data-badge]'), function (e) { return e.getAttribute('data-badge'); }).filter(function (v, i, a) { return a.indexOf(v) === i; }),
      panels: panels,
      stray: stray, small: small, overflow: over.slice(0, 8), clipped: clip,
      minContrast: +minc.toFixed(2), lowContrast: bad,
      colors: Object.keys(colors).sort(), offToken: Object.keys(offToken), danger: danger,
      banned: BANNED.filter(function (b) { return txt.indexOf(b) >= 0; })
    });
  });
  document.getElementById('out').textContent = 'MEASURE' + JSON.stringify(res) + 'ENDMEASURE';
});
""".replace('__TOKENS__', json.dumps(tokens)).replace('__BANNED__', json.dumps(BANNED, ensure_ascii=False))

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
<title>Kinetra Studio SC-02 인스펙터</title>
<style>
{BASE}body{{background:#0F1216;color:#E8EDF2;font-family:Pretendard,'Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;font-size:13px;line-height:20px}}
a{{color:#5B9DFF}}a:hover{{color:#A8CBFF}}
.kin-top{{padding:24px 16px 8px;max-width:2054px;margin:0 auto}}
.kin-top h1{{margin:0 0 4px;font-size:20px;line-height:28px;font-weight:600}}
.kin-top p{{margin:0 0 12px;color:#A9B4C0}}
.kin-nav{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px}}
.kin-board{{max-width:2054px;margin:0 auto;padding:24px 16px 0}}
.kin-board-title{{margin:0 0 8px;font-size:12px;line-height:16px;font-weight:500;color:#A9B4C0}}
.kin-board-scroll{{overflow-x:auto;border:1px solid #26303A;border-radius:8px;width:max-content;max-width:100%}}
.kin-foot{{max-width:2054px;margin:0 auto;padding:24px 16px 48px;color:#A9B4C0;font-size:12px}}
</style>
</head>
<body>
<header class="kin-top">
<h1>Kinetra Studio SC-02 인스펙터</h1>
<p>아트보드 S1~S10. 규격: design/briefs/sc-02.md. 토큰과 컴포넌트: design/exports/design-system/. 셸: design/exports/sc-01/ 오른쪽 패널(320 px). 각 아트보드 위 40 px 줄과 왼쪽 300 px 열은 주석입니다.</p>
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
if banned_hits:
    print('BANNED', banned_hits)

# Measuring (headless Chrome only, throwaway profile under /tmp, deleted afterwards):
#   P=$(mktemp -d /tmp/kin-sc02-chrome.XXXXXX)
#   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --disable-gpu \
#     --no-first-run --no-default-browser-check --user-data-dir="$P" --window-size=2200,1000 \
#     --virtual-time-budget=2000 --dump-dom "file://$OUT/measure.html" > dom.html; rm -rf "$P"
