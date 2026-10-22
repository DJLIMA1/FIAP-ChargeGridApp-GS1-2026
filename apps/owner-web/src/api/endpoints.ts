import type { ApiClient } from './client'
import type {
  AddressSuggestions,
  AlertItem,
  Connector,
  Coupon,
  CouponInput,
  Heatmap,
  Overview,
  OwnerInsights,
  Page,
  Profile,
  SessionItem,
  Station,
  Timeseries,
} from './types'
import type { PeriodQuery } from '../lib/period'
import type { MarginReport, PowerSiteInput, PricingRules, StationEconomics, StationPower, StationPricing } from './operations'

export interface PaymentsConfig {
  enabled: boolean
  provider?: string
  environment?: string
}

export interface SessionFilters extends PeriodQuery {
  status?: string
  q?: string
  limit?: number
  offset?: number
}

export type StationPatch = Partial<Pick<Station, 'name' | 'address' | 'active' | 'amenities' | 'kiosk_mode'>> & {
  latitude?: number
  longitude?: number
}

export type ConnectorPatch = Partial<{
  public_code: string
  connector_type: string
  power_kw: string
  price_per_kwh: string
  max_duration_minutes: number
  active: boolean
  /** Endereço do carregador GoodWe deste conector (1–247, único no posto; não pode ficar vazio). */
  charger_address: number
  /** Limite do dono (kW, até a potência nominal); `null` = usa a nominal. */
  power_limit_kw: string | null
}>

export interface MarginFilters extends PeriodQuery {
  limit?: number
  offset?: number
}

/** Filtros do relatório de resultado para a exportação (sem paginação). */
export function marginExportQuery(q: PeriodQuery): PeriodQuery {
  return { from: q.from, to: q.to, station_id: q.station_id || undefined }
}

