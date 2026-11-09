// Static description of the live-mode controls. Ranges are UI bounds only; the engine validates and simulates.
import type { LiveTemplate } from './types'

export interface ParamDef {
  key: string
  label: string
  unit: string
  min: number
  max: number
  step: number
  /** Used when the recorded scenario has no assumption with this key. */
  fallback: number
  /** Extra explanation under the slider. */
  hint?: string
  /** Rendered inside the collapsed "more parameters" group. */
  optional?: boolean
  testId?: string
}

export interface TemplateCfg {
  template: LiveTemplate
  /** Recorded scenario id used for default spec values + stored witnesses. */
  scenarioTemplate: string
  title: string
  params: ParamDef[]
  /** Key of the recorded control (variant sweep) this template maps to. */
  controlKey: string
  searchNote: string
}

export const TEMPLATES: TemplateCfg[] = [
  {
    template: 'rocket_car',
    scenarioTemplate: 'rocket_car',
    title: 'Roadster (rocket_car)',
    controlKey: 'thruster_force_max',
    searchNote: 'CMA-ES over the 21-parameter thruster schedule (pitch, lift and roll burn windows)',
    params: [
      { key: 'thruster_force_max', label: 'Max thrust per nozzle', unit: 'N', min: 300, max: 12000, step: 100, fallback: 8000, testId: 'live-fmax-slider' },
      { key: 'vehicle_mass', label: 'Vehicle mass', unit: 'kg', min: 1000, max: 1700, step: 10, fallback: 1300 },
      {
        key: 'thrust_spread',
        label: 'Thrust spread (per-nozzle random error)',
        unit: '',
        min: 0,
        max: 0.1,
        step: 0.005,
        fallback: 0,
        hint: 'Each nozzle gets an independent random thrust error drawn from the seed below.',
      },
      { key: 'ramp_speed', label: 'Ramp speed', unit: 'm/s', min: 16, max: 28, step: 0.5, fallback: 22, optional: true },
    ],
  },
  {
    template: 'humanoid_jump',
    scenarioTemplate: 'humanoid_jump',
    title: 'Humanoid (humanoid_jump)',
    controlKey: 'torque_scale',
    searchNote: '',
    params: [
      { key: 'torque_scale', label: 'Motor torque scale', unit: '×', min: 0.1, max: 1, step: 0.05, fallback: 1 },
      { key: 'payload_kg', label: 'Payload', unit: 'kg', min: 0, max: 15, step: 0.5, fallback: 0 },
      { key: 'ground_friction', label: 'Ground friction', unit: '', min: 0.4, max: 1.2, step: 0.05, fallback: 0.8 },
      { key: 'robot_mass', label: 'Robot mass', unit: 'kg', min: 25, max: 45, step: 0.5, fallback: 33.34, optional: true },
    ],
  },
]

export const SPEEDS: { label: string; value: number }[] = [
  { label: '0.25×', value: 0.25 },
  { label: '0.5×', value: 0.5 },
  { label: '1×', value: 1 },
  { label: '2×', value: 2 },
  { label: 'max', value: 0 },
]

export const ENGINE_START_CMD = 'cd packages/engine && .venv/bin/uvicorn kinetra_engine.api:app --port 8000'
export const ENGINE_START_ALT = 'scripts/dev.sh'

export const STORED_SCHEDULE_NOTE =
  'The stored schedule is re-simulated under your new parameters (not re-optimised) — use "Run live search" to let CMA-ES re-optimise.'
