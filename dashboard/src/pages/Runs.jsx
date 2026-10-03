import { useState } from 'react'
import { ago, useApi, Ver } from '../ui.jsx'

const STAT_LABELS = { queries_tested: 'consultas', candidates_found: 'candidatos', candidates_accepted: 'aceitos',
  candidates_discarded: 'descartados', advertisers_analyzed: 'anunciantes analisados', new_offers: 'novas ofertas',
  landing_pages: 'landing pages', alerts: 'alertas', meta_failed: 'falhas Meta', keywords_added: 'novas palavras' }

export default function Runs({ RunControl }) {
  const runs = useApi('/api/runs', [], 10000)
  const [sel, setSel] = useState(null)
  const [level, setLevel] = useState('')
  const current = sel ?? runs.data?.[0]?.id
  const logs = useApi(current ? `/api/runs/${current}/logs${level ? `?level=${level}` : ''}` : '/api/health', [current, level], 6000)
  return (
    <>
      <div className="topbar"><div><h1>Rodadas &amp; logs</h1><div className="sub">Histórico de execuções, status da coleta na Meta e logs por etapa</div></div><RunControl /></div>
      <div className="grid-2e">
        <section className="panel">
          <div className="panel-h"><h3>Rodadas</h3></div>
          <div className="table-wrap"><table>
            <thead><tr><th>#</th><th>Início</th><th>Gatilho</th><th>Status</th><th>Meta</th><th>Resumo</th></tr></thead>
            <tbody>{(runs.data || []).map((r) => (
              <tr key={r.id} onClick={() => setSel(r.id)} style={current === r.id ? { background: 'var(--surface-2)' } : undefined}>
                <td className="mono">{r.id}</td><td className="muted">{ago(r.started_at)}</td><td>{r.trigger}</td>
                <td><span className={`badge ${r.status === 'completed' ? 'b-blue' : r.status === 'running' ? 'b-emerging' : r.status === 'partial' ? 'b-watch' : 'b-sat'}`}>{r.status}</span></td>
                <td><Ver v={r.meta_status} /></td>
                <td className="muted" style={{ fontSize: 12 }}>{Object.entries(STAT_LABELS).filter(([k]) => r.stats?.[k]).map(([k, l]) => `${r.stats[k]} ${l}`).join(' · ')}</td>
              </tr>))}</tbody>
          </table>
          {runs.data && !runs.data.length && <div className="empty">Nenhuma rodada ainda.</div>}</div>
        </section>
        <section className="panel">
          <div className="panel-h"><h3>Logs da rodada #{current ?? '—'}</h3>
            <div className="toolbar">{[['', 'Tudo'], ['WARNING', 'Avisos'], ['ERROR', 'Erros']].map(([k, l]) => <button key={k} className={`chip ${level === k ? 'on' : ''}`} onClick={() => setLevel(k)}>{l}</button>)}</div>
          </div>
          <div className="panel-b log">
            {Array.isArray(logs.data) && logs.data.map((l, i) => (
              <div key={i} className={`ln ${l.level}`}><span className="muted">{new Date(l.ts + 'Z').toLocaleTimeString('pt-BR')}</span><span>{l.level}</span><span className="muted">{l.stage}</span><span className="msg">{l.message}</span></div>
            ))}
          </div>
        </section>
      </div>
    </>
  )
}
