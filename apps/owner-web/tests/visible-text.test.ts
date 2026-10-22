/**
 * Nada visível no painel fala em simulação, demonstração ou pagamento de teste. Renderiza as telas e os
 * componentes que mostram esses textos e varre o código (sem comentários) das páginas e cartões do painel.
 * Identificadores internos (`simulated`, `presentation_mode`) e os rótulos de contrato 'SIMULADO'/'TESTE'
 * (nunca desenhados) continuam valendo.
 */
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { beforeAll, describe, expect, it, vi } from 'vitest'
import type { SessionPayment } from '../src/api/operations'
import type { Station } from '../src/api/types'
import * as data from '../src/mock/data'

const FORBIDDEN = /simulad|simulaç|\bdemo\b|demonstra|modo teste|\bteste\b|modo apresenta|ilustrativ/i

const profile = { presentation_mode: false }
vi.mock('../src/auth/AuthContext', () => ({
  useAuth: () => ({ ep: {}, profile }),
}))

const SOURCES = import.meta.glob<string>('../src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true })

/** Código sem comentários (`//`, `/* *\/`, `{/* *\/}`), mantendo strings, templates e texto JSX. */
function withoutComments(source: string): string {
  let out = ''
  let i = 0
  while (i < source.length) {
    const ch = source[i]
    if (ch === '/' && source[i + 1] === '/') {
      while (i < source.length && source[i] !== '\n') i++
    } else if (ch === '/' && source[i + 1] === '*') {
      const end = source.indexOf('*/', i + 2)
      i = end < 0 ? source.length : end + 2
    } else if (ch === '/' && /[(,=:[!&|?{};]$/.test(out.trimEnd())) {
      // Literal de regex (ex.: o filtro que tira "(teste)" do rótulo da API): não é texto da tela.
      let j = i + 1
      let inClass = false
      while (j < source.length && source[j] !== '\n' && (inClass || source[j] !== '/')) {
        if (source[j] === '[') inClass = true
        else if (source[j] === ']') inClass = false
        j += source[j] === '\\' ? 2 : 1
      }
      out += '/x/'
      i = j + 1
    } else if (ch === "'" || ch === '"' || ch === '`') {
      let j = i + 1
      while (j < source.length && source[j] !== ch && !(ch !== '`' && source[j] === '\n')) j += source[j] === '\\' ? 2 : 1
      out += source.slice(i, j + 1)
      i = j + 1
    } else {
      out += ch
      i++
    }
  }
  return out
}

function offenders(path: string): string[] {
  const code = withoutComments(SOURCES[`../src/${path}`]).replace(/'(?:SIMULADO|TESTE)'/g, "''")
  // Logs de console (ex.: o aviso do modo de desenvolvimento do mock) não aparecem na tela.
  return code
    .split('\n')
    .filter((line) => FORBIDDEN.test(line) && !/^\s*console\.\w+\(/.test(line))
    .map((line) => `${path}: ${line.trim()}`)
}

describe('textos visíveis do painel', () => {
  beforeAll(async () => {
    await import('../src/mock/operations') // decora os postos do mock (carregadores, tela)
  })

  it('o varredor ignora comentários e acha texto em strings e JSX', () => {
    expect(withoutComments("// simulado\nconst a = 'x' /* teste */\n{/* demo */}<b>ok</b>")).toBe("\nconst a = 'x' \n{}<b>ok</b>")
    expect(FORBIDDEN.test(withoutComments("const a = 'Pagamento (teste)'"))).toBe(true)
    expect(withoutComments("s.replace(/\\((?:teste)\\)/g, '')")).toBe("s.replace(/x/g, '')")
  })

  it('páginas, cartões, textos e o mock do painel sem simulado/demo/teste', () => {
    const files = Object.keys(SOURCES).map((key) => key.replace('../src/', ''))
    for (const path of ['pages/Sessions.tsx', 'pages/Result.tsx', 'lib/power.ts', 'lib/margin.ts', 'components/station/PowerCard.tsx',
      'components/station/EconomicsCard.tsx', 'mock/operations.ts', 'mock/index.ts']) expect(files).toContain(path)
    expect(files.flatMap(offenders)).toEqual([])
  })

  it('mock: rótulos de pagamento das sessões e o PDF do Resultado', async () => {
    const ops = await import('../src/mock/operations')
    const labels = data.SESSION_POOL.slice(0, 400).map(ops.decorateSession).flatMap((s) => (s.payment ? [s.payment.status_label ?? ''] : []))
    expect(labels.length).toBeGreaterThan(0)
    expect(labels.filter((label) => FORBIDDEN.test(label))).toEqual([])
    const pdf = new TextDecoder('latin1').decode(ops.marginPdf(new URLSearchParams()))
    expect(pdf).toContain('dados de exemplo')
    expect(pdf).not.toMatch(FORBIDDEN)
  })

  it('apresentação (raiz do site) renderizada', async () => {
    const { default: Landing } = await import('../src/landing/Landing')
    const html = renderToStaticMarkup(createElement(Landing))
    expect(html).toContain('Como o protótipo funciona')
    expect(html).not.toMatch(FORBIDDEN)
  })

  it('totem em Dados da estação, nos dois modos da conta', async () => {
    const { KioskField } = await import('../src/components/station/KioskField')
    const station = (over: Partial<Station> = {}): Station => ({ ...structuredClone(data.STATIONS[0]), ...over })
    for (const presentation of [false, true]) {
      profile.presentation_mode = presentation
      const html = renderToStaticMarkup(createElement(KioskField, { station: station({ kiosk_mode: true }), onSaved: () => undefined }))
      expect(html).toContain('Pagamento:')
      expect(html).not.toMatch(FORBIDDEN)
    }
    profile.presentation_mode = false
  })

  it('cartão do carregador e a lista de carregadores do posto', async () => {
    const { ChargerCard } = await import('../src/components/station/ChargerCard')
    const connector = structuredClone(data.STATIONS[0]).connectors[0]
    const html = renderToStaticMarkup(createElement(ChargerCard, { connector, onSaved: () => undefined }))
    expect(html).toContain('GoodWe HCA G2')
    expect(html).not.toMatch(FORBIDDEN)
  })

  it('selos e rótulos de pagamento, origem da medição e exportação', async () => {
    const { KIOSK_TEXTS, paymentMethodLabel } = await import('../src/lib/kiosk')
    const { paymentBadge } = await import('../src/lib/overstay')
    const { SOURCE_LABELS } = await import('../src/lib/labels')
    const { CHARGER_STATUS_LABEL, chargerStatusText } = await import('../src/lib/charger')
    const payment = (over: Partial<SessionPayment>): SessionPayment =>
      ({ id: 'p', status: 'completed', status_label: 'Cobrado R$ 5,00 (teste)', environment: 'test', amount: '5.00', settlement: null, ...over }) as SessionPayment
    const visible = [
      ...Object.values(KIOSK_TEXTS),
      ...Object.values(SOURCE_LABELS),
      CHARGER_STATUS_LABEL,
      paymentMethodLabel(payment({ provider: 'simulated', method: 'simulated' })),
      paymentMethodLabel(payment({ provider: 'stripe', method: 'card' })),
      paymentBadge(payment({}))!.label,
      paymentBadge(payment({ status_label: 'Pago (simulado) · em uso', status: 'in_use', provider: 'simulated' }))!.label,
      chargerStatusText({ address: 1, label: 'GoodWe HCA G2', simulated: true, link: 'online' } as Parameters<typeof chargerStatusText>[0]),
    ]
    for (const text of visible) expect(text, text).not.toMatch(FORBIDDEN)
    expect(paymentBadge(payment({}))!.label).toBe('Cobrado R$ 5,00')
  })
})
