/**
 * DEV-ONLY: dados fictícios das frentes de operação do posto, no formato da API:
 *
 * - C · Resultado: custo do kWh por posto (Villa Olímpia sem custo, para mostrar o "—"),
 *   `/owner/margin` com a regra de `chargegrid_core.economics` e exportações CSV/PDF;
 * - B · Energia do estabelecimento: limite contratado, consumo SIMULADO da loja, divisão
 *   da potência, confirmação do equipamento com atraso (excesso transitório) e decisões;
 * - A · Pagamentos (Stripe · teste): interruptores do posto e `payment` nas sessões;
 * - Totem 0.8.0: `kiosk_mode` (Villa Lobos ligado), CG-003 travado por um pedido do totem
 *   (`kiosk_in_use`) e `payment.channel` (app / QR do painel / totem, simulado ou Stripe) nas sessões;
 * - D · Permanência: `rules.rotation` (`start_after_min`/`interval_min`, como a API), PUT
 *   parcial mesclado, termos públicos no posto, `overstay_fee`/`overstay_minutes` nas
 *   sessões e `occupancy` no ao vivo.
 *
 * Nunca entra no build de produção (importado só pelo mock).
 */
import type {
  LiveOccupancy,
  MarginReport,
  MarginRow,
  PowerDecision,
  PricingRules,
  RotationRule,
  SessionPayment,
  StationEconomics,
  StationOverstay,
  StationPower,
  StationPricing,
} from '../api/operations'
import type { LiveItem, SessionItem, Station } from '../api/types'
import { formatCurrency } from '../lib/format'
import * as data from './data'

const START = Date.now()
const S = data.STATIONS

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}
const cents = (value: number) => Math.round(value * 100 + Number.EPSILON * 100)
const money = (c: number) => (c / 100).toFixed(2)
/** Mesmo caminho de `economics._value`: 4 casas (como o cost_estimate) e depois o centavo. */
const value = (amount: number) => cents(Number(amount.toFixed(4)))
const round2 = (value: number) => cents(value) / 100

export class MockFailure extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

/* ------------------------------------------------------- C · custo do kWh */

const ENERGY_COST: Record<string, string | null> = { [S[0].id]: '0.8500', [S[1].id]: '0.9200', [S[2].id]: null }
const FEE = '25.00'

export function economics(stationId: string, notes = true): StationEconomics {
  const result: StationEconomics = {
    station_id: stationId,
    energy_cost_per_kwh: ENERGY_COST[stationId] ?? null,
    platform_fee_percent: FEE,
    fee_editable: false,
    currency: 'BRL',
  }
  if (notes) {
    result.notes = [
      'Custo do kWh: informe o valor médio pago à distribuidora (R$/kWh). Vale para as próximas recargas; as anteriores mantêm o custo travado no início.',
      'A comissão da plataforma é definida em contrato e não pode ser alterada no painel.',
    ]
  }
  return result
}

export function putEconomics(stationId: string, body: Record<string, unknown>): StationEconomics {
  if ('platform_fee_percent' in body) throw new MockFailure(422, 'fee_read_only', 'A comissão da plataforma é definida em contrato e não pode ser alterada no painel.')
  const value = body.energy_cost_per_kwh
  if (value === null || value === undefined || value === '') {
    ENERGY_COST[stationId] = null
  } else {
    const number = Number(String(value).replace(',', '.'))
    if (!Number.isFinite(number)) throw new MockFailure(422, 'invalid_economics', 'Informe o custo do kWh com números, por exemplo 0,85.')
    if (number < 0 || number > 100) throw new MockFailure(422, 'invalid_economics', 'O custo do kWh vai de R$ 0,00 a R$ 100,00.')
    ENERGY_COST[stationId] = number.toFixed(4)
  }
  return economics(stationId)
}

/* ------------------------------------------------ D · regras de permanência */

/** Padrão da API (`chargegrid_core.pricing.DEFAULT_RULES`): só estas chaves sobrevivem ao PUT. */
const DEFAULT_RULES = {
  demand: { enabled: true, max_increase_percent: 50, sensitivity: 'medium' },
  schedule: { enabled: true, intervals: [] as unknown[] },
  peak: { enabled: true, start: '18:00', end: '21:00', days: [0, 1, 2, 3, 4, 5, 6] },
  rotation: { enabled: false, start_after_min: 10, interval_min: 1, amount: '1.00', max_amount: '30.00' },
}
type RuleKey = keyof typeof DEFAULT_RULES

const RULES: Record<string, PricingRules> = Object.fromEntries(
  S.map((station, index) => [
    station.id,
    {
      demand: { enabled: true, max_increase_percent: 30, sensitivity: 'medium' },
      schedule: { enabled: index === 2, intervals: index === 2 ? [{ start: '22:00', end: '06:00', days: [0, 1, 2, 3, 4, 5, 6], prices: {} }] : [] },
      peak: { enabled: false, start: '18:00', end: '21:00', days: [0, 1, 2, 3, 4, 5, 6] },
      rotation: { enabled: index !== 2, start_after_min: 10, interval_min: 1, amount: '1.00', max_amount: '30.00' },
    },
  ]),
)

