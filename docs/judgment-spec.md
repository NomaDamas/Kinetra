# Judgment Spec — Tier-1 Templates (v0, hackathon)

Scope: what each template MUST compute, how, and how the result is worded. No code here.
Physics judge = MuJoCo (`mujoco` Python). All numbers in a report come from these computations; the LLM only fills the assumptions panel and writes prose around tool output.

**Conventions**
- `N` = **necessary condition**: violation ⇒ strong "impossible within model assumptions". Passing proves nothing.
- `S` = **sufficient evidence**: produced by a rollout that actually succeeded ⇒ strong "possible within model assumptions".
- `status` of every constant: `sourced` (link given), `default` (our choice, editable, not claimed true), `unverified` (a figure from a secondary source or memory — user must confirm).
- Distributions: `N(μ,σ)` normal, `U(a,b)` uniform, `LN(μ,σ)` lognormal. All MC draws use a fixed seed (`seed = hash(spec_json)`), so same input ⇒ same verdict.
- "Favorable bound" of an assumption = the 5th/95th percentile in the direction that helps feasibility. Strong-impossible claims are tested at favorable bounds (Section A, rule R3).
- Every simplified item carries label `SIMPLIFIED` = **"simplified model, needs precise validation"**.

Shared MuJoCo calls: `mj_forward`, `mj_step`, `mj_inverse` (→ `d.qfrc_inverse`), `mj_contactForce`, `mj_jacSubtreeCom`, `mj_energyPos/Vel` (needs `<option><flag energy="enable"/>`), `mj_setConst` after editing `m.body_mass/body_inertia`. Actuator limits: `m.actuator_forcerange`, `m.actuator_ctrlrange`, `m.actuator_gear`; joint-level: `m.jnt_actfrcrange`; actuator→joint map: `d.actuator_moment` (sparse; `mj_transmission` fills it).

---

## 1. Template `rocket_car` (e.g. Roadster cold-gas / rocket-thruster aerial roll + pitch rotation)

