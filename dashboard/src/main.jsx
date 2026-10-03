import React, { useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom'
import './styles.css'
import Dashboard from './pages/Dashboard.jsx'
import OfferPage from './pages/Offer.jsx'
import Runs from './pages/Runs.jsx'
import Keywords from './pages/Keywords.jsx'
import { api, ago, useApi } from './ui.jsx'

function RunControl() {
  const { data, reload } = useApi('/api/stats', [], 8000)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const running = data?.running
  const start = async () => {
    setBusy(true); setErr(null)
    try { await api('/api/runs', { method: 'POST', body: {} }); setTimeout(reload, 1500) } catch (e) { setErr(e.message) }
    setBusy(false)
  }
  const lr = data?.last_run
  return (
    <div className="actions">
      <span className="run-pill">
        <span className={`dot ${running ? 'live' : ''}`} />
        {running ? 'Garimpando agora…' : lr ? `Última rodada ${ago(lr.finished_at || lr.started_at)} · ${lr.status}` : 'Nenhuma rodada ainda'}
      </span>
      <button className="btn primary" onClick={start} disabled={busy || running}>▶ Rodar agora</button>
      {err && <span className="muted" style={{ fontSize: 12 }}>{err}</span>}
    </div>
  )
}

function Layout({ children }) {
  return (
    <div className="shell">
      <aside className="side">
        <div className="brand">
          <div className="brand-mark" aria-hidden>
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ff7a1a" strokeWidth="2">
              <circle cx="12" cy="12" r="9" opacity=".35" /><circle cx="12" cy="12" r="5" opacity=".6" />
              <path d="M12 12 L19 6" strokeLinecap="round" /><circle cx="12" cy="12" r="1.5" fill="#ff7a1a" />
            </svg>
          </div>
          <div className="brand-text">
            <div className="brand-title">RADAR</div>
            <div className="brand-sub">LOW TICKET</div>
          </div>
        </div>
        <nav className="nav">
          <NavLink to="/" end>📡 Radar</NavLink>
          <NavLink to="/watchlist">👁 Watchlist</NavLink>
          <NavLink to="/keywords">🧭 Palavras &amp; nichos</NavLink>
          <NavLink to="/runs">🗂 Rodadas &amp; logs</NavLink>
        </nav>
        <div className="side-foot">Quem está acelerando agora?</div>
      </aside>
      <main className="main">{children(RunControl)}</main>
    </div>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter>
    <Layout>
      {(RC) => (
        <Routes>
          <Route path="/" element={<Dashboard RunControl={RC} />} />
          <Route path="/watchlist" element={<Dashboard RunControl={RC} watchlist />} />
          <Route path="/offers/:id" element={<OfferPage RunControl={RC} />} />
          <Route path="/runs" element={<Runs RunControl={RC} />} />
          <Route path="/keywords" element={<Keywords RunControl={RC} />} />
        </Routes>
      )}
    </Layout>
  </BrowserRouter>,
)
