// Tiny, dependency-free renderer for the design brief (headings, paragraphs, lists, tables, code, bold/italic/links).
// Produces React elements (no innerHTML), so file content cannot inject markup.
import { Fragment, type ReactNode } from 'react'

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  const re = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\)|\*[^*\s][^*]*\*)/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(text.slice(last, m.index))
    const t = m[0]
    const k = `${keyBase}-${i++}`
    if (t.startsWith('**')) out.push(<b key={k}>{t.slice(2, -2)}</b>)
    else if (t.startsWith('`')) out.push(<code key={k}>{t.slice(1, -1)}</code>)
    else if (t.startsWith('[')) {
      const mm = /\[([^\]]+)\]\(([^)]+)\)/.exec(t)!
      const safe = /^(https?:|#|\.{0,2}\/|[\w-]+\/)/.test(mm[2]) && !/^javascript:/i.test(mm[2])
      out.push(safe ? <a key={k} href={mm[2]} target={mm[2].startsWith('http') ? '_blank' : undefined} rel="noreferrer">{mm[1]}</a> : <Fragment key={k}>{mm[1]}</Fragment>)
    } else out.push(<i key={k}>{t.slice(1, -1)}</i>)
    last = m.index + t.length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

const splitRow = (l: string) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim())

export function Markdown({ source }: { source: string }) {
  const lines = source.replace(/\r\n/g, '\n').split('\n')
  const blocks: ReactNode[] = []
  let i = 0
  let k = 0
  while (i < lines.length) {
    const line = lines[i]
    if (!line.trim()) {
      i++
      continue
    }
    if (line.startsWith('```')) {
      const buf: string[] = []
      i++
      while (i < lines.length && !lines[i].startsWith('```')) buf.push(lines[i++])
      i++
      blocks.push(<pre key={k++} className="detail">{buf.join('\n')}</pre>)
      continue
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(line)
    if (h) {
      const lvl = h[1].length
      const c = inline(h[2], `h${k}`)
      blocks.push(lvl === 1 ? <h2 key={k++} className="md-h1">{c}</h2> : lvl === 2 ? <h3 key={k++} className="md-h2">{c}</h3> : <h4 key={k++}>{c}</h4>)
      i++
      continue
    }
    if (line.trim().startsWith('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1])) {
      const head = splitRow(line)
      i += 2
      const rows: string[][] = []
      while (i < lines.length && lines[i].trim().startsWith('|')) rows.push(splitRow(lines[i++]))
      blocks.push(
        <div key={k++} className="tablewrap">
          <table className="tbl compact">
            <thead><tr>{head.map((c, j) => <th key={j}>{inline(c, `th${k}${j}`)}</th>)}</tr></thead>
            <tbody>{rows.map((r, a) => <tr key={a}>{r.map((c, j) => <td key={j}>{inline(c, `td${k}${a}${j}`)}</td>)}</tr>)}</tbody>
          </table>
        </div>,
      )
      continue
    }
    if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\./.test(line)
      const items: string[] = []
      while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ''))
      const lis = items.map((t, j) => <li key={j}>{inline(t, `li${k}${j}`)}</li>)
      blocks.push(ordered ? <ol key={k++}>{lis}</ol> : <ul key={k++}>{lis}</ul>)
      continue
    }
    if (line.startsWith('>')) {
      const buf: string[] = []
      while (i < lines.length && lines[i].startsWith('>')) buf.push(lines[i++].replace(/^>\s?/, ''))
      blocks.push(<blockquote key={k++}>{inline(buf.join(' '), `bq${k}`)}</blockquote>)
      continue
    }
    const buf: string[] = []
    while (i < lines.length && lines[i].trim() && !/^(#{1,4}\s|```|>|\s*([-*]|\d+\.)\s+)/.test(lines[i]) && !lines[i].trim().startsWith('|')) buf.push(lines[i++])
    if (buf.length === 0) {
      buf.push(lines[i++])
    }
    blocks.push(<p key={k++}>{inline(buf.join(' '), `p${k}`)}</p>)
  }
  return <div className="md">{blocks}</div>
}
