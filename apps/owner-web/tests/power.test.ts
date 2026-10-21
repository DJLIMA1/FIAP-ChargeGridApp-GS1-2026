import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { StationPower } from '../src/api/operations'
import type { Connector } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  connectorLine,
  connectorPower,
  defaultSiteLimitKw,
  formatKw,
  powerSummary,
  siteChanges,
  siteDraft,
  validateSiteLimit,
} from '../src/lib/power'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

/** `GET /stations/{id}/power` como `power.service.station_view` devolve (posto no limite padrão). */
const view: StationPower = {
  station_id: 'st-1', rebalance_enabled: true,
  site_limit_kw: '75.0', site_limit_default: true, site_limit_configured_kw: null, site_limit_default_kw: '75.0',
  building_load_kw: '18.4', building_load_source: 'simulated', building_load_simulated: true, building_load_mode: 'auto',
  building_load_updated_at: null, building_load_manual_until: null,
  building_profile: 'conveniencia', building_size: 'medio', building_profile_label: 'Loja de conveniência · porte médio', building_peak_kw: '22.0',
  station_cap_kw: null, available_kw: '56.6', allocated_kw: '47.0', envelope_kw: '47.0', exceeded_kw: '0.0', cars: 1,
  points: [
    { connector_id: 'c1', public_code: 'CG-001', power_kw: '60.000', online: true, adjustable: true, charger: null, session: { id: 's1', status: 'charging', target_kw: '47.0', applied_kw: '47.0', envelope_kw: '47.0', power_state: 'applied', reason: null, reason_short: 'Loja 18,4/75 kW', reason_code: 'site' } },
    { connector_id: 'c2', public_code: 'CG-002', power_kw: '22.000', online: true, adjustable: true, charger: null, session: null },
  ],
  decisions: [],
}

const connector = (over: Partial<Connector>): Connector => ({
  id: 'c2', station_id: 'st-1', public_code: 'CG-002', connector_type: 'Tipo 2', power_kw: '22.000', price_per_kwh: '1.69', max_duration_minutes: 60, active: true, ...over,
})

describe('Potência: limite contratado padrão', () => {
  it('max(75 kW, pico × 1,3) em passos de 10 kW, como chargegrid_core.site_load', () => {
    expect(defaultSiteLimitKw('conveniencia', 'medio')).toBe(75)
    expect(defaultSiteLimitKw('supermercado', 'medio')).toBe(130)
    expect(defaultSiteLimitKw('supermercado', 'grande')).toBe(210)
    expect(defaultSiteLimitKw('shopping', 'medio')).toBe(980)
    expect(defaultSiteLimitKw('padaria', 'grande')).toBe(100)
    expect(defaultSiteLimitKw(null, undefined)).toBe(75)
    expect(defaultSiteLimitKw('desconhecido', 'xl')).toBe(75)
  })

  it('valida o limite digitado; vazio = padrão', () => {
    expect(validateSiteLimit('75,5')).toEqual({ value: '75.5' })
    expect(validateSiteLimit('')).toEqual({ value: null })
    expect(validateSiteLimit('0').error).toBe('Informe um limite maior que zero.')
    expect(validateSiteLimit('10001').error).toBe('O limite contratado vai até 10.000 kW.')
    expect(validateSiteLimit('7,55').error).toBeTruthy()
  })
})

