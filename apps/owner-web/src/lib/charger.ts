/**
 * Estação = a TELA (painel ESP32-S3); Carregadores = os pontos que ela comanda. Cada ponto (na API,
 * `connector`) É um carregador GoodWe HCA G2 (simulado) com endereço Modbus (`charger_address`,
 * 1–247, único por posto, automático e editável; nunca vazio). Carregador offline só derruba aquele
 * ponto: a estação continua online enquanto a tela tiver contato. Mesmos textos do app e da API
 * (`chargegrid_core.chargers.link`).
 */
import { ApiError } from '../api/client'
import type { ChargerLink, ChargerLinkState, ChargerScreen, Connector, Station } from '../api/types'
import type { Tone } from './labels'
import { formatPower, formatRelative } from './format'

export const CHARGER_MODEL = 'goodwe_hca_g2'
export const CHARGER_TRANSPORT = 'modbus_tcp'
export const CHARGER_LABEL = 'GoodWe HCA G2'
/** O único HCA ligado hoje é o simulador (ESP32 + relé): a etiqueta diz isso (`STATUS_LABEL` do core). */
export const CHARGER_STATUS_LABEL = `${CHARGER_LABEL} (simulado)`
export const CHARGER_MIN_ADDRESS = 1
export const CHARGER_MAX_ADDRESS = 247

/** Mensagens da API (422 `invalid_charger_address`), reaproveitadas na validação do campo. */
export const CHARGER_ADDRESS_EMPTY = 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247'
export const CHARGER_ADDRESS_INVALID = 'Endereço do carregador deve ser um número inteiro de 1 a 247'

/** `pending` = a tela (online) ainda não confirmou este endereço. */
export const CHARGER_WAITING_TEXT = 'aguardando a tela'

export const CHARGER_LINK_TEXT: Record<ChargerLinkState, string> = {
  online: 'online',
  offline: 'offline',
  pending: CHARGER_WAITING_TEXT,
}

/** Selo do carregador no painel. */
export const CHARGER_STATE_META: Record<ChargerLinkState, { label: string; tone: Tone }> = {
  online: { label: 'Online', tone: 'green' },
  offline: { label: 'Offline', tone: 'red' },
  pending: { label: 'Aguardando a tela', tone: 'amber' },
}

/** Tipos de conector oferecidos no cartão (o atual entra na lista se for outro). */
export const CONNECTOR_TYPES = ['CCS2', 'Tipo 2', 'CHAdeMO', 'GB/T'] as const

export function chargerHost(address: number): string {
  return `cg-hca-${address}.local`
}

/** Linha de configuração do firmware do carregador (ESP do simulador HCA). */
export function cgAddrHint(address: number): string {
  return `No ESP do carregador: CG_ADDR = ${address}`
}

/** Menor endereço livre do posto (1, 2, 3…), ignorando vazios; posto cheio → `null`. */
export function nextFreeChargerAddress(used: Iterable<number | null | undefined>): number | null {
  const taken = new Set<number>()
  for (const value of used) if (typeof value === 'number') taken.add(value)
  for (let address = CHARGER_MIN_ADDRESS; address <= CHARGER_MAX_ADDRESS; address++) {
    if (!taken.has(address)) return address
  }
  return null
}

function isLinkState(value: unknown): value is ChargerLinkState {
  return value === 'online' || value === 'offline' || value === 'pending'
}

/** `Carregador 1 · GoodWe HCA G2 (simulado) · online` (`offline`, `aguardando a tela`); vazio sem bloco (= `status_text` do core). */
export function chargerStatusText(link: ChargerLink | null | undefined): string {
  if (!link || link.address === null || link.address === undefined) return ''
  const state = isLinkState(link.link) ? CHARGER_LINK_TEXT[link.link] : CHARGER_WAITING_TEXT
  const label = link.simulated === false ? (link.label ?? CHARGER_LABEL) : `${link.label ?? CHARGER_LABEL} (simulado)`
  return `Carregador ${link.address} · ${label} · ${state}`
}

/**
 * Estado do carregador: o `charger_link.link` do dono; sem bloco (API antiga/parcial), o `online`
 * do ponto. `null` quando não há nada para mostrar.
 */
export function chargerState(connector: Pick<Connector, 'charger_link' | 'online'>): ChargerLinkState | null {
  const link = connector.charger_link
  if (link) return isLinkState(link.link) ? link.link : 'pending'
  if (connector.online === undefined) return null
  return connector.online ? 'online' : 'offline'
}

/** Potência lida do carregador (W) em kW: `53,6 kW`. */
export function formatMeasuredPower(watts: number | null | undefined): string | null {
  if (watts === null || watts === undefined || !Number.isFinite(watts)) return null
  return formatPower(Math.round(watts / 100) / 10)
}

/**
 * Leitura do carregador numa linha: `última leitura agora · lendo 7,2 kW`, `última leitura há 3 h`,
 * `sem leitura ainda`; aguardando a tela sem leitura: vazio (o estado já diz tudo).
 */
export function chargerReadingText(link: ChargerLink | null | undefined, now: Date = new Date()): string {
  if (!link) return ''
  const parts: string[] = []
  if (link.last_online_at) parts.push(`última leitura ${formatRelative(link.last_online_at, now)}`)
  else if (link.link !== 'pending') parts.push('sem leitura ainda')
  const power = link.link === 'online' ? formatMeasuredPower(link.measured_power_w) : null
  if (power) parts.push(`lendo ${power}`)
  return parts.join(' · ')
}

/** Papel do ponto na tela: o ponto da própria tela (QR) ou um carregador adicional. */
export function screenRoleText(screen: ChargerScreen): string {
  return screen.role === 'screen' ? 'Este ponto é a tela' : `Carregador adicional da tela ${screen.public_code}`
}

