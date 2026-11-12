#!/usr/bin/env python3
"""SC-02 revision 2 (#411, design/briefs/sc-02-revision-2.md): edits a copy of the canvas sources in place.

usage: revise2.py <project_dir>
  <project_dir>  a copy of design/exports/sc-02/source/ (canvas.json + *.dc.html)

1. Centre-of-mass rows (S1, S2, S6, S7, S8, S9, S10) get the read-only frame label "조립체 원점 기준",
   written the way S3 writes its joint-axis frame label (axis icon + type.label 12 px, value column).
2. The centre-of-mass value becomes one line per axis (x / y / z), each with its unit, so a signed
   6-character value fits. Example values: x 0.12, y -12.35, z 0.45 m.
3. S2 (d) and S4 (b)(c)(d): the panel body becomes a vertical scroll region (title rows stay fixed).
   Collapsed section heads stay visible: the ones above the open section and the open head pin to
   the top of the scroll region; the ones below it pin to the bottom (as SC-04 S2).
Item 4 (re-measure) is build_export.py --measure.
"""
import re, sys, pathlib

proj = pathlib.Path(sys.argv[1])
MONO = "font-family:'JetBrains Mono',monospace;font-size:13px;line-height:20px;font-weight:500"
AXIS = "font-size:11px;line-height:20px;font-weight:500;color:#A9B4C0"
UNIT_M = '<span style="font-size:11px;font-weight:500;color:#A9B4C0">m</span>'
FRAME = ('<div data-frame="1" style="display:flex;align-items:center;gap:6px;padding:0 8px 0 80px;font-size:12px;'
         'line-height:16px;font-weight:500;color:#E8EDF2"><svg width="12" height="12" viewBox="0 0 12 12" fill="none" '
         'stroke="#A9B4C0" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" '
         'style="flex:none"><path d="M2.5 1.5v8h8M2.5 9.5l4.5-3.5"/></svg>조립체 원점 기준</div>')
OLD_VALUES = ['0.12', '0.00', '0.45']
NEW_VALUES = ['0.12', '-12.35', '0.45']


def com_row(line: str) -> str:
    start = line.index('<span data-vec="질량중심"')
    end = line.index(UNIT_M, start)
    vec = line[start:end]
    vals = re.findall(r"<span style=\"" + re.escape(MONO) + r"(;color:#[0-9A-F]{6})?\">([^<]*)</span>", vec)
    assert len(vals) == 3, vals
    colors = [c for c, _ in vals]
    values = [v for _, v in vals]
    if values == OLD_VALUES:
        values = NEW_VALUES
    lock = re.search(r'<svg[^>]*aria-label="편집 잠김".*?</svg>', vec)
    cols = '12px 12px minmax(0,1fr)' if lock else '12px minmax(0,1fr)'
    cells = []
    for i, (axis, val, col) in enumerate(zip('xyz', values, colors)):
        if lock:
            cells.append(f'<span style="display:flex;align-items:center;height:20px">{lock.group(0) if i == 0 else ""}</span>')
        cells.append(f'<span style="{AXIS}">{axis}</span>')
        cells.append(f'<span style="{MONO}{col};text-align:right">{val}</span>')
    new_vec = (f'<span data-vec="질량중심" style="display:grid;grid-template-columns:{cols};column-gap:6px;'
               f'min-width:0;padding-top:2px;white-space:nowrap">' + ''.join(cells) + '</span>')
    units = ('<span style="display:grid;padding-top:2px;font-size:11px;line-height:20px;font-weight:500;color:#A9B4C0">'
             '<span>m</span><span>m</span><span>m</span></span>')
    line = line[:start] + new_vec + units + line[end + len(UNIT_M):]
    # the row: top-aligned so the label and the badge sit on the x line
    line = re.sub(r'^(<div style="display:grid;grid-template-columns:64px minmax\(0,1fr\) 28px(?: auto)?;gap:[^;]+;)'
                  r'align-items:center;min-height:28px;padding:0 8px;',
                  r'\1align-items:start;min-height:28px;padding:2px 8px;', line, count=1)
    assert 'align-items:start' in line[:200], line[:200]
    line = line.replace('<span style="font-size:12px;font-weight:500;color:#A9B4C0">질량중심</span>',
                        '<span style="font-size:12px;line-height:24px;font-weight:500;color:#A9B4C0">질량중심</span>', 1)
    # S6: the read-only "섞임" in the badge column sits on the x line like a badge would
    line = line.replace('<span style="font-size:11px;line-height:16px;font-weight:500;color:#A9B4C0;padding:0 8px">섞임</span>',
                        '<span style="font-size:11px;line-height:24px;font-weight:500;color:#A9B4C0;padding:0 8px">섞임</span>', 1)
    return line


