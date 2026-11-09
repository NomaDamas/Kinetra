import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import App from '../App'

interface Action { t: number; type: string; line: string; scene: string; [k: string]: unknown }
interface Line { id: string; scene: string; text: string; start: number; end: number }
interface Scene { id: string; title: string; slide: { kind: string; tab?: string; wt?: string[]; spin?: string[]; sources?: string[] }; start: number }
interface Timeline { lang: 'ko' | 'en'; total: number; audio: string; tag: string; scenes: Scene[]; lines: Line[]; actions: Action[] }

declare global {
  interface Window {
    __filmStart?: () => void
    __filmLog?: { type: string; planned: number; fired: number; ok: boolean; line: string }[]
    __filmDone?: boolean
  }
}

const q = new URLSearchParams(location.search)
const FILM = q.has('film')
const LANG = q.get('lang') === 'en' ? 'en' : 'ko'

const num = (s: string) => parseFloat(s.replace(/[^0-9.\-]/g, ''))

/** Drive the real app UI through its own DOM; returns false if the target is not there (yet). */
function perform(a: Action): boolean {
  const $$ = <T extends Element>(s: string) => Array.from(document.querySelectorAll<T>(s))
  switch (a.type) {
    case 'select_scenario': {
      const b = $$<HTMLButtonElement>('button.chip.scenario').find((x) => x.textContent?.includes(String(a.title)))
      if (!b || b.disabled) return false
      b.click()
      return true
    }
    case 'tab': {
      const b = $$<HTMLButtonElement>('.tabs button').find((x) => x.textContent?.toLowerCase().includes(String(a.tab)))
      if (!b) return false
      b.click()
      window.scrollTo({ top: 0 })
      return true
    }
    case 'scroll': {
      const t = String(a.target)
      if (t === 'top') window.scrollTo({ top: 0, behavior: 'smooth' })
      else if (t === 'bottom') window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' })
      else {
        const el = document.getElementById(t)
        if (!el) return false
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
      return true
    }
    case 'open_assumptions': {
      const el = document.getElementById('assumptions')
      if (!el) return false
      el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      return true
    }
    case 'set_variant': {
      const tk = $$<HTMLButtonElement>('button.tick').find((x) => Math.abs(num(x.textContent ?? '') - Number(a.value)) < 1e-9)
      if (!tk) return false
      tk.click()
      return true
    }
    case 'apply_fix': {
      const b = $$<HTMLButtonElement>('button.btn.primary').find((x) => x.textContent?.includes('Apply fix'))
      if (!b || b.disabled) return false
      b.click()
      return true
    }
    case 'play': {
      const b = document.querySelector<HTMLButtonElement>('button[aria-label="Play"]')
      if (!b || b.disabled) return false
      b.click()
      return true
    }
  }
  return false
}

function Slide({ s }: { s: Scene }): ReactNode {
  const k = s.slide.kind
  if (k === 'problem')
    return (
      <>
        <div className="eyebrow">the problem · 문제</div>
        <h1>Testing physical ideas costs real money</h1>
        <div className="cols">
          <div className="card"><div className="big">${s.slide.wt?.[0]}–${s.slide.wt?.[1]} / hr</div><p>Wind-tunnel facility rate (NASA education slide; facility only, no model build/staff).</p></div>
          <div className="card"><div className="big">${s.slide.spin?.[0]}k–${s.slide.spin?.[1]}k</div><p>Hardware board respin (vendor blog claim, vendor has commercial interest).</p></div>
          <div className="card"><div className="big">—</div><p>Rocket hot-fire cost per test: no primary source found, so no number is shown.</p></div>
        </div>
        <div className="src">Sources: docs/judgment-spec.md §D — {s.slide.sources?.join(' · ')}</div>
      </>
    )
  if (k === 'insight')
    return (
      <>
        <div className="eyebrow">insight · 핵심</div>
        <h1>Screen bad ideas before you build them</h1>
        <div className="cols">
          <div className="card ok"><h3>Judge = MuJoCo</h3><p>Seeded rollouts, Monte-Carlo over uncertain assumptions. Every number comes from simulation tools.</p></div>
          <div className="card"><h3>Actor = Three.js</h3><p>Replays a stored trajectory. No physics in the browser, no invented verdicts.</p></div>
          <div className="card warn"><h3>Human gate</h3><p>Assumptions panel: editable, sourced, flagged low-confidence.</p></div>
        </div>
      </>
    )
  if (k === 'asymmetry')
    return (
      <>
        <div className="eyebrow">verdict asymmetry · 판정 비대칭</div>
        <h1>What we are allowed to claim</h1>
        <div className="cols">
          <div className="card ok"><h3>FOUND</h3><p>Strong evidence — within the stated assumptions.</p></div>
          <div className="card bad"><h3>NECESSARY CONDITION VIOLATED</h3><p>Strong “impossible under assumptions”.</p></div>
          <div className="card weak"><h3>NOT FOUND IN BUDGET</h3><p>WEAK evidence only. Never proof.</p></div>
        </div>
      </>
    )
  if (k === 'diff')
    return (
      <>
        <div className="eyebrow">differentiation · 차별점</div>
        <h1>Before the simulation exists</h1>
        <ul>
          <li><b>Drift</b> builds the sim. <b>We kill ideas not worth simulating.</b></li>
          <li><b>Luminary</b> speeds up experts’ simulations. <b>We give everyone their first physical experiment.</b></li>
          <li>Zoo (CAD-focused tooling) is a different layer; no claim of parity or comparison is made here.</li>
        </ul>
      </>
    )
  if (k === 'business')
    return (
      <>
        <div className="eyebrow">business model · UNVALIDATED</div>
        <h1>Hypothesis, not evidence</h1>
        <ul>
          <li>Hypothesis: per-idea screening reports for makers, hardware startups and educators.</li>
          <li>Willingness to pay: <b>not validated</b>. No customers, no revenue, no pilots.</li>
          <li>“Physical-equivalent cost” in reports is an estimate, not a quote and not a savings claim.</li>
        </ul>
      </>
    )
  if (k === 'roadmap')
    return (
      <>
        <div className="eyebrow">roadmap · 로드맵</div>
        <h1>Next</h1>
        <ul>
          <li>Validate calibration against real test data (today: synthetic only, sim-to-real not validated).</li>
          <li>More verified templates (drone next), more sourced cost references.</li>
          <li>User interviews to test the business hypothesis.</li>
        </ul>
      </>
    )
  return (
    <>
      <div className="eyebrow">ask · 요청</div>
      <h1>First users and real test data</h1>
      <ul>
        <li>People with a wild physical idea who will try the demo and tell us if it saves them a build.</li>
        <li>Partners with real test data to validate calibration.</li>
      </ul>
    </>
  )
}

export function Presenter() {
  const [tl, setTl] = useState<Timeline | null>(null)
  const [t, setT] = useState(0)
  const [playing, setPlaying] = useState(false)
  const clock = useRef({ base: 0, t0: 0, running: false })
  const fired = useRef<Set<number>>(new Set())
  const audio = useRef<HTMLAudioElement | null>(null)
  const tlRef = useRef<Timeline | null>(null)

  useEffect(() => {
    fetch(`/present/timeline.${LANG}.json`, { cache: 'no-cache' }).then((r) => r.json()).then((j: Timeline) => { setTl(j); tlRef.current = j })
    if (FILM) document.body.classList.add('film')
  }, [])

  const now = useCallback(() => {
    const c = clock.current
    return c.running ? c.base + (performance.now() - c.t0) / 1000 : c.base
  }, [])

  const start = useCallback(() => {
    const c = clock.current
    c.t0 = performance.now()
    c.running = true
    setPlaying(true)
    if (!FILM && audio.current) { audio.current.currentTime = c.base; void audio.current.play() }
    window.__filmLog = window.__filmLog ?? []
  }, [])
  const pause = useCallback(() => {
    const c = clock.current
    c.base = now()
    c.running = false
    setPlaying(false)
    audio.current?.pause()
  }, [now])
  const seek = useCallback((to: number) => {
    const c = clock.current
    c.base = Math.max(0, to)
    c.t0 = performance.now()
    const a = tlRef.current?.actions ?? []
    fired.current = new Set(a.map((x, i) => (x.t < c.base ? i : -1)).filter((i) => i >= 0))
    if (audio.current) audio.current.currentTime = c.base
  }, [])

  useEffect(() => {
    window.__filmStart = start
  }, [start])

  // main loop
  useEffect(() => {
    let raf = 0
    const pending = new Map<number, number>() // action idx -> first try time
    const loop = () => {
      const tt = clock.current.running && !FILM && audio.current && !audio.current.paused ? audio.current.currentTime : now()
      if (clock.current.running && !FILM && audio.current && !audio.current.paused) { clock.current.base = tt; clock.current.t0 = performance.now() }
      const T = tlRef.current
      if (T) {
        setT(tt)
        if (clock.current.running) {
          T.actions.forEach((a, i) => {
            if (fired.current.has(i) || a.t > tt) return
            const first = pending.get(i) ?? tt
            pending.set(i, first)
            const ok = perform(a)
            if (ok || tt - first > 4) {
              fired.current.add(i)
              ;(window.__filmLog ??= []).push({ type: a.type, planned: a.t, fired: Math.round(tt * 1000) / 1000, ok, line: a.line })
            }
          })
          if (tt >= T.total) { setPlaying(false); clock.current.running = false; window.__filmDone = true }
        }
      }
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => cancelAnimationFrame(raf)
  }, [now])

  const idx = useMemo(() => {
    if (!tl) return { sc: 0, ln: -1 }
    let sc = 0
    tl.scenes.forEach((s, i) => { if (t >= s.start) sc = i })
    let ln = -1
    tl.lines.forEach((l, i) => { if (t >= l.start && t <= l.end + 0.25) ln = i })
    return { sc, ln }
  }, [tl, t])

  useEffect(() => {
    if (FILM) return
    const h = (e: KeyboardEvent) => {
      if (!tlRef.current) return
      const T = tlRef.current
      const cur = now()
      if (e.code === 'Space') { e.preventDefault(); clock.current.running ? pause() : start() }
      else if (e.key === 'r' || e.key === 'R') { pause(); seek(0); window.location.reload() }
      else if (e.key === 'ArrowRight') seek((T.scenes.find((s) => s.start > cur + 0.01) ?? T.scenes[T.scenes.length - 1]).start)
      else if (e.key === 'ArrowLeft') seek([...T.scenes].reverse().find((s) => s.start < cur - 1.5)?.start ?? 0)
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [now, pause, start, seek])

  if (!tl) return <div className="pres-hud">loading timeline…</div>
  const sc = tl.scenes[idx.sc]
  const line = idx.ln >= 0 ? tl.lines[idx.ln] : null
  const showSlide = sc.slide.kind !== 'app'
  return (
    <>
      <App />
      {showSlide && <div className="pres-slide" key={sc.id}><Slide s={sc} /></div>}
      <span className="pill recorded pres-tag">{tl.tag}</span>
      {line && <div className="pres-sub">{line.text}</div>}
      <div className="pres-bar" style={{ width: `${(t / tl.total) * 100}%` }} />
      <div className="pres-hud">
        {sc.title} · {t.toFixed(1)}/{tl.total.toFixed(0)}s · {playing ? 'playing' : 'paused'} · space play/pause · ←/→ scene · R restart
      </div>
      {!FILM && <audio ref={audio} src={tl.audio} preload="auto" />}
    </>
  )
}
