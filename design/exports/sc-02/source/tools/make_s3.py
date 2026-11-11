#!/usr/bin/env python3
"""SC-02 revision: rebuild S3 (joint) as (a) collapsed summary + (b) axis open.
usage: make_s3.py <old S3.dc.html> <out S3.dc.html>"""
import re, sys
sys.path.insert(0, __file__.rsplit('/', 1)[0])
old = open(sys.argv[1], encoding='utf-8').read()
MONO = "font-family:'JetBrains Mono',monospace;font-size:13px;line-height:20px;font-weight:500"
CHEV_R = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4.5 2.5L8 6l-3.5 3.5"/></svg>'
CHEV_D = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2.5 4.5L6 8l3.5-3.5"/></svg>'
FRAME = '<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="#A9B4C0" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="flex:none"><path d="M2.5 1.5v8h8M2.5 9.5l4.5-3.5"/></svg>'
EX = '<span style="color:#93A0AE;border:1px dotted #7A899B;border-radius:2px;padding:0 4px">예시</span>'
EX_H = '<span style="margin-left:auto;font-size:11px;line-height:16px;font-weight:400;color:#93A0AE;border:1px dotted #7A899B;border-radius:2px;padding:0 4px">예시</span>'
SIMPLE_H = '<span style="font-size:11px;line-height:16px;font-weight:500;color:#E8EDF2;border:1px solid #3A4654;border-radius:2px;padding:0 4px">단순화 모델</span>'
HEAD = 'display:flex;align-items:center;gap:8px;width:100%;height:32px;box-sizing:border-box;padding:0 8px;border:0;border-radius:4px;background:transparent;color:#E8EDF2;font-size:13px;line-height:20px;font-weight:600;text-align:left;cursor:pointer'
HINT = 'margin-left:auto;font-size:11px;line-height:16px;font-weight:500;color:#93A0AE'
ROW = 'display:grid;grid-template-columns:64px minmax(0,1fr) 28px auto;gap:8px;align-items:center;min-height:28px;padding:0 8px;border-radius:4px'
SEP = '<div style="height:1px;background:#26303A;margin:4px 0"></div>'
UNIT = 'font-size:11px;font-weight:500;color:#A9B4C0'
LBL = 'font-size:12px;font-weight:500;color:#A9B4C0'

def grab(pattern):
    m = re.search(pattern, old, re.S); assert m, pattern; return m.group(0)
# reuse the exact pieces of the old S3 so everything not under revision stays as it was
head_part = old[:old.index('<div style="width:644px')]
tail_part = old[old.index('</x-dc>'):].replace('"width":644', '"width":988')
shell_mini = grab(r'<div aria-hidden="true" style="position:relative;width:240px.*?</div></div>')
panel_top = grab(r'<div style="flex:none;display:flex;align-items:center;justify-content:space-between;height:40px.*?</button></div>')
title = grab(r'<div style="flex:none;display:flex;align-items:baseline;gap:6px;padding:12px 16px 8px">.*?</div>')
footer = grab(r'<div style="flex:none;display:flex;align-items:center;gap:6px;padding:8px 16px;border-top.*?</div>')
kind_row = grab(r'<div style="display:grid;grid-template-columns:64px[^"]*"><label for="s3-kind".*?</button></div>')
axis_row = grab(r'<div style="display:grid;grid-template-columns:64px[^"]*"><span id="s3-axis-l".*?</button></div>')
badge_default = grab(r'<button type="button" data-ctl="최소 배지".*?</button>')
connected = grab(r'<button type="button" data-ctl="연결된 강체 2".*?</button>')

def badge(ctl): return badge_default.replace('data-ctl="최소 배지"', f'data-ctl="{ctl}"')

def panel(p, axis_open):
    k = kind_row.replace('s3-kind', f's3{p}-kind')
    out = [k, SEP]
    if axis_open:
        a = axis_row.replace('s3-axis-l', f's3{p}-axis-l').replace('>축</span>', '>방향</span>', 1)
        out += [f'<button type="button" data-ctl="축" aria-expanded="true" aria-controls="s3{p}-axis" style="{HEAD}">{CHEV_D}축</button>',
                f'<div id="s3{p}-axis" role="region" aria-label="축" style="display:flex;flex-direction:column;gap:4px;padding:6px 0;border-radius:6px;background:#1B2129">',
                a,
                f'<div data-frame="1" style="display:flex;align-items:center;gap:6px;padding:0 8px 0 80px;font-size:12px;line-height:16px;font-weight:500;color:#E8EDF2">{FRAME}부모 바디 좌표계 기준<span style="font-weight:400;color:#A9B4C0">· 차체</span></div>',
                f'<div style="display:flex;align-items:center;gap:6px;padding:0 8px 0 80px;font-size:11px;line-height:16px;color:#A9B4C0">방향 x, y, z · 단위벡터{EX}</div>',
                '</div>']
    else:
        out += [f'<button type="button" data-ctl="축" aria-expanded="false" style="{HEAD}">{CHEV_R}축<span style="{HINT}">방향 단위벡터 · 부모 바디 좌표계</span></button>']
    out += [SEP,
            f'<button type="button" data-ctl="한계" aria-expanded="false" style="{HEAD}">{CHEV_R}한계{EX_H}</button>',
            f'<div style="{ROW}"><span style="{LBL}">범위</span><span style="{MONO};text-align:right;white-space:nowrap">-90 ~ 90</span><span style="{UNIT}">°</span>{badge("한계 요약 배지")}</div>',
            SEP,
            f'<button type="button" data-ctl="파단 임계" aria-expanded="false" style="{HEAD}">{CHEV_R}파단 임계{SIMPLE_H}{EX_H}</button>',
            f'<div style="{ROW}"><span style="{LBL}">임계값</span><span style="{MONO};text-align:right;white-space:nowrap" aria-describedby="s3{p}-break-d">500</span><span style="{UNIT}">N·m</span>{badge("파단 임계 요약 배지")}</div>',
            f'<div id="s3{p}-break-d" style="padding:0 8px 0 80px;font-size:11px;line-height:16px;color:#A9B4C0">결합부 임계값입니다. 정밀 해석이 아닙니다.</div>',
            SEP, connected, SEP]
    body = '\n'.join(out)
    return (f'<aside data-panel="{p}" aria-label="인스펙터" style="flex:none;width:320px;height:790px;box-sizing:border-box;display:flex;flex-direction:column;background:#151A20;border:1px solid #26303A">\n'
            f'{panel_top}\n{title}\n<div style="flex:1 1 0;min-height:0;padding:0 8px 12px;display:flex;flex-direction:column;gap:4px">\n{body}\n</div>\n{footer}\n</aside>')

