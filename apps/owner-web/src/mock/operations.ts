/**
 * DEV-ONLY: dados fictícios das frentes de operação do posto, no formato da API:
 *
 * - C · Resultado: custo do kWh por posto (Villa Olímpia sem custo, para mostrar o "—"),
 *   `/owner/margin` com a regra de `chargegrid_core.economics` e exportações CSV/PDF;
 * - Potência: limite contratado (padrão do tipo/porte ou o do dono), consumo da loja SIMULADO pela
 *   curva do tipo/porte, rebalanceamento ligado por padrão, divisão da potência, confirmação do
 *   equipamento com atraso (excesso transitório) e potência efetiva por conector;
 * - Pagamento automático (Stripe · teste; simulado no totem em Modo apresentação): `payment` nas sessões;
 * - Totem 0.8.0: `kiosk_mode` (Villa Lobos ligado), CG-003 travado por um pedido do totem
 *   (`kiosk_in_use`) e `payment.channel` (app / QR do painel / totem, simulado ou Stripe) nas sessões;
 * - Estação = a central; cada ponto É um carregador GoodWe HCA G2 (simulado): endereços 1..N por
 *   posto na ordem de criação, uma central online por posto (no primeiro ponto) comandando todos,
 *   carregadores online para a demonstração, CG-007 offline (estação online × carregador offline)
 *   e CG-010 aguardando a central; PATCH `charger_address` (1–247, nunca vazio, único no posto: 422/409)
 *   e `POST /connectors/{id}/chargers` (Adicionar carregador; 409 screen_required/charger_address_full);
 *   `DELETE /connectors/{id}` (Remover carregador; 409 screen_charger/point_busy; o endereço fica livre);
 *   `DELETE /stations/{id}` (Remover estação; 409 station_busy/central_online; some das listas);
 * - D · Permanência: `rules.rotation` (`start_after_min`/`interval_min`, como a API), PUT
 *   parcial mesclado, termos públicos no posto, `overstay_fee`/`overstay_minutes` nas
 *   sessões.
 *
 * Nunca entra no build de produção (importado só pelo mock).
 */
import type {
  CentralRentLine,
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
import type { ChargerLink, ChargerLinkState, Connector, SessionItem, Station } from '../api/types'
import { DEFAULT_STORE_MIN_KW, DEFAULT_STORE_PEAK_KW, defaultSiteLimitKw, FLOOR_KW, requestedKw } from '../lib/power'
import {
  CHARGER_ADDRESS_EMPTY,
  CHARGER_ADDRESS_INVALID,
  CHARGER_LABEL,
  CHARGER_MAX_ADDRESS,
  CHARGER_MIN_ADDRESS,
  CHARGER_MODEL,
  CHARGER_TRANSPORT,
  chargerHost,
  nextFreeChargerAddress,
} from '../lib/charger'
import { formatCurrency } from '../lib/format'
import * as data from './data'

const S = data.STATIONS

/* Estado dos carregadores (declarado antes de decorar os postos, logo abaixo). */
const SECOND = 1000
const MOCK_HOUR = 3_600_000
/** Firmware das centrais do mock (multi-carregador). */
export const SCREEN_FIRMWARE = '1.6.0'
/**
 * Estado de cada carregador no mock (por id do ponto). Padrão `online` para a demonstração;
 * CG-007 sem resposta (central online: estação online × carregador offline) e CG-010 ainda não
 * confirmado pela central (`pending`). Carregador adicionado pelo dono nasce `pending`.
 */
const LINK_STATE = new Map<string, ChargerLinkState>()
const LINK_SEED: Record<string, ChargerLinkState> = { 'CG-007': 'offline', 'CG-010': 'pending' }
/** Centrais desligadas no mock (por id do posto); as outras ficam online, como na demonstração. */
const SCREEN_OFFLINE = new Set<string>()
/**
 * Potência que o carregador está entregando (kW) pela mesma divisão do cartão Potência; ligada
 * depois que a potência do posto é declarada (abaixo). Antes disso: a efetiva do ponto.
 */
let deliveredKw: (connector: Connector) => number | undefined = () => undefined

function hash(text: string): number {
  let h = 2166136261
  for (let i = 0; i < text.length; i++) h = Math.imul(h ^ text.charCodeAt(i), 16777619)
  return h >>> 0
}
const cents = (value: number) => Math.round(value * 100 + Number.EPSILON * 100)
const money = (c: number) => (c / 100).toFixed(2)
/** Mesmo caminho de `economics._value`: 4 casas (como o cost_estimate) e depois o centavo. */
const value = (amount: number) => cents(Number(amount.toFixed(4)))

export class MockFailure extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message)
  }
}

/* ------------------------------------------------------- C · custo do kWh */

const ENERGY_COST: Record<string, string | null> = { [S[0].id]: '0.8500', [S[1].id]: '0.9200', [S[2].id]: null }
const FEE = '25.00'
/** Aluguel mensal por central (contrato); cada estação tem uma central vinculada há muito tempo. */
const CENTRAL_RENT = 99
const DAY = 86_400_000
const SP_OFFSET = 3 * 3_600_000 // São Paulo = UTC−3: meia-noite local às 03:00 UTC