/** `overstay.clean_rotation`: mesmas faixas e mensagens da API. */
function cleanRotation(raw: Record<string, unknown>): RotationRule {
  const grace = Number(raw.start_after_min)
  const interval = Number(raw.interval_min)
  const amount = Number(raw.amount)
  const max = Number(raw.max_amount)
  if (typeof raw.enabled !== 'boolean') throw new MockFailure(422, 'invalid_pricing', 'Status da regra inválido.')
  if (![grace, interval, amount, max].every(Number.isFinite) || !Number.isInteger(grace) || !Number.isInteger(interval)) {
    throw new MockFailure(422, 'invalid_pricing', 'Preencha a taxa de permanência com números.')
  }
  if (grace < 0 || grace > 1440) throw new MockFailure(422, 'invalid_pricing', 'A tolerância vai de 0 a 1440 minutos.')
  if (interval < 1 || interval > 1440) throw new MockFailure(422, 'invalid_pricing', 'O intervalo da taxa de permanência vai de 1 a 1440 minutos.')
  if (amount < 0 || amount > 100) throw new MockFailure(422, 'invalid_pricing', 'O valor da taxa de permanência vai de R$ 0,00 a R$ 100,00.')
  if (max < 0 || max > 1000) throw new MockFailure(422, 'invalid_pricing', 'O teto da taxa de permanência vai de R$ 0,00 a R$ 1.000,00.')
  return { enabled: raw.enabled, start_after_min: grace, interval_min: interval, amount: amount.toFixed(2), max_amount: max.toFixed(2) }
}

/**
 * `pricing.merge_rules` + `clean_rules`: o PUT é parcial (cada regra enviada é mesclada
 * campo a campo sobre a salva) e chaves fora do padrão são descartadas em silêncio.
 */
export function mergeRules(stored: PricingRules, body: Record<string, unknown>): PricingRules {
  const merged: Record<string, unknown> = structuredClone(stored)
  for (const [key, value] of Object.entries(body ?? {})) {
    const current = merged[key]
    merged[key] = value && typeof value === 'object' && !Array.isArray(value) && current && typeof current === 'object'
      ? { ...(current as object), ...structuredClone(value as object) }
      : structuredClone(value)
  }
  const result: Record<string, Record<string, unknown>> = {}
  for (const key of Object.keys(DEFAULT_RULES) as RuleKey[]) {
    const defaults: Record<string, unknown> = structuredClone(DEFAULT_RULES[key])
    const raw = merged[key]
    if (raw && typeof raw === 'object') {
      for (const field of Object.keys(defaults)) if (field in (raw as object)) defaults[field] = (raw as Record<string, unknown>)[field]
    }
    if (typeof defaults.enabled !== 'boolean') throw new MockFailure(422, 'invalid_pricing', 'Status da regra inválido.')
    result[key] = defaults
  }
  const increase = Number(result.demand.max_increase_percent)
  if (!Number.isInteger(increase)) throw new MockFailure(422, 'invalid_pricing', 'Informe o acréscimo máximo em porcentagem inteira.')
  if (increase < 0 || increase > 100) throw new MockFailure(422, 'invalid_pricing', 'O acréscimo máximo vai de 0% a 100%.')
  result.demand.max_increase_percent = increase
  if (!['low', 'medium', 'high'].includes(String(result.demand.sensitivity))) throw new MockFailure(422, 'invalid_pricing', 'Escolha a sensibilidade: baixa, média ou alta.')
  if (!Array.isArray(result.schedule.intervals)) throw new MockFailure(422, 'invalid_pricing', 'Horários da tarifa inválidos.')
  result.rotation = cleanRotation(result.rotation) as unknown as Record<string, unknown>
  return result
}

const brl = (value: string) => `R$ ${value.replace('.', ',')}`

/** `overstay.public(terms)`: o bloco `overstay` público do posto. */
export function stationOverstay(stationId: string): StationOverstay {
  const rule = RULES[stationId]?.rotation
  if (!rule?.enabled) {
    return { enabled: false, grace_minutes: null, interval_minutes: null, amount: null, max_amount: null, fee_per_minute: null, version: null, summary: null }
  }
  const terms = { grace_minutes: rule.start_after_min, interval_minutes: rule.interval_min, amount: rule.amount, max_amount: rule.max_amount }
  const every = terms.interval_minutes === 1 ? 'por minuto' : `a cada ${terms.interval_minutes} min`
  return {
    enabled: true,
    ...terms,
    version: `ovs-${hash(JSON.stringify(terms)).toString(16).padStart(12, '0').slice(0, 12)}`,
    fee_per_minute: (Number(terms.amount) / terms.interval_minutes).toFixed(4),
    summary: `Após a recarga: ${terms.grace_minutes} min de tolerância; depois ${brl(terms.amount)} ${every}, até ${brl(terms.max_amount)}.`,
  }
}

