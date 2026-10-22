/**
 * Seção Potência do posto (mesmas regras da tela Potência do app, `services/site_power.py`, e da API,
 * `chargegrid_core.site_load`/`power`).
 *
 * **Limites** num só lugar: limite contratado (o do dono ou o padrão), margem ESTIMADA da loja (mínimo e
 * pico; sem medidor, o pico fica reservado o tempo todo) e máximo dos carregadores:
 * `para os carregadores = min(máximo dos carregadores, contratado − pico estimado)`.
 * A régua (escala, passos, faixas) e as travas de cada controle de arrastar ficam aqui, sem React.
 */
import type { StationPower } from '../api/operations'
import type { Connector } from '../api/types'
import { formatNumber, toNumber } from './format'

/** Atualização da seção enquanto a página está aberta e visível (como o app). */
export const POWER_POLL_MS = 3000

export const DEFAULT_STORE_MIN_KW = 14
export const DEFAULT_STORE_PEAK_KW = 22
export const FLOOR_KW = 1.4
export const ESTIMATE_LABEL = 'ESTIMATIVA'
export const REBALANCE_HELP = 'Divide a potência entre os carros sem passar dos limites do posto.'
export const ESTIMATE_HELP =
  'Não medimos a loja: é uma estimativa sua. Reservamos o pico estimado o tempo todo, por cima de tudo, e os carregadores dividem o que sobra.'

const round1 = (value: number) => Math.round(value * 10) / 10

/** Limite contratado padrão (`site_load.default_site_limit_kw`): `max(75 kW, pico × 1,3)` em passos de 10 kW. */
export function defaultSiteLimitKw(peakKw: number = DEFAULT_STORE_PEAK_KW): number {
  return Math.max(75, Math.ceil(Number((Math.max(0, peakKw) * 1.3).toFixed(6)) / 10) * 10)
}

/** "6 kW", "28,5 kW", "—" (até 1 casa, como a API arredonda). */
export function formatKw(value: string | number | null | undefined, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  const rounded = round1(number)
  return `${formatNumber(rounded, Number.isInteger(rounded) ? 0 : 1)} kW`
}

/** Valor → texto do campo ("75,5"; vazio sem valor). */
export function limitInput(value: string | number | null | undefined): string {
  const number = toNumber(value)
  return number === null ? '' : String(round1(number)).replace('.', ',')
}

/** kW digitado ("75,5") → número, `null` (vazio) ou erro. */
export function parseKw(text: string, { allowZero = false } = {}): { value?: number | null; error?: string } {
  const raw = text.trim()
  if (!raw) return { value: null }
  if (!/^\d{1,5}([.,]\d)?$/.test(raw)) return { error: 'Use kW com até 1 casa, por exemplo 75,5.' }
  const number = Number(raw.replace(',', '.'))
  if (number < 0 || (number === 0 && !allowZero)) return { error: 'Informe um valor maior que zero.' }
  if (number > 10000) return { error: 'Os valores vão até 10.000 kW.' }
  return { value: number }
}

export interface PowerSummary {
  available: string
  limit: string
  limitDetail: string
  store: string
  storeDetail: string
  cars: string
  carsDetail: string
  over: string | null
}

/** Cartão do topo: disponível, limite, margem ESTIMADA da loja e carros agora (`site_power.summary`). */
export function powerSummary(view: StationPower): PowerSummary {
  const used = toNumber(view.envelope_kw) ?? toNumber(view.allocated_kw) ?? 0
  const exceeded = Math.max(0, toNumber(view.exceeded_kw) ?? 0)
  const count = view.cars || 0
  const reserve = toNumber(view.store_reserve_kw) ?? toNumber(view.store_peak_kw)
  return {
    available: formatKw(view.available_kw, 'Sem limite'),
    limit: formatKw(view.site_limit_kw, 'Sem limite'),
    limitDetail: view.site_limit_default ? 'Padrão (75 kW ou pico × 1,3)' : 'Informado por você',
    store: `−${formatKw(reserve, '0 kW')}`,
    storeDetail: `Pico estimado, reservado o tempo todo${view.store_estimate_default ? ' (padrão)' : ''}`,
    cars: formatKw(used, '0 kW'),
    carsDetail: count ? `${count} carro${count !== 1 ? 's' : ''} carregando` : 'Nenhum carro carregando',
    over: exceeded > 0 ? `Excesso transitório de ${formatKw(exceeded)}: reduções enviadas, aguardando os equipamentos.` : null,
  }
}

