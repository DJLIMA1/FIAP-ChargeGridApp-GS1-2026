import { describe, expect, it } from 'vitest'
import type { SessionPayment } from '../src/api/operations'
import type { SessionItem } from '../src/api/types'
import { sessionsCsv } from '../src/lib/exporters'
import { CHANNEL_LABELS, kioskStatus, paymentChannel, paymentMethodLabel, serverKioskStatus } from '../src/lib/kiosk'
import { availabilityMeta } from '../src/lib/labels'
import { paymentBadge } from '../src/lib/overstay'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

const session: SessionItem = {
  id: 'e1', station_id: 's1', station_name: 'Villa Lobos', connector_id: 'c1', public_code: 'CG-001', status: 'completed',
  created_at: '2026-10-18T12:00:00+00:00', started_at: null, ended_at: null, duration_minutes: '40.0', energy_kwh: '24.500',
  price_per_kwh: '1.8900', discount_percent: 0, cost_estimate: '46.3050', source: 'measured', end_reason: 'requested',
}

const simulated: SessionPayment = {
  id: 'p1', status: 'completed', status_label: 'Cobrado R$ 5,00 (simulado)', environment: 'test', provider: 'simulated',
  origin: 'kiosk', channel: 'kiosk_totem', method: 'simulated', amount: '50.00', settlement: null,
}

describe('totem de autoatendimento: status do posto', () => {
  it('segue o Modo apresentação da conta do dono', () => {
    expect(kioskStatus({ active: true }, true, false)).toMatchObject({ enabled: true, method: 'simulated', label: 'SIMULADO', reason: null })
    expect(kioskStatus({ active: true }, false, true)).toMatchObject({ enabled: true, method: 'stripe', label: 'TESTE' })
    // Ainda sem /payments/config: supõe a Stripe ligada (a API decide no sync).
    expect(kioskStatus({ active: true }, false)).toMatchObject({ method: 'stripe' })
  })

  it('conta oficial sem Stripe no servidor e posto inativo ficam indisponíveis', () => {
    const missing = kioskStatus({ active: true }, false, false)
    expect(missing).toMatchObject({ enabled: false, method: null, reason: 'payments_unavailable', tone: 'red' })
    expect(missing.text).toBe('Indisponível: pagamentos Stripe não configurados no servidor')
    expect(kioskStatus({ active: false }, true, true)).toMatchObject({ enabled: false, reason: 'point_disabled', text: 'Indisponível: estação inativa' })
  })

  it('status numa linha com os mesmos textos do app', () => {
    expect(kioskStatus({ active: true }, false, true).text).toBe('Pagamento: Stripe')
    expect(kioskStatus({ active: true }, true).text).toBe('Pagamento: sem cobrança')
  })

  it('usa o kiosk_status da API e cai no cálculo se o modo da conta mudou depois', () => {
    const unavailable = { active: true, kiosk_status: { method: null, label: null, reason: 'payments_unavailable' as const } }
    // Sem /payments/config (supõe Stripe), o bloco da API diz indisponível.
    expect(kioskStatus(unavailable, false)).toMatchObject({ enabled: false, reason: 'payments_unavailable' })
    const stripe = { active: true, kiosk_status: { method: 'stripe' as const, label: 'TESTE' as const, reason: null } }
    expect(kioskStatus(stripe, false, false)).toMatchObject({ method: 'stripe', label: 'TESTE' })
    expect(kioskStatus(stripe, true)).toMatchObject({ method: 'simulated' }) // conta virou Modo apresentação
    const simulated = { active: true, kiosk_status: { method: 'simulated' as const, label: 'SIMULADO' as const, reason: null } }
    expect(kioskStatus(simulated, true)).toMatchObject({ label: 'SIMULADO' })
    expect(kioskStatus(simulated, false, true)).toMatchObject({ method: 'stripe' })
    expect(serverKioskStatus(simulated, false)).toBeNull()
    const off = { active: true, kiosk_status: { method: null, label: null, reason: 'point_disabled' as const } }
    expect(kioskStatus(off, true)).toMatchObject({ enabled: false, reason: 'point_disabled' })
    expect(serverKioskStatus({ kiosk_status: undefined }, true)).toBeNull()
  })

  it('ponto travado por pedido do totem aparece como "Em uso no totem"', () => {
    expect(availabilityMeta({ availability_status: 'occupied', kiosk_in_use: true })).toEqual({ label: 'Em uso no totem', tone: 'amber' })
    expect(availabilityMeta({ availability_status: 'occupied', kiosk_in_use: false })?.label).toBe('Em uso')
    expect(availabilityMeta({ availability_status: 'nope' })).toBeNull()
  })
})