function decorateStation(station: Station) {
  const index = S.indexOf(station)
  station.prepay_required ??= index === 1
  station.kiosk_payments ??= index !== 2
  station.kiosk_mode ??= index === 0
  for (const connector of station.connectors) {
    connector.kiosk_in_use ??= false
    // Pedido do totem aberto: o ponto aparece ocupado ("Em uso no totem"), como `availability()` da API.
    if (index === 0 && connector.public_code === 'CG-003' && connector.availability_status === 'available') {
      Object.assign(connector, { available: false, availability_status: 'occupied', kiosk_in_use: true })
    }
  }
  station.overstay = stationOverstay(station.id)
}
S.forEach(decorateStation)

export function pricing(stationId: string): StationPricing {
  const station = S.find((s) => s.id === stationId)!
  return {
    rules: structuredClone(RULES[stationId]),
    status: { multiplier: '1.00', level: 'normal', level_label: 'Normal', reason: 'normal', reason_label: 'Preço normal' },
    connectors: station.connectors.map((c) => ({
      id: c.id, public_code: c.public_code, active: c.active, connector_type: c.connector_type,
      base_price_per_kwh: c.price_per_kwh, current_base_price_per_kwh: c.price_per_kwh, current_price_per_kwh: c.price_per_kwh,
    })),
  }
}

/** PUT parcial, como a API: `{ rotation }` sozinho ou a sugestão da Previsão (`{ demand }`, `{ schedule }`). */
export function putPricing(stationId: string, body: Record<string, unknown>): StationPricing {
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw new MockFailure(422, 'validation_error', 'Envie um objeto com as regras.')
  RULES[stationId] = mergeRules(RULES[stationId], body)
  const station = S.find((s) => s.id === stationId)
  if (station) station.overstay = stationOverstay(stationId)
  return pricing(stationId)
}

/* ---------------------------------------------- A/D · sessões decoradas */

const PAID_LABEL = (charged: number, returned: number) =>
  returned > 0 ? `Cobrado ${formatCurrency(charged / 100)} (teste) · Devolvido ${formatCurrency(returned / 100)}` : `Cobrado ${formatCurrency(charged / 100)} (teste)`

/** `overstay_fee`/`overstay_minutes` de `/owner/sessions` (sem bloco `overstay`, como a API). */
function overstayFor(session: SessionItem): Pick<SessionItem, 'overstay_fee' | 'overstay_minutes'> {
  const h = hash(`ovs-${session.id}`)
  const rule = RULES[session.station_id]?.rotation
  const eligible = session.status === 'completed' && rule?.enabled && h % 100 < 14
  if (!eligible) return { overstay_fee: '0.00', overstay_minutes: 0 }
  const minutes = 1 + (h % 12)
  return { overstay_fee: money(Math.min(minutes * 100, 3000)), overstay_minutes: minutes }
}

function paymentFor(session: SessionItem, overstayCents: number): SessionPayment | null {
  const h = hash(`pay-${session.id}`)
  const prepay = S.find((s) => s.id === session.station_id)?.prepay_required
  if (!prepay && h % 100 >= 35) return null
  if (session.status === 'failed') return null
  const energy = cents(Number(session.cost_estimate ?? 0))
  const amount = Math.max(2000, Math.ceil((energy + overstayCents + 1000) / 1000) * 1000)
  const station = S.find((s) => s.id === session.station_id)
  // Canal: app, QR do painel (/pay/k) ou pedido do totem (só com o totem ligado); o totem de conta em
  // Modo apresentação paga simulado (acerto local, rótulo "(simulado)").
  const kiosk = h % 7 === 0 || (station?.kiosk_mode === true && h % 4 === 1)
  const channel = !kiosk ? 'app' : station?.kiosk_mode && h % 2 === 1 ? 'kiosk_totem' : 'kiosk_qr'
  const simulated = channel === 'kiosk_totem' && h % 3 !== 0
  const method = simulated ? 'simulated' : h % 5 === 0 ? 'pix' : 'card'
  const base = {
    id: `pay-${session.id.slice(0, 8)}`, environment: 'test', provider: simulated ? 'simulated' : 'stripe', origin: kiosk ? 'kiosk' : 'app', channel,
    method, currency: 'BRL', amount: money(amount),
  }
  const tag = (label: string) => (simulated ? label.replace(/\(teste\)/g, '(simulado)') : label)
  if (session.status === 'charging') return { ...base, status: 'in_use', status_label: tag('Pago (teste) · em uso'), settlement: null }
  const charged = energy + overstayCents
  const returned = amount - charged
  return {
    ...base,
    status: 'completed',
    status_label: tag(PAID_LABEL(charged, returned)),
    settlement: {
      status: 'done', energy_amount: money(energy), overstay_amount: money(overstayCents), fixed_fee: '0.00', charged: money(charged), returned: money(returned),
      return_kind: method === 'pix' ? 'refunded' : 'released', captured: money(charged), refunded: method === 'pix' ? money(returned) : '0.00', waived: '0.00',
      uncollected: '0.00', below_minimum: false, provider_fee: simulated ? null : money(Math.round(charged * 0.0399) + 39), settled_at: session.ended_at,
    },
  }
}