export function endpoints(api: ApiClient) {
  return {
    me: (signal?: AbortSignal) => api.get<Profile>('/me', undefined, signal),
    /** Stripe (teste) configurada no servidor; `enabled: false` → totem de conta oficial indisponível. */
    paymentsConfig: (signal?: AbortSignal) => api.get<PaymentsConfig>('/payments/config', undefined, signal),
    overview: (q: PeriodQuery, signal?: AbortSignal) => api.get<Overview>('/owner/overview', { ...q }, signal),
    timeseries: (q: PeriodQuery & { granularity?: 'hour' | 'day' }, signal?: AbortSignal) =>
      api.get<Timeseries>('/owner/timeseries', { ...q }, signal),
    heatmap: (q: PeriodQuery, signal?: AbortSignal) => api.get<Heatmap>('/owner/heatmap', { ...q }, signal),
    sessions: (q: SessionFilters, signal?: AbortSignal) => api.get<Page<SessionItem>>('/owner/sessions', { ...q }, signal),
    alerts: (stationId?: string | null, signal?: AbortSignal) =>
      api.get<{ items: AlertItem[]; generated_at: string }>('/owner/alerts', { station_id: stationId }, signal),
    stations: (signal?: AbortSignal) =>
      api.get<Page<Station>>('/operator/stations', { limit: 100, offset: 0 }, signal),
    station: (id: string, signal?: AbortSignal) => api.get<Station>(`/stations/${encodeURIComponent(id)}`, undefined, signal),
    addressSuggestions: (q: string, signal?: AbortSignal) =>
      api.get<AddressSuggestions>('/geo/address-suggestions', { q }, signal),
    patchStation: (id: string, body: StationPatch) => api.patch<Station>(`/stations/${encodeURIComponent(id)}`, body),
    patchConnector: (id: string, body: ConnectorPatch) =>
      api.patch<Connector>(`/connectors/${encodeURIComponent(id)}`, body),
    /**
     * Adicionar carregador à tela do ponto `connectorId` (ou à tela dele, se for um carregador
     * adicional): próximo endereço livre, inativo. 409 `screen_required` / `charger_address_full`.
     */
    addCharger: (connectorId: string) => api.post<Connector>(`/connectors/${encodeURIComponent(connectorId)}/chargers`, {}),
    /**
     * Remover carregador adicional (204, sem corpo): sai da estação e o endereço fica livre para o
     * próximo "Adicionar carregador". 409 `screen_charger` (o da própria central) / `point_busy`; 404.
     */
    removeCharger: (connectorId: string) => api.delete<void>(`/connectors/${encodeURIComponent(connectorId)}`),
    /**
     * Remover estação (204, sem corpo): o posto sai do mapa, das listas e do painel; sessões, recibos e
     * relatórios continuam. 409 `station_busy` (recarga/reserva/pedido do totem) / `central_online`
     * (restaurar a central antes); 404.
     */
    removeStation: (stationId: string) => api.delete<void>(`/stations/${encodeURIComponent(stationId)}`),
    // C · Resultado: custo do kWh do posto (comissão só leitura) e margem do período.
    economics: (id: string, signal?: AbortSignal) =>
      api.get<StationEconomics>(`/stations/${encodeURIComponent(id)}/economics`, undefined, signal),
    putEconomics: (id: string, energyCostPerKwh: string | null) =>
      api.put<StationEconomics>(`/stations/${encodeURIComponent(id)}/economics`, { energy_cost_per_kwh: energyCostPerKwh }),
    margin: (q: MarginFilters, signal?: AbortSignal) => api.get<MarginReport>('/owner/margin', { ...q }, signal),
    exportMargin: (fmt: 'csv' | 'pdf', q: PeriodQuery) => api.blob(`/owner/export/margin.${fmt}`, { ...marginExportQuery(q) }),
    exportCentralRent: (q: PeriodQuery) => api.blob('/owner/export/central-rent.csv', { ...marginExportQuery(q) }),
    // Potência do posto: limite contratado (padrão ou do dono), loja SIMULADA, rebalanceamento e tipo/porte.
    power: (id: string, signal?: AbortSignal) => api.get<StationPower>(`/stations/${encodeURIComponent(id)}/power`, undefined, signal),
    putPowerSite: (id: string, body: PowerSiteInput) => api.put<StationPower>(`/stations/${encodeURIComponent(id)}/power-site`, body),
    // D · Tarifa do posto (a taxa de permanência fica em rules.rotation). O PUT é parcial na API
    // (`pricing.merge_rules`): o que não vier no corpo continua como está.
    pricing: (id: string, signal?: AbortSignal) => api.get<StationPricing>(`/stations/${encodeURIComponent(id)}/pricing`, undefined, signal),
    putPricing: (id: string, rules: PricingRules) => api.put<StationPricing>(`/stations/${encodeURIComponent(id)}/pricing`, rules),
    coupons: (signal?: AbortSignal) => api.get<Page<Coupon>>('/coupons', { mine: true, limit: 100 }, signal),
    createCoupon: (body: CouponInput) => api.post<Coupon>('/coupons', body),
    patchCoupon: (id: string, body: Partial<Pick<Coupon, 'description' | 'discount_percent' | 'valid_until' | 'active'>>) =>
      api.patch<Coupon>(`/coupons/${encodeURIComponent(id)}`, body),
    insights: (q: PeriodQuery) =>
      api.post<OwnerInsights>(
        '/ai/owner-insights',
        Object.fromEntries(Object.entries(q).filter(([, v]) => v !== null && v !== undefined && v !== '')),
        { timeoutMs: 60_000 },
      ),
  }
}

export type Endpoints = ReturnType<typeof endpoints>

/** Busca todas as páginas de sessões do filtro atual (para exportação). */
export async function fetchAllSessions(
  ep: Endpoints,
  filters: Omit<SessionFilters, 'limit' | 'offset'>,
  max = 5000,
  onProgress?: (loaded: number, total: number) => void,
): Promise<{ items: SessionItem[]; total: number; truncated: boolean }> {
  const items: SessionItem[] = []
  let total: number
  let offset = 0
  for (;;) {
    const page = await ep.sessions({ ...filters, limit: 100, offset })
    total = page.total
    items.push(...page.items)
    offset += page.items.length
    onProgress?.(items.length, total)
    if (!page.items.length || offset >= total || items.length >= max) break
  }
  return { items: items.slice(0, max), total, truncated: total > max }
}