/* ---------------------------------------------------------------- régua de Limites */

export interface LimitsDraft {
  limit: number
  limitDefault: boolean
  min: number
  peak: number
  storeDefault: boolean
  /** Máximo dos carregadores (`null` = sem teto próprio). */
  cap: number | null
  notify: boolean
  /** Soma das nominais dos conectores ativos, piso de um carro e soma dos pisos. */
  total: number
  floor: number
  floorTotal: number
  scale: number
  step: number
}

const NICE = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]

/** Fim da régua: `max(contratado, 20) × 1,25` arredondado para cima (1/1,2/1,5/2/2,5/3/4/5/6/8 × 10ⁿ). */
export function scaleMax(limit: number): number {
  const top = Math.max(limit, 20) * 1.25
  const magnitude = 10 ** (String(Math.floor(top)).length - 1)
  const factor = NICE.find((item) => item * magnitude >= top) ?? 10
  return Math.round(factor * magnitude)
}

/** Passo do arraste: 1 kW até 200 kW de escala, 5 kW até 1.000, 10 kW acima. */
export function stepFor(scale: number): number {
  return scale <= 200 ? 1 : scale <= 1000 ? 5 : 10
}

export function snap(value: number, step: number): number {
  return Math.max(0, round1(Math.round(value / step) * step))
}

/** Rascunho a partir de `GET power` (valores efetivos e padrões). */
export function limitsDraft(view: StationPower): LimitsDraft {
  const peak = toNumber(view.store_peak_kw) ?? DEFAULT_STORE_PEAK_KW
  const min = toNumber(view.store_min_kw) ?? Math.min(DEFAULT_STORE_MIN_KW, peak)
  const floor = toNumber(view.charger_floor_kw) ?? FLOOR_KW
  const draft: LimitsDraft = {
    limit: toNumber(view.site_limit_kw) ?? defaultSiteLimitKw(peak),
    limitDefault: Boolean(view.site_limit_default),
    min,
    peak,
    storeDefault: view.store_peak_kw == null ? true : Boolean(view.store_estimate_default),
    cap: toNumber(view.station_cap_kw),
    notify: Boolean(view.power_limit_notify),
    total: toNumber(view.connectors_total_kw) ?? 0,
    floor,
    floorTotal: toNumber(view.chargers_floor_total_kw) ?? floor,
    scale: 0,
    step: 1,
  }
  return rescale(draft)
}

export function rescale(draft: LimitsDraft): LimitsDraft {
  const scale = scaleMax(draft.limit)
  return { ...draft, scale, step: stepFor(scale) }
}

/** Contratado − pico estimado. */
export const remainder = (d: LimitsDraft) => Math.max(0, round1(d.limit - d.peak))
/** `min(teto, contratado − pico)`. */
export const budget = (d: LimitsDraft) => (d.cap === null ? remainder(d) : Math.min(remainder(d), d.cap))
/** A partir daqui o teto não muda nada (vira "sem teto próprio"). */
export const capTop = (d: LimitsDraft) => (d.total > 0 ? Math.min(remainder(d), d.total) : remainder(d))

export interface Move {
  draft: LimitsDraft
  hint: string | null
}

/** Faixa da loja (mínimo e pico): o pico deixa ao menos o piso de um carro. */
export function moveStore(d: LimitsDraft, low: number, high: number): Move {
  let peak = snap(high, d.step)
  let hint: string | null = null
  const top = Math.max(0, round1(d.limit - d.floor))
  if (peak > top) {
    peak = top
    hint = 'Para reservar mais para a loja, aumente o limite contratado.'
  }
  return { draft: { ...d, min: Math.min(snap(low, d.step), peak), peak, storeDefault: false }, hint }
}

