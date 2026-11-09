import { useEffect, useState } from 'react'
import { ENGINE_API } from '../bundle'
import type { EngineHealth } from './types'

export interface HealthState {
  /** null until the first probe has finished. */
  checked: boolean
  /** The last /health answer; null when the engine did not answer. */
  health: EngineHealth | null
  error: string | null
}

/** Polls GET /health of the local engine (default every 3 s). Never throws; "engine down" is a normal state. */
export function useEngineHealth(onChange?: (up: boolean) => void, intervalMs = 3000): HealthState {
  const [state, setState] = useState<HealthState>({ checked: false, health: null, error: null })

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const probe = async () => {
      const ctl = new AbortController()
      const to = setTimeout(() => ctl.abort(), 2000)
      let next: HealthState
      try {
        const r = await fetch(`${ENGINE_API}/health`, { signal: ctl.signal })
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const j = (await r.json()) as EngineHealth
        next = { checked: true, health: j.ok === false ? null : j, error: j.ok === false ? 'engine reports not ok' : null }
      } catch (e) {
        next = { checked: true, health: null, error: (e as Error).message }
      } finally {
        clearTimeout(to)
      }
      if (!alive) return
      setState(next)
      onChange?.(next.health !== null)
      timer = setTimeout(probe, intervalMs)
    }
    void probe()
    return () => {
      alive = false
      clearTimeout(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [intervalMs])

  return state
}