export function decorateSession(session: SessionItem): SessionItem {
  const extra = overstayFor(session)
  const payment = paymentFor(session, cents(Number(extra.overstay_fee)))
  return { ...session, ...extra, payment }
}

/* --------------------------------------------------------- C · margem */

const METHODOLOGY = [
  'Receita bruta não é lucro. Margem = receita cobrada − comissão da plataforma − tarifa do provedor de pagamento − custo estimado da energia.',
  'Comissão sobre o valor cobrado depois do cupom, incluindo a taxa de permanência. O cupom é um desconto do dono do posto.',
  'Custo da energia = kWh × custo do kWh informado pelo dono, travado no início de cada recarga. Não inclui custos fixos (equipamento, aluguel, manutenção) nem tarifa de demanda (R$/kW).',
  'Sessões encerradas (concluídas ou interrompidas) com energia positiva, atribuídas à data de término (horário de São Paulo). Valores estimados até a confirmação do pagamento.',
]

function localHour(iso: string) {
  return Number(new Intl.DateTimeFormat('en-US', { timeZone: 'America/Sao_Paulo', hour: '2-digit', hourCycle: 'h23' }).format(new Date(iso)))
}

/** Uma linha de `session_economics` (mesma ordem de arredondamento: centavo por sessão). */
function marginRow(raw: SessionItem): MarginRow {
  const session = decorateSession(raw)
  const h = hash(`dem-${session.id}`)
  const multiplier = h % 100 < 6 ? 1.35 : h % 100 < 20 ? 1.2 : 1
  const kwh = Number(session.energy_kwh)
  const price = Number(session.price_per_kwh)
  const base = price / multiplier
  const night = S.indexOf(S.find((s) => s.id === session.station_id)!) === 2 && (localHour(session.ended_at!) >= 22 || localHour(session.ended_at!) < 6)
  const connectorBase = night ? base / 0.85 : base
  const gross = value(kwh * price)
  const revenue = cents(Number(session.cost_estimate))
  const atBase = value(kwh * base)
  const list = value(kwh * connectorBase)
  const overstay = cents(Number(session.overstay_fee ?? 0))
  const payment = session.payment?.settlement
  const revenueTotal = payment ? cents(Number(payment.charged)) : revenue + overstay
  const providerFee = payment?.provider_fee ? cents(Number(payment.provider_fee)) : null
  const platformFee = Math.round(revenueTotal * 0.25)
  const ownerNet = revenueTotal - platformFee - (providerFee ?? 0)
  const cost = ENERGY_COST[session.station_id]
  const energyCost = cost === null || cost === undefined ? null : value(kwh * Number(cost))
  const margin = energyCost === null ? null : ownerNet - energyCost
  return {
    session_id: session.id, ended_at: session.ended_at, station_id: session.station_id, station_name: session.station_name, public_code: session.public_code,
    source: session.source, energy_kwh: kwh.toFixed(3), connector_base_per_kwh: connectorBase.toFixed(4), base_per_kwh: base.toFixed(4),
    demand_multiplier: multiplier.toFixed(2), price_per_kwh: price.toFixed(4), coupon_code: session.discount_percent ? 'VERAO10' : null,
    discount_percent: session.discount_percent, list_value: money(list), schedule_effect: money(atBase - list), demand_effect: money(gross - atBase),
    gross: money(gross), discount: money(gross - revenue), revenue: money(revenue), overstay_revenue: overstay ? money(overstay) : null,
    revenue_total: money(revenueTotal), revenue_basis: payment ? 'captured' : 'estimated', payment_environment: session.payment ? 'test' : null,
    platform_fee_percent: FEE, platform_fee: money(platformFee), provider_fee: providerFee === null ? null : money(providerFee), owner_net: money(ownerNet),
    energy_cost_per_kwh: cost ?? null, cost_basis: cost ? 'snapshot' : 'missing', energy_cost: energyCost === null ? null : money(energyCost),
    margin: margin === null ? null : money(margin), margin_percent: margin !== null && revenueTotal ? ((margin / revenueTotal) * 100).toFixed(1) : null,
  }
}

const sumC = (rows: MarginRow[], key: keyof MarginRow) => rows.reduce((total, row) => total + (row[key] === null ? 0 : cents(Number(row[key]))), 0)
const anyValue = (rows: MarginRow[], key: keyof MarginRow) => rows.some((row) => row[key] !== null)

