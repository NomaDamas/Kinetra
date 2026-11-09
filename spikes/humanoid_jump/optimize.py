import sys, time, json, os, numpy as np, cma
from multiprocessing import Pool
from jump import *
os.makedirs("out", exist_ok=True)
_sim = None
def _init():
    global _sim; _sim = Sim(payload=float(os.environ.get("PAYLOAD", 0)), torque_scale=float(os.environ.get("TSCALE", 1)))
def _f(p):
    return objective(p, _sim, _f.target)[0]
def work(args):
    p, target = args
    c, r = objective(p, _sim, target)
    return c
def run(target, budget_evals=3000, seed=1, popsize=20, sigma0=0.3):
    scale = HI - LO
    x0 = (P0 - LO) / scale
    es = cma.CMAEvolutionStrategy(x0, sigma0, dict(seed=seed, popsize=popsize, bounds=[0, 1], verbose=-9))
    t0 = time.time(); n = 0; best = (1e9, None)
    with Pool(10, initializer=_init) as pool:
        while n < budget_evals and not es.stop():
            xs = es.ask()
            ps = [LO + np.array(x) * scale for x in xs]
            cs = pool.map(work, [(p, target) for p in ps])
            es.tell(xs, cs); n += len(xs)
            i = int(np.argmin(cs))
            if cs[i] < best[0]: best = (cs[i], ps[i])
            if (n // popsize) % 10 == 0: print(f"  evals={n} best={best[0]:.4f} t={time.time()-t0:.1f}s", flush=True)
            if best[0] < 0.03 + 0.0 and False: break
    return best, n, time.time() - t0
if __name__ == "__main__":
    target = float(sys.argv[1]); budget = int(sys.argv[2]); seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    (c, p), n, dt = run(target, budget, seed)
    s = Sim(payload=float(os.environ.get("PAYLOAD", 0)), torque_scale=float(os.environ.get("TSCALE", 1))); r = s.rollout(p)
    for k in ("per_joint_demand_ratio", "sat_frac"): r[k] = [round(x, 3) for x in r[k]]
    out = dict(target=target, seed=seed, evals=n, wall_s=dt, cost=c, params=dict(zip(PNAMES, map(float, p))), result=r)
    json.dump(out, open(f"out/best_{target}_seed{seed}{os.environ.get("TAG","")}.json", "w"), indent=1)
    print(json.dumps(out, indent=1))
