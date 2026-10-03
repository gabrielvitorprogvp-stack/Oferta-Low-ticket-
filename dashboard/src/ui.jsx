import { useEffect, useRef, useState } from 'react'

// ---------------------------------------------------------------- API
export async function api(path, opts = {}) {
  const r = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  })
  if (!r.ok) {
    let msg = r.statusText
    try { msg = (await r.json()).detail || msg } catch { /* sem corpo */ }
    throw new Error(msg)
  }
  return r.json()
}

export function useApi(path, deps = [], intervalMs = 0) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let alive = true
    api(path).then(
      (data) => alive && setState({ data, error: null, loading: false }),
      (error) => alive && setState((s) => ({ ...s, error, loading: false })),
    )
    return () => { alive = false }
  }, [path, tick, ...deps]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!intervalMs) return
    const id = setInterval(() => setTick((t) => t + 1), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return { ...state, reload: () => setTick((t) => t + 1) }
}

// ---------------------------------------------------------------- formatação
export const brl = (v) => (v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' }))
export const num = (v) => (v == null ? '—' : Number(v).toLocaleString('pt-BR'))
export function ago(iso) {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  const s = (Date.now() - d.getTime()) / 1000
  if (s < 60) return 'agora'
  if (s < 3600) return `${Math.round(s / 60)} min`
  if (s < 86400) return `${Math.round(s / 3600)} h`
  return `${Math.round(s / 86400)} d`
}
export const dateBR = (iso) => {
  if (!iso) return '—'
  const d = new Date(iso.endsWith('Z') || iso.length <= 10 ? iso : iso + 'Z')
  return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })
}
export function Delta({ v }) {
  if (v == null) return <span className="muted">—</span>
  if (v > 0) return <span className="delta-up mono">+{v}</span>
  if (v < 0) return <span className="mono" style={{ color: 'var(--st-sat)' }}>{v}</span>
  return <span className="delta-zero mono">0</span>
}

// ---------------------------------------------------------------- status
// 🔥 escala emergente · 🟡 observação · 🟢 mar azul · 🔴 saturado — sempre ícone + rótulo
export const STATUS = {
  EMERGING: { label: 'Escala emergente', short: 'Emergente', icon: '🔥', cls: 'b-emerging' },
  WATCHING: { label: 'Em observação', short: 'Observação', icon: '🟡', cls: 'b-watch' },
  TESTING: { label: 'Teste', short: 'Teste', icon: '🧪', cls: 'b-neutral' },
  NEW: { label: 'Novo', short: 'Novo', icon: '✨', cls: 'b-neutral' },
  MATURE: { label: 'Saturado / maduro', short: 'Saturado', icon: '🔴', cls: 'b-sat' },
  DECLINING: { label: 'Em queda', short: 'Em queda', icon: '📉', cls: 'b-sat' },
  DISCARDED: { label: 'Descartado', short: 'Descartado', icon: '⛔', cls: 'b-neutral' },
}
export function StatusBadge({ status, short }) {
  const s = STATUS[status] || { label: status, short: status, icon: '•', cls: 'b-neutral' }
  return <span className={`badge ${s.cls}`} title={s.label}><span aria-hidden>{s.icon}</span>{short ? s.short : s.label}</span>
}
export function BlueOceanBadge({ score }) {
  if (score == null || score < 60) return null
  return <span className="badge b-blue"><span aria-hidden>🟢</span>Mar azul</span>
}
export const ACC = {
  FORTISSIMA: '🚀 Fortíssima', FORTE: '⚡ Forte', MODERADA: '↗ Moderada', FRACA: '→ Fraca',
  ESTAVEL: '＝ Estável', QUEDA: '↘ Queda', SEM_DADOS: '· Sem dados',
}
export function Ver({ v }) {
  const label = { VERIFIED: 'VERIFICADO', PARTIAL: 'PARCIAL', NOT_VERIFIED: 'NÃO VERIFICADO', BLOCKED: 'BLOQUEADO' }
  return <span className={`ver ver-${v}`}>{label[v] || v}</span>
}

