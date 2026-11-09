// WebSocket client for the local engine's live simulation (ws://localhost:8000/ws/sim).
//
// Streaming model: when the first frames (or the first search preview) arrive, a Trajectory with `n_frames_max`
// entries is preallocated and published ONCE; later messages mutate it in place, so Scene's memo/camera never reset.
// `LiveHandle.filled` says how many frames are valid. Nothing here invents data: every number comes from an engine message.
import { useCallback, useEffect, useReducer, useRef } from 'react'
import { ENGINE_WS } from '../bundle'
import type { TemplateId, Trajectory } from '../types'
import type {
  LiveFrames,
  LiveHandle,
  LivePreview,
  LiveProgress,
  LiveReplayStart,
  LiveResult,
  LiveSearchDone,
  LiveStart,
  LiveStartReq,
} from './types'

export type Phase = 'idle' | 'connecting' | 'running' | 'searching' | 'done' | 'stopped' | 'error'

export interface FrameStats {
  steps: number
  compute_ms: number
  t: number
}

export interface LiveSnapshot {
  phase: Phase
  /** Header of the current/last run. */
  header: LiveStart | null
  /** Published (preallocated) trajectory; null until the first frame of a run has arrived. */
  traj: Trajectory | null
  handle: LiveHandle | null
  /** run_id of the run that `traj` belongs to (compare with header.run_id to detect a stale view). */
  trajRunId: number | null
  result: LiveResult | null
  progress: LiveProgress | null
  progressHist: LiveProgress[]
  preview: { gen: number; cost: number; success: boolean } | null
  searchDone: LiveSearchDone | null
  /** True once the server switched to streaming the best params after a search. */
  replaying: boolean
  frameStats: FrameStats | null
  error: string | null
  /** Request that produced the current run. */
  req: LiveStartReq | null
}

interface RunState {
  traj: Trajectory
  handle: LiveHandle
  published: boolean
  nmax: number
  runId: number
}

function emptySnapshot(): LiveSnapshot {
  return {
    phase: 'idle',
    header: null,
    traj: null,
    handle: null,
    trajRunId: null,
    result: null,
    progress: null,
    progressHist: [],
    preview: null,
    searchDone: null,
    replaying: false,
    frameStats: null,
    error: null,
    req: null,
  }
}

function allocRun(h: LiveStart): RunState {
  const n = Math.max(1, Math.floor(h.n_frames_max))
  const zeroPos: [number, number, number] = [0, 0, 0]
  const idQuat: [number, number, number, number] = [1, 0, 0, 0]
  const nb = h.bodies.length
  const traj: Trajectory = {
    schema_version: '0.1.0',
    model_id: h.model_id,
    model_hash: h.model_hash,
    dt: h.dt,
    bodies: h.bodies,
    pos: Array.from({ length: n }, () => Array.from({ length: nb }, () => zeroPos)),
    quat: Array.from({ length: n }, () => Array.from({ length: nb }, () => idQuat)),
    events: [],
    series: h.series.map((s) => ({ name: s.name, unit: s.unit, values: new Array<number>(n).fill(0) })),
    meta: {
      seed: h.seed,
      mujoco_version: h.mujoco_version,
      template_id: h.template as TemplateId,
      params: h.params ?? {},
      note: h.note ?? '',
    },
  }
  const handle: LiveHandle = { filled: 0, active: true, seriesMax: h.series_max, rev: 0, preview: false }
  return { traj, handle, published: false, nmax: n, runId: h.run_id }
}

/** Write frames [i0, i0+len) into the preallocated trajectory (clamped to n_frames_max). Returns the new frame count. */
function writeFrames(
  r: RunState,
  i0: number,
  pos: LiveFrames['pos'],
  quat: LiveFrames['quat'],
  series: Record<string, number[]> | undefined,
): number {
  const { traj, nmax } = r
  const len = Math.min(pos.length, quat.length, nmax - i0)
  for (let k = 0; k < len; k++) {
    traj.pos[i0 + k] = pos[k]
    traj.quat[i0 + k] = quat[k]
  }
  if (series) {
    for (const [name, vals] of Object.entries(series)) {
      let s = traj.series.find((x) => x.name === name)
      if (!s) {
        // lenient: a series that was not announced in `start`
        s = { name, unit: '', values: new Array<number>(nmax).fill(0) }
        traj.series.push(s)
      }
      const m = Math.min(vals.length, nmax - i0)
      for (let k = 0; k < m; k++) s.values[i0 + k] = vals[k]
    }
  }
  return Math.max(0, i0 + len)
}

/** Replace the not-yet-simulated tail with the first frame so camera/scale framing is valid from the start. */
function fillTailWithFirst(r: RunState, from: number) {
  const { traj, nmax } = r
  if (from <= 0) return
  for (let i = from; i < nmax; i++) {
    traj.pos[i] = traj.pos[0]
    traj.quat[i] = traj.quat[0]
  }
}

