import { useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Icon, type IconName } from '../components/Icon'
import { Banner, Field, Logo } from '../components/ui'

const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function Rings() {
  return (
    <svg className="auth-rings" viewBox="0 0 600 200" aria-hidden>
      <defs>
        <radialGradient id="ring-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#D72B32" stopOpacity="0.55" />
          <stop offset="70%" stopColor="#D72B32" stopOpacity="0.08" />
          <stop offset="100%" stopColor="#D72B32" stopOpacity="0" />
        </radialGradient>
      </defs>
      <ellipse cx="300" cy="100" rx="290" ry="92" fill="url(#ring-glow)" />
      <ellipse cx="300" cy="100" rx="270" ry="80" fill="none" stroke="#D72B32" strokeOpacity="0.55" strokeWidth="2" />
      <ellipse cx="300" cy="100" rx="200" ry="56" fill="#2a1416" stroke="#D72B32" strokeWidth="3" />
      <ellipse cx="300" cy="96" rx="168" ry="44" fill="none" stroke="#ff6b71" strokeOpacity="0.4" strokeWidth="1.5" />
    </svg>
  )
}

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  { icon: 'chart', title: 'Receita e energia', text: 'Por dia, por hora e por ponto' },
  { icon: 'station', title: 'Estações e tarifas', text: 'Preço, potência e status' },
  { icon: 'sparkles', title: 'Insights IA', text: 'Recomendações de preço e operação' },
]

export default function Login() {
  const { login, api, notice } = useAuth()
  const [mode, setMode] = useState<'login' | 'forgot'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [show, setShow] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  const emailError = email && !EMAIL.test(email.trim()) ? 'Informe um e-mail válido' : null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setError(null)
    if (!EMAIL.test(email.trim())) {
      setError('Informe um e-mail válido.')
      return
    }
    setBusy(true)
    try {
      if (mode === 'login') {
        if (!password) {
          setError('Informe sua senha.')
          return
        }
        await login(email, password)
      } else {
        const response = await api.forgotPassword(email.trim())
        setSent(response?.message || 'Se a conta existir, você receberá instruções para recuperar a senha.')
      }
    } catch (err) {
      setError(err instanceof ApiError ? (err.code === 'auth_rejected' ? 'E-mail ou senha incorretos.' : err.message) : 'Não foi possível entrar agora.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <div className="auth-panel">
        <form className="auth-form" onSubmit={submit} noValidate>
          <Logo height={26} />
          <h1>{mode === 'login' ? 'Painel do vendedor' : 'Recuperar senha'}</h1>
          <p className="lead">
            {mode === 'login'
              ? 'Acompanhe receita, energia e o status das suas estações em tempo real.'
              : 'Informe o e-mail da sua conta. Enviaremos as instruções para criar uma nova senha.'}
          </p>
          {notice && mode === 'login' ? (
            <Banner tone="error" icon="alert">
              {notice}
            </Banner>
          ) : null}
          {error ? (
            <Banner tone="error" icon="alert">
              {error}
            </Banner>
          ) : null}
          {sent && mode === 'forgot' ? (
            <Banner tone="ok" icon="check">
              {sent}
            </Banner>
          ) : null}
          <Field label="E-mail" error={emailError}>
            <input className="input input-big" type="email" autoComplete="username" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@empresa.com.br" autoFocus aria-invalid={Boolean(emailError)} />
          </Field>
          {mode === 'login' ? (
            <Field label="Senha">
              <div style={{ position: 'relative' }}>
                <input className="input input-big" style={{ width: '100%', paddingRight: 48 }} type={show ? 'text' : 'password'} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Sua senha" />
                <button type="button" className="pw-toggle" onClick={() => setShow((v) => !v)} aria-label={show ? 'Ocultar senha' : 'Mostrar senha'}>
                  <Icon name={show ? 'eyeOff' : 'eye'} size={19} />
                </button>
              </div>
            </Field>
          ) : null}
          <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
            {busy ? (mode === 'login' ? 'Entrando…' : 'Enviando…') : mode === 'login' ? 'Entrar' : 'Enviar instruções'}
          </button>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <button
              type="button"
              className="link-btn"
              onClick={() => {
                setMode(mode === 'login' ? 'forgot' : 'login')
                setError(null)
                setSent(null)
              }}
            >
              {mode === 'login' ? 'Esqueci minha senha' : 'Voltar para o login'}
            </button>
            <span className="dim" style={{ fontSize: 13 }}>
              Use a mesma conta do app ChargeGrid
            </span>
          </div>
        </form>
      </div>
      <div className="auth-visual" aria-hidden>
        <Rings />
        <p className="auth-quote">Sua operação de recarga, em um só painel.</p>
        <div className="auth-metrics">
          {FEATURES.map((feature) => (
            <div className="card" key={feature.title}>
              <span className="tile" style={{ width: 36, height: 36, marginBottom: 12 }}>
                <Icon name={feature.icon} size={18} />
              </span>
              <div style={{ fontWeight: 600 }}>{feature.title}</div>
              <div className="muted" style={{ fontSize: 13 }}>
                {feature.text}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
