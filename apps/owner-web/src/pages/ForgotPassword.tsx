import { useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { AUTH_ROUTES, useAuthRouteState } from '../auth/routes'
import { authErrorMessage, emailError, FORGOT_MESSAGE } from '../auth/signup'
import { AuthShell } from '../components/AuthShell'
import { Icon } from '../components/Icon'
import { Banner, Field } from '../components/ui'

export default function ForgotPassword() {
  const { api } = useAuth()
  const routeState = useAuthRouteState()
  const [email, setEmail] = useState(routeState.email ?? '')
  const [submitted, setSubmitted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sent, setSent] = useState<string | null>(null)
  const fieldError = submitted ? emailError(email) : null

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setSubmitted(true)
    setError(null)
    if (emailError(email)) return
    setBusy(true)
    try {
      const response = await api.forgotPassword(email.trim())
      setSent(response?.message ? `${response.message.replace(/\.?$/, '.')}` : FORGOT_MESSAGE)
    } catch (err) {
      setError(authErrorMessage(err, 'forgot').message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <div className="auth-head">
        <Link className="back-link" to={AUTH_ROUTES.login} state={{ email: email.trim() }}>
          <Icon name="chevronLeft" size={16} /> Voltar para entrar
        </Link>
        <h1>Recuperar senha</h1>
        <p className="lead">Informe o e-mail da sua conta. Enviaremos as instruções para criar uma nova senha.</p>
      </div>
      <form className="auth-fields" onSubmit={submit} noValidate>
        {error ? (
          <Banner tone="error" icon="alert">
            {error}
          </Banner>
        ) : null}
        {sent ? (
          <Banner tone="ok" icon="check">
            {sent}
          </Banner>
        ) : null}
        <Field label="E-mail" error={fieldError}>
          <input className="input input-big" type="email" autoComplete="username" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@empresa.com.br" autoFocus maxLength={254} aria-invalid={Boolean(fieldError)} />
        </Field>
        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
          {busy ? 'Enviando…' : sent ? 'Enviar novamente' : 'Enviar instruções'}
        </button>
      </form>
      <p className="auth-switch">
        <Link to={AUTH_ROUTES.register} state={{ email: email.trim() }}>
          Ainda não tem conta? <b>Criar conta</b>
        </Link>
      </p>
    </AuthShell>
  )
}