function centralsOf(stationId: string): number {
  const station = S.find((s) => s.id === stationId)
  return station && screenPoint(station) ? 1 : 0
}

export function economics(stationId: string, notes = true): StationEconomics {
  const result: StationEconomics = {
    station_id: stationId,
    energy_cost_per_kwh: ENERGY_COST[stationId] ?? null,
    platform_fee_percent: FEE,
    fee_editable: false,
    currency: 'BRL',
    central_monthly_rent: CENTRAL_RENT.toFixed(2),
    centrals: centralsOf(stationId),
    rent_editable: false,
  }
  if (notes) {
    result.notes = [
      'Custo do kWh: informe o valor médio pago à distribuidora (R$/kWh). Vale para as próximas recargas; as anteriores mantêm o custo travado no início.',
      'A comissão da plataforma é definida em contrato e não pode ser alterada no painel.',
      'Aluguel mensal por central: definido em contrato, rateado pelos dias de vínculo no mês e descontado do repasse.',
    ]
  }
  return result
}

/**
 * `chargegrid_core.rent.accrual`: cada dia local cujo início está em [from, min(to, agora)) vale
 * aluguel mensal ÷ dias do mês; arredondado ao centavo por central e mês.
 */
export function rentAccrual(from: number, to: number, stationIds: string[], now = Date.now()) {
  const cutoff = Math.min(to, now)
  let day = Math.floor((from - SP_OFFSET) / DAY) * DAY + SP_OFFSET
  if (day < from) day += DAY
  const groups = new Map<string, CentralRentLine & { exact: number }>()
  for (; day < cutoff; day += DAY) {
    const local = new Date(day - SP_OFFSET)
    const year = local.getUTCFullYear()
    const monthIndex = local.getUTCMonth()
    const month = `${year}-${String(monthIndex + 1).padStart(2, '0')}`
    const daysInMonth = new Date(Date.UTC(year, monthIndex + 1, 0)).getUTCDate()
    for (const stationId of stationIds) {
      const station = S.find((s) => s.id === stationId)
      const screen = station ? screenPoint(station) : undefined
      if (!station || !screen) continue
      const key = `${stationId}|${month}`
      const group = groups.get(key) ?? {
        station_id: stationId, station_name: station.name, device_id: `central-${screen.id}`, central: screen.public_code,
        month, days: 0, days_in_month: daysInMonth, monthly_amount: CENTRAL_RENT.toFixed(2), amount: '0.00', exact: 0,
      }
      group.days += 1
      group.exact += CENTRAL_RENT / daysInMonth
      groups.set(key, group)
    }
  }
  const lines: CentralRentLine[] = [...groups.values()]
    .map(({ exact, ...line }) => ({ ...line, amount: money(cents(exact)) }))
    .sort((a, b) => a.station_name.localeCompare(b.station_name) || a.month.localeCompare(b.month))
  const byStation: Record<string, number> = {}
  lines.forEach((line) => (byStation[line.station_id ?? ''] = (byStation[line.station_id ?? ''] ?? 0) + cents(Number(line.amount))))
  const total = Object.values(byStation).reduce((t, v) => t + v, 0)
  return { lines, byStation, total: lines.length ? total : null, centrals: new Set(lines.map((l) => l.device_id)).size }
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
  station.kiosk_mode ??= index === 0
  for (const connector of station.connectors) {
    connector.kiosk_in_use ??= false
    connector.power_limit_kw ??= null
    // Sem teto no posto: a efetiva é o pedido (nominal ou o limite do vendedor), como `power.allocate`.
    connector.effective_power_kw ??= requestedKw(connector).toFixed(3)
    // Pedido do totem aberto: o ponto aparece ocupado ("Em uso no totem"), como `availability()` da API.
    if (index === 0 && connector.public_code === 'CG-003' && connector.availability_status === 'available') {
      Object.assign(connector, { available: false, availability_status: 'occupied', kiosk_in_use: true })
    }
  }
  decorateChargers(station)
  station.overstay = stationOverstay(station.id)
}
S.forEach(decorateStation)

/* ------------------------------------------- estação (central) × carregadores */

export function linkStateOf(connector: Connector): ChargerLinkState {
  return LINK_STATE.get(connector.id) ?? LINK_SEED[connector.public_code] ?? 'online'
}

export function setLinkState(connectorId: string, state: ChargerLinkState): void {
  LINK_STATE.set(connectorId, state)
}

function screenDeviceId(station: Station): string {
  return `d0${String(S.indexOf(station) + 1).padStart(3, '0')}-6b1e-4c7a-9d2f-00000000a11e`
}

/** A central do posto fica no primeiro ponto (o do QR); os outros são carregadores adicionais dela. */
function screenPoint(station: Station): Connector | undefined {
  return station.connectors.find((c) => !c.retired)
}

