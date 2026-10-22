import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { StationPower } from '../src/api/operations'
import type { Connector } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  budget,
  capText,
  connectorLine,
  connectorPower,
  defaultSiteLimitKw,
  equation,
  formatKw,
  limitsChanges,
  limitsDraft,
  moveCap,
  moveLimit,
  moveStore,
  parseKw,
  powerSummary,
  restoreDefaults,
  scaleMax,
  segments,
  stepFor,
  storeText,
  typedValues,
} from '../src/lib/power'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

/** `GET /stations/{id}/power` como `power.service.station_view` devolve (posto nos padrões). */
const view: StationPower = {
  station_id: 'st-1', rebalance_enabled: true,
  site_limit_kw: '75.000', site_limit_default: true, site_limit_configured_kw: null, site_limit_default_kw: '75.000',
  store_min_kw: '14.000', store_peak_kw: '22.000', store_reserve_kw: '22.000', store_estimate_default: true, store_estimate_label: 'ESTIMATIVA',
  building_load_kw: '22.000', power_limit_notify: false, connectors_total_kw: '82.000', charger_floor_kw: '1.400', chargers_floor_total_kw: '2.800',
  station_cap_kw: null, available_kw: '53.000', allocated_kw: '47.0', envelope_kw: '47.0', exceeded_kw: '0.0', cars: 1,
  points: [
    { connector_id: 'c1', public_code: 'CG-001', power_kw: '60.000', online: true, adjustable: true, charger: null, session: { id: 's1', status: 'charging', target_kw: '47.0', applied_kw: '47.0', envelope_kw: '47.0', power_state: 'applied', reason: null, reason_short: 'Contrat. 75 - loja 22 kW', reason_code: 'site' } },
    { connector_id: 'c2', public_code: 'CG-002', power_kw: '22.000', online: true, adjustable: true, charger: null, session: null },
  ],
  decisions: [],
}

const connector = (over: Partial<Connector>): Connector => ({
  id: 'c2', station_id: 'st-1', public_code: 'CG-002', connector_type: 'Tipo 2', power_kw: '22.000', price_per_kwh: '1.69', max_duration_minutes: 60, active: true, ...over,
})

describe('Potência: padrões e valores digitados', () => {
  it('max(75 kW, pico × 1,3) em passos de 10 kW, como chargegrid_core.site_load', () => {
    expect(defaultSiteLimitKw()).toBe(75)
    expect(defaultSiteLimitKw(22)).toBe(75)
    expect(defaultSiteLimitKw(100)).toBe(130)
    expect(defaultSiteLimitKw(160)).toBe(210)
    expect(defaultSiteLimitKw(750)).toBe(980)
  })

  it('valida o kW digitado', () => {
    expect(parseKw('75,5')).toEqual({ value: 75.5 })
    expect(parseKw('')).toEqual({ value: null })
    expect(parseKw('0').error).toBe('Informe um valor maior que zero.')
    expect(parseKw('0', { allowZero: true })).toEqual({ value: 0 })
    expect(parseKw('10001').error).toBe('Os valores vão até 10.000 kW.')
    expect(parseKw('7,55').error).toBeTruthy()
  })
})

