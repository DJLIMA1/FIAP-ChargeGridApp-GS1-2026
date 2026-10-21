import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { ChargerLink } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import { chargerStatusText, validateChargerAddress } from '../src/lib/charger'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

/** `charger_link` do dono como a API devolve (`chargegrid_core.chargers.link.owner_block`). */
const API_LINK: ChargerLink = {
  model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, host: 'cg-hca-1.local', label: 'GoodWe HCA G2', simulated: true,
  link: 'online', reported: { model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, link: 'online' },
}

describe('carregador GoodWe ligado à tela: texto do status (igual ao app)', () => {
  it('online, offline e aguardando a tela', () => {
    expect(chargerStatusText(API_LINK)).toBe('Carregador 1 · GoodWe HCA G2 (simulado) · online')
    expect(chargerStatusText({ ...API_LINK, address: 3, link: 'offline' })).toBe('Carregador 3 · GoodWe HCA G2 (simulado) · offline')
    expect(chargerStatusText({ ...API_LINK, link: 'pending', reported: null })).toBe('Carregador 1 · GoodWe HCA G2 (simulado) · aguardando a tela')
    expect(chargerStatusText({ ...API_LINK, simulated: false })).toBe('Carregador 1 · GoodWe HCA G2 · online')
    expect(chargerStatusText(null)).toBe('')
    expect(chargerStatusText(undefined)).toBe('')
  })

  it('valida o endereço digitado: inteiro de 1 a 247', () => {
    expect(validateChargerAddress(' 1 ')).toEqual({ value: 1 })
    expect(validateChargerAddress('247')).toEqual({ value: 247 })
    for (const bad of ['', '0', '248', '1,5', '-1', 'a']) expect(validateChargerAddress(bad).error).toBeTruthy()
  })
})

describe('carregador GoodWe: PATCH /connectors/{id} e o mock', () => {
  it('o cliente envia charger_address (número) e null para remover', async () => {
    const calls: { url: string; method: string; body: unknown }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    await ep.patchConnector('c1', { charger_address: 1 })
    await ep.patchConnector('c1', { charger_address: null })
    expect(calls.map((c) => [c.method, c.url.endsWith('/connectors/c1'), c.body])).toEqual([
      ['PATCH', true, { charger_address: 1 }],
      ['PATCH', true, { charger_address: null }],
    ])
  })

  it('mock: CG-002 no endereço 1, online, no formato da API; os outros sem carregador', () => {
    const station = data.STATIONS[0]
    const cg2 = station.connectors.find((c) => c.public_code === 'CG-002')!
    expect(cg2.charger_address).toBe(1)
    expect(cg2.charger_link).toEqual(API_LINK)
    const cg3 = station.connectors.find((c) => c.public_code === 'CG-003')!
    expect(cg3.charger_address).toBeNull()
    expect(cg3.charger_link).toBeNull()
  })

  it('mock: valida 1–247, endereço único por posto (409) e remove com null', () => {
    const station = data.STATIONS[0]
    const cg2 = station.connectors.find((c) => c.public_code === 'CG-002')!
    const cg3 = station.connectors.find((c) => c.public_code === 'CG-003')!
    for (const bad of [0, 248, 1.5, '1', true]) {
      expect(() => ops.setChargerAddress(cg3.id, bad)).toThrow(expect.objectContaining({ status: 422, code: 'invalid_charger_address' }))
    }
    expect(() => ops.setChargerAddress(cg3.id, 1)).toThrow(expect.objectContaining({ status: 409, code: 'charger_address_taken' }))
    expect(() => ops.setChargerAddress(cg3.id, 1)).toThrow('O carregador 1 já está ligado ao ponto CG-002 deste posto. Escolha outro endereço.')
    // Outro posto pode usar o mesmo endereço.
    const other = data.STATIONS[1].connectors.find((c) => c.public_code === 'CG-006')!
    expect(ops.setChargerAddress(other.id, 1).charger_link?.address).toBe(1)
    ops.setChargerAddress(other.id, null)
    expect(ops.setChargerAddress(cg3.id, 2).charger_link).toMatchObject({ address: 2, host: 'cg-hca-2.local', link: 'online' })
    const removed = ops.setChargerAddress(cg3.id, null)
    expect(removed.charger_address).toBeNull()
    expect(removed.charger_link).toBeNull()
    expect(ops.setChargerAddress(cg2.id, 1).charger_address).toBe(1) // o mesmo ponto pode regravar o seu
  })
})
