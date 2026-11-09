import type { Scenario, Variant } from '../bundle'
import type { DesignBundle } from '../lib/design'
import type { Async, ScenarioRec } from '../lib/data'
import type { ProjectTab } from '../lib/router'

export interface ProjectCtx {
  id: string
  rec: ScenarioRec
  scenario: Scenario
  vIdx: number
  variant: Variant
  /** Select a variant; `tab` optionally navigates in the same step. Writes ?v= so the state is in the URL. */
  setVariant: (i: number, opts?: { tab?: ProjectTab; extra?: Record<string, string> }) => void
  design: Async<DesignBundle>
  query: URLSearchParams
  engineUp: boolean
  approved: Record<string, boolean>
  setApproved: (k: string, v: boolean) => void
  edits: Record<string, number>
  setEdit: (k: string, v: number | null) => void
  hrefTo: (tab: ProjectTab, extra?: Record<string, string | number | undefined>) => string
}
