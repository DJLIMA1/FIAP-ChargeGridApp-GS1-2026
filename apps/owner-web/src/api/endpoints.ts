import type { ApiClient } from './client'
import type {
  AddressSuggestions,
  AlertItem,
  Connector,
  Coupon,
  CouponInput,
  Heatmap,
  LiveItem,
  Overview,
  OwnerInsights,
  Page,
  Profile,
  SessionItem,
  Station,
  Timeseries,
} from './types'
import type { PeriodQuery } from '../lib/period'

export interface SessionFilters extends PeriodQuery {
  status?: string
  q?: string
  limit?: number
  offset?: number
}

export type StationPatch = Partial<Pick<Station, 'name' | 'address' | 'active' | 'amenities'>> & {
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
}>

export function endpoints(api: ApiClient) {
  return {
    me: () => api.get<Profile>('/me'),
    overview: (q: PeriodQuery, signal?: AbortSignal) => api.get<Overview>('/owner/overview', { ...q }, signal),
    timeseries: (q: PeriodQuery & { granularity?: 'hour' | 'day' }, signal?: AbortSignal) =>
      api.get<Timeseries>('/owner/timeseries', { ...q }, signal),
    heatmap: (q: PeriodQuery, signal?: AbortSignal) => api.get<Heatmap>('/owner/heatmap', { ...q }, signal),
    sessions: (q: SessionFilters, signal?: AbortSignal) => api.get<Page<SessionItem>>('/owner/sessions', { ...q }, signal),
    alerts: (stationId?: string | null, signal?: AbortSignal) =>
      api.get<{ items: AlertItem[]; generated_at: string }>('/owner/alerts', { station_id: stationId }, signal),
    live: (stationId?: string | null, signal?: AbortSignal) =>
      api.get<{ items: LiveItem[]; generated_at: string }>('/owner/live', { station_id: stationId }, signal),
    stations: (signal?: AbortSignal) =>
      api.get<Page<Station>>('/operator/stations', { limit: 100, offset: 0 }, signal),
    station: (id: string, signal?: AbortSignal) => api.get<Station>(`/stations/${encodeURIComponent(id)}`, undefined, signal),
    addressSuggestions: (q: string, signal?: AbortSignal) =>
      api.get<AddressSuggestions>('/geo/address-suggestions', { q }, signal),
    patchStation: (id: string, body: StationPatch) => api.patch<Station>(`/stations/${encodeURIComponent(id)}`, body),
    patchConnector: (id: string, body: ConnectorPatch) =>
      api.patch<Connector>(`/connectors/${encodeURIComponent(id)}`, body),
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
