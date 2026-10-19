import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { AUTH_ROUTES, useAuthRouteState } from '../auth/routes'
import { authErrorMessage, emailError, RESEND_MESSAGE } from '../auth/signup'
import { Icon } from '../components/Icon'
import { AuthShell } from '../components/AuthShell'
import { Banner, Field } from '../components/ui'

/** A API aceita um reenvio por minuto por e-mail. */
const COOLDOWN_S = 60

export default function VerifyEmail() {
  const { api } = useAuth()
  const navigate = useNavigate()
  const routeState = useAuthRouteState()
  const [email, setEmail] = useState(routeState.email ?? '')
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<{ tone: 'ok' | 'error' | 'info'; text: string } | null>(
    routeState.notice ? { tone: routeState.noticeTone ?? 'info', text: routeState.notice } : null,
  )
  const [fieldError, setFieldError] = useState<string | null>(null)
  const [cooldown, setCooldown] = useState(0)

  useEffect(() => {
    if (cooldown <= 0) return
    const timer = setTimeout(() => setCooldown((s) => s - 1), 1000)
    return () => clearTimeout(timer)
  }, [cooldown])

  const resend = async () => {
    if (busy || cooldown > 0) return
    const invalid = emailError(email)
    setFieldError(invalid)
    if (invalid) return
    setBusy(true)
    setFeedback(null)
    try {
      await api.resendSignup(email.trim())
      // Sempre a mesma mensagem neutra, como no app: não revela se a conta existe.
      setFeedback({ tone: 'ok', text: RESEND_MESSAGE })
      setCooldown(COOLDOWN_S)
    } catch (err) {
      setFeedback({ tone: 'error', text: authErrorMessage(err, 'resend').message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell>
      <div className="auth-head">
        <span className="auth-badge">
          <Icon name="mail" size={22} />
        </span>
        <h1>Verifique seu e-mail</h1>
        <p className="lead">
          {routeState.email ? (
            <>
              Abra o link de confirmação enviado para <b className="auth-email">{routeState.email}</b> e depois volte para entrar.
            </>
          ) : (
            'Abra o link de confirmação que enviamos. Se já confirmou, volte para entrar.'
          )}
        </p>
      </div>
      <div className="auth-fields">
        {feedback ? (
          <Banner tone={feedback.tone} icon={feedback.tone === 'ok' ? 'check' : feedback.tone === 'info' ? 'mail' : 'alert'}>
            {feedback.text}
          </Banner>
        ) : null}
        {routeState.email ? null : (
          <Field label="E-mail" error={fieldError}>
            <input className="input input-big" type="email" autoComplete="email" inputMode="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@empresa.com.br" maxLength={254} aria-invalid={Boolean(fieldError)} />
          </Field>
        )}
        <button type="button" className="btn btn-primary btn-lg btn-block" onClick={() => navigate(AUTH_ROUTES.login, { state: { email: email.trim() } })}>
          Voltar para entrar
        </button>
        <button type="button" className="btn btn-secondary btn-lg btn-block" onClick={() => void resend()} disabled={busy || cooldown > 0}>
          {busy ? 'Enviando…' : cooldown > 0 ? `Reenviar confirmação em ${cooldown} s` : 'Reenviar confirmação'}
        </button>
        <ul className="auth-tips">
          <li>Não encontrou? Confira as pastas de spam e promoções.</li>
          <li>O link confirma a conta; depois é só entrar com seu e-mail e senha.</li>
        </ul>
      </div>
    </AuthShell>
  )
}
