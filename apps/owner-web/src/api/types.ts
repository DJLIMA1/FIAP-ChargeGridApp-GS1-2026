/**
 * Formas das respostas da API ChargeGrid (/v1). Valores decimais chegam como
 * strings (ex.: "8420.00") para preservar precisão; `null` significa "sem dados".
 */
import type { SessionPayment, StationOverstay } from './operations'

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
  /** Modo apresentação da conta (totem 0.8.0): decide o pagamento do totem dos postos (simulado × Stripe teste). */
  presentation_mode?: boolean
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
  /** Frente A (Stripe em modo teste): ausente em APIs antigas, `null` sem pagamento. */
  payment?: SessionPayment | null
  /**
   * Frente D (permanência), `analytics.session_export_row`: taxa ("0.00" sem permanência)
   * e minutos cobrados (inteiro). `/owner/sessions` não traz o bloco `overstay` da sessão.
   */
  overstay_fee?: Decimal
  overstay_minutes?: number
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
  /** Totem 0.8.0: ponto travado por um pedido do totem (`occupied` + "Em uso no totem"). */
  kiosk_in_use?: boolean
  online?: boolean
  physical_state?: string
  retired?: boolean
  /** Limite do vendedor para o conector (`null` = nominal) e a potência efetiva no posto (`power.allocate`). */
  power_limit_kw?: Decimal | null
  effective_power_kw?: Decimal | null
  /** Carregador GoodWe HCA G2 ligado à tela deste ponto (só o dono): endereço 1–247 ou `null`. */
  charger_address?: number | null
  /** Estado do link pelo último sync da tela (só o dono); `null` sem carregador externo. */
  charger_link?: ChargerLink | null
}

export type ChargerLinkState = 'online' | 'offline' | 'pending'

export interface ChargerLink {
  model: 'goodwe_hca_g2' | string
  transport: 'modbus_tcp' | string
  address: number
  host: string
  label?: string
  simulated?: boolean
  /** `pending` = a tela (online) ainda não confirmou este endereço. */
  link: ChargerLinkState | string
  reported?: { model: string; transport: string; address: number; link: string } | null
}

export interface StationKioskStatus {
  method: 'simulated' | 'stripe' | null
  label: 'SIMULADO' | 'TESTE' | null
  reason: 'payments_unavailable' | 'point_disabled' | null
  reason_label?: string | null
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
  /** Totem 0.8.0: totem de autoatendimento no painel físico (padrão desligado). */
  kiosk_mode?: boolean
  /** Totem 0.8.0 (só o dono): método efetivo decidido pela API, mesma regra do `connector.kiosk` do sync. */
  kiosk_status?: StationKioskStatus | null
  /** Frente D: termos vigentes da taxa de permanência. */
  overstay?: StationOverstay | null
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

/** Sugestão de endereço (`GET /geo/address-suggestions`: Photon/OpenStreetMap ou ViaCEP). */
export interface AddressSuggestion {
  label: string
  street: string | null
  number: string | null
  district: string | null
  city: string | null
  state: string | null
  postcode: string | null
  latitude: number | null
  longitude: number | null
  place?: string
}

export interface AddressSuggestions {
  items: AddressSuggestion[]
  available: boolean
  attribution: string
}
