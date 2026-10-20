/**
 * Taxa de permanência (frente D) e selo de pagamento (frente A).
 *
 * A taxa fica em `rules.rotation` da tarifa do posto (`GET/PUT /stations/{id}/pricing`),
 * com as chaves que a API grava e devolve: `enabled`, `start_after_min` (tolerância),
 * `interval_min`, `amount` e `max_amount` (`chargegrid_core.overstay`). O PUT da API é
 * parcial (`pricing.merge_rules`): enviamos só `{ rotation }` e a tarifa por horário e
 * por demanda continuam como estão no servidor (sem sobrescrever com uma cópia velha).
 */
import type { LiveOccupancy, PricingRules, RotationRule, SessionPayment } from '../api/operations'
import { formatCurrency, toNumber } from './format'
import type { Tone } from './labels'

export interface RotationForm {
  enabled: boolean
  grace: string
  interval: string
  amount: string
  max: string
}

/** Mesmo padrão da API (`DEFAULT_ROTATION`): desligada, 10 min, R$ 1,00/min, até R$ 30,00. */
const DEFAULT_FORM: RotationForm = { enabled: false, grace: '10', interval: '1', amount: '1,00', max: '30,00' }

function money(value: unknown, fallback: string): string {
  const number = toNumber(value as string | number | null | undefined)
  return number === null ? fallback : number.toFixed(2).replace('.', ',')
}

function int(value: unknown, fallback: string): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : typeof value === 'string' && /^\d+$/.test(value) ? value : fallback
}

export function rotationForm(rules: PricingRules | null | undefined): RotationForm {
  const rule: Partial<RotationRule> = rules?.rotation ?? {}
  return {
    enabled: Boolean(rule.enabled),
    grace: int(rule.start_after_min, DEFAULT_FORM.grace),
    interval: int(rule.interval_min, DEFAULT_FORM.interval),
    amount: money(rule.amount, DEFAULT_FORM.amount),
    max: money(rule.max_amount, DEFAULT_FORM.max),
  }
}

/** Valores validados, já com as chaves de `rules.rotation` da API. */
export type RotationValues = RotationRule

const MONEY = /^\d{1,4}([.,]\d{1,2})?$/

/** Valida com os limites da API (tolerância 0–1440, intervalo 1–1440, valor 0–100, teto 0–1000). */
export function validateRotation(form: RotationForm): { values?: RotationValues; errors: Partial<Record<keyof RotationForm, string>> } {
  const errors: Partial<Record<keyof RotationForm, string>> = {}
  const grace = /^\d{1,4}$/.test(form.grace.trim()) ? Number(form.grace.trim()) : NaN
  const interval = /^\d{1,4}$/.test(form.interval.trim()) ? Number(form.interval.trim()) : NaN
  const amount = MONEY.test(form.amount.trim()) ? Number(form.amount.trim().replace(',', '.')) : NaN
  const max = MONEY.test(form.max.trim()) ? Number(form.max.trim().replace(',', '.')) : NaN
  if (!(grace >= 0 && grace <= 1440)) errors.grace = 'Tolerância de 0 a 1.440 min'
  if (!(interval >= 1 && interval <= 1440)) errors.interval = 'Intervalo de 1 a 1.440 min'
  if (!(amount >= 0 && amount <= 100)) errors.amount = 'Valor de R$ 0,00 a R$ 100,00'
  if (!(max >= 0 && max <= 1000)) errors.max = 'Teto de R$ 0,00 a R$ 1.000,00'
  if (Object.keys(errors).length) return { errors }
  return {
    errors,
    values: { enabled: form.enabled, start_after_min: grace, interval_min: interval, amount: amount.toFixed(2), max_amount: max.toFixed(2) },
  }
}

/** Corpo do `PUT /stations/{id}/pricing` que muda só a taxa de permanência. */
export function rotationPatch(values: RotationValues): PricingRules {
  const { enabled, start_after_min, interval_min, amount, max_amount } = values
  return { rotation: { enabled, start_after_min, interval_min, amount, max_amount } }
}

