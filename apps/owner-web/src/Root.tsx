import { lazy, Suspense } from 'react'

const App = lazy(() => import('./App'))
const Landing = lazy(() => import('./landing/Landing'))

/** Escolhe entre o painel (/dashboard) e a apresentação do projeto (raiz). */
export default function Root({ dashboard }: { dashboard: boolean }) {
  return <Suspense fallback={null}>{dashboard ? <App /> : <Landing />}</Suspense>
}
