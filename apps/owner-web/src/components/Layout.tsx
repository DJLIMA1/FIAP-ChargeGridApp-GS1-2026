import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { useFilters } from '../lib/filters'
import { firstName, formatTime } from '../lib/format'
import { PRESET_LABELS, validatePeriod, type PeriodPreset } from '../lib/period'
import { useApi } from '../lib/useApi'
import { Icon, type IconName } from './Icon'
import { Logo } from './ui'

const NAV: { to: string; label: string; icon: IconName; short?: string }[] = [
  { to: '/', label: 'Visão geral', icon: 'home', short: 'Início' },
  { to: '/estacoes', label: 'Estações', icon: 'station' },
  { to: '/sessoes', label: 'Sessões', icon: 'clock' },
  { to: '/alertas', label: 'Alertas', icon: 'bell' },
  { to: '/resultado', label: 'Resultado', icon: 'wallet' },
  { to: '/cupons', label: 'Cupons', icon: 'ticket' },
  { to: '/insights', label: 'Insights IA', icon: 'sparkles' },
]

function useAlertCount() {
  const { ep } = useAuth()
  const { stationId, refreshKey } = useFilters()
  const { data } = useApi((signal) => ep.alerts(stationId, signal), `alerts-count|${refreshKey}`)
  return data ? data.items.filter((item) => item.severity !== 'info').length : 0
}

function Sidebar({ open, onNavigate, alertCount }: { open: boolean; onNavigate(): void; alertCount: number }) {
  const { stations, stationsLoading } = useFilters()
  const active = stations.filter((s) => s.active).length
  return (
    <aside className={`sidebar ${open ? 'open' : ''}`} aria-label="Navegação principal">
      <NavLink to="/" className="brand" onClick={onNavigate} aria-label="ChargeGrid — Visão geral">
        <Logo height={24} />
      </NavLink>
      <div className="brand-sub">Painel do vendedor</div>
      <nav className="nav">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === '/'} className={({ isActive }) => `nav-link ${isActive ? 'active' : ''}`} onClick={onNavigate}>
            <Icon name={item.icon} size={21} />
            {item.label}
            {item.to === '/alertas' && alertCount > 0 ? <span className="count" aria-label={`${alertCount} alertas`}>{alertCount}</span> : null}
          </NavLink>
        ))}
      </nav>
      <div className="sidebar-foot">
        <div className="sidebar-card">
          <div className="label">Estações ativas</div>
          <div className="value">
            {stationsLoading && !stations.length ? '—' : (
              <>
                <span className="green">{active}</span> <span className="dim" style={{ fontSize: 18 }}>de {stations.length}</span>
              </>
            )}
          </div>
        </div>
      </div>
    </aside>
  )
}

function PeriodControl() {
  const { period, setPeriod } = useFilters()
  const [draft, setDraft] = useState({ start: period.start ?? '', end: period.end ?? '' })
  const [customOpen, setCustomOpen] = useState(period.preset === 'custom')
  const error = customOpen ? validatePeriod({ preset: 'custom', ...draft }) : null

  const choose = (preset: PeriodPreset) => {
    if (preset === 'custom') {
      setCustomOpen(true)
      return
    }
    setCustomOpen(false)
    setPeriod({ preset })
  }
  return (
    <>
      <div className="segmented" role="group" aria-label="Período">
        {(Object.keys(PRESET_LABELS) as PeriodPreset[]).map((preset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={preset === 'custom' ? customOpen : !customOpen && period.preset === preset}
            onClick={() => choose(preset)}
          >
            {preset === 'custom' ? (
              <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                <Icon name="calendar" size={15} />
                <span className="desktop-only">{PRESET_LABELS[preset]}</span>
              </span>
            ) : (
              PRESET_LABELS[preset]
            )}
          </button>
        ))}
      </div>
      {customOpen ? (
        <form
          className="custom-period"
          onSubmit={(event) => {
            event.preventDefault()
            if (!error) setPeriod({ preset: 'custom', ...draft })
          }}
        >
          <input className="input" type="date" aria-label="Data inicial" value={draft.start} max={draft.end || undefined} onChange={(e) => setDraft({ ...draft, start: e.target.value })} />
          <input className="input" type="date" aria-label="Data final" value={draft.end} min={draft.start || undefined} onChange={(e) => setDraft({ ...draft, end: e.target.value })} />
          <button className="btn btn-primary" type="submit" disabled={Boolean(error)} title={error ?? undefined} style={{ height: 38 }}>
            Aplicar
          </button>
        </form>
      ) : null}
    </>
  )
}

