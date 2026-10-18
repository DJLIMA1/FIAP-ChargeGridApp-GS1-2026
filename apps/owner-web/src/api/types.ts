/**
 * Formas das respostas da API ChargeGrid (/v1). Valores decimais chegam como
 * strings (ex.: "8420.00") para preservar precisão; `null` significa "sem dados".
 */

export type Decimal = string

export interface TokenResponse {
  access_token: string
  refresh_token: string
  expires_in?: number
  expires_at?: number
  token_type?: string
}

export interface Profile {
  id: string
  name: string
  account_type: 'consumer' | 'vendor' | string
  phone?: string | null
  vehicle_description?: string | null
  operator_enabled: boolean
  created_at?: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface Kpis {
  revenue: Decimal | null
  energy_wh: Decimal | null
  energy_kwh: Decimal | null
  sessions: number
  average_ticket: Decimal | null
  occupancy_percent: Decimal | null
  uptime_percent: Decimal | null
  reservations: number
  no_shows: number
  no_show_percent: Decimal | null
  interrupted_sessions: number
  failed_sessions: number
  active_sessions: number
  points: number
  points_online: number
}

export interface RankingItem {
  connector_id: string
  station_id: string
  station_name: string
  public_code: string
  revenue: Decimal | null
  energy_kwh: Decimal | null
  sessions: number
  occupancy_percent: Decimal | null
}

export interface Overview {
  period: { from: string; to: string; timezone: string }
  station_id: string | null
  kpis: Kpis
  stations: { total: number; active: number; points: number; points_published: number; points_online: number }
  ranking: RankingItem[]
  generated_at: string
}

export interface Timeseries {
  granularity: 'hour' | 'day'
  timezone: string
  basis: string
  buckets: string[]
  series: { revenue: Decimal[]; energy_kwh: Decimal[]; sessions: number[] }
}

export interface Heatmap {
  timezone: string
  basis: string
  days: string[]
  hours: number[]
  cells: number[][]
  max: number
  peak_hours: { hour: number; sessions: number }[]
}

export type SessionStatus = 'starting' | 'charging' | 'stopping' | 'completed' | 'interrupted' | 'failed'

export interface SessionItem {
  id: string
  station_id: string
  station_name: string
  connector_id: string
  public_code: string
  status: SessionStatus | string
  created_at: string | null
  started_at: string | null
  ended_at: string | null
  duration_minutes: Decimal | null
  energy_kwh: Decimal | null
  price_per_kwh: Decimal | null
  discount_percent: number
  cost_estimate: Decimal | null
  source: string
  end_reason: string
}

export type AlertSeverity = 'critical' | 'warning' | 'info'

export interface AlertItem {
  connector_id: string
  station_id: string
  station_name: string
  public_code: string
  kind: 'no_device' | 'device_offline' | 'device_fault' | 'command_failed' | 'point_idle' | string
  severity: AlertSeverity
  title: string
  detail: string
  at: string | null
}

export type AvailabilityStatus =
  | 'available'
  | 'offline'
  | 'reserved'
  | 'charging'
  | 'reconciling'
  | 'disabled'
  | 'fault'
  | 'occupied'

export interface LiveSession {
  id: string
  status: string
  started_at: string | null
  energy_wh: Decimal
  cost_estimate: Decimal
  soc_percent: Decimal | null
  power_w: Decimal | null
  source: string
  last_measurement_at: string | null
}

export interface LiveItem {
  connector_id: string
  station_id: string
  station_name: string
  station_active: boolean
  public_code: string
  connector_type: string
  power_kw: Decimal
  price_per_kwh: Decimal
  max_duration_minutes: number
  active: boolean
  retired: boolean
  has_device: boolean
  device_id: string | null
  online: boolean
  last_seen: string | null
  firmware_version: string | null
  physical_state: string
  available: boolean
  availability_status: AvailabilityStatus | string
  reserved_until: string | null
  session: LiveSession | null
}

export interface Amenity {
  kind: 'restaurante' | 'cafe' | 'banheiro' | 'shopping' | 'conveniencia'
  name: string
  distance_m: number | null
}

export interface Connector {
  id: string
  station_id: string
  public_code: string
  connector_type: string
  power_kw: Decimal
  price_per_kwh: Decimal
  max_duration_minutes: number
  active: boolean
  control_version?: number
  available?: boolean
  availability_status?: AvailabilityStatus | string
  reserved_until?: string | null
  online?: boolean
  physical_state?: string
  retired?: boolean
}

export interface Station {
  id: string
  owner_id: string | null
  name: string
  address: string
  latitude: number
  longitude: number
  active: boolean
  amenities: Amenity[]
  connectors: Connector[]
}

export interface Coupon {
  id: string
  operator_id: string
  station_id: string | null
  code: string
  description: string
  discount_percent: number
  valid_until: string
  active: boolean
}

export interface CouponInput {
  code: string
  description: string
  station_id: string | null
  discount_percent: number
  valid_until: string
}

export interface Recommendation {
  title: string
  detail: string
  impact: 'high' | 'medium' | 'low' | string
  kind: 'pricing' | 'operations' | 'marketing' | string
}

export interface OwnerInsights {
  summary: string
  recommendations: Recommendation[]
  generated_at: string
  model: string
}

export interface ApiErrorBody {
  error?: { code?: string; message?: string; fields?: { field: string; message: string }[] }
}
