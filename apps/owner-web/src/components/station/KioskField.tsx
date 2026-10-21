import { useState } from 'react'
import { ApiError } from '../../api/client'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { kioskStatus, serverKioskStatus } from '../../lib/kiosk'
import { useApi } from '../../lib/useApi'
import { useToast } from '../Toast'
import { FieldGroup } from '../ui'

/**
 * Totem de autoatendimento dentro de Dados da estação, como no app (`screens/station_ops.py`):
 * Ligado/Desligado em `kiosk_mode` (salva na hora, sem atualização otimista) e o status numa linha
 * ("Pagamento: Stripe (teste)", "Pagamento simulado (Modo apresentação)" ou o motivo de indisponível).
 * Some quando a API não envia o campo.
 */
export function KioskField({ station, onSaved }: { station: Station; onSaved(next: Station): void }) {
  const { ep, profile } = useAuth()
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const supported = typeof station.kiosk_mode === 'boolean'
  // Modo da conta atualizado (pode ter mudado no app depois do login). Com `kiosk_status` no posto a
  // API já decidiu a Stripe; `/payments/config` só para a API antiga ou se o modo mudou depois.
  const decidedByApi = Boolean(station.kiosk_status)
  const account = useApi(async (signal) => {
    const [me, config] = await Promise.all([
      ep.me(signal),
      decidedByApi ? Promise.resolve(undefined) : ep.paymentsConfig(signal).catch(() => ({ enabled: false })),
    ])
    const presentation = me.presentation_mode === true
    const stale = decidedByApi && !serverKioskStatus(station, presentation)
    const checked = config ?? (stale ? await ep.paymentsConfig(signal).catch(() => ({ enabled: false })) : undefined)
    return { presentation, stripe: checked ? checked.enabled === true : undefined }
  }, `kiosk-${station.id}`, supported)
  if (!supported) return null

  const presentation = account.data?.presentation ?? profile?.presentation_mode === true
  const status = kioskStatus(station, presentation, account.data?.stripe)
  const on = Boolean(station.kiosk_mode)

  const choose = async (value: boolean) => {
    if (saving || value === on) return
    setSaving(true)
    try {
      const next = await ep.patchStation(station.id, { kiosk_mode: value })
      onSaved(next)
      toast(next.kiosk_mode ? 'Totem de autoatendimento ligado' : 'Totem de autoatendimento desligado')
    } catch (err) {
      toast(`Totem não alterado: ${err instanceof ApiError ? err.message : 'tente novamente.'}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <FieldGroup label="Totem de autoatendimento">
      <div className="segmented" data-testid="kiosk-mode" style={{ height: 52 }}>
        <button type="button" aria-pressed={on} disabled={saving} onClick={() => void choose(true)} style={{ flex: 1, height: 50, minWidth: 110 }}>
          Ligado
        </button>
        <button type="button" aria-pressed={!on} disabled={saving} onClick={() => void choose(false)} style={{ flex: 1, height: 50, minWidth: 110 }}>
          Desligado
        </button>
      </div>
      <div data-testid="kiosk-status" className={status.reason ? 'red' : 'dim'} style={{ fontSize: 12.5 }}>
        {saving ? 'Salvando…' : status.text}
      </div>
    </FieldGroup>
  )
}
