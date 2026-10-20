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

export interface PaymentSettlement {
  status: 'due' | 'settling' | 'done' | 'failed' | string
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

export interface SessionPayment {
  id: string
  status: string
  status_label: string
  environment: 'test' | string
  provider?: string
  origin?: 'app' | 'kiosk' | string
  method?: 'card' | 'pix' | string | null
  currency?: string
  amount: Decimal
  settlement: PaymentSettlement | null
}

/* ----------------------------------------------------------- D · permanência */

/** `rules.rotation` ("Taxa de permanência"). Aceita as chaves do contrato e as antigas. */
export interface RotationRule {
  enabled?: boolean
  grace_minutes?: number
  interval_minutes?: number
  start_after_min?: number
  interval_min?: number
  amount?: Decimal
  max_amount?: Decimal
  [key: string]: unknown
}

export interface PricingRules {
  rotation?: RotationRule
  [key: string]: unknown
}

export interface StationPricing {
  rules: PricingRules
  status?: Record<string, unknown>
  connectors?: Record<string, unknown>[]
}

export interface StationOverstay {
  enabled: boolean
  grace_minutes: number
  interval_minutes: number
  amount: Decimal
  max_amount: Decimal
  version?: string | null
  summary?: string | null
}

export type OverstayStatus = 'none' | 'no_fee' | 'grace' | 'billing' | 'capped' | 'closed'

export interface SessionOverstay {
  status: OverstayStatus | string
  started_at?: string | null
  grace_remaining_seconds?: number | null
  billable_seconds?: number | null
  fee_due?: Decimal | null
  ended_at?: string | null
  end_reason?: string | null
}

export interface LiveOccupancy {
  session_id: string
  status: OverstayStatus | string
  started_at: string | null
  grace_remaining_seconds: number | null
  fee_due: Decimal | null
  max_fee: Decimal | null
  driver_label?: string | null
}
