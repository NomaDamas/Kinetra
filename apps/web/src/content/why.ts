// Typed copy for the Home page (#/). Source of truth for the argument: docs/why-kinetra.md.
// Rule: every number here is either read from a source we opened (sourceUrl) or flagged in `caveat`.
// No number about Kinetra's own results lives here; the Home page reads those from the recorded bundles.

export interface Bilingual {
  en: string;
  ko: string;
}

export interface ProblemPoint {
  /** One plain sentence; the number is shown separately as `value`. */
  text: string;
  /** Headline figure exactly as the source states it. */
  value: string;
  sourceLabel: string;
  sourceUrl: string;
  /** Mandatory honesty note: what this number is NOT (vendor claim, old slide, PCB-only, ...). */
  caveat: string;
}

export interface Persona {
  id: string;
  who: string;
  /** The exact decision this person has to make before spending money. */
  decision: string;
  /** What they put into Kinetra. */
  input: string;
  /** What they walk away with. */
  output: string;
}

export interface Step {
  title: string;
  body: string;
}

export interface Cta {
  label: string;
  /** Hash route. */
  href: string;
  kind: 'primary' | 'secondary';
}

export interface VerdictRule {
  status: string;
  meaning: string;
  strength: string;
}

export interface WhyContent {
  oneLiner: Bilingual;
  subLine: Bilingual;
  problemTitle: string;
  problemIntro: string;
  problem: ProblemPoint[];
  personasTitle: string;
  personas: Persona[];
  whatYouGetTitle: string;
  whatYouGet: Step[];
  howItWorksTitle: string;
  howItWorks: Step[];
  /** Verdict asymmetry, worded as in docs/judgment-spec.md section B. */
  verdictRules: VerdictRule[];
  notClaimsTitle: string;
  notClaims: string[];
  ctas: Cta[];
  /** Link to the long-form argument in the repo. */
  readMoreUrl: string;
}

