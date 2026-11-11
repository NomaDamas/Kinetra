#!/usr/bin/env python3
"""Kinetra Studio DS: build the standalone HTML gallery from the canvas artboards.

usage: build_export.py <project_dir> <out_dir> [--measure]
  <project_dir> holds the *.dc.html artboards and canvas.json; tokens.css is read from it or from its parent
  --measure  write measure.html (natural heights reported into <pre id="out">) instead of index.html
"""
import json, re, sys, pathlib

project = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
measure = '--measure' in sys.argv
out.mkdir(parents=True, exist_ok=True)

canvas = json.loads((project / 'canvas.json').read_text(encoding='utf-8'))
order = canvas['order']

# Initial values of the interactive holes in Controls.dc.html (mode = 조립, planet = 지구).
HOLES = {'primaryLabel': '실행하기'}
for i in range(4):
    on = i == 0
    HOLES[f't{i}bg'] = '#22324A' if on else 'transparent'
    HOLES[f't{i}fg'] = '#E8EDF2' if on else '#A9B4C0'
    HOLES[f't{i}sh'] = 'inset 0 -2px 0 #5B9DFF' if on else 'none'
    HOLES[f't{i}sel'] = 'true' if on else 'false'
    HOLES[f't{i}tab'] = '0' if on else '-1'
for i in range(3):
    on = i == 0
    HOLES[f'p{i}bg'] = '#22324A' if on else 'transparent'
    HOLES[f'p{i}fg'] = '#E8EDF2' if on else '#A9B4C0'
    HOLES[f'p{i}sh'] = 'inset 0 0 0 1px #5B9DFF' if on else 'none'


def body_of(src: str) -> str:
    m = re.search(r'</helmet>(.*)</x-dc>', src, re.S)
    if not m:
        raise SystemExit('no <x-dc> body')
    html = m.group(1).strip()
    # event bindings are replaced by the vanilla script below
    html = re.sub(r'\s+on[A-Z][A-Za-z]*="\{\{[^}]*\}\}"', '', html)
    html = re.sub(r'\s+checked="\{\{p0on\}\}"', ' checked', html)
    html = re.sub(r'\s+checked="\{\{p[12]on\}\}"', '', html)
    html = html.replace('tabIndex=', 'tabindex=')
    # <sc-if value="{{flag}}"> ... </sc-if>  ->  hidden span toggled by the script
    html = re.sub(r'<sc-if value="\{\{\s*(\w+)\s*\}\}"[^>]*>(.*?)</sc-if>',
                  lambda m: f'<span data-if="{m.group(1)}" hidden style="display:contents">{m.group(2)}</span>', html, flags=re.S)
    html = re.sub(r'\{\{\s*(\w+)\s*\}\}', lambda m: HOLES[m.group(1)], html)
    if '{{' in html or '<sc-' in html:
        raise SystemExit('unresolved template syntax left in export')
    return html


boards = []
for name in order:
    src = (project / name).read_text(encoding='utf-8')
    b = canvas['boards'][name]
    html = body_of(src)
    # root: fixed canvas height -> min-height (export never clips); measuring uses natural height
    root_h = re.match(r'<div style="width:(\d+)px;height:(\d+)px;', html)
    if not root_h:
        raise SystemExit(f'{name}: unexpected root')
    w, h = int(root_h.group(1)), int(root_h.group(2))
    assert (w, h) == (b['w'], b['h']), f'{name}: root {w}x{h} != canvas {b["w"]}x{b["h"]}'
    repl = f'<div data-board="{name}" style="width:{w}px;' + ('' if measure else f'min-height:{h}px;')
    html = html.replace(root_h.group(0), repl, 1)
    boards.append({'name': name, 'id': name.split('.')[0].lower(), 'title': b.get('title', name), 'w': w, 'h': h, 'html': html})

# tokens.css sits beside the artboards when exported from Claude Design, and one level up (next to source/) in the repo and the zip.
tokens_path = next((p for p in (project / 'tokens.css', project.parent / 'tokens.css') if p.is_file()), None)
if tokens_path is None:
    raise SystemExit(f'tokens.css not found in {project} or {project.parent}')
tokens_css = tokens_path.read_text(encoding='utf-8')

