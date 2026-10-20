/**
 * Formas das respostas das frentes de operação do posto (mesmas regras de
 * `types.ts`: decimais como strings, `null` = sem dado):
 *
 * - C · Resultado: `/stations/{id}/economics`, `/owner/margin` e exportações;
 * - B · Energia do estabelecimento: `/stations/{id}/power`, `power-site`, `building-load`;
 * - A · Pagamentos (Stripe em modo teste): `payment` nas sessões do dono;
 * - D · Permanência: `rules.rotation`, `overstay` no posto/sessão e `occupancy` no ao vivo.
 *
 * Campos das frentes ainda em andamento são opcionais: a tela some ou mostra "—"
 * quando eles não vêm.
 */
import type { Decimal } from './types'

/* ------------------------------------------------------------ C · resultado */

export interface StationEconomics {
  station_id: string
  energy_cost_per_kwh: Decimal | null
  platform_fee_percent: Decimal
  fee_editable: boolean
  currency: string
  notes?: string[]
}

export type CostBasis = 'snapshot' | 'current' | 'missing'

export interface MarginRow {
  session_id: string
  ended_at: string | null
  station_id: string | null
  station_name: string
  public_code: string
  source: string | null
  energy_kwh: Decimal
  connector_base_per_kwh: Decimal | null
  base_per_kwh: Decimal
  demand_multiplier: Decimal
  price_per_kwh: Decimal
  coupon_code: string | null
  discount_percent: number
  list_value: Decimal
  schedule_effect: Decimal | null
  demand_effect: Decimal
  gross: Decimal
  discount: Decimal
  revenue: Decimal
  overstay_revenue: Decimal | null
  revenue_total: Decimal
  revenue_basis: 'estimated' | 'captured' | string
  payment_environment: string | null
  platform_fee_percent: Decimal
  platform_fee: Decimal
  provider_fee: Decimal | null
  owner_net: Decimal
  energy_cost_per_kwh: Decimal | null
  cost_basis: CostBasis | string
  energy_cost: Decimal | null
  margin: Decimal | null
  margin_percent: Decimal | null
}

export interface MarginTotals {
  sessions: number
  energy_kwh: Decimal
  list_value: Decimal
  schedule_effect: Decimal | null
  demand_effect: Decimal
  gross: Decimal
  discount: Decimal
  revenue: Decimal
  overstay_revenue: Decimal | null
  revenue_total: Decimal
  platform_fee: Decimal
  provider_fee: Decimal | null
  owner_net: Decimal
  energy_cost: Decimal | null
  margin: Decimal | null
  margin_covered: Decimal
  margin_percent: Decimal | null
  coverage: { sessions: number; with_energy_cost: number; missing_energy_cost: number }
}

export interface MarginStationConfig extends StationEconomics {
  station_name: string
}

export interface MarginReport {
  schema_version: number
  period: { from: string; to: string; timezone: string }
  basis: string
  currency: string
  station_id: string | null
  stations: MarginStationConfig[]
  totals: MarginTotals
  dynamic_pricing: {
    demand_effect: Decimal
    schedule_effect: Decimal | null
    sessions_with_increase: number
    average_multiplier: Decimal | null
  }
  coupons: { sessions: number; discount: Decimal }
  sources: Record<string, number>
  by_station: (MarginTotals & { station_id: string | null; station_name: string })[]
  warnings: string[]
  methodology: string[]
  items: MarginRow[]
  total: number
  limit: number
  offset: number
  generated_at: string
}

/* ------------------------------------------- B · energia do estabelecimento */

export type PowerState = 'applied' | 'reducing' | 'raising' | 'waiting' | 'paused' | 'fixed'

export interface PowerPointSession {
  id: string
  status: string
  target_kw: Decimal | null
  applied_kw: Decimal | null
  envelope_kw: Decimal | null
  power_state: PowerState | string | null
  reason: string | null
  reason_short: string | null
  reason_code: string | null
}

export interface PowerPoint {
  connector_id: string
  public_code: string
  power_kw: Decimal | null
  online: boolean
  adjustable: boolean
  charger: Record<string, unknown> | null
  session: PowerPointSession | null
}

export interface PowerDecision {
  id: string | number
  created_at: string
  trigger: string
  available_kw: Decimal | null
  exceeded_kw: Decimal | null
  summary: string
}

export interface StationPower {
  station_id: string
  rebalance_enabled: boolean
  site_limit_kw: Decimal | null
  building_load_kw: Decimal | null
  building_load_source: string | null
  building_load_simulated: boolean
  building_load_updated_at: string | null
  station_cap_kw: Decimal | null
  available_kw: Decimal | null
  allocated_kw: Decimal | null
  envelope_kw: Decimal | null
  exceeded_kw: Decimal | null
  cars: number
  points: PowerPoint[]
  decisions: PowerDecision[]
}

