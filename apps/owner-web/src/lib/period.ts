/**
 * Período do painel → parâmetros `from`/`to` da API (mesma regra de
 * `chargegrid_core.analytics.period_bounds`):
 *
 * - Hoje / 7 dias / 30 dias: começam à meia-noite de São Paulo (hoje, hoje-6,
 *   hoje-29) e terminam agora.
 * - Personalizado: datas locais inclusivas; o fim inclui o dia inteiro.
 */
import { TIMEZONE } from './format'

export type PeriodPreset = 'today' | '7d' | '30d' | 'custom'

export interface PeriodState {
  preset: PeriodPreset
  /** YYYY-MM-DD (somente no personalizado). */
  start?: string
  end?: string
}

export interface PeriodQuery {
  from?: string
  to?: string
  station_id?: string | null
}

export const MAX_WINDOW_DAYS = 366
export const PRESET_LABELS: Record<PeriodPreset, string> = {
  today: 'Hoje',
  '7d': '7 dias',
  '30d': '30 dias',
  custom: 'Personalizado',
}

const DAY_MS = 86_400_000

/** Deslocamento (min) do fuso em relação ao UTC naquele instante (SP = -180). */
export function zoneOffsetMinutes(instant: number, timeZone = TIMEZONE): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instant))
  const get = (type: string) => Number(parts.find((p) => p.type === type)?.value)
  const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
  return Math.round((asUtc - Math.floor(instant / 1000) * 1000) / 60_000)
}

/** Data local (YYYY-MM-DD) de um instante no fuso do relatório. */
export function localDate(instant: Date | number, timeZone = TIMEZONE): string {
  const parts = new Intl.DateTimeFormat('en-CA', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(
    typeof instant === 'number' ? new Date(instant) : instant,
  )
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  return `${get('year')}-${get('month')}-${get('day')}`
}

function parseDay(value: string | undefined): [number, number, number] | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(value ?? '')
  if (!match) return null
  const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])]
  const check = new Date(Date.UTC(y, m - 1, d))
  if (check.getUTCFullYear() !== y || check.getUTCMonth() !== m - 1 || check.getUTCDate() !== d) return null
  return [y, m, d]
}

/** Meia-noite local de `day` (YYYY-MM-DD) + `addDays`, como instante UTC. */
export function localMidnight(day: string, addDays = 0, timeZone = TIMEZONE): Date {
  const parsed = parseDay(day)
  if (!parsed) throw new Error('Data inválida')
  const [y, m, d] = parsed
  const naive = Date.UTC(y, m - 1, d + addDays)
  let guess = naive - zoneOffsetMinutes(naive, timeZone) * 60_000
  guess = naive - zoneOffsetMinutes(guess, timeZone) * 60_000
  return new Date(guess)
}

export function daysBetween(start: string, end: string): number {
  const a = parseDay(start)
  const b = parseDay(end)
  if (!a || !b) return NaN
  return Math.round((Date.UTC(b[0], b[1] - 1, b[2]) - Date.UTC(a[0], a[1] - 1, a[2])) / DAY_MS)
}

export function validatePeriod(period: PeriodState): string | null {
  if (period.preset !== 'custom') return null
  if (!parseDay(period.start) || !parseDay(period.end)) return 'Informe as datas inicial e final.'
  const span = daysBetween(period.start!, period.end!)
  if (span < 0) return 'A data final deve ser posterior à inicial.'
  if (span + 1 > MAX_WINDOW_DAYS) return `Escolha até ${MAX_WINDOW_DAYS} dias.`
  return null
}

export function periodBounds(period: PeriodState, now: Date = new Date()): { from: Date; to: Date } {
  if (period.preset === 'custom') {
    const error = validatePeriod(period)
    if (error) throw new Error(error)
    return { from: localMidnight(period.start!), to: localMidnight(period.end!, 1) }
  }
  const back = { today: 0, '7d': 6, '30d': 29 }[period.preset]
  return { from: localMidnight(localDate(now), -back), to: now }
}

export function periodQuery(period: PeriodState, stationId: string | null | undefined, now: Date = new Date()): PeriodQuery {
  const { from, to } = periodBounds(period, now)
  return { from: from.toISOString(), to: to.toISOString(), station_id: stationId || undefined }
}

/** Mesma sugestão da API: por hora até 2 dias, por dia acima disso. */
export function suggestedGranularity(query: PeriodQuery): 'hour' | 'day' {
  if (!query.from || !query.to) return 'day'
  return new Date(query.to).getTime() - new Date(query.from).getTime() <= 2 * DAY_MS ? 'hour' : 'day'
}

export function periodLabel(period: PeriodState): string {
  if (period.preset !== 'custom') {
    return period.preset === 'today' ? 'Hoje' : `Últimos ${period.preset === '7d' ? 7 : 30} dias`
  }
  const fmt = (day?: string) => (day ? day.split('-').reverse().slice(0, 2).join('/') : '')
  return `${fmt(period.start)} – ${fmt(period.end)}`
}