describe('Potência: régua de Limites (mesmas contas do app)', () => {
  it('escala, passos e faixas', () => {
    expect([scaleMax(75), scaleMax(210), scaleMax(980), scaleMax(5), scaleMax(2000)]).toEqual([100, 300, 1500, 25, 2500])
    expect([stepFor(100), stepFor(500), stepFor(2000)]).toEqual([1, 5, 10])
    const draft = limitsDraft(view)
    expect(draft).toMatchObject({ limit: 75, limitDefault: true, min: 14, peak: 22, storeDefault: true, cap: null, total: 82, scale: 100, step: 1 })
    expect(budget(draft)).toBe(53)
    expect(segments(draft)).toEqual([
      { key: 'store_base', kw: 14 }, { key: 'store_peak', kw: 8 }, { key: 'chargers', kw: 53 }, { key: 'above', kw: 25 },
    ])
    expect(segments(draft, 30).slice(2, 4)).toEqual([{ key: 'cars', kw: 30 }, { key: 'chargers', kw: 23 }])
    expect([equation(draft), storeText(draft), capText(draft)]).toEqual(['75 kW contratados − 22 kW de margem da loja', '14 – 22 kW', '53 kW · sem teto'])
  })

  it('arrastes travam e o PUT leva só o que mudou (o padrão nunca vira valor do dono)', () => {
    const original = limitsDraft({ ...view, connectors_total_kw: '44.000' })
    expect(limitsChanges(original, original)).toEqual({})
    let move = moveStore(original, 10, 90)
    expect(move.hint).toContain('aumente o limite contratado')
    expect([move.draft.min, move.draft.peak]).toEqual([10, 73.6])
    move = moveStore(original, 12.2, 30.4)
    expect([move.draft.min, move.draft.peak, budget(move.draft), move.hint]).toEqual([12, 30, 45, null])
    move = moveLimit(move.draft, 20)
    expect([move.draft.limit, move.hint]).toEqual([31.4, 'Para baixar mais o contratado, reduza o pico estimado da loja.'])
    move = moveLimit(move.draft, 90)
    expect(budget(move.draft)).toBe(60)
    move = moveCap(move.draft, 40)
    expect([move.draft.cap, capText(move.draft), budget(move.draft)]).toEqual([40, '40 kW', 40])
    expect(equation(move.draft)).toContain('limitado pelo máximo dos carregadores')
    expect(moveCap(move.draft, 1).hint).toContain('O mínimo é 2,8 kW')
    expect(moveCap(move.draft, 60).draft.cap).toBeNull()  // fim da faixa: sem teto próprio
    const final = { ...moveCap(move.draft, 30).draft, notify: true }
    expect(limitsChanges(final, original)).toEqual({ site_limit_kw: '90.0', store_min_kw: '12.0', store_peak_kw: '30.0', max_power_kw: '30.0', power_limit_notify: true })
    const saved = { ...final, limitDefault: false, storeDefault: false }
    expect(limitsChanges(restoreDefaults(saved), saved)).toEqual({ site_limit_kw: null, store_min_kw: null, store_peak_kw: null, max_power_kw: null })
  })

  it('valores digitados', () => {
    const draft = limitsDraft(view)
    expect(typedValues(draft, { limit: '75', min: '30', peak: '20', cap: '' }).error).toContain('não pode passar do pico')
    expect(typedValues(draft, { limit: '75', min: '10', peak: '74', cap: '' }).error).toContain('ao menos 1,4 kW')
    expect(typedValues(draft, { limit: '75', min: '10', peak: '20', cap: '1' }).error).toContain('pelo menos 2,8 kW')
    const next = typedValues(draft, { limit: '2000', min: '100', peak: '400', cap: '' }).draft!
    expect([next.scale, next.step, budget(next)]).toEqual([2500, 10, 1600])
  })

  it('o PUT power-site leva só as chaves alteradas', async () => {
    const calls: { url: string; method: string; body: unknown }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    const draft = limitsDraft(view)
    await ep.putPowerSite('st-1', limitsChanges(moveLimit(draft, 100).draft, draft))
    await ep.putPowerSite('st-1', { rebalance_enabled: false })
    expect(calls).toEqual([
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { site_limit_kw: '100.0' } },
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { rebalance_enabled: false } },
    ])
    expect('putBuildingLoad' in ep).toBe(false)
  })
})