/**
 * `charger_link` do dono (`chargegrid_core.chargers.link.owner_block`): online com última leitura
 * agora e a potência lida (a efetiva enquanto carrega, 0 parado); offline com a última leitura de
 * 3 h atrás; pending sem leitura (a central ainda não confirmou o endereço).
 */
export function chargerLink(connector: Connector, now: number = Date.now()): ChargerLink | null {
  const address = connector.charger_address
  if (address === null || address === undefined) return null
  const link = linkStateOf(connector)
  const charging = connector.availability_status === 'charging'
  const delivered = charging ? (deliveredKw(connector) ?? Number(connector.effective_power_kw ?? connector.power_kw)) : 0
  const measured = link === 'online' ? Math.round(delivered * 1000) : null
  return {
    model: CHARGER_MODEL, transport: CHARGER_TRANSPORT, address, host: chargerHost(address), label: CHARGER_LABEL, simulated: true,
    link,
    last_online_at: link === 'online' ? new Date(now - 3 * SECOND).toISOString() : link === 'offline' ? new Date(now - 3 * MOCK_HOUR).toISOString() : null,
    measured_power_w: measured,
    reported:
      link === 'pending'
        ? null
        : link === 'online'
          ? { model: CHARGER_MODEL, transport: CHARGER_TRANSPORT, address, link }
          : { model: 'esp32_bench', transport: 'simulated', address, link },
  }
}

/**
 * Tela, carregadores e disponibilidade como a API: `screen_online`, `screens`, e em cada ponto
 * `online` (= carregador respondendo), `screen_online`, `unavailable_reason`, `charger_link` e
 * `screen`. Idempotente (o horário da última leitura acompanha o relógio a cada GET).
 */
export function decorateChargers(station: Station, now: number = Date.now()): Station {
  ensureChargerAddresses(station)
  const home = screenPoint(station)
  if (!home) {
    station.screen_online = null
    station.screens = []
    return station
  }
  const deviceId = screenDeviceId(station)
  const lastSeen = new Date(now - 3 * SECOND).toISOString()
  const screenOnline = !SCREEN_OFFLINE.has(station.id)
  const members = station.connectors.filter((c) => !c.retired)
  station.screen_online = screenOnline
  station.screens = [
    {
      device_id: deviceId, connector_id: home.id, public_code: home.public_code, online: screenOnline, last_seen: lastSeen,
      firmware_version: SCREEN_FIRMWARE, multi_charger: true, charger_ids: members.map((c) => c.id),
    },
  ]
  for (const connector of members) {
    connector.charger_link = chargerLink(connector, now)
    const link = connector.charger_link?.link
    connector.screen_online = screenOnline
    connector.online = screenOnline && link === 'online'
    connector.unavailable_reason = !screenOnline ? 'screen_offline' : link === 'online' ? null : 'charger_offline'
    if (connector.unavailable_reason && connector.active && !['offline', 'disabled'].includes(connector.availability_status ?? '')) {
      Object.assign(connector, { available: false, availability_status: 'offline' })
    }
    connector.screen = {
      device_id: deviceId, connector_id: home.id, public_code: home.public_code, online: screenOnline, last_seen: lastSeen,
      firmware_version: SCREEN_FIRMWARE, role: connector.id === home.id ? 'screen' : 'charger', multi_charger: true,
    }
  }
  return station
}

/**
 * Todo ponto tem endereço: quem ainda não tem (seed ou ponto novo) recebe o menor livre do
 * posto, na ordem de criação (1, 2, 3…), como a API na criação do posto / do ponto.
 */
export function ensureChargerAddresses(station: Station): Station {
  for (const connector of station.connectors) {
    if (connector.charger_address === undefined || connector.charger_address === null) {
      connector.charger_address = nextFreeChargerAddress(station.connectors.map((c) => c.charger_address))
    }
    connector.charger_link = chargerLink(connector)
  }
  return station
}

/** PATCH `charger_address` como a API: inteiro 1–247 (nunca vazio), único por posto (409 `charger_address_taken`). */
export function setChargerAddress(connectorId: string, value: unknown): Connector {
  const station = S.find((s) => s.connectors.some((c) => c.id === connectorId))
  const connector = station?.connectors.find((c) => c.id === connectorId)
  if (!station || !connector) throw new MockFailure(404, 'not_found', 'Ponto não encontrado')
  if (value === null || value === undefined) throw new MockFailure(422, 'invalid_charger_address', CHARGER_ADDRESS_EMPTY)
  if (typeof value !== 'number' || !Number.isInteger(value) || value < CHARGER_MIN_ADDRESS || value > CHARGER_MAX_ADDRESS) {
    throw new MockFailure(422, 'invalid_charger_address', CHARGER_ADDRESS_INVALID)
  }
  if (value === connector.charger_address) return connector // mesmo endereço: nada muda
  const other = station.connectors.find((c) => c.id !== connectorId && c.charger_address === value)
  if (other) {
    throw new MockFailure(409, 'charger_address_taken', `O carregador ${value} já está ligado ao ponto ${other.public_code} deste posto. Escolha outro endereço.`)
  }
  connector.charger_address = value
  // Endereço novo: a central ainda não confirmou o carregador nele.
  setLinkState(connector.id, 'pending')
  decorateChargers(station)
  return connector
}

