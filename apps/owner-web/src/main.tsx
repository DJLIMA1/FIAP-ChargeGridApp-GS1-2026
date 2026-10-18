import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles/global.css'

async function start() {
  // Modo demonstração SOMENTE em desenvolvimento: `import.meta.env.DEV` é
  // `false` no build de produção, então este bloco (e o módulo mock) é
  // eliminado pelo bundler — conferido por `npm run check:dist`.
  if (import.meta.env.DEV && import.meta.env.VITE_MOCK === '1') {
    const { installMock } = await import('./mock')
    installMock()
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  )
}

void start()
