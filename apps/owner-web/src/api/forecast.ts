import type { ApiClient } from './client'
import type { Decimal } from './types'

/** Métricas de erro (`mae_pp` em pontos percentuais; `wape` 0–1; `accuracy_percent` = 100 − WAPE). */
export interface ForecastMetrics {
  mae_pp: number | null
  wape: number | null
  accuracy_percent: number | null
}

export interface DailyMetrics {
  peak_days: number
  peak_hit_percent: number | null
  energy_day_wape: number | null
  energy_day_accuracy_percent: number | null
}

export interface ForecastHour {
  start: string
  occupancy_percent: Decimal
  baseline_percent: Decimal
  low_percent: Decimal | null
  high_percent: Decimal | null
  energy_kwh: Decimal
  expected_multiplier: Decimal
  full: boolean
}

export interface ForecastWindow {
  start: string
  end: string
  label: string
  max_percent?: Decimal
  min_percent?: Decimal
}

export interface PricePreview {
  connector_id: string
  public_code: string
  from: Decimal
  to: Decimal
}

export interface ForecastSuggestion {
  kind: 'enable_demand' | 'raise_demand_cap' | 'schedule_peak' | 'schedule_idle' | string
  title: string
  detail: string
  window: { start: string; end: string }
  action: { type: 'pricing_rules'; patch: Record<string, unknown>; preview?: PricePreview[] }
}

export interface ForecastCoverage {
  days_measured: number
  days_synthetic: number
  first_hour: string | null
}

export interface ForecastModelCard {
  version: string
  trained_on: string
  library: string
  selected: 'gbm' | 'baseline'
  offline_test: {
    period: string
    baseline: ForecastMetrics | null
    gbm: ForecastMetrics | null
    daily?: Record<string, DailyMetrics>
    unseen_stations?: Record<string, ForecastMetrics | null>
  }
}

export interface OwnerForecast {
  station_id: string
  generated_at: string
  timezone: string
  as_of: string
  horizon_hours: number
  connectors: number
  status: 'ok' | 'no_history'
  method: 'gbm' | 'baseline'
  method_reason: string
  model: ForecastModelCard | null
  coverage: ForecastCoverage
  includes_synthetic: boolean
  notes: string[]
  accuracy: {
    window_days: number
    origins: number
    status: 'ok' | 'insufficient_history'
    baseline: ForecastMetrics | null
    gbm: ForecastMetrics | null
    daily: Record<string, DailyMetrics>
  } | null
  band?: string
  hours: ForecastHour[]
  peaks: ForecastWindow[]
  idle: ForecastWindow[]
  suggestions: ForecastSuggestion[]
}

export interface OccupancyHistory {
  station_id: string
  weeks: number
  days: string[]
  hours: number[]
  occupancy_percent: (Decimal | null)[][]
  energy_kwh: (Decimal | null)[][]
  samples: number[][]
  max_occupancy_percent: Decimal
  coverage: ForecastCoverage
  includes_synthetic: boolean
  notes: string[]
}

export function forecastEndpoints(api: ApiClient) {
  return {
    forecast: (stationId: string, signal?: AbortSignal) =>
      api.get<OwnerForecast>('/owner/forecast', { station_id: stationId, horizon_hours: 36 }, signal),
    history: (stationId: string, weeks: number, signal?: AbortSignal) =>
      api.get<OccupancyHistory>('/owner/occupancy-history', { station_id: stationId, weeks }, signal),
    /** Aplica a sugestão pelo PUT parcial de tarifas que já existe. */
    applyPricing: (stationId: string, patch: Record<string, unknown>) =>
      api.request<unknown>('PUT', `/stations/${encodeURIComponent(stationId)}/pricing`, { body: patch }),
  }
}
