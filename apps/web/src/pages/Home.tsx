import type { DemoIndex } from '../bundle'
import { fmt } from '../bundle'
import { NewIdea } from '../components/NewIdea'
import { Loading } from '../components/ui'
import { WHY } from '../content/why'
import { useProjects } from '../lib/data'
import { projectHref } from '../lib/router'
import { designSnapshot, heroIndex } from '../lib/summary'
import { evalsOf, pct, shortStatus, templateTitle, trim } from '../util'

const STATUS_TONE: Record<string, string> = { FEASIBLE_FOUND: 'ok', INFEASIBLE_NECESSARY_CONDITION: 'bad', NOT_FOUND_IN_BUDGET: 'weak' }

export function Home({ index }: { index: DemoIndex | null }) {
  const projects = useProjects(index, 0)
  return (
    <div className="home">
      <section className="hero-home">
        <div className="eyebrow">Kinetra · design brief lab</div>
        <h1 className="hero-h">{WHY.oneLiner.en}</h1>
        <p className="hero-ko" lang="ko">{WHY.oneLiner.ko}</p>
        <p className="sub">{WHY.subLine.en}</p>
        <div className="row cta-row">
          {WHY.ctas.map((c) => (
            <a key={c.href} className={`btn ${c.kind === 'primary' ? 'primary big' : 'big'}`} href={c.href}>{c.label}</a>
          ))}
        </div>
      </section>

      <section className="home-sec" aria-labelledby="try-h">
        <h2 id="try-h" className="sec-h">Try an idea</h2>
        <NewIdea index={index} />
      </section>

      <section className="home-sec" aria-labelledby="problem-h">
        <h2 id="problem-h" className="sec-h">{WHY.problemTitle}</h2>
        <p className="sec-intro">{WHY.problemIntro}</p>
        <div className="problem-grid">
          {WHY.problem.map((p) => (
            <figure className="pfig" key={p.sourceUrl}>
              <div className="pfig-v mono">{p.value}</div>
              <figcaption>
                <p>{p.text}</p>
                <p className="caveat"><b>Caveat.</b> {p.caveat}</p>
                <a className="small" href={p.sourceUrl} target="_blank" rel="noreferrer">{p.sourceLabel} ↗</a>
              </figcaption>
            </figure>
          ))}
        </div>
      </section>

      <section className="home-sec" aria-labelledby="get-h">
        <h2 id="get-h" className="sec-h">{WHY.whatYouGetTitle}</h2>
        <div className="tiles">
          {WHY.whatYouGet.map((s, i) => (
            <div className="tile" key={s.title}>
              <span className="tile-n mono">{i + 1}</span>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-sec" aria-labelledby="how-h">
        <h2 id="how-h" className="sec-h">{WHY.howItWorksTitle}</h2>
        <ol className="flow">
          {WHY.howItWorks.map((s, i) => (
            <li key={s.title}>
              <span className="flow-n mono">{i + 1}</span>
              <div><b>{s.title}</b><p>{s.body}</p></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="home-sec" aria-labelledby="proof-h">
        <h2 id="proof-h" className="sec-h">Proof, from the recorded runs</h2>
        <p className="sec-intro">Computed live from the bundle files in this site, not typed in. Each is a seeded, reproducible run of the template, with the verdict the strength rules allow.</p>
        {projects.status === 'loading' && <Loading what="recorded runs" />}
        {projects.status === 'error' && <div className="state err" role="alert">Recorded runs could not be loaded: {projects.error}</div>}
        {projects.status === 'ok' && (
          <div className="proof-grid">
            {projects.data.projects.filter((p) => !p.rec.local).map((p) => {
              const s = p.rec.scenario
              const hero = s.variants[heroIndex(s)]
              const fe = s.variants.filter((v) => v.verdict.status === 'FEASIBLE_FOUND')
              const impossible = s.variants.filter((v) => v.verdict.status === 'INFEASIBLE_NECESSARY_CONDITION')
              const notFound = s.variants.filter((v) => v.verdict.status === 'NOT_FOUND_IN_BUDGET')
              const f = hero.verdict.feasibility
              const snap = p.design ? designSnapshot(p.design.brief) : null
              return (
                <article className="proof" key={p.id}>
                  <header>
                    <div className="eyebrow">{templateTitle(s.template)}</div>
                    <h3><a href={projectHref(p.id)}>{s.title ?? p.id}</a></h3>
                  </header>
                  <p className="small muted">{s.tagline}</p>
                  <div className="proof-sweep">
                    <b className="mono">{s.variants.length}</b> recorded values of <i>{s.control.label.toLowerCase()}</i> ({trim(s.variants[0].value)} to {trim(s.variants[s.variants.length - 1].value)} {s.control.unit}):
                    <div className="row">
                      {impossible.length > 0 && <span className="pill bad">{impossible.length} impossible under assumptions</span>}
                      {notFound.length > 0 && <span className="pill weak">{notFound.length} not found in budget (weak)</span>}
                      {fe.length > 0 && <span className="pill ok">{fe.length} feasible</span>}
                    </div>
                  </div>
                  <div className="proof-hero">
                    <span className={`pill ${STATUS_TONE[hero.verdict.status] ?? ''}`}>{shortStatus(hero.verdict).label}</span>
                    <span className="mono">
                      {f.n_samples > 0 ? <>p_success {pct(f.p_success)} <span className="muted">[{pct(f.ci_low)}, {pct(f.ci_high)}] n={f.n_samples}</span></> : 'not sampled'}
                    </span>
                    <span className="muted small">at {trim(hero.value)} {s.control.unit}{evalsOf(hero.verdict) ? ` · ${evalsOf(hero.verdict)!.toLocaleString('en-US')} evals` : ''}</span>
                  </div>
                  {snap && (
                    <div className="small">Design: <b className="mono">+{snap.massAddedKg !== null ? fmt(snap.massAddedKg, 4) : '?'} kg</b> · {snap.ok}/{snap.total} components meet requirements · {snap.custom} custom · {snap.sourcing} need sourcing</div>
                  )}
                  <a className="btn" href={projectHref(p.id)}>Open the project →</a>
                </article>
              )
            })}
          </div>
        )}
      </section>

      <section className="home-sec" aria-labelledby="who-h">
        <h2 id="who-h" className="sec-h">{WHY.personasTitle}</h2>
        <div className="tiles three">
          {WHY.personas.map((p) => (
            <div className="tile" key={p.id}>
              <h3>{p.who}</h3>
              <p><b>Decision.</b> {p.decision}</p>
              <p><b>Puts in.</b> {p.input}</p>
              <p><b>Walks away with.</b> {p.output}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="home-sec" aria-labelledby="rules-h">
        <h2 id="rules-h" className="sec-h">What we are allowed to claim</h2>
        <div className="tiles three">
          {WHY.verdictRules.map((r) => (
            <div className={`tile rule ${STATUS_TONE[r.status] ?? ''}`} key={r.status}>
              <div className="mono rule-s">{r.status}</div>
              <p>{r.meaning}</p>
              <b className="small">{r.strength}</b>
            </div>
          ))}
        </div>
      </section>

      <section className="home-sec" aria-labelledby="not-h">
        <h2 id="not-h" className="sec-h">{WHY.notClaimsTitle}</h2>
        <ul className="notclaims">
          {WHY.notClaims.map((n) => <li key={n}>{n}</li>)}
        </ul>
        <p className="small"><a href={WHY.readMoreUrl} target="_blank" rel="noreferrer">Read the long-form argument ↗</a></p>
        <div className="row cta-row">
          {WHY.ctas.map((c) => (
            <a key={c.href} className={`btn ${c.kind === 'primary' ? 'primary big' : 'big'}`} href={c.href}>{c.label}</a>
          ))}
        </div>
      </section>
    </div>
  )
}