function totalsOf(rows: MarginRow[]) {
  const covered = rows.filter((row) => row.energy_cost !== null)
  const complete = covered.length === rows.length
  const revenueTotal = sumC(rows, 'revenue_total')
  const marginCovered = sumC(covered, 'margin')
  const margin = rows.length ? (complete ? marginCovered : null) : 0
  return {
    sessions: rows.length,
    energy_kwh: rows.reduce((t, r) => t + Number(r.energy_kwh), 0).toFixed(3),
    list_value: money(sumC(rows, 'list_value')),
    schedule_effect: anyValue(rows, 'schedule_effect') ? money(sumC(rows, 'schedule_effect')) : null,
    demand_effect: money(sumC(rows, 'demand_effect')),
    gross: money(sumC(rows, 'gross')),
    discount: money(sumC(rows, 'discount')),
    revenue: money(sumC(rows, 'revenue')),
    overstay_revenue: anyValue(rows, 'overstay_revenue') ? money(sumC(rows, 'overstay_revenue')) : null,
    revenue_total: money(revenueTotal),
    platform_fee: money(sumC(rows, 'platform_fee')),
    provider_fee: anyValue(rows, 'provider_fee') ? money(sumC(rows, 'provider_fee')) : null,
    owner_net: money(sumC(rows, 'owner_net')),
    energy_cost: covered.length ? money(sumC(covered, 'energy_cost')) : rows.length ? null : '0.00',
    margin: margin === null ? null : money(margin),
    margin_covered: money(marginCovered),
    margin_percent: margin !== null && revenueTotal ? ((margin / revenueTotal) * 100).toFixed(1) : null,
    coverage: { sessions: rows.length, with_energy_cost: covered.length, missing_energy_cost: rows.length - covered.length },
  }
}

function marginRows(params: URLSearchParams): MarginRow[] {
  const from = Date.parse(params.get('from') ?? '') || Date.now() - 7 * 86_400_000
  const to = Date.parse(params.get('to') ?? '') || Date.now()
  const station = params.get('station_id')
  return data.SESSION_POOL.filter((s) => {
    if (!['completed', 'interrupted'].includes(s.status) || !s.ended_at || Number(s.energy_kwh) <= 0) return false
    const ended = Date.parse(s.ended_at)
    return ended >= from && ended < to && (!station || s.station_id === station)
  })
    .map(marginRow)
    .sort((a, b) => (a.ended_at! < b.ended_at! ? 1 : -1))
}

export function marginReport(params: URLSearchParams): MarginReport {
  const rows = marginRows(params)
  const totals = totalsOf(rows)
  const station = params.get('station_id')
  const surge = rows.filter((r) => Number(r.demand_multiplier) > 1)
  const coupons = rows.filter((r) => r.discount_percent)
  const sources: Record<string, number> = {}
  rows.forEach((r) => (sources[r.source ?? 'unknown'] = (sources[r.source ?? 'unknown'] ?? 0) + 1))
  const byStation = S.filter((s) => !station || s.id === station)
    .map((s) => ({ ...totalsOf(rows.filter((r) => r.station_id === s.id)), station_id: s.id, station_name: s.name }))
    .filter((entry) => entry.sessions)
  const warnings: string[] = []
  if (totals.coverage.missing_energy_cost) {
    warnings.push(`${totals.coverage.missing_energy_cost} de ${totals.sessions} sessões sem custo da energia informado: a margem total não é calculada. Informe o custo do kWh do posto.`)
  }
  if (totals.margin !== null && Number(totals.margin) < 0) warnings.push('Margem negativa no período: o repasse não cobre o custo estimado da energia.')
  const limit = Math.min(500, Number(params.get('limit') ?? 50))
  const offset = Number(params.get('offset') ?? 0)
  return {
    schema_version: 1,
    period: { from: new Date(Date.parse(params.get('from') ?? '') || Date.now() - 7 * 86_400_000).toISOString(), to: new Date(Date.parse(params.get('to') ?? '') || Date.now()).toISOString(), timezone: 'America/Sao_Paulo' },
    basis: 'ended_at',
    currency: 'BRL',
    station_id: station,
    stations: S.filter((s) => !station || s.id === station).map((s) => ({ ...economics(s.id, false), station_name: s.name })),
    totals,
    dynamic_pricing: {
      demand_effect: totals.demand_effect,
      schedule_effect: totals.schedule_effect,
      sessions_with_increase: surge.length,
      average_multiplier: surge.length ? (surge.reduce((t, r) => t + Number(r.demand_multiplier), 0) / surge.length).toFixed(2) : null,
    },
    coupons: { sessions: coupons.length, discount: money(sumC(coupons, 'discount')) },
    sources,
    by_station: byStation,
    warnings,
    methodology: METHODOLOGY,
    items: rows.slice(offset, offset + limit),
    total: rows.length,
    limit,
    offset,
    generated_at: new Date().toISOString(),
  }
}