/** Limite contratado: nunca abaixo do pico da loja + o piso de um carro. */
export function moveLimit(d: LimitsDraft, value: number): Move {
  let limit = snap(value, d.step)
  let hint: string | null = null
  const bottom = round1(d.peak + d.floor)
  if (limit < bottom) {
    limit = bottom
    hint = 'Para baixar mais o contratado, reduza o pico estimado da loja.'
  }
  return { draft: { ...d, limit, limitDefault: false }, hint }
}

/** Máximo dos carregadores: no fim da faixa = sem teto próprio (`null`). */
export function moveCap(d: LimitsDraft, value: number): Move {
  let cap = snap(value, d.step)
  let hint: string | null = null
  if (cap < d.floorTotal) {
    cap = d.floorTotal
    hint = `O mínimo é ${formatKw(d.floorTotal)} (piso de cada carregador).`
  }
  return { draft: { ...d, cap: cap >= capTop(d) ? null : cap }, hint }
}

/** "53 kW · sem teto" (sem teto próprio: tudo que sobra, ou todos no máximo) ou "40 kW". */
export function capText(d: LimitsDraft): string {
  return d.cap === null || d.cap >= capTop(d) ? `${formatKw(capTop(d))} · sem teto` : formatKw(d.cap)
}

export const storeText = (d: LimitsDraft) => `${formatKw(d.min).replace(' kW', '')} – ${formatKw(d.peak)}`

export function equation(d: LimitsDraft): string {
  const head = `${formatKw(d.limit)} contratados − ${formatKw(d.peak)} de margem da loja`
  return d.cap !== null && d.cap < remainder(d) ? `${head} · limitado pelo máximo dos carregadores` : head
}

export type SegmentKey = 'store_base' | 'store_peak' | 'cars' | 'chargers' | 'unused' | 'above'

/** Faixas da régua em kW, da esquerda para a direita (as de 0 kW somem), como `site_power.segments`. */
export function segments(d: LimitsDraft, used?: number | null): { key: SegmentKey; kw: number }[] {
  const left = remainder(d)
  const chargers = budget(d)
  const inUse = Math.min(Math.max(0, used ?? 0), chargers)
  const items: { key: SegmentKey; kw: number }[] = [
    { key: 'store_base', kw: d.min },
    { key: 'store_peak', kw: round1(d.peak - d.min) },
    { key: 'cars', kw: inUse },
    { key: 'chargers', kw: round1(chargers - inUse) },
    { key: 'unused', kw: round1(left - chargers) },
    { key: 'above', kw: Math.max(0, round1(d.scale - d.limit)) },
  ]
  return items.filter((item) => item.kw > 0)
}

export interface PowerSiteBody {
  site_limit_kw?: string | null
  store_min_kw?: string | null
  store_peak_kw?: string | null
  max_power_kw?: string | null
  power_limit_notify?: boolean
  rebalance_enabled?: boolean
}

/** Corpo do `PUT power-site` só com o que mudou; o padrão nunca é gravado como valor do dono. */
export function limitsChanges(draft: LimitsDraft, original: LimitsDraft): PowerSiteBody {
  const body: PowerSiteBody = {}
  if (!draft.limitDefault && (original.limitDefault || draft.limit !== original.limit)) body.site_limit_kw = draft.limit.toFixed(1)
  else if (draft.limitDefault && !original.limitDefault) body.site_limit_kw = null
  const storeChanged = draft.min !== original.min || draft.peak !== original.peak
  if (draft.storeDefault && !original.storeDefault) Object.assign(body, { store_min_kw: null, store_peak_kw: null })
  else if (!draft.storeDefault && (storeChanged || original.storeDefault)) Object.assign(body, { store_min_kw: draft.min.toFixed(1), store_peak_kw: draft.peak.toFixed(1) })
  if (draft.cap !== original.cap) body.max_power_kw = draft.cap === null ? null : draft.cap.toFixed(1)
  if (draft.notify !== original.notify) body.power_limit_notify = draft.notify
  return body
}