SCRIPT = r"""
(function () {
  var labels = ['실행하기', '1회 실행', '판정 실행', '내보내기'];
  function show(flag, on) {
    document.querySelectorAll('[data-if="' + flag + '"]').forEach(function (el) { el.hidden = !on; el.style.display = on ? 'contents' : 'none'; });
  }
  show('isRun', false); show('changed', false);
  var list = document.querySelector('[data-live="mode"]');
  var primary = document.querySelector('[data-live="primary"]');
  if (list && primary) {
    var tabs = Array.prototype.slice.call(list.querySelectorAll('[role="tab"]'));
    var setMode = function (n, focus) {
      tabs.forEach(function (t, i) {
        var on = i === n;
        t.setAttribute('aria-selected', on ? 'true' : 'false');
        t.tabIndex = on ? 0 : -1;
        t.style.background = on ? '#22324A' : 'transparent';
        t.style.color = on ? '#E8EDF2' : '#A9B4C0';
        t.style.boxShadow = on ? 'inset 0 -2px 0 #5B9DFF' : 'none';
      });
      primary.querySelector('span:last-child').textContent = labels[n];
      show('isRun', n === 1);
      if (focus) tabs[n].focus();
    };
    tabs.forEach(function (t, i) { t.addEventListener('click', function () { setMode(i, false); }); });
    list.addEventListener('keydown', function (e) {
      var d = e.key === 'ArrowRight' ? 1 : e.key === 'ArrowLeft' ? -1 : 0;
      if (!d) return;
      e.preventDefault();
      var cur = tabs.findIndex(function (t) { return t.getAttribute('aria-selected') === 'true'; });
      setMode((cur + d + tabs.length) % tabs.length, true);
    });
  }
  var group = document.querySelector('[data-live="planet"]');
  if (group) {
    var radios = Array.prototype.slice.call(group.querySelectorAll('input[type="radio"]'));
    radios.forEach(function (r) {
      r.addEventListener('change', function () {
        radios.forEach(function (x) {
          var on = x.checked, l = x.parentElement;
          l.style.background = on ? '#22324A' : 'transparent';
          l.style.color = on ? '#E8EDF2' : '#A9B4C0';
          l.style.boxShadow = on ? 'inset 0 0 0 1px #5B9DFF' : 'none';
        });
        show('changed', true);
      });
    });
  }
})();
"""

MEASURE = r"""
window.addEventListener('load', function () {
  var go = function () {
    var res = [];
    document.querySelectorAll('[data-board]').forEach(function (el) {
      var over = [];
      el.querySelectorAll('*').forEach(function (c) {
        var r = c.getBoundingClientRect(), p = el.getBoundingClientRect();
        if (r.right > p.right + 1 && r.width > 0) over.push(Math.round(r.right - p.right));
      });
      res.push({ name: el.getAttribute('data-board'), natural: Math.ceil(el.getBoundingClientRect().height), overflowX: over.length ? Math.max.apply(null, over) : 0 });
    });
    document.getElementById('out').textContent = 'MEASURE' + JSON.stringify(res) + 'ENDMEASURE';
  };
  (document.fonts && document.fonts.ready ? document.fonts.ready : Promise.resolve()).then(go, go);
});
"""

nav = ''.join(f'<a href="#{b["id"]}">{b["title"]}</a>' for b in boards)
sections = ''.join(
    f'<section class="kin-board" id="{b["id"]}" aria-label="{b["title"]}"><h2 class="kin-board-title">{b["title"]}</h2>'
    f'<div class="kin-board-scroll" tabindex="0" role="group" aria-label="{b["title"]} 갤러리">{b["html"]}</div></section>'
    for b in boards)

page = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kinetra Studio 디자인 시스템</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
{tokens_css}
html{{background:#0F1216}}
body{{margin:0;background:#0F1216;color:#E8EDF2;font-family:var(--kin-font-ui);font-size:13px;line-height:20px}}
button,input{{font-family:inherit}}
input::placeholder{{color:#93A0AE;opacity:1}}
a{{color:#5B9DFF}}a:hover{{color:#A8CBFF}}
label:has(input:focus-visible){{outline:2px solid #A8CBFF;outline-offset:2px}}
.kin-top{{padding:24px 16px 8px;max-width:1840px;margin:0 auto}}
.kin-top h1{{margin:0 0 4px;font:var(--kin-type-heading)}}
.kin-top p{{margin:0 0 12px;color:#A9B4C0}}
.kin-nav{{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px}}
.kin-board{{max-width:1840px;margin:0 auto;padding:24px 16px 0}}
.kin-board-title{{margin:0 0 8px;font:var(--kin-type-label);color:#A9B4C0}}
.kin-board-scroll{{overflow-x:auto;border:1px solid #26303A;border-radius:8px}}
.kin-foot{{max-width:1840px;margin:0 auto;padding:24px 16px 48px;color:#A9B4C0;font-size:12px}}
</style>
</head>
<body>
<header class="kin-top">
<h1>Kinetra Studio 디자인 시스템</h1>
<p>토큰과 공통 컴포넌트 갤러리. 규격: design/briefs/design-system.md. 토큰 파일: tokens.css, tokens.json.</p>
<nav class="kin-nav" aria-label="갤러리 목차">{nav}</nav>
</header>
<main>{sections}</main>
<footer class="kin-foot">독립 실행 HTML 내보내기. 글꼴 파일은 들어 있지 않습니다. JetBrains Mono는 온라인일 때 Google Fonts에서 불러오고, Pretendard는 설치되어 있을 때만 쓰입니다.</footer>
{'<pre id="out"></pre>' if measure else ''}
<script>{MEASURE if measure else SCRIPT}</script>
</body>
</html>
"""
target = out / ('measure.html' if measure else 'index.html')
target.write_text(page, encoding='utf-8')
print(target, len(page))
