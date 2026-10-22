import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { PricingRules } from '../src/api/operations'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  overstayCell,
  paymentBadge,
  rotationForm,
  rotationPatch,
  rotationSummary,
  validateRotation,
} from '../src/lib/overstay'

/** `rules` como `GET /stations/{id}/pricing` devolve (`pricing.stored_rules` / `clean_rules`). */
const savedRules = (): PricingRules => ({
  demand: { enabled: true, max_increase_percent: 30, sensitivity: 'high' },
  schedule: { enabled: true, intervals: [{ start: '22:00', end: '06:00', days: [0, 1, 2, 3, 4], prices: { c1: '1.2000' } }] },
  peak: { enabled: false, start: '18:00', end: '21:00', days: [0, 1, 2, 3, 4, 5, 6] },
  rotation: { enabled: false, start_after_min: 30, interval_min: 10, amount: '0.20', max_amount: '30.00' },
})

describe('taxa de permanência: rules.rotation com as chaves reais da API', () => {
  it('lê start_after_min/interval_min (únicas chaves que a API devolve)', () => {
    expect(rotationForm(savedRules())).toEqual({ enabled: false, grace: '30', interval: '10', amount: '0,20', max: '30,00' })
    // Padrão da API (DEFAULT_ROTATION) quando não há regra.
    expect(rotationForm(null)).toEqual({ enabled: false, grace: '10', interval: '1', amount: '1,00', max: '30,00' })
  })

  it('rotationPatch grava exatamente as chaves de clean_rotation (sem grace_minutes/interval_minutes)', () => {
    const { values } = validateRotation({ enabled: true, grace: '10', interval: '1', amount: '1,00', max: '25' })
    const body = rotationPatch(values!)
    expect(body).toEqual({ rotation: { enabled: true, start_after_min: 10, interval_min: 1, amount: '1.00', max_amount: '25.00' } })
    expect(Object.keys(body.rotation!).sort()).toEqual(['amount', 'enabled', 'interval_min', 'max_amount', 'start_after_min'])
  })

  it('PUT /stations/{id}/pricing parcial: só { rotation } (a API mescla o resto)', async () => {
    const bodies: unknown[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      expect(String(input)).toBe('/v1/stations/st-1/pricing')
      expect(init.method).toBe('PUT')
      bodies.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ rules: { ...savedRules(), ...(bodies[0] as object) } }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    const { values } = validateRotation({ enabled: true, grace: '10', interval: '1', amount: '1,00', max: '30,00' })
    const next = await ep.putPricing('st-1', rotationPatch(values!))
    expect(Object.keys(bodies[0] as object)).toEqual(['rotation'])
    expect(rotationForm(next.rules)).toEqual({ enabled: true, grace: '10', interval: '1', amount: '1,00', max: '30,00' })
  })

  it('valida com os limites da API', () => {
    expect(validateRotation({ enabled: true, grace: '0', interval: '1', amount: '0', max: '0' }).values).toBeTruthy()
    const bad = validateRotation({ enabled: true, grace: '1441', interval: '0', amount: '100,01', max: '1000,01' })
    expect(bad.values).toBeUndefined()
    expect(Object.keys(bad.errors).sort()).toEqual(['amount', 'grace', 'interval', 'max'])
  })

  it('resume os termos em pt-BR', () => {
    expect(rotationSummary({ enabled: true, start_after_min: 10, interval_min: 1, amount: '1.00', max_amount: '30.00' })).toBe('Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)')
    expect(rotationSummary({ enabled: true, start_after_min: 0, interval_min: 5, amount: '2.50', max_amount: '20.00' })).toBe('Após a recarga: sem tolerância, depois R$ 2,50 a cada 5 min (máx. R$ 20,00)')
    expect(rotationSummary({ enabled: false, start_after_min: 0, interval_min: 1, amount: '0', max_amount: '0' })).toContain('Sem taxa')
  })
})

describe('coluna Permanência', () => {
  it('coluna Permanência usa overstay_fee (texto) e overstay_minutes (inteiro) de /owner/sessions', () => {
    expect(overstayCell({})).toEqual({ text: '—' })
    // analytics.session_export_row: sem permanência vem "0.00" e 0.
    expect(overstayCell({ overstay_fee: '0.00', overstay_minutes: 0 })).toEqual({ text: '—' })
    expect(overstayCell({ overstay_fee: '2.00', overstay_minutes: 2 })).toEqual({ text: 'R$ 2,00 · 2 min' })
  })
})

describe('selo de pagamento', () => {
  it('usa o rótulo da API, capturado/devolvido e marca teste', () => {
    expect(paymentBadge(null)).toBeNull()
    expect(paymentBadge(undefined)).toBeNull()
    const done = paymentBadge({
      id: 'p', status: 'completed', status_label: 'Cobrado R$ 32,10 (teste) · Devolvido R$ 7,90', environment: 'test', amount: '40.00',
      settlement: { status: 'done', energy_amount: '32.10', overstay_amount: '0.00', fixed_fee: '0.00', charged: '32.10', returned: '7.90', return_kind: 'released', captured: '32.10', refunded: '0.00', waived: '0.00', uncollected: '0.00', below_minimum: false, provider_fee: '1.67', settled_at: null },
    })
    expect(done).toEqual({ label: 'Cobrado R$ 32,10 · Devolvido R$ 7,90', tone: 'green', test: true, detail: 'Capturado R$ 32,10 · liberado R$ 7,90' })
    expect(paymentBadge({ id: 'p', status: 'in_use', status_label: 'Pago (teste) · em uso', environment: 'test', amount: '20.00', settlement: null })).toMatchObject({ tone: 'blue', detail: null })
  })
})