/** "Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)". */
export function rotationSummary(values: RotationValues): string {
  if (!values.enabled) return 'Sem taxa de permanência: o carro pode ficar na vaga depois da recarga sem cobrança.'
  const grace = values.start_after_min ? `${values.start_after_min} min de tolerância` : 'sem tolerância'
  const each = values.interval_min === 1 ? `${formatCurrency(values.amount)}/min` : `${formatCurrency(values.amount)} a cada ${values.interval_min} min`
  return `Após a recarga: ${grace}, depois ${each} (máx. ${formatCurrency(values.max_amount)})`
}

/* ------------------------------------------------ vaga ocupada após a recarga */

export const OVERSTAY_STATUS: Record<string, { label: string; tone: Tone }> = {
  none: { label: 'Sem permanência', tone: 'gray' },
  no_fee: { label: 'Na vaga · sem taxa', tone: 'gray' },
  grace: { label: 'Em tolerância', tone: 'amber' },
  billing: { label: 'Cobrando permanência', tone: 'red' },
  capped: { label: 'Taxa no máximo', tone: 'red' },
  closed: { label: 'Permanência encerrada', tone: 'green' },
}

/** "04:37" (minutos:segundos); horas viram "1:02:05". */
export function formatCountdown(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return '—'
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`
}

/** Linha do ao vivo para quem ocupa a vaga depois da recarga. */
export function occupancyText(occupancy: LiveOccupancy, elapsedSeconds = 0): string {
  const fee = formatCurrency(occupancy.fee_due ?? '0')
  const max = occupancy.max_fee ? ` de ${formatCurrency(occupancy.max_fee)}` : ''
  switch (occupancy.status) {
    case 'grace':
      return `Tolerância: restam ${formatCountdown((occupancy.grace_remaining_seconds ?? 0) - elapsedSeconds)}`
    case 'billing':
      return `Taxa acumulada ${fee}${max}`
    case 'capped':
      return `Taxa no máximo: ${fee}`
    case 'no_fee':
      return 'Recarga concluída, sem taxa de permanência'
    default:
      return OVERSTAY_STATUS[occupancy.status]?.label ?? occupancy.status
  }
}

/**
 * Coluna "Permanência" das sessões, com os campos de `/owner/sessions`:
 * `overstay_fee` ("0.00" sem permanência) e `overstay_minutes` (inteiro).
 */
export function overstayCell(item: { overstay_fee?: string | null; overstay_minutes?: number | null }): { text: string } {
  const fee = toNumber(item.overstay_fee ?? null)
  const minutes = item.overstay_minutes ?? 0
  if (fee && fee > 0) return { text: `${formatCurrency(fee)}${minutes ? ` · ${Math.round(minutes)} min` : ''}` }
  return { text: '—' }
}

/* -------------------------------------------------------- selo de pagamento */

export function paymentBadge(payment: SessionPayment | null | undefined): { label: string; tone: Tone; test: boolean; detail: string | null } | null {
  if (!payment) return null
  const status = payment.status
  const tone: Tone =
    status === 'completed'
      ? 'green'
      : status === 'in_use' || status === 'authorized' || status === 'paid'
        ? 'blue'
        : status === 'declined' || payment.settlement?.status === 'failed'
          ? 'red'
          : status === 'expired' || status === 'canceled'
            ? 'gray'
            : 'amber'
  const s = payment.settlement
  let detail: string | null = null
  if (s && s.status === 'done') {
    const returned = toNumber(s.returned) ?? 0
    detail = `Capturado ${formatCurrency(s.charged)}${returned > 0 ? ` · ${s.return_kind === 'refunded' ? 'devolvido' : 'liberado'} ${formatCurrency(s.returned)}` : ''}`
  }
  // O simulado do totem (Modo apresentação) diz "(simulado)", nunca "teste".
  return { label: payment.status_label || status, tone, test: payment.environment === 'test' && payment.provider !== 'simulated' && payment.method !== 'simulated', detail }
}