**Maneuver as implemented (decided interpretation).** In ONE ramp jump the car completes a full 360° rotation about its body pitch axis AND a full 360° about its body roll axis, then lands upright. A rotation counts as full when `|∫ω dt| >= 340°` (360° minus the 20° tolerance) for the body-frame angular-velocity component (`qvel[3]` roll about x, `qvel[4]` pitch about y), integrated from launch to first touchdown. Upright = roll and pitch each within 20° (final) / 30° (touchdown) of a whole number of turns (wrapped ZYX Euler angles), plus touchdown vertical speed <= 6 m/s, touchdown pitch and roll rates <= 3 rad/s, no thrust after contact, propellant within the cap, ride height 0.5–0.8 m. The two rotations may be simultaneous or sequential; the optimizer decides. The template has 18 nozzles: 10 pitch/lift (as before) plus 8 side roll nozzles (up/down pairs at y = ±0.95 m, two couples for +/- roll), and a 21-parameter burn schedule (7 windows x start/duration/throttle). Necessary screen: R2 is evaluated for pitch AND roll (roll inertia `I_x` from the MuJoCo model, roll torque from the side nozzles' lateral arms) and the propellant bound takes the more demanding axis.

Model: free-body car (`freejoint`), 4 wheel contacts, N thruster sites (force along site axis, `<general>` actuator with `gear` on a site transmission, or applied via `d.xfrc_applied`), propellant mass depleting in the Python loop (`m.body_mass[tank]`, then `mj_setConst`). Control parameterization for CMA-ES: thrust-pair on/off times `t_on1,t_off1,t_on2,t_off2`, pair-split ratio, launch speed `v0`, ramp angle (≈6–8 dims).

### 1.1 Judgment items

| # | Item | Formula / MuJoCo call | Type | Threshold & source | Label |
|---|------|----------------------|------|--------------------|-------|
| R1 | **Thrust-to-weight (vertical-capable)** | `TWR = ΣF_i·ẑ_body-axis·cosφ / (m_total·g)`; F_i = `m_dot_i·Isp·g0` or nozzle `p·A_t·C_F` | **N** if thrusters are claimed to lift/hover the car: TWR<1 ⇒ cannot sustain lift. Not required for a pure flip. | TWR ≥ 1 is Newton's 2nd law (no source needed). Margin target ≥1.2 is `default`. | — |
| R2 | **Min pitch AND roll rotation time vs available air time** (`flip_time_vs_air_time`, `roll_time_vs_air_time`) | `I_y` about COM: `Σ[R·diag(body_inertia)·Rᵀ + m_i(|d_i|²E − d_i d_iᵀ)]` over car bodies (cross-check: set free-joint ω, read `d.subtree_angmom[0]` / `I`). `τ_max = Σ_i F_i·r_i` (couple arm about COM, `d.site_xpos − d.subtree_com`). Bang-bang min-time for rotation θ=2π: `α=τ_max/I_y`, `T_min = 2·√(2π/α)`. `T_air` = ballistic time from launch `v_z0` and drop height: `T_air = (v_z0+√(v_z0²+2g·h_drop))/g`. | **N**: `T_air < T_min` ⇒ impossible (even with ideal control). | Physics identity. Required rotation (2π flip, π/… partial) is user spec. | — |
| R3 | **Angular impulse needed vs available** | `L_req = I_y·ω_peak`, `ω_peak=√(2π·α)` (min-time profile; also despin ⇒ ×2 total). `L_avail = ∫τ dt = τ_max·t_burn_max`, `t_burn_max = m_usable·Isp·g0 / ΣF_i` | **N**: `2·L_req > L_avail` ⇒ impossible | Physics identity | — |
| R4 | **Propellant mass (rocket equation)** | Impulse form (small Δv/mass fraction): `m_p = I_total / (Isp·g0)`, `I_total=∫ΣF dt`. Full form for large mass fraction: `Δv = Isp·g0·ln(m0/mf)` → `m_p = m0(1−e^{−Δv/(Isp g0)})`. Usable cold-gas mass, isothermal blowdown: `m_gas = (p0−p_min)·V·M/(R·T0)`, N₂ M=0.028 kg/mol, R=8.314 J/mol/K | **N**: `m_p,required > m_gas,usable` ⇒ impossible. Rollout-time depletion check is **S**-side. | Rocket equation: [NASA Glenn, Ideal Rocket Equation](https://www1.grc.nasa.gov/beginners-guide-to-aeronautics/ideal-rocket-equation). Isp(N₂ cold gas) ≈ 60–75 s = `unverified` | SIMPLIFIED (isothermal; real adiabatic cooling lowers usable mass and Isp) |
| R5 | **Landing peak G (vehicle)** | Rollout: accelerometer sensor at COM (`mjSENS_ACCELEROMETER`) or `‖Σ contact force‖/(m g)` via `mj_contactForce` over contacts in the first 0.5 s after touchdown. Pre-check (N): `a_stop = v_td²/(2·s_stroke)`, `v_td = √(v_z_land²+…)` from ballistic phase, `s_stroke` = suspension+tire travel | **N**: `a_stop/g` > structural limit even with full stroke ⇒ impossible. **S**: rollout peak below limits | Vehicle limit = `default` (see assumptions); actual chassis/battery structure limit is **not** judged (→ STRUCTURAL_UNMODELED) | SIMPLIFIED (rigid body + spring-damper) |
| R6 | **Occupant G limit (duration-aware)** | Accelerometer at seat site; compute running mean `ā(Δ)` over windows Δ∈{0.044, 0.1, 0.2} s (window-max). Limit curve (restrained seated, spineward): 45 G @0.044 s, 40 G @0.1 s, 25 G @0.2 s | **N** (pre-check from R5 `a_stop`) and **S** (rollout): `ā(Δ) > limit(Δ)` ⇒ FAIL; ≤ ⇒ PASS | Eiband, NASA Memo 5-19-59E, Fig. 2 "voluntary tolerance" boundary, onset ≈500 G/s: [NTRS 19980228043](https://ntrs.nasa.gov/api/citations/19980228043/downloads/19980228043.pdf). Applies only to restrained seated occupants; **comfort/safety margin factor 0.5 is `default`** | SIMPLIFIED (human tolerance from 1950s volunteer sled data; not injury prediction for a specific person) |
| R7 | **COM / inertia sensitivity** | Finite differences: perturb `m_total ±5%`, COM offset ±`δ` (shift `body_ipos` of payload/battery bodies), `I_y ±10%`; `mj_setConst`; recompute R2/R3 margins. `S_i = ∂(margin)/∂θ_i · σ_i/|margin|` (normalized) | Neither (diagnostic). Report top-3 `S_i`; if a ±1σ move flips PASS→FAIL, tag result `FRAGILE` | Default perturbation sizes `default` | — |
| R8 | **Roll + pitch rotation achieved (rollout)** | CMA-ES-found controller; pass if: the body-rate integrals of BOTH pitch and roll reach >= 340° by first touchdown, roll and pitch are within tolerance of a whole number of turns at touchdown and at the end, post-touchdown rollover not occurring within 1.0 s (body z-axis·world z > 0.5) | **S** (the verdict "solution found"). Includes R5/R6 as constraints | Pass tolerances `default` | SIMPLIFIED |
| R9 | **Thruster-ramp duty energy sanity** | Gas energy (isothermal, ideal): `W_gas = p0·V·ln(p0/p_min)` vs. kinetic+rotational energy gain `½Iω²+Δ(½mv²)+mgΔh` | **N** only as loose check (jets are very inefficient) — flag if required > W_gas | Thermodynamics | SIMPLIFIED |

### 1.2 Editable assumptions (rocket_car)

| Parameter | Default distribution | Status / source |
|-----------|---------------------|-----------------|
| Vehicle mass (incl. occupant, gas) | `N(1900, 80)` kg | `unverified`. Top Gear interview reported via secondary analysis: weight-reduction *target* <1700 kg ([Locsic analysis](https://locsic.com/thinking/tesla-roadster-2026-analysis/)); production mass not confirmed. |
| Wheelbase / COM height | wheelbase 2.825 m (secondary, same source); COM height `N(0.45,0.03)` m | wheelbase `unverified`; COM height `default` |
| Pitch inertia `I_y` | derived from geometry template; ×`LN(0, 0.10)` | `default` |
| Thruster count & positions | per spec (secondary source: 10 nozzles on Rocket variant: 4 rear, 4 up, 2 front-yaw). The template adds 8 side roll nozzles (our modeling choice, not a sourced layout) | `unverified` |
| Per-nozzle thrust | `U(0.5, 1.5) ×` nominal; nominal derived from `p·A_t·C_F` | `default`; no official thrust figure known to us |
| Storage volume `V` | 200 L rear; 600 L total in Rocket variant (secondary) | `unverified` |
| Storage pressure `p0` / `p_min` | `U(250, 450)` bar / 5 bar | `default` |
| Isp (cold gas N₂) | `N(65, 7)` s | `unverified` |
| Launch speed / ramp angle | optimizer variables; ramp angle bound `[0°, 35°]` | `default` |
| Suspension+tire stroke `s_stroke` | `N(0.15, 0.03)` m | `default` |
| Vehicle structural landing limit | `U(8, 15)` g | `default` (no source) |
| Occupant limit factor on Eiband curve | `0.5` fixed (editable) | `default` |

---

## 2. Template `humanoid_jump` (jump and landing)

Model: MuJoCo humanoid (menagerie or own MJCF) with `<motor>` or `<position>` actuators having `forcerange`/`ctrlrange` set from the assumptions panel; ground plane with friction. Control parameterization: crouch depth, push-off timing/ramp of knee/hip/ankle torque scalings, arm swing amplitude, landing-stance pose, landing impedance gain (≈8–12 dims).

### 2.1 Judgment items

| # | Item | Formula / MuJoCo call | Type | Threshold & source | Label |
|---|------|----------------------|------|--------------------|-------|
| H1 | **Static torque saturation (hold crouch)** | Set pose `qpos=q_crouch`, `qvel=0`, `qacc=0`; `mj_inverse(m,d)`; `τ_req = d.qfrc_inverse` (generalized forces incl. gravity & contact if feet in contact). Map to actuators: solve `A·u = τ_req`, `A = actuator_moment^T·diag(gear)` (least squares / `mj_mulM`-free; for 1:1 joint motors `u=τ_req/gear`). `ρ_static = max_j |u_j| / forcerange_j` | **N**: `ρ_static>1` at *every* pose in the planned crouch range (sample the squat sweep) ⇒ impossible (cannot even hold the crouch) | Threshold ρ>1 is definition. Torque limits come from user panel (`default`, see assumptions) | — |
| H2 | **Takeoff impulse required** | `v_to = √(2g·h_jump)` (COM apex rise `h_jump`, user spec). `J_req = m·v_to + m·g·t_push` (net vertical impulse). Required mean COM accel over stroke `s_push`: `a_req = v_to²/(2 s_push)` → `F_req = m(a_req+g)` | **N** with H3 | Physics identity | — |
| H3 | **Takeoff impulse available (max-effort bound)** | At several poses along push stroke: desired `qacc* = J_com⁺·[0,0,a_req]` (use `mj_jacSubtreeCom` for body 0 `J_com`; `J_com⁺` pseudo-inverse); `mj_inverse` with `qacc=qacc*` ⇒ `τ`; `ρ_dyn(q)=max_j|u_j|/forcerange_j`. Available impulse bound: `F_max(q)=F_req/ρ_dyn(q)` (linear scaling; valid for fixed pose, ignoring contact unilaterality) ⇒ `J_avail ≈ ∫F_max(q(s))·ds/v̄`. **Speed/power bound**: `P_req=F_req·v_to/2` vs. `Σ_j τ_max,j·ω_max,j` (ω_max from panel) | **N**: `min_s ρ_dyn(q(s))>1` over the whole stroke ⇒ impossible; or `P_req > P_peak_total` ⇒ impossible | ρ and P limits from user panel | SIMPLIFIED (ignores actuator bandwidth, tendon/elastic storage unless modeled) |
| H4 | **Joint torque saturation ratio (rollout)** | Over the rollout: `ρ_j(t)=|d.actuator_force[j]|/max(|forcerange_j|)`; report `max_t ρ_j`, and fraction of push-off time with `ρ_j≥0.98` (saturated) per joint. Name the arg-max joint → "binding constraint" | **S** feature (solution used actuators within limits by construction as MuJoCo clips). Used to name binding joint when search fails (`ρ≥0.98` for most of push-off) | `0.98` saturation flag = `default` | — |
| H5 | **Landing peak ground reaction force (GRF)** | Rollout: `F_z(t)=Σ_contacts` normal component from `mj_contactForce` (frame→world via `d.contact[i].frame`), restricted to foot geoms. Peak over 1 s post-touchdown; `GRF_peak/(m g)` in body weights (BW). Pre-check (N): `F_avg=m·v_td²/(2·s_stop)+mg` with `s_stop`=max COM drop on landing (leg stroke) | **N** (pre-check): `F_avg` exceeds `(F_max at landing pose by H3 method)` ⇒ cannot decelerate within stroke ⇒ impossible. **S**: peak ≤ limit in rollout | Limit = `default` (e.g. 10 BW); no hardware-specific source. Human reference not cited here (we do not have a sourced figure) | SIMPLIFIED (soft contact params `solref/solimp` affect peak; report sensitivity) |
| H6 | **Tipping / support margin** | Support polygon = convex hull of foot-geom contact points with `F_n>ε` (from `d.contact`). COM projection `c=d.subtree_com[0][:2]`. **Static margin** `m_s = min signed distance(c, polygon edges)`. **ZMP**: `x_zmp = Σ_i (p_i,x F_i,z) / Σ F_i,z` (+ contact torque terms from `mj_contactForce` torque rows when condim≥4); `m_z = min signed distance(ZMP, polygon)` | **S** gate: after landing, require `m_z>0` for all t in settle window and final `m_s>margin` and no fall (torso height > 0.6·standing height at T+2 s). Violation of H6 in the rollout is not by itself "impossible" (controller may be bad) | `margin=0.01 m`, settle window 2.0 s = `default` | — |
| H7 | **Payload sensitivity** | Add payload mass `Δm` to torso body (`m.body_mass`, scale `body_inertia` proportional, `mj_setConst`). Recompute H1/H3 `ρ` and re-run best controller. Report `Δm*` = max payload with `ρ_static≤1` (bisection over Δm, ≤12 evals) and `∂ρ/∂Δm` | Diagnostic (also gives "suggested fix" input: payload cap or actuator upgrade found by optimizer, not LLM) | Perturbation range `[0, +50%]` of body mass = `default` | — |
| H8 | **Jump achieved (rollout)** | CMA-ES controller; pass if: COM apex rise ≥ `h_jump` (measured from standing COM), feet-off-ground flight phase detected (no foot contact for ≥ 50 ms), landing without fall (H6), no self-collision penetration beyond tol, `ρ_j≤1` by clipping *and* not trivially rail-bound in whole stroke (H4 info) | **S** | `tol`s `default` | SIMPLIFIED |
| H9 | **Foot slip at takeoff** | `μ_req = max_t |F_t|/F_n` over stance from `mj_contactForce`; compare `μ_req` vs. floor friction `μ` | **N** (sub-check): required horizontal-to-vertical ratio at best posture > μ ⇒ impossible on that floor | μ from panel (`default`) | — |

### 2.2 Editable assumptions (humanoid_jump)

| Parameter | Default distribution | Status / source |
|-----------|---------------------|-----------------|
| Body mass | `N(70, 8)` kg (or robot spec if the user names one, then `N(spec, 1%)`) | `default` |
| Per-joint peak torque (knee/hip/ankle) | per robot spec; for generic: knee `N(150,20)`, hip `N(150,20)`, ankle `N(80,12)` N·m | `default`/`unverified` |
| Joint speed limit ω_max | knee/hip `U(8,15)` rad/s | `default` |
| Motor torque scale (derating/hot) | `U(0.85, 1.0)` | `default` |
| Target apex rise `h_jump` | user input | user spec |
| Leg stroke `s_push`, `s_stop` | derived from model geometry ±5% | `default` |
| Ground friction μ | `U(0.6, 1.0)` | `default` |
| Contact stiffness `solref` | `[0.02,1]` ± 25% | `default` (MuJoCo default-ish) |
| Payload | `N(0, 0)` default (user-set) | user spec |
| Landing GRF limit | `U(6, 12)` BW | `default` (no source) |
| COM offset (torso) | `N(0, 0.01)` m per axis | `default` |

---

## 3. Template `drone` (quadrotor)

Model: free-body X-quad, 4 rotor sites with thrust `F_i = k_T·ω_i²` and reaction torque `τ_i = ±k_Q·ω_i²` (implemented as `<general>` actuators with `gear` thrust + yaw-torque columns, first-order motor lag in Python), battery mass as body. CMA-ES variables: (for "can it do X") gain set of hover/maneuver controller or trajectory-feasibility parameters (4–10 dims). Many drone items are closed-form **N** checks; MuJoCo rollouts provide **S**.

### 3.1 Judgment items

| # | Item | Formula / MuJoCo call | Type | Threshold & source | Label |
|---|------|----------------------|------|--------------------|-------|
| D1 | **Thrust-to-weight** | `TWR = T_max_total/(m_total g)`, `T_max_total = Σ_i k_T ω_max,i²` (or datasheet static thrust × derate) | **N**: `TWR<1` ⇒ cannot hover. | `TWR≥1` physics. Control-authority target `TWR≥2` for agile flight = `default` (rule of thumb, `unverified`) | — |
| D2 | **Hover thrust margin** | `h = mg / T_max_total` (hover throttle fraction); margin `1−h`; with one-motor-out: `h_oo = mg/(T_max_total − T_max,i)` (lower bound; asymmetric thrust also needs yaw/roll balance — see D4) | **N**: `h>1` ⇒ impossible. **S**: rollout hovers 10 s with `max_i throttle_i ≤ 0.9`. | `0.9` throttle ceiling for control headroom = `default` | — |
| D3 | **Max payload** | `m_pl,max = T_max_total/(g·TWR_req) − m_empty` where `TWR_req=1` (necessary bound, "absolute hover payload") and `TWR_req=default 2` ("usable payload"). Verify by bisection: add mass in MuJoCo, run hover rollout + step-disturbance, largest mass with success | `TWR_req=1` bound is **N**; bisection result is **S** | `TWR_req` = `default` | — |
| D4 | **Yaw authority** | Rotor thrust `F_i=k_T ω_i²`, reaction torque `τ_i=±k_Q ω_i²` (sign by spin direction). Max yaw torque: LP `max τ_z = Σ s_i (k_Q/k_T) F_i` s.t. `Σ F_i = m g` (hover), `0 ≤ F_i ≤ F_max`, roll/pitch trim moments = 0 (`scipy.optimize.linprog`, 4 vars). Required: `α_req = ψ̇*/t*` (user rate and time), `τ_req = I_zz·α_req`. Ratio `Ψ = τ_z,max/τ_req` | **N**: `Ψ<1` ⇒ impossible. **S**: rollout achieves the yaw step | Spec-driven; `k_Q/k_T` = `default` | SIMPLIFIED (ignores motor lag, rotor drag) |
| D5 | **Battery endurance (hover)** | Momentum theory: `P_ideal = (mg)^{3/2}/√(2ρ_air A_tot)`, `P_elec = P_ideal/(FM·η_motor·η_ESC) + P_avionics`; `E = e_pack·m_batt·DoD`; `t_hover = E/P_elec`. Cross-check in sim by integrating the thrust-to-power model | **N for hover-duration missions only**: `t_hover < t_required` ⇒ impossible. Forward flight can need less power than hover, so for cruise/range missions endurance is an **estimate**, not an N-check | `e_pack`: NASA workshop slide gives *current pack-level capability 150–170 Wh/kg*: [NTRS 20180001539](https://ntrs.nasa.gov/api/citations/20180001539/downloads/20180001539.pdf) (2017 aerospace-grade; hobby LiPo may differ → `default` `N(180,25)`, `unverified`). `FM≈0.6–0.7`, `η_motor·η_ESC≈0.8`: `default` | SIMPLIFIED (momentum theory; ignores voltage sag, Peukert, temperature) |
| D6 | **Max attitude acceleration / tilt authority** | `α_roll,max = (T_max_arm·L_arm)/I_xx` (two rotors max, two idle-limited by `mg` balance); tilt for horizontal accel `a_x ≤ g·tan(θ_max)`, `θ_max = acos(1/TWR)` | **N** for aggressive maneuvers: required `a_req > g·√(TWR²−1)` ⇒ impossible | Physics | SIMPLIFIED |
| D7 | **Maneuver feasibility (rollout)** | MuJoCo rollout with disturbance (wind gust force on `xfrc_applied`), motor lag; success = trajectory tracked within `e_max`, no motor saturating >0.5 s, battery SoC > `SoC_min` at end | **S** | `e_max`, `SoC_min=0.2` = `default` | SIMPLIFIED |
| D8 | **COM / inertia sensitivity** | As R7 on `m_pl`, COM offset (payload off-center ⇒ steady torque `m_pl g δ` must be ≤ `τ_roll,max` available at hover), `I_xx` | **N** subcheck: `m_pl·g·δ > τ_hover_trim_max` ⇒ impossible | — | — |

### 3.2 Editable assumptions (drone)

| Parameter | Default distribution | Status / source |
|-----------|---------------------|-----------------|
| Empty mass (frame+motors+avionics) | user/BOM | user spec |
| Payload mass | user | user spec |
| Static thrust per motor/prop | datasheet value ×`U(0.9,1.0)` (derate) | `default` |
| `k_Q/k_T` ratio (yaw torque per thrust) | `N(0.016, 0.004)` m | `default`/`unverified` |
| Battery specific energy `e_pack` | `N(180, 25)` Wh/kg (see D5) | `unverified` |
| Usable depth of discharge DoD | `U(0.75, 0.9)` | `default` |
| Figure of merit FM | `U(0.55, 0.72)` | `default` |
| η_motor·η_ESC | `N(0.80, 0.04)` | `default` |
| Air density ρ | `N(1.20, 0.05)` kg/m³ (sea level 20 °C) | `default` |
| Wind gust | `U(0, 6)` m/s | `default` |
| Motor time constant | `U(0.03, 0.08)` s | `default` |
| Control-authority TWR target | `2.0` fixed (editable) | `default` |

---

## A. Failure taxonomy and user-facing sentence templates

Each failed or rejected run is assigned **exactly one primary** `failure_class` (the first that applies in the priority order listed) and optional secondary classes. `{…}` placeholders are filled from tool output only.

| Code | Trigger (machine rule) | Strength | Sentence template |
|------|-----------------------|----------|-------------------|
| `MODEL_INVALID` | MJCF compile error, NaN/Inf in rollout, unstable `mj_step` (qacc blow-up), mass or inertia violating physical consistency, energy increases >{x}% with no actuator input | none (no verdict) | "The simulation model was not valid ({reason}), so no feasibility verdict is given. This is a tooling problem, not a physical finding." |
| `ENERGY_BUDGET` | R4 / R9 / D5 / H3-power: required energy, propellant, or peak power exceeds available at favorable assumption bounds | **strong impossible** | "Not possible with the stated assumptions: the maneuver needs {required} {unit} but at most {available} {unit} is available, even at the favorable end of the assumptions ({assump_list}). Shortfall factor {ratio}×." |
| `ACTUATOR_SATURATION` | H1/H3 `ρ>1` over whole range at favorable bounds; R2/R3/D4/D6 authority shortfall | **strong impossible** | "Not possible with the stated hardware: at {pose/phase}, joint/thruster {name} would need {req} {unit} but its limit is {lim} {unit} ({ρ}× over), even at the favorable end of the assumptions." |
| `CONTACT_LOSS` | Required friction `μ_req>μ` at favorable μ (H9); wheel/foot lifts with no recovery; takeoff slip | strong if from N-check; else weak | N-check: "The required traction ratio {μ_req} exceeds the available friction {μ_max} on this surface." Rollout: "In the searched controllers the contact was lost at {phase}; this is not proof that no controller can hold contact." |
| `TIPPING` | H6 violated at final state (ZMP/COM outside support polygon, fall, rollover) in all top-K controllers | weak (search outcome) unless caused by N-check | "All {K} best controllers tipped over after landing (ZMP margin {m} m). A different landing strategy or wider support may still work; this was not found in {N_evals} evaluations." |
| `STRUCTURAL_UNMODELED` | Peak landing/impact load (R5, H5, thruster/mount loads) exceeds `default` structural limit, **or** the idea depends on strength of parts we do not model | **flag, not verdict** (structure not judged) | "The motion is dynamically feasible, but peak load {value} {unit} exceeds the assumed structural limit of {limit} {unit}. Structure was not analyzed (no FEA) — simplified model, needs precise validation." |
| `OCCUPANT_LIMIT` | R6 fails: duration-aware G exceeds {factor}× Eiband curve at favorable bounds | **strong** if N pre-check; weak if rollout-only | "The landing would impose {G} g for {Δ} s on occupants, above the {limit} g tolerance bound from [Eiband 1959]. Even with {s_stroke} m of stroke the minimum is {G_min} g." |
| `SEARCH_BUDGET_EXHAUSTED` | No N-check violated, no success in `N_evals` | **weak** | "No solution was found in {N_evals} simulations (budget {B}, {k} CMA-ES restarts), and no necessary condition was violated. This is **weak** evidence of infeasibility, not proof; a larger search or different control strategy might succeed." |
| `ASSUMPTION_FRAGILE` | Success only in `p<0.5` of MC samples; or ±1σ in one assumption flips PASS→FAIL (R7/H7) | strong-ish (qualified) | "A solution exists but only works in {p}% of the assumption range ({CI}); the outcome is dominated by {param} (sensitivity {S})." |
| `UNSUPPORTED_PHYSICS` | Idea requires effects we do not judge (aero, thermal, FEA — Section C) | none | "This part of the idea depends on {effect}, which this tool does not simulate. Result applies to rigid-body dynamics only — simplified model, needs precise validation." |

Priority: `MODEL_INVALID` > `UNSUPPORTED_PHYSICS` > `ENERGY_BUDGET` > `ACTUATOR_SATURATION` > `CONTACT_LOSS` (N-check) > `OCCUPANT_LIMIT` (N) > `STRUCTURAL_UNMODELED` > `TIPPING` > `ASSUMPTION_FRAGILE` > `SEARCH_BUDGET_EXHAUSTED`.

**Binding constraint** = the item with the smallest margin among passing items (S outcome) or the violated N item with the largest shortfall factor (impossible outcome); for weak outcomes, the item with highest time-at-limit in the best controller (H4 / thruster duty).

---

## B. Verdict-wording rules

Verdict object: `{class, strength, p_feasible, ci95, binding_constraint, failure_class, n_evals, n_mc, seed, assumptions_hash}`.

| Rule | Text |
|------|------|
| **R1 Found ⇒ strong** | `class=FEASIBLE`, allowed phrases: "A controller/design achieving this exists *within the stated assumptions*", "proved by simulation under assumptions". Always attach `assumptions_hash` and list which assumptions were `default`/`unverified`. Never: "will work", "safe", "certified". |
| **R2 Probability** | `p_feasible` = fraction of Monte-Carlo samples (n_mc draws from the assumptions panel; each sample re-checked with the *found* controller, or re-optimized if budget allows) where all S-items pass; report 95 % Wilson interval. Wording: "feasible in {p}% of sampled assumption sets (95% CI {lo}–{hi}%, n={n_mc})". Never report a probability without n and CI. |
| **R3 N violated ⇒ strong impossible** | Allowed only if violation holds at the **favorable bound** (5th/95th percentile in the helpful direction) of every assumption involved. Text: "Impossible within the stated assumptions: {sentence from taxonomy}". If violated at nominal but passes at the favorable bound ⇒ downgrade to `UNLIKELY`, list the assumption that would have to change ("would require {param} ≥ {value}"). |
| **R4 Not found ⇒ weak** | No N violated and no S success ⇒ `class=NOT_FOUND` ⇒ MUST use the words "not found", "weak evidence", "in {N} evaluations"; MUST NOT use "impossible", "cannot", "infeasible". |
| **R5 Suggested fix** | Only from optimizer: re-run search with one design variable relaxed (e.g. thrust ×k, payload −Δm, joint torque ×k, stroke +Δs); report the smallest change that flips to FEASIBLE ("found by search, N evals; not unique"). The LLM may not propose numeric fixes. |
| **R6 Determinism** | Same `(spec_json, seed)` ⇒ same verdict and same number strings. Seed derivation `seed = int(sha256(canonical_json(spec))[:8],16)`. |
| **R7 Labels** | Every report section containing a SIMPLIFIED item prints: **"simplified model, needs precise validation"**. Every number from a `default`/`unverified` assumption is tagged "assumed". |
| **R8 Human review** | Before and after run: assumptions panel shows each parameter's value, distribution, status (`sourced/default/unverified`) with link; verdict shows "based on the above, as edited by {user}". |
| **R9 Mixed outcomes** | If N-checks pass, S found in some samples: `FEASIBLE_FRAGILE` when `p<0.5`, `FEASIBLE` otherwise (threshold `0.5`, `0.9` for "robust" — `default`). |

Verdict classes: `FEASIBLE` (strong), `FEASIBLE_FRAGILE` (strong+qualified), `IMPOSSIBLE` (strong, N), `UNLIKELY` (N violated at nominal only), `NOT_FOUND` (weak), `NO_VERDICT` (MODEL_INVALID / UNSUPPORTED).

---

## C. Explicitly NOT judged

| Domain | What we do not do | Uncertainty label text (verbatim, shown beside any related claim) |
|--------|------------------|-----------------------------------------------------------------|
| CFD / aerodynamics | Drag, lift, downforce, ground effect, rotor wake/inflow, propulsive plume, wind loading. Only constant `Cd·A` or momentum-theory estimates, where stated | **"Aerodynamics not simulated (simplified drag/momentum model only) — simplified model, needs precise validation."** |
| Thermal | Battery/motor/ESC heating, derating, nozzle cooling from gas expansion, brake fade | **"Thermal effects not modeled — simplified model, needs precise validation."** |
| FEA / structure | Stress, fatigue, buckling, crash energy absorption, mounting loads, bone/injury biomechanics beyond Eiband curve | **"Structural strength not analyzed (no FEA) — simplified model, needs precise validation."** |
| Control hardware | Sensor noise, latency, state estimation, fault tolerance (beyond motor lag) | **"Perfect state feedback assumed; real sensing/latency not modeled — simplified model, needs precise validation."** |
| Combustion / pressure vessel | Real rocket motor performance, tank burst, certification | **"Propulsion modeled as ideal constant-Isp thrust — simplified model, needs precise validation."** |
| Safety/regulatory | Legality, human-rating, certification | **"No safety or regulatory assessment is made."** |
| Economics | Production cost beyond BOM lookup | **"Costs are estimates, see cost_estimate methodology."** |

---

## D. Real-world cost references (cite-able)

Only figures I could open and read are listed as `sourced`; all else `unverified`. These are order-of-magnitude anchors, not quotes.

| Item | Figure | Source | Status |
|------|--------|--------|--------|
| Wind tunnel test, full-scale subsonic (NASA Ames 80×120 ft) | ≈ $1,000 / hour "estimated test cost" | [NASA Glenn education slide "Types of Wind Tunnels"](https://www.grc.nasa.gov/WWW/k-12/WindTunnel/WTExpKids/tsld032.htm) | `sourced` (educational slide, old; hourly facility rate only, excludes model build, staff, data reduction) |
| Wind tunnel test, full-scale supersonic (NASA Glenn 10×10 ft) | ≈ $2,000 / hour "estimated test cost" | same slide | `sourced` (same caveat) |
| Rocket test stand construction (reference scale) | A-3 test stand (J-2X) completed 2013 at $349 M; B-2 refurbishment for SLS core stage 2017 at $230 M; leases: A-3 to Rocket Lab ≈ $3.4 M, A-2 + 30 acres to Relativity ≈ $2.7 M (7 years) | [NASA OIG IG-24-018, Rocket Propulsion Test Program](https://oig.nasa.gov/wp-content/uploads/2024/09/ig-24-018.pdf) | `sourced` (capital/lease, **not** per-test cost) |
| NASA Rocket Propulsion Test program annual budget | ≈ $46–48 M/yr (flat, projected $48.6 M through FY2029) | same OIG report | `sourced` (portfolio budget, not per-test) |
| Rocket engine hot-fire / static-fire cost per test | — | no primary source found in our search | **`unverified` — do not print a number** |
| Hardware prototype respin (mid-complexity embedded board) | $30 k–$80 k per spin incl. engineering time, fab/assembly $3–8 k, 1–3 weeks bring-up, schedule impact | [Octavo Systems, "The Real Cost of a Board Spin"](https://octavosystems.com/the-real-cost-of-a-board-spin) (vendor blog, a SiP vendor with commercial interest) | `sourced` as a vendor claim; treat as `unverified` for general use |
| Small-team 4-layer PCB respin (illustrative) | ≈ $3.5–6 k fully loaded; one example model $4,750 | [IDO / IntelCAD insight](https://idostudio.ai/insight/2026-10-07-calculating-the-true-cost-of-a-hardware-respin) (vendor blog, explicitly "illustrative composite") | `sourced` as illustrative, not measured |
| Eiband human tolerance (not a cost) | see R6 | [NTRS 19980228043](https://ntrs.nasa.gov/api/citations/19980228043/downloads/19980228043.pdf) | `sourced` |

Not found / not cited: wind tunnel for small automotive tunnel rates, drone flight-test day rate, humanoid robot prototype cost → `unverified` (omit unless a source is added).

---

## E. `cost_estimate` methodology

Purpose: show "what would the physical equivalent of this verdict have cost" next to the simulation cost, always as an **estimate**.

```
cost_estimate = {
  "sim": {
     "wallclock_s": measured,               # time.perf_counter
     "n_evals": int, "n_mc": int,
     "cpu_core_hours": wallclock_s*cores/3600,
     "usd": cpu_core_hours * rate_usd_per_core_hour   # rate = default 0.05 (unverified), editable
  },
  "physical_equiv": {
     "items": [{"name","qty","unit_usd_low","unit_usd_high","source_url|null","status"}],
     "usd_low": Σ qty*unit_low, "usd_high": Σ qty*unit_high,
     "label": "ESTIMATE — order of magnitude, not a quote"
  },
  "ratio_low/high": physical/sim
}
```

Rules:
1. **Mapping, not invention.** Each judgment item maps to a physical test it replaces: aero → wind-tunnel hours; thruster/propellant → static-fire tests; structure → prototype build/respin; drop/landing → drop-test rig runs. Counts (`qty`) = `ceil(n_distinct_conditions_evaluated / conditions_per_physical_test)` with `conditions_per_physical_test` default per template (`default`, editable); it is the number of physical tests a human would plausibly run to cover the same evidence, **not** the number of simulation rollouts.
2. **Unit costs** only from Section D with `status=sourced`; any item without a sourced figure carries `unit_usd_* = null` and is excluded from the total with a visible "not priced" line (never silently zero, never guessed).
3. **Range, not point.** Report low–high; use sourced low/high if both exist, else ×[0.5, 2] around a single sourced point and mark "range assumed".
4. **Sim cost** is measured, not estimated; only the rate per core-hour is assumed (unverified until the user sets it).
5. **Excludes** facility setup, safety/regulatory, and schedule delay unless a sourced figure covers it (the respin sources above do include engineering time; say so).
6. **Wording:** "Estimated physical-equivalent cost: $X–$Y (estimate; based on {sources}; items not priced: {list}). The simulation used {cpu_core_hours} core-hours (≈${sim_usd}). This is a rough comparison, not a quote and not a claim that simulation replaces physical testing."
7. Do not compute ROI claims ("saved $N") — only "estimated physical-equivalent".

---

## F. Output checklist per run (what the report must contain)

1. Verdict class + strength + one-sentence (Section B) + `p_feasible` with CI and n.
2. Table of items: id, value, limit, margin, type (N/S), pass/fail, status of constants.
3. Binding constraint; failure_class sentence (Section A) if not FEASIBLE.
4. Necessary-condition panel (R2/R3/R4, H1/H2/H3/H5, D1/D2/D4/D5) — shown even when feasible (margins).
5. Suggested fix (optimizer-found, with eval count) or "none found in N evals (weak)".
6. Assumptions panel snapshot + hash + seeds; SIMPLIFIED labels (Section C); `cost_estimate` (Section E).
