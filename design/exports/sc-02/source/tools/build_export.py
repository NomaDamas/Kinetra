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
      if (!e.hasAttribute('data-scroll') && e.tagName !== 'SELECT' && e.tagName !== 'INPUT' && (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') && (e.scrollWidth > e.clientWidth + 1 || e.scrollHeight > e.clientHeight + 1)) clip.push(label(e) + ' ' + e.scrollWidth + 'x' + e.scrollHeight + ' in ' + e.clientWidth + 'x' + e.clientHeight);
      if (e.children.length === 0 && e.clientWidth > 0 && cs.overflowX === 'visible' && e.scrollWidth > e.clientWidth + 1) clip.push('spills its box: ' + label(e) + ' ' + e.scrollWidth + '>' + e.clientWidth);
      // sc-02-rev: a field cell with children (icon + value) must also stay inside its grid track
      if (e.children.length > 0 && e.closest('[data-panel]') && e.clientWidth > 0 && cs.overflowX === 'visible' && e.scrollWidth > e.clientWidth + 1) clip.push('cell spills: ' + label(e) + ' ' + e.scrollWidth + '>' + e.clientWidth);
      if ((e.tagName === 'INPUT' || e.tagName === 'SELECT') && e.scrollWidth > e.clientWidth + 1) clip.push('text cut: ' + label(e) + ' ' + e.scrollWidth + '>' + e.clientWidth);
    });
    // sc-02-rev: a child that sticks out of a field row cell on either side (right-aligned content
    // spills to the left, which scrollWidth does not report)
    var stick = [];
    board.querySelectorAll('[data-panel] [style*="display:grid"] > *').forEach(function (cell) {
      if (!shown(cell)) return; var c = cell.getBoundingClientRect();
      function annot(k) { for (var e = k; e && e !== cell; e = e.parentElement) if (getComputedStyle(e).position === 'absolute') return true; return false; }
      cell.querySelectorAll('*').forEach(function (k) { if (!shown(k) || annot(k)) return; var q = k.getBoundingClientRect();
        if (q.left < c.left - 0.5 || q.right > c.right + 0.5) stick.push(label(cell) + ' > ' + label(k) + ' ' + Math.round(q.left - c.left) + '/' + Math.round(c.right - q.right));
        // an icon squeezed below its drawn size counts as not fitting
        if (k.tagName.toLowerCase() === 'svg' && k.getAttribute('width') && q.width < parseFloat(k.getAttribute('width')) - 0.5) stick.push('icon squeezed in ' + label(cell) + ' ' + q.width.toFixed(1) + '<' + k.getAttribute('width')); });
      var tw = document.createTreeWalker(cell, NodeFilter.SHOW_TEXT), tn;
      while ((tn = tw.nextNode())) { if (!tn.nodeValue.trim() || annot(tn.parentElement)) continue; var rg = document.createRange(); rg.selectNodeContents(tn); var tr = rg.getBoundingClientRect();
        if (tr.width > 0 && (tr.left < c.left - 0.5 || tr.right > c.right + 0.5)) stick.push('text spills ' + label(cell) + ': ' + tn.nodeValue.trim().slice(0, 20)); }
    });
    // panel content must fit its 790 px height: every child of a panel inside the panel box
    var panels = [].map.call(board.querySelectorAll('[data-panel]'), function (pn) {
      var r = pn.getBoundingClientRect(), spill = [];
      pn.querySelectorAll('*').forEach(function (e) { if (!shown(e) || e.closest('[data-scroll]')) return; var q = e.getBoundingClientRect(); if (q.bottom > r.bottom + 0.5 || q.right > r.right + 0.5) spill.push(label(e)); });
      // sc-02-rev2: content inside a scroll region must stay inside the region horizontally; vertically it scrolls
      pn.querySelectorAll('[data-scroll] *').forEach(function (e) { if (!shown(e)) return; var q = e.getBoundingClientRect(), s = e.closest('[data-scroll]').getBoundingClientRect(); if (q.right > s.right + 0.5 || q.left < s.left - 0.5) spill.push('scroll x: ' + label(e)); });
      // sc-02-rev2: a non-scrolling panel body must hold its content; a flex child squeezed below its own size is cut content
      var squeezed = [], bodyOver = [];
      [].forEach.call(pn.children, function (c) {
        var cs = getComputedStyle(c); if (cs.display !== 'flex' && cs.display !== 'grid') return;
        if (!c.hasAttribute('data-scroll') && c.scrollHeight > c.clientHeight + 1) bodyOver.push(label(c).slice(0, 20) + ' ' + c.scrollHeight + '>' + c.clientHeight);
        [].forEach.call(c.children, function (k) { if (!shown(k)) return; var h1 = k.getBoundingClientRect().height, old = k.style.flexShrink; k.style.flexShrink = '0'; var h2 = k.getBoundingClientRect().height; k.style.flexShrink = old; if (h2 > h1 + 0.5) squeezed.push(label(k) + ' ' + h1.toFixed(1) + '<' + h2.toFixed(1)); });
      });
      // sc-02-rev2: scroll region. Heads pinned top/bottom must be fully inside the visible region at the top and at the
      // bottom of the scroll, now and with 600 px of extra content (as if the open section were longer)
      var scroll = [].map.call(pn.querySelectorAll('[data-scroll]'), function (sc) {
        var heads = [].filter.call(sc.querySelectorAll('[data-sticky-top] button[aria-expanded], [data-sticky-heads] button[aria-expanded]'), shown);
        function check(tag) { var bad = []; [0, 1e6].forEach(function (y) { sc.scrollTop = y; var v = sc.getBoundingClientRect(); heads.forEach(function (h) { var q = h.getBoundingClientRect(); if (q.top < v.top - 0.5 || q.bottom > v.bottom + 0.5) bad.push(tag + (y ? ' bottom ' : ' top ') + label(h)); }); }); sc.scrollTop = 0; return bad; }
        var title = pn.querySelector('h2'), t0 = title.getBoundingClientRect().top;
        var res = { content: sc.scrollHeight, visible: sc.clientHeight, heads: heads.map(label), hidden: check('now') };
        var open = sc.querySelector('[role="region"]'), pad = document.createElement('div'); pad.style.height = '600px'; open.appendChild(pad);
        res.stressContent = sc.scrollHeight; res.hidden = res.hidden.concat(check('stress'));
        var dock = sc.querySelector('[data-sticky-heads]'), pinned = sc.querySelector('[data-sticky-top]');
        // stuck positions while scrolled half-way: the dock's bottom edge should meet the region's bottom edge, the top block its top edge
        sc.scrollTop = Math.round((sc.scrollHeight - sc.clientHeight) / 2); var v = sc.getBoundingClientRect();
        if (dock) res.dockGapStuck = +(v.bottom - dock.getBoundingClientRect().bottom).toFixed(1);
        if (pinned) res.topGapStuck = +(pinned.getBoundingClientRect().top - v.top).toFixed(1);
        sc.scrollTop = 1e6;
        res.titleMoved = Math.abs(title.getBoundingClientRect().top - t0) > 0.5; sc.scrollTop = 0; open.removeChild(pad);
        return res;
      });
      return { id: pn.getAttribute('data-panel'), w: Math.round(r.width), h: Math.round(r.height), ctl: [].filter.call(pn.querySelectorAll('[data-ctl]'), function (e) { return shown(e) && !e.closest('[data-transient]'); }).length, spill: spill.slice(0, 5), squeezed: squeezed, bodyOver: bodyOver, scroll: scroll };
    });
    var vec = [].map.call(board.querySelectorAll('[data-vec]'), function (v) {
      var cells = [].filter.call(v.children, function (k) { return /JetBrains/.test(getComputedStyle(k).fontFamily); });
      var fit = cells.map(function (k) { var rg = document.createRange(); rg.selectNodeContents(k); var w = rg.getBoundingClientRect().width; return { v: k.textContent, text: +w.toFixed(1), cell: +k.getBoundingClientRect().width.toFixed(1) }; });
      var ch = (function () { var s = document.createElement('span'); s.style.cssText = getComputedStyle(cells[0]).cssText; s.style.font = getComputedStyle(cells[0]).font; s.style.position = 'absolute'; s.textContent = '0000000000'; v.appendChild(s); var w = s.getBoundingClientRect().width / 10; v.removeChild(s); return w; })();
      var row = v.parentElement, nx = row.nextElementSibling;
      return { fit: fit, charW: +ch.toFixed(2), maxChars: Math.floor(Math.min.apply(null, fit.map(function (f) { return f.cell; })) / ch), frame: !!(nx && nx.hasAttribute('data-frame')) ? nx.textContent.trim() : null, frameFocusable: !!(nx && nx.querySelector(SEL)) };
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
      panels: panels, vec: vec,
      stray: stray, small: small, overflow: over.slice(0, 8), clipped: clip, cellSpill: stick,
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