export function Score({ v, c, kind }) {
  if (v == null) return <span className="muted">—</span>
  return (
    <span className="score" title={`score ${v} · confiança ${c ?? '—'}`}>
      <span className="row"><span className="v">{Math.round(v)}</span><span className="c">conf {c != null ? Math.round(c) : '—'}</span></span>
      <span className={`bar ${kind === 'blue' ? 'blue' : ''}`}><i style={{ width: `${Math.max(2, Math.min(100, v))}%` }} /></span>
    </span>
  )
}

// ---------------------------------------------------------------- gráficos (SVG, série única)
function useWidth() {
  const ref = useRef(null)
  const [w, setW] = useState(600)
  useEffect(() => {
    if (!ref.current) return
    const ro = new ResizeObserver(([e]) => setW(Math.max(260, e.contentRect.width)))
    ro.observe(ref.current)
    return () => ro.disconnect()
  }, [])
  return [ref, w]
}

function niceMax(v) {
  if (v <= 5) return 5
  const p = Math.pow(10, Math.floor(Math.log10(v)))
  return Math.ceil(v / p) * p
}

/** Linha: quantidade de criativos x data. points = [{x: Date|iso, y: number, label?}] */
export function LineChart({ points, height = 220, unit = 'criativos' }) {
  const [ref, w] = useWidth()
  const [hover, setHover] = useState(null)
  if (!points?.length) return <div className="empty">Sem snapshots ainda — o gráfico aparece a partir da 1ª análise.</div>
  const pad = { l: 36, r: 16, t: 14, b: 26 }
  const xs = points.map((p) => new Date(p.x).getTime())
  const minX = Math.min(...xs), maxX = Math.max(...xs)
  const maxY = niceMax(Math.max(...points.map((p) => p.y)) * 1.1)
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b
  const sx = (t) => pad.l + (maxX === minX ? iw / 2 : ((t - minX) / (maxX - minX)) * iw)
  const sy = (y) => pad.t + ih - (y / maxY) * ih
  const path = points.map((p, i) => `${i ? 'L' : 'M'}${sx(xs[i])},${sy(p.y)}`).join(' ')
  const area = `${path} L${sx(xs[xs.length - 1])},${sy(0)} L${sx(xs[0])},${sy(0)} Z`
  const ticks = [0, maxY / 2, maxY]
  const onMove = (e) => {
    const r = e.currentTarget.getBoundingClientRect()
    const mx = ((e.clientX - r.left) / r.width) * w
    let best = 0
    xs.forEach((t, i) => { if (Math.abs(sx(t) - mx) < Math.abs(sx(xs[best]) - mx)) best = i })
    setHover(best)
  }
  const labelIdx = new Set([0, points.length - 1])
  return (
    <div className="chart" ref={ref}>
      <svg viewBox={`0 0 ${w} ${height}`} onMouseMove={onMove} onMouseLeave={() => setHover(null)} role="img"
        aria-label={`Quantidade de ${unit} por data`}>
        <g className="grid">{ticks.map((t) => <line key={t} x1={pad.l} x2={w - pad.r} y1={sy(t)} y2={sy(t)} />)}</g>
        <g className="axis">
          {ticks.map((t) => <text key={t} x={pad.l - 8} y={sy(t) + 4} textAnchor="end">{Math.round(t)}</text>)}
          {[...labelIdx].map((i) => <text key={i} x={sx(xs[i])} y={height - 6} textAnchor={i ? 'end' : 'start'}>{dateBR(points[i].x)}</text>)}
        </g>
        <path className="area" d={area} />
        <path className="line" d={path} />
        {points.map((p, i) => <circle key={i} className="pt" cx={sx(xs[i])} cy={sy(p.y)} r={hover === i ? 6 : 4} />)}
        {points.length > 1 && <text x={sx(xs[xs.length - 1])} y={sy(points[points.length - 1].y) - 10} textAnchor="end"
          style={{ fill: 'var(--text-primary)', fontSize: 12, fontWeight: 700, fontFamily: 'var(--mono)' }}>{points[points.length - 1].y}</text>}
        {hover != null && <line className="cross" x1={sx(xs[hover])} x2={sx(xs[hover])} y1={pad.t} y2={pad.t + ih} />}
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ left: `${(sx(xs[hover]) / w) * 100}%`, top: sy(points[hover].y) }}>
          {new Date(points[hover].x).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
          {' · '}<b>{points[hover].y}</b> {unit}{points[hover].label ? ` · ${points[hover].label}` : ''}
        </div>
      )}
    </div>
  )
}

