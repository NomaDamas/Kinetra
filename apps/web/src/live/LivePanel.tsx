import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { fmt, loadScenario, type DemoIndex, type Scenario, type Variant } from '../bundle'
import { Replay } from '../components/Replay'
import { statusMeta } from '../util'
import { XYChart } from './Chart'
import { ENGINE_START_ALT, ENGINE_START_CMD, SPEEDS, STORED_SCHEDULE_NOTE, TEMPLATES, type ParamDef, type TemplateCfg } from './config'
import type { LiveDisplayItem, LiveStartReq } from './types'
import { useEngineHealth } from './useEngineHealth'
import { useLiveSim, type Phase } from './useLiveSim'

interface Props {
  index: DemoIndex | null
  /** Reports engine reachability (from the 3 s /health poll) so the header pill stays in sync. */
  onEngineUp?: (up: boolean) => void
}

const DEBOUNCE_MS = 250

type ScenarioState = { status: 'loading' } | { status: 'ok'; scenario: Scenario } | { status: 'failed'; error: string }

const PHASE_LABEL: Record<Phase, string> = {
  idle: 'idle',
  connecting: 'connecting…',
  running: 'streaming',
  searching: 'searching',
  done: 'done',
  stopped: 'stopped',
  error: 'error',
}

function witnessVariants(sc: Scenario | null): Variant[] {
  return sc ? sc.variants.filter((v) => Object.keys(v.verdict.best_params).length > 0) : []
}

/** Default schedule source: the feasible variant whose control value equals the spec's nominal value, else the last witness. */
function defaultWitness(sc: Scenario | null, cfg: TemplateCfg): number | null {
  const w = witnessVariants(sc)
  if (!sc || w.length === 0) return null
  const nominal = sc.spec.assumptions.find((a) => a.key === cfg.controlKey)?.value
  const hit = w.find((v) => nominal !== undefined && Math.abs(v.value - nominal) < 1e-9 && v.verdict.status === 'FEASIBLE_FOUND')
  return (hit ?? w[w.length - 1]).value
}

function nearestVariant(sc: Scenario, value: number): Variant | null {
  let best: Variant | null = null
  let bd = Infinity
  for (const v of sc.variants) {
    const d = Math.abs(v.value - value)
    if (d < bd) {
      bd = d
      best = v
    }
  }
  return best
}

function fmtDisplay(v: LiveDisplayItem['value']): string {
  if (typeof v === 'number') return fmt(v, 4)
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  return v
}

function copy(text: string) {
  void navigator.clipboard?.writeText(text)
}

