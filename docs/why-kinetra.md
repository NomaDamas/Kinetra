# Why Kinetra exists

> **Before you build hardware, know if it can work, what breaks first, and what to build.**
>
> 하드웨어를 만들기 전에, 되는지 · 무엇이 먼저 깨지는지 · 무엇을 만들어야 하는지 압니다.

The output is a verified **design brief**, not a pretty simulation: verdict + what limits you + sized components + custom parts with CAD + BOM + risks + the next physical test.

Status of every claim below: a number has a link, or it says *unsourced*. Statements about Kinetra's own behaviour are measured in this repo (see README, "Measured results"). Anything we could not verify is marked `[INFERENCE]` or `unvalidated`.

---

## 1. The expensive moment: finding out too late

Most of a hardware project's cost is decided at concept stage; the failure usually surfaces at the first prototype or the first test campaign.

| Figure | Source | What it is *not* |
|---|---|---|
| During design only about **15 %** of life-cycle cost is spent, but the design **commits about 75 %** of it; late fixes cost considerably more. | [NASA Systems Engineering Handbook §2.5, Fig. 2.5-1](https://www.nasa.gov/reference/2-5-cost-effectiveness-considerations) (chart from Defense Acquisition University) | NASA says the numbers "will vary from project to project"; the shape of the curve is the point. Programme-scale (not a startup prototype). |
| Typical PCB project: **2.9 respins**, **$44,000 per respin**, **8.5 days** schedule hit per respin. | Lifecycle Insights (Sept 2018) as quoted in [Design World, "Modern practices in PCB design verification"](https://www.designworldonline.com/modern-practices-in-pcb-design-verification) (we opened this page and the quote is there; we did not see the Lifecycle Insights dataset). Repeated in [Cadstrom, "The True Price of PCB Reworks"](https://www.cadstrom.io/resources/the-true-price-of-pcb-reworks). | The article was written by a PCB-verification vendor (Mentor/Siemens) and the second by another vendor (Cadstrom). Electronics only, 2018. |
| Mid-complexity embedded board spin: **$30 k to $80 k** including engineering time; fab/assembly $3 to 8 k; 1 to 3 weeks of bring-up. | [Octavo Systems, "The Real Cost of a Board Spin"](https://octavosystems.com/the-real-cost-of-a-board-spin) | Vendor blog with a commercial interest. Order of magnitude only. |
| Full-scale subsonic wind-tunnel time: about **$1,000 per hour** (NASA Ames 80x120 ft); supersonic (Glenn 10x10 ft) about $2,000 per hour. | [NASA Glenn education slide, "Types of Wind Tunnels"](https://www.grc.nasa.gov/WWW/k-12/WindTunnel/WTExpKids/tsld032.htm) | Old educational slide; facility hourly rate only (no model build, staff or data reduction). Kinetra does **not** simulate aerodynamics. |
| Test-stand scale: A-3 test stand (J-2X) completed 2013 at **$349 M**; Rocket Lab leases A-3 for about $3.4 M. | [NASA OIG IG-24-018](https://oig.nasa.gov/wp-content/uploads/2024/09/ig-24-018.pdf) | Capital and lease, not per-test cost. |
| Typical hardware product goes through **3 to 8 prototype loops**; a prototype loop costs a startup **$50 k to $250 k**; each loop raises prototype cost 15 to 40 %. | [Cratus Technology, "Why 80% of hardware projects fail in prototyping"](https://www.cratustech.com/why-hardware-projects-fail-in-prototyping) | A contract-engineering firm's marketing article citing "industry veterans" with no primary data. **Treat as unsourced colour**, not as a benchmark. We only list it because it is the only prototype-loop cost range we found for products broader than PCBs. |

What we could **not** source, and therefore do not print anywhere: rocket-engine hot-fire cost per test, drone flight-test day rate, humanoid prototype cost, mechanical-prototype respin cost outside PCBs.

The honest summary: the *direction* (late discovery costs more, and prototypes are rarely right the first time) is well supported. The *size* of the saving for a given customer is **unvalidated**; the interviews in section 7 exist to find out.

## 2. Who it is for

Three concrete people, each with one decision.

| Persona | The decision they face | What they give Kinetra | What they leave with |
|---|---|---|---|
| **Hardware founder at concept stage** (pre-seed/seed, spec exists, no prototype yet) | "Do I spend the first prototype budget on this spec, or change the spec first?" | The product claim in one sentence + parts under consideration | Verdict, binding constraint, sized components, cheapest physical test that would confirm it. A page they can show a co-founder or investor. |
| **Robotics R&D lead** (platform exists, next generation being specified) | "Which actuator, gearbox or battery do I order, and will it carry the task?" | Mass, torque/speed limits, the motion to achieve | Requirements derived from a simulated witness run (with margin), matched to cited catalog parts; custom/needs-sourcing parts flagged. |
| **Maker / small team without a test rig** | "Will this build work at all, and which part should I buy so it does?" | A rough idea and the specs they know | Plain answer first, an optimizer-found fix, a BOM with unpriced lines marked unpriced. |

These personas are hypotheses; none has been interviewed yet (section 7).

## 3. What you get: the design brief

One document per idea (`design-brief.md`, plus `bom.csv` and CAD files):

1. **Verdict**, with strength: `FEASIBLE_FOUND` (strong existence), `INFEASIBLE_NECESSARY_CONDITION` (strong: impossible under stated assumptions), `NOT_FOUND_IN_BUDGET` (weak; not a proof). `p_success` is always reported with n and a 95 % interval.
2. **What breaks first**: the binding constraint and its margin.
3. **Sized components**: requirements read from a real rollout of the witness design, times a margin factor, matched to cited catalog entries. If nothing meets a requirement the line becomes *custom* or *needs sourcing*; we never invent a vendor part.
4. **Custom parts with CAD**: parametric geometry, a simple load check labelled "simplified model, needs FEA", STL for preview, STEP for engineers.
5. **Closed loop**: the designed hardware's mass is put back into the model and the verdict is re-run until the mass converges. A design that is "feasible" only before its own hardware weight is added is caught here.
6. **BOM and risks**: only cited prices are summed; unpriced lines are counted, never treated as zero.
7. **Next physical test**: the cheapest real test that would confirm or kill the weakest assumption.

Contract: [`docs/design-stage.md`](design-stage.md). Verdict wording rules: [`docs/judgment-spec.md`](judgment-spec.md) §B.

## 4. Why existing tools do not cover it

None of these is a bad product; they answer different questions. Descriptions are from each vendor's own pages; we have not used all of them.

| Tool | What it is | The gap Kinetra targets |
|---|---|---|
| **Luminary Cloud** ([luminary.ai](https://luminary.ai/platform)) | Cloud simulation / "Physics AI" platform, CFD and multi-physics for engineering teams. | Built for people who already have a detailed model and a simulation question. Kinetra starts from a sentence, and is rigid-body only. |
| **SimScale** ([simscale.com](https://www.simscale.com/docs/cad-preparation)) | Cloud simulation platform where you prepare and upload a CAD model, then set up the simulation. | Needs CAD first. Kinetra asks "should this CAD exist, and which parts?" |
| **Zoo** ([zoo.dev](https://zoo.dev/design-studio)) | CAD platform with a conversational CAD agent (text to geometry). | Makes geometry. Does not say whether the mechanism achieves the task. Different layer; we make no comparison claim. |
| **Drift** ([docs.godrift.ai](https://docs.godrift.ai/getting-started/introduction)) | AI copilot that builds, tests and debugs robot simulations (MuJoCo, Isaac, ROS) from prompts. | Builds the simulation. Does not render a verdict with necessary-condition proofs, Monte-Carlo intervals, sized parts or a BOM. |
| **NVIDIA Isaac Sim** ([docs](https://docs.omniverse.nvidia.com/isaacsim/latest)) | Reference application on Omniverse to develop, simulate and test AI-driven robots. | A powerful simulator for a team that already has a robot design. It is not a feasibility screen and has no design-brief output. |
| **A general coding agent + MuJoCo** | Can write a one-off MuJoCo script. | A good engineer can reproduce parts of this. What a one-off script lacks is fixed templates, sourced assumptions panel, necessary-condition screen, verdict wording rules, determinism and a component/BOM step. Whether that matters to a buyer is exactly what the 3-way benchmark (section 7) tests. |

## 5. Why now

- **Physics engines are cheap and fast.** Measured in this repo: the roadster live endpoint runs about 29,000 MuJoCo steps/s (4.5 s of simulated flight in about 39 ms) on a laptop. Thousands of rollouts per idea are affordable; a single physical test is not.
- **Search is cheap.** CMA-ES over 10 to 15 control parameters finds a flip witness in seconds to minutes (spike: 3.4 s / 3,072 rollouts at 5 kN), and the necessary-condition screen proves impossibility in milliseconds.
- **Model access is open.** MuJoCo and the Menagerie robot models (Unitree G1) are open source; the Kinetra catalog and templates build on them.
- **The other side of the trade is not getting cheaper.** Prototype respins and test campaigns are still paid in engineer time, tooling and calendar weeks (section 1). [INFERENCE: we have no trend data for this claim.]

## 6. What we do NOT claim

- **Accuracy against reality is unvalidated.** No real hardware data was used. Every verdict is "simplified model, needs precise validation". Sim-to-real calibration has been shown only on synthetic data.
- **Willingness to pay is unvalidated.** No customer, revenue or traction exists. The business hypothesis (free exploration, paid design briefs for teams with money on the line) is untested.
- **Two verified templates only** (rocket car, humanoid jump). A drone catalog exists but the template is not shipped.
- **Not judged:** CFD/aero, thermal, FEA, sensing/latency, combustion, safety/regulatory ([`judgment-spec.md`](judgment-spec.md) §C). Custom-part checks are hand calculations labelled "needs FEA".
- **A brief does not replace testing.** It decides *which* physical test to run first and with which parts.
- **Fragile results exist and are shown:** after adding its own designed hardware (+81 kg), the roadster's 5 kN design drops from 76.6 % to 54.8 % success (n = 500); the current roadster bundle does not sample per-nozzle thrust error, and with ±10 % thrust noise the 5 kN figure was ~13 %. The humanoid design loses its witness once its actuators' mass is added (`NOT_FOUND_IN_BUDGET`, weak).

## 7. How we would prove it next

### 7.1 Three-way benchmark (planned, **not run**)

Same 10 physical ideas (5 feasible-by-construction, 5 with a planted impossibility such as 0.15x torque), given to three arms:

| Arm | Who/what | Time-boxed |
|---|---|---|
| A | An engineer by hand (spreadsheet + their own tools) | 2 h per idea |
| B | A general coding agent writing a MuJoCo script | 2 h per idea |
| C | Kinetra | Same input sentence |

Scored against a ground truth we construct (planted limits known by design) on: verdict correctness (including never calling a weak result "impossible"), correct binding constraint, parts that actually meet requirements, calibration of stated confidence, and time to a usable answer. Publish all raw results, including losses. If B ties C on correctness, the product is not the verdict; it is only the packaging, and we must say so.

### 7.2 Five design-partner interviews

Targets: 2 hardware founders at concept/pre-prototype, 2 robotics R&D leads, 1 maker/lab. 30 minutes each, no demo until question 6.

1. Tell me about the last time a physical prototype or test failed for a reason you could have predicted. What did it cost in money and weeks?
2. Before building, what did you do to decide it would work? Who did it, how long did it take?
3. What would you have needed to see to cancel or change the spec before building?
4. Which decisions did you make on spec-sheet numbers alone (motor, battery, gearbox)? Which of those turned out wrong?
5. Who signs off the prototype budget, and what evidence do they ask for today?
6. (Show a design brief.) What is missing for you to act on it? What would you not trust, and why?
7. Would you pay for this, and per what: per brief, per seat, per project? What have you paid in the last year for anything that answered a similar question? (Ask about *past* spending, not hypothetical price.)
8. Would you give us one real idea and its real test result so we can compare the brief to what happened?

Success criterion decided in advance: at least 3 of 5 describe a specific, recent, costly late failure **and** agree to supply a real idea plus its outcome. If fewer, the reason to exist is not established and we change the target user, not the slide.

## 8. Lessons from the hackathon (candid)

We lost. There was no judge feedback in this repo, so what follows is our own reading. `[INFERENCE]` throughout.

- **We showed a simulation, not a decision a customer pays for.** The demo was a slider and a 3D replay of a car flipping. Interesting, but the question a buyer asks is "what do I do on Monday?" and the product ended at a verdict. (Numbers in this section are from the hackathon-era bundle.)
- **The best-looking number was weak.** The shipped roadster "fix" was a verified witness with `p_success` 3.6 % (95 % interval shown). We labelled it fragile, which is honest, but a judge sees "the fix works 3.6 % of the time". A verdict without a way forward reads as a failure.
- **Non-monotone results looked like a bug.** `p_success` 5 kN (13.4 %) < 4 kN (46.6 %) is search noise at a small budget. We disclosed it instead of tuning it away; the cost is that it is unexplained on screen.
- **Two templates is a demo, not coverage.** We never said clearly who is allowed to type an idea and what happens when theirs does not match a template.
- **The dashboard and navigation were not organized.** Answer-first structure was missing; jargon (necessary condition, CMA-ES, Wilson CI) came before value.
- **Business claims were absent or weak.** Willingness to pay unvalidated, no interviews, no benchmark.

What changes: the **design brief is the product**. A weak verdict now ends in a recommended action (change a spec, which part to size, which test to run), parts and CAD close the "what to build" gap, the mass-feedback loop turns "feasible" into "feasible with the hardware you would actually add", and the Home page opens with the problem and the answer, not the simulation. The honesty rules stay: they are what makes "impossible" a statement a team can rely on.

## Source list added in this revision

New primary/secondary sources opened for this document (beyond `judgment-spec.md` §D):
- NASA Systems Engineering Handbook §2.5 (cost locked in early): https://www.nasa.gov/reference/2-5-cost-effectiveness-considerations
- Design World, citing Lifecycle Insights 2018 (2.9 respins, $44,000, 8.5 days): https://www.designworldonline.com/modern-practices-in-pcb-design-verification
- Cadstrom, "The True Price of PCB Reworks" (same figures; vendor blog): https://www.cadstrom.io/resources/the-true-price-of-pcb-reworks
- Cratus Technology prototype-loop ranges (vendor marketing, flagged unsourced colour): https://www.cratustech.com/why-hardware-projects-fail-in-prototyping
- Tool descriptions: [Luminary](https://luminary.ai/platform), [Zoo](https://zoo.dev/design-studio), [Drift](https://docs.godrift.ai/getting-started/introduction), [Isaac Sim](https://docs.omniverse.nvidia.com/isaacsim/latest)
