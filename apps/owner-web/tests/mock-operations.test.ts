import { describe, expect, it } from 'vitest'
import { buildCascade } from '../src/lib/margin'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

const c = (v: string | null) => Math.round(Number(v) * 100)

describe('mock do painel (modo demonstração)', () => {
  it('o resultado fecha: totais = soma das linhas e cascata coerente', () => {
    const params = new URLSearchParams({ limit: '500' })
    const report = ops.marginReport(params)
    expect(report.total).toBeGreaterThan(50)
    const sum = (key: 'gross' | 'platform_fee' | 'owner_net' | 'revenue_total') => report.items.reduce((t, r) => t + c(r[key]), 0)
    expect(c(report.totals.gross)).toBe(sum('gross'))
    expect(c(report.totals.owner_net)).toBe(sum('owner_net'))
    // Villa Olímpia sem custo: margem total "—" com cobertura parcial.
    expect(report.totals.margin).toBeNull()
    expect(report.totals.coverage.missing_energy_cost).toBeGreaterThan(0)
    const steps = buildCascade(report.totals, '25%')
    expect(steps.find((s) => s.key === 'margin')?.value).toBeNull()
    for (const row of report.items) {
      expect(c(row.revenue_total) - c(row.platform_fee) - c(row.provider_fee)).toBe(c(row.owner_net))
      if (row.margin !== null) expect(c(row.owner_net) - c(row.energy_cost)).toBe(c(row.margin))
    }
  })

  it('com o custo informado em todos os postos, a margem total aparece', () => {
    const villaOlimpia = data.STATIONS[2].id
    ops.putEconomics(villaOlimpia, { energy_cost_per_kwh: '0,90' })
    const report = ops.marginReport(new URLSearchParams())
    expect(report.totals.coverage.missing_energy_cost).toBe(0)
    expect(report.totals.margin).not.toBeNull()
    ops.putEconomics(villaOlimpia, { energy_cost_per_kwh: null })
  })

  it('limite contratado menor reduz o alvo e o excesso aparece até a confirmação', () => {
    const villaLobos = data.STATIONS[0].id
    const before = ops.power(villaLobos)
    const load = Number(before.building_load_kw)
    const after = ops.putPowerSite(villaLobos, { site_limit_kw: (load + 15).toFixed(1) })
    expect(after.available_kw).toBe('15.0')
    expect(after.points.find((p) => p.session)?.session?.target_kw).toBe('15.0')
    expect(Number(after.exceeded_kw)).toBeGreaterThan(0)
    expect(after.decisions[0].trigger).toBe('site_limit_changed')
    ops.putPowerSite(villaLobos, { site_limit_kw: null })
  })

  it('PUT de tarifa parcial é mesclado como na API (rotation sozinho e sugestão da Previsão)', () => {
    const id = data.STATIONS[0].id
    const before = ops.pricing(id).rules
    const next = ops.putPricing(id, { rotation: { enabled: true, start_after_min: 5, grace_minutes: 99 } }).rules
    expect(next.rotation).toEqual({ enabled: true, start_after_min: 5, interval_min: 1, amount: '1.00', max_amount: '30.00' })
    expect(next.demand).toEqual(before.demand)
    expect(next.schedule).toEqual(before.schedule)
    // Sugestão da Previsão (`action.patch`) só com `demand`: a permanência fica igual.
    const suggested = ops.putPricing(id, { demand: { max_increase_percent: 30 } }).rules
    expect(suggested.rotation).toEqual(next.rotation)
    expect(() => ops.putPricing(id, { rotation: { max_amount: '1000.01' } })).toThrow(/1\.000,00/)
    ops.putPricing(id, { rotation: before.rotation })
  })
})

describe('mock: cupons', () => {
  it('o desconto total é só dos cupons (sem resíduo de arredondamento)', () => {
    const report = ops.marginReport(new URLSearchParams())
    expect(report.coupons.discount).toBe(report.totals.discount)
  })
})
