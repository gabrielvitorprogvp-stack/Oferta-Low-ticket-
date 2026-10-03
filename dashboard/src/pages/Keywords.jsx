import { useState } from 'react'
import { api, ago, num, useApi } from '../ui.jsx'

export default function Keywords({ RunControl }) {
  const kws = useApi('/api/keywords', [], 30000)
  const clusters = useApi('/api/clusters', [], 30000)
  const [term, setTerm] = useState('')
  const add = async (e) => { e.preventDefault(); if (!term.trim()) return; await api('/api/keywords', { method: 'POST', body: { term } }); setTerm(''); kws.reload() }
  return (
    <>
      <div className="topbar"><div><h1>Palavras &amp; nichos</h1><div className="sub">SEMENTE → OFERTA → NOVAS PALAVRAS → NOVOS ANUNCIANTES. Os nichos emergem dos sinais, não são escolhidos antes.</div></div><RunControl /></div>
      <div className="grid-2e">
        <section className="panel">
          <div className="panel-h"><h3>Clusters de mercado</h3></div>
          <div className="table-wrap"><table>
            <thead><tr><th>Nicho</th><th className="r">Anunciantes</th><th className="r">Ofertas</th><th className="r">🔥 Emergentes</th><th className="r">Velocity médio</th><th>Palavras</th></tr></thead>
            <tbody>{(clusters.data || []).map((c) => (
              <tr key={c.id} style={{ cursor: 'default' }}><td><b>{c.name}</b></td><td className="r mono">{c.advertisers}</td><td className="r mono">{c.offers}</td>
                <td className="r mono">{c.emerging}</td><td className="r mono">{c.avg_velocity ?? '—'}</td>
                <td><div className="tags">{(c.keywords || []).slice(0, 5).map((k) => <span key={k} className="tag">{k}</span>)}</div></td></tr>))}</tbody>
          </table>{clusters.data && !clusters.data.length && <div className="empty">Os clusters aparecem após as primeiras ofertas.</div>}</div>
        </section>
        <section className="panel">
          <div className="panel-h"><h3>Fila de consultas</h3>
            <form className="toolbar" onSubmit={add}><input className="input" placeholder="Adicionar termo…" value={term} onChange={(e) => setTerm(e.target.value)} /><button className="btn sm">+ Adicionar</button></form>
          </div>
          <div className="table-wrap"><table>
            <thead><tr><th>Termo</th><th>Origem</th><th>Status</th><th className="r">Resultados Meta</th><th className="r">Anunciantes</th><th className="r">Última</th></tr></thead>
            <tbody>{(kws.data || []).map((k) => (
              <tr key={k.id} style={{ cursor: 'default' }}><td><b>{k.term}</b></td><td><span className="tag">{k.source}</span></td>
                <td><span className={`badge ${k.status === 'explored' ? 'b-blue' : k.status === 'failed' ? 'b-sat' : 'b-neutral'}`}>{k.status}</span></td>
                <td className="r mono">{num(k.results_last)}</td><td className="r mono">{k.candidates_found}</td><td className="r muted">{ago(k.last_queried_at)}</td></tr>))}</tbody>
          </table></div>
        </section>
      </div>
    </>
  )
}