export function LivePanel({ index, onEngineUp }: Props) {
  const { health, checked } = useEngineHealth(onEngineUp)
  const sim = useLiveSim()
  const [tplIdx, setTplIdx] = useState(0)
  const cfg = TEMPLATES[tplIdx]
  const [scenarios, setScenarios] = useState<Record<string, ScenarioState>>({})
  const [edits, setEdits] = useState<Record<string, Record<string, number>>>({})
  const [seeds, setSeeds] = useState<Record<string, number>>({})
  const [witnessSel, setWitnessSel] = useState<Record<string, number>>({})
  const [rescale, setRescale] = useState(false)
  const [speed, setSpeed] = useState(1)
  const [autoRun, setAutoRun] = useState(true)
  const [searchSeconds, setSearchSeconds] = useState(15)

  // ---- recorded scenario (default spec values + stored witnesses) for the selected template
  const meta = useMemo(() => index?.scenarios.find((s) => s.template === cfg.scenarioTemplate) ?? null, [index, cfg])
  const metaId = meta?.id ?? null
  const requested = useRef(new Set<string>())
  useEffect(() => {
    if (!metaId || requested.current.has(metaId)) return
    requested.current.add(metaId)
    setScenarios((m) => ({ ...m, [metaId]: { status: 'loading' } }))
    loadScenario(metaId)
      .then((scenario) => setScenarios((m) => ({ ...m, [metaId]: { status: 'ok', scenario } })))
      .catch((e: Error) => setScenarios((m) => ({ ...m, [metaId]: { status: 'failed', error: e.message } })))
  }, [metaId])
  const scState: ScenarioState | null = metaId ? (scenarios[metaId] ?? { status: 'loading' }) : null
  const scenario = scState?.status === 'ok' ? scState.scenario : null

  const tkey = cfg.template
  const witnesses = useMemo(() => witnessVariants(scenario), [scenario])
  const witnessValue = witnessSel[tkey] ?? defaultWitness(scenario, cfg)
  const witness = witnesses.find((v) => witnessValue !== null && Math.abs(v.value - witnessValue) < 1e-9) ?? null
  const recordedSeed = scenario?.variants[0]?.verdict.reproducibility.seed
  const seed = seeds[tkey] ?? recordedSeed ?? 0

  const valueOf = useCallback(
    (p: ParamDef): number => edits[tkey]?.[p.key] ?? scenario?.spec.assumptions.find((a) => a.key === p.key)?.value ?? p.fallback,
    [edits, tkey, scenario],
  )

  // ---- engine capabilities
  const engineUp = health !== null
  const liveTemplates = health?.live?.templates ?? health?.templates
  const templateOk = !engineUp || !liveTemplates || liveTemplates.includes(tkey)
  const searchList = health?.live?.search
  const searchOk = engineUp && !!searchList && searchList.includes(tkey)
  const scenarioReady = scState === null || scState.status !== 'loading'
  const active = sim.phase === 'connecting' || sim.phase === 'running' || sim.phase === 'searching'
  const canRun = engineUp && templateOk && scenarioReady

  const buildReq = useCallback(
    (mode: 'sim' | 'search'): LiveStartReq => {
      const overrides: Record<string, number> = {}
      for (const a of scenario?.spec.assumptions ?? []) overrides[a.key] = a.value
      for (const p of cfg.params) overrides[p.key] = valueOf(p)
      const req: LiveStartReq = { type: 'start', template: cfg.template, mode, overrides, seed, speed }
      if (mode === 'sim') {
        if (witness) {
          req.params = witness.verdict.best_params
          if (cfg.template === 'rocket_car') {
            req.rescale_throttle = rescale
            req.rescale_from = witness.value
          }
        }
      } else {
        req.search = { max_seconds: searchSeconds, preview_every: 2 }
      }
      return req
    },
    [scenario, cfg, valueOf, seed, speed, witness, rescale, searchSeconds],
  )

  // ---- debounced auto re-simulation: every change cancels the running sim server-side (a new `start`) and re-runs for real
  const latest = useRef({ canRun, autoRun, searching: false, build: buildReq, run: sim.run })
  latest.current = { canRun, autoRun, searching: sim.phase === 'searching' || sim.replaying, build: buildReq, run: sim.run }
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const queueRun = useCallback(() => {
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const l = latest.current
      if (l.canRun && l.autoRun && !l.searching) l.run(l.build('sim'))
    }, DEBOUNCE_MS)
  }, [])
  useEffect(() => () => clearTimeout(timer.current), [])

  const setParam = (p: ParamDef, v: number) => {
    setEdits((e) => ({ ...e, [tkey]: { ...e[tkey], [p.key]: v } }))
    queueRun()
  }

  const runNow = () => {
    clearTimeout(timer.current)
    sim.run(buildReq('sim'))
  }
  const searchNow = () => {
    clearTimeout(timer.current)
    sim.run(buildReq('search'))
  }
  const stopNow = () => {
    clearTimeout(timer.current)
    sim.stop()
  }
  const pickTemplate = (i: number) => {
    if (i === tplIdx) return
    clearTimeout(timer.current)
    sim.reset()
    setTplIdx(i)
  }

  // ---- derived view data
  const { traj, handle, header, result } = sim
  const staleView = traj !== null && header !== null && sim.trajRunId !== header.run_id // previous run's frames until the new run has frames
  const filled = handle?.filled ?? 0
  const nShow = traj ? Math.min(filled, traj.pos.length) : 0
  const xMax = traj ? (handle?.active ? header?.n_frames_max ?? traj.pos.length : traj.pos.length) : 0
  const xRange: [number, number] | undefined = traj ? [0, Math.max(1, xMax - 1) * traj.dt] : undefined
  const cursor = traj && handle?.active && !handle.preview ? Math.max(0, filled - 1) * traj.dt : null
  const nearest = scenario && sim.req ? nearestVariant(scenario, sim.req.overrides?.[cfg.controlKey] ?? valueOf(cfg.params[0])) : null
  const resultTemplateMatches = header?.template === tkey

  return (
    <div className="live-panel" data-testid="live-panel">
      <section className="panel">
        <header className="panel-h">
          <div className="row">
            <span className="live-badge" data-testid="live-badge">
              <i className="live-dot" />
              LIVE
            </span>
            <h2>Live simulation</h2>
            <span className="muted small">real MuJoCo stepped by the local engine, streamed over a WebSocket</span>
          </div>
          <span
            className={`pill ${!checked ? 'muted-pill' : engineUp ? 'ok' : 'bad'}`}
            data-testid="live-engine-status"
            title={health?.live?.version_note}
          >
            {!checked
              ? 'engine: checking…'
              : engineUp
                ? `engine online · MuJoCo ${health?.mujoco_version ?? '?'} · templates: ${(liveTemplates ?? []).join(', ') || '—'}`
                : 'engine offline'}
          </span>
        </header>

        {checked && !engineUp && (
          <div className="callout bad" data-testid="live-engine-down">
            <b>The local engine is not running, so Live runs are disabled.</b> Nothing here is faked: no engine, no live data. Start it with:
            <pre className="cmd mono">{ENGINE_START_CMD}</pre>
            <div className="small">
              or <code>{ENGINE_START_ALT}</code>{' '}
              <button className="link" onClick={() => copy(ENGINE_START_CMD)}>copy command</button>
            </div>
            <div className="small muted">Recorded demo still works in the other tabs.</div>
          </div>
        )}

        <div className="row live-tpl">
          <span className="muted small">Template</span>
          <div className="seg" role="group" aria-label="Live template">
            {TEMPLATES.map((t, i) => (
              <button key={t.template} className={i === tplIdx ? 'on' : ''} onClick={() => pickTemplate(i)} disabled={active && i !== tplIdx}>
                {t.title}
              </button>
            ))}
          </div>
          {scState?.status === 'failed' && <span className="pill warn">recorded scenario unavailable: {scState.error}</span>}
          {!index && <span className="muted small">loading recorded bundle…</span>}
          {index && !meta && <span className="pill warn">no recorded scenario for {cfg.template}: using built-in defaults</span>}
          {checked && engineUp && !templateOk && <span className="pill bad">engine has no live support for {cfg.template}</span>}
        </div>

        <div className="live-grid">
          <div className="live-controls">
            <h4>Parameters (each change re-simulates for real)</h4>
            {cfg.params
              .filter((p) => !p.optional)
              .map((p) => (
                <ParamRow key={p.key} p={p} value={valueOf(p)} onChange={(v) => setParam(p, v)} />
              ))}
            <details className="live-more">
              <summary className="small muted">more parameters</summary>
              {cfg.params
                .filter((p) => p.optional)
                .map((p) => (
                  <ParamRow key={p.key} p={p} value={valueOf(p)} onChange={(v) => setParam(p, v)} />
                ))}
            </details>

            <div className="live-row">
              <label className="small" htmlFor="live-seed">Seed</label>
              <input
                id="live-seed"
                className="num"
                type="number"
                step={1}
                value={seed}
                data-testid="live-seed"
                onChange={(e) => {
                  setSeeds((s) => ({ ...s, [tkey]: Math.trunc(Number(e.target.value) || 0) }))
                  queueRun()
                }}
              />
              {recordedSeed !== undefined && <span className="muted small">recorded seed {recordedSeed}</span>}
            </div>

            <h4>Schedule source</h4>
            <div className="live-row">
              <select
                className="live-select"
                aria-label="Schedule source"
                data-testid="live-witness"
                value={witness ? String(witness.value) : ''}
                disabled={witnesses.length === 0}
                onChange={(e) => {
                  setWitnessSel((w) => ({ ...w, [tkey]: Number(e.target.value) }))
                  queueRun()
                }}
              >
                {witnesses.length === 0 && <option value="">(no stored witness: engine uses its recorded default)</option>}
                {witnesses.map((v) => (
                  <option key={v.value} value={String(v.value)}>
                    witness from recorded variant {v.value} {scenario?.control.unit} · {v.verdict.status === 'FEASIBLE_FOUND' ? `p≈${(v.verdict.feasibility.p_success * 100).toFixed(0)}%` : v.verdict.status}
                  </option>
                ))}
              </select>
            </div>
            {cfg.template === 'rocket_car' && (
              <label className="chk live-row">
                <input
                  type="checkbox"
                  checked={rescale}
                  data-testid="live-rescale"
                  onChange={(e) => {
                    setRescale(e.target.checked)
                    queueRun()
                  }}
                />
                rescale throttle to keep commanded thrust
              </label>
            )}
            <p className="muted small live-note">{STORED_SCHEDULE_NOTE}</p>

            <h4>Playback speed</h4>
            <div className="seg" role="group" aria-label="Simulation speed" data-testid="live-speed">
              {SPEEDS.map((s) => (
                <button
                  key={s.label}
                  className={s.value === speed ? 'on' : ''}
                  onClick={() => {
                    setSpeed(s.value)
                    queueRun()
                  }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <div className="muted small live-note">1× paces simulation time to wall-clock; max steps as fast as the engine can.</div>

            <div className="live-actions">
              <button className="btn primary" data-testid="live-run" onClick={runNow} disabled={!canRun} title={canRun ? undefined : 'engine offline'}>
                ▶ Run live
              </button>
              <button className="btn" data-testid="live-stop" onClick={stopNow} disabled={!active}>
                ■ Stop
              </button>
              <button className="btn" data-testid="live-restart" onClick={() => sim.restart()} disabled={!canRun || !sim.req || active}>
                ↻ Restart
              </button>
              <label className="chk">
                <input type="checkbox" checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} data-testid="live-autorun" /> auto-run on change
              </label>
            </div>
          </div>

          <div className="live-stage">
            <div className="live-status-row">
              <span className={`pill ${sim.phase === 'error' ? 'bad' : sim.phase === 'done' ? 'ok' : active ? 'warn' : 'muted-pill'}`} data-testid="live-phase">
                {PHASE_LABEL[sim.phase]}
              </span>
              {header && (
                <span className="muted small mono">
                  run #{header.run_id} · {header.mode} · {header.compute === 'batch' ? 'batch (rollout computed, then paced out)' : 'incremental mj_step stream'} · MuJoCo {header.mujoco_version}
                </span>
              )}
              {staleView && <span className="pill muted-pill">showing previous run until frames arrive</span>}
            </div>
            {sim.error && (
              <div className="callout bad" data-testid="live-error">
                <b>Live run failed:</b> {sim.error}
              </div>
            )}
            <div data-testid="live-view">
              {traj && handle ? (
                <Replay
                  traj={traj}
                  loading={false}
                  compare={null}
                  playToken={0}
                  live={handle}
                  liveLabel={header ? `${header.mode === 'search' ? 'search preview / best replay' : 'sim'} #${header.run_id}` : undefined}
                />
              ) : (
                <div className="view live-empty">
                  <div className="view-empty">
                    {sim.phase === 'connecting' ? 'Connecting to the local engine…' : 'Press “Run live” — frames will stream here from a real MuJoCo simulation.'}
                  </div>
                  <span className="view-tag">no run yet</span>
                </div>
              )}
            </div>
            {header?.note && <div className="muted small live-note">{header.note}</div>}
          </div>
        </div>
      </section>

      {header && traj && (header.charts?.length ?? 0) > 0 && resultTemplateMatches && (
        <section className="panel">
          <header className="panel-h">
            <h2>Live charts</h2>
            <span className="muted small mono">{handle?.active ? `streaming · ${nShow} frames` : `${nShow} frames`} · x = simulation time (s)</span>
          </header>
          <div className="live-charts" data-testid="live-charts">
            {(header.charts ?? []).map((c) => {
              const s = traj.series.find((x) => x.name === c.series)
              return s ? (
                <XYChart
                  key={c.series}
                  title={c.label}
                  ys={s.values}
                  dt={traj.dt}
                  n={nShow}
                  xRange={xRange}
                  cursor={cursor}
                  xlabel="t (s)"
                  ylabel={c.unit}
                />
              ) : null
            })}
          </div>
        </section>
      )}

      <div className="grid2 live-results">
        <section className="panel" data-testid="live-throughput">
          <header className="panel-h">
            <h2>Measured throughput</h2>
            <span className="muted small">from the engine, not estimated</span>
          </header>
          {result ? (
            <div className="kv">
              <div><span>steps</span><b className="mono">{result.perf.steps.toLocaleString('en-US')}</b></div>
              <div><span>steps / s</span><b className="mono" data-testid="live-steps-per-s">{Math.round(result.perf.steps_per_s).toLocaleString('en-US')}</b></div>
              <div><span>µs / step</span><b className="mono">{fmt(result.perf.us_per_step, 4)}</b></div>
              <div><span>compute</span><b className="mono">{fmt(result.perf.compute_ms, 4)} ms</b></div>
              <div><span>sim time</span><b className="mono">{fmt(result.perf.sim_time_s, 4)} s</b></div>
              <div><span>realtime factor</span><b className="mono">{fmt(result.perf.realtime_factor, 4)}×</b></div>
              <div><span>frames</span><b className="mono">{result.perf.frames}</b></div>
              <div><span>MuJoCo</span><b className="mono">{result.mujoco_version}</b></div>
            </div>
          ) : sim.frameStats ? (
            <div className="kv">
              <div><span>steps so far</span><b className="mono">{sim.frameStats.steps.toLocaleString('en-US')}</b></div>
              <div><span>compute so far</span><b className="mono">{fmt(sim.frameStats.compute_ms, 4)} ms</b></div>
              <div><span>sim time</span><b className="mono">{fmt(sim.frameStats.t, 4)} s</b></div>
            </div>
          ) : (
            <div className="muted small">{active ? 'waiting for the first frames…' : 'Run a live simulation to measure steps/s, µs/step and the realtime factor.'}</div>
          )}
          {result?.perf.compute && <div className="muted small live-note">{result.perf.compute}</div>}
        </section>

        <section className="panel" data-testid="live-result">
          <header className="panel-h">
            <h2>Live result</h2>
            {result && (
              <span className={`pill big ${result.success ? 'ok' : 'bad'}`} data-testid="live-result-verdict">
                {result.success ? 'LIVE ROLLOUT: SUCCESS' : 'LIVE ROLLOUT: FAILED'}
              </span>
            )}
          </header>
          {result ? (
            <>
              <div className="tablewrap">
                <table className="tbl compact">
                  <thead>
                    <tr><th>Check</th><th>Value</th><th>Limit</th><th /></tr>
                  </thead>
                  <tbody>
                    {result.display.map((d) => (
                      <tr key={d.key}>
                        <td>{d.label}</td>
                        <td className="mono">{fmtDisplay(d.value)} {d.unit}</td>
                        <td className="mono muted">{d.threshold ?? ''}</td>
                        <td>{d.ok === null ? <span className="pill muted-pill">info</span> : <span className={`pill ${d.ok ? 'ok' : 'bad'}`}>{d.ok ? 'pass' : 'fail'}</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {result.failed_checks.length > 0 && <div className="failed-check">failed checks: {result.failed_checks.join(', ')}</div>}
              <div className="muted small mono live-note">
                seed {result.seed} · MuJoCo {result.mujoco_version} · sha256 {result.trajectory_sha256.slice(0, 16)}…
              </div>
              <details className="live-more">
                <summary className="small muted">schedule + overrides that produced this run</summary>
                <pre className="detail">{JSON.stringify({ params: result.params, overrides: result.overrides }, null, 1)}</pre>
              </details>
              {scenario && nearest && (
                <div className="callout live-recorded" data-testid="live-recorded">
                  <div className="small">
                    <b>recorded (seeded pipeline)</b> · nearest recorded variant {scenario.control.label} = {nearest.value} {scenario.control.unit}
                  </div>
                  <div className="row">
                    <span className={`pill ${statusMeta(nearest.verdict).tone}`}>{statusMeta(nearest.verdict).title}</span>
                    <span className="mono">
                      p_success = {(nearest.verdict.feasibility.p_success * 100).toFixed(1)}% [{(nearest.verdict.feasibility.ci_low * 100).toFixed(1)}–
                      {(nearest.verdict.feasibility.ci_high * 100).toFixed(1)}%] · n={nearest.verdict.feasibility.n_samples}
                    </span>
                  </div>
                  <div className="muted small">
                    A single live nominal rollout is one deterministic episode, <b>not</b> the Monte-Carlo p_success (which samples the uncertain assumptions). The two numbers are not comparable.
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="muted small">
              {active ? 'The result card appears when the rollout completes.' : 'No live result yet.'}
              {scenario && <> A single live nominal rollout is not the Monte-Carlo p_success shown for recorded variants.</>}
            </div>
          )}
        </section>
      </div>

      <section className="panel" data-testid="live-search-panel">
        <header className="panel-h">
          <h2>Live search <span className="kr">CMA-ES, real</span></h2>
          <span className="muted small">{cfg.searchNote || 'search is not available for this template'}</span>
        </header>
        <div className="live-actions">
          <button className="btn primary" data-testid="live-search" onClick={searchNow} disabled={!canRun || !searchOk || active}>
            {searchOk || !engineUp ? 'Run live search' : 'search not available live for this template'}
          </button>
          <button className="btn" data-testid="live-search-cancel" onClick={stopNow} disabled={sim.phase !== 'searching' || sim.replaying}>
            Cancel
          </button>
          <label className="small row">
            budget
            <input
              className="num"
              type="number"
              min={1}
              max={120}
              step={1}
              value={searchSeconds}
              onChange={(e) => setSearchSeconds(Math.min(120, Math.max(1, Number(e.target.value) || 15)))}
              style={{ width: 64 }}
              data-testid="live-search-seconds"
            />
            s
          </label>
          {engineUp && !searchOk && (
            <span className="muted small" data-testid="live-search-reason">
              Live search is only available for: {(searchList ?? []).join(', ') || 'no template'} (engine health.live.search).
            </span>
          )}
          {!engineUp && <span className="muted small">engine offline</span>}
        </div>
        <p className="muted small live-note">
          Re-optimises the thruster schedule under the current parameters with real CMA-ES; every candidate is a full MuJoCo rollout. The 3D view shows the best-so-far rollout; when the search ends, the best schedule is streamed as a normal live run.
        </p>
        {(sim.progress || sim.searchDone) && (
          <div className="live-search-body" data-testid="live-search-progress">
            {sim.progress && (
              <div className="kv">
                <div><span>generation</span><b className="mono">{sim.progress.gen}</b></div>
                <div><span>evals</span><b className="mono">{sim.progress.evals.toLocaleString('en-US')}</b></div>
                <div><span>evals / s</span><b className="mono">{Math.round(sim.progress.evals_per_s).toLocaleString('en-US')}</b></div>
                <div><span>elapsed</span><b className="mono">{fmt(sim.progress.elapsed_s, 3)} s</b></div>
                <div><span>best cost</span><b className="mono">{fmt(sim.progress.best_cost, 4)}</b></div>
                <div>
                  <span>status</span>
                  <b className="mono">{sim.searchDone ? (sim.searchDone.found ? 'found' : 'not found') : sim.progress.success ? 'success found, still refining' : 'searching'}</b>
                </div>
                {sim.progress.restart !== undefined && <div><span>restart</span><b className="mono">{sim.progress.restart}</b></div>}
                {sim.progress.popsize !== undefined && <div><span>population</span><b className="mono">{sim.progress.popsize}</b></div>}
              </div>
            )}
            {sim.progressHist.length > 1 && (
              <XYChart
                title="Best cost vs evaluations"
                xs={sim.progressHist.map((p) => p.evals)}
                ys={sim.progressHist.map((p) => p.best_cost)}
                n={sim.progressHist.length}
                xlabel="evals"
                ylabel="best cost"
                color="#ffb347"
                h={170}
                testId="live-search-chart"
              />
            )}
            {sim.preview && !sim.searchDone && (
              <div className="muted small mono">
                preview: best-so-far rollout from generation {sim.preview.gen} · cost {fmt(sim.preview.cost, 4)} · {sim.preview.success ? 'passes all checks' : 'does not yet pass all checks'}
              </div>
            )}
            {sim.searchDone && (
              <div className="callout" data-testid="live-search-done">
                <div className="row">
                  <span className={`pill big ${sim.searchDone.found ? 'ok' : 'weak'}`}>{sim.searchDone.found ? 'SEARCH: FOUND A SCHEDULE' : 'SEARCH: NOT FOUND'}</span>
                  <span className="mono small">
                    stopped by {sim.searchDone.stopped_by} · {sim.searchDone.evals.toLocaleString('en-US')} evals · {fmt(sim.searchDone.wall_s, 3)} s · {Math.round(sim.searchDone.evals_per_s).toLocaleString('en-US')} evals/s · {sim.searchDone.generations} generations
                  </span>
                </div>
                {!sim.searchDone.found && (
                  <div className="muted small">Not found within this budget is weak evidence only, never proof of impossibility. {sim.searchDone.stopped_by === 'cancelled' ? 'The search was cancelled.' : ''}</div>
                )}
                {sim.replaying && <div className="small">The best schedule found is now streamed as a normal live run in the 3D view above.</div>}
              </div>
            )}
          </div>
        )}
      </section>
    </div>
  )
}

function ParamRow({ p, value, onChange }: { p: ParamDef; value: number; onChange: (v: number) => void }) {
  const id = `live-p-${p.key}`
  return (
    <div className="live-param">
      <div className="live-param-h">
        <label htmlFor={id}>{p.label}</label>
        <span className="mono live-param-v">
          <input
            className="num"
            type="number"
            min={p.min}
            max={p.max}
            step={p.step}
            value={Number.isFinite(value) ? value : p.fallback}
            aria-label={`${p.label} value`}
            onChange={(e) => {
              const v = Number(e.target.value)
              if (Number.isFinite(v)) onChange(v)
            }}
          />{' '}
          <span className="muted">{p.unit}</span>
        </span>
      </div>
      <input
        id={id}
        className="slider"
        type="range"
        min={p.min}
        max={p.max}
        step={p.step}
        value={value}
        data-testid={p.testId ?? `live-param-${p.key}`}
        onChange={(e) => onChange(Number(e.target.value))}
      />
      {p.hint && <div className="muted small">{p.hint}</div>}
    </div>
  )
}
