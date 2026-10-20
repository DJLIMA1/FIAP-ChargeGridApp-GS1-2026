import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { PricingRules } from '../src/api/operations'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  formatCountdown,
  occupancyText,
  overstayCell,
  paymentBadge,
  rotationForm,
  rotationSummary,
  validateRotation,
  withRotation,
} from '../src/lib/overstay'

const savedRules = (): PricingRules => ({
  demand: { enabled: true, max_increase_percent: 30, sensitivity: 'high' },
  schedule: { enabled: true, intervals: [{ start: '22:00', end: '06:00', days: [0, 1, 2, 3, 4], prices: { c1: '1.2000' } }] },
  peak: { enabled: false, start: '18:00', end: '21:00', increase_percent: 20 },
  rotation: { enabled: false, start_after_min: 30, interval_min: 10, amount: '0.20', max_amount: '30.00' },
  future_rule: { kept: true },
})

describe('taxa de permanência: gravação preservando as regras', () => {
  it('lê as chaves antigas e as do contrato', () => {
    expect(rotationForm(savedRules())).toEqual({ enabled: false, grace: '30', interval: '10', amount: '0,20', max: '30,00' })
    expect(rotationForm({ rotation: { enabled: true, grace_minutes: 0, interval_minutes: 5, amount: '2', max_amount: '40' } })).toEqual({ enabled: true, grace: '0', interval: '5', amount: '2,00', max: '40,00' })
    expect(rotationForm(null)).toMatchObject({ enabled: false, grace: '10', interval: '1' })
  })

  it('muda só rotation e devolve demanda, horários e chaves desconhecidas intactos', () => {
    const rules = savedRules()
    const before = structuredClone(rules)
    const { values } = validateRotation({ enabled: true, grace: '10', interval: '1', amount: '1,00', max: '25' })
    const next = withRotation(rules, values!)
    expect(rules).toEqual(before) // não altera o objeto carregado
    expect(next.demand).toEqual(before.demand)
    expect(next.schedule).toEqual(before.schedule)
    expect(next.peak).toEqual(before.peak)
    expect(next.future_rule).toEqual({ kept: true })
    // Formato antigo continua antigo (a API em andamento valida start_after_min/interval_min).
    expect(next.rotation).toEqual({ enabled: true, start_after_min: 10, interval_min: 1, amount: '1.00', max_amount: '25.00' })
  })

  it('grava no formato do contrato quando é o que veio, e nos dois quando nada veio', () => {
    const { values } = validateRotation({ enabled: true, grace: '5', interval: '2', amount: '1', max: '10' })
    expect(withRotation({ rotation: { enabled: false, grace_minutes: 10, interval_minutes: 1, amount: '1.00', max_amount: '30.00' } }, values!).rotation).toEqual({
      enabled: true, grace_minutes: 5, interval_minutes: 2, amount: '1.00', max_amount: '10.00',
    })
    expect(withRotation({ demand: { enabled: false } }, values!)).toEqual({
      demand: { enabled: false },
      rotation: { enabled: true, start_after_min: 5, interval_min: 2, grace_minutes: 5, interval_minutes: 2, amount: '1.00', max_amount: '10.00' },
    })
  })

  it('PUT /stations/{id}/pricing leva as regras inteiras', async () => {
    const bodies: unknown[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      expect(String(input)).toBe('/v1/stations/st-1/pricing')
      expect(init.method).toBe('PUT')
      bodies.push(JSON.parse(String(init.body)))
      return new Response(JSON.stringify({ rules: bodies[0] }), { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    const { values } = validateRotation({ enabled: true, grace: '10', interval: '1', amount: '1,00', max: '30,00' })
    await ep.putPricing('st-1', withRotation(savedRules(), values!))
    expect(Object.keys(bodies[0] as object).sort()).toEqual(['demand', 'future_rule', 'peak', 'rotation', 'schedule'])
    expect((bodies[0] as PricingRules).schedule).toEqual(savedRules().schedule)
  })

  it('valida com os limites da API', () => {
    expect(validateRotation({ enabled: true, grace: '0', interval: '1', amount: '0', max: '0' }).values).toBeTruthy()
    const bad = validateRotation({ enabled: true, grace: '1441', interval: '0', amount: '100,01', max: '1000,01' })
    expect(bad.values).toBeUndefined()
    expect(Object.keys(bad.errors).sort()).toEqual(['amount', 'grace', 'interval', 'max'])
  })

  it('resume os termos em pt-BR', () => {
    expect(rotationSummary({ enabled: true, grace_minutes: 10, interval_minutes: 1, amount: '1.00', max_amount: '30.00' })).toBe('Após a recarga: 10 min de tolerância, depois R$ 1,00/min (máx. R$ 30,00)')
    expect(rotationSummary({ enabled: true, grace_minutes: 0, interval_minutes: 5, amount: '2.50', max_amount: '20.00' })).toBe('Após a recarga: sem tolerância, depois R$ 2,50 a cada 5 min (máx. R$ 20,00)')
    expect(rotationSummary({ enabled: false, grace_minutes: 0, interval_minutes: 1, amount: '0', max_amount: '0' })).toContain('Sem taxa')
  })
})

describe('vaga ocupada e coluna Permanência', () => {
  it('formata a tolerância restante e a taxa acumulada', () => {
    expect(formatCountdown(277)).toBe('04:37')
    expect(formatCountdown(3725)).toBe('1:02:05')
    expect(formatCountdown(-3)).toBe('00:00')
    expect(formatCountdown(null)).toBe('—')
    const base = { session_id: 's', started_at: null, max_fee: '30.00' }
    expect(occupancyText({ ...base, status: 'grace', grace_remaining_seconds: 300, fee_due: '0.00' })).toBe('Tolerância: restam 05:00')
    expect(occupancyText({ ...base, status: 'grace', grace_remaining_seconds: 300, fee_due: '0.00' }, 30)).toBe('Tolerância: restam 04:30')
    expect(occupancyText({ ...base, status: 'billing', grace_remaining_seconds: 0, fee_due: '4.00' })).toBe('Taxa acumulada R$ 4,00 de R$ 30,00')
    expect(occupancyText({ ...base, status: 'capped', grace_remaining_seconds: 0, fee_due: '30.00' })).toBe('Taxa no máximo: R$ 30,00')
  })

  it('mostra "—" quando a API não envia os campos', () => {
    expect(overstayCell({})).toEqual({ text: '—' })
    expect(overstayCell({ overstay: { status: 'none' }, overstay_fee: '0.00', overstay_minutes: 0 })).toEqual({ text: '—' })
    expect(overstayCell({ overstay_fee: '3.00', overstay_minutes: '3' })).toEqual({ text: 'R$ 3,00 · 3 min' })
    expect(overstayCell({ overstay: { status: 'billing', fee_due: '2.00' } })).toMatchObject({ badge: 'Cobrando permanência', text: 'R$ 2,00' })
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
    expect(done).toEqual({ label: 'Cobrado R$ 32,10 (teste) · Devolvido R$ 7,90', tone: 'green', test: true, detail: 'Capturado R$ 32,10 · liberado R$ 7,90' })
    expect(paymentBadge({ id: 'p', status: 'in_use', status_label: 'Pago (teste) · em uso', environment: 'test', amount: '20.00', settlement: null })).toMatchObject({ tone: 'blue', detail: null })
  })
})
