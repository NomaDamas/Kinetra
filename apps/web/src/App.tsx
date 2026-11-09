import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DEMO_BASE,
  IS_FIXTURE,
  engineReachable,
  loadAux,
  loadIndex,
  loadScenario,
  loadTrajectory,
  matchScenario,
  runEngine,
  type DemoIndex,
  type Scenario,
  type ScenarioMeta,
} from './bundle'
import type { Trajectory } from './types'
import { statusMeta } from './util'
import { AgentRun } from './components/AgentRun'
import { Assumptions } from './components/Assumptions'
import { Autoresearch, type ArData, type CalibFile, type ExcitationFile, type IntegrationFile, type LedgerFile } from './components/Autoresearch'
import { Bom } from './components/Bom'
import { FixCallout } from './components/Fix'
import { Replay } from './components/Replay'
import { VerdictCard } from './components/VerdictCard'
import { LivePanel } from './live/LivePanel'

type Tab = 'lab' | 'autoresearch' | 'live'

export default function App() {
  const [index, setIndex] = useState<DemoIndex | null>(null)
  const [indexErr, setIndexErr] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('lab')
  const [prompt, setPrompt] = useState('')
  const [scenario, setScenario] = useState<Scenario | null>(null)
  const [runKey, setRunKey] = useState(0)
  const [running, setRunning] = useState(false)
  const [message, setMessage] = useState<{ kind: 'info' | 'err'; text: string } | null>(null)
  const [vIdx, setVIdx] = useState(0)
  const [traj, setTraj] = useState<Trajectory | null>(null)
  const [trajLoading, setTrajLoading] = useState(false)
  const [cmpTraj, setCmpTraj] = useState<Trajectory | null>(null)
  const [compare, setCompare] = useState(false)
  const [playToken, setPlayToken] = useState(0)
  const [approved, setApproved] = useState<Record<string, boolean>>({})
  const [edits, setEdits] = useState<Record<string, number>>({})
  const [engineUp, setEngineUp] = useState(false)
  const [rerunning, setRerunning] = useState(false)
  const [ar, setAr] = useState<ArData | null>(null)
  const [swap, setSwap] = useState(0)
  // the Live tab stays mounted (hidden) once opened so a running stream / its socket survive tab switches
  const [liveOpened, setLiveOpened] = useState(false)
  const resultsRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadIndex().then(setIndex).catch((e: Error) => setIndexErr(e.message))
    engineReachable().then(setEngineUp)
  }, [])

  useEffect(() => {
    if (!index?.autoresearch) return
    const a = index.autoresearch
    Promise.all([
      loadAux<LedgerFile>(a.attitude_ledger),
      loadAux<CalibFile>(a.calibration),
      loadAux<IntegrationFile>(a.integration),
      loadAux<ExcitationFile>(a.excitation),
    ]).then(([ledger, calibration, integration, excitation]) => setAr({ ledger: normalizeLedger(ledger), calibration, integration, excitation }))
  }, [index])

  // Load trajectories for the selected variant (and the fixed variant for compare).
  const variant = scenario?.variants[vIdx] ?? null
  useEffect(() => {
    if (!scenario || !variant) return
    let live = true
    setTrajLoading(true)
    loadTrajectory(scenario.id, variant)
      .then((t) => live && setTraj(t))
      .catch((e: Error) => live && setMessage({ kind: 'err', text: `Trajectory failed to load: ${e.message}` }))
      .finally(() => live && setTrajLoading(false))
    setSwap((s) => s + 1)
    return () => {
      live = false
    }
  }, [scenario, variant])

  const fixedIdx = useMemo(() => {
    if (!scenario || !variant?.verdict.suggested_fix) return null
    const ch = variant.verdict.suggested_fix.changes.find((c) => c.param === scenario.control.key)
    const feas = scenario.variants.map((v, i) => [v, i] as const).filter(([v]) => v.verdict.status === 'FEASIBLE_FOUND')
    if (ch) {
      let best: number | null = null
      let bd = Infinity
      for (const [v, i] of feas) {
        const d = Math.abs(v.value - ch.to_value)
        if (d < bd) {
          bd = d
          best = i
        }
      }
      if (best !== null) return best
    }
    // fall back to the nearest feasible variant above/below
    return feas.length ? feas.reduce((a, b) => (Math.abs(b[0].value - variant.value) < Math.abs(a[0].value - variant.value) ? b : a))[1] : null
  }, [scenario, variant])

  useEffect(() => {
    if (!compare || !scenario || fixedIdx === null || variant?.verdict.status === 'FEASIBLE_FOUND') {
      setCmpTraj(null)
      return
    }
    let live = true
    loadTrajectory(scenario.id, scenario.variants[fixedIdx]).then((t) => live && setCmpTraj(t)).catch(() => live && setCmpTraj(null))
    return () => {
      live = false
    }
  }, [compare, scenario, fixedIdx, variant])

  const openScenario = useCallback(async (meta: ScenarioMeta) => {
    setMessage(null)
    setRunning(true)
    setTab('lab')
    try {
      const s = await loadScenario(meta.id)
      setApproved({})
      setEdits({})
      setCompare(false)
      setTraj(null)
      setCmpTraj(null)
      setScenario(s)
      setVIdx(s.control.default_index)
      setRunKey((k) => k + 1)
    } catch (e) {
      setRunning(false)
      setMessage({ kind: 'err', text: `Could not load scenario "${meta.id}": ${(e as Error).message}` })
    }
  }, [])

  const submit = useCallback(
    async (text: string) => {
      if (!index) return
      const m = matchScenario(text, index.scenarios)
      if (m) return openScenario(m)
      setScenario(null)
      setMessage(null)
      const up = await engineReachable()
      setEngineUp(up)
      if (!up) {
        setMessage({
          kind: 'info',
          text: 'No recorded scenario matches this idea, and the local engine API is not reachable at http://localhost:8000. This demo does not invent results for unseen ideas. To run it for real: `cd packages/engine && .venv/bin/uvicorn kinetra_engine.api:app --port 8000`, then submit again.',
        })
        return
      }
      setRunning(true)
      try {
        const s = await runEngine(text)
        setApproved({})
        setEdits({})
        setTraj(null)
        setScenario(s)
        setVIdx(s.control?.default_index ?? 0)
        setRunKey((k) => k + 1)
        setMessage({ kind: 'info', text: 'Result from your LOCAL engine API (live run, not a recorded scenario).' })
      } catch (e) {
        setRunning(false)
        setMessage({ kind: 'err', text: `Local engine run failed: ${(e as Error).message}` })
      }
    },
    [index, openScenario],
  )

  const rerun = useCallback(async () => {
    if (!scenario) return
    setRerunning(true)
    try {
      const s = await runEngine(scenario.idea, edits)
      setScenario(s)
      setVIdx(s.control?.default_index ?? 0)
      setEdits({})
      setMessage({ kind: 'info', text: 'Re-ran on the local engine with your edited assumptions.' })
    } catch (e) {
      setMessage({ kind: 'err', text: `Re-run failed: ${(e as Error).message}` })
    } finally {
      setRerunning(false)
    }
  }, [scenario, edits])

  const onRunDone = useCallback(() => {
    setRunning(false)
    window.setTimeout(() => resultsRef.current?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 150)
  }, [])

  const applyFix = () => {
    if (fixedIdx === null) return
    setCompare(false)
    setVIdx(fixedIdx)
    setPlayToken((t) => t + 1)
  }

  const showResults = scenario && !running
  const meta = variant ? statusMeta(variant.verdict) : null

  return (
    <div className="app">
      <header className="top">
        <div className="brand"><span className="logo">K</span><b>Kinetra</b><span className="muted">physical feasibility lab</span></div>
        <nav className="tabs">
          <button className={tab === 'lab' ? 'on' : ''} onClick={() => setTab('lab')}>Feasibility lab</button>
          <button className={tab === 'autoresearch' ? 'on' : ''} onClick={() => setTab('autoresearch')}>Autoresearch</button>
          <button
            className={tab === 'live' ? 'on' : ''}
            onClick={() => {
              setLiveOpened(true)
              setTab('live')
            }}
            data-testid="tab-live"
          >
            <span className="live-dot" /> Live
          </button>
        </nav>
        <div className="top-r">
          {IS_FIXTURE && <span className="pill bad" title="Dev fixtures from spike outputs: NOT real engine bundles">DEV FIXTURES</span>}
          <span className={`pill ${engineUp ? 'ok' : 'muted-pill'}`}>{engineUp ? 'local engine: online' : 'local engine: offline'}</span>
        </div>
      </header>

      {liveOpened && (
        <main className="main" hidden={tab !== 'live'}>
          <LivePanel index={index} onEngineUp={setEngineUp} />
        </main>
      )}

      {tab === 'live' ? null : tab === 'autoresearch' ? (
        <main className="main"><Autoresearch data={ar} /></main>
      ) : (
        <main className="main">
          <section className="hero">
            <div className="eyebrow">Judge = MuJoCo · Actor = Three.js</div>
            <h1>Can your wild physical idea actually work?</h1>
            <p className="sub">
              Type an idea. A tool pipeline researches assumptions, screens necessary conditions, searches, and runs Monte-Carlo in a physics simulator, then tells you how sure it is.
              <span className="kr"> 황당한 물리 아이디어가 가능한지 시뮬레이션으로 판정합니다.</span>
            </p>
            <form
              className="prompt"
              onSubmit={(e) => {
                e.preventDefault()
                void submit(prompt)
              }}
            >
              <textarea
                value={prompt}
                onChange={(e) => setPrompt(e.target.value)}
                placeholder="e.g. A 1.3-tonne roadster flips 360° on rocket thrusters and lands on its wheels"
                rows={2}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    void submit(prompt)
                  }
                }}
              />
              <button className="btn primary big" type="submit" disabled={!index || !prompt.trim() || running}>Judge it</button>
            </form>
            <div className="chips scn">
              {index?.scenarios.map((s) => (
                <button
                  key={s.id}
                  className={`chip scenario ${scenario?.id === s.id ? 'on' : ''}`}
                  onClick={() => {
                    setPrompt(s.idea)
                    void openScenario(s)
                  }}
                  disabled={running}
                  title={s.tagline}
                >
                  <b>{s.title}</b>
                  <span>{s.tagline}</span>
                  <em>{s.tier === 1 ? 'tier 1 · verified template' : 'tier 2 · experimental'}</em>
                </button>
              ))}
              {!index && !indexErr && <span className="muted">loading scenarios…</span>}
            </div>
            {indexErr && (
              <div className="callout bad">
                Demo bundle not found ({indexErr}). Expected <code>{DEMO_BASE}/index.json</code>. Build it with
                <code> packages/engine/scripts/build_*_bundle.py</code>{import.meta.env.DEV && <>, or open this page with <code>?fixtures=1</code> for dev fixtures</>}.
              </div>
            )}
            {message && <div className={`callout ${message.kind === 'err' ? 'bad' : ''}`}>{message.text}</div>}
          </section>

          {scenario && (
            <AgentRun steps={scenario.agent_steps} runKey={runKey} onDone={onRunDone} />
          )}

          {showResults && variant && meta && (
            <div ref={resultsRef} className="results">
              <div className="headline-bar" key={swap}>
                <span className={`pill big ${meta.tone}`}>{meta.title}</span>
                <span className="hl">{variant.headline}</span>
                <span className="muted small mono">{scenario.control.label} = {variant.value} {scenario.control.unit}</span>
              </div>

              <Assumptions
                assumptions={scenario.spec.assumptions}
                verdict={variant.verdict}
                control={scenario.control}
                variants={scenario.variants}
                variantIdx={vIdx}
                onVariant={(i) => {
                  setVIdx(i)
                  setCompare(false)
                  setPlayToken((t) => t + 1)
                }}
                approved={approved}
                onApprove={(k, v) => setApproved((a) => ({ ...a, [k]: v }))}
                edits={edits}
                onEdit={(k, v) =>
                  setEdits((e) => {
                    const n = { ...e }
                    if (v === null) delete n[k]
                    else n[k] = v
                    return n
                  })
                }
                engineUp={engineUp}
                onRerun={rerun}
                rerunning={rerunning}
              />

              <section className="panel" id="replay">
                <header className="panel-h">
                  <h2>3D replay <span className="kr">재생</span></h2>
                  <span className="row">
                    <span className="pill recorded">recorded run · replays stored MuJoCo trajectory</span>
                    <span className="pill muted-pill">actor: Three.js · no physics here</span>
                  </span>
                </header>
                <Replay
                  traj={traj}
                  loading={trajLoading}
                  compare={compare ? cmpTraj : null}
                  mainLabel={`${scenario.control.label} = ${variant.value} ${scenario.control.unit}`}
                  compareLabel={fixedIdx !== null ? `fixed: ${scenario.variants[fixedIdx].value} ${scenario.control.unit}` : undefined}
                  playToken={playToken}
                />
              </section>

              <FixCallout variant={variant} fixedValue={fixedIdx !== null ? scenario.variants[fixedIdx].value : undefined} control={scenario.control} fixedIdx={fixedIdx} onApply={applyFix} compare={compare} onCompare={setCompare} />

              <div key={`v${swap}`} className="swap-in">
                <VerdictCard verdict={variant.verdict} assumptions={scenario.spec.assumptions} />
              </div>
              <Bom verdict={variant.verdict} />
            </div>
          )}
        </main>
      )}

      <footer className="foot">
        <div className="foot-grid">
          <div>
            <b>Judge = MuJoCo, Actor = Three.js.</b> Every number in a verdict comes from simulation tools, never from a language model. Three.js only replays a stored trajectory.
            <div className="muted small">Verdict asymmetry: found = strong · necessary condition violated = strong "impossible under assumptions" · not found in budget = weak, never proof.</div>
          </div>
          <div>
            <b>What this does not judge / limits</b>
            <ul>
              <li>CFD, thermal and FEA effects are not modelled; labelled "simplified model" where relevant.</li>
              <li>Agent runs shown here are recorded, seeded and reproducible, not live compute; the research step reads a curated catalog, not the live web.</li>
              <li>Catalog values marked unverified / llm_estimate are placeholders to review.</li>
              <li>Autoresearch uses synthetic data; sim-to-real is not validated.</li>
              <li>Cost "physical-equivalent" figures are estimates; willingness to pay is unvalidated.</li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}

/** Accept either {entries:[...]} or a bare array of ledger rows. */
function normalizeLedger(l: LedgerFile | null): LedgerFile | null {
  if (!l) return null
  if (Array.isArray(l)) return { entries: l as LedgerFile['entries'] }
  return l
}
