#!/usr/bin/env python3
"""SC-01 Studio 셸: 아트보드 S1~S10의 원본(*.dc.html)과 canvas.json, 독립 갤러리(index.html)를 만든다.

usage: build_sc01.py <out_dir> [--tokens <design-system/tokens.json>] [--artifact <path>]
  <out_dir>/source/*.dc.html, <out_dir>/source/canvas.json  아트보드 원본 (Claude Design 캔버스 형식)
  <out_dir>/index.html                                       원본에서 다시 읽어 이어 붙인 독립 갤러리 (외부 요청 없음)
  <out_dir>/source/tools/selfcheck.json                      아트보드별 상시 조작 요소 이름과 수, primary 수
  --tokens    쓰인 모든 hex가 승인된 토큰 값인지 확인한다 (새 색이 있으면 멈춘다)
  --artifact  같은 갤러리를 Artifact 게시용 조각(문서 뼈대 없음)으로도 쓴다

규격: design/briefs/sc-01.md. 색·글자·간격·컴포넌트 마크업은 design/exports/design-system/(v0)의 것을 그대로 옮겼다.
"""
import json, re, sys, pathlib, html as _html

# ---------------------------------------------------------------- 토큰 (design-system/tokens.json의 값 그대로)
APP, PANEL, CARD, RAISED, FIELD, HOVER, SEL = '#0F1216', '#151A20', '#1B2129', '#222A33', '#0F1318', '#263039', '#22324A'
B_SUB, B_DEF, B_STR = '#26303A', '#3A4654', '#7A899B'
T1, T2, T3 = '#E8EDF2', '#A9B4C0', '#93A0AE'
ACC, ACC_ON, FOCUS = '#5B9DFF', '#08111F', '#A8CBFF'
WARN, INFO = '#F2B84B', '#8FB8E8'
EV = {  # 증거 강도: (글자·테두리, 바탕, 막대 칸 수)
    'none': ('#93A0AE', '#1B2129', 0), 'l0': ('#A0ACBB', '#1F252D', 1),
    'l1': ('#BBAFF3', '#2A2444', 2), 'l2': ('#D2BFFF', '#322858', 3),
}
SHADOW = '0 8px 24px rgba(0,0,0,0.5)'  # elevation.3
UI = "Pretendard,'Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif"
MONO = "'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace"
W, H = 1440, 900
TOP, AGENT, TL_S, TL_L, BANNER = 48, 56, 32, 120, 32
LEFT, RIGHT, RAIL = 240, 320, 40

e = _html.escape


# ---------------------------------------------------------------- 아이콘
def ico(inner, size=12, sw=1.5, fill='none', vb=None):
    vb = vb or f'0 0 {size} {size}'
    stroke = '' if fill != 'none' else f' stroke="currentColor" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round"'
    return f'<svg width="{size}" height="{size}" viewBox="{vb}" fill="{fill}"{stroke} aria-hidden="true">{inner}</svg>'


I_LEFT = ico('<path d="M7.5 2.5L4 6l3.5 3.5"/>')
I_RIGHT = ico('<path d="M4.5 2.5L8 6l-3.5 3.5"/>')
I_UP = ico('<path d="M2.5 7.5L6 4l3.5 3.5"/>')
I_DOWN = ico('<path d="M2.5 4.5L6 8l3.5-3.5"/>')
I_MORE = ico('<circle cx="3" cy="7" r="1.2"/><circle cx="7" cy="7" r="1.2"/><circle cx="11" cy="7" r="1.2"/>', 14, fill='currentColor')
I_MIC = ico('<rect x="5" y="1.5" width="4" height="7" rx="2"/><path d="M2.5 7a4.5 4.5 0 0 0 9 0M7 11.5v1.5"/>', 14, 1.4)
I_PLAY = ico('<path d="M2 1l7 4-7 4z"/>', 10, fill='currentColor')
I_PLAY12 = ico('<path d="M3 1.5l7.5 4.5L3 10.5z"/>', 12, fill='currentColor')
I_PAUSE = ico('<rect x="2.5" y="2" width="2.5" height="8" rx=".5"/><rect x="7" y="2" width="2.5" height="8" rx=".5"/>', 12, fill='currentColor')
I_REWIND = ico('<path d="M2.5 6a3.5 3.5 0 1 0 1-2.5M2.5 1.5v2.5H5"/>', 12, 1.4)
I_SEARCH = ico('<circle cx="5.2" cy="5.2" r="3.4"/><path d="M7.8 7.8l2.7 2.7"/>', 12, 1.4)
I_CLOSE = ico('<path d="M2.5 2.5l7 7M9.5 2.5l-7 7"/>')
I_SPIN = ico('<path d="M6 1.5a4.5 4.5 0 1 1-4.5 4.5"/>', 12, 1.6)
I_WARN = ico('<path d="M8 2l6.5 11.5h-13zM8 6.5v3.5M8 11.8v.2"/>', 14, 1.5, vb='0 0 16 16')
I_LIB = ico('<rect x="2" y="2" width="4" height="4" rx=".5"/><rect x="8" y="2" width="4" height="4" rx=".5"/><rect x="2" y="8" width="4" height="4" rx=".5"/><rect x="8" y="8" width="4" height="4" rx=".5"/>', 14, 1.4)
I_INSP = ('<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" aria-hidden="true">'
          '<path d="M2 4h10M2 10h10"/><circle cx="5" cy="4" r="1.6" fill="#151A20"/><circle cx="9" cy="10" r="1.6" fill="#151A20"/></svg>')
TRI = '<svg width="14" height="14" viewBox="0 0 14 14" aria-hidden="true"><path d="M7 1.5l6 11H1z" fill="currentColor"/></svg>'
DOT = '<svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true"><circle cx="6" cy="6" r="4.5" fill="currentColor"/></svg>'


def bars(n, label=True):
    parts_f = ''.join(f'M{8*i} 0h6v12H{8*i}z' for i in range(n))
    parts_e = ''.join(f'M{8*i+.5:g} .5h5v11h-5z' for i in range(n, 4))
    aria = f'role="img" aria-label="증거 강도 {n}/4"' if label else 'aria-hidden="true"'
    s = f'<svg width="30" height="12" viewBox="0 0 30 12" {aria}>'
    if parts_f:
        s += f'<path d="{parts_f}" fill="currentColor"/>'
    if parts_e:
        s += f'<path d="{parts_e}" fill="none" stroke="currentColor"/>'
    return s + '</svg>'


def kbd(t):
    return f'<kbd style="font-family:{MONO};font-size:11px;line-height:16px;color:{T2};border:1px solid {B_DEF};border-radius:2px;padding:0 4px">{t}</kbd>'


BUSY = ' aria-busy="true"'
EXP_T = ' aria-expanded="true"'
SR = 'position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap'


# ---------------------------------------------------------------- 보드 문맥: 상시 조작 요소를 이름과 함께 센다
class Ctx:
    def __init__(self, bid):
        self.bid, self.ctls, self.reveals, self.primary, self.n = bid, [], [], 0, 0

    def c(self, name):
        """상시 조작 요소 하나 (0절 2번의 세는 법)."""
        self.ctls.append(name)
        return f' data-ctl="{e(name)}"'

    def r(self, name):
        """공개(3.2절)로 열려 있는 동안만 보이는 요소. 상시 수에는 넣지 않고 따로 적는다."""
        self.reveals.append(name)
        return f' data-rev="{e(name)}"'

    def uid(self, p):
        self.n += 1
        return f'{self.bid}-{p}{self.n}'


# ---------------------------------------------------------------- 공통 컴포넌트 (design-system 마크업)
def btn_primary(x, label, icon='', disabled=False, describedby=None):
    x.primary += 1
    if disabled:
        st = f'height:32px;padding:0 16px;border:1px solid {B_DEF};border-radius:4px;background:{RAISED};color:{T3};font-size:12px;font-weight:600;cursor:not-allowed;display:inline-flex;align-items:center;gap:6px'
        extra = ' aria-disabled="true"' + (f' aria-describedby="{describedby}"' if describedby else '')
    else:
        st = f'height:32px;padding:0 16px;border:0;border-radius:4px;background:{ACC};color:{ACC_ON};font-size:12px;font-weight:600;display:inline-flex;align-items:center;gap:6px;cursor:pointer'
        extra = ''
    return f'<button type="button" data-primary="1"{extra}{x.c("주 행동 · " + label)} style="{st}">{icon}<span>{label}</span></button>'


def btn_secondary(x, label, name=None, rev=False, extra='', disabled=False):
    mark = x.r(name or label) if rev else x.c(name or label)
    if disabled:
        st = f'height:28px;padding:0 12px;border:1px solid {B_DEF};border-radius:4px;background:transparent;color:{T3};font-size:12px;font-weight:500;cursor:not-allowed'
        extra += ' aria-disabled="true"'
    else:
        st = f'height:28px;padding:0 12px;border:1px solid {B_STR};border-radius:4px;background:transparent;color:{T1};font-size:12px;font-weight:500;cursor:pointer'
    return f'<button type="button"{extra}{mark} style="{st}">{label}</button>'


def btn_icon(x, aria, icon, name=None, rev=False, extra='', size=28, fg=T1, bg='transparent', style=''):
    mark = x.r(name or aria) if rev else x.c(name or aria)
    return (f'<button type="button" aria-label="{e(aria)}"{extra}{mark} style="width:{size}px;height:{size}px;padding:0;border:1px solid transparent;'
            f'border-radius:4px;background:{bg};color:{fg};display:inline-flex;align-items:center;justify-content:center;cursor:pointer;flex:none;{style}">{icon}</button>')


