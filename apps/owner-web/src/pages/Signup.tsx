import { useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { AUTH_ROUTES, useAuthRouteState } from '../auth/routes'
import { authErrorMessage, firstError, NEUTRAL_SIGNUP_MESSAGE, PASSWORD_MAX, PASSWORD_MIN, validateSignup, type SignupErrors, type SignupField } from '../auth/signup'
import { AuthShell, PasswordInput } from '../components/AuthShell'
import { Icon } from '../components/Icon'
import { Banner, Field } from '../components/ui'

export default function Signup() {
  const { register } = useAuth()
  const navigate = useNavigate()
  const routeState = useAuthRouteState()
  const [values, setValues] = useState({ name: '', email: routeState.email ?? '', password: '', confirm: '' })
  const [touched, setTouched] = useState<Partial<Record<SignupField, boolean>>>({})
  const [submitted, setSubmitted] = useState(false)
  const [serverErrors, setServerErrors] = useState<SignupErrors>({})
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const refs = {
    name: useRef<HTMLInputElement>(null),
    email: useRef<HTMLInputElement>(null),
    password: useRef<HTMLInputElement>(null),
    confirm: useRef<HTMLInputElement>(null),
  }

  const errors = validateSignup(values)
  const shown = (field: SignupField) => serverErrors[field] ?? (submitted || touched[field] ? errors[field] : undefined) ?? null
  const set = (field: SignupField) => (value: string) => {
    setValues((current) => ({ ...current, [field]: value }))
    setServerErrors((current) => ({ ...current, [field]: undefined }))
  }
  const blur = (field: SignupField) => () => setTouched((current) => ({ ...current, [field]: Boolean(values[field]) || current[field] }))

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    setSubmitted(true)
    setError(null)
    setServerErrors({})
    const invalid = firstError(errors)
    if (invalid) {
      refs[invalid].current?.focus()
      return
    }
    setBusy(true)
    try {
      const outcome = await register({ name: values.name, email: values.email, password: values.password })
      const email = values.email.trim()
      if (outcome === 'confirm') navigate(AUTH_ROUTES.verify, { state: { email } })
      else if (outcome === 'neutral') navigate(AUTH_ROUTES.login, { state: { email, notice: NEUTRAL_SIGNUP_MESSAGE, noticeTone: 'info' } })
      // 'tokens': a sessão já foi aberta e o Gate mostra a próxima tela.
    } catch (err) {
      const { field, message } = authErrorMessage(err, 'register')
      if (field) {
        setServerErrors({ [field]: message })
        refs[field].current?.focus()
      } else setError(message)
    } finally {
      setBusy(false)
    }
  }

  const nameError = shown('name')
  const emailErr = shown('email')
  const passwordError = shown('password')
  const confirmError = shown('confirm')

  return (
    <AuthShell compactHero={false}>
      <div className="auth-head">
        <h1>Criar conta</h1>
        <p className="lead">Conta de vendedor para acompanhar e gerenciar suas estações de recarga.</p>
      </div>
      <form className="auth-fields" onSubmit={submit} noValidate>
        {error ? (
          <Banner tone="error" icon="alert">
            {error}
          </Banner>
        ) : null}
        <Field label="Nome completo" error={nameError}>
          <input ref={refs.name} className="input input-big" autoComplete="name" value={values.name} onChange={(e) => set('name')(e.target.value)} onBlur={blur('name')} placeholder="Como aparece nos seus documentos" autoFocus maxLength={100} aria-invalid={Boolean(nameError)} />
        </Field>
        <Field label="E-mail" error={emailErr}>
          <input ref={refs.email} className="input input-big" type="email" autoComplete="email" inputMode="email" value={values.email} onChange={(e) => set('email')(e.target.value)} onBlur={blur('email')} placeholder="voce@empresa.com.br" maxLength={254} aria-invalid={Boolean(emailErr)} />
        </Field>
        <Field label="Senha" hint={`mínimo de ${PASSWORD_MIN} caracteres`} error={passwordError}>
          <PasswordInput ref={refs.password} autoComplete="new-password" value={values.password} onChange={set('password')} onBlur={blur('password')} placeholder="Crie uma senha" maxLength={PASSWORD_MAX} aria-invalid={Boolean(passwordError)} />
        </Field>
        <Field label="Confirmar senha" error={confirmError}>
          <PasswordInput ref={refs.confirm} autoComplete="new-password" value={values.confirm} onChange={set('confirm')} onBlur={blur('confirm')} placeholder="Repita a senha" maxLength={PASSWORD_MAX} aria-invalid={Boolean(confirmError)} />
        </Field>
        <p className="auth-note">
          <Icon name="qr" size={18} />
          <span>Depois de criar a conta, vincule seu primeiro equipamento pelo app ChargeGrid escaneando o QR do totem.</span>
        </p>
        <button type="submit" className="btn btn-primary btn-lg btn-block" disabled={busy}>
          {busy ? 'Criando sua conta…' : 'Criar conta'}
        </button>
      </form>
      <p className="auth-switch">
        <Link to={AUTH_ROUTES.login} state={{ email: values.email.trim() }}>
          Já tenho conta · <b>Entrar</b>
        </Link>
      </p>
    </AuthShell>
  )
}