def col(label, aside):
    return (f'<div style="flex:none;width:320px;display:flex;flex-direction:column">\n'
            f'<div style="height:28px;display:flex;align-items:center;font-size:12px;line-height:16px;font-weight:500;color:#A9B4C0">{label}</div>\n{aside}\n</div>')

W = '<span style="color:#E8EDF2">'
notes = f'''<div style="flex:none;width:300px;box-sizing:border-box;padding:16px 24px 0 16px;display:flex;flex-direction:column;gap:12px;font-size:12px;line-height:16px;color:#A9B4C0">
{shell_mini}
<div><strong style="color:#E8EDF2;font-weight:600">셸 안의 위치: SC-01 오른쪽 패널</strong><br>320 × 790 px.</div>
<div>관절을 고르면 종류와 요약 두 줄(한계, 파단 임계: 값 · 단위 · 배지)만 보입니다. 축, 한계, 파단 임계의 상세는 접힌 머리 뒤에 있고 한 번에 하나만 열립니다. 머리를 열면 그 요약 줄 자리에 상세 행이 열려 같은 값을 두 번 보이지 않습니다.</div>
<div>닿는 길: S1에서 {W}관절 2</span> 머리(1단계) → {W}관절 A</span> 고르기(2단계)가 (a)입니다. 상세는 S2 (c)의 {W}바로 열기</span>(2단계)로 그 머리를 연 채로 엽니다. 뷰포트에서 관절을 바로 고르면 (a)에서 머리 하나(1단계)입니다.</div>
<div><span style="color:#E8EDF2;font-weight:600">기준 좌표계</span><br>축 단위벡터는 부모 바디(차체) 좌표계 기준입니다. 읽기 전용 라벨이라 조작 요소로 세지 않습니다. 단위 자리 –와 배지는 그대로입니다. 접힌 머리에도 좌표계 이름이 보입니다.</div>
<div><span style="color:#E8EDF2;font-weight:600">파단 임계</span><br>결합부에 걸리는 하중이 이 값을 넘으면 결합이 끊어진다고 보는 단순화 모델입니다(계획 4.6절). 요약 줄에도 늘 "단순화 모델" 라벨이 붙습니다.</div>
<div>한계나 파단 임계를 열면 (b)의 축처럼 그 자리에 최소·최대, 파단 임계 입력 행이 열립니다(그림 생략). 수치는 모두 예시입니다. 관절 종류 목록 전체는 B-06c가 정합니다.</div>
</div>'''

note_bar = ('<div data-note="1" style="flex:none;height:40px;box-sizing:border-box;display:flex;align-items:center;justify-content:space-between;gap:16px;padding:0 16px;border-bottom:1px dashed #7A899B;font-size:12px;line-height:16px;color:#A9B4C0">'
            '<span><strong style="color:#E8EDF2;font-weight:600">S3 관절</strong> · 관절 하나 선택 · (a) 기본 (b) 축 열림</span><span>조작 요소 (a) 9 · (b) 13 · 인스펙터 primary 0</span></div>')
root_open = old[old.index('<div style="width:644px'):old.index('<div data-note="1"')].replace('width:644px', 'width:988px')
page = (head_part + root_open + note_bar + '\n\n<div style="flex:1 1 0;min-height:0;display:flex;padding:0 24px 24px 0">\n\n' + notes + '\n\n'
        '<div style="display:flex;gap:24px">\n' + col('(a) 기본 · 종류와 요약만', panel('a', False)) + '\n' + col('(b) 축 열림 · 기준 좌표계', panel('b', True)) + '\n</div>\n\n</div>\n</div>\n' + tail_part)
open(sys.argv[2], 'w', encoding='utf-8').write(page)
print(len(page))