export interface PowerSiteInput {
  site_limit_kw?: string | null
  rebalance_enabled?: boolean
}

/* ------------------------------------------------------------ A · pagamentos */

/** `settlement` de `payment_row` (`modules/payments/funding.py`); `settlement_status` do modelo. */
export interface PaymentSettlement {
  status: 'none' | 'due' | 'settling' | 'done' | 'failed' | string
  energy_amount: Decimal
  overstay_amount: Decimal
  fixed_fee: Decimal
  charged: Decimal
  returned: Decimal
  return_kind: 'released' | 'refunded' | string
  captured: Decimal
  refunded: Decimal
  waived: Decimal
  uncollected: Decimal
  below_minimum: boolean
  provider_fee: Decimal | null
  settled_at: string | null
}

export type PaymentStatus =
  | 'awaiting_payment'
  | 'declined'
  | 'authorized'
  | 'paid'
  | 'in_use'
  | 'expired'
  | 'canceled'
  | 'completed'

/** `payment` de cada item de `/owner/sessions` (`payment_row(..., owner=True)`; `null` sem pagamento). */
export interface SessionPayment {
  id: string
  status: PaymentStatus | string
  status_label: string
  environment: 'test' | string
  provider?: string
  origin?: 'app' | 'kiosk' | string
  /** `/owner/sessions` e `/operator/charging-sessions` (totem 0.8.0): canal da recarga paga. */
  channel?: 'app' | 'kiosk_qr' | 'kiosk_totem' | string
  method?: 'card' | 'pix' | string | null
  currency?: string
  amount: Decimal
  energy_cap?: Decimal
  fixed_fee?: Decimal
  overstay_reserve?: Decimal
  price_per_kwh?: Decimal
  base_price_per_kwh?: Decimal
  demand_multiplier?: Decimal
  discount_percent?: number
  max_duration_minutes?: number
  max_power_kw?: Decimal | null
  connector_id?: string
  session_id?: string | null
  expires_at?: string | null
  start_deadline?: string | null
  authorized_at?: string | null
  created_at?: string | null
  provider_ref?: string | null
  settlement: PaymentSettlement | null
}

/* ----------------------------------------------------------- D · permanência */

/**
 * `rules.rotation` ("Taxa de permanência"), exatamente como a API grava e devolve
 * (`chargegrid_core.overstay.DEFAULT_ROTATION` / `clean_rotation`). Chaves fora destas
 * são descartadas em silêncio pelo `clean_rules` (ex.: `grace_minutes`).
 */
export interface RotationRule {
  enabled: boolean
  /** Tolerância em minutos (0–1440). */
  start_after_min: number
  /** Intervalo cobrado em minutos (1–1440; 1 = "por minuto"). */
  interval_min: number
  /** Valor por intervalo, "1.00" (R$ 0–100). */
  amount: Decimal
  /** Teto por recarga, "30.00" (R$ 0–1000). */
  max_amount: Decimal
}

export interface PricingRules {
  rotation?: RotationRule
  [key: string]: unknown
}

/** `GET/PUT /stations/{id}/pricing` (`modules/pricing/routes.py::_payload`). */
export interface StationPricing {
  rules: PricingRules
  status?: Record<string, unknown>
  connectors?: {
    id: string
    public_code: string
    active: boolean
    connector_type: string
    base_price_per_kwh: Decimal
    current_base_price_per_kwh: Decimal
    current_price_per_kwh: Decimal
  }[]
}

/**
 * `overstay` público do posto (`chargegrid_core.overstay.public`). Com a taxa desligada
 * todos os campos (menos `enabled: false`) vêm `null`.
 */
export interface StationOverstay {
  enabled: boolean
  grace_minutes: number | null
  interval_minutes: number | null
  amount: Decimal | null
  max_amount: Decimal | null
  fee_per_minute: Decimal | null
  version: string | null
  summary: string | null
}

export type OverstayStatus = 'none' | 'no_fee' | 'grace' | 'billing' | 'capped' | 'closed'

/** `occupancy` de cada ponto em `/owner/live` (`app/overstay.py::occupancy_by_connector`). */
export interface LiveOccupancy {
  session_id: string
  status: OverstayStatus | string
  started_at: string | null
  /** 0 fora de grace/billing/capped (nunca `null`). */
  grace_remaining_seconds: number
  billable_minutes: number
  fee_due: Decimal
  /** `null` sem termos aceitos (taxa zero). */
  max_fee: Decimal | null
  fee_applies: boolean
  driver_label: string
  as_of: string | null
}
