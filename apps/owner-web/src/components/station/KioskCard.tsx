import { useState } from 'react'
import { ApiError } from '../../api/client'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { KIOSK_FOLLOWS, kioskStatus, serverKioskStatus } from '../../lib/kiosk'
import { useApi } from '../../lib/useApi'
import { useToast } from '../Toast'
import { Badge, Card, ErrorBanner, Switch } from '../ui'

const DETAIL =
  'O painel físico vende a recarga sem o app: por valor, tempo ou energia, com pagamento na tela. Padrão desligado; desligado, o painel mostra as telas atuais.'

/**
 * Totem de autoatendimento do posto (`kiosk_mode`, totem 0.8.0) e o status: método efetivo pelo
 * Modo apresentação da conta (`/me`) e motivo de indisponível (`payments_unavailable`). Some quando a
 * API não envia o campo.
 */
export function KioskCard({ station, onSaved }: { station: Station; onSaved(next: Station): void }) {
  const { ep, profile } = useAuth()
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const supported = typeof station.kiosk_mode === 'boolean'
  // Modo da conta atualizado (pode ter mudado no app depois do login) e a Stripe do servidor. Com
  // `kiosk_status` no posto a API já decidiu a Stripe; `/payments/config` só para a API antiga.
  const decidedByApi = Boolean(station.kiosk_status)
  const account = useApi(async (signal) => {
    const [me, config] = await Promise.all([
      ep.me(signal),
      decidedByApi ? Promise.resolve(undefined) : ep.paymentsConfig(signal).catch(() => ({ enabled: false })),
    ])
    const presentation = me.presentation_mode === true
    // Conta mudou de modo depois de ler o posto: o bloco da API não vale e a Stripe precisa ser conferida.
    const stale = decidedByApi && !serverKioskStatus(station, presentation)
    const checked = config ?? (stale ? await ep.paymentsConfig(signal).catch(() => ({ enabled: false })) : undefined)
    return { presentation, stripe: checked ? checked.enabled === true : undefined }
  }, `kiosk-${station.id}`, supported)
  if (!supported) return null

  const presentation = account.data?.presentation ?? profile?.presentation_mode === true
  const status = kioskStatus(station, presentation, account.data?.stripe)
  const on = Boolean(station.kiosk_mode)

  const toggle = async (value: boolean) => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      // Sem atualização otimista: o interruptor muda com a resposta do servidor.
      const next = await ep.patchStation(station.id, { kiosk_mode: value })
      onSaved(next)
      toast(value ? 'Totem de autoatendimento ligado' : 'Totem de autoatendimento desligado')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Totem de autoatendimento" sub="Recarga sem celular no painel físico do posto" id="kiosk">
      <div className="stack" style={{ gap: 12 }}>
        <div className="list-row" style={{ alignItems: 'flex-start' }}>
          <div className="grow">
            <Switch checked={on} disabled={saving} onChange={(value) => void toggle(value)} label={<b style={{ fontWeight: 600 }}>Totem de autoatendimento</b>} />
            <div className="sub" style={{ marginTop: 6, marginLeft: 52, whiteSpace: 'normal' }}>
              {saving ? 'Salvando…' : DETAIL}
            </div>
          </div>
        </div>
        <div data-testid="kiosk-status" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
            <Badge tone={on ? 'green' : 'gray'}>{on ? 'Ligado' : 'Desligado'}</Badge>
            {status.label ? <Badge tone={status.tone}>{status.label}</Badge> : <Badge tone="red">Indisponível</Badge>}
            {account.loading && !account.data ? <span className="dim">conferindo o modo da conta…</span> : null}
          </span>
          <span style={status.reason ? { color: 'var(--red-soft)' } : undefined}>
            <b style={{ fontWeight: 600 }}>{on ? 'Totem ligado' : 'Ao ligar'}</b> · {status.text}
          </span>
          <span className="dim" style={{ fontSize: 12.5 }}>
            {KIOSK_FOLLOWS}
          </span>
        </div>
        {error ? <ErrorBanner error={error} title="Totem não alterado" /> : null}
      </div>
    </Card>
  )
}
