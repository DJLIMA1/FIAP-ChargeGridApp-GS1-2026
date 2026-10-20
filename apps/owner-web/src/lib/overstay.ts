/**
 * Taxa de permanência (frente D) e selo de pagamento (frente A).
 *
 * A taxa fica em `rules.rotation` da tarifa do posto (`GET/PUT /stations/{id}/pricing`).
 * O PUT sempre leva as regras inteiras: só `rotation` muda, e `demand`, `schedule`,
 * `peak` e qualquer chave futura voltam como vieram. A API em andamento ainda
 * grava as chaves antigas (`start_after_min`/`interval_min`); o contrato novo usa
 * `grace_minutes`/`interval_minutes`. Lemos as duas e gravamos no formato que veio.
 */
import type { LiveOccupancy, PricingRules, RotationRule, SessionOverstay, SessionPayment } from '../api/operations'
import { formatCurrency, toNumber } from './format'
import type { Tone } from './labels'

export interface RotationForm {
  enabled: boolean
  grace: string
  interval: string
  amount: string
  max: string
}

const DEFAULT_FORM: RotationForm = { enabled: false, grace: '10', interval: '1', amount: '1,00', max: '30,00' }

function money(value: unknown, fallback: string): string {
  const number = toNumber(value as string | number | null | undefined)
  return number === null ? fallback : number.toFixed(2).replace('.', ',')
}

function int(value: unknown, fallback: string): string {
  return typeof value === 'number' && Number.isFinite(value) ? String(Math.round(value)) : typeof value === 'string' && /^\d+$/.test(value) ? value : fallback
}

export function rotationForm(rules: PricingRules | null | undefined): RotationForm {
  const rule = (rules?.rotation ?? {}) as RotationRule
  return {
    enabled: Boolean(rule.enabled),
    grace: int(rule.grace_minutes ?? rule.start_after_min, DEFAULT_FORM.grace),
    interval: int(rule.interval_minutes ?? rule.interval_min, DEFAULT_FORM.interval),
    amount: money(rule.amount, DEFAULT_FORM.amount),
    max: money(rule.max_amount, DEFAULT_FORM.max),
  }
}

export interface RotationValues {
  enabled: boolean
  grace_minutes: number
  interval_minutes: number
  amount: string
  max_amount: string
}

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
    values: { enabled: form.enabled, grace_minutes: grace, interval_minutes: interval, amount: amount.toFixed(2), max_amount: max.toFixed(2) },
  }
}

/**
 * Regras inteiras com a nova `rotation`. Preserva as outras chaves de `rotation`
 * e grava as minutagens no formato em uso (antigo, novo ou ambos se nenhum veio).
 */
export function withRotation(rules: PricingRules, values: RotationValues): PricingRules {
  const current = (rules.rotation ?? {}) as RotationRule
  const legacy = 'start_after_min' in current || 'interval_min' in current
  const modern = 'grace_minutes' in current || 'interval_minutes' in current
  const rotation: RotationRule = { ...current, enabled: values.enabled, amount: values.amount, max_amount: values.max_amount }
  if (legacy || !modern) {
    rotation.start_after_min = values.grace_minutes
    rotation.interval_min = values.interval_minutes
  }
  if (modern || !legacy) {
    rotation.grace_minutes = values.grace_minutes
    rotation.interval_minutes = values.interval_minutes
  }
  return { ...structuredClone(rules), rotation }
}

/** "Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)". */
export function rotationSummary(values: Pick<RotationValues, 'enabled' | 'grace_minutes' | 'interval_minutes' | 'amount' | 'max_amount'>): string {
  if (!values.enabled) return 'Sem taxa de permanência: o carro pode ficar na vaga depois da recarga sem cobrança.'
  const grace = values.grace_minutes ? `${values.grace_minutes} min de tolerância` : 'sem tolerância'
  const each = values.interval_minutes === 1 ? `${formatCurrency(values.amount)}/min` : `${formatCurrency(values.amount)} a cada ${values.interval_minutes} min`
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

/** Coluna "Permanência" das sessões: valor + minutos, status ou "—". */
export function overstayCell(item: { overstay?: SessionOverstay | null; overstay_fee?: string | null; overstay_minutes?: string | number | null }): { text: string; tone?: Tone; badge?: string } {
  const status = item.overstay?.status
  if (status === 'grace' || status === 'billing' || status === 'capped') {
    const meta = OVERSTAY_STATUS[status]
    return { text: item.overstay?.fee_due ? formatCurrency(item.overstay.fee_due) : '', tone: meta.tone, badge: meta.label }
  }
  const fee = toNumber(item.overstay_fee ?? item.overstay?.fee_due ?? null)
  const minutes = toNumber(item.overstay_minutes ?? null) ?? (item.overstay?.billable_seconds ? item.overstay.billable_seconds / 60 : null)
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
  return { label: payment.status_label || status, tone, test: payment.environment === 'test', detail }
}
