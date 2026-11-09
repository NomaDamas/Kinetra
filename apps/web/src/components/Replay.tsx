import { useCallback, useEffect, useRef, useState } from 'react'
import type { Trajectory } from '../types'
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
}

const SPEEDS = [0.1, 0.25, 0.5, 1, 2]

function duration(t: Trajectory | null) {
  return t ? Math.max(0, (t.pos.length - 1) * t.dt) : 0
}

export function Replay({ traj, loading, compare, compareLabel, mainLabel, playToken }: Props) {
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
  const dur = Math.max(duration(traj), compare ? duration(compare) : 0)
  const durRef = useRef(dur)
  durRef.current = dur

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
      if (playingRef.current && durRef.current > 0) {
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
          {traj ? <Scene traj={traj} clock={clock} follow={follow} trail={trail} /> : <div className="view-empty">{loading ? 'Loading trajectory…' : 'No trajectory'}</div>}
          {mainLabel && <span className="view-tag">{mainLabel}</span>}
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
        <button className="btn primary" onClick={toggle} disabled={!traj} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❚❚ Pause' : '▶ Play'}
        </button>
        <button
          className="btn"
          onClick={() => {
            clock.current.t = 0
            setUiT(0)
          }}
          disabled={!traj}
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
          disabled={!traj}
          onChange={(e) => {
            clock.current.t = Number(e.target.value)
            setUiT(clock.current.t)
          }}
          aria-label="Timeline"
        />
        <span className="mono time">
          {uiT.toFixed(2)} / {dur.toFixed(2)} s
        </span>
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
      {traj && <div className="muted small mono">{traj.model_id} · dt {traj.dt}s · {traj.pos.length} frames · seed {traj.meta.seed} · {traj.meta.note}</div>}
    </div>
  )
}
