import { lazy, Suspense } from 'react'
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { AUTH_ROUTES } from './auth/routes'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { EmptyState, Logo, Skeleton } from './components/ui'
import { FiltersProvider } from './lib/filters'
import ForgotPassword from './pages/ForgotPassword'
import Login from './pages/Login'
import OperatorPending from './pages/OperatorPending'
import Signup from './pages/Signup'
import VerifyEmail from './pages/VerifyEmail'

const Overview = lazy(() => import('./pages/Overview'))
const Stations = lazy(() => import('./pages/Stations'))
const StationDetail = lazy(() => import('./pages/StationDetail'))
const Sessions = lazy(() => import('./pages/Sessions'))
const Alerts = lazy(() => import('./pages/Alerts'))
const Coupons = lazy(() => import('./pages/Coupons'))
const Insights = lazy(() => import('./pages/Insights'))
const Result = lazy(() => import('./pages/Result'))

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

function NotFound() {
  return (
    <div className="card">
      <EmptyState icon="info" title="Página não encontrada" action={<Link className="btn btn-primary" to="/">Ir para a visão geral</Link>}>
        O endereço acessado não existe neste painel.
      </EmptyState>
    </div>
  )
}

/** Telas de acesso que não fazem sentido com a sessão aberta. */
const AUTH_PATHS = ['/login', ...Object.values(AUTH_ROUTES)]

function Gate() {
  const { status } = useAuth()
  if (status === 'booting') return <Splash />
  if (status === 'signed_out') {
    return (
      <Routes>
        <Route path={AUTH_ROUTES.login} element={<Login />} />
        <Route path={AUTH_ROUTES.register} element={<Signup />} />
        <Route path={AUTH_ROUTES.verify} element={<VerifyEmail />} />
        <Route path={AUTH_ROUTES.forgot} element={<ForgotPassword />} />
        <Route path="/login" element={<Navigate to={AUTH_ROUTES.login} replace />} />
        {/* Link profundo (ex.: /sessoes): entra e continua no mesmo endereço. */}
        <Route path="*" element={<Login />} />
      </Routes>
    )
  }
  if (status === 'operator_pending') {
    return (
      <Routes>
        {AUTH_PATHS.map((path) => (
          <Route key={path} path={path} element={<Navigate to="/" replace />} />
        ))}
        <Route path="*" element={<OperatorPending />} />
      </Routes>
    )
  }
  return (
    <FiltersProvider>
      <Routes>
        <Route element={<Layout />}>
          <Route index element={<Suspense fallback={<PageFallback />}><Overview /></Suspense>} />
          <Route path="estacoes" element={<Suspense fallback={<PageFallback />}><Stations /></Suspense>} />
          <Route path="estacoes/:id" element={<Suspense fallback={<PageFallback />}><StationDetail /></Suspense>} />
          <Route path="sessoes" element={<Suspense fallback={<PageFallback />}><Sessions /></Suspense>} />
          <Route path="alertas" element={<Suspense fallback={<PageFallback />}><Alerts /></Suspense>} />
          <Route path="resultado" element={<Suspense fallback={<PageFallback />}><Result /></Suspense>} />
          <Route path="cupons" element={<Suspense fallback={<PageFallback />}><Coupons /></Suspense>} />
          <Route path="insights" element={<Suspense fallback={<PageFallback />}><Insights /></Suspense>} />
          {AUTH_PATHS.map((path) => (
            <Route key={path} path={path} element={<Navigate to="/" replace />} />
          ))}
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