def tooltip(text, style, tid=None):
    i = f' id="{tid}"' if tid else ''
    return (f'<span role="tooltip"{i} style="position:absolute;z-index:6;white-space:nowrap;background:{RAISED};border-radius:8px;box-shadow:{SHADOW};'
            f'padding:6px 10px;color:{T1};font-size:12px;line-height:16px;font-weight:500;display:inline-flex;align-items:center;gap:8px;{style}">{text}</span>')


EX = f'<span style="font-size:11px;line-height:16px;color:{T3};border:1px dotted {B_STR};border-radius:2px;padding:0 4px;white-space:nowrap">예시</span>'

VB = {  # 값 배지 5종 중 이 화면이 쓰는 것: (글자색, 안쪽 span 스타일, 글리프)
    'cite': ('#C5D0DC', f'border:1px solid {B_STR}', '<path d="M2.5 8.5v-3a2.5 2.5 0 0 1 2.5-2.5M7 8.5v-3a2.5 2.5 0 0 1 2.5-2.5"/>'),
    'declared': ('#F2A8D0', 'background:#3A1D2E', '<path d="M2 10l.6-2.6 5.6-5.6 2 2-5.6 5.6z"/>'),
    'sim': (T1, 'background:#303B49', '<path d="M1 6q1.25-5 2.5 0t2.5 0t2.5 0t2.5 0"/>'),
    'stale': (T1, f'background:#303B49;border:1px dashed {T2}', '<path d="M1 6q1.25-5 2.5 0t2.5 0t2.5 0t2.5 0"/>'),
}


