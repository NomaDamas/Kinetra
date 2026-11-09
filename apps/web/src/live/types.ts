// Live-mode protocol types (local engine: ws://localhost:8000/ws/sim, REST GET /health).
// Everything the engine streams is real MuJoCo output; nothing in this folder simulates physics.
import type { ContactEvent, TrajBody } from '../types'

export type LiveTemplate = 'rocket_car' | 'humanoid_jump'
export type LiveMode = 'sim' | 'search'

/**
 * Mutable streaming state shared between the live hook (writer) and Scene/Replay (readers).
 * The Trajectory it describes is preallocated and mutated in place; `filled` is the number of valid frames.
 */
export interface LiveHandle {
  filled: number
  /** True while frames are still arriving (play/scrub disabled, clock follows the frontier). */
  active: boolean
  /** Flame normaliser for `thrust_*` series (from the engine's start message). */
  seriesMax?: Record<string, number>
  /** Bumped whenever already-filled frames are overwritten (search preview, replay_start) so the trail is rebuilt. */
  rev?: number
  /** True while the content is a full best-so-far rollout (search preview): the view loops it instead of following the frontier. */
  preview?: boolean
}

// ---- REST ----
export interface EngineHealth {
  ok: boolean
  templates?: string[]
  mujoco_version?: string
  live?: {
    protocol?: number
    templates?: string[]
    search?: string[]
    version_note?: string
  }
}

// ---- client -> server ----
export interface LiveStartReq {
  type: 'start'
  template: LiveTemplate
  mode: LiveMode
  params?: Record<string, number>
  overrides?: Record<string, number>
  seed?: number
  /** 1 = real time, 0 = unpaced (max). */
  speed?: number
  rescale_throttle?: boolean
  rescale_from?: number
  search?: { max_seconds?: number; preview_every?: number }
}

// ---- server -> client ----
export interface LiveChartSpec {
  series: string
  label: string
  unit: string
}

export interface LiveStart {
  type: 'start'
  run_id: number
  mode: LiveMode
  template: string
  model_id: string
  model_hash: string
  mujoco_version: string
  dt: number
  physics_dt?: number
  n_frames_max: number
  bodies: TrajBody[]
  series: { name: string; unit: string }[]
  series_max?: Record<string, number>
  charts?: LiveChartSpec[]
  params?: Record<string, number>
  overrides?: Record<string, number>
  seed: number
  speed?: number
  compute?: 'incremental' | 'batch'
  note?: string
}

export interface LiveFrames {
  type: 'frames'
  i0: number
  pos: [number, number, number][][]
  quat: [number, number, number, number][][]
  series?: Record<string, number[]>
  t?: number
  steps?: number
  compute_ms?: number
}

export interface LiveProgress {
  type: 'progress'
  gen: number
  evals: number
  best_cost: number
  success: boolean
  elapsed_s: number
  evals_per_s: number
  restart?: number
  popsize?: number
  stopped_by?: string
}

export interface LivePreview {
  type: 'preview'
  gen: number
  cost: number
  success: boolean
  n_frames: number
  pos: [number, number, number][][]
  quat: [number, number, number, number][][]
  series?: Record<string, number[]>
}

export interface LiveSearchDone {
  type: 'search_done'
  found: boolean
  best_cost: number
  evals: number
  wall_s: number
  evals_per_s: number
  generations: number
  params?: Record<string, number>
  stopped_by: string
}

export interface LiveReplayStart {
  type: 'replay_start'
  params?: Record<string, number>
}

export interface LiveDisplayItem {
  key: string
  label: string
  value: number | string | boolean
  unit: string
  ok: boolean | null
  threshold?: string
}

export interface LivePerf {
  steps: number
  sim_time_s: number
  compute_ms: number
  us_per_step: number
  steps_per_s: number
  realtime_factor: number
  frames: number
  compute?: string
}

export interface LiveResult {
  type: 'result'
  mode: LiveMode
  success: boolean
  failed_checks: string[]
  display: LiveDisplayItem[]
  perf: LivePerf
  mujoco_version: string
  seed: number
  params?: Record<string, number>
  overrides?: Record<string, number>
  events: ContactEvent[]
  n_frames: number
  trajectory_sha256: string
}
