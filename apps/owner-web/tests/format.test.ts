import { describe, expect, it } from 'vitest'
import {
  formatCurrency,
  formatDate,
  formatDateTime,
  formatDuration,
  formatEnergy,
  formatNumber,
  formatPercent,
  formatTariff,
  formatTime,
  formatWeekday,
} from '../src/lib/format'
import { parseDecimal, toInputDecimal, validateDuration, validatePower, validatePrice, validateCouponCode, validatePercent } from '../src/lib/validate'

describe('formatação pt-BR', () => {
  it('formata moeda com milhar e vírgula', () => {
    expect(formatCurrency('1234.56')).toBe('R$ 1.234,56')
    expect(formatCurrency(8420)).toBe('R$ 8.420,00')
    expect(formatCurrency('8420.00', { compact: true })).toBe('R$ 8.420')
    expect(formatCurrency('45.76', { compact: true })).toBe('R$ 45,76')
    expect(formatCurrency(null)).toBe('—')
    expect(formatCurrency('abc')).toBe('—')
  })

  it('formata tarifa por kWh com até 4 casas', () => {
    expect(formatTariff('1.8900')).toBe('R$ 1,89/kWh')
    expect(formatTariff('1.2345')).toBe('R$ 1,2345/kWh')
  })

  it('formata energia, números e percentuais', () => {
    expect(formatEnergy('2184.000')).toBe('2.184 kWh')
    expect(formatEnergy('12.345')).toBe('12,3 kWh')
    expect(formatEnergy('0.250')).toBe('0,250 kWh')
    expect(formatEnergy(0)).toBe('0 kWh')
    expect(formatNumber(184)).toBe('184')
    expect(formatNumber(12345)).toBe('12.345')
    expect(formatPercent('23.4')).toBe('23,4%')
    expect(formatPercent(null)).toBe('—')
  })

  it('formata duração', () => {
    expect(formatDuration('42.4')).toBe('42 min')
    expect(formatDuration(60)).toBe('1 h')
    expect(formatDuration('95')).toBe('1 h 35 min')
    expect(formatDuration(null)).toBe('—')
  })

  it('usa o fuso America/Sao_Paulo para datas', () => {
    // 02:30 UTC = 23:30 do dia anterior em São Paulo (UTC-3).
    expect(formatDateTime('2026-10-18T02:30:00Z')).toBe('17/10/2026 23:30')
    expect(formatDate('2026-10-18T02:30:00Z')).toBe('17/10/2026')
    expect(formatTime('2026-10-18T15:05:00Z')).toBe('12:05')
    expect(formatWeekday('2026-10-12T12:00:00-03:00')).toBe('Seg')
    expect(formatDateTime(null)).toBe('—')
    expect(formatDateTime('não é data')).toBe('—')
  })
})

describe('validação dos formulários', () => {
  it('aceita decimais com vírgula ou ponto', () => {
    expect(parseDecimal('1,89')).toBe('1.89')
    expect(parseDecimal('R$ 1.234,5')).toBe('1234.5')
    expect(parseDecimal('22')).toBe('22')
    expect(parseDecimal('abc')).toBeNull()
    expect(parseDecimal('')).toBeNull()
    expect(toInputDecimal('1.8900', 2)).toBe('1,89')
    expect(toInputDecimal('60.000')).toBe('60')
  })

  it('respeita os limites da API', () => {
    expect(validatePrice('1,89').value).toBe('1.89')
    expect(validatePrice('0').value).toBe('0')
    expect(validatePrice('1,23456').error).toBeTruthy()
    expect(validatePrice('20000').error).toBeTruthy()
    expect(validatePower('0').error).toBeTruthy()
    expect(validatePower('7,4').value).toBe('7.4')
    expect(validatePower('1001').error).toBeTruthy()
    expect(validateDuration('60').value).toBe(60)
    expect(validateDuration('0').error).toBeTruthy()
    expect(validateDuration('1441').error).toBeTruthy()
    expect(validateDuration('1.5').error).toBeTruthy()
    expect(validateCouponCode('VERAO10')).toBeNull()
    expect(validateCouponCode('com espaço')).toBeTruthy()
    expect(validatePercent('15').value).toBe(15)
    expect(validatePercent('101').error).toBeTruthy()
  })
})
