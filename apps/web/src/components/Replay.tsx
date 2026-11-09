import { useCallback, useEffect, useRef, useState } from 'react'
import type { Trajectory } from '../types'
import type { LiveHandle } from '../live/types'
import { Scene, type Clock } from './Scene'

interface Props {
  traj: Trajectory | null
  loading: boolean
  /** Optional second trajectory (e.g. the fixed variant) shown side-by-side. */
  compare: Trajectory | null
  compareLabel?: string
  mainLabel?: string
  /** Incrementing token: restarts playback from t=0 and plays. */
  playToken: number
  /** Live run attached to `traj` (streamed in place). While `live.active` the playhead follows the stream frontier. */
  live?: LiveHandle
  /** Label of the main view when `live` is given. */
  liveLabel?: string
}

const SPEEDS = [0.1, 0.25, 0.5, 1, 2]

function duration(t: Trajectory | null, live?: LiveHandle) {
  if (!t) return 0
  const n = live?.active ? Math.min(live.filled, t.pos.length) : t.pos.length
  return Math.max(0, (n - 1) * t.dt)
}

export function Replay({ traj, loading, compare, compareLabel, mainLabel, playToken, live, liveLabel }: Props) {
  const clock = useRef<Clock>({ t: 0 })
  const [uiT, setUiT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(0.5)
  const [follow, setFollow] = useState(true)
  const [trail, setTrail] = useState(true)
  const playingRef = useRef(playing)
  const speedRef = useRef(speed)
  playingRef.current = playing
  speedRef.current = speed
  const streaming = !!live?.active
  const dur = Math.max(duration(traj, live), compare ? duration(compare) : 0)
  const durRef = useRef(dur)
  durRef.current = dur
  const liveRef = useRef(live)
  const trajRef = useRef(traj)
  liveRef.current = live
  trajRef.current = traj

  // reset when the trajectory changes
  useEffect(() => {
    clock.current.t = 0
    setUiT(0)
  }, [traj, compare])

  useEffect(() => {
    if (playToken > 0) {
      clock.current.t = 0
      setPlaying(true)
    }
  }, [playToken])

  useEffect(() => {
    let raf = 0
    let last = performance.now()
    let lastUi = 0
    const loop = (now: number) => {
      const dt = Math.min((now - last) / 1000, 0.1)
      last = now
      const lv = liveRef.current
      const tj = trajRef.current
      if (lv?.active && tj) {
        // streaming: follow the frontier (search preview: loop the best-so-far rollout in real time)
        const end = Math.max(0, (Math.max(1, Math.min(lv.filled, tj.pos.length)) - 1) * tj.dt)
        if (lv.preview) {
          clock.current.t += dt
          if (clock.current.t > end) clock.current.t = 0
        } else clock.current.t = end
      } else if (playingRef.current && durRef.current > 0) {
        clock.current.t += dt * speedRef.current
        if (clock.current.t >= durRef.current) {
          clock.current.t = durRef.current
          setPlaying(false)
        }
      }
      if (now - lastUi > 50) {
        lastUi = now
        setUiT(clock.current.t)
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [])

  const toggle = useCallback(() => {
    if (!playing && clock.current.t >= durRef.current - 1e-6) clock.current.t = 0
    setPlaying((p) => !p)
  }, [playing])

  return (
    <div className="replay">
      <div className={`replay-views ${compare ? 'two' : ''}`}>
        <div className="view">
          {traj ? <Scene traj={traj} clock={clock} follow={follow} trail={trail} live={live} /> : <div className="view-empty">{loading ? 'Loading trajectory…' : 'No trajectory'}</div>}
          {live && traj ? (
            <span className="view-tag live-tag">
              <i className="live-dot" />
              LIVE · real MuJoCo on local engine
              {liveLabel && <span className="muted"> · {liveLabel}</span>}
            </span>
          ) : (
            mainLabel && <span className="view-tag">{mainLabel}</span>
          )}
          {loading && traj && <span className="view-tag right">swapping…</span>}
        </div>
        {compare && (
          <div className="view">
            <Scene traj={compare} clock={clock} follow={follow} trail={trail} />
            <span className="view-tag good">{compareLabel ?? 'compare'}</span>
          </div>
        )}
      </div>
      <div className="transport">
        <button className="btn primary" onClick={toggle} disabled={!traj || streaming} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <button
          className="btn"
          onClick={() => {
            clock.current.t = 0
            setUiT(0)
          }}
          disabled={!traj || streaming}
        >
          ⏮
        </button>
        <input
          className="scrub"
          type="range"
          min={0}
          max={dur || 1}
          step={dur / 1000 || 0.001}
          value={uiT}
          disabled={!traj || streaming}
          onChange={(e) => {
            clock.current.t = Number(e.target.value)
            setUiT(clock.current.t)
          }}
          aria-label="Timeline"
        />
        <span className="mono time">
          {uiT.toFixed(2)} / {dur.toFixed(2)} s
        </span>
        {streaming && (
          <span className="pill bad live-pill" data-testid="live-streaming">
            <i className="live-dot" />
            {live?.preview ? 'search preview' : 'streaming'}
          </span>
        )}
        <div className="seg" role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button key={s} className={s === speed ? 'on' : ''} onClick={() => setSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
        <label className="chk">
          <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow
        </label>
        <label className="chk">
          <input type="checkbox" checked={trail} onChange={(e) => setTrail(e.target.checked)} /> trail
        </label>
      </div>
      {traj && <div className="muted small mono">{traj.model_id} · dt {traj.dt}s · {streaming ? `${live?.filled ?? 0}/${traj.pos.length}` : traj.pos.length} frames · seed {traj.meta.seed} · {traj.meta.note}</div>}
    </div>
  )
}
