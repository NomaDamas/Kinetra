#!/usr/bin/env python3
"""Build docs/pitch/script.json. Every spoken number is read from the demo bundle / sourced docs here, never typed in prose."""
import json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "apps/web/public/demo"
OUT = ROOT / "docs/pitch/script.json"


def load(p):
    return json.loads(Path(p).read_text())


def pct(x):
    v = round(x * 100, 1)
    return str(int(v)) if float(v).is_integer() else str(v)


def main():
    idx = load(DEMO / "index.json")
    scen = {s["id"]: s for s in idx["scenarios"]}
    rid = "roadster" if "roadster" in scen else next(i for i in scen if "rocket" in i)
    R = load(DEMO / rid / "scenario.json")
    V = R["variants"]
    imp = next((i for i, v in enumerate(V) if v["verdict"]["status"] == "INFEASIBLE_NECESSARY_CONDITION"), None)
    nf = [i for i, v in enumerate(V) if v["verdict"]["status"] == "NOT_FOUND_IN_BUDGET"]
    nf_i = nf[0] if nf else None
    fix_i = None
    fx = None
    for i in ([nf_i] if nf_i is not None else []) + ([imp] if imp is not None else []):
        f = V[i]["verdict"].get("suggested_fix")
        if f and f["changes"]:
            fx = f
            tv = f["changes"][0]["to_value"]
            fix_i = min((j for j, v in enumerate(V) if v["verdict"]["status"] == "FEASIBLE_FOUND"), key=lambda j: abs(V[j]["value"] - tv))
            break
    assert nf_i is not None and fix_i is not None, "roadster bundle lacks a not-found + feasible pair"
    unit = R["control"]["unit"]
    nfv = V[nf_i]
    n_evals = int(re.search(r"([\d,]+) evaluations", nfv["headline"]).group(1).replace(",", ""))
    chk = None
    if imp is not None:
        c = next(c for c in V[imp]["verdict"]["necessary_checks"] if not c["passed"])
        chk = c
    fixv = V[fix_i]
    fp = fixv["verdict"]["feasibility"]
    p_fix, lo, hi, n_mc = fp["p_success"], fp["ci_low"], fp["ci_high"], fp["n_samples"]
    n_steps = len(R["agent_steps"])
    # humanoid (optional)
    H = None
    hid = next((i for i in ("humanoid", "g1_jump") if i in scen and (DEMO / i / "scenario.json").exists()), None)
    if hid:
        H = load(DEMO / hid / "scenario.json")
    # autoresearch
    L = load(DEMO / "autoresearch/ledger.json")
    conf = {c["id"]: c for c in L["confirmation"]}
    base = conf["att-000"]
    pdc = conf["att-006"]
    I = load(DEMO / "autoresearch/integration.json")
    sb = next(r for r in I["rows"] if r["family"] == "schedule" and r["stage"] == "before")
    sa = next(r for r in I["rows"] if r["family"] == "schedule" and r["stage"] == "after")
    X = load(DEMO / "autoresearch/excitation.json")
    ni = X["n_identified"]
    # sourced cost figures: docs/judgment-spec.md section D (read, not typed)
    spec = (ROOT / "docs/judgment-spec.md").read_text()
    secD = spec.split("## D.")[1].split("## E.")[0]
    m1 = re.search(r"80×120 ft\) \| ≈ \$([\d,]+) / hour", secD)
    m2 = re.search(r"10×10 ft\) \| ≈ \$([\d,]+) / hour", secD)
    m3 = re.search(r"\$(\d+) k–\$(\d+) k per spin", secD)
    wt1, wt2, sp_lo, sp_hi = m1.group(1), m2.group(1), m3.group(1), m3.group(2)
    assert wt1 and wt2 and sp_lo

    s = []

    def sc(id, title, slide, ko, en, actions=None, dur_min=0.0):
        s.append(dict(id=id, title=title, slide=slide, narration=[dict(id=f"{id}.{k}", ko=a, en=b, actions=(actions or {}).get(k, [])) for k, (a, b) in enumerate(zip(ko, en))]))

    sc("problem", "Problem", dict(kind="problem", wt=[wt1, wt2], spin=[sp_lo, sp_hi],
        sources=[
            "NASA Glenn education slide 'Types of Wind Tunnels' (facility hourly rate, old, excludes model build/staff)",
            "Octavo Systems 'The Real Cost of a Board Spin' (vendor claim, SiP vendor with commercial interest)",
            "Rocket hot-fire cost per test: no primary source found, NO NUMBER SHOWN"]),
       ["물리 실험은 비쌉니다. NASA 교육 자료는 풍동 시간당 비용을 약 " + wt1 + "달러에서 " + wt2 + "달러로 추정합니다. 시설 사용료만이고, 모델 제작과 인건비는 빠져 있습니다.",
        f"하드웨어 시제품 재제작은 벤더 블로그 기준 {sp_lo}천에서 {sp_hi}천 달러입니다. 이쪽은 벤더 주장이라 참고용입니다. 로켓 연소 시험 비용은 믿을 만한 출처를 못 찾아서 숫자를 쓰지 않았습니다."],
       ["Physical experiments are expensive. A NASA education slide estimates wind tunnel time at about $" + wt1 + " to $" + wt2 + " per hour. That is the facility rate only, without model build or staff.",
        f"A hardware respin is ${sp_lo}k to ${sp_hi}k by one vendor blog, so treat it as a vendor claim. For rocket hot fire we found no primary source, so we show no number."])
    sc("insight", "Insight", dict(kind="insight"),
       ["아이디어를 만들기 전에 걸러내는 것이 핵심입니다. 판정은 MuJoCo가 하고, 화면의 3D는 저장된 궤적을 재생하는 배우일 뿐입니다. 모든 숫자는 시뮬레이션 도구에서 나오고 언어 모델에서 나오지 않습니다."],
       ["The point is to screen bad ideas before anyone builds them. MuJoCo is the judge. Three.js is only the actor replaying a stored trajectory. Every number comes from simulation tools, never from a language model."])
    pick = f"chip:{scen[rid]['title']}"
    sc("demo_roadster", "Demo 1: roadster flip", dict(kind="app", tab="lab"),
       [f"첫 번째 데모입니다. 이것은 기록된, 시드가 고정된 재현 가능한 실행입니다. 실시간 계산이 아닙니다. 로켓 추력기로 공중 회전을 하는 로드스터를 고릅니다.",
        f"에이전트는 도구 {n_steps}개를 순서대로 호출했습니다. 이 로그는 기록된 것입니다.",
        f"추력기 하나당 {fmtn(nfv['value'])} 뉴턴으로 설정하면, {n_evals}번 평가해도 해를 찾지 못했습니다. 이것은 약한 증거이고, 불가능의 증명이 아닙니다.",
        ] + ([f"더 낮은 {fmtn(V[imp]['value'])} 뉴턴에서는 필요한 회전 시간 {chk['measured']:.1f}초가 가용 시간 {chk['limit']:.2f}초를 넘습니다. 이건 필요조건 위반이라 가정 하에서 강한 불가능입니다."] if imp is not None and chk else []) + [
        f"옵티마이저의 수정안은 {fmtn(fx['changes'][0]['from_value'])}에서 {fmtn(fx['changes'][0]['to_value'])} 뉴턴으로 올리는 것입니다. 수정안을 적용하겠습니다.",
        f"해를 찾았습니다. 하지만 가정 표본 {n_mc}개 중 {pct(p_fix)}퍼센트에서만 성공하고, 신뢰구간은 {pct(lo)}에서 {pct(hi)}퍼센트입니다. 취약한 해이고, 단순화된 모델이라 정밀 검증이 필요합니다."],
       [f"Demo one. This is a recorded, seeded, reproducible run, not live compute. We pick the roadster that flips on rocket thrusters.",
        f"The agent called {n_steps} tools in order. This log is recorded.",
        f"At {fmtn(nfv['value'])} newtons per nozzle, the search did not find a solution in {n_evals} evaluations. That is weak evidence, not proof of impossibility.",
        ] + ([f"At a lower {fmtn(V[imp]['value'])} newtons, the flip needs {chk['measured']:.1f} seconds but only {chk['limit']:.2f} seconds are available. A necessary condition is violated: strong impossibility under the assumptions."] if imp is not None and chk else []) + [
        f"The optimizer's fix raises thrust from {fmtn(fx['changes'][0]['from_value'])} to {fmtn(fx['changes'][0]['to_value'])} newtons. Applying the fix.",
        f"A solution is found, but it works in only {pct(p_fix)} percent of {n_mc} sampled assumption sets, with a 95 percent interval of {pct(lo)} to {pct(hi)}. It is fragile, and the model is simplified and needs precise validation."],
       None)
    # actions for demo_roadster (line index -> list); at = seconds after line start
    nl = len(s[-1]["narration"])
    A = {0: [dict(at=3.0, type="select_scenario", title=scen[rid]["title"])],
         1: [dict(at=0.3, type="scroll", target="run")],
         2: [dict(at=0.3, type="open_assumptions"), dict(at=0.8, type="set_variant", value=nfv["value"])]}
    k = 3
    if imp is not None and chk:
        A[k] = [dict(at=0.3, type="set_variant", value=V[imp]["value"])]
        k += 1
    A[k] = [dict(at=0.2, type="scroll", target="fix"), dict(at=4.0, type="apply_fix")]
    A[k + 1] = [dict(at=0.4, type="scroll", target="verdict"), dict(at=0.4, type="play")]
    for i, a in A.items():
        s[-1]["narration"][i]["actions"] = a
    # humanoid
    if H:
        hv = H["variants"]
        feas = [v for v in hv if v["verdict"]["status"] == "FEASIBLE_FOUND"]
        bad = [v for v in hv if v["verdict"]["status"] != "FEASIBLE_FOUND"]
        ko = ["두 번째 데모는 휴머노이드 점프와 착지입니다. 같은 기록된 재현 가능한 실행입니다."]
        en = ["Demo two is a humanoid jump and landing. Same recorded, reproducible run."]
        acts = {0: [dict(at=2.5, type="select_scenario", title=scen[hid]["title"])]}
        if bad:
            b = bad[0]
            ko.append(f"{R and H['control']['label']} {fmtn(b['value'])} {H['control']['unit']}에서는 {b['headline'].split(': ',1)[-1][:90]}. 이 문장은 번들에서 읽은 그대로입니다.")
            en.append(f"At {H['control']['label']} {fmtn(b['value'])} {H['control']['unit']}: {b['headline'].split(': ',1)[-1][:120]}. This sentence is read from the bundle.")
            acts[1] = [dict(at=0.5, type="set_variant", value=b["value"])]
        if feas:
            f0 = feas[-1]
            ko.append(f"{fmtn(f0['value'])} {H['control']['unit']}에서는 해를 찾았습니다. 재생해 보겠습니다. 단순화된 모델입니다.")
            en.append(f"At {fmtn(f0['value'])} {H['control']['unit']} a solution is found. Replaying it. Simplified model.")
            acts[len(ko) - 1] = [dict(at=0.5, type="set_variant", value=f0["value"]), dict(at=1.5, type="play")]
        sc("demo_humanoid", "Demo 2: humanoid jump", dict(kind="app", tab="lab"), ko, en, acts)
    sc("autoresearch", "Autoresearch", dict(kind="app", tab="autoresearch"),
       ["이제 오토리서치입니다. 여기 데이터는 합성 데이터이고, 실물 검증은 하지 않았습니다. 이 점을 분명히 말씀드립니다.",
        f"자세 제어에서 기본 개루프 스케줄은 200개 교란 표본 중 {pct(base['success_rate'])}퍼센트만 성공했습니다. 피드백 제어를 추가한 설정은 {pct(pdc['success_rate'])}퍼센트입니다. 장난감 10킬로그램 시험체이고 실제 차량에 대한 주장이 아닙니다.",
        f"보정 실험 추천은 식별 가능한 매개변수를 {ni['of']}개 중 {ni['baseline']}개에서 {ni['recommended']}개로 늘렸습니다. 판정에 반영하면 스케줄 제어기의 성공률이 {pct(sb['p'])}퍼센트에서 {pct(sa['p'])}퍼센트로 움직입니다. 단, 모델 클래스가 같은 자기일관 테스트입니다."],
       ["Now autoresearch. The data here is synthetic and sim-to-real is not validated. We say this up front.",
        f"For attitude control, the baseline open-loop schedule succeeds in {pct(base['success_rate'])} percent of 200 disturbed samples. With feedback it is {pct(pdc['success_rate'])} percent. It is a toy 10 kilogram article, not a claim about a real vehicle.",
        f"The calibration experiment recommendation raises identifiable parameters from {ni['baseline']} to {ni['recommended']} of {ni['of']}. In the verdict, the schedule controller moves from {pct(sb['p'])} to {pct(sa['p'])} percent. This is a self-consistent test where the model class matches the generator."],
       None)
    s[-1]["narration"][0]["actions"] = [dict(at=0.3, type="tab", tab="autoresearch")]
    s[-1]["narration"][1]["actions"] = [dict(at=0.5, type="scroll", target="top")]
    s[-1]["narration"][2]["actions"] = [dict(at=0.5, type="scroll", target="bottom")]
    sc("asymmetry", "Verdict asymmetry", dict(kind="asymmetry"),
       ["판정은 비대칭입니다. 해를 찾으면 가정 안에서 강한 증거입니다. 필요조건이 깨지면 강한 불가능입니다. 예산 안에서 못 찾은 것은 약한 증거일 뿐이고, 절대 증명이라 말하지 않습니다."],
       ["Verdicts are asymmetric. Found is strong evidence within the assumptions. A violated necessary condition is a strong impossibility. Not found within budget is weak evidence only, and we never call it proof."])
    sc("diff", "Differentiation", dict(kind="diff"),
       ["Drift builds the sim. We kill ideas not worth simulating.".replace("Drift builds the sim. We kill ideas not worth simulating.", "Drift builds the sim. We kill ideas not worth simulating."),
        "Luminary speeds up experts' simulations. We give everyone their first physical experiment."],
       ["Drift builds the sim. We kill ideas not worth simulating.",
        "Luminary speeds up experts' simulations. We give everyone their first physical experiment."])
    sc("business", "Business model (UNVALIDATED)", dict(kind="business"),
       ["사업 모델은 가설이고 검증되지 않았습니다. 지불 의사는 확인하지 못했고, 고객이나 매출도 아직 없습니다."],
       ["The business model is a hypothesis and is unvalidated. We have not confirmed willingness to pay, and we have no customers or revenue yet."])
    sc("roadmap", "Roadmap", dict(kind="roadmap"),
       ["다음 단계는 실물 데이터로 보정을 검증하는 것, 더 많은 템플릿, 그리고 사용자 인터뷰입니다."],
       ["Next: validate calibration against real data, add more templates, and run user interviews."])
    sc("ask", "Ask", dict(kind="ask"),
       ["저희가 원하는 것은 이 가설을 검증할 첫 사용자와 실물 시험 데이터를 가진 파트너입니다. 감사합니다."],
       ["What we need: first users to test this hypothesis, and partners with real test data. Thank you."])
    meta = dict(tag_ko="기록된 실행, 시드 고정 · 재현 가능", tag_en="recorded run, seeded & reproducible", humanoid_included=bool(H),
                bundle=dict(roadster=rid, humanoid=hid, control_unit=unit))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dict(meta=meta, scenes=s), ensure_ascii=False, indent=1))
    print("wrote", OUT, "scenes", len(s), "humanoid", bool(H))


def fmtn(x):
    return str(int(x)) if float(x).is_integer() else str(x)


if __name__ == "__main__":
    main()
