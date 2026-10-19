import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AUTH_ROUTES, useAuthRouteState } from '../auth/routes'
import { authErrorMessage, emailError } from '../auth/signup'
import { AuthShell, PasswordInput } from '../components/AuthShell'
import { Banner, Field } from '../components/ui'

export default function Login() {
  const { login, notice } = useAuth()
  const navigate = useNavigate()
  const routeState = useAuthRouteState()
  const [email, setEmail] = useState(routeState.email ?? '')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitted, setSubmitted] = useState(false)
  const [emailBlurred, setEmailBlurred] = useState(false)
  const emailInvalid = submitted || (emailBlurred && email) ? emailError(email) : null
  const passwordInvalid = submitted && !password ? 'Informe sua senha.' : null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setSubmitted(true)
    setError(null)
    if (emailError(email) || !password) return
    setBusy(true)
    try {
      await login(email, password)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'email_not_confirmed') {
        navigate(AUTH_ROUTES.verify, { state: { email: email.trim(), notice: 'Confirme seu e-mail para entrar. Você pode pedir uma nova mensagem abaixo.', noticeTone: 'info' } })
        return
      }
      setError(authErrorMessage(err, 'login').message)
    } finally {
      setBusy(false)
    }
  }

  const banner = error ?? notice ?? routeState.notice ?? null
  const tone = error || notice ? 'error' : routeState.noticeTone ?? 'info'

  return (
    <AuthShell>
      <div className="auth-head">
        <h1>Painel do vendedor</h1>
        <p className="lead">Acompanhe receita, energia e o status das suas estações em tempo real.</p>
      </div>
      <form className="auth-fields" onSubmit={submit} noValidate>
        {banner ? (
          <Banner tone={tone} icon={tone === 'ok' ? 'check' : tone === 'info' ? 'mail' : 'alert'}>
            {banner}
          </Banner>
        ) : null}
        <Field label="E-mail" error={emailInvalid}>
          <input className="input input-big" type="email" autoComplete="username" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} onBlur={() => setEmailBlurred(true)} placeholder="voce@empresa.com.br" autoFocus aria-invalid={Boolean(emailInvalid)} maxLength={254} />
        </Field>
        <Field label="Senha" error={passwordInvalid}>
          <PasswordInput autoComplete="current-password" value={password} onChange={setPassword} placeholder="Sua senha" aria-invalid={Boolean(passwordInvalid)} maxLength={128} />
        </Field>
        <div className="auth-row">
          <Link className="link-btn" to={AUTH_ROUTES.forgot} state={{ email: email.trim() }}>
            Esqueci minha senha
          </Link>
        </div>
        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
          {busy ? 'Entrando…' : 'Entrar'}
        </button>
      </form>
      <div className="auth-divider">
        <span>Novo no ChargeGrid?</span>
      </div>
      <Link className="btn btn-secondary btn-lg btn-block" to={AUTH_ROUTES.register} state={{ email: email.trim() }}>
        Criar conta de vendedor
      </Link>
      <p className="auth-foot">Use a mesma conta do app ChargeGrid.</p>
    </AuthShell>
  )
}