def vbadge(x, kind, label, as_button=True, name=None):
    fg, inner, glyph = VB[kind]
    g = ('<svg width="12" height="12" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.4" '
         f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{glyph}</svg>')
    span = (f'<span style="display:inline-flex;align-items:center;gap:4px;height:20px;box-sizing:border-box;padding:0 8px;'
            f'border-radius:999px;{inner}">{g}{label}</span>')
    if not as_button:  # 목록 항목 안: 목록이 하나의 조작 요소라서 배지는 읽기 전용으로 그린다
        return f'<span style="display:inline-flex;align-items:center;height:24px;color:{fg};font-size:11px;line-height:16px;font-weight:500;white-space:nowrap">{span}</span>'
    return (f'<button type="button" aria-label="값 배지: {e(label)}. 근거 보기"{x.c(name or ("값 배지 · " + label))} style="display:inline-flex;align-items:center;height:24px;padding:0;border:0;'
            f'background:none;color:{fg};font-size:11px;line-height:16px;font-weight:500;white-space:nowrap;cursor:pointer;font-family:inherit">{span}</button>')


def ev_pill(level, parts, x=None, name='증거 배지', aria='', expanded=None):
    """상단바 증거 배지(누르면 근거 팝오버). parts: [(mono?, text)]."""
    fg, bg, n = EV[level]
    inner = bars(n) + ''.join(f'<span style="font-family:{MONO}">{t}</span>' if m else f'<span>{t}</span>' for m, t in parts)
    st = (f'display:inline-flex;align-items:center;gap:8px;height:28px;box-sizing:border-box;padding:0 12px;border-radius:999px;'
          f'background:{bg};border:1px solid {fg};color:{fg};font-size:12px;font-weight:500;white-space:nowrap;cursor:pointer;font-family:inherit')
    ex = '' if expanded is None else f' aria-expanded="{str(expanded).lower()}"'
    return f'<button type="button" aria-haspopup="dialog"{ex} aria-label="{e(aria)}. 근거 보기"{x.c(name)} style="{st}">{inner}</button>'


def ev_chip(level, text):
    """작은 읽기 전용 증거 칩(타임라인, 카드 안). 조작 요소가 아니다."""
    fg, bg, n = EV[level]
    return (f'<span style="display:inline-flex;align-self:flex-start;align-items:center;gap:6px;height:20px;box-sizing:border-box;padding:0 8px;border-radius:999px;'
            f'background:{bg};border:1px solid {fg};color:{fg};font-size:11px;font-weight:500;white-space:nowrap">{bars(n)}{text}</span>')


def l3_line():
    c = EV['none'][0]
    return (f'<span style="display:inline-flex;align-items:center;gap:8px;color:{c};font-size:12px;line-height:16px;font-weight:500;white-space:nowrap">'
            f'{bars(0)}<span><span style="font-family:{MONO}">L3</span> 실물 검증 없음</span></span>')


# ---------------------------------------------------------------- 상단바
MODES = ['조립', '실행', '판정', 'Halo']
PLANETS = ['지구', '화성', '달']


def topbar(x, mode, planet, badge, primary, offline=False, planet_busy=False, open_=None, tab_focus=False):
    # 프로젝트 이름: 누르면 제자리 편집
    name = (f'<button type="button" aria-label="프로젝트 이름: 점프 로버. 눌러서 바꾸기"{x.c("프로젝트 이름")} style="height:28px;padding:0 8px;border:1px solid transparent;'
            f'border-radius:4px;background:transparent;color:{T1};font-size:13px;line-height:20px;font-weight:600;cursor:text;white-space:nowrap">점프 로버</button>')
    # 행성 전환기: 라디오 그룹(하나로 센다)
    labels = ''
    for i, p in enumerate(PLANETS):
        on = i == planet
        busy = on and planet_busy
        st = (f'position:relative;display:inline-flex;align-items:center;gap:6px;height:24px;padding:0 14px;border-radius:999px;font-size:12px;font-weight:500;cursor:pointer;'
              f'background:{SEL if on else "transparent"};color:{T1 if on else T2};box-shadow:{"inset 0 0 0 1px " + ACC if on else "none"}')
        labels += (f'<label style="{st}"><input type="radio" name="planet-{x.bid}" value="{i}"{" checked" if on else ""} '
                   f'style="position:absolute;opacity:0;width:1px;height:1px;margin:0">{I_SPIN if busy else ""}{p}</label>')
    planet_g = (f'<div role="radiogroup" aria-label="행성"{BUSY if planet_busy else ""}{x.c("행성 전환기")} style="display:inline-flex;padding:2px;gap:2px;'
                f'border:1px solid {B_STR};border-radius:999px;background:{FIELD}">{labels}</div>')
    # 모드 전환기: 탭 목록(하나로 센다)
    tabs = ''
    for i, m in enumerate(MODES):
        on = i == mode
        ring = f';outline:2px solid {FOCUS};outline-offset:2px' if (on and tab_focus) else ''
        tabs += (f'<button type="button" role="tab" aria-selected="{str(on).lower()}" tabindex="{0 if on else -1}" style="height:28px;padding:0 14px;border:0;'
                 f'border-radius:4px 4px 0 0;font-size:12px;font-weight:500;cursor:pointer;background:{SEL if on else "transparent"};color:{T1 if on else T2};'
                 f'box-shadow:{"inset 0 -2px 0 " + ACC if on else "none"}{ring}">{m}</button>')
    mode_g = f'<div role="tablist" aria-label="모드"{x.c("모드 전환기")} style="display:inline-flex;gap:2px">{tabs}</div>'

    badge_html = badge
    if open_ == 'evidence':
        badge_html = f'<span style="position:relative;display:inline-flex">{badge}{evidence_popover(x)}</span>'
    left = [name, planet_g, mode_g, badge_html]
    if offline:
        left.append(f'<span role="status" style="display:inline-flex;align-items:center;gap:6px;height:28px;box-sizing:border-box;padding:0 12px;border:1px solid {WARN};'
                    f'border-radius:999px;font-size:12px;font-weight:500;color:{WARN};white-space:nowrap">{I_WARN}엔진 연결 끊김</span>')
        left.append(btn_secondary(x, '다시 연결'))

    share = (f'<button type="button" aria-haspopup="dialog"{EXP_T if open_ == "share" else ""}{x.c("공유")} style="height:28px;padding:0 12px;'
             f'border:1px solid {B_STR};border-radius:4px;background:{HOVER if open_ == "share" else "transparent"};color:{T1};font-size:12px;font-weight:500;cursor:pointer">공유</button>')
    if open_ == 'share':
        share = f'<span style="position:relative;display:inline-flex">{share}{share_popover(x)}</span>'
    more = btn_icon(x, '더보기', I_MORE, name='⋯ 더보기',
                    extra=' aria-haspopup="menu"' + (' aria-expanded="true"' if open_ == 'more' else ''),
                    bg=HOVER if open_ == 'more' else 'transparent')
    if open_ == 'more':
        more = f'<span style="position:relative;display:inline-flex">{more}{more_menu(x)}</span>'
    return (f'<header style="grid-column:1/-1;position:relative;z-index:5;display:flex;align-items:center;gap:12px;padding:0 12px;background:{PANEL};'
            f'border-bottom:1px solid {B_SUB}">{"".join(left)}<span style="flex:1 1 0"></span>{primary}{share}{more}</header>')


def evidence_popover(x):
    c2 = EV['l2'][0]
    return (f'<div role="dialog" aria-label="증거 근거"{x.r("증거 근거 팝오버")} style="position:absolute;top:36px;left:0;z-index:6;width:340px;box-sizing:border-box;background:{RAISED};'
            f'border-radius:8px;box-shadow:{SHADOW};padding:12px;display:flex;flex-direction:column;gap:8px;font-size:12px;line-height:16px;white-space:normal">'
            f'<div style="display:flex;align-items:center;gap:8px;color:{c2};font-weight:600">{bars(3)}<span style="font-family:{MONO}">L2</span>판정 · 탐색 + 몬테카를로</div>'
            f'<div><span style="color:{T2}">화면 문구</span> <span style="font-family:{MONO}">FEASIBLE_FOUND</span> · 이 모델에서는 성공 사례를 찾았습니다.</div>'
            f'<div><span style="color:{T2}">근거</span> 탐색과 몬테카를로 <span style="font-family:{MONO}">n = 500</span> 표본. 확률과 가정은 판정 카드에 있습니다.</div>'
            f'<div style="border-top:1px solid {B_SUB};padding-top:8px">{l3_line()}<div style="color:{T2};margin-top:2px">실측 현재 0건. 숨기지 않습니다.</div></div>'
            f'<div style="color:{T3}">{kbd("Esc")} 닫기</div></div>')


def share_popover(x):
    return (f'<div role="dialog" aria-label="공유"{x.r("공유 팝오버")} style="position:absolute;top:36px;right:0;z-index:6;width:300px;box-sizing:border-box;background:{RAISED};'
            f'border-radius:8px;box-shadow:{SHADOW};padding:12px;display:flex;flex-direction:column;gap:10px;font-size:12px;line-height:16px">'
            f'<div style="font-size:13px;font-weight:600">공유</div>'
            f'<div style="color:{T2}">보기 전용 링크를 만듭니다. 링크에도 지금의 증거 단계가 그대로 붙습니다. 세부는 D1에서 정합니다.</div>'
            f'<div style="display:flex;gap:8px;align-items:center">{btn_secondary(x, "링크 만들기", rev=True)}'
            f'{btn_secondary(x, "복사", rev=True, disabled=True)}<span style="color:{T3}">링크를 만든 뒤 복사</span></div>'
            f'<div style="color:{T3}">{kbd("Esc")} 닫기</div></div>')


def more_menu(x):
    items = [('되돌리기', 'Ctrl Z'), ('다시 실행', 'Ctrl Shift Z'), ('변경 이력', ''), ('단축키 보기', '?')]
    rows = ''.join(
        f'<button type="button" role="menuitem"{x.r("⋯ 메뉴 · " + t)} style="display:flex;align-items:center;justify-content:space-between;gap:16px;width:100%;height:28px;'
        f'padding:0 8px;border:0;border-radius:4px;background:{HOVER if i == 0 else "transparent"};color:{T1};font-size:12px;font-weight:500;cursor:pointer">'
        f'<span>{t}</span>{kbd(k) if k else ""}</button>' for i, (t, k) in enumerate(items))
    return (f'<div role="menu" aria-label="더보기"{x.r("⋯ 메뉴")} style="position:absolute;top:36px;right:0;z-index:6;width:220px;box-sizing:border-box;background:{RAISED};'
            f'border-radius:8px;box-shadow:{SHADOW};padding:4px;display:flex;flex-direction:column;gap:2px">{rows}</div>')


# ---------------------------------------------------------------- 라이브러리 (왼쪽 패널)
PARTS = [  # 이름, 사양 라벨, 값, 단위, 배지, 예시 여부. 8.9 N만 design-system.md 10절의 값이다
    ('차체', '길이', '4', 'm', 'cite', True),
    ('바퀴', '지름', '0.6', 'm', 'cite', True),
    ('냉가스 추력기', '최대 추력', '8.9', 'N', 'cite', False),
    ('빔', '길이', '2', 'm', 'cite', True),
    ('모터', '정격 토크', '120', 'N·m', 'cite', True),
    ('점프대', '높이', '0.5', 'm', 'cite', True),
]


def lib_tabs(x, tab):
    out = ''
    for key, label in (('base', '기본 부품'), ('mine', '내 것')):
        on = key == tab
        out += (f'<button type="button" role="tab" aria-selected="{str(on).lower()}" tabindex="{0 if on else -1}" style="height:28px;padding:0 12px;border:0;'
                f'border-radius:4px 4px 0 0;font-size:12px;font-weight:500;cursor:pointer;background:{SEL if on else "transparent"};color:{T1 if on else T2};'
                f'box-shadow:{"inset 0 -2px 0 " + ACC if on else "none"}">{label}</button>')
    return f'<div role="tablist" aria-label="라이브러리"{x.c("라이브러리 탭")} style="display:inline-flex;gap:2px">{out}</div>'


def left_panel(x, collapsed=False, tab='base', selected=None, search=None, tip=False, focus=False):
    if collapsed:
        ring = f'outline:2px solid {FOCUS};outline-offset:2px;' if focus else ''
        t = tooltip(f'라이브러리 펼치기 {kbd("[")}', 'left:44px;top:6px') if tip else ''
        b = btn_icon(x, '라이브러리 펼치기', I_LIB, name='라이브러리 펼치기(레일)', extra=' aria-expanded="false"', style=ring)
        return (f'<aside data-rail="1" aria-label="라이브러리" style="grid-column:1;position:relative;z-index:4;background:{PANEL};border-right:1px solid {B_SUB};'
                f'display:flex;flex-direction:column;align-items:center;padding:6px 0">{b}{t}</aside>')
    head = (f'<div style="display:flex;align-items:center;justify-content:space-between;height:40px;flex:none;padding:0 8px 0 16px;border-bottom:1px solid {B_SUB}">'
            f'<h2 style="margin:0;font-size:16px;line-height:24px;font-weight:600">라이브러리</h2>'
            f'{btn_icon(x, "라이브러리 접기", I_LEFT, extra=EXP_T)}</div>')
    tabs = f'<div style="padding:8px 8px 0;border-bottom:1px solid {B_SUB};flex:none">{lib_tabs(x, tab)}</div>'
    if tab == 'mine':
        body = (f'<div style="padding:24px 16px;display:flex;flex-direction:column;gap:8px;align-items:flex-start">'
                f'<div style="font-size:16px;line-height:24px;font-weight:600">가져온 부품이 없습니다</div>'
                f'<div style="color:{T2};font-size:12px;line-height:16px">glb 파일을 가져오면 여기에 모입니다.</div>'
                f'<div style="margin-top:4px">{btn_secondary(x, "가져오기", name="가져오기(내 것 탭)")}</div></div>')
        return (f'<aside aria-label="라이브러리" style="grid-column:1;min-height:0;background:{PANEL};border-right:1px solid {B_SUB};display:flex;flex-direction:column">'
                f'{head}{tabs}{body}</aside>')
    parts = PARTS if not search else [p for p in PARTS if search in p[0] or search in p[1]]
    sfield = ''
    if search is not None:
        sid = x.uid('q')
        sfield = (f'<div style="padding:8px 8px 0;flex:none"><div style="display:flex;align-items:center;gap:6px;height:28px;box-sizing:border-box;padding:0 8px;'
                  f'border:1px solid {ACC};border-radius:4px;background:{FIELD};color:{T2}">{I_SEARCH}'
                  f'<input id="{sid}" aria-label="부품 검색" value="{e(search)}"{x.r("부품 검색 필드")} style="flex:1 1 0;min-width:0;height:24px;padding:0;border:0;'
                  f'background:transparent;color:{T1};font-size:13px;outline:0">{kbd("Esc")}</div></div>')
    opts = ''
    sel_id = ''
    for nm, lab, val, unit, kind, ex in parts:
        on = nm == selected
        oid = x.uid('opt')
        if on:
            sel_id = oid
        bg = f'background:{SEL};box-shadow:inset 0 0 0 1px {ACC};' if on else ''
        opts += (f'<div role="option" id="{oid}" aria-selected="{str(on).lower()}" style="display:flex;flex-direction:column;gap:2px;padding:6px 8px;border-radius:4px;{bg}">'
                 f'<span style="font-size:13px;line-height:20px;font-weight:500">{nm}</span>'
                 f'<span style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:11px;line-height:16px;color:{T2}">{lab}'
                 f'<span style="font-family:{MONO};font-size:12px;font-weight:500;color:{T1}">{val} <span style="color:{T2}">{unit}</span></span>'
                 f'{vbadge(x, kind, "인용", as_button=False)}{EX if ex else ""}</span></div>')
    if not parts:
        opts = f'<div style="padding:8px;color:{T2}">찾는 부품이 없습니다.</div>'
    ad = f' aria-activedescendant="{sel_id}"' if sel_id else ''
    lst = (f'<div role="listbox" tabindex="0" aria-label="기본 부품 목록"{ad}{x.c("부품 목록")} style="flex:1 1 0;min-height:0;overflow:auto;padding:8px;'
           f'display:flex;flex-direction:column;gap:2px">{opts}</div>')
    foot = (f'<div style="flex:none;display:flex;align-items:center;gap:6px;height:32px;padding:0 16px;border-top:1px solid {B_SUB};'
            f'font-size:11px;line-height:16px;color:{T3}">{kbd("/")} 또는 목록을 누르면 부품 검색</div>') if search is None else ''
    return (f'<aside aria-label="라이브러리" style="grid-column:1;min-height:0;background:{PANEL};border-right:1px solid {B_SUB};display:flex;flex-direction:column">'
            f'{head}{tabs}{sfield}{lst}{foot}</aside>')


# ---------------------------------------------------------------- 오른쪽 패널 (인스펙터 · 판정)
def rail_right(x, tip=False, label='인스펙터 펼치기'):
    t = tooltip(f'{label} {kbd("]")}', 'right:44px;top:6px') if tip else ''
    b = btn_icon(x, label, I_INSP, name='인스펙터 펼치기(레일)', extra=' aria-expanded="false"')
    return (f'<aside data-rail="1" aria-label="인스펙터" style="grid-column:3;position:relative;z-index:4;background:{PANEL};border-left:1px solid {B_SUB};'
            f'display:flex;flex-direction:column;align-items:center;padding:6px 0">{b}{t}</aside>')


def panel_right(x, title, body, foot='', aria=None):
    head = (f'<div style="display:flex;align-items:center;justify-content:space-between;height:40px;flex:none;padding:0 8px 0 16px;border-bottom:1px solid {B_SUB}">'
            f'<h2 style="margin:0;font-size:16px;line-height:24px;font-weight:600">{title}</h2>'
            f'{btn_icon(x, title + " 접기", I_RIGHT, name="오른쪽 패널 접기", extra=EXP_T)}</div>')
    f = f'<div style="flex:none;padding:8px 16px 12px;font-size:11px;line-height:16px;color:{T3}">{foot}</div>' if foot else ''
    return (f'<aside aria-label="{aria or title}" style="grid-column:3;min-height:0;background:{PANEL};border-left:1px solid {B_SUB};display:flex;flex-direction:column">'
            f'{head}<div style="flex:1 1 0;min-height:0;overflow:auto;padding:12px 8px;display:flex;flex-direction:column;gap:4px">{body}</div>{f}</aside>')


def sec_label(t):
    return f'<div style="padding:0 8px;font-size:12px;line-height:16px;font-weight:500;color:{T2}">{t}</div>'


def divider():
    return f'<div style="height:1px;background:{B_SUB};margin:8px 0"></div>'


def field_row(label, value, unit, badge, ex=False, mono_label=False):
    lab = (f'<span style="font-family:{MONO};font-size:12px;font-weight:500;color:{T2}">{label}</span>' if mono_label
           else f'<span style="font-size:12px;font-weight:500;color:{T2}">{label}</span>')
    cols = ('76px minmax(0,1fr) 24px auto auto' if ex else '84px minmax(0,1fr) 24px auto')
    return (f'<div style="display:grid;grid-template-columns:{cols};gap:{6 if ex else 8}px;align-items:center;min-height:28px;padding:0 8px;border-radius:4px">'
            f'{lab}<span style="font-family:{MONO};font-size:13px;font-weight:500;text-align:right">{value}</span>'
            f'<span style="font-size:11px;font-weight:500;color:{T2}">{unit}</span>{badge}{EX if ex else ""}</div>')


def selected_line(name):
    return (f'<div style="padding:0 8px 8px;display:flex;align-items:baseline;gap:8px"><span style="font-size:12px;color:{T2}">선택</span>'
            f'<span style="font-size:13px;line-height:20px;font-weight:600">{name}</span></div>')


def inspector(x, variant='basic'):
    body = selected_line('차체') + sec_label('요약')
    body += field_row('차체 질량', '1.3', 't', vbadge(x, 'declared', '사용자 선언'))
    if variant == 'run':
        body += divider() + sec_label('이번 실행 · 읽기 전용')
        body += field_row('최고 속도', '12.4', 'm/s', vbadge(x, 'sim', '시뮬'), ex=True)
    if variant == 'offline':
        body += field_row('무게중심 높이', '0.62', 'm', vbadge(x, 'stale', '시뮬 · 오래됨'), ex=True)
        body += (f'<div style="padding:0 8px 0 90px;display:flex;gap:6px;align-items:center;font-size:11px;line-height:16px;font-weight:500;color:{T2}">'
                 f'오래됨 · 마지막 계산 <span style="font-family:{MONO}">19:42</span>{EX}</div>')
    return panel_right(x, '인스펙터', body, foot='자리 표시 · 필드 상세는 SC-02')


def verdict_empty(x):
    body = (f'<div style="padding:40px 8px 16px;display:flex;flex-direction:column;gap:8px">'
            f'<div style="font-size:20px;line-height:28px;font-weight:600">판정 없음</div>'
            f'<div style="color:{T2}">판정을 실행하면 이 자리에 판정 카드가 나타납니다.</div>'
            f'<div style="color:{T2}">다음 행동: 오른쪽 위의 <span style="color:{T1};font-weight:600">판정 실행</span>을 누릅니다.</div></div>')
    return panel_right(x, '판정', body, foot='자리 표시 · 판정 카드 상세는 SC-04')


def verdict_card(x):
    c2 = EV['l2'][0]
    lid = x.uid('lnk')
    card = (f'<article aria-label="판정 카드 요약" style="background:{CARD};border:1px solid {B_DEF};border-left:3px solid {c2};border-radius:6px;padding:12px;'
            f'display:flex;flex-direction:column;gap:12px">'
            f'{ev_chip("l2", "L2 판정 · 탐색 + 몬테카를로")}'
            f'<div><div style="display:flex;align-items:center;gap:8px;font-family:{MONO};font-weight:500">{DOT}FEASIBLE_FOUND</div>'
            f'<div>이 모델에서는 성공 사례를 찾았습니다.</div></div>'
            f'<div style="display:flex;flex-direction:column;gap:6px"><div style="font-size:11px;line-height:16px;font-weight:500;color:{T2}">확률 · '
            f'<span style="font-family:{MONO}">p_success</span></div>'
            f'<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap"><span style="font-size:28px;line-height:36px;font-weight:600">15.2%</span>'
            f'<span style="font-family:{MONO};font-weight:500">[12.3, 18.6]</span>{vbadge(x, "sim", "시뮬")}</div>'
            f'<div role="img" aria-label="신뢰구간 막대: 12.3%에서 18.6%, 점 추정 15.2%. 눈금 0%에서 25%" style="position:relative;height:16px">'
            f'<div style="position:absolute;left:0;right:0;top:4px;height:8px;box-sizing:border-box;background:{FIELD};border:1px solid {B_STR};border-radius:2px"></div>'
            f'<div style="position:absolute;left:49.2%;width:25.2%;top:4px;height:8px;background:{c2}"></div>'
            f'<div style="position:absolute;left:60.8%;top:0;width:2px;height:16px;background:{T1}"></div></div>'
            f'<div style="display:flex;justify-content:space-between;font-family:{MONO};font-size:11px;line-height:16px;color:{T2}"><span>0%</span>'
            f'<span>95% CI · n = 500 표본</span><span>25%</span></div></div>'
            f'<div style="display:flex;flex-direction:column;gap:4px;border-top:1px solid {B_SUB};padding-top:10px">'
            f'<div style="font-size:11px;line-height:16px;font-weight:500;color:{T2}">민감도 1위 · 판정을 뒤집는 가정</div>'
            f'<div style="font-size:13px;font-weight:600">노즐별 추력 잡음</div></div>'
            f'<a id="{lid}" href="#" aria-haspopup="dialog"{x.c("가정표 · 이 모델이 보지 않는 것 열기")} style="align-self:flex-start;display:inline-flex;align-items:center;gap:4px;'
            f'min-height:24px;color:{ACC};font-size:12px;font-weight:500;text-decoration:underline">가정표 · 이 모델이 보지 않는 것 열기</a>'
            f'</article>')
    return panel_right(x, '판정', card, foot='자리 표시 · 판정 카드 상세(가정표, 민감도 순위, 시드)는 SC-04')


# ---------------------------------------------------------------- 뷰포트 · 에이전트 바 · 타임라인
def viewport(extra='', halo=False):
    if halo:
        c1 = EV['l1'][0]
        inner = (f'<div style="position:absolute;left:50%;top:44%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:12px">'
                 f'<div style="position:relative;width:640px;height:360px;max-width:100%;box-sizing:border-box;border:1px dashed {B_STR};border-radius:6px">'
                 f'<div style="position:absolute;left:0;right:0;top:62%;height:1px;background:{B_DEF}"></div>'
                 f'<div style="position:absolute;left:0;right:0;top:calc(62% + 10px);text-align:center;font-size:11px;line-height:16px;font-weight:500;color:{T3}">'
                 f'Halo 미리보기 자리 · 카메라·자막 편집은 SC-08</div></div>'
                 f'<div style="display:inline-flex;align-items:center;gap:8px;color:{c1};font-size:13px;line-height:20px;font-weight:600">{bars(2)}판정 없음: 1회 실행</div></div>')
    else:
        inner = (f'<div style="position:absolute;left:0;right:0;top:62%;height:1px;background:{B_DEF}"></div>'
                 f'<div style="position:absolute;left:0;right:0;top:calc(62% + 12px);text-align:center;font-size:11px;line-height:16px;font-weight:500;color:{T3}">'
                 f'3D 뷰포트 · 코드 프로토타입으로 검증</div>')
    return (f'<main aria-label="3D 뷰포트" tabindex="0" data-vp="1" style="grid-column:2;position:relative;min-width:0;min-height:0;overflow:hidden;background:{APP}">'
            f'{inner}{extra}</main>')


def agent_bar(x, chip=None):
    ch = (f'<span style="flex:none;display:inline-flex;align-items:center;height:20px;box-sizing:border-box;padding:0 8px;border:1px solid {B_DEF};'
          f'border-radius:999px;background:{RAISED};font-size:11px;font-weight:500;color:{T2}">선택: {chip}</span>') if chip else ''
    iid = x.uid('ask')
    mic = (f'<button type="button" aria-label="음성 입력 시작"{x.c("마이크")} style="flex:none;width:32px;height:32px;padding:0;border:1px solid {B_STR};'
           f'border-radius:999px;background:transparent;color:{T1};display:inline-flex;align-items:center;justify-content:center;cursor:pointer">{I_MIC}</button>')
    field = (f'<div style="flex:1 1 0;min-width:0;display:flex;align-items:center;gap:8px;height:32px;box-sizing:border-box;padding:0 8px;border:1px solid {B_STR};'
             f'border-radius:4px;background:{FIELD}">{ch}<input id="{iid}" aria-label="에이전트에게 요청하기" placeholder="에이전트에게 요청하기"{x.c("에이전트 입력창")} '
             f'style="flex:1 1 0;min-width:0;height:24px;padding:0;border:0;background:transparent;color:{T1};font-size:13px">'
             f'<span style="flex:none;font-size:11px;line-height:16px;color:{T3}">{kbd("Enter")} 보내기</span></div>')
    return (f'<section aria-label="에이전트 바" style="grid-column:1/-1;display:flex;align-items:center;gap:8px;padding:0 12px;background:{PANEL};'
            f'border-top:1px solid {B_SUB}">{mic}{field}</section>')


def tl_toggle(x, expanded):
    lab = '타임라인 접기' if expanded else '타임라인 펼치기'
    return (f'<button type="button" aria-expanded="{str(expanded).lower()}" aria-label="{lab}"{x.c(lab)} style="flex:none;height:24px;padding:0 8px;'
            f'border:1px solid transparent;border-radius:4px;background:transparent;color:{T1};font-size:12px;font-weight:500;display:inline-flex;'
            f'align-items:center;gap:6px;cursor:pointer">{I_DOWN if expanded else I_UP}타임라인</button>')


def track(color=None, marker=False, note=''):
    ticks = ''.join(f'<span style="position:absolute;left:{i/6*100:.4g}%;top:12px;transform:translateX(-50%);white-space:nowrap;font-family:{MONO};font-size:11px;line-height:16px;'
                    f'color:{T3}">{i} s</span><span style="position:absolute;left:{i/6*100:.4g}%;top:-4px;width:1px;height:8px;background:{B_DEF}"></span>'
                    for i in range(7))
    return ticks


def timeline(x, kind):
    """kind: assemble(접힘) | run | verdict-none | verdict | halo"""
    if kind == 'assemble':
        return (f'<section data-tl="short" aria-label="타임라인" style="grid-column:1/-1;display:flex;align-items:center;gap:12px;padding:0 12px 0 8px;background:{PANEL};'
                f'border-top:1px solid {B_SUB}">{tl_toggle(x, False)}<span style="flex:1 1 0;text-align:center;font-size:12px;line-height:16px;color:{T3}">'
                f'조립 중에는 물리가 꺼져 있습니다</span>{l3_line()}</section>')
    chip, right, body = '', '', ''
    if kind == 'run':
        chip = ev_chip('l1', '<span style="font-family:' + MONO + '">L1</span> · 1회 실행 · 판정 아님')
        right = btn_secondary(x, '판정 카드 열기')
    elif kind == 'verdict':
        chip = ev_chip('l2', '<span style="font-family:' + MONO + '">L2</span> · 판정 표본 중 하나')
    elif kind == 'halo':
        chip = ev_chip('l1', '<span style="font-family:' + MONO + '">L1</span> · 1회 실행 · 판정 아님')
    head = (f'<div style="display:flex;align-items:center;gap:12px;height:32px;flex:none;padding:0 12px 0 8px">{tl_toggle(x, True)}{chip}'
            f'<span style="flex:1 1 0"></span>{right}{l3_line()}</div>')
    if kind == 'verdict-none':
        body = (f'<div style="flex:1 1 0;display:flex;align-items:center;justify-content:center;font-size:12px;line-height:16px;color:{T3}">'
                f'판정을 실행하면 표본 실행을 여기서 다시 볼 수 있습니다.</div>')
    else:
        col = EV['l2' if kind == 'verdict' else 'l1'][0]
        transport = (btn_icon(x, '재생', I_PLAY12) + btn_icon(x, '일시정지', I_PAUSE) + btn_icon(x, '되감기', I_REWIND))
        mk = ''
        if kind == 'run':
            mk = (f'<div style="position:absolute;left:40%;top:-13px;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:0;color:{col}">'
                  f'<button type="button" aria-label="실패: 전복, 2.4 s. 원인 보기"{x.c("실패 표식 ▲ 전복")} style="width:24px;height:24px;padding:0;border:0;'
                  f'border-radius:2px;background:{PANEL};color:{col};display:inline-flex;align-items:center;justify-content:center;cursor:pointer">{TRI}</button>'
                  f'<span style="display:inline-flex;gap:4px;align-items:center;margin-top:18px;font-size:11px;line-height:16px;font-weight:500;'
                  f'background:{PANEL};padding:0 4px">전복 {EX}</span></div>')
        scale_ex = f'<span style="position:absolute;right:0;top:-26px">{EX}</span>'
        body = (f'<div style="flex:1 1 0;display:flex;align-items:flex-start;gap:16px;padding:14px 32px 0 12px">'
                f'<div style="display:flex;gap:4px;flex:none">{transport}</div>'
                f'<div style="position:relative;flex:1 1 0;margin-top:13px;border-top:2px solid {B_DEF}">{track()}{mk}{scale_ex}</div></div>')
    return (f'<section aria-label="타임라인" style="grid-column:1/-1;display:flex;flex-direction:column;background:{PANEL};border-top:1px solid {B_SUB}">'
            f'{head}{body}</section>')


def banner_planet(x):
    n = EV['none'][0]
    return (f'<div role="status" style="grid-column:1/-1;display:flex;align-items:center;gap:10px;padding:0 8px 0 16px;background:{CARD};border-bottom:1px solid {B_SUB};'
            f'font-size:12px;line-height:16px"><span style="color:{n};display:inline-flex">{bars(0)}</span>'
            f'<span>달로 바꿨습니다. 이전 판정은 무효입니다. 다시 판정해야 합니다</span>'
            f'<span style="color:{T3}">· 달의 물리로 다시 컴파일하는 중</span><span style="flex:1 1 0"></span>'
            f'{btn_icon(x, "안내 닫기", I_CLOSE, size=24)}</div>')


# ---------------------------------------------------------------- 셸 조립
def shell(x, *, mode=0, planet=0, badge, primary, left, right, tl, agent_chip=None, offline=False, planet_busy=False,
          open_=None, banner=False, vp_extra='', halo=False, overlay='', tab_focus=False, sr=''):
    lw = RAIL if left.startswith('<aside data-rail') else LEFT
    rw = RAIL if right.startswith('<aside data-rail') else RIGHT
    tlh = TL_S if tl.startswith('<section data-tl="short"') else TL_L
    rows = f'{TOP}px ' + (f'{BANNER}px ' if banner else '') + f'minmax(0,1fr) {AGENT}px {tlh}px'
    parts = [topbar(x, mode, planet, badge, primary, offline=offline, planet_busy=planet_busy, open_=open_, tab_focus=tab_focus)]
    if banner:
        parts.append(banner_planet(x))
    parts += [left, viewport(vp_extra, halo), right, agent_bar(x, agent_chip), tl]
    srh = f'<span role="status" aria-live="polite" style="{SR}">{sr}</span>' if sr else ''
    return (f'<div data-frame="{x.bid}" style="position:relative;width:{W}px;height:{H}px;flex:none;box-sizing:border-box;overflow:hidden;display:grid;'
            f'grid-template-columns:{lw}px minmax(0,1fr) {rw}px;grid-template-rows:{rows};background:{APP};color:{T1};font-family:{UI};font-size:13px;'
            f'line-height:20px;font-variant-numeric:tabular-nums">{"".join(parts)}{srh}{overlay}</div>')


def badge_l0(x):
    return ev_pill('l0', [(True, 'L0'), (False, '조립')], x, aria='증거 단계 L0 조립')


def run_icon():
    return I_PLAY


# ---------------------------------------------------------------- 아트보드 S1~S10
def s1(x, **kw):
    return shell(x, badge=badge_l0(x), primary=btn_primary(x, '실행하기'), left=left_panel(x), right=rail_right(x),
                 tl=timeline(x, 'assemble'), **kw)


def s2(x):
    return shell(x, badge=badge_l0(x), primary=btn_primary(x, '실행하기'), left=left_panel(x, selected='차체'),
                 right=inspector(x), tl=timeline(x, 'assemble'), agent_chip='차체', open_='more')


def s3(x):
    badge = ev_pill('l1', [(True, 'L1'), (False, '미리보기 · 1회 실행. 판정이 아닙니다')], x, aria='증거 단계 L1 미리보기. 1회 실행. 판정이 아닙니다')
    return shell(x, mode=1, badge=badge, primary=btn_primary(x, '1회 실행', icon=run_icon()), left=left_panel(x, selected='차체'),
                 right=inspector(x, 'run'), tl=timeline(x, 'run'), agent_chip='차체', sr='L1 미리보기. 1회 실행. 판정이 아닙니다')


def s4(x):
    badge = ev_pill('none', [(False, '판정 없음')], x, aria='증거 단계: 판정 없음')
    return shell(x, mode=2, badge=badge, primary=btn_primary(x, '판정 실행'), left=left_panel(x, search='추력'),
                 right=verdict_empty(x), tl=timeline(x, 'verdict-none'))


def s5(x):
    badge = ev_pill('l2', [(True, 'L2'), (False, '판정'), (True, 'FEASIBLE_FOUND')], x, aria='증거 단계 L2 판정 FEASIBLE_FOUND', expanded=True)
    return shell(x, mode=2, badge=badge, primary=btn_primary(x, '판정 실행'), left=left_panel(x),
                 right=verdict_card(x), tl=timeline(x, 'verdict'), open_='evidence', sr='L2 판정. FEASIBLE_FOUND')


def s6(x):
    badge = ev_pill('l1', [(True, 'L1'), (False, '판정 없음: 1회 실행')], x, aria='증거 단계 L1. 판정 없음: 1회 실행')
    return shell(x, mode=3, badge=badge, primary=btn_primary(x, '내보내기'), left=left_panel(x, tab='mine'),
                 right=rail_right(x), tl=timeline(x, 'halo'), open_='share', halo=True)


def s7a(x):
    return shell(x, badge=badge_l0(x), primary=btn_primary(x, '실행하기'), left=left_panel(x, collapsed=True, tip=True, focus=True),
                 right=rail_right(x), tl=timeline(x, 'assemble'))


def s7b(x):
    return shell(x, badge=badge_l0(x), primary=btn_primary(x, '실행하기'), left=left_panel(x, collapsed=True),
                 right=inspector(x), tl=timeline(x, 'assemble'), agent_chip='차체')


def s7c(x):
    return shell(x, badge=badge_l0(x), primary=btn_primary(x, '실행하기'), left=left_panel(x, collapsed=True),
                 right=rail_right(x, tip=True), tl=timeline(x, 'assemble'), agent_chip='차체')


def s8(x):
    badge = ev_pill('none', [(False, '무효: 다시 판정해야 합니다')], x, aria='증거: 무효. 다시 판정해야 합니다')
    return shell(x, planet=2, planet_busy=True, badge=badge, primary=btn_primary(x, '실행하기'), left=left_panel(x),
                 right=rail_right(x), tl=timeline(x, 'assemble'), banner=True,
                 sr='달로 바꿨습니다. 이전 판정은 무효입니다. 다시 판정해야 합니다')


def s9(x):
    tid = x.uid('why')
    prim = btn_primary(x, '실행하기', disabled=True, describedby=tid)
    prim = f'<span style="position:relative;display:inline-flex">{prim}{tooltip("엔진에 연결되어야 실행할 수 있습니다", "top:2px;right:calc(100% + 8px)", tid)}</span>'
    return shell(x, badge=badge_l0(x), primary=prim, left=left_panel(x, selected='차체'), right=inspector(x, 'offline'),
                 tl=timeline(x, 'assemble'), agent_chip='차체', offline=True)


def s10(x):
    def num(n, left, top):
        return (f'<span style="position:absolute;left:{left}px;top:{top}px;width:20px;height:20px;border-radius:999px;background:{ACC};color:{ACC_ON};'
                f'font-size:11px;line-height:20px;font-weight:600;text-align:center">{n}</span>')

    def zone(l, t, w, h):
        return f'<span style="position:absolute;left:{l}px;top:{t}px;width:{w}px;height:{h}px;box-sizing:border-box;border:1px dashed {FOCUS};border-radius:4px"></span>'
    vh = H - TOP - AGENT - TL_S  # 뷰포트 높이 764
    card_h = round(vh * 0.4)
    card_top = TOP + vh - card_h - 8
    li = lambda t: f'<li style="margin:0 0 4px">{t}</li>'
    legend = (f'<div style="position:absolute;left:836px;top:64px;width:540px;box-sizing:border-box;background:{RAISED};border-radius:8px;box-shadow:{SHADOW};'
              f'padding:16px;font-size:12px;line-height:18px;color:{T1}">'
              f'<div style="font-size:11px;line-height:16px;font-weight:500;color:{T2}">S10 · 설명용 주석. 앱 화면이 아닙니다</div>'
              f'<div style="font-size:16px;line-height:24px;font-weight:600;margin:2px 0 8px">탭 순서와 포커스</div>'
              f'<ol style="margin:0 0 10px;padding-left:20px">'
              + li('상단바: 프로젝트 이름 → 행성(라디오 그룹, ←→) → 모드(탭 목록, ←→) → 증거 배지 → 실행하기 → 공유 → ⋯')
              + li('라이브러리: 접기 → 탭(←→) → 부품 목록(↑↓, Enter로 선택). ' + kbd('/') + ' 검색')
              + li('3D 뷰포트: 포커스 정지점 하나. 안의 조작은 코드 프로토타입(4.7)')
              + li('인스펙터: 레일의 펼치기. 펼치면 패널 안 필드 순서')
              + li('에이전트 바: 마이크 → 입력창(' + kbd('Enter') + ' 보내기)')
              + li('타임라인: 펼치기·접기 → (펼침) 재생 · 일시정지 · 되감기 → 표식 → 판정 카드 열기')
              + '</ol>'
              f'<div style="display:flex;flex-direction:column;gap:4px;color:{T2}">'
              f'<div>포커스 링: 2 px <span style="font-family:{MONO}">color.focus.ring</span> + 2 px 간격. 예: 모드 전환기의 "조립" 탭</div>'
              f'<div>{kbd("Esc")} 팝오버·메뉴·변경안 카드를 닫고 포커스를 연 버튼으로 돌려 줍니다</div>'
              f'<div>{kbd("[")} 라이브러리, {kbd("]")} 인스펙터 접기·펼치기 [제안] · {kbd("Ctrl Z")} 되돌리기 · {kbd("?")} 단축키 보기</div>'
              f'<div>증거 단계가 바뀌면 스크린리더가 읽습니다: "L1 미리보기. 1회 실행. 판정이 아닙니다"</div>'
              f'<div>누르는 영역 24 × 24 px 이상. 줄인 모션 설정이면 패널 접힘·펼침은 불투명도 전환만</div></div></div>')
    card = (f'<div style="position:absolute;left:{LEFT + 16}px;top:{card_top}px;width:560px;height:{card_h}px;box-sizing:border-box;border:1px dashed {B_STR};'
            f'border-radius:6px;display:flex;flex-direction:column;justify-content:flex-end;padding:12px;gap:2px;font-size:12px;line-height:16px;color:{T2}">'
            f'<span style="color:{T1};font-weight:600">변경안 카드 영역 · 내용은 SC-03</span>'
            f'<span>에이전트 바 위로 올라옵니다. 최대 높이 = 뷰포트 높이의 40% (<span style="font-family:{MONO}">{card_h} px</span> / {vh} px) [제안]</span>'
            f'<span>닫기: 수락 · 거절 · {kbd("Esc")}</span></div>')
    overlay = (f'<div data-annot="1" aria-hidden="true" style="position:absolute;inset:0;z-index:8;pointer-events:none">'
               + zone(2, 2, W - 4, TOP - 4) + zone(2, TOP + 2, LEFT - 4, vh - 4) + zone(LEFT + 2, TOP + 2, W - LEFT - RAIL - 4, vh - 4)
               + zone(W - RAIL + 2, TOP + 2, RAIL - 4, vh - 4) + zone(2, TOP + vh + 2, W - 4, AGENT - 4) + zone(2, H - TL_S + 2, W - 4, TL_S - 4)
               + num(1, 600, 14) + num(2, 176, 58) + num(3, LEFT + 10, 58) + num(4, W - RAIL + 10, 86) + num(5, 1290, TOP + vh + 18) + num(6, 150, H - TL_S + 6)
               + card + legend + '</div>')
    return s1(x, overlay=overlay, tab_focus=True)


BOARDS = [  # (파일, 제목, 함수, 너비, 높이)
    ('S1-Default', 'S1 기본: 조립 · 선택 없음 · 변경안 없음', s1),
    ('S2-Selected', 'S2 조립 · 부품 하나 선택', s2),
    ('S3-Run', 'S3 실행 · 1회 실행 뒤', s3),
    ('S4-VerdictNone', 'S4 판정 · 판정 없음', s4),
    ('S5-VerdictL2', 'S5 판정 · L2 FEASIBLE_FOUND', s5),
    ('S6-Halo', 'S6 Halo · 판정 없음', s6),
    ('S7-Collapsed', 'S7 패널 접힘 변형 (a) (b) (c)', None),
    ('S8-PlanetSwitch', 'S8 행성 전환 직후 (지구 → 달)', s8),
    ('S9-Offline', 'S9 엔진 오프라인', s9),
    ('S10-Keyboard', 'S10 키보드 주석 (S1 위에 겹침)', s10),
]
S7_FRAMES = [
    ('a', '(a) 왼쪽만 접힘 · 조립, 선택 없음 · 레일에 포커스와 툴팁', s7a),
    ('b', '(b) 오른쪽 열림 + 왼쪽 접힘 · 조립, 차체 선택', s7b),
    ('c', '(c) 모두 접힘 · 뷰포트 최대 · 차체 선택 유지, 상단바·에이전트 바·타임라인 한 줄은 남음', s7c),
]

HELMET = """<helmet>
<style>
body{margin:0}
button,input{font-family:inherit}
input::placeholder{color:#93A0AE;opacity:1}
:focus-visible{outline:2px solid #A8CBFF;outline-offset:2px}
label:has(input:focus-visible){outline:2px solid #A8CBFF;outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition-property:opacity!important;animation:none!important}}
</style>
</helmet>"""


def dc_file(title, root, w, h):
    return (f'<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<title>{e(title)}</title>\n<script src="./support.js"></script>\n</head>\n<body>\n'
            f'<x-dc>\n{HELMET}\n{root}\n</x-dc>\n'
            f'<script type="text/x-dc" data-dc-script data-props=\'{{"$preview":{{"width":{w},"height":{h}}}}}\'>\n'
            'class Component extends DCLogic {\nrenderVals() { return {}; }\n}\n</script>\n</body>\n</html>\n')


def frame_info(x, frag):
    dom = [_html.unescape(v) for v in re.findall(r'data-ctl="([^"]*)"', frag)]
    assert sorted(dom) == sorted(x.ctls), (x.bid, dom, x.ctls)
    rev = [_html.unescape(v) for v in re.findall(r'data-rev="([^"]*)"', frag)]
    return {'id': x.bid, 'ctls': dom, 'reveals': rev, 'primary': x.primary}


def build_boards():
    out = []
    for fname, title, fn in BOARDS:
        if fn is not None:
            x = Ctx(fname.split('-')[0].lower())
            root = fn(x)
            root = root.replace('<div data-frame=', f'<div data-board="{fname}.dc.html" data-frame=', 1)
            frames = [frame_info(x, root)]
            out.append((fname, title, root, W, H, frames))
            continue
        frames, html_frames = [], ''
        for key, sub, f in S7_FRAMES:
            x = Ctx(f's7{key}')
            fh = f(x)
            html_frames += (f'<div style="display:flex;flex-direction:column;gap:12px;flex:none"><div style="font-size:12px;line-height:16px;font-weight:500;color:{T2}">{sub}</div>'
                            f'{fh}</div>')
            frames.append(frame_info(x, fh))
        w7 = 48 * 2 + W * 3 + 48 * 2
        h7 = 48 + 16 + 12 + H + 48
        root = (f'<div data-board="{fname}.dc.html" style="width:{w7}px;height:{h7}px;box-sizing:border-box;padding:48px;background:{APP};color:{T1};font-family:{UI};'
                f'font-size:13px;line-height:20px;display:flex;gap:48px;align-items:flex-start">{html_frames}</div>')
        out.append((fname, title, root, w7, h7, frames))
    return out


# ---------------------------------------------------------------- 자기 점검 데이터 (갤러리와 NOTES가 같은 값을 쓴다)
S1_NAMES = ['프로젝트 이름', '행성 전환기', '모드 전환기', '증거 배지', '주 행동 · 실행하기', '공유', '⋯ 더보기', '라이브러리 접기', '라이브러리 탭',
            '부품 목록', '인스펙터 펼치기(레일)', '에이전트 입력창', '마이크', '타임라인 펼치기']

FEATURES = [  # 3.1절: 기능, 단계, 닿는 곳, 그려진 아트보드
    ('프로젝트 이름 보기·바꾸기', '0', '상단바 이름 버튼(제자리 편집)', 'S1~S10'),
    ('행성 전환(지구·화성·달)', '0', '상단바 라디오 그룹', 'S1~S10, 전환 중 S8'),
    ('모드 전환(조립·실행·판정·Halo)', '0', '상단바 탭 목록', 'S1~S10'),
    ('현재 증거 단계와 근거', '0 / 1', '배지 상시, 누르면 근거 팝오버', '배지 전부, 팝오버 S5'),
    ('주 행동(모드별 하나)', '0', '상단바 오른쪽 primary', 'S1~S10'),
    ('공유', '1', '공유 → 팝오버(링크 만들기·복사)', 'S6'),
    ('되돌리기·다시 실행·변경 이력·단축키 보기', '1', '⋯ 메뉴, 단축키 Ctrl Z 등', 'S2(메뉴), S10(단축키)'),
    ('라이브러리: 기본 부품, 내 것', '0', '왼쪽 패널 탭', 'S1, 내 것 S6'),
    ('라이브러리: 부품 검색', '1', '/ 또는 목록을 누르면 필드', 'S4(열림), 안내 줄 S1'),
    ('라이브러리: 가져오기(glb)', '1', '내 것 탭의 가져오기', 'S6'),
    ('인스펙터(SC-02)', '1', '부품 선택 시 자동, 아니면 레일', 'S2, S3, S9, S7(b)'),
    ('에이전트에게 텍스트로 요청', '0', '에이전트 입력창, Enter 보내기', 'S1~S10'),
    ('에이전트에게 음성으로 요청', '0', '마이크(인식문 확인 뒤 전송, SC-03)', 'S1~S10'),
    ('변경안 보기·수락·거절(SC-03)', '0 (생기면)', '에이전트 바 위 카드 영역', 'S10(영역과 40% 상한 주석)'),
    ('실행 재생·일시정지·되감기', '1', '타임라인 펼침(실행 모드 진입 시 자동)', 'S3, S5, S6'),
    ('실패·파단 표식 보기', '1 / 2', '타임라인 표식 → 원인 팝오버', 'S3(표식). 팝오버 모양은 DS Controls'),
    ('판정 카드 열기(SC-04)', '1', '판정 모드 자동 / 타임라인의 판정 카드 열기', 'S5(자동), S3(버튼)'),
    ('패널 접기·펼치기', '0', '패널 머리의 접기, 레일의 펼치기', 'S1~S10, S7'),
    ('엔진 다시 연결', '1', '엔진 연결 끊김 칩 옆 다시 연결', 'S9'),
    ('세 행성 나란히 비교', '—', 'SC-07 몫. 자리 없음', '—'),
    ('Halo 카메라·자막 편집', '—', 'SC-08 몫. Halo 틀만', 'S6(틀)'),
    ('생성 3D', '—', 'S2 기능. 셸에 없음', '—'),
]

REVEAL_MAP = [  # 3.2절 공개 지도
    ('인스펙터', '부품 선택 → 오른쪽 패널 펼침', 'S2 (S3, S9, S7b)'),
    ('타임라인', '실행·판정·Halo 진입 → 펼침, 조립은 32px 한 줄', 'S3, S4, S5, S6 / 접힘 S1'),
    ('변경안 카드', '에이전트 바 위로 올라옴, 최대 높이 40%', 'S10 (영역 주석. 카드 내부는 SC-03)'),
    ('판정 카드', '판정 모드 진입 또는 타임라인 판정 카드 열기', 'S5 / 버튼 S3'),
    ('증거 배지 근거', '배지를 누르면 팝오버', 'S5'),
    ('더보기·공유', '버튼 → 메뉴·팝오버', '⋯ S2, 공유 S6'),
    ('부품 검색', '/ 또는 목록 → 필드', 'S4'),
    ('가져오기', '내 것 탭', 'S6'),
    ('행성 전환 뒤 안내', '행성을 바꾸면 상단바 아래 한 줄', 'S8'),
]


# ---------------------------------------------------------------- 갤러리
def body_of(src):
    m = re.search(r'</helmet>(.*)</x-dc>', src, re.S)
    if not m:
        raise SystemExit('no <x-dc> body')
    return m.group(1).strip()


def table(head, rows):
    th = ''.join(f'<th scope="col">{h}</th>' for h in head)
    tr = ''.join('<tr>' + ''.join(f'<td>{c}</td>' for c in r) + '</tr>' for r in rows)
    return f'<div class="kin-tbl"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def selfcheck_html(check):
    rows = []
    for b in check['boards']:
        for f in b['frames']:
            delta = f['count'] - 14
            rows.append([f'<b>{f["label"]}</b>', f'<span class="mono">{f["count"]}</span>',
                         ('S1과 같음' if delta == 0 else f'S1 대비 {delta:+d}'), f'<span class="mono">{f["primary"]}</span>',
                         ', '.join(e(n) for n in f['ctls']), ', '.join(e(n) for n in f['reveals']) or '—'])
    t1 = table(['아트보드', '상시 조작 요소', '증가분', 'primary', '상시 조작 요소 이름', '공개로 열린 요소(수에 넣지 않음)'], rows)
    t2 = table(['기능(3.1)', '단계', '닿는 곳', '그려진 아트보드'], FEATURES)
    t3 = table(['숨긴 것(3.2)', '드러나는 방법', '그려진 아트보드'], REVEAL_MAP)
    return (f'<section class="kin-check" id="selfcheck" aria-label="자기 점검"><h2>자기 점검</h2>'
            f'<p>상시 조작 요소는 빌드할 때 이름을 붙여 세고, 헤드리스 Chrome에서 포커스할 수 있는 요소를 다시 세어 맞춰 봤습니다. '
            f'탭 목록·라디오 그룹·목록은 하나로 셉니다. 3D 뷰포트의 포커스 정지점은 3D 상호작용 범위(4.7)라 세지 않습니다.</p>'
            f'{t1}<h3>기능 도달 단계</h3>{t2}<h3>공개 지도</h3>{t3}</section>')


GALLERY_CSS = """
:root{color-scheme:dark}
html{background:#0F1216}
body{margin:0;background:#0F1216;color:#E8EDF2;font-family:Pretendard,'Pretendard Variable',-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo','Malgun Gothic','Noto Sans KR',sans-serif;font-size:13px;line-height:20px;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px))}
button,input{font-family:inherit}
input::placeholder{color:#93A0AE;opacity:1}
:focus-visible{outline:2px solid #A8CBFF;outline-offset:2px}
label:has(input:focus-visible){outline:2px solid #A8CBFF;outline-offset:2px}
@media (prefers-reduced-motion:reduce){*{transition-property:opacity!important;animation:none!important}}
a{color:#5B9DFF}a:hover{color:#A8CBFF}
.mono{font-family:'JetBrains Mono',ui-monospace,SFMono-Regular,Menlo,monospace}
.kin-top{padding-block:24px 8px;max-width:1840px;margin:0 auto}
.kin-top h1{margin:0 0 4px;font:600 20px/28px var(--f,inherit);text-wrap:balance}
.kin-top p{margin:0 0 12px;color:#A9B4C0;max-width:880px}
.kin-nav{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12px}
.kin-board{max-width:1840px;margin:0 auto;padding-block:24px 0}
.kin-board-title{margin:0 0 8px;font-size:12px;line-height:16px;font-weight:500;color:#A9B4C0}
.kin-board-scroll{overflow-x:auto;border:1px solid #26303A;border-radius:8px}
.kin-check{max-width:1840px;margin:0 auto;padding-block:32px 0}
.kin-check h2{margin:0 0 4px;font-size:20px;line-height:28px;font-weight:600}
.kin-check h3{margin:24px 0 8px;font-size:16px;line-height:24px;font-weight:600}
.kin-check p{margin:0 0 12px;color:#A9B4C0;max-width:880px}
.kin-tbl{overflow-x:auto;border:1px solid #26303A;border-radius:8px}
.kin-tbl table{border-collapse:collapse;width:100%;font-size:12px;line-height:16px}
.kin-tbl th{text-align:left;font-weight:500;color:#A9B4C0;background:#151A20;padding:8px 10px;border-bottom:1px solid #26303A;white-space:nowrap}
.kin-tbl td{padding:8px 10px;border-bottom:1px solid #26303A;vertical-align:top;min-width:64px}
.kin-tbl tr:last-child td{border-bottom:0}
.kin-foot{max-width:1840px;margin:0 auto;padding-block:24px 48px;color:#A9B4C0;font-size:12px}
"""


def gallery(boards_src, check, fragment=False):
    nav = ''.join(f'<a href="#{fn.lower()}">{e(t.split(" ")[0])}</a>' for fn, t, *_ in boards_src) + '<a href="#selfcheck">자기 점검</a>'
    secs = ''.join(
        f'<section class="kin-board" id="{fn.lower()}" aria-label="{e(t)}"><h2 class="kin-board-title">{e(t)} · {w} × {h}</h2>'
        f'<div class="kin-board-scroll" tabindex="0" role="group" aria-label="{e(t)} 아트보드">{body}</div></section>'
        for fn, t, body, w, h in boards_src)
    head = (f'<title>Kinetra Studio 셸 SC-01</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n<style>{GALLERY_CSS}</style>\n')
    main = (f'<header class="kin-top"><h1>Kinetra Studio 셸 · SC-01</h1>'
            f'<p>Studio 셸의 배치와 상태 아트보드 S1~S10 (1440 × 900, 어두운 테마). 규격: design/briefs/sc-01.md. 토큰과 컴포넌트는 design/exports/design-system/(v0) 그대로입니다. '
            f'3D 뷰포트, 인스펙터·판정 카드·변경안 카드의 내부는 자리 표시입니다.</p>'
            f'<nav class="kin-nav" aria-label="갤러리 목차">{nav}</nav></header>'
            f'<main>{secs}{selfcheck_html(check)}</main>'
            f'<footer class="kin-foot">독립 실행 HTML. 외부 요청이 없습니다. 글꼴 파일은 들어 있지 않아 Pretendard와 JetBrains Mono는 설치되어 있을 때만 쓰이고, 아니면 시스템 글꼴로 바뀝니다. '
            f'"예시" 꼬리표가 붙은 수치는 design-system.md 10절에 없는 지어낸 값입니다.</footer>')
    if fragment:
        return head + main
    return (f'<!doctype html>\n<html lang="ko">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f'{head}</head>\n<body>\n{main}\n</body>\n</html>\n')


# ---------------------------------------------------------------- 검사
FORBIDDEN = ['현실과 동일', '실제와 똑같이', '검증됨', '보장', '성공 확인', '통과', '불가능', '된다/안 된다', '에이전트가 가능하다고']


def checks(text, tokens_path):
    problems = []
    if tokens_path:
        tok = json.loads(pathlib.Path(tokens_path).read_text(encoding='utf-8'))
        allowed = {v.upper() for v in tok.values() if isinstance(v, str) and re.fullmatch(r'#[0-9A-Fa-f]{6}', v)}
        used = {h.upper() for h in re.findall(r'#[0-9A-Fa-f]{6}\b', text)}
        new = sorted(used - allowed)
        if new:
            problems.append(f'토큰에 없는 색: {new}')
        rgba = set(re.findall(r'rgba\([^)]*\)', text)) - {'rgba(0,0,0,0.5)'}
        if rgba:
            problems.append(f'토큰에 없는 rgba: {rgba}')
    if '#FF7B72' in text.upper():
        problems.append('status.danger(빨강)이 쓰였다')
    for w in FORBIDDEN:
        if w in text:
            problems.append(f'금지 문구: {w}')
    if re.search(r'https?://', text):
        problems.append('외부 URL이 있다')
    return problems


def main():
    out = pathlib.Path(sys.argv[1])
    tokens = sys.argv[sys.argv.index('--tokens') + 1] if '--tokens' in sys.argv else None
    art = sys.argv[sys.argv.index('--artifact') + 1] if '--artifact' in sys.argv else None
    src = out / 'source'
    src.mkdir(parents=True, exist_ok=True)
    built = build_boards()
    canvas = {'v': 3, 'createdOnFiles': {'v': 1, 'at': '2026-11-10T10:00:00Z'}, 'title': 'Kinetra Studio 셸 SC-01',
              'launch': {'view': 'canvas'}, 'pages': [], 'boards': {}, 'order': [], 'notes': {}, 'designSystems': []}
    check = {'boards': []}
    POS, yy = {}, 0
    for row in [['S1-Default', 'S2-Selected'], ['S3-Run', 'S4-VerdictNone'], ['S5-VerdictL2', 'S6-Halo'], ['S7-Collapsed'], ['S8-PlanetSwitch', 'S9-Offline'], ['S10-Keyboard']]:
        hh = 0
        for j, fn in enumerate(row):
            bh = next(b[4] for b in built if b[0] == fn)
            POS[fn] = (j * (W + 80), yy)
            hh = max(hh, bh)
        yy += hh + 160
    for i, (fn, title, root, w, h, frames) in enumerate(built):
        name = f'{fn}.dc.html'
        (src / name).write_text(dc_file(title, root, w, h), encoding='utf-8')
        x0, y0 = POS[fn]
        canvas['boards'][name] = {'x': x0, 'y': y0, 'w': w, 'h': h, 'title': title}
        canvas['order'].append(name)
        fr = []
        for f in frames:
            lab = title.split(' ')[0] + ('' if len(frames) == 1 else f'({f["id"][-1]})')
            fr.append({'label': lab, 'id': f['id'], 'count': len(f['ctls']), 'ctls': f['ctls'], 'reveals': f['reveals'], 'primary': f['primary']})
        check['boards'].append({'file': name, 'title': title, 'frames': fr})
    canvas['notes'] = {'row-1': {'x': 0, 'y': -200, 'text': 'SC-01 Studio 셸 · S1~S10', 'kind': 'title1', 'maxW': 2960}}
    (src / 'canvas.json').write_text(json.dumps(canvas, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    s1f = check['boards'][0]['frames'][0]
    assert sorted(s1f['ctls']) == sorted(S1_NAMES), f'S1 조작 요소가 5.1절과 다르다: {s1f["ctls"]}'
    for b in check['boards']:
        for f in b['frames']:
            assert f['primary'] == 1, f'{f["label"]}: primary {f["primary"]}개'

    # 갤러리는 방금 쓴 원본을 다시 읽어 만든다
    boards_src = []
    for name in canvas['order']:
        b = canvas['boards'][name]
        boards_src.append((name[:-8], b['title'], body_of((src / name).read_text(encoding='utf-8')), b['w'], b['h']))
    page = gallery(boards_src, check)
    probs = checks(page, tokens)
    if probs:
        raise SystemExit('검사 실패:\n  ' + '\n  '.join(probs))
    (out / 'index.html').write_text(page, encoding='utf-8')
    (src / 'tools' / 'selfcheck.json').write_text(json.dumps(check, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if art:
        pathlib.Path(art).write_text(gallery(boards_src, check, fragment=True), encoding='utf-8')
    for b in check['boards']:
        for f in b['frames']:
            print(f'{f["label"]:8} ctl={f["count"]:2} primary={f["primary"]} reveals={len(f["reveals"])}')
    print(out / 'index.html', len(page))


if __name__ == '__main__':
    main()
