import { useState } from 'react'
import type { DemoIndex } from '../bundle'
import { Autoresearch } from '../components/Autoresearch'
import { ErrorBox, Loading, PageHead } from '../components/ui'
import { getAutoresearch, useAsync, type Async } from '../lib/data'
import { LAB_SUBS, type LabSub } from '../lib/router'
import { LivePanel } from '../live/LivePanel'

interface Props {
  sub: LabSub
  index: Async<DemoIndex>
  idx: DemoIndex | null
  onEngineUp: (up: boolean) => void
}

const LABELS: Record<LabSub, { label: string; hint: string }> = {
  autoresearch: { label: 'Autoresearch', hint: 'Ledger, attitude control, calibration' },
  live: { label: 'Live sandbox', hint: 'Free-form real MuJoCo on your local engine' },
}

export function Lab({ sub, index, idx, onEngineUp }: Props) {
  const ar = useAsync(() => (idx ? getAutoresearch(idx) : new Promise<never>(() => {})), `ar:${idx ? 1 : 0}`)
  // the live sandbox stays mounted (hidden) once opened so a running stream survives sub-tab switches
  const [liveOpened, setLiveOpened] = useState(sub === 'live')
  if (sub === 'live' && !liveOpened) setLiveOpened(true)

  return (
    <div className="stack">
      <PageHead eyebrow="Lab" title="Where the method is tested" sub="Autoresearch checks that the calibration and control loops behave on synthetic data; the live sandbox steps real MuJoCo on your machine with parameters you choose." />
      <nav className="subtabs" aria-label="Lab sections">
        {LAB_SUBS.map((s) => (
          <a key={s} href={`#/lab/${s}`} className={s === sub ? 'on' : ''} aria-current={s === sub ? 'page' : undefined}>
            {s === 'live' && <i className="live-dot" />}
            <b>{LABELS[s].label}</b>
            <small>{LABELS[s].hint}</small>
          </a>
        ))}
      </nav>

      <div hidden={sub !== 'autoresearch'}>
        {index.status === 'loading' && <Loading what="demo bundle" />}
        {index.status === 'error' && <ErrorBox title="Demo bundle not found" error={index.error} />}
        {ar.status === 'loading' && index.status === 'ok' && <Loading what="autoresearch data" />}
        {ar.status === 'error' && <ErrorBox title="Autoresearch data failed to load" error={ar.error} />}
        {ar.status === 'ok' && <Autoresearch data={ar.data} />}
      </div>
      {liveOpened && (
        <div hidden={sub !== 'live'}>
          <LivePanel index={idx} onEngineUp={onEngineUp} />
        </div>
      )}
    </div>
  )
}
