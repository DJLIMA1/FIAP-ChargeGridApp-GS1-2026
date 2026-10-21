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

describe('estação (tela) × carregadores no detalhe do posto', () => {
  // O mock decora os postos (tela, charger_link, screen) ao carregar as operações.
  beforeAll(async () => {
    await import('../src/mock/operations')
  })
  const st = (index = 0) => structuredClone(data.STATIONS[index])
  const point = (code: string, index = 0) => st(index).connectors.find((c) => c.public_code === code)!
  const noop = () => undefined

  it('cartão do carregador: status do carregador, endereço/tipo/potência/limite, tarifa/duração e a tela', async () => {
    const { ChargerCard } = await import('../src/components/station/ChargerCard')
    const html = renderToStaticMarkup(createElement(ChargerCard, { connector: point('CG-002'), onSaved: noop }))
    expect(html).toContain('CG-002')
    expect(html).toMatch(/class="badge green ">Online</)
    expect(html).toContain('Carregador 2 · GoodWe HCA G2 (simulado) · Tipo 2 · 22 kW')
    const order = ['Endereço', 'Tipo de conector', 'Potência nominal', 'Limite', 'Carregador 2 · online', 'Tarifa', 'Duração máxima', 'Salvar carregador']
    const positions = order.map((text) => html.indexOf(text))
    positions.forEach((pos, i) => expect(pos, order[i]).toBeGreaterThan(i ? positions[i - 1] : -1))
    expect(html).toMatch(/data-testid="charger-address"[^>]*value="2"/)
    expect(html).toContain('última leitura agora · lendo 0 kW')
    expect(html).not.toContain('charger-cgaddr') // online: sem a dica do CG_ADDR
    // Sem textos antigos/redundantes.
    expect(html).not.toMatch(/simulação da tela|Dispositivo online|Dispositivo offline|Conector|Modbus TCP na rede/)
    const screen = renderToStaticMarkup(createElement(ChargerCard, { connector: point('CG-001'), onSaved: noop }))
    expect(screen).not.toContain('charger-screen')
    expect(screen).toContain('Carregando')
    expect(screen).toMatch(/lendo \d+(,\d)? kW/)
  })

  it('carregador offline: selo Offline (sem repetir a disponibilidade), última leitura e CG_ADDR', async () => {
    const { ChargerCard } = await import('../src/components/station/ChargerCard')
    const html = renderToStaticMarkup(createElement(ChargerCard, { connector: point('CG-007', 1), onSaved: noop }))
    expect(html.match(/>Offline</g)).toHaveLength(1)
    expect(html).toContain('Carregador 4 · offline')
    expect(html).toContain('última leitura há 3 h')
    expect(html).toContain('No ESP do carregador: CG_ADDR = 4')
    expect(html).not.toContain('charger-screen') // status da central fica em Dados
    const pending = renderToStaticMarkup(createElement(ChargerCard, { connector: point('CG-010', 2), onSaved: noop }))
    expect(pending).toContain('Aguardando a central')
    expect(pending).toMatch(/Carregador 3 · aguardando a central<\/span><span data-testid="charger-cgaddr"> · No ESP do carregador: CG_ADDR = 3/)
    expect(pending).toContain('CG_ADDR = 3')
    expect(pending).toContain('Inativo')
    expect(pending).not.toContain('Desativado') // o interruptor já diz Inativo
  })

  it('campo de endereço: legado sem endereço sugere o próximo livre; API antiga (sem o campo) some', async () => {
    const { ChargerField, ChargerLinkLine } = await import('../src/components/station/ChargerField')
    const legacyNull = { ...point('CG-003'), charger_address: null, charger_link: null }
    const html = renderToStaticMarkup(createElement(ChargerField, { connector: legacyNull, onSaved: noop, suggested: 4 }))
    expect(html).toMatch(/data-testid="charger-address"[^>]*value="4"/)
    expect(html).toContain('sem endereço')
    const legacy = { ...point('CG-003'), charger_address: undefined, charger_link: undefined, screen: undefined }
    expect(renderToStaticMarkup(createElement(ChargerField, { connector: legacy, onSaved: noop }))).toBe('')
    expect(renderToStaticMarkup(createElement(ChargerLinkLine, { connector: legacy }))).toBe('')
    const { ChargerCard } = await import('../src/components/station/ChargerCard')
    expect(renderToStaticMarkup(createElement(ChargerCard, { connector: legacy, onSaved: noop }))).not.toContain('charger-screen')
    const source = read('components/station/ChargerField.tsx')
    expect(source).not.toContain('charger_address: null')
    expect(source).toMatch(/if \(parsed\.error\) return setError\(parsed\.error\)[\s\S]*patchConnector/)
  })

  it('Dados da estação mostram a tela (status, ponto, carregadores, contato, firmware)', async () => {
    const { StationForm } = await import('../src/pages/StationDetail')
    const html = renderToStaticMarkup(createElement(StationForm, { station: st(1), onSaved: noop }))
    expect(html).toContain('Central online')
    expect(html).toMatch(/Central no ponto CG-004 · comanda 4 carregadores · contato agora · firmware 1\.6\.0/)
    expect(html.indexOf('Central online')).toBeLessThan(html.indexOf('Nome da estação'))
    const { ScreenStatus } = await import('../src/components/station/ScreenStatus')
    expect(renderToStaticMarkup(createElement(ScreenStatus, { station: { ...st(), screens: undefined } }))).toBe('')
    expect(renderToStaticMarkup(createElement(ScreenStatus, { station: { ...st(), screens: [], screen_online: null } }))).toContain('Sem central')
    const offline = st()
    offline.screens = offline.screens!.map((s) => ({ ...s, online: false }))
    expect(renderToStaticMarkup(createElement(ScreenStatus, { station: offline }))).toContain('Central offline')
  })

  it('Carregadores: "Adicionar carregador", estação online × carregador offline e a estação offline', async () => {
    const { ChargersCard, StationHealth } = await import('../src/pages/StationDetail')
    const marginal = renderToStaticMarkup(createElement(ChargersCard, { station: st(1), onSaved: noop, onAdded: noop }))
    expect(marginal).toContain('>Carregadores</h2>')
    expect(marginal).toMatch(/data-testid="add-charger"[^>]*>.*Adicionar carregador/)
    expect(marginal).toContain('Carregador CG-007 offline')
    expect(marginal).toContain('Só esse ponto fica indisponível')
    expect(marginal.match(/data-testid="charger-card"/g)).toHaveLength(4)
    expect(marginal).not.toMatch(/Conectores|conector\(es\)/)
    // Villa Lobos: todos online, sem aviso.
    expect(renderToStaticMarkup(createElement(StationHealth, { station: st(0) }))).toBe('')
    const down = { ...st(0), screen_online: false }
    expect(renderToStaticMarkup(createElement(StationHealth, { station: down }))).toContain('Estação offline')
    const empty = renderToStaticMarkup(createElement(ChargersCard, { station: { ...st(0), connectors: [] }, onSaved: noop, onAdded: noop }))
    expect(empty).toContain('Nenhum carregador')
    expect(empty).not.toContain('add-charger')
    const page = read('pages/StationDetail.tsx')
    expect(page).toContain('ep.addCharger(target.id)')
    expect(page).toContain('addChargerErrorText(err)')
    expect(page).toContain('cgAddrHint(added.charger_address)')
    expect(page).toContain('nextFreeChargerAddress(points.map((c) => c.charger_address))')
  })
})