function UserMenu() {
  const { profile, logout } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onClick = (event: MouseEvent) => {
      if (!ref.current?.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  const name = profile?.name || 'Vendedor'
  return (
    <div style={{ position: 'relative' }} ref={ref}>
      <button type="button" className="avatar" aria-haspopup="menu" aria-expanded={open} aria-label={`Conta de ${name}`} onClick={() => setOpen((v) => !v)}>
        {(firstName(name)[0] || 'V').toUpperCase()}
      </button>
      {open ? (
        <div className="menu" role="menu">
          <div className="who">
            <b>{name}</b>
            <span>Conta de vendedor</span>
          </div>
          <button type="button" role="menuitem" onClick={() => void logout()}>
            <Icon name="logout" size={18} /> Sair
          </button>
        </div>
      ) : null}
    </div>
  )
}

export function Layout() {
  const { stations, stationId, setStationId, refresh, reloadStations, lastRefresh } = useFilters()
  const [menuOpen, setMenuOpen] = useState(false)
  const [spinning, setSpinning] = useState(false)
  const location = useLocation()
  const alertCount = useAlertCount()
  const closeMenu = useCallback(() => setMenuOpen(false), [])

  useEffect(() => {
    setMenuOpen(false)
    window.scrollTo({ top: 0 })
  }, [location.pathname])

  const onRefresh = () => {
    refresh()
    reloadStations()
    setSpinning(true)
    setTimeout(() => setSpinning(false), 900)
  }
  const isActive = (to: string) => (to === '/' ? location.pathname === '/' : location.pathname.startsWith(to))

  return (
    <div className="shell">
      <Sidebar open={menuOpen} onNavigate={closeMenu} alertCount={alertCount} />
      {menuOpen ? <div className="overlay" style={{ zIndex: 54 }} onClick={closeMenu} aria-hidden /> : null}
      <div className="main">
        <header className="topbar">
          <div className="mobile-brand">
            <Logo height={21} />
          </div>
          <span className="muted desktop-only" style={{ fontSize: 13 }}>
            <span className="live-dot" aria-hidden />
            Dados atualizados às {formatTime(lastRefresh)}
          </span>
          <div className="spacer" />
          <div className="topbar-controls">
            <PeriodControl />
            <select className="select station-select" aria-label="Filtrar por estação" value={stationId ?? ''} onChange={(e) => setStationId(e.target.value || null)}>
              <option value="">Todas as estações</option>
              {stations.map((station) => (
                <option key={station.id} value={station.id}>
                  {station.name}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className={`icon-btn ${spinning ? 'spinning' : ''}`} onClick={onRefresh} aria-label="Atualizar dados" title="Atualizar dados">
            <Icon name="refresh" size={18} />
          </button>
          <UserMenu />
        </header>
        <main className="content" id="conteudo">
          <Outlet />
        </main>
      </div>
      <nav className="bottom-nav" aria-label="Navegação">
        {NAV.slice(0, 4).map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === '/'} className={isActive(item.to) ? 'active' : ''}>
            <Icon name={item.icon} size={22} />
            {item.short ?? item.label}
          </NavLink>
        ))}
        <button type="button" onClick={() => setMenuOpen(true)} className={isActive('/cupons') || isActive('/insights') || isActive('/resultado') ? 'active' : ''} aria-label="Mais opções">
          <Icon name="menu" size={22} />
          Mais
        </button>
      </nav>
    </div>
  )
}
