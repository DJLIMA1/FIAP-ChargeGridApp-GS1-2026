import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints, marginExportQuery } from '../src/api/endpoints'
import type { MarginTotals } from '../src/api/operations'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  buildCascade,
  cascadeWidth,
  feeLabel,
  marginExportFilename,
  NOT_PROFIT_TEXT,
  NOT_PROFIT_TITLE,
  stationsMissingCost,
  validateEnergyCost,
} from '../src/lib/margin'

const totals = (patch: Partial<MarginTotals> = {}): MarginTotals => ({
  sessions: 10,
  energy_kwh: '250.000',
  list_value: '440.00',
  schedule_effect: null,
  demand_effect: '60.00',
  gross: '500.00',
  discount: '20.00',
  revenue: '480.00',
  overstay_revenue: null,
  revenue_total: '480.00',
  platform_fee: '120.00',
  provider_fee: null,
  owner_net: '360.00',
  energy_cost: '212.50',
  margin: '147.50',
  margin_covered: '147.50',
  margin_percent: '30.7',
  coverage: { sessions: 10, with_energy_cost: 10, missing_energy_cost: 0 },
  ...patch,
})

describe('cascata do resultado', () => {
  it('segue receita bruta → cupons → comissão → repasse → custo → margem', () => {
    const steps = buildCascade(totals(), '25%')
    expect(steps.map((s) => s.key)).toEqual(['gross', 'discount', 'revenue_total', 'platform_fee', 'owner_net', 'energy_cost', 'margin'])
    expect(steps.map((s) => s.kind)).toEqual(['total', 'minus', 'total', 'minus', 'total', 'minus', 'result'])
    expect(steps.find((s) => s.key === 'platform_fee')?.label).toBe('Comissão da plataforma (25%)')
    expect(steps.find((s) => s.key === 'owner_net')?.label).toBe('Repasse')
    expect(steps.find((s) => s.key === 'margin')).toMatchObject({ label: 'Margem estimada', value: '147.50', missingCost: false, hint: '30,7% da receita cobrada' })
    // A cascata fecha: bruta − cupom − comissão − custo = margem (centavos).
    const c = (v: string | null) => Math.round(Number(v) * 100)
    const [gross, discount, , fee, net, cost, margin] = steps.map((s) => c(s.value))
    expect(gross - discount - fee).toBe(net)
    expect(net - cost).toBe(margin)
  })

  it('com aluguel das centrais: repasse das recargas → aluguel → repasse líquido → custo → resultado', () => {
    const steps = buildCascade(totals({ central_rent: '99.00', centrals: 1, owner_net_after_rent: '261.00', result: '48.50' }), '25%')
    expect(steps.map((s) => s.key)).toEqual(['gross', 'discount', 'revenue_total', 'platform_fee', 'owner_net', 'central_rent', 'owner_net_after_rent', 'energy_cost', 'result'])
    expect(steps.find((s) => s.key === 'central_rent')).toMatchObject({ label: 'Aluguel das centrais (1 central)', kind: 'minus', value: '99.00' })
    expect(steps.find((s) => s.key === 'owner_net')?.label).toBe('Repasse das recargas')
    expect(steps.find((s) => s.key === 'result')).toMatchObject({ label: 'Resultado estimado', value: '48.50' })
    expect(steps.find((s) => s.key === 'result')?.hint).toContain('Margem de contribuição antes do aluguel')
    const c = (v: string | null) => Math.round(Number(v) * 100)
    const value = (key: string) => c(steps.find((s) => s.key === key)!.value)
    expect(value('owner_net') - value('central_rent')).toBe(value('owner_net_after_rent'))
    expect(value('owner_net_after_rent') - value('energy_cost')).toBe(value('result'))
  })

  it('ajuste do pagamento fecha receita bruta → receita cobrada', () => {
    const steps = buildCascade(totals({ payment_adjustment: '-0.40', revenue_total: '479.60' }), '25%')
    expect(steps.map((s) => s.key)).toEqual(['gross', 'discount', 'payment_adjustment', 'revenue_total', 'platform_fee', 'owner_net', 'energy_cost', 'margin'])
    expect(steps.find((s) => s.key === 'payment_adjustment')).toMatchObject({ kind: 'minus', value: '0.40' })
    expect(buildCascade(totals({ payment_adjustment: '0.00' }), '25%').some((s) => s.key === 'payment_adjustment')).toBe(false)
  })

  it('inclui permanência e tarifa do provedor só quando existem', () => {
    const steps = buildCascade(totals({ overstay_revenue: '15.00', revenue_total: '495.00', provider_fee: '9.90', platform_fee: '123.75', owner_net: '361.35' }), '25%')
    expect(steps.map((s) => s.key)).toEqual(['gross', 'discount', 'overstay', 'revenue_total', 'platform_fee', 'provider_fee', 'owner_net', 'energy_cost', 'margin'])
    expect(steps.find((s) => s.key === 'overstay')?.kind).toBe('plus')
  })

  it('custo ausente mostra "—" (nunca zero) com atalho e margem parcial', () => {
    const steps = buildCascade(
      totals({ energy_cost: '120.00', margin: null, margin_covered: '80.00', margin_percent: null, coverage: { sessions: 10, with_energy_cost: 6, missing_energy_cost: 4 } }),
      '25%',
    )
    const cost = steps.find((s) => s.key === 'energy_cost')!
    const margin = steps.find((s) => s.key === 'margin')!
    expect(cost.value).toBeNull()
    expect(cost.missingCost).toBe(true)
    expect(cost.hint).toContain('4 de 10 sessão(ões) sem custo')
    expect(margin.value).toBeNull()
    expect(margin.hint).toBe('Parcial: R$ 80,00 em 6 sessão(ões) com custo')
  })

  it('rótulo da comissão e largura das barras', () => {
    expect(feeLabel([{ platform_fee_percent: '25.00' }, { platform_fee_percent: '25.00' }])).toBe('25%')
    expect(feeLabel([{ platform_fee_percent: '25.00' }, { platform_fee_percent: '20.00' }])).toBe('20% a 25%')
    expect(feeLabel([])).toBe('25%')
    const steps = buildCascade(totals(), '25%')
    expect(cascadeWidth(steps[0], '500.00')).toBe(100)
    expect(cascadeWidth(steps[3], '500.00')).toBe(24)
    expect(cascadeWidth(steps[0], '0.00')).toBe(0)
  })

  it('lista os postos sem custo do kWh', () => {
    const missing = stationsMissingCost({
      stations: [
        { station_id: 'a', station_name: 'A', energy_cost_per_kwh: '0.8500', platform_fee_percent: '25.00', fee_editable: false, currency: 'BRL' },
        { station_id: 'b', station_name: 'B', energy_cost_per_kwh: null, platform_fee_percent: '25.00', fee_editable: false, currency: 'BRL' },
      ],
    })
    expect(missing.map((s) => s.station_id)).toEqual(['b'])
  })
})

