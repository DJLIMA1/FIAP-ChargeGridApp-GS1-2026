import { useState } from 'react'
import { useAuth } from '../auth/AuthContext'
import { authErrorMessage } from '../auth/signup'
import { AuthShell } from '../components/AuthShell'
import { Icon, type IconName } from '../components/Icon'
import { Banner } from '../components/ui'

const STEPS: { icon: IconName; title: string; text: string }[] = [
  { icon: 'phone', title: 'Instale o app ChargeGrid', text: 'No celular, entre com este mesmo e-mail e senha.' },
  { icon: 'qr', title: 'Escaneie o QR da central', text: 'A central do ponto sem dono mostra um QR de vinculação. Escaneie pelo app para se tornar o proprietário.' },
  { icon: 'station', title: 'Publique e volte aqui', text: 'Informe nome, endereço e tarifa no app. Depois toque em “Já vinculei” para abrir o painel.' },
]

/** Vendedor sem operação habilitada: explica como vincular o primeira central. */
export default function OperatorPending() {
  const { logout, recheck, profile, status } = useAuth()
  const [busy, setBusy] = useState(false)
  const [feedback, setFeedback] = useState<{ tone: 'info' | 'error'; text: string } | null>(null)
  const firstName = profile?.name?.trim().split(/\s+/)[0]

  const check = async () => {
    if (busy) return
    setBusy(true)
    setFeedback(null)
    try {
      await recheck()
      setFeedback({ tone: 'info', text: 'Ainda não encontramos centrais vinculadas a esta conta. Conclua a vinculação no app e tente de novo.' })
    } catch (err) {
      setFeedback({ tone: 'error', text: authErrorMessage(err, 'login').message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <AuthShell wide>
      <div className="auth-head">
        <span className="eyebrow">Conta de vendedor criada</span>
        <h1>Olá{firstName ? `, ${firstName}` : ''}!</h1>
        <p className="lead">Falta só vincular seu primeira central. Leva poucos minutos e é feito pelo app.</p>
      </div>
      <ol className="steps">
        {STEPS.map((step, index) => (
          <li key={step.title}>
            <span className="step-num" aria-hidden>
              {index + 1}
            </span>
            <div>
              <div className="step-title">
                <Icon name={step.icon} size={17} /> {step.title}
              </div>
              <p>{step.text}</p>
            </div>
          </li>
        ))}
      </ol>
      {feedback && status === 'operator_pending' ? (
        <Banner tone={feedback.tone} icon={feedback.tone === 'info' ? 'info' : 'alert'}>
          {feedback.text}
        </Banner>
      ) : null}
      <div className="auth-actions">
        <button type="button" className="btn btn-primary btn-lg" onClick={() => void check()} disabled={busy}>
          <Icon name="refresh" size={18} /> {busy ? 'Verificando…' : 'Já vinculei · Atualizar'}
        </button>
        <button type="button" className="btn btn-secondary btn-lg" onClick={() => void logout()}>
          <Icon name="logout" size={18} /> Sair
        </button>
      </div>
    </AuthShell>
  )
}
