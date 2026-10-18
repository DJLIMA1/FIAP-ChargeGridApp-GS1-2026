/** Formatação pt-BR (moeda, energia, datas no fuso America/Sao_Paulo). */

export const TIMEZONE = 'America/Sao_Paulo'
const LOCALE = 'pt-BR'
/** Espaços especiais que o Intl usa em moedas (NBSP e NNBSP). */
const SPECIAL_SPACES = new RegExp(`[${String.fromCharCode(0xa0, 0x202f)}]`, 'g')

export function toNumber(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === '') return null
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) ? number : null
}

const currency2 = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const currency0 = new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'BRL', minimumFractionDigits: 0, maximumFractionDigits: 0 })

/** "R$ 1.234,56" (troca o espaço especial do Intl por espaço comum). */
export function formatCurrency(value: string | number | null | undefined, options: { compact?: boolean; empty?: string } = {}): string {
  const number = toNumber(value)
  if (number === null) return options.empty ?? '—'
  const formatter = options.compact && Math.abs(number) >= 1000 ? currency0 : currency2
  return formatter.format(number).replace(SPECIAL_SPACES, ' ')
}

/** Tarifa com até 4 casas significativas: "R$ 1,89/kWh". */
export function formatTariff(value: string | number | null | undefined): string {
  const number = toNumber(value)
  if (number === null) return '—'
  const digits = Math.round(number * 100) === number * 100 ? 2 : 4
  return `${new Intl.NumberFormat(LOCALE, { style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: digits })
    .format(number)
    .replace(SPECIAL_SPACES, ' ')}/kWh`
}

export function formatNumber(value: string | number | null | undefined, digits = 0, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  return new Intl.NumberFormat(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(number)
}

/** "2.184 kWh" (inteiro a partir de 100 kWh, senão 1 casa; até 3 casas para valores pequenos). */
export function formatEnergy(value: string | number | null | undefined, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  const abs = Math.abs(number)
  const digits = abs >= 100 ? 0 : abs >= 1 ? 1 : abs === 0 ? 0 : 3
  return `${formatNumber(number, digits)} kWh`
}

export function formatPercent(value: string | number | null | undefined, digits = 1, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  return `${formatNumber(number, digits)}%`
}

export function formatPower(value: string | number | null | undefined): string {
  const number = toNumber(value)
  if (number === null) return '—'
  return `${formatNumber(number, Number.isInteger(number) ? 0 : 1)} kW`
}

export function formatDuration(minutes: string | number | null | undefined): string {
  const number = toNumber(minutes)
  if (number === null) return '—'
  const total = Math.round(number)
  if (total < 60) return `${total} min`
  const hours = Math.floor(total / 60)
  const rest = total % 60
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

function parse(value: string | Date | null | undefined): Date | null {
  if (!value) return null
  const date = value instanceof Date ? value : new Date(value)
  return Number.isNaN(date.getTime()) ? null : date
}

const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
const shortDateTimeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
const dateFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, day: '2-digit', month: '2-digit', year: 'numeric' })
const dayMonthFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, day: '2-digit', month: '2-digit' })
const timeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, hour: '2-digit', minute: '2-digit' })
const weekdayFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TIMEZONE, weekday: 'short' })

/** "18/10/2026 14:05" */
export function formatDateTime(value: string | Date | null | undefined, empty = '—'): string {
  const date = parse(value)
  return date ? dateTimeFmt.format(date).replace(',', '') : empty
}

/** "18/10 14:05" */
export function formatShortDateTime(value: string | Date | null | undefined, empty = '—'): string {
  const date = parse(value)
  return date ? shortDateTimeFmt.format(date).replace(',', '') : empty
}

export function formatDate(value: string | Date | null | undefined, empty = '—'): string {
  const date = parse(value)
  return date ? dateFmt.format(date) : empty
}

export function formatDayMonth(value: string | Date | null | undefined, empty = '—'): string {
  const date = parse(value)
  return date ? dayMonthFmt.format(date) : empty
}

export function formatTime(value: string | Date | null | undefined, empty = '—'): string {
  const date = parse(value)
  return date ? timeFmt.format(date) : empty
}

/** "Seg", "Ter"... */
export function formatWeekday(value: string | Date | null | undefined): string {
  const date = parse(value)
  if (!date) return ''
  const text = weekdayFmt.format(date).replace('.', '')
  return text.charAt(0).toUpperCase() + text.slice(1, 3)
}

/** "há 3 min", "há 2 h", "há 4 dias". */
export function formatRelative(value: string | Date | null | undefined, now: Date = new Date(), empty = 'nunca'): string {
  const date = parse(value)
  if (!date) return empty
  const seconds = Math.round((now.getTime() - date.getTime()) / 1000)
  if (seconds < 45) return 'agora'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `há ${minutes} min`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `há ${hours} h`
  const days = Math.round(hours / 24)
  return `há ${days} ${days === 1 ? 'dia' : 'dias'}`
}

export function greeting(now: Date = new Date()): string {
  const hour = Number(new Intl.DateTimeFormat('en-US', { timeZone: TIMEZONE, hour: '2-digit', hourCycle: 'h23' }).format(now))
  if (hour < 12) return 'Bom dia'
  if (hour < 18) return 'Boa tarde'
  return 'Boa noite'
}

export function firstName(name: string | null | undefined): string {
  return (name || '').trim().split(/\s+/)[0] || ''
}
