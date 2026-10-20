import { useState } from 'react'
import { ApiError } from '../../api/client'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { useToast } from '../Toast'
import { Badge, Card, ErrorBanner, Switch } from '../ui'

type Flag = 'prepay_required' | 'kiosk_payments'

const COPY: Record<Flag, { label: string; on: string; off: string; detail: string }> = {
  prepay_required: {
    label: 'Exigir pagamento antecipado (Stripe · teste)',
    on: 'Pagamento antecipado exigido',
    off: 'Pagamento antecipado desligado',
    detail: 'O motorista paga um teto antes da recarga começar; no fim, cobra-se só a energia confirmada e o resto é liberado ou devolvido.',
  },
  kiosk_payments: {
    label: 'Pagamento pelo QR do painel',
    on: 'QR de pagamento ligado',
    off: 'QR de pagamento desligado',
    detail: 'O painel físico mostra um QR para pagar sem o app (R$ 10, 20 ou 40) e a recarga começa após a confirmação.',
  },
}

/** Interruptores de pagamento do posto (frente A). Some quando a API não envia os campos. */
export function PaymentsCard({ station, onSaved }: { station: Station; onSaved(next: Station): void }) {
  const { ep } = useAuth()
  const toast = useToast()
  const [saving, setSaving] = useState<Flag | null>(null)
  const [error, setError] = useState<string | null>(null)
  const flags = (Object.keys(COPY) as Flag[]).filter((flag) => typeof station[flag] === 'boolean')
  if (!flags.length) return null

  const toggle = async (flag: Flag, value: boolean) => {
    if (saving) return
    setSaving(flag)
    setError(null)
    try {
      // Sem atualização otimista: o interruptor muda com a resposta do servidor.
      const next = await ep.patchStation(station.id, { [flag]: value })
      onSaved(next)
      toast(value ? COPY[flag].on : COPY[flag].off)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(null)
    }
  }

  return (
    <Card
      title={
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          Pagamentos <Badge tone="amber">teste</Badge>
        </span>
      }
      sub="Stripe em modo teste: nenhum valor real é cobrado"
      id="payments"
    >
      <div className="stack" style={{ gap: 0 }}>
        {flags.map((flag) => (
          <div key={flag} className="list-row" style={{ alignItems: 'flex-start' }}>
            <div className="grow">
              <Switch checked={Boolean(station[flag])} disabled={saving !== null} onChange={(value) => void toggle(flag, value)} label={<b style={{ fontWeight: 600 }}>{COPY[flag].label}</b>} />
              <div className="sub" style={{ marginTop: 6, marginLeft: 52, whiteSpace: 'normal' }}>
                {saving === flag ? 'Salvando…' : COPY[flag].detail}
              </div>
            </div>
          </div>
        ))}
        {error ? <ErrorBanner error={error} title="Configuração de pagamento não salva" /> : null}
      </div>
    </Card>
  )
}
