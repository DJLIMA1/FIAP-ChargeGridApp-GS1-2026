import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import Root from './Root'
import { DASHBOARD_BASE } from './basePath'
import './styles/global.css'

async function start() {
  const { pathname, search, hash } = window.location
  const inDashboard = pathname === DASHBOARD_BASE || pathname.startsWith(`${DASHBOARD_BASE}/`)
  // A raiz é a apresentação do projeto; o painel vive sob /dashboard. Links
  // antigos do painel (ex.: /estacoes, /entrar) seguem para o novo endereço.
  if (!inDashboard && pathname !== '/') {
    window.location.replace(`${DASHBOARD_BASE}${pathname}${search}${hash}`)
    return
  }
  // Modo demonstração SOMENTE em desenvolvimento: `import.meta.env.DEV` é
  // `false` no build de produção, então este bloco (e o módulo mock) é
  // eliminado pelo bundler — conferido por `npm run check:dist`.
  if (inDashboard && import.meta.env.DEV && import.meta.env.VITE_MOCK === '1') {
    const { installMock } = await import('./mock')
    installMock()
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <Root dashboard={inDashboard} />
    </StrictMode>,
  )
}

void start()
