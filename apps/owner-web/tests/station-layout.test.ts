/**
 * Painel alinhado ao app do vendedor: sem "Ao vivo", "Energia do estabelecimento" e "Pagamentos";
 * Potência no detalhe do posto e o totem dentro de Dados da estação.
 */
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { Station } from '../src/api/types'
import * as data from '../src/mock/data'

const profile = { presentation_mode: false }
vi.mock('../src/auth/AuthContext', () => ({
  useAuth: () => ({ ep: {}, profile }),
}))

/** Código-fonte do painel (Vite: `?raw`), sem depender de `node:fs`. */
const SOURCES = import.meta.glob<string>('../src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true })
const exists = (path: string) => `../src/${path}` in SOURCES
const read = (path: string) => {
  const text = SOURCES[`../src/${path}`]
  if (text === undefined) throw new Error(`arquivo ausente: ${path}`)
  return text
}

describe('partes removidas', () => {
  it('Ao vivo, Energia do estabelecimento e Pagamentos não existem mais', () => {
    expect(exists('pages/StationDetail.tsx')).toBe(true)
    for (const file of ['components/LivePanel.tsx', 'components/station/SitePowerCard.tsx', 'components/station/PaymentsCard.tsx', 'components/station/KioskCard.tsx']) {
      expect(exists(file), file).toBe(false)
    }
    const overview = read('pages/Overview.tsx')
    expect(overview).not.toMatch(/LivePanel|Ao vivo/)
    const detail = read('pages/StationDetail.tsx')
    expect(detail).not.toMatch(/SitePowerCard|PaymentsCard|KioskCard|Energia do estabelecimento|prepay_required|kiosk_payments/)
    expect(detail).toContain('<PowerCard station={station} />')
    const endpoints = read('api/endpoints.ts')
    expect(endpoints).not.toMatch(/\/owner\/live|building-load|prepay_required|kiosk_payments/)
    expect(read('mock/index.ts')).not.toMatch(/\/owner\/live|building-load/)
    expect(read('components/Layout.tsx')).not.toMatch(/Ao vivo/)
  })

  it('o mock não tem mais os interruptores de pagamento', () => {
    for (const station of data.STATIONS) {
      expect(station).not.toHaveProperty('prepay_required')
      expect(station).not.toHaveProperty('kiosk_payments')
    }
  })
})

describe('totem em Dados da estação', () => {
  const station = (over: Partial<Station> = {}): Station => ({ ...structuredClone(data.STATIONS[0]), ...over })

  it('Ligado/Desligado e o status numa linha dentro do cartão Dados da estação', async () => {
    const { StationForm } = await import('../src/pages/StationDetail')
    const html = renderToStaticMarkup(createElement(StationForm, { station: station({ kiosk_mode: true }), onSaved: () => undefined }))
    const card = html.indexOf('Dados da estação')
    const kiosk = html.indexOf('Totem de autoatendimento')
    expect(card).toBeGreaterThanOrEqual(0)
    expect(kiosk).toBeGreaterThan(card)
    expect(html.indexOf('Salvar alterações')).toBeGreaterThan(kiosk)
    expect(html).toMatch(/data-testid="kiosk-mode"[^>]*>.*aria-pressed="true"[^>]*>Ligado/)
    expect(html).toContain('<div data-testid="kiosk-status" class="dim" style="font-size:12.5px">Pagamento: Stripe (teste)</div>')
  })

  it('Modo apresentação e estação inativa mudam a linha de status', async () => {
    const { KioskField } = await import('../src/components/station/KioskField')
    profile.presentation_mode = true
    const simulated = renderToStaticMarkup(createElement(KioskField, { station: station({ kiosk_mode: false }), onSaved: () => undefined }))
    expect(simulated).toContain('Pagamento simulado (Modo apresentação)')
    expect(simulated).toMatch(/aria-pressed="true"[^>]*>Desligado/)
    profile.presentation_mode = false
    const inactive = renderToStaticMarkup(createElement(KioskField, { station: station({ active: false, kiosk_mode: false }), onSaved: () => undefined }))
    expect(inactive).toContain('class="red"')
    expect(inactive).toContain('Indisponível: estação inativa')
    const legacy = renderToStaticMarkup(createElement(KioskField, { station: station({ kiosk_mode: undefined }), onSaved: () => undefined }))
    expect(legacy).toBe('')
  })
})

describe('carregador GoodWe no conector (como Conectores → conector no app)', () => {
  // O mock decora os postos (charger_address/charger_link) ao carregar as operações.
  beforeAll(async () => {
    await import('../src/mock/operations')
  })
  const point = (code: string) => structuredClone(data.STATIONS[0].connectors.find((c) => c.public_code === code)!)

  it('campo de endereço (1..N do posto), Salvar e o status numa linha dentro do cartão do conector', async () => {
    const { ChargerField } = await import('../src/components/station/ChargerField')
    const html = renderToStaticMarkup(createElement(ChargerField, { connector: point('CG-002'), onSaved: () => undefined }))
    expect(html).toContain('Carregador GoodWe (endereço)')
    expect(html).toMatch(/data-testid="charger-address"[^>]*value="2"/)
    expect(html).toContain('Salvar')
    expect(html).toContain('Carregador GoodWe · endereço 2 · aguardando carregador (simulação da tela)')
    const online = { ...point('CG-001'), charger_link: { ...point('CG-001').charger_link!, link: 'online' } }
    expect(renderToStaticMarkup(createElement(ChargerField, { connector: online, onSaved: () => undefined }))).toContain('Carregador GoodWe · endereço 1 · online')
    const page = read('pages/StationDetail.tsx')
    expect(page).toContain('<ChargerField connector={connector} onSaved={onSaved} suggested={suggestedAddress} />')
    expect(page).toContain('nextFreeChargerAddress(points.map((c) => c.charger_address))')
  })

  it('sem o carregador opcional: nada de Remover/"carregador externo"; vazio valida no campo sem request', async () => {
    const { ChargerField } = await import('../src/components/station/ChargerField')
    for (const code of ['CG-001', 'CG-002', 'CG-003']) {
      const html = renderToStaticMarkup(createElement(ChargerField, { connector: point(code), onSaved: () => undefined }))
      expect(html).not.toContain('Remover')
      expect(html).not.toMatch(/carregador externo/i)
    }
    const source = read('components/station/ChargerField.tsx')
    expect(source).not.toContain('charger_address: null')
    expect(source).toMatch(/if \(parsed\.error\) return setError\(parsed\.error\)[\s\S]*patchConnector/)
  })

  it('dado legado sem endereço: o próximo livre do posto no campo; API antiga (sem o campo): nada aparece', async () => {
    const { ChargerField } = await import('../src/components/station/ChargerField')
    const legacyNull = { ...point('CG-003'), charger_address: null, charger_link: null }
    const html = renderToStaticMarkup(createElement(ChargerField, { connector: legacyNull, onSaved: () => undefined, suggested: 4 }))
    expect(html).toMatch(/data-testid="charger-address"[^>]*value="4"/)
    expect(html).toContain('sem endereço')
    const legacy = { ...point('CG-003'), charger_address: undefined, charger_link: undefined }
    expect(renderToStaticMarkup(createElement(ChargerField, { connector: legacy, onSaved: () => undefined }))).toBe('')
  })
})