/** Mensagens das recusas do POST "Adicionar carregador" (iguais à API). */
export const SCREEN_REQUIRED_MESSAGE = 'Este ponto não tem central vinculada'
export const ADDRESS_FULL_MESSAGE = 'Posto sem endereço de carregador livre (1 a 247)'

/** Códigos de carregadores removidos: como na API (o ponto fica no histórico), não voltam a ser usados. */
const REMOVED_CODES: string[] = []

function nextPublicCode(): string {
  const used = [...S.flatMap((s) => s.connectors.map((c) => c.public_code)), ...REMOVED_CODES].map((code) => Number(/(\d+)$/.exec(code)?.[1] ?? 0))
  return `CG-${String(Math.max(0, ...used) + 1).padStart(3, '0')}`
}

/**
 * `POST /connectors/{id}/chargers`: próximo carregador da central do ponto (a do próprio ponto ou a
 * central de quem ele é carregador adicional): próximo endereço livre, mesmo tipo/potência/preço/
 * duração do ponto da central, inativo, aguardando a central. 409 `screen_required`/`charger_address_full`.
 */
export function addCharger(connectorId: string): Connector {
  const station = S.find((s) => s.connectors.some((c) => c.id === connectorId))
  const connector = station?.connectors.find((c) => c.id === connectorId)
  if (!station || !connector) throw new MockFailure(404, 'not_found', 'Ponto não encontrado')
  if (!connector.screen) throw new MockFailure(409, 'screen_required', SCREEN_REQUIRED_MESSAGE)
  const home = station.connectors.find((c) => c.id === connector.screen!.connector_id) ?? connector
  const address = nextFreeChargerAddress(station.connectors.map((c) => c.charger_address))
  if (address === null) throw new MockFailure(409, 'charger_address_full', ADDRESS_FULL_MESSAGE)
  const serial = station.connectors.length + S.reduce((sum, s) => sum + s.connectors.length, 0)
  const fresh: Connector = {
    id: `c1${Date.now().toString(16).slice(-4)}-6b1e-4c7a-9d2f-${serial.toString(16).padStart(12, '0')}`,
    station_id: station.id, public_code: nextPublicCode(), connector_type: home.connector_type, power_kw: home.power_kw,
    price_per_kwh: home.price_per_kwh, max_duration_minutes: home.max_duration_minutes, active: false, control_version: 1,
    available: false, availability_status: 'disabled', reserved_until: null, kiosk_in_use: false, online: false,
    physical_state: 'idle', retired: false, power_limit_kw: null, effective_power_kw: requestedKw(home).toFixed(3),
    charger_address: address,
  }
  station.connectors.push(fresh)
  setLinkState(fresh.id, 'pending')
  decorateChargers(station)
  return fresh
}

/** Mensagens das recusas do DELETE "Remover carregador" (iguais à API). */
export const SCREEN_CHARGER_MESSAGE = 'Este é o carregador da própria central; ele não pode ser removido.'
export const REMOVE_BUSY_MESSAGE = 'Encerre reservas/recargas antes de remover o carregador'

/**
 * `DELETE /connectors/{id}` (204): o carregador adicional sai da estação (some das listagens e da
 * central) e o endereço fica livre para o próximo "Adicionar carregador". 409 `screen_charger` (o
 * ponto da própria central), 409 `point_busy` (recarga/reserva ativa ou pedido do totem); 404.
 */
export function removeCharger(connectorId: string): void {
  const station = S.find((s) => s.connectors.some((c) => c.id === connectorId))
  const connector = station?.connectors.find((c) => c.id === connectorId)
  if (!station || !connector || connector.retired) throw new MockFailure(404, 'not_found', 'Ponto não encontrado')
  if (screenPoint(station)?.id === connector.id) throw new MockFailure(409, 'screen_charger', SCREEN_CHARGER_MESSAGE)
  if (connector.kiosk_in_use || ['charging', 'reserved', 'reconciling'].includes(connector.availability_status ?? '')) {
    throw new MockFailure(409, 'point_busy', REMOVE_BUSY_MESSAGE)
  }
  station.connectors.splice(station.connectors.indexOf(connector), 1)
  REMOVED_CODES.push(connector.public_code)
  LINK_STATE.delete(connector.id)
  decorateChargers(station)
}

/** Mensagens das recusas do DELETE "Remover estação" (iguais à API). */
export const STATION_BUSY_MESSAGE = 'Há recarga, reserva ou pedido do totem em andamento. Encerre antes de remover.'
export const CENTRAL_ONLINE_MESSAGE =
  'Restaure a central (Dados da estação → Restaurar) antes de remover a estação: ela volta ao QR de fábrica e pode ser usada em outro posto.'

