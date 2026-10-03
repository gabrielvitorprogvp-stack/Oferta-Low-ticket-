import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ACC, ago, api, BlueOceanBadge, brl, dateBR, LaunchBars, LineChart, num, StatusBadge, STATUS, useApi, Ver } from '../ui.jsx'

const VEL_LABELS = { growth: 'Crescimento recente (25)', upload_freq: 'Frequência de uploads (20)', survival: 'Sobrevivência de antigos (20)',
  hooks: 'Variedade de hooks (15)', formats: 'Variedade de formatos (10)', funnel: 'Consistência do funil (10)' }
const BLUE_LABELS = { pain: 'Força da dor (15)', clarity: 'Clareza da oferta (10)', intent: 'Intenção de compra (10)',
  competition: 'Concorrência observada (15)', similar: 'Anunciantes semelhantes (10)', differentiation: 'Diferenciação (10)',
  own_version: 'Versão própria viável (10)', delivery: 'Facilidade de entrega (8)', creative_power: 'Força criativa possível (6)',
  low_cost: 'Baixo custo de produção (6)' }
const MAXES = { growth: 25, upload_freq: 20, survival: 20, hooks: 15, formats: 10, funnel: 10, pain: 15, clarity: 10, intent: 10,
  competition: 15, similar: 10, differentiation: 10, own_version: 10, delivery: 8, creative_power: 6, low_cost: 6 }

function Breakdown({ comp, labels, evidence, blue }) {
  return (
    <div className="score-break">
      {Object.entries(comp || {}).map(([k, v]) => (
        <div className="item" key={k}>
          <div className="lbl">
            <span>{labels[k] || k}{evidence?.[k] ? <span className="muted"> — {evidence[k]}</span> : null}</span>
            <span className={`bar ${blue ? 'blue' : ''}`}><i style={{ width: `${(v / MAXES[k]) * 100}%` }} /></span>
          </div>
          <span className="mono r" style={{ textAlign: 'right' }}>{v}</span>
        </div>
      ))}
    </div>
  )
}

function Kv({ items }) {
  return <dl className="kv">{items.filter(([, v]) => v != null && v !== '' && !(Array.isArray(v) && !v.length)).map(([k, v]) => (
    <Fragment key={k}><dt>{k}</dt><dd>{Array.isArray(v) ? <ul className="list">{v.map((x, i) => <li key={i}>{x}</li>)}</ul> : v}</dd></Fragment>
  ))}</dl>
}

