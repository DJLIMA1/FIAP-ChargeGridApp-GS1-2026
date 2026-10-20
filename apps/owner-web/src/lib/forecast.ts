import type { ForecastHour, ForecastMetrics, OwnerForecast } from '../api/forecast'
import { TIMEZONE, toNumber } from './format'

export const FULL_PERCENT = 80

export interface ForecastPoint {
  key: string
  label: string
  tooltip: string
  occupancy: number
  baseline: number
  band: [number, number] | null
  energy: number
  full: boolean
}

const hourFmt = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', timeZone: TIMEZONE })
const dayFmt = new Intl.DateTimeFormat('pt-BR', { weekday: 'short', day: '2-digit', hour: '2-digit', timeZone: TIMEZONE })

/** Horas locais vêm sem fuso ("2026-10-21T17:00:00"): são horário de São Paulo. */
export function localInstant(value: string): Date {
  return new Date(/[zZ]|[+-]\d\d:\d\d$/.test(value) ? value : `${value}-03:00`)
}

export function forecastPoints(hours: ForecastHour[]): ForecastPoint[] {
  return hours.map((hour) => {
    const when = localInstant(hour.start)
    const low = toNumber(hour.low_percent)
    const high = toNumber(hour.high_percent)
    return {
      key: hour.start,
      label: `${hourFmt.format(when)}h`,
      tooltip: dayFmt.format(when).replace(',', ''),
      occupancy: toNumber(hour.occupancy_percent) ?? 0,
      baseline: toNumber(hour.baseline_percent) ?? 0,
      band: low !== null && high !== null ? [low, high] : null,
      energy: toNumber(hour.energy_kwh) ?? 0,
      full: hour.full,
    }
  })
}

export function methodLabel(method: OwnerForecast['method']): string {
  return method === 'gbm' ? 'Modelo (gradient boosting)' : 'Média do mesmo dia e hora'
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(digits).replace('.', ',')}%`
}

export function points(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1).replace('.', ',')} p.p.`
}

/** "erro 12% menor que a média" — comparação honesta entre os dois métodos nos mesmos pontos. */
export function comparison(model: ForecastMetrics | null | undefined, base: ForecastMetrics | null | undefined): string | null {
  const m = model?.mae_pp
  const b = base?.mae_pp
  if (m === null || m === undefined || b === null || b === undefined || b <= 0) return null
  const delta = Math.round(((b - m) / b) * 100)
  if (delta === 0) return 'mesmo erro da média'
  return delta > 0 ? `erro ${delta}% menor que a média` : `erro ${Math.abs(delta)}% maior que a média`
}

export function totalEnergy(hours: ForecastHour[], first = 0, count = 24): number {
  return hours.slice(first, first + count).reduce((sum, hour) => sum + (toNumber(hour.energy_kwh) ?? 0), 0)
}

/** Cor da célula do mapa de ocupação média (0–100%). */
export function occupancyColor(value: number | null): string {
  if (value === null || value <= 0) return '#242424'
  const level = Math.min(1, 0.12 + (value / 100) * 0.88)
  return value >= FULL_PERCENT ? `rgba(232, 146, 43, ${level})` : `rgba(61, 190, 122, ${level})`
}
