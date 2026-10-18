import { describe, expect, it } from 'vitest'
import type { SessionItem } from '../src/api/types'
import { csvCell, exportFilename, sessionsCsv, sessionsJson } from '../src/lib/exporters'

const row: SessionItem = {
  id: 'e1',
  station_id: 's1',
  station_name: 'Villa Lobos, Pinheiros',
  connector_id: 'c1',
  public_code: 'CG-001',
  status: 'completed',
  created_at: '2026-10-18T12:00:00+00:00',
  started_at: '2026-10-18T12:00:40+00:00',
  ended_at: '2026-10-18T12:40:40+00:00',
  duration_minutes: '40.0',
  energy_kwh: '24.500',
  price_per_kwh: '1.8900',
  discount_percent: 0,
  cost_estimate: '46.3050',
  source: 'measured',
  end_reason: 'requested',
}

describe('exportação de sessões', () => {
  it('gera CSV RFC 4180 com cabeçalho em português', () => {
    const csv = sessionsCsv([row])
    const [header, line] = csv.split('\r\n')
    expect(header.startsWith('ID da sessão,Posto,Ponto,Status')).toBe(true)
    expect(header).toContain('Valor estimado (R$)')
    expect(line).toBe('e1,"Villa Lobos, Pinheiros",CG-001,completed,2026-10-18T12:00:00+00:00,2026-10-18T12:00:40+00:00,2026-10-18T12:40:40+00:00,40.0,24.500,1.8900,0,46.3050,measured,requested')
    expect(csv.endsWith('\r\n')).toBe(true)
  })

  it('neutraliza fórmulas sem alterar números negativos', () => {
    expect(csvCell('=HYPERLINK("x")')).toBe(`"'=HYPERLINK(""x"")"`)
    expect(csvCell('@SUM(A1)')).toBe("'@SUM(A1)")
    expect(csvCell('-12.5')).toBe('-12.5')
    expect(csvCell(null)).toBe('')
    expect(csvCell(true)).toBe('sim')
    expect(csvCell('linha\nnova')).toBe('"linha\nnova"')
  })

  it('gera JSON com o envelope da API', () => {
    const now = new Date('2026-10-18T17:05:00Z')
    const parsed = JSON.parse(sessionsJson([row], { from: 'a', to: 'b', station_id: undefined, q: '' }, now))
    expect(parsed).toMatchObject({ schema_version: 1, dataset: 'sessions', currency: 'BRL', total: 1, timezone: 'America/Sao_Paulo' })
    expect(parsed.filters).toEqual({ from: 'a', to: 'b' })
    expect(parsed.items[0].id).toBe('e1')
    expect(parsed.generated_at).toBe('2026-10-18T17:05:00.000Z')
  })

  it('nomeia o arquivo no horário de São Paulo', () => {
    expect(exportFilename('csv', new Date('2026-10-18T17:05:00Z'))).toBe('chargegrid-sessoes-20261018-1405.csv')
  })
})
