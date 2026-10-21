/**
 * Totem de autoatendimento (firmware 0.8.0) no painel do vendedor: status do totem do posto (uma linha
 * em Dados da estação) e canal/método das sessões pagas. Mesmas regras do app (`screens/station_ops.py`,
 * `services/owner_sessions.py`) e da API (`kiosk_totem.method_for`, `funding.payment_channel`).
 */
import type { SessionPayment } from '../api/operations'
import type { Station } from '../api/types'
import type { Tone } from './labels'

export type KioskMethod = 'simulated' | 'stripe'
export type KioskReason = 'payments_unavailable' | 'point_disabled'

export interface KioskStatus {
  enabled: boolean
  method: KioskMethod | null
  label: 'SIMULADO' | 'TESTE' | null
  reason: KioskReason | null
  text: string
  tone: Tone
}

/** Status numa linha, como o app (`station_ops.KIOSK_TEXTS`/`KIOSK_REASONS`). */
export const KIOSK_TEXTS: Record<KioskMethod, string> = {
  stripe: 'Pagamento: Stripe (teste)',
  simulated: 'Pagamento simulado (Modo apresentação)',
}

export const KIOSK_REASON_TEXT: Record<KioskReason, string> = {
  payments_unavailable: 'Indisponível: pagamentos Stripe não configurados no servidor',
  point_disabled: 'Indisponível: estação inativa',
}

/**
 * `kiosk_status` que a API manda no posto do dono, ou `null` para deduzir. Vale o bloco do servidor (inclui a
 * Stripe configurada), exceto quando o Modo apresentação da conta mudou depois que o posto foi lido: aí ele não
 * bate com `presentationMode` e o painel volta ao cálculo local.
 */
export function serverKioskStatus(
  station: Pick<Station, 'kiosk_status'>,
  presentationMode: boolean,
): { method: KioskMethod | null; reason: KioskReason | null } | null {
  const server = station.kiosk_status
  if (!server || typeof server !== 'object') return null
  const { method, reason } = server
  if (reason === 'point_disabled' && method === null) return { method, reason }
  if (presentationMode && method === 'simulated' && reason === null) return { method, reason }
  if (!presentationMode && ((method === 'stripe' && reason === null) || (method === null && reason === 'payments_unavailable')))
    return { method, reason }
  return null
}

/**
 * Status como o `connector.kiosk` do sync: decidido pelo modo da conta do dono. Usa `station.kiosk_status`
 * (API com o campo); sem ele deduz, e `stripeEnabled` é `GET /payments/config` → `enabled`
 * (`undefined` = ainda não consultado; supõe ligada).
 */
export function kioskStatus(station: Pick<Station, 'active' | 'kiosk_status'>, presentationMode: boolean, stripeEnabled?: boolean): KioskStatus {
  let method: KioskMethod | null
  let reason: KioskReason | null = null
  const decided = serverKioskStatus(station, presentationMode)
  if (decided) {
    method = decided.method
    reason = decided.reason
  } else if (!station.active) {
    method = null
    reason = 'point_disabled'
  } else if (presentationMode) method = 'simulated'
  else if (stripeEnabled !== false) method = 'stripe'
  else {
    method = null
    reason = 'payments_unavailable'
  }
  if (method === 'simulated') return { enabled: true, method, label: 'SIMULADO', reason, tone: 'amber', text: KIOSK_TEXTS.simulated }
  if (method === 'stripe') return { enabled: true, method, label: 'TESTE', reason, tone: 'blue', text: KIOSK_TEXTS.stripe }
  return { enabled: false, method, label: null, reason, tone: 'red', text: KIOSK_REASON_TEXT[reason as KioskReason] }
}

export type PaymentChannel = 'app' | 'kiosk_qr' | 'kiosk_totem' | 'kiosk'

export const CHANNEL_LABELS: Record<PaymentChannel, string> = {
  app: 'App',
  kiosk_qr: 'QR do painel',
  kiosk_totem: 'Totem',
  kiosk: 'Painel',
}

export function isSimulated(payment: SessionPayment | null | undefined): boolean {
  return payment?.provider === 'simulated' || payment?.method === 'simulated'
}

/**
 * Canal da recarga: `payment.channel` de `/owner/sessions`; sem o campo (API antiga), pela origem
 * (simulado só existe no totem; outra origem `kiosk` = "Painel"). Sem pagamento: app.
 */
export function paymentChannel(payment: SessionPayment | null | undefined): PaymentChannel {
  if (!payment) return 'app'
  const channel = payment.channel
  if (channel === 'app' || channel === 'kiosk_qr' || channel === 'kiosk_totem') return channel
  if (isSimulated(payment)) return 'kiosk_totem'
  return payment.origin === 'kiosk' ? 'kiosk' : 'app'
}

/** Método do pagamento: "Simulado" (totem em Modo apresentação), "Stripe (teste)" ou "—" sem pagamento. */
export function paymentMethodLabel(payment: SessionPayment | null | undefined): string {
  if (!payment) return '—'
  return isSimulated(payment) ? 'Simulado' : 'Stripe (teste)'
}

export function channelTone(channel: PaymentChannel): Tone {
  return channel === 'kiosk_totem' ? 'amber' : channel === 'app' ? 'gray' : 'blue'
}