changed = {}
for f in sorted(proj.glob('*.dc.html')):
    L = f.read_text(encoding='utf-8').split('\n')
    out, n = [], 0
    for line in L:
        if 'data-vec="질량중심"' in line:
            out.append(com_row(line))
            out.append(FRAME)
            n += 1
        else:
            out.append(line)
    if n:
        f.write_text('\n'.join(out), encoding='utf-8')
        changed[f.name] = n

# S1 annotation: the new label is read-only and not counted
m = proj / 'Main.dc.html'
t = m.read_text(encoding='utf-8')
old = '<div>세지 않은 것: 제목, 단위, 질량중심 수치(읽기 전용), 아래 줄의 안내 글자.</div>'
new = ('<div>세지 않은 것: 제목, 단위, 질량중심 수치와 기준 좌표계 라벨(읽기 전용), 아래 줄의 안내 글자.</div>\n'
       '<div>질량중심은 축마다 한 줄(x, y, z)이고 각 줄에 단위가 붙습니다. 기준은 <span style="color:#E8EDF2">조립체 원점</span>입니다. '
       '배지는 셋을 묶어 하나입니다.</div>')
assert t.count(old) == 1
m.write_text(t.replace(old, new), encoding='utf-8')

# ---- 3. scroll region with pinned heads
BODY_OLD = '<div style="flex:1 1 0;min-height:0;padding:0 8px 12px;display:flex;flex-direction:column;gap:4px">'
BODY_NEW = ('<div data-scroll="1" style="flex:1 1 0;min-height:0;overflow-y:auto;padding:0 8px 12px;display:grid;'
            'grid-template-columns:minmax(0,1fr);align-content:start;gap:4px">')
PIN = 'display:grid;grid-template-columns:minmax(0,1fr);gap:4px;margin:0 -8px;padding:0 8px;background:#151A20'
TOP_OPEN = f'<div data-sticky-top="1" style="position:sticky;top:0;z-index:1;{PIN}">'
BOTTOM_OPEN = f'<div data-sticky-heads="1" style="position:sticky;bottom:-12px;z-index:1;{PIN}">'


def depth_delta(s: str) -> int:
    return len(re.findall(r'<div\b', s)) - s.count('</div>')


def scroll_panel(L, panel, first_top_head):
    a = next(i for i, l in enumerate(L) if f'<aside data-panel="{panel}"' in l)
    body = next(i for i in range(a, len(L)) if L[i] == BODY_OLD)
    L[body] = BODY_NEW
    # body end: matching </div>
    d, end = 0, None
    for i in range(body, len(L)):
        d += depth_delta(L[i])
        if d == 0:
            end = i
            break
    top = next(i for i in range(body, end) if f'data-ctl="{first_top_head}"' in L[i])
    opened = next(i for i in range(body, end) if 'aria-expanded="true"' in L[i] and L[i].startswith('<button'))
    # open region: the block right after the open head
    d, rend = 0, None
    for i in range(opened + 1, end):
        d += depth_delta(L[i])
        if d == 0:
            rend = i
            break
    below = L[rend + 1:end]
    heads_below = [l for l in below if l.startswith('<button') and 'aria-expanded="false"' in l]
    new = L[:top] + [TOP_OPEN] + L[top:opened + 1] + ['</div>'] + L[opened + 1:rend + 1]
    if heads_below:
        new += [BOTTOM_OPEN] + below + ['</div>']
    else:
        new += below
    new += L[end:]
    return new


NOTE = ('<div>펼친 내용이 패널보다 길면 <span style="color:#E8EDF2">본문만 세로로 스크롤</span>됩니다. 머리(인스펙터 줄, 제목 줄)는 고정입니다. '
        '스크롤해도 섹션 머리의 이름과 개수가 보이도록, 열린 머리와 그 위의 접힌 머리는 본문 위쪽에, 그 아래의 접힌 머리는 본문 아래쪽에 붙습니다. '
        '기본 줄(질량, 재질, 질량중심, 관성 보기)은 본문과 함께 스크롤됩니다.</div>')
for fname, plan, anchor in [
    ('S2.dc.html', [('d', '재질 세부')], '<div>열린 섹션 안의 수치는 예시입니다.'),
    ('S4.dc.html', [('b', '추력 곡선'), ('c', '추력 곡선'), ('d', '추력 곡선')], '<div>곡선, 추진제 질량, 스케줄의 수치는 예시입니다.'),
]:
    p = proj / fname
    L = p.read_text(encoding='utf-8').split('\n')
    for panel, head in plan:
        L = scroll_panel(L, panel, head)
    t = '\n'.join(L)
    assert t.count(anchor) == 1, (fname, anchor)
    t = t.replace(anchor, NOTE.replace('기본 줄(질량, 재질, 질량중심, 관성 보기)', '기본 줄(종류, 카탈로그 최대 추력, 선언 노즐당 추력)' if fname == 'S4.dc.html' else '기본 줄(질량, 재질, 질량중심, 관성 보기)') + '\n' + anchor, 1)
    p.write_text(t, encoding='utf-8')

print('com rows', changed)
