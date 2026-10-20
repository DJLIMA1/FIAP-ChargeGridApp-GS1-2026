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

  it('consumo da loja reduz o alvo e o excesso aparece até a confirmação', () => {
    const villaLobos = data.STATIONS[0].id
    const before = ops.power(villaLobos)
    expect(before.available_kw).toBe('45.0')
    const after = ops.putBuildingLoad(villaLobos, { building_load_kw: '60' })
    expect(after.available_kw).toBe('15.0')
    expect(after.points.find((p) => p.session)?.session?.target_kw).toBe('15.0')
    expect(Number(after.exceeded_kw)).toBeGreaterThan(0)
    expect(after.decisions[0].trigger).toBe('building_load_changed')
    ops.putBuildingLoad(villaLobos, { building_load_kw: '30' })
  })

  it('PUT de tarifa parcial é recusado (o painel manda as regras inteiras)', () => {
    const id = data.STATIONS[0].id
    expect(() => ops.putPricing(id, { rotation: { enabled: true } })).toThrow(/regras inteiras/)
    const rules = ops.pricing(id).rules
    expect(ops.putPricing(id, rules).rules).toEqual(rules)
  })
})

describe('mock: cupons', () => {
  it('o desconto total é só dos cupons (sem resíduo de arredondamento)', () => {
    const report = ops.marginReport(new URLSearchParams())
    expect(report.coupons.discount).toBe(report.totals.discount)
  })
})
