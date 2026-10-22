/**
 * Formas reais da API (apps/api) que o painel lê e grava. Os objetos abaixo copiam o que
 * o código da API devolve; o mock de demonstração precisa seguir o mesmo formato.
 */
import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { SessionPayment, StationOverstay } from '../src/api/operations'
import type { SessionItem } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import { overstayCell, paymentBadge } from '../src/lib/overstay'
import * as data from '../src/mock/data'
import * as forecastMock from '../src/mock/forecast'
import * as ops from '../src/mock/operations'

function client(respond: (url: string, init: RequestInit) => unknown = () => ({})) {
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
    return new Response(JSON.stringify(respond(String(input), init)), { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
  const store = createTokenStore(storage)
  store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
  return { ep: endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch })), calls }
}

describe('permanência: overstay público do posto (chargegrid_core.overstay.public)', () => {
  it('desligada: enabled false e o resto null; o mock devolve o mesmo', () => {
    const off: StationOverstay = { enabled: false, grace_minutes: null, interval_minutes: null, amount: null, max_amount: null, fee_per_minute: null, version: null, summary: null }
    expect(ops.stationOverstay(data.STATIONS[2].id)).toEqual(off)
  })

  it('ligada: termos + fee_per_minute + summary no texto da API', () => {
    const on = ops.stationOverstay(data.STATIONS[0].id)
    expect(Object.keys(on).sort()).toEqual(['amount', 'enabled', 'fee_per_minute', 'grace_minutes', 'interval_minutes', 'max_amount', 'summary', 'version'])
    expect(on).toMatchObject({ enabled: true, grace_minutes: 10, interval_minutes: 1, amount: '1.00', max_amount: '30.00', fee_per_minute: '1.0000' })
    expect(on.summary).toBe('Após a recarga: 10 min de tolerância; depois R$ 1,00 por minuto, até R$ 30,00.')
    expect(on.version).toMatch(/^ovs-[0-9a-f]{12}$/)
  })
})

describe('permanência: /owner/sessions', () => {
  it('sessões trazem overstay_fee/overstay_minutes, sem bloco overstay (mock igual)', () => {
    const pool = data.SESSION_POOL.slice(0, 200).map(ops.decorateSession)
    for (const item of pool) {
      expect(item).not.toHaveProperty('overstay')
      expect(typeof item.overstay_fee).toBe('string')
      expect(Number.isInteger(item.overstay_minutes)).toBe(true)
    }
    const withFee = pool.find((item) => Number(item.overstay_fee) > 0) as SessionItem
    expect(overstayCell(withFee).text).toMatch(/^R\$ .+ · \d+ min$/)
  })
})

describe('tarifa: PUT parcial também para as sugestões da Previsão', () => {
  it('cada action.patch do mock da Previsão é aceito e não mexe na permanência', () => {
    const id = data.STATIONS[0].id
    const before = ops.pricing(id).rules
    for (const suggestion of forecastMock.forecast(id).suggestions) {
      const next = ops.putPricing(id, suggestion.action.patch).rules
      expect(next.rotation).toEqual(before.rotation)
    }
    ops.putPricing(id, before)
  })
})

describe('pagamento da sessão (payment_row owner=True)', () => {
  it('aceita settlement "none" e o rótulo da API', () => {
    const payment: SessionPayment = {
      id: 'p', status: 'expired', status_label: 'Expirado', environment: 'test', provider: 'fake', origin: 'app', method: null, currency: 'BRL', amount: '20.00',
      energy_cap: '20.00', fixed_fee: '0.00', overstay_reserve: '0.00', price_per_kwh: '1.5000', base_price_per_kwh: '1.5000', demand_multiplier: '1.00', discount_percent: 0,
      max_duration_minutes: 120, max_power_kw: null, connector_id: 'c', session_id: null, expires_at: null, start_deadline: null, authorized_at: null, created_at: null, provider_ref: null,
      settlement: { status: 'none', energy_amount: '0.00', overstay_amount: '0.00', fixed_fee: '0.00', charged: '0.00', returned: '20.00', return_kind: 'released', captured: '0.00', refunded: '0.00', waived: '0.00', uncollected: '0.00', below_minimum: false, provider_fee: null, settled_at: null },
    }
    expect(paymentBadge(payment)).toEqual({ label: 'Expirado', tone: 'gray', test: true, detail: null })
  })
})

describe('potência e resultado: corpos e rotas', () => {
  it('power-site e economics usam as chaves dos schemas da API', async () => {
    const { ep, calls } = client()
    await ep.putPowerSite('st-1', { site_limit_kw: '75.5' })
    await ep.putPowerSite('st-1', { rebalance_enabled: false, store_min_kw: '5.0', store_peak_kw: '12.0', max_power_kw: '40.0', power_limit_notify: true })
    await ep.putPowerSite('st-1', { site_limit_kw: null })
    await ep.putEconomics('st-1', null)
    await ep.power('st-1')
    expect(calls).toEqual([
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { site_limit_kw: '75.5' } },
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { rebalance_enabled: false, store_min_kw: '5.0', store_peak_kw: '12.0', max_power_kw: '40.0', power_limit_notify: true } },
      { url: '/v1/stations/st-1/power-site', method: 'PUT', body: { site_limit_kw: null } },
      { url: '/v1/stations/st-1/economics', method: 'PUT', body: { energy_cost_per_kwh: null } },
      { url: '/v1/stations/st-1/power', method: 'GET', body: undefined },
    ])
  })
})