describe('canal e método das sessões', () => {
  it('usa payment.channel e cai na origem em API antiga', () => {
    expect(paymentChannel(simulated)).toBe('kiosk_totem')
    expect(paymentChannel({ ...simulated, channel: 'kiosk_qr', provider: 'stripe', method: 'card' })).toBe('kiosk_qr')
    expect(paymentChannel(null)).toBe('app')
    expect(paymentChannel({ ...simulated, channel: undefined })).toBe('kiosk_totem') // simulado só existe no totem
    expect(paymentChannel({ ...simulated, channel: undefined, provider: 'stripe', method: 'card' })).toBe('kiosk')
    expect(paymentMethodLabel(simulated)).toBe('Sem cobrança')
    expect(paymentMethodLabel({ ...simulated, provider: 'stripe', method: 'pix' })).toBe('Stripe')
    expect(paymentMethodLabel(null)).toBe('—')
  })

  it('selo do simulado não leva "teste"', () => {
    expect(paymentBadge(simulated)).toMatchObject({ label: 'Cobrado R$ 5,00', test: false })
    expect(paymentBadge({ ...simulated, provider: 'stripe', method: 'card', status_label: 'Pago' })).toMatchObject({ test: true })
  })

  it('CSV ganha Canal e Pagamento só quando a API manda payment', () => {
    expect(sessionsCsv([session]).split('\r\n')[0].endsWith('Motivo de término')).toBe(true)
    const [header, totem, app] = sessionsCsv([{ ...session, payment: simulated }, { ...session, id: 'e2', payment: null }]).split('\r\n')
    expect(header.endsWith('Motivo de término,Canal,Pagamento')).toBe(true)
    expect(totem.endsWith(`requested,${CHANNEL_LABELS.kiosk_totem},Sem cobrança`)).toBe(true)
    expect(app.endsWith('requested,App,—')).toBe(true)
  })
})

describe('mock do painel (totem 0.8.0)', () => {
  it('posto com o totem ligado, ponto em uso no totem e canais nas sessões', () => {
    const [villaLobos, pinheiros] = data.STATIONS
    expect(villaLobos.kiosk_mode).toBe(true)
    expect(pinheiros.kiosk_mode).toBe(false)
    const held = villaLobos.connectors.find((c) => c.public_code === 'CG-003')!
    expect(held).toMatchObject({ availability_status: 'occupied', kiosk_in_use: true, available: false })
    const channels = new Set<string>()
    let simulatedSeen = false
    for (let i = 0; i < 400; i += 1) {
      const decorated = ops.decorateSession({ ...session, id: `mock-${i.toString(16).padStart(8, '0')}`, station_id: villaLobos.id })
      if (!decorated.payment) continue
      channels.add(String(decorated.payment.channel))
      if (decorated.payment.provider === 'simulated') {
        simulatedSeen = true
        expect(decorated.payment.status_label).not.toMatch(/teste|simulado/i)
        expect(decorated.payment.channel).toBe('kiosk_totem')
      }
    }
    expect([...channels].sort()).toEqual(['app', 'kiosk_qr', 'kiosk_totem'])
    expect(simulatedSeen).toBe(true)
  })
})