describe('Potência: não grava o padrão como valor do dono', () => {
  it('o campo começa vazio no padrão e nada é enviado sem mudança', () => {
    const draft = siteDraft(view)
    expect(draft).toEqual({ limit: '', profile: 'conveniencia', size: 'medio' })
    expect(siteChanges(view, draft).body).toEqual({})
  })

  it('mudar só o tipo/porte não envia site_limit_kw', () => {
    const { body } = siteChanges(view, { limit: '', profile: 'supermercado', size: 'grande' })
    expect(body).toEqual({ building_profile: 'supermercado', building_size: 'grande' })
    expect(body).not.toHaveProperty('site_limit_kw')
  })

  it('envia o limite só quando o dono altera; vazio volta ao padrão (null)', () => {
    expect(siteChanges(view, { ...siteDraft(view), limit: '90' }).body).toEqual({ site_limit_kw: '90.0' })
    const owned = { ...view, site_limit_configured_kw: '150.0', site_limit_default: false }
    expect(siteDraft(owned).limit).toBe('150')
    expect(siteChanges(owned, { ...siteDraft(owned), limit: '' }).body).toEqual({ site_limit_kw: null })
    expect(siteChanges(owned, { ...siteDraft(owned), limit: '150,0' }).body).toEqual({})
    expect(siteChanges(owned, { ...siteDraft(owned), limit: 'abc' }).error).toBeTruthy()
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
    await ep.putPowerSite('st-1', siteChanges(view, { limit: '', profile: 'padaria', size: 'medio' }).body)
    await ep.putPowerSite('st-1', { rebalance_enabled: false })
    expect(calls).toEqual([
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { building_profile: 'padaria' } },
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { rebalance_enabled: false } },
    ])
    expect('putBuildingLoad' in ep).toBe(false)
  })
})

describe('Potência: resumo e conectores', () => {
  it('disponível, limite (padrão), loja SIMULADA pelo tipo e carros agora', () => {
    expect(formatKw('28.5')).toBe('28,5 kW')
    expect(powerSummary(view)).toEqual({
      available: '56,6 kW', limit: '75 kW', limitDetail: 'Padrão para o tipo de estabelecimento',
      load: '18,4 kW', loadDetail: 'Loja de conveniência', cars: '47 kW', carsDetail: '1 carro carregando', over: null,
    })
    const owned = powerSummary({ ...view, site_limit_default: false, building_load_mode: 'manual', cars: 0, envelope_kw: '0.0', exceeded_kw: '3.0' })
    expect(owned).toMatchObject({ limitDetail: 'Informado por você', loadDetail: 'Valor do simulador (30 min)', carsDetail: 'Nenhum carro carregando' })
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
  it('rebalanceamento ligado, loja SIMULADA e limite padrão sem valor do dono', () => {
    for (const station of data.STATIONS) {
      const p = ops.power(station.id)
      expect(p.rebalance_enabled).toBe(true)
      expect(p.building_load_simulated).toBe(true)
      expect(Number(p.building_load_kw)).toBeLessThanOrEqual(Number(p.site_limit_kw) * 0.85)
      if (p.site_limit_default) expect(p.site_limit_configured_kw).toBeNull()
    }
    const villaLobos = ops.power(data.STATIONS[0].id)
    expect(villaLobos).toMatchObject({ site_limit_kw: '75.0', site_limit_default: true, building_profile: 'conveniencia', building_size: 'medio' })
    expect(Number(villaLobos.available_kw)).toBeCloseTo(75 - Number(villaLobos.building_load_kw), 5)
  })

  it('PUT parcial: tipo/porte mudam o padrão; null volta ao padrão', () => {
    const id = data.STATIONS[0].id
    const changed = ops.putPowerSite(id, { building_profile: 'supermercado', building_size: 'grande' })
    expect(changed).toMatchObject({ site_limit_kw: '210.0', site_limit_default: true, site_limit_configured_kw: null })
    const owned = ops.putPowerSite(id, { site_limit_kw: '90.0' })
    expect(owned).toMatchObject({ site_limit_kw: '90.0', site_limit_default: false, site_limit_configured_kw: '90.0' })
    const back = ops.putPowerSite(id, { site_limit_kw: null, building_profile: 'conveniencia', building_size: 'medio' })
    expect(back).toMatchObject({ site_limit_kw: '75.0', site_limit_default: true, site_limit_configured_kw: null })
    expect(() => ops.putPowerSite(id, { building_profile: 'castelo' })).toThrow()
  })

  it('conectores do posto trazem a potência efetiva', () => {
    for (const c of data.STATIONS.flatMap((s) => s.connectors)) expect(c.effective_power_kw).toMatch(/^\d+\.\d{3}$/)
  })
})
