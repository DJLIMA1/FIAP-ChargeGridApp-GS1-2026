/**
 * DEV-ONLY: previsão fictícia no formato de `/owner/forecast` e `/owner/occupancy-history`
 * (`VITE_MOCK=1`). Curva de shopping com pico às 18h; marcada como histórico sintético.
 */
import type { ForecastHour, OccupancyHistory, OwnerForecast } from '../api/forecast'

const CURVE = [2, 1, 0, 0, 0, 0, 3, 8, 15, 28, 40, 52, 66, 60, 34, 12, 10, 58, 88, 84, 60, 30, 12, 4]
const DAYS = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']

function localIso(date: Date): string {
  const shifted = new Date(date.getTime() - 3 * 3_600_000)
  return `${shifted.toISOString().slice(0, 13)}:00:00-03:00`
}

function label(start: Date, today: Date): string {
  const days = Math.round((start.getTime() - today.getTime()) / 86_400_000)
  return days <= 0 ? 'Hoje' : days === 1 ? 'Amanhã' : DAYS[(start.getUTCDay() + 6) % 7]
}

export function forecast(stationId: string): OwnerForecast {
  const now = new Date()
  const first = new Date(Math.floor(now.getTime() / 3_600_000) * 3_600_000)
  const hours: ForecastHour[] = Array.from({ length: 36 }, (_, i) => {
    const when = new Date(first.getTime() + i * 3_600_000)
    const hour = (when.getUTCHours() + 21) % 24
    const base = CURVE[hour]
    const occ = Math.min(100, base * (hour >= 17 && hour <= 19 ? 1.04 : 0.95))
    return {
      start: localIso(when), occupancy_percent: occ.toFixed(1), baseline_percent: base.toFixed(1),
      low_percent: Math.max(0, occ - 18).toFixed(1), high_percent: Math.min(100, occ + 14).toFixed(1),
      energy_kwh: ((base / 100) * 4 * 15.6).toFixed(3), expected_multiplier: occ >= 80 ? '1.20' : '1.00', full: occ >= 80,
    }
  })
  const peakIndex = hours.findIndex((h, i) => h.full && i > 12)
  const today = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()))
  const peakStart = new Date(first.getTime() + Math.max(0, peakIndex) * 3_600_000)
  return {
    station_id: stationId, generated_at: now.toISOString(), timezone: 'America/Sao_Paulo', as_of: hours[0].start,
    horizon_hours: 36, connectors: 4, status: 'ok', method: 'gbm',
    method_reason: 'O modelo errou menos que a média nos últimos dias deste posto.',
    model: {
      version: 'occ-gbm-v1', trained_on: 'histórico sintético syn-v1 (semente 20261020, 36 postos, 210 dias)',
      library: 'scikit-learn 1.6.1 GradientBoostingRegressor', selected: 'gbm',
      offline_test: {
        period: 'dias 175–209 do histórico sintético (nunca usados no ajuste)',
        baseline: { mae_pp: 16.08, wape: 0.7072, accuracy_percent: 29.3 },
        gbm: { mae_pp: 14.98, wape: 0.6589, accuracy_percent: 34.1 },
        daily: {
          baseline: { peak_days: 1174, peak_hit_percent: 56.6, energy_day_wape: 0.2455, energy_day_accuracy_percent: 75.4 },
          gbm: { peak_days: 1174, peak_hit_percent: 57.2, energy_day_wape: 0.3149, energy_day_accuracy_percent: 68.5 },
        },
      },
    },
    coverage: { days_measured: 6, days_synthetic: 50, first_hour: null },
    includes_synthetic: true,
    notes: ['Inclui histórico sintético (rotulado).'],
    accuracy: {
      window_days: 14, origins: 14, status: 'ok',
      baseline: { mae_pp: 12.4, wape: 0.41, accuracy_percent: 59 }, gbm: { mae_pp: 10.9, wape: 0.36, accuracy_percent: 64 },
      daily: {
        baseline: { peak_days: 14, peak_hit_percent: 71.4, energy_day_wape: 0.18, energy_day_accuracy_percent: 82 },
        gbm: { peak_days: 14, peak_hit_percent: 78.6, energy_day_wape: 0.22, energy_day_accuracy_percent: 78 },
      },
    },
    band: 'p10–p90 do erro no backtest',
    hours,
    peaks: peakIndex >= 0 ? [{ start: localIso(peakStart), end: localIso(new Date(peakStart.getTime() + 2 * 3_600_000)), label: `${label(peakStart, today)} 18h–20h deve lotar`, max_percent: '91.5' }] : [],
    idle: [],
    suggestions: [
      {
        kind: 'raise_demand_cap', title: 'Aumente o acréscimo máximo para 30%',
        detail: 'Amanhã 18h–20h deve lotar. Hoje o preço dinâmico sobe no máximo 20%; com 30% o pico fica mais valorizado e parte da procura migra para horários livres.',
        window: { start: hours[0].start, end: hours[2].start },
        action: { type: 'pricing_rules', patch: { demand: { max_increase_percent: 30 } } },
      },
      {
        kind: 'schedule_idle', title: 'Tarifa menor 15:00–17:00',
        detail: 'Amanhã 15h–17h deve ficar vazio. Uma tarifa base 10% menor toda quarta-feira das 15:00 às 17:00 aparece para o motorista como melhor horário no app.',
        window: { start: hours[0].start, end: hours[2].start },
        action: { type: 'pricing_rules', patch: { schedule: { enabled: true, intervals: [] } },
          preview: [{ connector_id: 'c1', public_code: 'CG-001', from: '1.8900', to: '1.7010' }] },
      },
    ],
  }
}

export function history(stationId: string, weeks: number): OccupancyHistory {
  const occupancy = DAYS.map((_, d) => CURVE.map((v) => (d >= 5 ? Math.min(100, v * 1.15) : v).toFixed(1)))
  return {
    station_id: stationId, weeks, days: DAYS, hours: CURVE.map((_, h) => h), occupancy_percent: occupancy,
    energy_kwh: occupancy.map((row) => row.map((v) => ((Number(v) / 100) * 4 * 15.6).toFixed(3))),
    samples: DAYS.map(() => CURVE.map(() => weeks)), max_occupancy_percent: '100.0',
    coverage: { days_measured: 6, days_synthetic: weeks * 7 - 6, first_hour: null }, includes_synthetic: true,
    notes: ['Inclui histórico sintético (rotulado).'],
  }
}