/** "Restaurar padrão": loja 14–22 kW, contratado padrão e sem teto próprio. */
export function restoreDefaults(d: LimitsDraft): LimitsDraft {
  return rescale({ ...d, min: DEFAULT_STORE_MIN_KW, peak: DEFAULT_STORE_PEAK_KW, storeDefault: true, limit: defaultSiteLimitKw(), limitDefault: true, cap: null })
}

/** Valores digitados nos campos exatos; devolve o rascunho ou o erro. */
export function typedValues(d: LimitsDraft, texts: { limit: string; min: string; peak: string; cap: string }): { draft?: LimitsDraft; error?: string } {
  const limit = parseKw(texts.limit)
  const min = parseKw(texts.min, { allowZero: true })
  const peak = parseKw(texts.peak, { allowZero: true })
  const cap = parseKw(texts.cap)
  const error = limit.error ?? min.error ?? peak.error ?? cap.error
  if (error) return { error }
  if (limit.value == null || min.value == null || peak.value == null) return { error: 'Preencha o contratado e a estimativa da loja.' }
  if (min.value > peak.value) return { error: 'O mínimo estimado da loja não pode passar do pico.' }
  if (limit.value - peak.value < d.floor) return { error: `O pico da loja precisa deixar ao menos ${formatKw(d.floor)} do contratado para os carregadores.` }
  if (cap.value != null && cap.value < d.floorTotal) return { error: `O máximo dos carregadores precisa ser de pelo menos ${formatKw(d.floorTotal)}.` }
  const next = { ...d, limit: limit.value, limitDefault: false, min: min.value, peak: peak.value, storeDefault: false, cap: cap.value ?? null }
  if (next.cap !== null && next.cap >= capTop(next)) next.cap = null
  return { draft: rescale(next) }
}

/* ---------------------------------------------------------------- conectores */

export interface ConnectorPower {
  inactive: boolean
  configured: number
  effective: number | null
  /** Carregando: potência aplicada (ou alvo) agora; livre: o máximo que receberia ("até"). */
  charging: boolean
}

/** Pedido do conector: nominal, reduzida pelo limite do vendedor (`power.requested_kw`). */
export function requestedKw(connector: Pick<Connector, 'power_kw' | 'power_limit_kw'>): number {
  const rating = toNumber(connector.power_kw) ?? 0
  const limit = toNumber(connector.power_limit_kw)
  return limit !== null && limit > 0 ? Math.min(rating, limit) : rating
}

/** Potência configurada × efetiva de um conector (`site_power.connector_line`). */
export function connectorPower(connector: Connector, view: Pick<StationPower, 'available_kw' | 'points'> | null): ConnectorPower {
  const configured = requestedKw(connector)
  if (connector.active === false) return { inactive: true, configured, effective: null, charging: false }
  const session = view?.points.find((p) => p.connector_id === connector.id)?.session
  if (session) {
    const now = toNumber(session.applied_kw) ?? toNumber(session.target_kw)
    if (now !== null) return { inactive: false, configured, effective: now, charging: true }
  }
  let effective = toNumber(connector.effective_power_kw) ?? configured
  const available = toNumber(view?.available_kw)
  if (available !== null && available < effective) effective = available
  return { inactive: false, configured, effective, charging: false }
}

/** "60 kW configurados · 47 kW efetivos" (carregando) ou "… · até 55 kW efetivos" (livre). */
export function connectorLine(power: ConnectorPower): string {
  if (power.inactive) return 'Inativo: fica fora da divisão do posto'
  const head = `${formatKw(power.configured)} configurados`
  return `${head} · ${power.charging ? '' : 'até '}${formatKw(power.effective)} efetivos`
}