function trimRun(r: RunState, n: number) {
  const k = Math.max(1, Math.min(n, r.nmax))
  r.traj.pos.length = k
  r.traj.quat.length = k
  for (const s of r.traj.series) s.values.length = k
  r.handle.filled = k
}

export interface LiveSim extends LiveSnapshot {
  run: (req: LiveStartReq) => void
  /** Re-run the last start request (as a fresh `start`). */
  restart: () => void
  stop: () => void
  reset: () => void
}

export function useLiveSim(): LiveSim {
  const [, force] = useReducer((x: number) => x + 1, 0)
  const snap = useRef<LiveSnapshot>(emptySnapshot())
  const run = useRef<RunState | null>(null)
  const ws = useRef<WebSocket | null>(null)
  const opening = useRef<Promise<WebSocket> | null>(null)
  const seq = useRef(0)
  /** Waiting for the `start` message of a just-sent request: everything before it belongs to the previous run. */
  const pendingStart = useRef(false)
  /** After a client-side stop, in-flight messages of the cancelled run are dropped. */
  const ignoring = useRef(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mounted = useRef(true)

  const bump = useCallback((immediate: boolean) => {
    if (!mounted.current) return
    if (immediate) {
      if (timer.current) {
        clearTimeout(timer.current)
        timer.current = null
      }
      force()
      return
    }
    if (timer.current) return
    timer.current = setTimeout(() => {
      timer.current = null
      if (mounted.current) force()
    }, 60)
  }, [])

  const isActive = (p: Phase) => p === 'connecting' || p === 'running' || p === 'searching'

  /** Stop treating the run as streaming; keep the frames that arrived so far (honestly partial). */
  const freeze = useCallback(() => {
    const r = run.current
    if (!r) return
    r.handle.active = false
    r.handle.preview = false
    if (r.published) trimRun(r, r.handle.filled)
  }, [])

  const publish = useCallback((r: RunState) => {
    if (r.published) return
    r.published = true
    snap.current.traj = r.traj
    snap.current.handle = r.handle
    snap.current.trajRunId = r.runId
  }, [])

  const onMessage = useCallback(
    (socket: WebSocket, ev: MessageEvent) => {
      if (socket !== ws.current || typeof ev.data !== 'string') return
      let m: { type?: string } & Record<string, unknown>
      try {
        m = JSON.parse(ev.data) as typeof m
      } catch {
        return
      }
      const s = snap.current
      const type = m.type

      if (type === 'start') {
        if (ignoring.current) return
        pendingStart.current = false
        const h = m as unknown as LiveStart
        const r = allocRun(h)
        run.current = r
        s.header = h
        s.result = null
        s.progress = null
        s.progressHist = []
        s.preview = null
        s.searchDone = null
        s.replaying = false
        s.frameStats = null
        s.error = null
        s.phase = h.mode === 'search' ? 'searching' : 'running'
        // keep showing the previous run's view until this run has frames to show
        bump(true)
        return
      }
      if (type === 'error') {
        if (ignoring.current) return
        pendingStart.current = false
        freeze()
        s.error = typeof m.message === 'string' ? m.message : 'engine reported an error'
        s.phase = 'error'
        bump(true)
        return
      }
      if (type === 'stopped') {
        // the reply to our own `stop` (or to a request that was superseded) must not stop a newer run
        if (!pendingStart.current && !ignoring.current && isActive(s.phase)) {
          freeze()
          s.phase = 'stopped'
          bump(true)
        }
        return
      }
      if (pendingStart.current || ignoring.current) return
      const r = run.current
      if (!r) return

      switch (type) {
        case 'frames': {
          const f = m as unknown as LiveFrames
          const n = writeFrames(r, f.i0, f.pos, f.quat, f.series)
          if (!r.published && f.i0 === 0 && n > 0) {
            fillTailWithFirst(r, n)
            publish(r)
          }
          r.handle.filled = Math.max(n, 0)
          r.handle.active = true
          r.handle.preview = false
          if (typeof f.steps === 'number' && typeof f.compute_ms === 'number') {
            s.frameStats = { steps: f.steps, compute_ms: f.compute_ms, t: f.t ?? (n - 1) * r.traj.dt }
          }
          bump(!r.published)
          return
        }
        case 'progress': {
          const p = m as unknown as LiveProgress
          s.progress = p
          s.progressHist = [...s.progressHist, p]
          bump(false)
          return
        }
        case 'preview': {
          const p = m as unknown as LivePreview
          const n = writeFrames(r, 0, p.pos, p.quat, p.series)
          if (n > 0) {
            if (!r.published) {
              fillTailWithFirst(r, n)
              publish(r)
            }
            r.handle.filled = n
            r.handle.rev = (r.handle.rev ?? 0) + 1
            r.handle.active = true
            r.handle.preview = true
          }
          s.preview = { gen: p.gen, cost: p.cost, success: p.success }
          bump(!r.published)
          return
        }
        case 'search_done': {
          s.searchDone = m as unknown as LiveSearchDone
          bump(true)
          return
        }
        case 'replay_start': {
          // the best params are now streamed as a normal sim into the same preallocated trajectory
          s.replaying = true
          s.phase = 'running'
          const rs = m as unknown as LiveReplayStart
          if (rs.params) r.traj.meta.params = rs.params
          r.handle.filled = 0
          r.handle.rev = (r.handle.rev ?? 0) + 1
          r.handle.preview = false
          r.handle.active = true
          bump(true)
          return
        }
        case 'result': {
          const res = m as unknown as LiveResult
          const n = res.n_frames > 0 ? res.n_frames : r.handle.filled
          if (r.published) trimRun(r, n)
          r.traj.events = res.events ?? []
          if (res.params) r.traj.meta.params = res.params
          r.handle.active = false
          r.handle.preview = false
          s.result = res
          s.phase = 'done'
          bump(true)
          return
        }
        default:
          return // unknown message types are ignored
      }
    },
    [bump, freeze, publish],
  )

  const onClose = useCallback(
    (socket: WebSocket) => {
      if (socket !== ws.current) return
      ws.current = null
      opening.current = null
      const s = snap.current
      if (isActive(s.phase)) {
        freeze()
        s.phase = 'error'
        s.error =
          'Connection to the local engine was lost mid-run. No data was invented: frames received so far are kept as-is. Check that the engine is still running, then press "Run live" to reconnect.'
        bump(true)
      }
    },
    [bump, freeze],
  )

  const connect = useCallback((): Promise<WebSocket> => {
    const cur = ws.current
    if (cur && cur.readyState === WebSocket.OPEN) return Promise.resolve(cur)
    if (cur && cur.readyState === WebSocket.CONNECTING && opening.current) return opening.current
    const sock = new WebSocket(ENGINE_WS)
    ws.current = sock
    const p = new Promise<WebSocket>((resolve, reject) => {
      sock.onopen = () => resolve(sock)
      sock.onerror = () => reject(new Error(`could not open ${ENGINE_WS}`))
    })
    opening.current = p
    sock.onmessage = (e) => onMessage(sock, e)
    sock.onclose = () => onClose(sock)
    return p
  }, [onMessage, onClose])

  const runReq = useCallback(
    (req: LiveStartReq) => {
      const my = ++seq.current
      const s = snap.current
      // the previous run (if any) is cancelled server-side by this `start`
      if (run.current) {
        run.current.handle.active = false
        run.current.handle.preview = false
      }
      s.req = req
      s.error = null
      s.phase = 'connecting'
      s.result = null
      s.searchDone = null
      s.progress = null
      s.progressHist = []
      s.preview = null
      s.replaying = false
      s.frameStats = null
      pendingStart.current = true
      ignoring.current = false
      bump(true)
      connect()
        .then((sock) => {
          if (my !== seq.current) return
          sock.send(JSON.stringify(req))
        })
        .catch((e: Error) => {
          if (my !== seq.current) return
          pendingStart.current = false
          s.phase = 'error'
          s.error = `Could not reach the live engine (${e.message}). Start it with the command shown above; nothing was simulated.`
          if (ws.current && ws.current.readyState !== WebSocket.OPEN) {
            ws.current = null
            opening.current = null
          }
          bump(true)
        })
    },
    [bump, connect],
  )

  const restart = useCallback(() => {
    const prev = snap.current.req
    if (prev) runReq(prev) // a fresh `start` (not {type:'restart'}) also works after a reconnect, when the server has no previous request
  }, [runReq])

  const stop = useCallback(() => {
    const s = snap.current
    if (!isActive(s.phase)) return
    seq.current++ // a start that is still waiting for the socket must not be sent
    const sock = ws.current
    if (sock && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: 'stop' }))
    ignoring.current = true
    pendingStart.current = false
    freeze()
    s.phase = 'stopped'
    bump(true)
  }, [bump, freeze])

  const reset = useCallback(() => {
    const sock = ws.current
    if (isActive(snap.current.phase) && sock && sock.readyState === WebSocket.OPEN) sock.send(JSON.stringify({ type: 'stop' }))
    seq.current++
    ignoring.current = true
    pendingStart.current = false
    run.current = null
    snap.current = emptySnapshot()
    bump(true)
  }, [bump])

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      clearTimeout(timer.current ?? undefined)
      const sock = ws.current
      ws.current = null
      if (sock) {
        sock.onmessage = null
        sock.onclose = null
        sock.close()
      }
    }
  }, [])

  return { ...snap.current, run: runReq, restart, stop, reset }
}
