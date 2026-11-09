import { useEffect, useRef, useState } from 'react'
import type { AgentStep } from '../bundle'

interface Props {
  steps: AgentStep[]
  /** key changes => restart the animation */
  runKey: number
  onDone: () => void
}

/** Plays back a RECORDED pipeline log. Delays are cosmetic; the wall_seconds shown are the real recorded ones. */
export function AgentRun({ steps, runKey, onDone }: Props) {
  const [shown, setShown] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const done = useRef(onDone)
  done.current = onDone

  useEffect(() => {
    setShown(0)
    setOpen(null)
    let i = 0
    let timer = 0
    const tick = () => {
      i++
      setShown(i)
      if (i < steps.length) timer = window.setTimeout(tick, 380 + Math.min(900, steps[i - 1].wall_seconds * 18))
      else done.current()
    }
    timer = window.setTimeout(tick, 250)
    return () => window.clearTimeout(timer)
  }, [runKey, steps])

  const total = steps.reduce((a, s) => a + s.wall_seconds, 0)
  return (
    <section className="panel" id="run">
      <header className="panel-h">
        <h2>Agent run <span className="kr">에이전트 실행</span></h2>
        <span className="pill recorded" title="The pipeline ran earlier; this is a replay of its log. Nothing is computed in your browser.">
          RECORDED RUN · seeded & reproducible
        </span>
      </header>
      <ol className="steps">
        {steps.map((s, i) => {
          const state = i < shown ? 'done' : i === shown ? 'active' : 'pending'
          return (
            <li key={s.id} className={`step ${state}`}>
              <span className="dot" aria-hidden>{state === 'done' ? '✓' : state === 'active' ? '…' : ''}</span>
              <div className="step-body">
                <div className="step-top">
                  <b>{s.label}</b>
                  <code className="tool">{s.tool}</code>
                  {state === 'done' && <span className="mono wall">{s.wall_seconds.toFixed(2)}s wall</span>}
                </div>
                {state === 'done' && (
                  <div className="step-sum">
                    {s.summary}
                    {s.detail !== undefined && s.detail !== null && (
                      <button className="link" onClick={() => setOpen(open === s.id ? null : s.id)}>
                        {open === s.id ? 'hide detail' : 'detail'}
                      </button>
                    )}
                  </div>
                )}
                {open === s.id && <pre className="detail">{JSON.stringify(s.detail, null, 2)}</pre>}
              </div>
            </li>
          )
        })}
      </ol>
      <p className="muted small">
        {steps.length} tool calls, {total.toFixed(1)} s total recorded wall time. Numbers come from simulation tools, not from a language model.
        {' '}Replaying the log is animated for readability only.
      </p>
    </section>
  )
}
