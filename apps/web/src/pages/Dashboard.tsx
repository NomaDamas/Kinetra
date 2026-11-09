import { useState } from 'react'
import type { DemoIndex } from '../bundle'
import { fmt } from '../bundle'
import { NewIdea } from '../components/NewIdea'
import { Empty, ErrorBox, Loading, PageHead, StatusBadge } from '../components/ui'
import { VariantStrip } from '../components/VariantStrip'
import { useProjects, type Async, type ProjectRec } from '../lib/data'
import { projectHref } from '../lib/router'
import { designSnapshot, heroIndex, lastRunLabel } from '../lib/summary'
import { pct, shortStatus, templateTitle, trim } from '../util'

interface Props {
  index: Async<DemoIndex>
  idx: DemoIndex | null
}

export function Dashboard({ index, idx }: Props) {
  const [bump] = useState(0)
  const projects = useProjects(idx, bump)
  return (
    <div className="stack">
      <PageHead
        eyebrow="Projects"
        title="Every idea, one honest status"
        sub="One card per idea. The numbers come from the recorded runs and design files; open a project for the answer, the parts and the report."
      />
      <section className="panel" aria-labelledby="new-idea-h">
        <h2 id="new-idea-h">New idea</h2>
        <p className="muted small">Describe a physical idea in one sentence. Ideas matching a recorded project open instantly; anything else runs on your local engine.</p>
        <NewIdea index={idx} />
      </section>

      {index.status === 'loading' && <Loading what="demo bundle" />}
      {index.status === 'error' && (
        <ErrorBox title="Demo bundle not found" error={index.error}>
          <p className="small">Expected <code>/demo/index.json</code>. Build it with <code>packages/engine/scripts/build_*_bundle.py</code>{import.meta.env.DEV && <>, or open this page with <code>?fixtures=1</code> for dev fixtures</>}.</p>
        </ErrorBox>
      )}
      {index.status === 'ok' && projects.status === 'loading' && <Loading what="projects" />}
      {projects.status === 'error' && <ErrorBox title="Projects could not be loaded" error={projects.error} />}
      {projects.status === 'ok' && (
        <>
          {projects.data.failed.map((f) => (
            <ErrorBox key={f.id} title={`Project “${f.id}” failed to load`} error={f.error} />
          ))}
          {projects.data.projects.length === 0 ? (
            <Empty title="No projects yet">Submit an idea above to create the first one.</Empty>
          ) : (
            <div className="project-grid">
              {projects.data.projects.map((p) => <ProjectCard key={p.id} p={p} />)}
            </div>
          )}
        </>
      )}
    </div>
  )
}

function ProjectCard({ p }: { p: ProjectRec }) {
  const s = p.rec.scenario
  const hi = heroIndex(s)
  const hero = s.variants[hi]
  const v = hero.verdict
  const sh = shortStatus(v)
  const f = v.feasibility
  const snap = p.design ? designSnapshot(p.design.brief) : null
  const bc = v.binding_constraint
  const feasible = s.variants.filter((x) => x.verdict.status === 'FEASIBLE_FOUND').length
  return (
    <article className="pcard">
      <header>
        <div>
          <div className="eyebrow">{templateTitle(s.template)}{p.rec.local ? ' · local run' : ''}</div>
          <h3><a href={projectHref(p.id, 'overview')}>{s.title ?? p.id}</a></h3>
        </div>
        <StatusBadge verdict={v} />
      </header>
      <p className="small muted pcard-idea">{s.idea}</p>

      <div className="pcard-nums">
        <div>
          <div className="stat-l">p_success {s.variants.length > 1 ? `@ ${trim(hero.value)} ${s.control.unit}` : ''}</div>
          <div className="stat-v mono">{f.n_samples > 0 ? pct(f.p_success) : '—'}</div>
          <div className="stat-s">{f.n_samples > 0 ? `95% CI ${pct(f.ci_low)} to ${pct(f.ci_high)} · n=${f.n_samples}` : sh.strength}</div>
        </div>
        <div>
          <div className="stat-l">Binding constraint</div>
          <div className="stat-v small-v mono" title={bc?.name}>{bc?.name.split(' (')[0] ?? '—'}</div>
          <div className="stat-s">{bc ? `margin ${bc.margin >= 0 ? '+' : ''}${fmt(bc.margin)} ${bc.unit}` : 'none reported'}</div>
        </div>
      </div>

      <div className="pcard-design">
        <div className="stat-l">Design{p.design?.origin === 'fixture' && <span className="pill bad tiny" title="Sample from apps/web/fixtures, not engine output">DEV FIXTURE</span>}</div>
        {snap ? (
          <div className="row small">
            <span className="mono">{snap.massAddedKg !== null ? `+${fmt(snap.massAddedKg, 4)} kg` : 'mass n/a'}</span>
            <span className="pill ok">{snap.ok} ok</span>
            {snap.custom > 0 && <span className="pill recorded">{snap.custom} custom</span>}
            {snap.sourcing > 0 && <span className="pill warn">{snap.sourcing} needs sourcing</span>}
            {snap.fail > 0 && <span className="pill bad">{snap.fail} miss</span>}
          </div>
        ) : (
          <div className="small muted">{p.rec.local ? 'not generated for local runs' : 'no design.json yet'}</div>
        )}
      </div>

      {s.variants.length > 1 && (
        <div className="pcard-cmp">
          <div className="stat-l">{s.control.label}: {feasible}/{s.variants.length} recorded values feasible</div>
          <VariantStrip control={s.control} variants={s.variants} active={hi} compact />
        </div>
      )}

      <footer>
        <span className="small muted">Last run {lastRunLabel(p.rec.builtAt, p.design?.brief.reproducibility.generated_at ?? null)}</span>
        <a className="btn primary" href={projectHref(p.id, 'overview')}>Open project →</a>
      </footer>
    </article>
  )
}