const CSV_COLUMNS: [keyof MarginRow, string][] = [
  ['session_id', 'ID da sessão'], ['ended_at', 'Fim'], ['station_name', 'Posto'], ['public_code', 'Ponto'], ['energy_kwh', 'Energia (kWh)'],
  ['price_per_kwh', 'Preço travado (R$/kWh)'], ['gross', 'Receita bruta antes do cupom (R$)'], ['discount', 'Desconto do cupom (R$)'],
  ['overstay_revenue', 'Taxa de permanência (R$)'], ['revenue_total', 'Receita cobrada (R$)'], ['platform_fee', 'Comissão da plataforma (R$)'],
  ['provider_fee', 'Tarifa do provedor (R$)'], ['owner_net', 'Repasse ao dono (R$)'], ['energy_cost', 'Custo estimado da energia (R$)'], ['margin', 'Margem estimada (R$)'],
]

export function marginCsv(params: URLSearchParams): string {
  const quote = (value: unknown) => {
    const text = value === null || value === undefined ? '' : String(value)
    return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
  }
  const lines = [CSV_COLUMNS.map(([, label]) => quote(label)).join(',')]
  for (const row of marginRows(params)) lines.push(CSV_COLUMNS.map(([key]) => quote(row[key])).join(','))
  return lines.join('\r\n') + '\r\n'
}

/** PDF mínimo e válido de uma página (texto Helvetica) só para a demonstração. */
export function marginPdf(params: URLSearchParams): Uint8Array {
  const t = totalsOf(marginRows(params))
  const ascii = (text: string) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[()\\]/g, '')
  const lines = [
    'ChargeGrid - Resultado do posto (DEMONSTRACAO, dados ficticios)',
    'Receita bruta nao e lucro.',
    `Receita bruta: R$ ${t.gross}`,
    `Descontos e cupons: - R$ ${t.discount}`,
    `Receita cobrada: R$ ${t.revenue_total}`,
    `Comissao da plataforma (25%): - R$ ${t.platform_fee}`,
    `Repasse: R$ ${t.owner_net}`,
    `Custo estimado da energia: ${t.coverage.missing_energy_cost ? '-' : `- R$ ${t.energy_cost}`}`,
    `Margem estimada: ${t.margin === null ? '-' : `R$ ${t.margin}`}`,
  ].map(ascii)
  const content = `BT /F1 12 Tf 50 790 Td 16 TL ${lines.map((l) => `(${l}) Tj T*`).join(' ')} ET`
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ]
  let pdf = '%PDF-1.4\n'
  const offsets: number[] = []
  objects.forEach((body, i) => {
    offsets.push(pdf.length)
    pdf += `${i + 1} 0 obj\n${body}\nendobj\n`
  })
  const xref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n${offsets.map((o) => `${String(o).padStart(10, '0')} 00000 n \n`).join('')}`
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`
  return new TextEncoder().encode(pdf)
}

/* ------------------------------------------ B · energia do estabelecimento */

interface PowerSite {
  rebalance: boolean
  limit: number | null
  load: number
  updatedAt: string | null
  applied: Record<string, number>
  pendingSince: Record<string, number>
  decisions: PowerDecision[]
  lastKey: string
}

const POWER: Record<string, PowerSite> = {
  [S[0].id]: { rebalance: true, limit: 75, load: 30, updatedAt: new Date(START - 60_000).toISOString(), applied: {}, pendingSince: {}, decisions: [], lastKey: '' },
  [S[1].id]: { rebalance: true, limit: 150, load: 62, updatedAt: new Date(START - 120_000).toISOString(), applied: {}, pendingSince: {}, decisions: [], lastKey: '' },
  [S[2].id]: { rebalance: false, limit: null, load: 0, updatedAt: null, applied: {}, pendingSince: {}, decisions: [], lastKey: '' },
}
const FLOOR = 1.4
let decisionSeq = 1
const kwText = (value: number) => (Math.round(value * 10) / 10).toFixed(1).replace(/\.0$/, '').replace('.', ',')

interface Allocation {
  connector: Station['connectors'][number]
  target: number
  code: 'site' | 'charger' | 'paused' | 'fixed'
}

function allocate(station: Station, site: PowerSite) {
  const charging = station.connectors.filter((c) => c.availability_status === 'charging')
  const available = site.limit === null ? Infinity : Math.max(0, site.limit - site.load)
  const requests = charging.map((c) => Number(c.power_kw))
  const want = requests.reduce((t, r) => t + r, 0)
  const allocations: Allocation[] = charging.map((connector, i) => {
    if (!site.rebalance) return { connector, target: requests[i], code: 'fixed' as const }
    if (available >= want) return { connector, target: requests[i], code: 'charger' as const }
    if (available < FLOOR * charging.length) {
      // Sem o mínimo para todos: os mais novos pausam (aqui, a partir do último).
      const fits = Math.floor(available / FLOOR)
      return i < fits ? { connector, target: Math.round((available / Math.max(1, fits)) * 10) / 10, code: 'site' as const } : { connector, target: 0, code: 'paused' as const }
    }
    return { connector, target: Math.round(((available * requests[i]) / want) * 10) / 10, code: 'site' as const }
  })
  return { available: site.limit === null ? null : available, allocations, cars: charging.length }
}

