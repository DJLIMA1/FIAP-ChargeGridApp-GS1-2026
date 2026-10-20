import { describe, expect, it } from 'vitest'
import type { ForecastHour } from '../src/api/forecast'
import { comparison, forecastPoints, localInstant, methodLabel, occupancyColor, percent, points, totalEnergy } from '../src/lib/forecast'
import { forecast } from '../src/mock/forecast'

const hour = (start: string, occupancy: string, extra: Partial<ForecastHour> = {}): ForecastHour => ({
  start, occupancy_percent: occupancy, baseline_percent: '50.0', low_percent: null, high_percent: null,
  energy_kwh: '2.500', expected_multiplier: '1.00', full: Number(occupancy) >= 80, ...extra,
})

describe('previsão', () => {
  it('lê horas locais com ou sem deslocamento como horário de São Paulo', () => {
    expect(localInstant('2026-10-21T17:00:00').toISOString()).toBe('2026-10-21T20:00:00.000Z')
    expect(localInstant('2026-10-21T17:00:00-03:00').toISOString()).toBe('2026-10-21T20:00:00.000Z')
  })

  it('monta pontos do gráfico com faixa só quando calibrada', () => {
    const [plain, banded] = forecastPoints([
      hour('2026-10-21T17:00:00-03:00', '91.5'),
      hour('2026-10-21T18:00:00-03:00', '40.0', { low_percent: '20.0', high_percent: '60.0' }),
    ])
    expect(plain).toMatchObject({ label: '17h', occupancy: 91.5, baseline: 50, band: null, full: true })
    expect(banded.band).toEqual([20, 60])
    expect(totalEnergy([hour('a', '1'), hour('b', '1')])).toBe(5)
  })

  it('compara modelo e média de forma honesta', () => {
    expect(comparison({ mae_pp: 9, wape: 0.3, accuracy_percent: 70 }, { mae_pp: 10, wape: 0.33, accuracy_percent: 67 })).toBe('erro 10% menor que a média')
    expect(comparison({ mae_pp: 11, wape: null, accuracy_percent: null }, { mae_pp: 10, wape: null, accuracy_percent: null })).toBe('erro 10% maior que a média')
    expect(comparison(null, { mae_pp: 10, wape: null, accuracy_percent: null })).toBeNull()
    expect(methodLabel('baseline')).toBe('Média do mesmo dia e hora')
    expect(percent(56.6)).toBe('57%')
    expect(points(14.98)).toBe('15,0 p.p.')
    expect(percent(null)).toBe('—')
  })

  it('destaca lotação em laranja e vazio em cinza', () => {
    expect(occupancyColor(null)).toBe('#242424')
    expect(occupancyColor(90)).toContain('232, 146, 43')
    expect(occupancyColor(30)).toContain('61, 190, 122')
  })

  it('mock de desenvolvimento segue o contrato e rotula o histórico sintético', () => {
    const body = forecast('station-1')
    expect(body.hours).toHaveLength(36)
    expect(body.includes_synthetic).toBe(true)
    expect(body.suggestions.every((s) => s.action.type === 'pricing_rules')).toBe(true)
  })
})