export default function OfferPage({ RunControl }) {
  const { id } = useParams()
  const { data: o, error, reload } = useApi(`/api/offers/${id}`, [id], 30000)
  const [tab, setTab] = useState('ads')
  const [series, setSeries] = useState('offer')
  if (error) return <div className="empty">Erro: {error.message}</div>
  if (!o) return <div className="empty">Carregando…</div>
  const m = o.metrics || {}
  const acc = o.acceleration_detail || {}
  const lp = o.landing_pages?.[0]
  const lpd = lp?.data || {}
  const vel = o.score_breakdown?.velocity || {}
  const blue = o.score_breakdown?.blue_ocean || {}
  const mod = o.modeling || {}
  const offerPts = (o.snapshots || []).map((s) => ({ x: s.taken_at + 'Z', y: s.distinct_creatives, label: s.verification }))
  const advPts = (o.advertiser_snapshots || []).filter((s) => s.active_ads_total != null)
    .map((s) => ({ x: s.taken_at + 'Z', y: s.active_ads_total, label: s.verification }))
  const setStatus = async (status) => { await api(`/api/offers/${o.id}`, { method: 'PATCH', body: { status } }); reload() }

  return (
    <>
      <div className="topbar" style={{ marginBottom: 8 }}>
        <Link className="back" to="/">← Voltar ao radar</Link>
        <RunControl />
      </div>
      <div className="hero">
        <div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
            <StatusBadge status={o.status} /><BlueOceanBadge score={o.blue_ocean_score} /><Ver v={o.verification} />
            {o.status_locked && <span className="tag">status fixado manualmente</span>}
          </div>
          <h1>{o.name}</h1>
          <div className="hero-meta">
            <span>👤 <b>{o.advertiser}</b></span>
            {o.niche && <span>🧭 {o.niche}</span>}
            <span>💰 {brl(o.price_brl)}{o.price_source ? <span className="muted"> ({o.price_source})</span> : ''}</span>
            {o.product_format && <span>📦 {o.product_format}</span>}
            {o.checkout_platform && <span>🛒 {o.checkout_platform}</span>}
            <span className="muted">1ª vez visto {dateBR(o.first_seen_at)} · analisado há {ago(o.last_analyzed_at)}</span>
          </div>
          <div className="hero-meta" style={{ marginTop: 8 }}>
            {o.landing_url && <a className="tag" href={o.landing_url} target="_blank" rel="noreferrer">↗ Página da oferta</a>}
            {o.advertiser_detail?.library_url && <a className="tag" href={o.advertiser_detail.library_url} target="_blank" rel="noreferrer">↗ Meta Ads Library</a>}
            {o.advertiser_detail?.page_url && <a className="tag" href={o.advertiser_detail.page_url} target="_blank" rel="noreferrer">↗ Página do anunciante</a>}
            <select className="input" style={{ padding: '3px 8px', fontSize: 12 }} value="" onChange={(e) => e.target.value && setStatus(e.target.value)} aria-label="Alterar status">
              <option value="">Alterar status…</option>
              {Object.entries(STATUS).map(([k, s]) => <option key={k} value={k}>{s.icon} {s.label}</option>)}
            </select>
          </div>
        </div>
        <div className="big-scores">
          <div className="big-score"><div className="l">Velocity Score</div><div className="v">{Math.round(o.velocity_score ?? 0)}<span className="muted" style={{ fontSize: 14 }}>/100</span></div><div className="c">confiança {Math.round(o.velocity_confidence ?? 0)}/100</div></div>
          <div className="big-score"><div className="l">Score Mar Azul</div><div className="v" style={{ color: 'var(--st-blue)' }}>{Math.round(o.blue_ocean_score ?? 0)}<span className="muted" style={{ fontSize: 14 }}>/100</span></div><div className="c">confiança {Math.round(o.blue_ocean_confidence ?? 0)}/100</div></div>
        </div>
      </div>

      <div className="stats-row">
        <div className="mini"><div className="l">Criativos distintos</div><div className="v">{num(m.distinct_creatives)}</div></div>
        <div className="mini"><div className="l">Anúncios ativos (oferta)</div><div className="v">{num(m.observed_ads)}</div></div>
        <div className="mini"><div className="l">Novos 7d / 14d</div><div className="v">{num(m.new_7d)} / {num(m.new_14d)}</div></div>
        <div className="mini"><div className="l">Novos 30d / 40d</div><div className="v">{num(m.new_30d)} / {num(m.new_40d)}</div></div>
        <div className="mini"><div className="l">Antigos ativos (30d+)</div><div className="v">{num(m.old_active)}</div></div>
        <div className="mini"><div className="l">Aceleração</div><div className="v" style={{ fontSize: 15, marginTop: 4 }}>{ACC[acc.signal] || '—'}</div></div>
      </div>

      <div className="grid-2">
        <section className="panel">
          <div className="panel-h">
            <h3>Quantidade de criativos × data</h3>
            <div className="tabs">
              <button className={`tab ${series === 'offer' ? 'on' : ''}`} onClick={() => setSeries('offer')}>Criativos da oferta</button>
              <button className={`tab ${series === 'adv' ? 'on' : ''}`} onClick={() => setSeries('adv')}>Anúncios do anunciante</button>
            </div>
          </div>
          <div className="panel-b">
            <LineChart points={series === 'offer' ? offerPts : advPts} unit={series === 'offer' ? 'criativos' : 'anúncios'} />
            <div className="note">
              {acc.explanation || 'Sem sinal ainda.'}
              {acc.estimated && ' — estimativa: precisa de ≥2 snapshots com 10h+ de intervalo para medir aceleração real.'}
              {' '}Δ3d <b className="mono">{acc.delta_3d ?? '—'}</b> · Δ7d <b className="mono">{acc.delta_7d ?? '—'}</b> · Δ14d <b className="mono">{acc.delta_14d ?? '—'}</b>
              {acc.creative_growth_rate != null && <> · crescimento/dia <b className="mono">{(acc.creative_growth_rate * 100).toFixed(1)}%</b></>}
              {m.series_basis && <> · base: {m.series_basis}</>}
            </div>
          </div>
        </section>
        <section className="panel">
          <div className="panel-h"><h3>Timeline de lançamento (40 dias)</h3></div>
          <div className="panel-b">
            <LaunchBars items={o.launch_timeline} />
            <div className="note">Datas de início dos criativos ativos. Pausados não aparecem (viés de sobrevivência).</div>
          </div>
        </section>
      </div>

      <div className="grid-2e">
        <section className="panel">
          <div className="panel-h"><h3>Velocity Score — composição</h3><span className="muted">{Math.round(vel.score ?? 0)} pts</span></div>
          <div className="panel-b">
            <Breakdown comp={vel.components} labels={VEL_LABELS} />
            {vel.notes?.length > 0 && <div className="note">{vel.notes.join(' · ')}</div>}
          </div>
        </section>
        <section className="panel">
          <div className="panel-h"><h3>Mar Azul — composição</h3><span className="muted">{Math.round(blue.score ?? 0)} pts</span></div>
          <div className="panel-b"><Breakdown comp={blue.components} labels={BLUE_LABELS} evidence={blue.evidence} blue /></div>
        </section>
      </div>

      <section className="panel" style={{ marginBottom: 16 }}>
        <div className="panel-h">
          <div className="tabs">
            {[['ads', `Anúncios (${o.ads.length})`], ['hooks', `Hooks (${(m.hooks || []).length})`], ['funnel', 'Funil / landing'], ['demand', `Demanda (${o.demand.length})`],
              ['model', 'Modelagem'], ['competitors', `Concorrentes (${o.competitors.length})`], ['history', 'Histórico']].map(([k, l]) => (
              <button key={k} className={`tab ${tab === k ? 'on' : ''}`} onClick={() => setTab(k)}>{l}</button>
            ))}
          </div>
          <div className="tags">{Object.entries(m.formats || {}).map(([f, n]) => <span key={f} className="tag">{f} · {n}</span>)}</div>
        </div>
        <div className="panel-b">
          {tab === 'ads' && (
            <div className="ads-grid">
              {o.ads.map((a) => (
                <a key={a.id} className="ad-card" href={a.library_url} target="_blank" rel="noreferrer" style={a.is_active ? undefined : { opacity: 0.5 }}>
                  {a.thumb ? <img src={a.thumb} alt="" loading="lazy" referrerPolicy="no-referrer" onError={(e) => { e.currentTarget.style.display = 'none' }} /> : <div className="noimg">{a.display_format || 'sem mídia'}</div>}
                  <div className="b">
                    <div className="hook">{a.hook || a.title || '—'}</div>
                    <div className="secondary" style={{ display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{a.body}</div>
                    <div className="f"><span>{a.display_format} · {a.cta_text || '—'}</span><span>{a.is_active ? `desde ${dateBR(a.start_date)}` : 'inativo'}</span></div>
                    <div className="f"><span className="mono">crv {a.fingerprint}</span>{a.collation_count > 1 && <span>{a.collation_count} versões</span>}</div>
                  </div>
                </a>
              ))}
              {!o.ads.length && <div className="empty">Nenhum anúncio coletado.</div>}
            </div>
          )}
          {tab === 'hooks' && <ul className="list">{(m.hooks || []).map((h, i) => <li key={i}>{h}</li>)}</ul>}
          {tab === 'funnel' && (lp ? (
            <div className="grid-2e" style={{ marginBottom: 0 }}>
              <div>
                <div style={{ marginBottom: 10, display: 'flex', gap: 8, alignItems: 'center' }}><Ver v={lp.status} /><span className="muted">capturado há {ago(lp.fetched_at)}</span></div>
                {lpd.currency_note && <div className="warn-box" style={{ marginBottom: 10 }}>{lpd.currency_note}</div>}
                <Kv items={[
                  ['Headline', lpd.headline], ['Subheadline', lpd.subheadline], ['Promessa', lpd.promise], ['Mecanismo', lpd.mechanism],
                  ['Preço', lpd.price_brl != null ? brl(lpd.price_brl) : null], ['Preço anterior', lpd.price_old_brl != null ? brl(lpd.price_old_brl) : null],
                  ['Entregáveis', lpd.deliverables], ['Bônus', lpd.bonuses], ['Prova', lpd.proof],
                  ['Depoimentos', lpd.testimonials ? `${lpd.testimonials} menções` : null], ['Garantia', lpd.guarantee], ['Urgência', lpd.urgency],
                  ['CTAs', lpd.ctas], ['Checkout', lpd.checkout_url], ['Order bump', lpd.order_bump ? 'sim' : null], ['Upsell', lpd.upsell ? 'sim' : null],
                  ['Quiz', lpd.quiz ? 'sim' : 'não'], ['VSL', lpd.vsl ? 'sim' : 'não'], ['Estrutura (headings)', lpd.structure],
                  ['URL final', lp.final_url], ['Erro', lp.error],
                ]} />
              </div>
              <div>{lp.screenshot ? <a href={lp.screenshot} target="_blank" rel="noreferrer"><img className="shot" src={lp.screenshot} alt="Screenshot da landing page" /></a> : <div className="empty">Sem screenshot.</div>}</div>
            </div>
          ) : <div className="empty">Landing page ainda não analisada.</div>)}
          {tab === 'demand' && (
            <>
              <div style={{ marginBottom: 10 }}><Ver v={o.demand_status} /> <span className="muted">Fontes externas (Google/Bing/DDG/Brave, Reddit, fóruns). Bloqueios ficam como NÃO VERIFICADO — nada é inferido.</span></div>
              <ul className="list">{o.demand.map((d, i) => (
                <li key={i}><span className="tag">{d.kind}</span> <a href={d.url} target="_blank" rel="noreferrer"><b>{d.title}</b></a> <span className="muted">— {d.snippet?.slice(0, 180)} ({d.source}: “{d.query}”)</span></li>
              ))}</ul>
              {!o.demand.length && <div className="empty">Sem evidências coletadas ainda.</div>}
            </>
          )}
          {tab === 'model' && (
            <>
              <div className="warn-box" style={{ marginBottom: 14 }}>⚖️ {mod.aviso || 'Use apenas como inteligência de mercado. Não copie marca, nome, textos, criativos ou propriedade intelectual.'}</div>
              <Kv items={[
                ['Dor', mod.dor], ['Público', mod.publico], ['Mecanismo', mod.mecanismo], ['Promessa', mod.promessa],
                ['Estrutura', mod.estrutura], ['Ângulos usados', mod.angulos ? Object.entries(mod.angulos).map(([a, n]) => `${a} (${n})`) : null],
                ['Modelo comercial', mod.modelo_comercial ? Object.entries(mod.modelo_comercial).filter(([, v]) => v != null && v !== 0).map(([k, v]) => `${k}: ${v === true ? 'sim' : v}`) : null],
                ['Palavras-chave', mod.palavras_chave], ['Diferenciação sugerida', mod.diferenciacao_sugerida],
              ]} />
            </>
          )}
          {tab === 'competitors' && (
            <table><thead><tr><th>Oferta</th><th>Anunciante</th><th className="r">Preço</th><th className="r">Criativos</th><th className="r">Velocity</th><th>Status</th></tr></thead>
              <tbody>{o.competitors.map((c) => (
                <tr key={c.id} onClick={() => { window.location.href = `/offers/${c.id}` }}>
                  <td><div className="offer-name">{c.name}</div></td><td>{c.advertiser}</td><td className="r mono">{brl(c.price_brl)}</td>
                  <td className="r mono">{num(c.creatives)}</td><td className="r mono">{Math.round(c.velocity_score ?? 0)}</td><td><StatusBadge status={c.status} /></td>
                </tr>))}</tbody></table>
          )}
          {tab === 'history' && (
            <>
              <h4 style={{ margin: '0 0 8px' }}>Status</h4>
              <ul className="list">{(o.history || []).map(([t, s, why], i) => <li key={i}><span className="mono muted">{new Date(t + 'Z').toLocaleString('pt-BR')}</span> <StatusBadge status={s} /> <span className="secondary">{why}</span></li>)}</ul>
              <h4 style={{ margin: '16px 0 8px' }}>Snapshots</h4>
              <div className="table-wrap"><table><thead><tr><th>Data</th><th className="r">Criativos</th><th className="r">Anúncios</th><th className="r">Novos 7d</th><th className="r">Novos 14d</th><th className="r">Antigos</th><th className="r">Hooks</th><th className="r">Cobertura</th><th>Dado</th></tr></thead>
                <tbody>{[...o.snapshots].reverse().map((s, i) => (
                  <tr key={i} style={{ cursor: 'default' }}><td className="mono">{new Date(s.taken_at + 'Z').toLocaleString('pt-BR')}</td><td className="r mono">{s.distinct_creatives}</td>
                    <td className="r mono">{s.active_ads_total ?? '—'}</td><td className="r mono">{s.new_7d}</td><td className="r mono">{s.new_14d}</td><td className="r mono">{s.old_active}</td>
                    <td className="r mono">{s.hooks_count}</td><td className="r mono">{s.coverage != null ? `${Math.round(s.coverage * 100)}%` : '—'}</td><td><Ver v={s.verification} /></td></tr>))}</tbody></table></div>
              <h4 style={{ margin: '16px 0 8px' }}>Triagem</h4>
              <Kv items={[['Checks', o.validation?.checks ? Object.entries(o.validation.checks).map(([k, v]) => `${k}: ${v == null ? 'não observado' : v ? 'sim' : 'não'}`) : null],
                ['Motivos', o.validation?.reasons], ['Descarte', o.discard_reason], ['Estágio', `${o.stage} — ${m.stage_reason || ''}`],
                ['Descoberto via', o.advertiser_detail?.discovered_via]]} />
            </>
          )}
        </div>
      </section>
    </>
  )
}
