import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  availabilityText,
  BUILDING_LOAD_DEBOUNCE_MS,
  debounce,
  formatKw,
  loadSliderMax,
  POWER_STATE,
  powerUsage,
  validateSiteLimit,
} from '../src/lib/power'

describe('formatação de potência', () => {
  it('formata kW em pt-BR com até 1 casa', () => {
    expect(formatKw('6.0')).toBe('6 kW')
    expect(formatKw('28.5')).toBe('28,5 kW')
    expect(formatKw(1.44)).toBe('1,4 kW')
    expect(formatKw(null)).toBe('—')
    expect(formatKw(undefined, 'sem dado')).toBe('sem dado')
  })

  it('soma dos pontos contra o disponível, com excesso transitório', () => {
    expect(powerUsage({ envelope_kw: '30.0', allocated_kw: '30.0', available_kw: '45.0', exceeded_kw: '0.0' })).toMatchObject({ used: 30, available: 45, exceeded: 0, over: false })
    expect(powerUsage({ envelope_kw: '30.0', allocated_kw: '30.0', available_kw: '45.0', exceeded_kw: '0.0' }).percent).toBeCloseTo(66.67, 1)
    const reducing = powerUsage({ envelope_kw: '45.0', allocated_kw: '20.0', available_kw: '20.0', exceeded_kw: '25.0' })
    expect(reducing).toMatchObject({ used: 45, exceeded: 25, over: true, percent: 100 })
    expect(powerUsage({ envelope_kw: null, allocated_kw: '12.0', available_kw: null, exceeded_kw: null })).toMatchObject({ used: 12, available: null, percent: 100, over: false })
  })

  it('explica o disponível e a faixa do controle', () => {
    expect(availabilityText({ site_limit_kw: '75.0', building_load_kw: '30.0', available_kw: '45.0', station_cap_kw: null })).toBe('75 kW contratados − 30 kW da loja = 45 kW para recarga')
    expect(availabilityText({ site_limit_kw: null, building_load_kw: '0.0', available_kw: null, station_cap_kw: '22.0' })).toContain('Sem limite contratado')
    expect(loadSliderMax({ site_limit_kw: '75.0', building_load_kw: '30.0' })).toBe(75)
    expect(loadSliderMax({ site_limit_kw: null, building_load_kw: '0.0' })).toBe(100)
    expect(loadSliderMax({ site_limit_kw: '20.0', building_load_kw: '42.3' })).toBe(43)
  })

  it('valida o limite contratado com os limites da API', () => {
    expect(validateSiteLimit('75,5')).toEqual({ value: '75.5' })
    expect(validateSiteLimit('')).toEqual({ value: null })
    expect(validateSiteLimit('0').error).toBe('Informe um limite maior que zero.')
    expect(validateSiteLimit('10001').error).toBe('O limite contratado vai até 10.000 kW.')
    expect(validateSiteLimit('7,55').error).toBeTruthy()
  })

  it('rotula os estados de potência', () => {
    expect(POWER_STATE.reducing.label).toBe('Reduzindo')
    expect(POWER_STATE.paused.tone).toBe('red')
  })
})

describe('debounce do consumo simulado', () => {
  afterEach(() => vi.useRealTimers())

  it('envia só o último valor depois da pausa', () => {
    vi.useFakeTimers()
    const send = vi.fn()
    const slide = debounce(send, BUILDING_LOAD_DEBOUNCE_MS)
    slide(10)
    slide(12.5)
    vi.advanceTimersByTime(BUILDING_LOAD_DEBOUNCE_MS - 1)
    slide(14)
    expect(send).not.toHaveBeenCalled()
    expect(slide.pending()).toBe(true)
    vi.advanceTimersByTime(BUILDING_LOAD_DEBOUNCE_MS)
    expect(send).toHaveBeenCalledTimes(1)
    expect(send).toHaveBeenCalledWith(14)
    expect(slide.pending()).toBe(false)
  })

  it('flush envia já (ao soltar o controle) e cancel descarta', () => {
    vi.useFakeTimers()
    const send = vi.fn()
    const slide = debounce(send, 300)
    slide(20)
    slide.flush()
    expect(send).toHaveBeenCalledWith(20)
    slide.flush()
    expect(send).toHaveBeenCalledTimes(1)
    slide(25)
    slide.cancel()
    vi.advanceTimersByTime(1000)
    expect(send).toHaveBeenCalledTimes(1)
  })
})
