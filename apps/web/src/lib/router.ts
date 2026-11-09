// Minimal hash router. No backend needed: the static bundle (and any static host) serves one index.html.
//   #/                      Home
//   #/projects              Dashboard
//   #/p/<id>/<tab>?v=<n>    Project workspace (tab = overview | assumptions | simulate | design | report | evidence)
//   #/lab/<sub>             Lab (autoresearch | live)
import { useEffect, useState } from 'react'

export const PROJECT_TABS = ['overview', 'assumptions', 'simulate', 'design', 'report', 'evidence'] as const
export type ProjectTab = (typeof PROJECT_TABS)[number]
export const LAB_SUBS = ['autoresearch', 'live'] as const
export type LabSub = (typeof LAB_SUBS)[number]

export type Route =
  | { name: 'home' }
  | { name: 'projects'; query: URLSearchParams }
  | { name: 'project'; id: string; tab: ProjectTab; query: URLSearchParams }
  | { name: 'lab'; sub: LabSub; query: URLSearchParams }
  | { name: 'notfound'; path: string }

export function parseHash(hash: string): Route {
  const raw = hash.replace(/^#/, '')
  const [pathPart, queryPart = ''] = raw.split('?')
  const query = new URLSearchParams(queryPart)
  const parts = pathPart.split('/').filter(Boolean)
  if (parts.length === 0) return { name: 'home' }
  if (parts[0] === 'projects' && parts.length === 1) return { name: 'projects', query }
  if (parts[0] === 'p' && parts.length >= 2 && parts.length <= 3) {
    const tab = (parts[2] ?? 'overview') as ProjectTab
    if (!PROJECT_TABS.includes(tab)) return { name: 'notfound', path: pathPart }
    return { name: 'project', id: decodeURIComponent(parts[1]), tab, query }
  }
  if (parts[0] === 'lab' && parts.length <= 2) {
    const sub = (parts[1] ?? 'autoresearch') as LabSub
    if (!LAB_SUBS.includes(sub)) return { name: 'notfound', path: pathPart }
    return { name: 'lab', sub, query }
  }
  return { name: 'notfound', path: pathPart }
}

export function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseHash(location.hash))
  useEffect(() => {
    const on = () => setRoute(parseHash(location.hash))
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  return route
}

export function projectHref(id: string, tab: ProjectTab = 'overview', query?: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined) q.set(k, String(v))
  const qs = q.toString()
  return `#/p/${encodeURIComponent(id)}/${tab}${qs ? `?${qs}` : ''}`
}

/** Navigate. `replace` keeps the history clean for state-only changes (e.g. variant selection). */
export function go(hash: string, replace = false) {
  if (replace) location.replace(hash)
  else location.hash = hash
}

/** Key that changes when the *page* changes (not just the query); used for scroll-to-top. */
export function pageKey(r: Route): string {
  switch (r.name) {
    case 'project':
      return `p/${r.id}/${r.tab}`
    case 'lab':
      return `lab/${r.sub}`
    case 'notfound':
      return `404/${r.path}`
    default:
      return r.name
  }
}