function reasonFor(alloc: Allocation, site: PowerSite, cars: number) {
  const alone = cars === 1 ? 'só o seu carro está carregando' : `há ${cars} carros carregando`
  const kw = kwText(alloc.target)
  switch (alloc.code) {
    case 'site':
      return { text: `${kw} kW porque a loja usa ${kwText(site.load)} de ${kwText(site.limit ?? 0)} kW e ${alone}.`, short: `Loja ${kwText(site.load)}/${kwText(site.limit ?? 0)} kW` }
    case 'paused':
      return { text: `Pausado: a loja usa ${kwText(site.load)} de ${kwText(site.limit ?? 0)} kW e não sobra o mínimo de 1,4 kW para mais um carro.`, short: 'Pausado: sem capacidade' }
    case 'fixed':
      return { text: `${kw} kW: rebalanceamento desligado, vale a potência definida no início da recarga.`, short: 'Rebalanceamento desligado' }
    default:
      return { text: `${kw} kW, o máximo deste carregador (sobra potência: ${alone}).`, short: 'Máximo do carregador' }
  }
}

function record(site: PowerSite, trigger: string, available: number | null, allocations: Allocation[], exceeded: number) {
  const parts = allocations.map((a) => `${a.connector.public_code} ${kwText(a.target)} kW`).join(', ')
  const summary = allocations.length
    ? `${available === null ? 'Sem limite contratado' : `Disponível ${kwText(available)} kW`} para ${allocations.length} carro(s): ${parts}.`
    : `${available === null ? 'Sem limite contratado' : `Disponível ${kwText(available)} kW`}; nenhum carro carregando.`
  site.decisions.unshift({ id: decisionSeq++, created_at: new Date().toISOString(), trigger, available_kw: available === null ? null : available.toFixed(1), exceeded_kw: exceeded.toFixed(1), summary })
  site.decisions.length = Math.min(site.decisions.length, 20)
}

/** Visão de `/stations/{id}/power`; o equipamento "confirma" ajustes ~1,2 s depois. */
export function power(stationId: string, trigger = 'initial'): StationPower {
  const station = S.find((s) => s.id === stationId)!
  const site = POWER[stationId]
  const now = Date.now()
  const { available, allocations, cars } = allocate(station, site)
  const key = JSON.stringify([site.rebalance, site.limit, site.load, allocations.map((a) => a.target)])
  let confirmed = false
  for (const a of allocations) {
    const id = a.connector.id
    site.applied[id] ??= a.target
    if (site.applied[id] !== a.target) {
      site.pendingSince[id] ??= now
      if (now - site.pendingSince[id] >= 1200) {
        site.applied[id] = a.target
        delete site.pendingSince[id]
        confirmed = true
      }
    } else delete site.pendingSince[id]
  }
  const envelopes = allocations.map((a) => Math.max(a.target, site.applied[a.connector.id] ?? a.target))
  const envelope = envelopes.reduce((t, e) => t + e, 0)
  const exceeded = available === null ? 0 : Math.max(0, envelope - available)
  if (key !== site.lastKey) {
    record(site, site.lastKey ? trigger : 'initial', available, allocations, exceeded)
    site.lastKey = key
  } else if (confirmed) {
    record(site, 'power_confirmed', available, allocations, exceeded)
  }
  return {
    station_id: stationId,
    rebalance_enabled: site.rebalance,
    site_limit_kw: site.limit === null ? null : site.limit.toFixed(1),
    building_load_kw: site.load.toFixed(1),
    building_load_source: site.updatedAt ? 'simulated' : null,
    building_load_simulated: Boolean(site.updatedAt),
    building_load_updated_at: site.updatedAt,
    station_cap_kw: null,
    available_kw: available === null ? null : available.toFixed(1),
    allocated_kw: allocations.reduce((t, a) => t + a.target, 0).toFixed(1),
    envelope_kw: envelope.toFixed(1),
    exceeded_kw: exceeded.toFixed(1),
    cars,
    points: station.connectors.map((connector) => {
      const alloc = allocations.find((a) => a.connector.id === connector.id)
      const applied = alloc ? site.applied[connector.id] : null
      const reason = alloc ? reasonFor(alloc, site, cars) : null
      const state = !alloc ? null : alloc.code === 'paused' && applied === 0 ? 'paused' : applied === alloc.target ? 'applied' : (applied ?? 0) > alloc.target ? 'reducing' : 'raising'
      return {
        connector_id: connector.id,
        public_code: connector.public_code,
        power_kw: Number(connector.power_kw).toFixed(1),
        online: Boolean(connector.online),
        adjustable: true,
        charger: { phases: Number(connector.power_kw) > 22 ? 3 : 1 },
        session: alloc
          ? {
              id: `ses-${connector.id.slice(0, 8)}`, status: 'charging', target_kw: alloc.target.toFixed(1), applied_kw: (applied ?? 0).toFixed(1),
              envelope_kw: Math.max(alloc.target, applied ?? 0).toFixed(1), power_state: state, reason: reason!.text, reason_short: reason!.short, reason_code: alloc.code,
            }
          : null,
      }
    }),
    decisions: structuredClone(site.decisions),
  }
}

