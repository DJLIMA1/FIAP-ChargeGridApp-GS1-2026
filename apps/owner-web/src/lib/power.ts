/**
 * Seção Potência do posto (mesmas regras da tela Potência do app, `services/site_power.py`, e da API,
 * `chargegrid_core.site_load`/`power`): limite contratado efetivo (o do dono ou o padrão do tipo/porte),
 * consumo da loja SIMULADO, disponível para os carregadores e potência configurada × efetiva por conector.
 */
import type { StationPower } from '../api/operations'
import type { Connector } from '../api/types'
import { formatNumber, toNumber } from './format'

/** Atualização da seção enquanto a página está aberta e visível (como o app). */
export const POWER_POLL_MS = 3000

export type BuildingProfile = 'conveniencia' | 'farmacia' | 'padaria' | 'supermercado' | 'restaurante' | 'shopping'
export type BuildingSize = 'pequeno' | 'medio' | 'grande'

/** Tipos de estabelecimento aceitos pela API (`PowerSiteInput.building_profile`) e pico típico (porte médio). */
export const BUILDING_PROFILES: { value: BuildingProfile; label: string; peakKw: number }[] = [
  { value: 'conveniencia', label: 'Loja de conveniência', peakKw: 22 },
  { value: 'farmacia', label: 'Farmácia', peakKw: 12 },
  { value: 'padaria', label: 'Padaria', peakKw: 45 },
  { value: 'supermercado', label: 'Supermercado', peakKw: 100 },
  { value: 'restaurante', label: 'Restaurante', peakKw: 30 },
  { value: 'shopping', label: 'Shopping', peakKw: 750 },
]

export const BUILDING_SIZES: { value: BuildingSize; label: string; factor: number }[] = [
  { value: 'pequeno', label: 'Pequeno', factor: 0.6 },
  { value: 'medio', label: 'Médio', factor: 1 },
  { value: 'grande', label: 'Grande', factor: 1.6 },
]

export const DEFAULT_PROFILE: BuildingProfile = 'conveniencia'
export const DEFAULT_SIZE: BuildingSize = 'medio'

export const REBALANCE_HELP = 'Divide a potência entre os carros sem passar do limite contratado.'

export function profileKey(value: string | null | undefined): BuildingProfile {
  return BUILDING_PROFILES.some((p) => p.value === value) ? (value as BuildingProfile) : DEFAULT_PROFILE
}

export function sizeKey(value: string | null | undefined): BuildingSize {
  return BUILDING_SIZES.some((s) => s.value === value) ? (value as BuildingSize) : DEFAULT_SIZE
}

export function profileLabel(value: string | null | undefined): string {
  return BUILDING_PROFILES.find((p) => p.value === profileKey(value))!.label
}

/**
 * Limite contratado padrão (`site_load.default_site_limit_kw`): `max(75 kW, pico × 1,3)` em passos de
 * 10 kW. Só para mostrar o padrão do tipo/porte escolhido antes de salvar; a API recalcula.
 */
export function defaultSiteLimitKw(profile?: string | null, size?: string | null): number {
  const peak = BUILDING_PROFILES.find((p) => p.value === profileKey(profile))!.peakKw
  const factor = BUILDING_SIZES.find((s) => s.value === sizeKey(size))!.factor
  const sized = Math.round(peak * factor * 10) / 10
  return Math.max(75, Math.ceil(Number((sized * 1.3).toFixed(6)) / 10) * 10)
}

/** "6 kW", "28,5 kW", "—" (até 1 casa, como a API arredonda). */
export function formatKw(value: string | number | null | undefined, empty = '—'): string {
  const number = toNumber(value)
  if (number === null) return empty
  const rounded = Math.round(number * 10) / 10
  return `${formatNumber(rounded, Number.isInteger(rounded) ? 0 : 1)} kW`
}

