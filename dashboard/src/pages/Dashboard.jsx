import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { ACC, ago, brl, Delta, num, Score, StatusBadge, useApi, api } from '../ui.jsx'

const FILTERS = [
  ['active', 'Todas'], ['emerging', '🔥 Escala emergente'], ['blue_ocean', '🟢 Mar azul'], ['new', '✨ Novo'],
  ['watching', '🟡 Em observação'], ['mature', '🔴 Maduro'], ['declining', '📉 Em queda'], ['discarded', '⛔ Descartado'],
]
const SORTS = [['velocity', 'Velocity'], ['blue_ocean', 'Mar azul'], ['recent', 'Última análise'], ['first_seen', 'Mais novas'], ['price', 'Preço']]

export default function Dashboard({ RunControl, watchlist }) {
  const [filter, setFilter] = useState(watchlist ? 'watching' : 'active')
  const [sort, setSort] = useState('velocity')
  const [q, setQ] = useState('')
  const stats = useApi('/api/stats', [], 15000)
  const alerts = useApi('/api/alerts?limit=6', [], 15000)
  const offers = useApi(`/api/offers?filter=${filter}&sort=${sort}${q ? `&q=${encodeURIComponent(q)}` : ''}`, [], 20000)
  const nav = useNavigate()
  const st = stats.data || {}
  const bs = st.by_status || {}
  const count = (f) => ({ active: st.offers_monitored, emerging: st.emerging, blue_ocean: st.blue_ocean, new: bs.NEW,
    watching: (bs.WATCHING || 0) + (bs.TESTING || 0), mature: bs.MATURE, declining: bs.DECLINING, discarded: bs.DISCARDED })[f]

  return (
    <>
      <div className="topbar">
        <div>
          <h1>{watchlist ? 'Watchlist' : 'Radar Low Ticket'}</h1>
          <div className="sub">{watchlist ? 'Ofertas com potencial em observação — revisitadas automaticamente a cada rodada'
            : 'Escala emergente em produtos digitais low ticket · Meta Ads Library + sinais públicos'}</div>
        </div>
        <RunControl />
      </div>

      {!watchlist && (
        <div className="kpis">
          <div className="kpi"><div className="label">Ofertas monitoradas</div><div className="value">{num(st.offers_monitored)}</div></div>
          <div className="kpi hot"><div className="label">🔥 Escalas emergentes</div><div className="value">{num(st.emerging)}</div></div>
          <div className="kpi"><div className="label">✨ Novas ofertas (24h)</div><div className="value">{num(st.new_today)}</div></div>
          <div className="kpi"><div className="label">Anunciantes monitorados</div><div className="value">{num(st.advertisers_monitored)}</div></div>
          <div className="kpi"><div className="label">🔔 Alertas recentes (24h)</div><div className="value">{num(st.alerts_recent)}</div></div>
        </div>
      )}

        {!watchlist && (
          <section className="panel" style={{ marginBottom: 16 }}>
            <div className="panel-h"><h2>🔔 Alertas recentes</h2></div>
            <div className="alerts">
              {(alerts.data || []).map((a) => (
                <Link key={a.id} to={a.offer_id ? `/offers/${a.offer_id}` : '/runs'} className={`alert ${a.read ? '' : 'unread'}`}
                  onClick={() => !a.read && api(`/api/alerts/${a.id}/read`, { method: 'POST' })}>
                  <div className="ico">{a.type === 'EMERGING_SCALE' ? '🔥' : a.type === 'ACCELERATION' ? '🚀' : '⚠️'}</div>
                  <div style={{ minWidth: 0 }}>
                    <div className="t">{a.title}</div>
                    <div className="m">{a.message.split('\n').filter(Boolean).slice(1, 5).join(' · ')}</div>
                    <div className="m muted">{ago(a.created_at)} {a.sent_channels?.length ? `· enviado: ${a.sent_channels.join(', ')}` : ''}</div>
                  </div>
                </Link>
              ))}
              {alerts.data && !alerts.data.length && <div className="empty">Sem alertas. Eles só aparecem quando há sinal relevante.</div>}
            </div>
          </section>
        )}
      <div>
        <section className="panel" style={{ marginBottom: 16 }}>
          <div className="panel-h">
            <div className="toolbar">
              {FILTERS.map(([k, l]) => (
                <button key={k} className={`chip ${filter === k ? 'on' : ''}`} onClick={() => setFilter(k)}>
                  {l}{count(k) != null && <span className="n">{count(k)}</span>}
                </button>
              ))}
            </div>
            <div className="toolbar">
              <input className="input" placeholder="Buscar oferta, anunciante, nicho…" value={q} onChange={(e) => setQ(e.target.value)} />
              <select className="input" value={sort} onChange={(e) => setSort(e.target.value)} aria-label="Ordenar">
                {SORTS.map(([k, l]) => <option key={k} value={k}>Ordenar: {l}</option>)}
              </select>
            </div>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Oferta</th><th>Anunciante</th><th>Nicho</th><th className="r">Preço</th><th className="r">Criat.</th>
                  <th className="r">+7 dias</th><th className="r">+14 dias</th>
                  <th className="r">Velocity</th><th className="r">Mar azul</th><th>Status</th><th className="r col-opt">Análise</th>
                </tr>
              </thead>
              <tbody>
                {(offers.data?.items || []).map((o) => (
                  <tr key={o.id} className={o.status === 'EMERGING' ? 'emerging' : ''} onClick={() => nav(`/offers/${o.id}`)}>
                    <td>
                      <div className="offer-name" title={o.name}>{o.name || o.domain}</div>
                      <div className="offer-sub">{[o.product_format, o.checkout_platform, o.domain].filter(Boolean).join(' · ')}</div>
                    </td>
                    <td><div className="offer-name" style={{ maxWidth: 130, fontWeight: 500 }} title={o.advertiser}>{o.advertiser}</div></td>
                    <td><div className="offer-sub" style={{ maxWidth: 115, color: 'var(--text-secondary)', fontSize: 13 }} title={o.niche}>{o.niche || '—'}</div></td>
                    <td className="r mono">{brl(o.price_brl)}</td>
                    <td className="r mono">{num(o.creatives)}</td>
                    <td className="r"><Delta v={o.delta_7d ?? o.new_7d} /></td>
                    <td className="r"><Delta v={o.delta_14d ?? o.new_14d} /></td>
                    <td className="r">
                      <Score v={o.velocity_score} c={o.velocity_confidence} />
                      <div className="acc-line" title={o.acceleration_estimated ? 'estimado pelas datas de início — aguarda histórico' : 'medido entre snapshots'}>
                        {ACC[o.acceleration] || '—'}{o.acceleration_estimated && o.acceleration && o.acceleration !== 'SEM_DADOS' ? ' *' : ''}
                      </div>
                    </td>
                    <td className="r">
                      <Score v={o.blue_ocean_score} c={o.blue_ocean_confidence} kind="blue" />
                      {o.blue_ocean_score >= 60 && <div className="acc-line" style={{ color: 'var(--st-blue)' }}>🟢 mar azul</div>}
                    </td>
                    <td><StatusBadge status={o.status} short /></td>
                    <td className="r muted col-opt">{ago(o.last_analyzed_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {offers.data && !offers.data.items.length && <div className="empty">Nada aqui ainda. Rode uma garimpagem para popular o radar.</div>}
            {offers.error && <div className="empty">Erro ao carregar: {offers.error.message}</div>}
          </div>
          <div className="note" style={{ margin: 12 }}>+7/+14 dias = variação real entre snapshots quando há histórico; senão, criativos lançados no período (datas de início). * = aceleração estimada.</div>
        </section>

      </div>
    </>
  )
}
