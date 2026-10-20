/**
 * Energia do estabelecimento (frente B): rótulos, formatação de kW, a soma da
 * potência dos pontos contra o disponível e o debounce do controle deslizante
 * "Consumo da loja (SIMULADO)".
 */
import type { StationPower } from '../api/operations'
import { formatNumber, toNumber } from './format'
import type { Tone } from './labels'

/** Intervalo de atualização do cartão de energia enquanto a página está aberta. */
export const POWER_POLL_MS = 1500
/** Espera sem mexer no controle antes de gravar o consumo simulado. */
export const BUILDING_LOAD_DEBOUNCE_MS = 350

export const POWER_STATE: Record<string, { label: string; tone: Tone }> = {
  applied: { label: 'Aplicada', tone: 'green' },
  reducing: { label: 'Reduzindo', tone: 'amber' },
  raising: { label: 'Aumentando', tone: 'blue' },
  waiting: { label: 'Aguardando', tone: 'amber' },
  paused: { label: 'Pausada', tone: 'red' },
  fixed: { label: 'Fixa', tone: 'gray' },
}

export const POWER_TRIGGER: Record<string, string> = {
  initial: 'Início',
  building_load_changed: 'Consumo da loja',
  site_limit_changed: 'Limite contratado',
  station_cap_changed: 'Teto do posto',
  session_started: 'Recarga iniciada',
  session_ended: 'Recarga encerrada',
  request_changed: 'Pedido alterado',
  power_confirmed: 'Confirmação do equipamento',
}

/** "6 kW", "28,5 kW", "—" (até 1 casa, como a API arredonda). */
export function formatKw(value: string | number | null | undefined, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  const rounded = Math.round(number * 10) / 10
  return `${formatNumber(rounded, Number.isInteger(rounded) ? 0 : 1)} kW`
}

export interface PowerUsage {
  /** Soma das potências reservadas aos pontos (envelopes: aplicada ou ajuste pendente). */
  used: number
  available: number | null
  /** 0–100 do disponível (limitado a 100 na barra). */
  percent: number
  exceeded: number
  over: boolean
}

export function powerUsage(view: Pick<StationPower, 'envelope_kw' | 'allocated_kw' | 'available_kw' | 'exceeded_kw'>): PowerUsage {
  const used = toNumber(view.envelope_kw) ?? toNumber(view.allocated_kw) ?? 0
  const available = toNumber(view.available_kw)
  const exceeded = Math.max(0, toNumber(view.exceeded_kw) ?? 0)
  const percent = available && available > 0 ? Math.min(100, (used / available) * 100) : used > 0 ? 100 : 0
  return { used, available, percent, exceeded, over: exceeded > 0 || (available !== null && used > available + 1e-9) }
}

/** "30 kW contratados − 12 kW da loja = 18 kW para recarga" (ou o texto sem limite). */
export function availabilityText(view: Pick<StationPower, 'site_limit_kw' | 'building_load_kw' | 'available_kw' | 'station_cap_kw'>): string {
  const limit = toNumber(view.site_limit_kw)
  const load = toNumber(view.building_load_kw) ?? 0
  if (limit === null) return `Sem limite contratado: vale o teto do posto (${formatKw(view.station_cap_kw, 'potência nominal')}).`
  return `${formatKw(limit)} contratados − ${formatKw(load)} da loja = ${formatKw(view.available_kw)} para recarga`
}

/** Faixa do controle deslizante: 0 até o limite contratado (ou 100 kW sem limite). */
export function loadSliderMax(view: Pick<StationPower, 'site_limit_kw' | 'building_load_kw'>): number {
  const limit = toNumber(view.site_limit_kw)
  const load = toNumber(view.building_load_kw) ?? 0
  return Math.max(10, Math.ceil(Math.max(limit ?? 100, load)))
}

/** Limite contratado digitado ("75,5") → string da API, `null` (vazio remove) ou erro. */
export function validateSiteLimit(text: string): { value?: string | null; error?: string } {
  const raw = text.trim()
  if (!raw) return { value: null }
  if (!/^\d{1,5}([.,]\d)?$/.test(raw)) return { error: 'Use kW com até 1 casa, por exemplo 75,5.' }
  const number = Number(raw.replace(',', '.'))
  if (number <= 0) return { error: 'Informe um limite maior que zero.' }
  if (number > 10000) return { error: 'O limite contratado vai até 10.000 kW.' }
  return { value: number.toFixed(1) }
}

export interface Debounced<A extends unknown[]> {
  (...args: A): void
  /** Executa já o último pedido pendente (ex.: ao soltar o controle). */
  flush(): void
  cancel(): void
  pending(): boolean
}

/** Debounce simples (último valor vence) com `flush`/`cancel`, testável com timers falsos. */
export function debounce<A extends unknown[]>(fn: (...args: A) => void, wait: number): Debounced<A> {
  let timer: ReturnType<typeof setTimeout> | null = null
  let last: A | null = null
  const run = () => {
    timer = null
    if (!last) return
    const args = last
    last = null
    fn(...args)
  }
  const debounced = ((...args: A) => {
    last = args
    if (timer) clearTimeout(timer)
    timer = setTimeout(run, wait)
  }) as Debounced<A>
  debounced.flush = () => {
    if (timer) clearTimeout(timer)
    run()
  }
  debounced.cancel = () => {
    if (timer) clearTimeout(timer)
    timer = null
    last = null
  }
  debounced.pending = () => timer !== null
  return debounced
}