describe('Potência: resumo e conectores', () => {
  it('disponível, limite (padrão), margem ESTIMADA da loja e carros agora', () => {
    expect(formatKw('28.5')).toBe('28,5 kW')
    expect(powerSummary(view)).toEqual({
      available: '53 kW', limit: '75 kW', limitDetail: 'Padrão (75 kW ou pico × 1,3)',
      store: '−22 kW', storeDetail: 'Pico estimado, reservado o tempo todo (padrão)', cars: '47 kW', carsDetail: '1 carro carregando', over: null,
    })
    const owned = powerSummary({ ...view, site_limit_default: false, store_estimate_default: false, cars: 0, envelope_kw: '0.0', exceeded_kw: '3.0' })
    expect(owned).toMatchObject({ limitDetail: 'Informado por você', storeDetail: 'Pico estimado, reservado o tempo todo', carsDetail: 'Nenhum carro carregando' })
    expect(owned.over).toContain('3 kW')
  })

  it('configurada × efetiva: carregando, livre (até o disponível) e inativo', () => {
    const charging = connectorPower(connector({ id: 'c1', public_code: 'CG-001', power_kw: '60.000', effective_power_kw: '60.000' }), view)
    expect(connectorLine(charging)).toBe('60 kW configurados · 47 kW efetivos')
    const free = connectorPower(connector({ power_limit_kw: '11.000', effective_power_kw: '11.000' }), view)
    expect(connectorLine(free)).toBe('11 kW configurados · até 11 kW efetivos')
    const tight = connectorPower(connector({ effective_power_kw: '22.000' }), { ...view, available_kw: '9.5' })
    expect(connectorLine(tight)).toBe('22 kW configurados · até 9,5 kW efetivos')
    expect(connectorLine(connectorPower(connector({ active: false }), view))).toBe('Inativo: fica fora da divisão do posto')
  })
})

describe('Potência no mock (mesmos padrões da API)', () => {
  it('rebalanceamento ligado, margem ESTIMADA fixa da loja e limite padrão sem valor do dono', () => {
    for (const station of data.STATIONS) {
      const p = ops.power(station.id)
      expect(p.rebalance_enabled).toBe(true)
      expect(p.store_estimate_label).toBe('ESTIMATIVA')
      expect(Number(p.store_reserve_kw)).toBeLessThanOrEqual(Number(p.site_limit_kw) - 1.4)
      if (p.site_limit_default) expect(p.site_limit_configured_kw).toBeNull()
      expect(p).not.toHaveProperty('building_load_simulated')
    }
    const villaLobos = ops.power(data.STATIONS[0].id)
    expect(villaLobos).toMatchObject({ site_limit_kw: '75.0', site_limit_default: true, store_min_kw: '14.0', store_peak_kw: '22.0', store_estimate_default: true })
    expect(Number(villaLobos.available_kw)).toBe(53)
    expect(ops.power(data.STATIONS[0].id).available_kw).toBe(villaLobos.available_kw)  // fixo: nada simulado
  })

  it('PUT parcial valida o estado final; null volta ao padrão', () => {
    const id = data.STATIONS[0].id
    const changed = ops.putPowerSite(id, { store_min_kw: '89.6', store_peak_kw: '160.0' })
    expect(changed).toMatchObject({ site_limit_kw: '210.0', site_limit_default: true, available_kw: '50.0', store_estimate_default: false })
    expect(() => ops.putPowerSite(id, { site_limit_kw: '120' })).toThrow(/deixa 0 kW/)
    expect(ops.power(id).site_limit_kw).toBe('210.0')  // nada gravado
    const capped = ops.putPowerSite(id, { site_limit_kw: '200.0', max_power_kw: '30', power_limit_notify: true })
    expect(capped).toMatchObject({ site_limit_kw: '200.0', available_kw: '30.0', station_cap_kw: '30.000', power_limit_notify: true })
    expect(() => ops.putPowerSite(id, { store_min_kw: '170' })).toThrow(/não pode passar do pico/)
    const back = ops.putPowerSite(id, { site_limit_kw: null, store_min_kw: null, store_peak_kw: null, max_power_kw: null, power_limit_notify: false })
    expect(back).toMatchObject({ site_limit_kw: '75.0', site_limit_default: true, site_limit_configured_kw: null, available_kw: '53.0' })
  })

  it('conectores do posto trazem a potência efetiva', () => {
    for (const c of data.STATIONS.flatMap((s) => s.connectors)) expect(c.effective_power_kw).toMatch(/^\d+\.\d{3}$/)
  })
})
