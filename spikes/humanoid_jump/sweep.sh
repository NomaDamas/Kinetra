#!/bin/bash
# feasibility-boundary sweep: (target, torque_scale, payload)
cd "$(dirname "$0")"
run() { TSCALE=$2 PAYLOAD=$3 TAG="_ts$2_pl$3" .venv/bin/python optimize.py $1 4000 1 > /tmp/sw.txt 2>&1; .venv/bin/python - "$1" "$2" "$3" <<'P'
import sys,json
t,ts,pl=sys.argv[1:4]
txt=open('/tmp/sw.txt').read(); j=json.loads(txt[txt.index('{'):]); r=j['result']
print(f"target={t} torque_scale={ts} payload={pl}kg -> h={r['com_apex_rise']:.3f} stable={r['stable_landing']} landed={r['landed']} grf_bw={r['grf_peak_land_bw']:.2f} demand_ratio={r['torque_demand_ratio_max']:.2f} wall={j['wall_s']:.0f}s cost={j['cost']:.3f}",flush=True)
P
}
for ts in 1.0 0.7 0.5 0.35; do run 0.2 $ts 0; done
run 0.2 1.0 5; run 0.4 1.0 5; run 0.4 0.5 0
run 0.7 1.0 0; run 1.0 1.0 0