export function setScreenOnline(stationId: string, online: boolean): void {
  if (online) SCREEN_OFFLINE.delete(stationId)
  else SCREEN_OFFLINE.add(stationId)
}

/**
 * `DELETE /stations/{id}` (204): o posto sai das listas, do painel e dos alertas; o histórico fica.
 * 409 `station_busy` (recarga/reserva/pedido do totem), 409 `central_online` (central ligada:
 * restaurar antes); 404 (inexistente ou já removido).
 */
export function removeStation(stationId: string): void {
  const station = S.find((s) => s.id === stationId)
  if (!station || data.isRemovedStation(stationId)) throw new MockFailure(404, 'not_found', 'Posto não encontrado')
  if (station.connectors.some((c) => c.kiosk_in_use || ['charging', 'reserved', 'reconciling'].includes(c.availability_status ?? ''))) {
    throw new MockFailure(409, 'station_busy', STATION_BUSY_MESSAGE)
  }
  decorateChargers(station)
  if (station.screen_online) throw new MockFailure(409, 'central_online', CENTRAL_ONLINE_MESSAGE)
  station.active = false
  for (const connector of station.connectors) Object.assign(connector, { active: false, available: false, availability_status: 'disabled' })
  data.REMOVED_STATIONS.add(stationId)
}

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
  returned > 0 ? `Cobrado ${formatCurrency(charged / 100)} · Devolvido ${formatCurrency(returned / 100)}` : `Cobrado ${formatCurrency(charged / 100)}`

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
  // Pagamento automático (sem pré-pagamento obrigatório): parte das recargas tem pagamento registrado.
  if (h % 100 >= 35) return null
  if (session.status === 'failed') return null
  const energy = cents(Number(session.cost_estimate ?? 0))
  const amount = Math.max(2000, Math.ceil((energy + overstayCents + 1000) / 1000) * 1000)
  const station = S.find((s) => s.id === session.station_id)
  // Canal: app, QR do painel (/pay/k) ou pedido do totem (só com o totem ligado); o totem de conta em
  // Modo apresentação paga simulado (acerto local; o rótulo é o mesmo da API, sem marca de ambiente).
  const kiosk = h % 7 === 0 || (station?.kiosk_mode === true && h % 4 === 1)
  const channel = !kiosk ? 'app' : station?.kiosk_mode && h % 2 === 1 ? 'kiosk_totem' : 'kiosk_qr'
  const simulated = channel === 'kiosk_totem' && h % 3 !== 0
  const method = simulated ? 'simulated' : h % 5 === 0 ? 'pix' : 'card'
  const base = {
    id: `pay-${session.id.slice(0, 8)}`, environment: 'test', provider: simulated ? 'simulated' : 'stripe', origin: kiosk ? 'kiosk' : 'app', channel,
    method, currency: 'BRL', amount: money(amount),
  }
  if (session.status === 'charging') return { ...base, status: 'in_use', status_label: 'Pago · em uso', settlement: null }
  const charged = energy + overstayCents
  const returned = amount - charged
  return {
    ...base,
    status: 'completed',
    status_label: PAID_LABEL(charged, returned),
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
  'Custo da energia = kWh × custo do kWh informado pelo dono, travado no início de cada recarga. Não inclui custos fixos (equipamento, manutenção) nem tarifa de demanda (R$/kW).',
  'Sessões encerradas (concluídas ou interrompidas) com energia positiva, atribuídas à data de término (horário de São Paulo). Valores estimados até a confirmação do pagamento; a diferença do valor capturado (perdoado ou não cobrado) aparece como ajuste do pagamento.',
  'Aluguel das centrais: valor mensal por central (definido em contrato) rateado por dia de vínculo no horário de São Paulo — valor mensal ÷ dias do mês por dia em que a central esteve vinculada. É descontado do repasse (folha) e do resultado; a margem de contribuição por recarga não muda.',
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
  const adjustment = revenueTotal - revenue - overstay
  const margin = energyCost === null ? null : ownerNet - energyCost
  return {
    session_id: session.id, ended_at: session.ended_at, station_id: session.station_id, station_name: session.station_name, public_code: session.public_code,
    source: session.source, energy_kwh: kwh.toFixed(3), connector_base_per_kwh: connectorBase.toFixed(4), base_per_kwh: base.toFixed(4),
    demand_multiplier: multiplier.toFixed(2), price_per_kwh: price.toFixed(4), coupon_code: session.discount_percent ? 'VERAO10' : null,
    discount_percent: session.discount_percent, list_value: money(list), schedule_effect: money(atBase - list), speed_effect: null, demand_effect: money(gross - atBase),
    gross: money(gross), discount: money(gross - revenue), revenue: money(revenue), overstay_revenue: overstay ? money(overstay) : null,
    revenue_total: money(revenueTotal), payment_adjustment: money(adjustment), revenue_basis: payment ? 'captured' : 'estimated', payment_environment: session.payment ? 'test' : null,
    platform_fee_percent: FEE, platform_fee: money(platformFee), provider_fee: providerFee === null ? null : money(providerFee), owner_net: money(ownerNet),
    energy_cost_per_kwh: cost ?? null, cost_basis: cost ? 'snapshot' : 'missing', energy_cost: energyCost === null ? null : money(energyCost),
    margin: margin === null ? null : money(margin), margin_percent: margin !== null && revenueTotal ? ((margin / revenueTotal) * 100).toFixed(1) : null,
  }
}

