import { useEffect, useRef } from 'react'
import { IS_FIXTURE } from './bundle'
import { useIndex } from './lib/data'
import { pageKey, projectHref, useRoute } from './lib/router'
import { useEngineHealth } from './live/useEngineHealth'
import { Home } from './pages/Home'
import { Dashboard } from './pages/Dashboard'
import { Project } from './pages/Project'
import { Lab } from './pages/Lab'
import { ErrorBox } from './components/ui'

export default function App() {
  const route = useRoute()
  const index = useIndex()
  const { health, checked } = useEngineHealth(undefined, 5000)
  const engineUp = health !== null
  const key = pageKey(route)
  const prev = useRef<string | null>(null)
  const main = useRef<HTMLElement>(null)

  // New page => start at the top and move focus to the content (keyboard / screen-reader users). State-only changes (?v=) keep scroll.
  useEffect(() => {
    if (prev.current !== null && prev.current !== key) {
      const sameProject = prev.current.split('/')[1] === key.split('/')[1] && key.startsWith('p/') && prev.current.startsWith('p/')
      if (!sameProject) window.scrollTo({ top: 0 })
    }
    prev.current = key
  }, [key])

  const nav = (name: string) => (route.name === name ? 'on' : '')
  const idx = index.status === 'ok' ? index.data : null

  return (
    <div className="app">
      <a className="skip" href="#main" onClick={(e) => { e.preventDefault(); main.current?.focus() }}>Skip to content</a>
      <header className="topbar">
        <a className="brand" href="#/" aria-label="Kinetra home">
          <span className="logo">K</span>
          <b>Kinetra</b>
          <span className="muted brand-sub">design brief lab</span>
        </a>
        <nav className="tabs" aria-label="Main">
          <a className={nav('home')} href="#/" aria-current={route.name === 'home' ? 'page' : undefined}>Home</a>
          <a className={nav('projects') || (route.name === 'project' ? 'on' : '')} href="#/projects" aria-current={route.name === 'projects' ? 'page' : undefined}>Projects</a>
          <a className={nav('lab')} href="#/lab" aria-current={route.name === 'lab' ? 'page' : undefined}>Lab</a>
        </nav>
        <div className="top-r">
          {IS_FIXTURE && <span className="pill bad" title="Dev fixtures from spike outputs: NOT real engine bundles">DEV FIXTURES</span>}
          <span className={`pill ${!checked ? 'muted-pill' : engineUp ? 'ok' : 'muted-pill'}`} title="Local engine API at http://localhost:8000; needed only for LIVE runs and new ideas">
            {!checked ? 'engine: checking…' : engineUp ? 'local engine: online' : 'local engine: offline'}
          </span>
        </div>
      </header>

      <main className="main" id="main" tabIndex={-1} ref={main}>
        {route.name === 'home' && <Home index={idx} />}
        {route.name === 'projects' && <Dashboard index={index} idx={idx} />}
        {route.name === 'project' && <Project key={route.id} id={route.id} tab={route.tab} query={route.query} engineUp={engineUp} index={idx} />}
        {route.name === 'lab' && <Lab sub={route.sub} index={index} idx={idx} onEngineUp={() => {}} />}
        {route.name === 'notfound' && (
          <ErrorBox title="Page not found" error={`#/${route.path}`}>
            <p className="small"><a href="#/">Home</a> · <a href="#/projects">Projects</a> · <a href={projectHref('roadster')}>Example project</a></p>
          </ErrorBox>
        )}
      </main>

      <footer className="foot">
        <div className="foot-grid">
          <div>
            <b>Judge = MuJoCo, Actor = Three.js.</b> Every number in a verdict comes from simulation tools, never from a language model. Three.js only replays a stored trajectory.
            <div className="muted small">Verdict asymmetry: found = strong · necessary condition violated = strong "impossible under assumptions" · not found in budget = weak, never proof.</div>
          </div>
          <div>
            <b>What this does not judge / limits</b>
            <ul>
              <li>CFD, thermal and FEA effects are not modelled; labelled "simplified model" where relevant. Part checks are hand calculations that need FEA.</li>
              <li>Recorded runs are seeded and reproducible, not live compute; the research step reads a curated catalog, not the live web.</li>
              <li>Catalog values marked unverified / llm_estimate are placeholders to review.</li>
              <li>Autoresearch uses synthetic data; sim-to-real is not validated.</li>
              <li>Costs sum only cited prices; unpriced lines are counted, never treated as zero.</li>
            </ul>
          </div>
        </div>
      </footer>
    </div>
  )
}
