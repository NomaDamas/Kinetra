#!/usr/bin/env python3
"""Print the SC-15 self-check numbers that measure.html wrote into the dumped DOM.

usage: read_measure.py <dom.html> [--full]
Prints one line per artboard: controls (always visible / with opened parts), primaries, problems.
Problems are any non-empty list among stray, small, overflow, clipped, unitSpill, cellSpill,
squeezed, lowContrast, offToken, banned.
"""
import html, json, re, sys

t = open(sys.argv[1], encoding='utf-8').read()
m = re.search(r'MEASURE(.*?)ENDMEASURE', t, re.S)
if not m:
    raise SystemExit('no MEASURE block in ' + sys.argv[1])
data = json.loads(html.unescape(m.group(1)))
PROBLEMS = ['stray', 'small', 'overflow', 'clipped', 'unitSpill', 'cellSpill', 'squeezed', 'lowContrast', 'offToken', 'banned']
if '--full' in sys.argv:
    print(json.dumps(data, ensure_ascii=False, indent=1))
    raise SystemExit
allc = set()
for b in data:
    allc.update(b['colors'])
    units = '; '.join(f"{u['unit']} {u['persistent']}+{u['transient']}" + (f" p{u['primary']}" if u['primary'] else '') for u in b['units'])
    probs = {k: b[k] for k in PROBLEMS if b[k]}
    spare = ','.join(str(p['spare']) for p in b['panels'])
    print(f"{b['name']}: ctl {b['controls']}/{b['controlsTotal']} | primary panel {b['primaryInPanels']} topbar {b['primaryInTopBar']} | "
          f"contrast {b['minContrast']} | badges {','.join(b['badges'])} | units {units} | panel spare {spare}")
    for s in b['status']:
        print('   status colour:', s)
    for k, v in probs.items():
        print('   PROBLEM', k, json.dumps(v, ensure_ascii=False)[:600])
print('colours used:', len(allc), ' '.join(sorted(allc)))