describe('faixa "Receita bruta não é lucro"', () => {
  it('explica a margem de contribuição e o que fica de fora', () => {
    expect(NOT_PROFIT_TITLE).toBe('Receita bruta não é lucro')
    expect(NOT_PROFIT_TEXT).toContain('margem de contribuição')
    expect(NOT_PROFIT_TEXT).toContain('comissão da plataforma')
    expect(NOT_PROFIT_TEXT).toContain('custo estimado da energia')
    expect(NOT_PROFIT_TEXT).toContain('não inclui custos fixos')
  })
})

describe('custo do kWh', () => {
  it('aceita vírgula, até 4 casas, vazio = não informado', () => {
    expect(validateEnergyCost('0,85')).toEqual({ value: '0.8500' })
    expect(validateEnergyCost(' 1.2345 ')).toEqual({ value: '1.2345' })
    expect(validateEnergyCost('')).toEqual({ value: null })
    expect(validateEnergyCost('0,12345').error).toBeTruthy()
    expect(validateEnergyCost('abc').error).toBeTruthy()
    expect(validateEnergyCost('101').error).toBe('O custo do kWh vai de R$ 0,00 a R$ 100,00.')
  })
})

function memoryStorage(): KeyValueStorage {
  const data = new Map<string, string>()
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) }
}

describe('exportação do resultado', () => {
  function setup(body: BodyInit, type: string) {
    const calls: { url: string; method: string; auth: string | null }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET', auth: new Headers(init.headers).get('Authorization') })
      return new Response(body, { status: 200, headers: { 'Content-Type': type } })
    })
    const store = createTokenStore(memoryStorage())
    store.setTokens({ access_token: 'access-1', refresh_token: 'refresh-1', expires_in: 3600 }, Date.now())
    const api = createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch })
    return { ep: endpoints(api), calls }
  }

  it('baixa o CSV com período e posto dos filtros, sem paginação, autenticado', async () => {
    const { ep, calls } = setup('ID da sessão,Fim\r\n', 'text/csv; charset=utf-8')
    const blob = await ep.exportMargin('csv', { from: '2026-10-14T03:00:00.000Z', to: '2026-10-20T17:00:00.000Z', station_id: 'st-1' })
    expect(await blob.text()).toBe('ID da sessão,Fim\r\n')
    expect(calls).toHaveLength(1)
    const url = new URL(calls[0].url, 'http://x')
    expect(url.pathname).toBe('/v1/owner/export/margin.csv')
    expect(Object.fromEntries(url.searchParams)).toEqual({ from: '2026-10-14T03:00:00.000Z', to: '2026-10-20T17:00:00.000Z', station_id: 'st-1' })
    expect(calls[0].method).toBe('GET')
    expect(calls[0].auth).toBe('Bearer access-1')
  })

  it('baixa o PDF de todas as estações sem station_id', async () => {
    const { ep, calls } = setup(new Uint8Array([37, 80, 68, 70]), 'application/pdf')
    const blob = await ep.exportMargin('pdf', { from: 'a', to: 'b', station_id: undefined })
    expect(blob.size).toBe(4)
    const url = new URL(calls[0].url, 'http://x')
    expect(url.pathname).toBe('/v1/owner/export/margin.pdf')
    expect(url.searchParams.has('station_id')).toBe(false)
    expect(marginExportQuery({ from: 'a', to: 'b', station_id: '' })).toEqual({ from: 'a', to: 'b', station_id: undefined })
  })

  it('a tela usa a mesma rota paginada para o relatório', async () => {
    const { ep, calls } = setup(JSON.stringify({ items: [] }), 'application/json')
    await ep.margin({ from: 'a', to: 'b', station_id: 'st-1', limit: 50, offset: 100 })
    expect(calls[0].url).toBe('/v1/owner/margin?from=a&to=b&station_id=st-1&limit=50&offset=100')
  })

  it('monta o nome do arquivo no cliente (horário de São Paulo, posto opcional)', () => {
    const now = new Date('2026-10-20T17:05:00Z')
    expect(marginExportFilename('csv', now)).toBe('chargegrid-resultado-20261020-1405.csv')
    expect(marginExportFilename('pdf', now, 'Villa Olímpia / Loja 2')).toBe('chargegrid-resultado-20261020-1405-villa-olimpia-loja-2.pdf')
  })
})