/* ------------------------------------------------------------------ estação */

export type StationScreenState = 'online' | 'offline' | 'none'

export const STATION_SCREEN_META: Record<StationScreenState, { label: string; tone: Tone }> = {
  online: { label: 'Estação online', tone: 'green' },
  offline: { label: 'Estação offline', tone: 'red' },
  none: { label: 'Sem tela', tone: 'gray' },
}

/**
 * Status da estação = o da TELA (`station.screen_online`; `null` = posto sem tela). API antiga
 * (sem o campo): online se algum ponto responde.
 */
export function stationScreenState(station: Pick<Station, 'screen_online' | 'connectors'>): StationScreenState {
  if (station.screen_online === true) return 'online'
  if (station.screen_online === false) return 'offline'
  if (station.screen_online === null) return 'none'
  const points = station.connectors.filter((c) => !c.retired)
  if (!points.length) return 'none'
  return points.some((c) => c.online) ? 'online' : 'offline'
}

/**
 * Carregadores publicados sem resposta com a tela online (só eles ficam indisponíveis). Inativos
 * (ex.: recém-adicionado, aguardando a tela) não entram: o motorista nem os vê.
 */
export function offlineChargers(station: Pick<Station, 'screen_online' | 'connectors'>): Connector[] {
  if (stationScreenState(station) !== 'online') return []
  return station.connectors.filter(
    (c) =>
      !c.retired &&
      c.active !== false &&
      (c.unavailable_reason === 'charger_offline' || (c.unavailable_reason === undefined && chargerState(c) === 'offline')),
  )
}

export function chargersLabel(count: number): string {
  return `${count} ${count === 1 ? 'carregador' : 'carregadores'}`
}

/** `3 carregadores · 2 online`. */
export function stationChargerSummary(station: Pick<Station, 'connectors'>): string {
  const points = station.connectors.filter((c) => !c.retired)
  const online = points.filter((c) => chargerState(c) === 'online').length
  return `${chargersLabel(points.length)} · ${online} online`
}

/**
 * Linha da estação: o status é o da TELA; carregador offline aparece à parte (não derruba a estação).
 * `Estação online · 2 de 4 carregadores em uso · carregador CG-007 offline`.
 */
export function stationSummary(station: Station): { line: string; tone: 'green' | 'amber' | 'red' | 'gray' } {
  const points = station.connectors.filter((c) => !c.retired)
  if (!station.active) return { line: 'Inativa · oculta para motoristas', tone: 'gray' }
  if (!points.length) return { line: 'Sem carregadores vinculados', tone: 'amber' }
  const screen = stationScreenState(station)
  if (screen === 'offline') return { line: 'Estação offline · tela sem contato', tone: 'red' }
  if (screen === 'none') return { line: 'Sem tela vinculada', tone: 'amber' }
  const busy = points.filter((c) => ['charging', 'occupied', 'reserved'].includes(c.availability_status ?? '')).length
  const free = points.filter(
    (c) =>
      c.active !== false &&
      c.online !== false &&
      !c.unavailable_reason &&
      (c.availability_status == null ? c.available === true : c.availability_status === 'available'),
  ).length
  const offline = offlineChargers(station)
  const faults = points.filter((c) => c.availability_status === 'fault').length
  const parts = ['Estação online']
  if (busy) parts.push(`${busy} de ${points.length} carregadores em uso`)
  parts.push(`${chargersLabel(free)} ${free === 1 ? 'livre' : 'livres'}`)
  if (offline.length === 1) parts.push(`carregador ${offline[0].public_code} offline`)
  else if (offline.length) parts.push(`${offline.length} carregadores offline`)
  if (faults) parts.push(`${faults} com falha`)
  return { line: parts.join(' · '), tone: offline.length || faults ? 'amber' : 'green' }
}

/**
 * Ponto usado no POST "Adicionar carregador": o da própria tela (`screen.role == 'screen'`), senão
 * qualquer ponto com tela; sem tela, o primeiro (a API responde 409 `screen_required`).
 */
export function addChargerTarget(station: Pick<Station, 'connectors'>): Connector | null {
  const points = station.connectors.filter((c) => !c.retired)
  return points.find((c) => c.screen?.role === 'screen') ?? points.find((c) => c.screen) ?? points[0] ?? null
}

export const SCREEN_REQUIRED_TEXT = 'Esta estação não tem tela vinculada. Vincule a tela pelo QR no app ChargeGrid e tente de novo.'
export const ADDRESS_FULL_TEXT = 'Todos os endereços de carregador (1 a 247) já estão em uso nesta estação.'

/** Mensagem do erro do POST "Adicionar carregador" (409 `screen_required` / `charger_address_full`). */
export function addChargerErrorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.code === 'screen_required') return SCREEN_REQUIRED_TEXT
    if (error.code === 'charger_address_full') return ADDRESS_FULL_TEXT
    return error.message
  }
  return 'Não foi possível adicionar o carregador. Tente novamente.'
}

/** Endereço digitado → inteiro 1–247. Vazio é erro: todo ponto é um carregador. */
export function validateChargerAddress(text: string): { value?: number; error?: string } {
  const raw = text.trim()
  if (!raw) return { error: CHARGER_ADDRESS_EMPTY }
  if (!/^\d+$/.test(raw)) return { error: CHARGER_ADDRESS_INVALID }
  const value = Number(raw)
  if (value < CHARGER_MIN_ADDRESS || value > CHARGER_MAX_ADDRESS) return { error: CHARGER_ADDRESS_INVALID }
  return { value }
}