/** Barras: criativos lançados por dia (datas de início). items = [[iso, n], ...] */
export function LaunchBars({ items, days = 40, height = 150 }) {
  const [ref, w] = useWidth()
  const [hover, setHover] = useState(null)
  const end = new Date(); end.setHours(0, 0, 0, 0)
  const map = Object.fromEntries(items || [])
  const data = []
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date(end); d.setDate(end.getDate() - i)
    const k = d.toISOString().slice(0, 10)
    data.push({ k, d, n: map[k] || 0 })
  }
  const older = (items || []).filter(([k]) => k < data[0].k).reduce((a, [, n]) => a + n, 0)
  const pad = { l: 26, r: 6, t: 10, b: 22 }
  const iw = w - pad.l - pad.r, ih = height - pad.t - pad.b
  const maxY = niceMax(Math.max(1, ...data.map((x) => x.n)))
  const bw = iw / data.length
  return (
    <div className="chart" ref={ref}>
      <svg viewBox={`0 0 ${w} ${height}`} onMouseLeave={() => setHover(null)} role="img" aria-label="Criativos lançados por dia">
        <g className="grid"><line x1={pad.l} x2={w - pad.r} y1={pad.t + ih} y2={pad.t + ih} /></g>
        <g className="axis">
          <text x={pad.l - 6} y={pad.t + 8} textAnchor="end">{maxY}</text>
          <text x={pad.l} y={height - 5}>{dateBR(data[0].k)}</text>
          <text x={w - pad.r} y={height - 5} textAnchor="end">hoje</text>
        </g>
        {data.map((x, i) => {
          const h = (x.n / maxY) * ih
          const bx = pad.l + i * bw + 1, bwid = Math.max(1, bw - 2) // 2px de respiro entre barras
          return (
            <g key={x.k} onMouseEnter={() => setHover(i)}>
              <rect x={pad.l + i * bw} y={pad.t} width={bw} height={ih} fill="transparent" />
              {x.n > 0 && <path className={`barm ${hover != null && hover !== i ? 'dim' : ''}`}
                d={`M${bx},${pad.t + ih} V${pad.t + ih - h + Math.min(4, h)} Q${bx},${pad.t + ih - h} ${bx + Math.min(4, bwid / 2)},${pad.t + ih - h} H${bx + bwid - Math.min(4, bwid / 2)} Q${bx + bwid},${pad.t + ih - h} ${bx + bwid},${pad.t + ih - h + Math.min(4, h)} V${pad.t + ih} Z`} />}
            </g>
          )
        })}
      </svg>
      {hover != null && (
        <div className="tooltip" style={{ left: `${((pad.l + hover * bw + bw / 2) / w) * 100}%`, top: pad.t + ih - (data[hover].n / maxY) * ih }}>
          {data[hover].d.toLocaleDateString('pt-BR')} · <b>{data[hover].n}</b> criativo(s) novo(s)
        </div>
      )}
      {older > 0 && <div className="note">+{older} criativo(s) ativo(s) lançado(s) antes da janela de {days} dias (sobreviventes).</div>}
    </div>
  )
}
