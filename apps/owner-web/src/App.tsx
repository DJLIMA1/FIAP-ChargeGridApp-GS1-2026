import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { OPERATOR_PENDING_MESSAGE } from './auth/vendor'
import { Icon } from './components/Icon'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { EmptyState, Logo, Skeleton } from './components/ui'
import { FiltersProvider } from './lib/filters'
import Login from './pages/Login'

const Overview = lazy(() => import('./pages/Overview'))
const Stations = lazy(() => import('./pages/Stations'))
const StationDetail = lazy(() => import('./pages/StationDetail'))
const Sessions = lazy(() => import('./pages/Sessions'))
const Alerts = lazy(() => import('./pages/Alerts'))
const Coupons = lazy(() => import('./pages/Coupons'))
const Insights = lazy(() => import('./pages/Insights'))

function Splash() {
  return (
    <div className="center-screen" aria-busy="true" aria-label="Carregando painel">
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 18 }}>
        <Logo height={28} />
        <Skeleton width={160} height={4} radius={2} />
      </div>
    </div>
  )
}

function PageFallback() {
  return (
    <div className="stack" aria-busy="true" aria-label="Carregando">
      <Skeleton width="40%" height={34} />
      <div className="grid kpis">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} height={118} radius={16} />
        ))}
      </div>
      <Skeleton height={320} radius={16} />
    </div>
  )
}

function OperatorPending() {
  const { logout, profile } = useAuth()
  return (
    <div className="center-screen">
      <div className="restricted card" style={{ padding: 32 }}>
        <Logo height={24} />
        <h1 style={{ margin: '8px 0 0', fontSize: 26 }}>Olá{profile?.name ? `, ${profile.name.split(' ')[0]}` : ''}!</h1>
        <p className="muted" style={{ margin: 0, fontSize: 15 }}>
          {OPERATOR_PENDING_MESSAGE}
        </p>
        <button type="button" className="btn btn-secondary" style={{ alignSelf: 'flex-start' }} onClick={() => void logout()}>
          <Icon name="logout" size={16} /> Sair
        </button>
      </div>
    </div>
  )
}

function NotFound() {
  return (
    <div className="card">
      <EmptyState icon="info" title="Página não encontrada" action={<Link className="btn btn-primary" to="/">Ir para a visão geral</Link>}>
        O endereço acessado não existe neste painel.
      </EmptyState>
    </div>
  )
}

function Gate() {
  const { status } = useAuth()
  if (status === 'booting') return <Splash />
  if (status === 'signed_out') {
    return (
      <Routes>
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  if (status === 'operator_pending') return <OperatorPending />
  return (
    <FiltersProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Suspense fallback={<PageFallback />}><Overview /></Suspense>} />
          <Route path="estacoes" element={<Suspense fallback={<PageFallback />}><Stations /></Suspense>} />
          <Route path="estacoes/:id" element={<Suspense fallback={<PageFallback />}><StationDetail /></Suspense>} />
          <Route path="sessoes" element={<Suspense fallback={<PageFallback />}><Sessions /></Suspense>} />
          <Route path="alertas" element={<Suspense fallback={<PageFallback />}><Alerts /></Suspense>} />
          <Route path="cupons" element={<Suspense fallback={<PageFallback />}><Coupons /></Suspense>} />
          <Route path="insights" element={<Suspense fallback={<PageFallback />}><Insights /></Suspense>} />
          <Route path="login" element={<Navigate to="/" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </FiltersProvider>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <ToastProvider>
        <AuthProvider>
          <Gate />
        </AuthProvider>
      </ToastProvider>
    </BrowserRouter>
  )
}
