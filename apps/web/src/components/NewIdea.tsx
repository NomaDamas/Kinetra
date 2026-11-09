import { useState } from 'react'
import { engineReachable, matchScenario, runEngine, type DemoIndex } from '../bundle'
import { registerLocalRun } from '../lib/data'
import { go, projectHref } from '../lib/router'
import { ENGINE_START_CMD } from '../live/config'

interface Props {
  index: DemoIndex | null
  compact?: boolean
}

/** One-sentence idea box. Recorded ideas open their stored bundle; anything else runs on the local engine (never invented). */
export function NewIdea({ index, compact }: Props) {
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ kind: 'info' | 'err'; text: string; cmd?: boolean } | null>(null)

  const submit = async (idea: string) => {
    if (!index || !idea.trim()) return
    setMsg(null)
    const m = matchScenario(idea, index.scenarios)
    if (m) {
      go(projectHref(m.id, 'overview'))
      return
    }
    setBusy(true)
    try {
      if (!(await engineReachable())) {
        setMsg({
          kind: 'info',
          cmd: true,
          text: 'No recorded project matches this idea, and the local engine API is not reachable at http://localhost:8000. Kinetra does not invent results for unseen ideas. Start the engine, then submit again:',
        })
        return
      }
      setMsg({ kind: 'info', text: 'Running the full pipeline on your local engine (screen, search, Monte-Carlo). This can take up to ~30 s…' })
      const s = await runEngine(idea)
      const id = registerLocalRun(s)
      go(projectHref(id, 'overview'))
    } catch (e) {
      setMsg({ kind: 'err', text: `Local engine run failed: ${(e as Error).message}` })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className={`newidea ${compact ? 'compact' : ''}`}>
      <form
        className="prompt"
        onSubmit={(e) => {
          e.preventDefault()
          void submit(text)
        }}
      >
        <label className="sr-only" htmlFor="idea-input">Describe a physical idea in one sentence</label>
        <textarea
          id="idea-input"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. A 1.3-tonne roadster rolls and pitches a full 360° off a ramp on rocket thrusters and lands on its wheels"
          rows={compact ? 2 : 3}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void submit(text)
            }
          }}
        />
        <button className="btn primary big" type="submit" disabled={!index || !text.trim() || busy}>
          {busy ? 'Running…' : 'Check this idea'}
        </button>
      </form>
      {index && index.scenarios.length > 0 && (
        <div className="chips examples">
          <span className="muted small">Recorded examples:</span>
          {index.scenarios.map((s) => (
            <button key={s.id} className="chip link-chip" type="button" onClick={() => setText(s.idea)} title={s.idea}>
              {s.title}
            </button>
          ))}
        </div>
      )}
      {msg && (
        <div className={`callout ${msg.kind === 'err' ? 'bad' : ''}`} role={msg.kind === 'err' ? 'alert' : 'status'}>
          {msg.text}
          {msg.cmd && <pre className="cmd mono">{ENGINE_START_CMD}</pre>}
        </div>
      )}
    </div>
  )
}
