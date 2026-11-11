#!/usr/bin/env python3
"""SC-02 revision (#411): apply the four fixes to the canvas artboards in <project_dir> in place.
usage: revise.py <project_dir>   (folder holding canvas.json and *.dc.html)
Run on a copy of design/exports/sc-02/source/, then make_s3.py for S3; the result equals sc-02-rev/source/."""
import re, sys, json, pathlib
P = pathlib.Path(sys.argv[1])
def rd(n): return (P / n).read_text(encoding='utf-8')
def wr(n, t): (P / n).write_text(t, encoding='utf-8')
def sub1(t, old, new, n=1):
    c = t.count(old)
    assert c == n, f'expected {n} of {old[:80]!r}, found {c}'
    return t.replace(old, new)

MONO = "font-family:'JetBrains Mono',monospace;font-size:13px;line-height:20px;font-weight:500"
LETTER = "font-size:11px;line-height:16px;font-weight:500;color:#A9B4C0"
LOCK = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#A9B4C0" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" role="img" aria-label="편집 잠김"><path d="M2.5 5.5h7v5h-7zM4 5.5V4a2 2 0 0 1 4 0v1.5"/></svg>'
CHEV_R = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6l-3.5 3.5"/></svg>'
CHEV_D = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4.5L6 8l3.5-3.5"/></svg>'
INFO = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#A9B4C0" stroke-width="1.4" stroke-linecap="round" aria-hidden="true" style="flex:none"><circle cx="6" cy="6" r="4.8"/><path d="M6 5.5v3M6 3.6v.2"/></svg>'
FRAME = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#A9B4C0" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex:none"><path d="M2.5 1.5v8h8M2.5 9.5l4.5-3.5"/></svg>'
EX = '<span style="color:#93A0AE;border:1px dotted #7A899B;border-radius:2px;padding:0 4px">예시</span>'
EX_H = '<span style="font-size:11px;line-height:16px;font-weight:400;color:#93A0AE;border:1px dotted #7A899B;border-radius:2px;padding:0 4px">예시</span>'
SIMPLE_H = '<span style="font-size:11px;line-height:16px;font-weight:500;color:#E8EDF2;border:1px solid #3A4654;border-radius:2px;padding:0 4px">단순화 모델</span>'

# ---------- fix 4: centre-of-mass vector as three narrow read-only cells (x / y / z over the values) ----------
def vec(vals=('0.12', '0.00', '0.45'), color=None, lock=False):
    c = f';color:{color}' if color else ''
    top = []
    for i, l in enumerate('xyz'):
        if lock and i == 0:
            top.append(f'<span style="display:flex;align-items:center;justify-content:space-between;{LETTER}">{LOCK}<span>x</span></span>')
        else:
            top.append(f'<span style="{LETTER}">{l}</span>')
    vs = [f'<span style="{MONO}{c}">{v}</span>' for v in vals]
    return ('<span data-vec="질량중심" style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));column-gap:4px;'
            'min-width:0;text-align:right;white-space:nowrap">' + ''.join(top) + ''.join(vs) + '</span>')

OLD_V = "<span style=\"font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;text-align:right;white-space:nowrap\">0.12 0.00 0.45</span>"
OLD_V_GREY = "<span style=\"font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;text-align:right;white-space:nowrap;color:#A9B4C0\">0.12 0.00 0.45</span>"
OLD_V_MIX = "<span style=\"font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;text-align:right;color:#93A0AE\">—</span>"
OLD_V_LOCK = re.compile(r"<span style=\"display:inline-flex;align-items:center;justify-content:flex-end;gap:4px;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:500;white-space:nowrap\"><svg[^>]*aria-label=\"편집 잠김\">.*?</svg>0\.12 0\.00 0\.45</span>", re.S)
HELP_OLD = 'x, y, z · 계산값(읽기 전용)'
HELP_NEW = '계산값(읽기 전용)'

