import { useEffect, useState } from 'react'
import { Markdown } from '../../components/Markdown'
import { Empty, ErrorBox, Loading, Panel } from '../../components/ui'
import { assetUrl, type DesignBundle } from '../../lib/design'
import type { ProjectCtx } from '../projectCtx'

type Text = { status: 'loading' } | { status: 'ok'; text: string } | { status: 'error'; error: string }

function useText(url: string | null): Text {
  const [s, setS] = useState<{ url: string | null; v: Text }>({ url, v: { status: 'loading' } })
  useEffect(() => {
    if (!url) return
    let live = true
    fetch(url, { cache: 'no-cache' })
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        const t = await r.text()
        // a SPA dev server answers missing files with index.html
        if (/^\s*<!doctype html/i.test(t)) throw new Error('file missing')
        return t
      })
      .then((text) => live && setS({ url, v: { status: 'ok', text } }))
      .catch((e: Error) => live && setS({ url, v: { status: 'error', error: `${url}: ${e.message}` } }))
    return () => {
      live = false
    }
  }, [url])
  if (!url) return { status: 'error', error: 'no design bundle' }
  return s.url === url ? s.v : { status: 'loading' }
}

export function ReportTab({ ctx }: { ctx: ProjectCtx }) {
  const d = ctx.design
  const bundle = d.status === 'ok' ? d.data : null
  const md = useText(bundle ? assetUrl(bundle, 'export/design-brief.md') : null)
  if (d.status === 'loading') return <Loading what="design brief" />
  if (d.status === 'error' || !bundle)
    return (
      <div className="stack">
        <Empty title="No design brief for this project yet">
          The report is assembled from <code>design.json</code>, <code>export/design-brief.md</code>, <code>export/bom.csv</code> and the CAD files. None of them exist for this project.
        </Empty>
        {d.status === 'error' && <ErrorBox title="Why it is empty" error={d.error} />}
      </div>
    )
  return (
    <div className="stack">
      {bundle.origin === 'fixture' && <div className="banner warn"><b>DEV FIXTURE</b> · sample files from <code>apps/web/fixtures/design</code>, not engine output.</div>}
      <Downloads bundle={bundle} />
      <Panel title="Design brief" kr="설계 브리프" right={<span className="pill muted-pill mono">export/design-brief.md</span>}>
        {md.status === 'loading' && <Loading what="design-brief.md" />}
        {md.status === 'error' && <ErrorBox title="design-brief.md could not be loaded" error={md.error} />}
        {md.status === 'ok' && <Markdown source={md.text} />}
      </Panel>
    </div>
  )
}

function Downloads({ bundle }: { bundle: DesignBundle }) {
  const b = bundle.brief
  const files: { label: string; sub: string; href: string; name: string }[] = [
    { label: 'design-brief.md', sub: 'Verdict, requirements, parts, risks, next tests', href: assetUrl(bundle, 'export/design-brief.md'), name: 'design-brief.md' },
    { label: 'bom.csv', sub: 'Only cited prices are summed; unpriced lines stay blank', href: assetUrl(bundle, 'export/bom.csv'), name: 'bom.csv' },
  ]
  for (const p of b.custom_parts) {
    if (p.cad_stl) files.push({ label: `${p.id}.stl`, sub: `${p.name} · web preview mesh`, href: assetUrl(bundle, p.cad_stl), name: `${p.id}.stl` })
    if (p.cad_step) files.push({ label: `${p.id}.step`, sub: `${p.name} · for engineers`, href: assetUrl(bundle, p.cad_step), name: `${p.id}.step` })
  }
  files.push({ label: 'design.json', sub: 'Machine-readable design brief', href: assetUrl(bundle, 'design.json'), name: 'design.json' })
  return (
    <Panel title="Downloads" kr="내려받기">
      <div className="downloads">
        {files.map((f) => (
          <a key={f.href} className="dl" href={f.href} download={f.name}>
            <span className="dl-i" aria-hidden>↓</span>
            <span><b className="mono">{f.label}</b><span className="small muted dl-s">{f.sub}</span></span>
          </a>
        ))}
      </div>
      {b.custom_parts.every((p) => !p.cad_step) && b.custom_parts.length > 0 && <p className="small muted">No STEP files: the CAD kernel was not available when this brief was generated. STL meshes are provided.</p>}
    </Panel>
  )
}