const sumC = (rows: MarginRow[], key: keyof MarginRow) => rows.reduce((total, row) => total + (row[key] === null ? 0 : cents(Number(row[key]))), 0)
const anyValue = (rows: MarginRow[], key: keyof MarginRow) => rows.some((row) => row[key] !== null)

function totalsOf(rows: MarginRow[], rentCents: number | null = null, centrals = 0) {
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
    speed_effect: null,
    payment_adjustment: money(sumC(rows, 'payment_adjustment')),
    central_rent: rentCents === null ? null : money(rentCents),
    centrals,
    owner_net_after_rent: money(sumC(rows, 'owner_net') - (rentCents ?? 0)),
    result: margin === null ? null : money(margin - (rentCents ?? 0)),
    result_percent: margin !== null && revenueTotal ? (((margin - (rentCents ?? 0)) / revenueTotal) * 100).toFixed(1) : null,
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

function windowOf(params: URLSearchParams) {
  const from = Date.parse(params.get('from') ?? '') || Date.now() - 7 * 86_400_000
  const to = Date.parse(params.get('to') ?? '') || Date.now()
  return { from, to }
}

function rentOf(params: URLSearchParams) {
  const { from, to } = windowOf(params)
  const station = params.get('station_id')
  return rentAccrual(from, to, S.filter((s) => !station || s.id === station).map((s) => s.id))
}

export function rentCsv(params: URLSearchParams): string {
  const header = ['Posto', 'Central (ponto)', 'Mês', 'Dias cobrados', 'Dias do mês', 'Aluguel mensal (R$)', 'Valor (R$)']
  const lines = rentOf(params).lines.map((l) => [l.station_name, l.central, l.month, l.days, l.days_in_month, l.monthly_amount, l.amount].join(','))
  return [header.join(','), ...lines].join('\r\n') + '\r\n'
}

export function marginReport(params: URLSearchParams): MarginReport {
  const rows = marginRows(params)
  const rent = rentOf(params)
  const totals = totalsOf(rows, rent.total, rent.centrals)
  const station = params.get('station_id')
  const surge = rows.filter((r) => Number(r.demand_multiplier) > 1)
  const coupons = rows.filter((r) => r.discount_percent)
  const sources: Record<string, number> = {}
  rows.forEach((r) => (sources[r.source ?? 'unknown'] = (sources[r.source ?? 'unknown'] ?? 0) + 1))
  const byStation = S.filter((s) => !station || s.id === station)
    .map((s) => ({
      ...totalsOf(rows.filter((r) => r.station_id === s.id), rent.total === null ? null : (rent.byStation[s.id] ?? 0), centralsOf(s.id)),
      station_id: s.id,
      station_name: s.name,
    }))
    .filter((entry) => entry.sessions || entry.central_rent !== null)
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
    stations: data.currentStations().filter((s) => !station || s.id === station).map((s) => ({ ...economics(s.id, false), station_name: s.name })),
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
    central_rent: rent.total === null ? null : { total: money(rent.total), centrals: rent.centrals, lines: rent.lines },
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
  const rent = rentOf(params)
  const t = totalsOf(marginRows(params), rent.total, rent.centrals)
  const ascii = (text: string) => text.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[()\\]/g, '')
  const lines = [
    'ChargeGrid - Resultado do posto (dados de exemplo)',
    'Receita bruta nao e lucro.',
    `Receita bruta: R$ ${t.gross}`,
    `Descontos e cupons: - R$ ${t.discount}`,
    `Receita cobrada: R$ ${t.revenue_total}`,
    `Comissao da plataforma (25%): - R$ ${t.platform_fee}`,
    `Repasse: R$ ${t.owner_net}`,
    ...(t.central_rent === null ? [] : [`Aluguel das centrais: - R$ ${t.central_rent}`, `Repasse liquido: R$ ${t.owner_net_after_rent}`]),
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

/* -------------------------------------------------------------- potência */

interface PowerSite {
  rebalance: boolean
  /** Informado pelo dono (`null` = padrão pelo pico estimado). */
  limit: number | null
  /** Margem ESTIMADA da loja (`null` = 14–22 kW). */
  storeMin: number | null
  storePeak: number | null
  /** Máximo dos carregadores (`null` = sem teto próprio). */
  cap: number | null
  notify: boolean
  applied: Record<string, number>
  pendingSince: Record<string, number>
  decisions: PowerDecision[]
  lastKey: string
}

const site = (limit: number | null, storeMin: number | null, storePeak: number | null): PowerSite => ({
  rebalance: true, limit, storeMin, storePeak, cap: null, notify: false, applied: {}, pendingSince: {}, decisions: [], lastKey: '',
})

/** Rebalanceamento ligado por padrão; Villa Lobos nos padrões, Marginal e Villa Olímpia com a estimativa
 * que a migração d8b3f6a2c5e7 deu aos tipos antigos (supermercado grande limitado a 85 % de 150 kW;
 * restaurante pequeno). */
const POWER: Record<string, PowerSite> = {
  [S[0].id]: site(null, null, null),
  [S[1].id]: site(150, 89.6, 127.5),
  [S[2].id]: site(null, 3.1, 18),
}

function storeEstimate(power: PowerSite): { min: number; peak: number; isDefault: boolean } {
  if (power.storePeak === null && power.storeMin === null) return { min: DEFAULT_STORE_MIN_KW, peak: DEFAULT_STORE_PEAK_KW, isDefault: true }
  const peak = power.storePeak ?? Math.max(DEFAULT_STORE_PEAK_KW, power.storeMin ?? 0)
  return { min: Math.min(power.storeMin ?? DEFAULT_STORE_MIN_KW, peak), peak, isDefault: false }
}

function effectiveLimit(power: PowerSite): { kw: number; isDefault: boolean } {
  return power.limit === null ? { kw: defaultSiteLimitKw(storeEstimate(power).peak), isDefault: true } : { kw: power.limit, isDefault: false }
}

/** Margem reservada para a loja: o pico ESTIMADO, fixo (nunca deixa menos de 1,4 kW do contratado). */
export function storeReserve(power: PowerSite): number {
  return Math.min(storeEstimate(power).peak, Math.max(0, Math.round((effectiveLimit(power).kw - FLOOR_KW) * 10) / 10))
}

const FLOOR = 1.4

deliveredKw = (connector) => {
  const station = S.find((s) => s.id === connector.station_id)
  const site = station ? POWER[station.id] : undefined
  if (!station || !site) return undefined
  return allocate(station, site, storeReserve(site)).allocations.find((a) => a.connector.id === connector.id)?.target
}
let decisionSeq = 1
const kwText = (value: number) => (Math.round(value * 10) / 10).toFixed(1).replace(/\.0$/, '').replace('.', ',')

interface Allocation {
  connector: Station['connectors'][number]
  target: number
  code: 'site' | 'charger' | 'paused' | 'fixed'
}

function allocate(station: Station, site: PowerSite, load: number) {
  const charging = station.connectors.filter((c) => c.availability_status === 'charging')
  const siteLeft = Math.max(0, Math.round((effectiveLimit(site).kw - load) * 10) / 10)
  const available = site.cap === null ? siteLeft : Math.min(siteLeft, site.cap)
  const requests = charging.map((c) => requestedKw(c))
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
  return { available, allocations, cars: charging.length }
}

function reasonFor(alloc: Allocation, site: PowerSite & { load: number }, cars: number) {
  const alone = cars === 1 ? 'só o seu carro está carregando' : `há ${cars} carros carregando`
  const kw = kwText(alloc.target)
  switch (alloc.code) {
    case 'site':
      return {
        text: `${kw} kW porque ${kwText(site.load)} kW dos ${kwText(effectiveLimit(site).kw)} kW contratados ficam reservados para a loja (estimativa) e ${alone}.`,
        short: `Contrat. ${kwText(effectiveLimit(site).kw)} - loja ${kwText(site.load)} kW`,
      }
    case 'paused':
      return { text: `Pausado: dos ${kwText(effectiveLimit(site).kw)} kW contratados, ${kwText(site.load)} kW ficam reservados para a loja (estimativa) e não sobra o mínimo de 1,4 kW para mais um carro.`, short: 'Pausado: sem capacidade' }
    case 'fixed':
      return { text: `${kw} kW: rebalanceamento desligado, vale a potência definida no início da recarga.`, short: 'Rebalanceamento desligado' }
    default:
      return { text: `${kw} kW, o máximo deste carregador (sobra potência: ${alone}).`, short: 'Máximo do carregador' }
  }
}

function record(site: PowerSite, trigger: string, available: number, allocations: Allocation[], exceeded: number) {
  const parts = allocations.map((a) => `${a.connector.public_code} ${kwText(a.target)} kW`).join(', ')
  const summary = allocations.length
    ? `Disponível ${kwText(available)} kW para ${allocations.length} carro(s): ${parts}.`
    : `Disponível ${kwText(available)} kW; nenhum carro carregando.`
  site.decisions.unshift({ id: decisionSeq++, created_at: new Date().toISOString(), trigger, available_kw: available.toFixed(1), exceeded_kw: exceeded.toFixed(1), summary })
  site.decisions.length = Math.min(site.decisions.length, 20)
}

/** Visão de `/stations/{id}/power`; o equipamento "confirma" ajustes ~1,2 s depois. */
export function power(stationId: string, trigger = 'initial'): StationPower {
  const station = S.find((s) => s.id === stationId)!
  const site = POWER[stationId]
  const now = Date.now()
  const load = storeReserve(site)
  const store = storeEstimate(site)
  const limit = effectiveLimit(site)
  const { available, allocations, cars } = allocate(station, site, load)
  const key = JSON.stringify([site.rebalance, limit.kw, load, site.cap, allocations.map((a) => a.target)])
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
  const exceeded = Math.max(0, envelope - available)
  if (key !== site.lastKey) {
    record(site, site.lastKey ? trigger : 'initial', available, allocations, exceeded)
    site.lastKey = key
  } else if (confirmed) {
    record(site, 'power_confirmed', available, allocations, exceeded)
  }
  return {
    station_id: stationId,
    rebalance_enabled: site.rebalance,
    site_limit_kw: limit.kw.toFixed(1),
    site_limit_default: limit.isDefault,
    site_limit_configured_kw: site.limit === null ? null : site.limit.toFixed(1),
    site_limit_default_kw: defaultSiteLimitKw(store.peak).toFixed(1),
    store_min_kw: store.min.toFixed(1),
    store_peak_kw: store.peak.toFixed(1),
    store_reserve_kw: load.toFixed(1),
    store_estimate_default: store.isDefault,
    store_estimate_label: 'ESTIMATIVA',
    building_load_kw: load.toFixed(1),
    power_limit_notify: site.notify,
    station_cap_kw: site.cap === null ? null : site.cap.toFixed(3),
    connectors_total_kw: station.connectors.filter((c) => c.active !== false && !c.retired).reduce((t, c) => t + Number(c.power_kw), 0).toFixed(3),
    charger_floor_kw: FLOOR_KW.toFixed(3),
    chargers_floor_total_kw: (station.connectors.filter((c) => c.active !== false && !c.retired).length * FLOOR_KW || FLOOR_KW).toFixed(3),
    available_kw: available.toFixed(1),
    allocated_kw: allocations.reduce((t, a) => t + a.target, 0).toFixed(1),
    envelope_kw: envelope.toFixed(1),
    exceeded_kw: exceeded.toFixed(1),
    cars,
    points: station.connectors.map((connector) => {
      const alloc = allocations.find((a) => a.connector.id === connector.id)
      const applied = alloc ? site.applied[connector.id] : null
      const reason = alloc ? reasonFor(alloc, { ...site, load }, cars) : null
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

const decimalOrNull = (value: string | null | undefined, message: string): number | null => {
  if (value === null || value === undefined) return null
  const number = Number(value)
  if (!Number.isFinite(number) || number < 0) throw new MockFailure(422, 'invalid_store_estimate', message)
  return Math.round(number * 10) / 10
}

/** `PUT power-site` parcial, como `power.service.set_site`: valida o estado final; `null` volta ao padrão. */
export function putPowerSite(
  stationId: string,
  body: { site_limit_kw?: string | null; rebalance_enabled?: boolean; store_min_kw?: string | null; store_peak_kw?: string | null; max_power_kw?: string | null; power_limit_notify?: boolean },
): StationPower {
  const current = POWER[stationId]
  const site: PowerSite = { ...current }
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
  if ('store_min_kw' in body) site.storeMin = decimalOrNull(body.store_min_kw, 'Informe a estimativa da loja em kW.')
  if ('store_peak_kw' in body) {
    site.storePeak = decimalOrNull(body.store_peak_kw, 'Informe a estimativa da loja em kW.')
    trigger = 'store_estimate_changed'
  }
  if ('max_power_kw' in body) {
    const cap = body.max_power_kw === null || body.max_power_kw === undefined ? null : Number(body.max_power_kw)
    const station = S.find((s) => s.id === stationId)!
    const floors = station.connectors.filter((c) => c.active !== false && !c.retired).length * FLOOR_KW
    if (cap !== null && (!Number.isFinite(cap) || cap <= 0 || cap < floors)) throw new MockFailure(422, 'invalid_power_limit', `O limite do posto precisa ser de pelo menos ${kwText(floors)} kW.`)
    site.cap = cap === null ? null : Math.round(cap * 10) / 10
    trigger = 'station_cap_changed'
  }
  for (const key of ['rebalance_enabled', 'power_limit_notify'] as const) {
    if (!(key in body)) continue
    if (typeof body[key] !== 'boolean') throw new MockFailure(422, 'null_not_allowed', 'Campo não aceita null')
  }
  if ('rebalance_enabled' in body) {
    site.rebalance = body.rebalance_enabled!
    trigger = 'request_changed'
  }
  if ('power_limit_notify' in body) site.notify = body.power_limit_notify!
  if (site.storeMin !== null && site.storePeak !== null && site.storeMin > site.storePeak) throw new MockFailure(422, 'invalid_store_estimate', 'O mínimo estimado da loja não pode passar do pico.')
  const left = effectiveLimit(site).kw - storeEstimate(site).peak
  if (left < FLOOR_KW) throw new MockFailure(422, 'invalid_store_estimate', `O pico estimado da loja deixa ${kwText(Math.max(0, left))} kW para os carregadores; o mínimo para carregar um carro é 1,4 kW.`)
  Object.assign(current, site)
  return power(stationId, trigger)
}