for name, n in [('Main.dc.html', 1), ('S2.dc.html', 4), ('S8.dc.html', 1), ('S9.dc.html', 1), ('S10.dc.html', 1)]:
    t = rd(name)
    t = sub1(t, OLD_V, vec(), n)
    if name == 'S8.dc.html':
        t = sub1(t, OLD_V_GREY, vec(color='#A9B4C0'))
    t = t.replace(HELP_OLD, HELP_NEW)
    wr(name, t)
t = rd('S6.dc.html'); t = sub1(t, OLD_V_MIX, vec(('—', '—', '—'), color='#93A0AE')); wr('S6.dc.html', t)
t = rd('S7.dc.html'); assert len(OLD_V_LOCK.findall(t)) == 1; t = OLD_V_LOCK.sub(lambda m: vec(lock=True), t); wr('S7.dc.html', t)

# ---------- fix 2: catalogue max thrust (cited, read-only) vs declared per-nozzle thrust (one truth) ----------
LBL2 = 'font-size:12px;line-height:16px;font-weight:500;color:#A9B4C0'
NOTE = (f'<div role="note" data-thrust-note="1" style="display:flex;align-items:center;gap:6px;margin:2px 8px 0;padding:4px 8px;border:1px solid #3A4654;'
        f'border-radius:4px;font-size:12px;line-height:16px;color:#E8EDF2">{INFO}선언값이 카탈로그 사양을 넘습니다 (카탈로그 밖)</div>')
CITE_BADGE = ('<button type="button" data-ctl="카탈로그 최대 추력 배지" data-badge="인용" aria-haspopup="dialog" aria-expanded="false" aria-label="값 배지 인용. 누르면 출처를 엽니다" '
              'style="display:inline-flex;align-items:center;height:24px;padding:0;border:0;background:none;color:#C5D0DC;font-size:11px;line-height:16px;font-weight:500;white-space:nowrap;cursor:pointer">'
              '<span style="display:inline-flex;align-items:center;gap:4px;height:20px;box-sizing:border-box;padding:0 8px;border-radius:999px;border:1px solid #7A899B">'
              '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 8.5v-3a2.5 2.5 0 0 1 2.5-2.5M7 8.5v-3a2.5 2.5 0 0 1 2.5-2.5"/></svg>인용</span></button>')
def cat_row():
    return ('<div style="display:grid;grid-template-columns:72px minmax(0,1fr) 28px auto;gap:8px;align-items:center;min-height:28px;padding:0 8px;border-radius:4px">'
            f'<span style="{LBL2}">카탈로그<br>최대 추력</span><span style="{MONO};text-align:right">8.9</span>'
            '<span style="font-size:11px;font-weight:500;color:#A9B4C0">N</span>' + CITE_BADGE + '</div>')

t = rd('S4.dc.html')
for p in 'abcd':
    m = re.search(r'<div style="display:grid;grid-template-columns:72px minmax\(0,1fr\) 28px auto;[^"]*"><label for="s4%s-max".*?data-ctl="최대 추력 배지".*?</button></div>' % p, t, re.S)
    assert m, p
    t = t[:m.start()] + cat_row() + t[m.end():]
    old = f'<label for="s4{p}-noz" style="font-size:12px;font-weight:500;color:#A9B4C0">노즐당 추력</label>'
    t = sub1(t, old, f'<label for="s4{p}-noz" style="{LBL2}">선언<br>노즐당 추력</label>')
    m = re.search(r'<input id="s4%s-noz" data-ctl="노즐당 추력 입력".*?data-ctl="노즐당 추력 배지".*?</button></div>' % p, t, re.S)
    seg = m.group(0).replace('data-ctl="노즐당 추력 입력"', 'data-ctl="선언 노즐당 추력 입력"').replace('data-ctl="노즐당 추력 배지"', 'data-ctl="선언 노즐당 추력 배지"')
    t = t[:m.start()] + seg + NOTE + t[m.end():]
t = sub1(t, '최대 추력 8.9 N은 카탈로그 값이라 <span', '카탈로그 최대 추력 8.9 N은 카탈로그 사양이라 읽기 전용 <span')
t = re.sub(r'노즐당 추력 8 kN은 카탈로그 밖이라 (<span[^>]*>카탈로그 밖 · 사용자 선언</span>)입니다\(design-system\.md 10절\)\.',
           r'선언 노즐당 추력 8 kN은 이 설계에서 사용자가 선언한 값이라 \1입니다(design-system.md 10절). 두 값은 이름이 다른 별개 개념이고, 모델이 쓰는 값은 선언값 하나입니다. 선언값이 사양을 넘는다는 사실은 그 아래 한 줄로 보입니다.', t, count=1)