export const WHY: WhyContent = {
  oneLiner: {
    en: 'Before you build hardware, know if it can work, what breaks first, and what to build.',
    ko: '하드웨어를 만들기 전에, 되는지, 무엇이 먼저 깨지는지, 무엇을 만들어야 하는지 압니다.',
  },
  subLine: {
    en: 'Describe a physical idea in one sentence. Kinetra checks it against physics, sizes the parts, draws the custom ones, and hands you a design brief with a verdict, a BOM and the first physical test to run.',
    ko: '물리 아이디어를 한 문장으로 적으면, 물리 법칙으로 검증하고, 부품 사양을 정하고, 맞춤 부품은 CAD로 그리고, 판정 · BOM · 먼저 해볼 물리 시험이 담긴 설계 브리프를 돌려줍니다.',
  },

  problemTitle: 'The expensive moment is finding out too late',
  problemIntro:
    'Most of a hardware project\u2019s cost is decided at concept stage, and the failure usually shows up at the first prototype. These are the figures we could open and read; each carries its caveat.',
  problem: [
    {
      text: 'During design only about 15% of life-cycle cost is spent, but the design commits about 75% of it. Fixing problems found late costs considerably more.',
      value: '15% spent / 75% committed',
      sourceLabel: 'NASA Systems Engineering Handbook, section 2.5',
      sourceUrl: 'https://www.nasa.gov/reference/2-5-cost-effectiveness-considerations',
      caveat:
        'NASA states these are example figures from a Defense Acquisition University chart and vary by project. The shape of the curve is the point, not the exact percentages.',
    },
    {
      text: 'Typical board project: 2.9 respins at $44,000 each, with 8.5 days of schedule impact per respin.',
      value: '2.9 respins x $44,000',
      sourceLabel: 'Lifecycle Insights (Sept 2018) as quoted in Design World, "Modern practices in PCB design verification"',
      sourceUrl: 'https://www.designworldonline.com/modern-practices-in-pcb-design-verification',
      caveat:
        'Electronics (PCB) only, 2018. The article is by Mentor Graphics (a Siemens business), a PCB-verification vendor, and we did not see the Lifecycle Insights dataset itself. Mechanical and robotic prototypes are not covered.',
    },
    {
      text: 'A mid-complexity embedded board spin costs $30k to $80k including engineering time, plus 1 to 3 weeks of bring-up.',
      value: '$30k to $80k per spin',
      sourceLabel: 'Octavo Systems, "The Real Cost of a Board Spin"',
      sourceUrl: 'https://octavosystems.com/the-real-cost-of-a-board-spin',
      caveat: 'Vendor claim from a company with a commercial interest; treat as an order of magnitude, not a benchmark.',
    },
    {
      text: 'Renting a full-scale subsonic wind tunnel is about $1,000 per hour; supersonic about $2,000 per hour.',
      value: '$1,000 per hour',
      sourceLabel: 'NASA Glenn education slide, "Types of Wind Tunnels"',
      sourceUrl: 'https://www.grc.nasa.gov/WWW/k-12/WindTunnel/WTExpKids/tsld032.htm',
      caveat:
        'Old educational slide; facility hourly rate only, excludes model build, staff and data reduction. Kinetra does not simulate aerodynamics.',
    },
  ],

  personasTitle: 'Who it is for',
  personas: [
    {
      id: 'founder',
      who: 'Hardware founder at concept stage',
      decision: 'Do I spend the first prototype budget on this spec, or change the spec first?',
      input: 'The product claim in one sentence ("a car that flips 360 degrees on thrusters") plus the parts I am considering.',
      output: 'A verdict, the constraint that binds first, sized components and the cheapest physical test that would confirm it.',
    },
    {
      id: 'rnd',
      who: 'Robotics R&D lead',
      decision: 'Which actuator, gearbox or battery do I order for the next platform, and will it carry the task?',
      input: 'Mass, torque and speed limits, and the motion the platform must achieve.',
      output:
        'Requirements derived from a simulated witness run, matched to catalog parts with margins, with the parts that need sourcing flagged.',
    },
    {
      id: 'maker',
      who: 'Maker or small team without a test rig',
      decision: 'Will this build work at all, and which part should I buy so it does?',
      input: 'A rough idea and whatever specs I already know.',
      output: 'A plain answer first, an optimizer-found fix, and a BOM I can order from, with unpriced lines marked as unpriced.',
    },
  ],

  whatYouGetTitle: 'What you get: a design brief, not a simulation',
  whatYouGet: [
    {
      title: 'Verdict',
      body: 'Feasible, impossible under stated assumptions, or not found in budget, with the strength of that evidence written next to it.',
    },
    { title: 'What breaks first', body: 'The binding constraint with its margin, so you know which number to attack.' },
    {
      title: 'Sized components',
      body: 'Requirements derived from the witness run, matched to cited catalog parts, or flagged as custom or needs sourcing.',
    },
    {
      title: 'Custom parts with CAD',
      body: 'Parametric geometry with a simple load check (labelled "simplified model, needs FEA"), downloadable as STL and STEP.',
    },
    {
      title: 'Closed loop',
      body: 'The designed hardware\u2019s mass goes back into the model and the verdict is re-run until it converges.',
    },
    { title: 'BOM and next physical test', body: 'bom.csv with only cited prices summed, and the first physical test worth running.' },
  ],

  howItWorksTitle: 'How it works',
  howItWorks: [
    { title: 'Idea', body: 'One sentence, matched to a verified template (rocket car and humanoid jump today).' },
    {
      title: 'Assumptions',
      body: 'Every parameter shows value, distribution, source and confidence. You review them before anything runs.',
    },
    {
      title: 'Necessary-condition screen',
      body: 'Cheap analytic checks (energy, torque, impulse) that can prove "impossible" at the favorable end of the assumptions.',
    },
    {
      title: 'Search and Monte-Carlo',
      body: 'CMA-ES searches a control schedule in MuJoCo; the winner is re-run over the uncertain assumptions for p_success with a 95% interval.',
    },
    { title: 'Design', body: 'Requirements, components, custom parts and the mass-feedback loop, all through the same verdict machinery.' },
    { title: 'Brief', body: 'design-brief.md, bom.csv and CAD files you can hand to an engineer.' },
  ],

  verdictRules: [
    {
      status: 'FEASIBLE_FOUND',
      meaning: 'A design that works exists under the stated assumptions. Reliability is the separate p_success with its interval.',
      strength: 'Strong existence evidence',
    },
    {
      status: 'INFEASIBLE_NECESSARY_CONDITION',
      meaning: 'A necessary condition fails even at the favorable end of the assumptions.',
      strength: 'Strong: impossible under these assumptions',
    },
    {
      status: 'NOT_FOUND_IN_BUDGET',
      meaning: 'The search found nothing in N evaluations and no necessary condition was violated.',
      strength: 'Weak: not a proof',
    },
  ],

  notClaimsTitle: 'What we do not claim',
  notClaims: [
    'Accuracy against reality is unvalidated: no real hardware data has been used. Every result is "simplified model, needs precise validation".',
    'Willingness to pay is unvalidated. There are no customers, revenue or traction.',
    'Only two verified templates exist (rocket car, humanoid jump). Other kinds of ideas are not supported yet.',
    'CFD, thermal and FEA are not judged. Part checks are hand calculations labelled "needs FEA".',
    'Costs are summed only from cited prices; everything else is shown as unpriced, never as zero.',
    'A brief is a verified starting point for a physical test campaign, not a replacement for one.',
  ],

  ctas: [
    { label: 'Open the dashboard', href: '#/projects', kind: 'primary' },
    { label: 'See an example design brief', href: '#/p/roadster/report', kind: 'secondary' },
  ],
  readMoreUrl: 'https://github.com/NomaDamas/Kinetra/blob/main/docs/why-kinetra.md',
};