export function putPowerSite(stationId: string, body: { site_limit_kw?: string | null; rebalance_enabled?: boolean }): StationPower {
  const site = POWER[stationId]
  let trigger = 'site_limit_changed'
  if ('site_limit_kw' in body) {
    if (body.site_limit_kw === null) site.limit = null
    else {
      const value = Number(body.site_limit_kw)
      if (!Number.isFinite(value) || value <= 0) throw new MockFailure(422, 'invalid_power_limit', 'Informe um limite contratado maior que zero.')
      if (value > 10000) throw new MockFailure(422, 'invalid_power_limit', 'O limite contratado deve ser de até 10.000 kW.')
      site.limit = Math.round(value * 10) / 10
    }
  }
  if (typeof body.rebalance_enabled === 'boolean') {
    site.rebalance = body.rebalance_enabled
    trigger = 'request_changed'
  }
  return power(stationId, trigger)
}

export function putBuildingLoad(stationId: string, body: { building_load_kw?: string | number }): StationPower {
  const value = Number(body.building_load_kw)
  if (!Number.isFinite(value) || value < 0 || value > 10000) throw new MockFailure(422, 'validation_error', 'O consumo vai de 0 a 10.000 kW.')
  const site = POWER[stationId]
  site.load = Math.round(value * 10) / 10
  site.updatedAt = new Date().toISOString()
  return power(stationId, 'building_load_changed')
}

/* ------------------------------------------------- ao vivo: potência e vaga */

/** Carros que continuam na vaga depois da recarga (ponto livre, cabo conectado). */
const OCCUPIED: Record<string, { endedMinutesAgo: number; label: string }> = {
  'CG-002': { endedMinutesAgo: 4, label: 'Motorista do app' },
  'CG-006': { endedMinutesAgo: 14, label: 'Visitante do painel' },
}

/** `overstay.occupancy_by_connector`: mesmo formato e regras de fase da API. */
function occupancyFor(item: LiveItem): LiveOccupancy | null {
  const spot = OCCUPIED[item.public_code]
  const rule = RULES[item.station_id]?.rotation
  if (!spot || item.availability_status !== 'available') return null
  const since = Math.floor((Date.now() - START) / 1000 + spot.endedMinutesAgo * 60)
  const started = new Date(Date.now() - since * 1000).toISOString()
  const base = { session_id: `ovs-${item.connector_id.slice(0, 8)}`, started_at: started, driver_label: spot.label, as_of: new Date().toISOString() }
  if (!rule?.enabled) {
    return { ...base, status: 'no_fee', grace_remaining_seconds: 0, billable_minutes: 0, fee_due: '0.00', max_fee: null, fee_applies: false }
  }
  const grace = rule.start_after_min * 60
  const amount = Number(rule.amount)
  const max = Number(rule.max_amount)
  const intervals = Math.max(0, Math.floor((since - grace) / (rule.interval_min * 60)))
  const fee = Math.min(round2(intervals * amount), max)
  const capped = fee >= max
  const status = capped ? 'capped' : since <= grace ? 'grace' : 'billing'
  const cap = amount > 0 ? Math.ceil(max / amount) : intervals
  return {
    ...base, status, grace_remaining_seconds: Math.max(0, grace - since), billable_minutes: Math.min(intervals, cap) * rule.interval_min,
    fee_due: fee.toFixed(2), max_fee: rule.max_amount, fee_applies: true,
  }
}

export function decorateLive(payload: { items: LiveItem[]; generated_at: string }) {
  const views: Record<string, StationPower> = {}
  for (const item of payload.items) {
    const occupancy = occupancyFor(item)
    item.occupancy = occupancy
    if (occupancy) item.availability_status = 'occupied'
    if (item.session) {
      views[item.station_id] ??= power(item.station_id)
      const point = views[item.station_id].points.find((p) => p.connector_id === item.connector_id)?.session
      if (point) {
        item.session.applied_power_kw = point.applied_kw
        item.session.power_state = point.power_state
        item.session.power_reason = point.reason
        const appliedW = Number(point.applied_kw) * 1000
        if (item.session.power_w && Number(item.session.power_w) > appliedW) item.session.power_w = (appliedW * 0.97).toFixed(0)
      }
    }
  }
  return payload
}