assert '모델이 쓰는 값은 선언값 하나' in t
t = sub1(t, '조작 요소 (a) 11 · (b) 20 · (c) 13 · (d) 20 ·', '조작 요소 (a) 10 · (b) 19 · (c) 12 · (d) 19 ·')
wr('S4.dc.html', t)

t = rd('S2.dc.html')
t = sub1(t, '<span style="font-size:12px;font-weight:500;color:#A9B4C0">최대 추력</span>', f'<span style="{LBL2}">카탈로그<br>최대 추력</span>')
t = sub1(t, 'data-ctl="최대 추력 배지"', 'data-ctl="카탈로그 최대 추력 배지"')
t = sub1(t, '<span style="font-size:12px;font-weight:500;color:#A9B4C0">노즐당 추력</span>', f'<span style="{LBL2}">선언<br>노즐당 추력</span>')
t = sub1(t, 'data-ctl="노즐당 추력 배지"', 'data-ctl="선언 노즐당 추력 배지"')
m = re.search(r'data-ctl="선언 노즐당 추력 배지".*?</button></div>', t, re.S)
t = t[:m.end()] + NOTE + t[m.end():]
t = sub1(t, '차체 질량 1.3 t, 최대 추력 8.9 N, 노즐당 추력 8 kN만', '차체 질량 1.3 t, 카탈로그 최대 추력 8.9 N, 선언 노즐당 추력 8 kN만')

# ---------- fix 3 (S2 c): direct-open buttons so joint details stay within 2 steps ----------
BTN = 'height:24px;padding:0 8px;border:1px solid #3A4654;border-radius:4px;background:transparent;color:#E8EDF2;font-size:12px;font-weight:500;cursor:pointer'
def direct(j):
    b = ''.join(f'<button type="button" data-ctl="관절 {j} {x} 바로 열기" aria-label="관절 {j}의 {x}를 연 채로 열기" style="{BTN}">{x}</button>' for x in ('축', '한계', '파단 임계'))
    return ('<div style="display:flex;flex-wrap:wrap;align-items:center;gap:4px;padding:2px 8px 0">'
            f'<span style="font-size:11px;line-height:16px;font-weight:500;color:#A9B4C0;margin-right:2px">바로 열기</span>{b}</div>')
for j in 'AB':
    m = re.search(r'data-ctl="관절 %s 종류 배지".*?</button></div>' % j, t, re.S)
    t = t[:m.end()] + direct(j) + t[m.end():]
t = sub1(t, '이름을 누르면 그 관절이 선택되고 축, 한계, 파단 임계가 바로 보입니다(S3).',
         '이름을 누르면 그 관절이 선택되고 종류와 한계·파단 임계 요약이 보입니다. 바로 열기는 그 상세를 연 채로 엽니다(S3).')
t = sub1(t, '(a) 22 · (b) 16 · (c) 14 · (d) 17 =', '(a) 22 · (b) 16 · (c) 20 · (d) 17 =')
wr('S2.dc.html', t)

# ---------- canvas index: S3 is now two panels wide (988, like S8); the row-1 title spans the wider row ----------
t = rd('canvas.json')
t = sub1(t, '"S3.dc.html": {"x": 2480, "y": 0, "w": 644, "h": 882, "title": "S3 관절 선택"}',
         '"S3.dc.html": {"x": 2480, "y": 0, "w": 988, "h": 882, "title": "S3 관절 선택 · (a) 기본 (b) 축 열림"}')
t = sub1(t, '"text": "SC-02 인스펙터 · 강체와 관절", "kind": "title1", "maxW": 3124}', '"text": "SC-02 인스펙터 · 강체와 관절", "kind": "title1", "maxW": 3468}')
wr('canvas.json', t)
print('ok')