/** Valor da API → texto do campo ("75,5"; vazio sem valor). */
export function limitInput(value: string | number | null | undefined): string {
  const number = toNumber(value)
  return number === null ? '' : String(Math.round(number * 10) / 10).replace('.', ',')
}

/** Limite contratado digitado ("75,5") → string da API, `null` (vazio = padrão do tipo/porte) ou erro. */
export function validateSiteLimit(text: string): { value?: string | null; error?: string } {
  const raw = text.trim()
  if (!raw) return { value: null }
  if (!/^\d{1,5}([.,]\d)?$/.test(raw)) return { error: 'Use kW com até 1 casa, por exemplo 75,5.' }
  const number = Number(raw.replace(',', '.'))
  if (number <= 0) return { error: 'Informe um limite maior que zero.' }
  if (number > 10000) return { error: 'O limite contratado vai até 10.000 kW.' }
  return { value: number.toFixed(1) }
}

export interface SiteDraft {
  limit: string
  profile: BuildingProfile
  size: BuildingSize
}

/** Rascunho do formulário a partir da visão: o limite é o INFORMADO pelo dono (vazio = padrão). */
export function siteDraft(view: Pick<StationPower, 'site_limit_configured_kw' | 'building_profile' | 'building_size'>): SiteDraft {
  return { limit: limitInput(view.site_limit_configured_kw), profile: profileKey(view.building_profile), size: sizeKey(view.building_size) }
}

export interface PowerSiteBody {
  site_limit_kw?: string | null
  building_profile?: BuildingProfile
  building_size?: BuildingSize
}

/**
 * Corpo do `PUT power-site` só com o que o dono mudou. O padrão nunca é gravado como valor do dono:
 * `site_limit_kw` só vai quando o campo difere do informado (vazio → `null`, volta ao padrão).
 */
export function siteChanges(view: Pick<StationPower, 'site_limit_configured_kw' | 'building_profile' | 'building_size'>, draft: SiteDraft): { body: PowerSiteBody; error?: string } {
  const saved = siteDraft(view)
  const body: PowerSiteBody = {}
  let error: string | undefined
  if (draft.limit.trim() !== saved.limit) {
    const check = validateSiteLimit(draft.limit)
    if (check.error) error = check.error
    else {
      const before = toNumber(view.site_limit_configured_kw)
      const after = check.value === null || check.value === undefined ? null : Number(check.value)
      if (after !== before) body.site_limit_kw = check.value ?? null
    }
  }
  if (draft.profile !== saved.profile) body.building_profile = draft.profile
  if (draft.size !== saved.size) body.building_size = draft.size
  return { body, error }
}

export interface PowerSummary {
  available: string
  limit: string
  limitDetail: string
  load: string
  loadDetail: string
  cars: string
  carsDetail: string
  over: string | null
}

/** Cartão do topo: disponível, limite, loja (SIMULADO) e carros agora (`site_power.summary`). */
export function powerSummary(view: StationPower): PowerSummary {
  const used = toNumber(view.envelope_kw) ?? toNumber(view.allocated_kw) ?? 0
  const exceeded = Math.max(0, toNumber(view.exceeded_kw) ?? 0)
  const count = view.cars || 0
  const profile = view.building_profile_label?.split(' · ')[0] || profileLabel(view.building_profile)
  return {
    available: formatKw(view.available_kw, 'Sem limite'),
    limit: formatKw(view.site_limit_kw, 'Sem limite'),
    limitDetail: view.site_limit_default ? 'Padrão para o tipo de estabelecimento' : 'Informado por você',
    load: formatKw(view.building_load_kw, '0 kW'),
    loadDetail: view.building_load_mode === 'manual' ? 'Valor do simulador (30 min)' : profile,
    cars: formatKw(used, '0 kW'),
    carsDetail: count ? `${count} carro${count !== 1 ? 's' : ''} carregando` : 'Nenhum carro carregando',
    over: exceeded > 0 ? `Excesso transitório de ${formatKw(exceeded)}: reduções enviadas, aguardando os equipamentos.` : null,
  }
}

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
