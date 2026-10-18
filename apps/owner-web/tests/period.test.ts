import { describe, expect, it } from 'vitest'
import { localDate, localMidnight, periodBounds, periodLabel, periodQuery, suggestedGranularity, validatePeriod } from '../src/lib/period'

// 18/10/2026 14:05 em São Paulo (UTC-3).
const NOW = new Date('2026-10-18T17:05:00Z')

describe('período → parâmetros da API', () => {
  it('converte datas locais de São Paulo', () => {
    expect(localDate(NOW)).toBe('2026-10-18')
    expect(localDate(new Date('2026-10-18T02:00:00Z'))).toBe('2026-10-17')
    expect(localMidnight('2026-10-18').toISOString()).toBe('2026-10-18T03:00:00.000Z')
    expect(localMidnight('2026-10-18', 1).toISOString()).toBe('2026-10-19T03:00:00.000Z')
  })

  it('Hoje começa à meia-noite local e termina agora', () => {
    const { from, to } = periodBounds({ preset: 'today' }, NOW)
    expect(from.toISOString()).toBe('2026-10-18T03:00:00.000Z')
    expect(to.toISOString()).toBe(NOW.toISOString())
  })

  it('7 e 30 dias incluem hoje (hoje-6 e hoje-29)', () => {
    expect(periodBounds({ preset: '7d' }, NOW).from.toISOString()).toBe('2026-10-12T03:00:00.000Z')
    expect(periodBounds({ preset: '30d' }, NOW).from.toISOString()).toBe('2026-09-19T03:00:00.000Z')
  })

  it('personalizado usa datas inclusivas', () => {
    const query = periodQuery({ preset: 'custom', start: '2026-10-01', end: '2026-10-10' }, 'abc', NOW)
    expect(query).toEqual({ from: '2026-10-01T03:00:00.000Z', to: '2026-10-11T03:00:00.000Z', station_id: 'abc' })
  })

  it('omite station_id quando é "todas"', () => {
    expect(periodQuery({ preset: '7d' }, null, NOW).station_id).toBeUndefined()
  })

  it('valida o período personalizado', () => {
    expect(validatePeriod({ preset: '7d' })).toBeNull()
    expect(validatePeriod({ preset: 'custom', start: '2026-10-10', end: '2026-10-01' })).toMatch(/posterior/)
    expect(validatePeriod({ preset: 'custom', start: '2025-01-01', end: '2026-10-01' })).toMatch(/366/)
    expect(validatePeriod({ preset: 'custom', start: '2026-02-30', end: '2026-03-01' })).toMatch(/Informe/)
    expect(() => periodBounds({ preset: 'custom' })).toThrow()
  })

  it('sugere granularidade por hora até 2 dias', () => {
    expect(suggestedGranularity(periodQuery({ preset: 'today' }, null, NOW))).toBe('hour')
    expect(suggestedGranularity(periodQuery({ preset: '7d' }, null, NOW))).toBe('day')
  })

  it('gera rótulos legíveis', () => {
    expect(periodLabel({ preset: '7d' })).toBe('Últimos 7 dias')
    expect(periodLabel({ preset: 'custom', start: '2026-10-01', end: '2026-10-10' })).toBe('01/10 – 10/10')
  })
})
