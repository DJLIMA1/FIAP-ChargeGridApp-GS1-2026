import { describe, expect, it, vi } from 'vitest'
import { createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { ChargerLink, Connector } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import { chargerStatusText, nextFreeChargerAddress, validateChargerAddress } from '../src/lib/charger'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

/** `charger_link` do dono como a API devolve (`chargegrid_core.chargers.link.owner_block`). */
const API_LINK: ChargerLink = {
  model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, host: 'cg-hca-1.local', label: 'GoodWe HCA G2', simulated: true,
  link: 'online', reported: { model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, link: 'online' },
}
const WAITING = 'aguardando carregador (simulação da tela)'

describe('cada conector é um carregador GoodWe: texto do status (igual ao app/core)', () => {
  it('online; offline e pending = aguardando carregador (simulação da tela)', () => {
    expect(chargerStatusText(API_LINK)).toBe('Carregador GoodWe · endereço 1 · online')
    expect(chargerStatusText({ ...API_LINK, address: 3, link: 'offline' })).toBe(`Carregador GoodWe · endereço 3 · ${WAITING}`)
    expect(chargerStatusText({ ...API_LINK, link: 'pending', reported: null })).toBe(`Carregador GoodWe · endereço 1 · ${WAITING}`)
    expect(chargerStatusText({ ...API_LINK, link: 'desconhecido' })).toBe(`Carregador GoodWe · endereço 1 · ${WAITING}`)
    expect(chargerStatusText(null)).toBe('')
    expect(chargerStatusText(undefined)).toBe('')
  })

  it('valida o endereço digitado: inteiro de 1 a 247, nunca vazio', () => {
    expect(validateChargerAddress(' 1 ')).toEqual({ value: 1 })
    expect(validateChargerAddress('247')).toEqual({ value: 247 })
    expect(validateChargerAddress('  ').error).toBe('Endereço do carregador não pode ficar vazio: informe um número de 1 a 247')
    for (const bad of ['0', '248', '1,5', '-1', 'a']) {
      expect(validateChargerAddress(bad).error).toBe('Endereço do carregador deve ser um número inteiro de 1 a 247')
    }
  })

  it('próximo endereço livre do posto: o menor de 1 a 247', () => {
    expect(nextFreeChargerAddress([])).toBe(1)
    expect(nextFreeChargerAddress([1, 2, 3])).toBe(4)
    expect(nextFreeChargerAddress([1, 3, null, undefined])).toBe(2)
    expect(nextFreeChargerAddress(Array.from({ length: 247 }, (_, i) => i + 1))).toBeNull()
  })
})

describe('carregador GoodWe: PATCH /connectors/{id} e o mock', () => {
  it('o cliente envia charger_address (número)', async () => {
    const calls: { url: string; method: string; body: unknown }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
      return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    await ep.patchConnector('c1', { charger_address: 2 })
    expect(calls.map((c) => [c.method, c.url.endsWith('/connectors/c1'), c.body])).toEqual([['PATCH', true, { charger_address: 2 }]])
  })

  it('mock: todos os conectores com endereço 1..N por posto (ordem de criação), aguardando carregador', () => {
    for (const station of data.STATIONS) {
      expect(station.connectors.map((c) => c.charger_address)).toEqual(station.connectors.map((_, i) => i + 1))
      for (const c of station.connectors) {
        expect(c.charger_link).toMatchObject({ address: c.charger_address, host: `cg-hca-${c.charger_address}.local`, link: 'offline' })
        expect(chargerStatusText(c.charger_link)).toBe(`Carregador GoodWe · endereço ${c.charger_address} · ${WAITING}`)
      }
    }
    // Tela online confirma o endereço e reporta o carregador sem resposta; tela offline não reporta.
    const cg2 = data.STATIONS[0].connectors.find((c) => c.public_code === 'CG-002')!
    expect(cg2.charger_link).toEqual({
      ...API_LINK, address: 2, host: 'cg-hca-2.local', link: 'offline',
      reported: { model: 'esp32_bench', transport: 'simulated', address: 2, link: 'offline' },
    })
    const cg7 = data.STATIONS[1].connectors.find((c) => c.public_code === 'CG-007')!
    expect(cg7.online).toBe(false)
    expect(cg7.charger_link?.reported).toBeNull()
  })

  it('mock: conector novo recebe o próximo endereço livre do posto', () => {
    const station = structuredClone(data.STATIONS[0])
    station.connectors[1].charger_address = 5 // CG-002 movido: o 2 ficou livre
    const fresh = { ...structuredClone(station.connectors[2]), id: 'novo', public_code: 'CG-099', charger_address: undefined, charger_link: undefined } as Connector
    station.connectors.push(fresh)
    ops.ensureChargerAddresses(station)
    expect(station.connectors.map((c) => c.charger_address)).toEqual([1, 5, 3, 2])
    expect(fresh.charger_link).toMatchObject({ address: 2, link: 'offline' })
  })

  it('mock: valida 1–247 e vazio (422), endereço único por posto (409), mesmo valor sem efeito', () => {
    const station = data.STATIONS[0]
    const cg3 = station.connectors.find((c) => c.public_code === 'CG-003')!
    for (const empty of [null, undefined]) {
      expect(() => ops.setChargerAddress(cg3.id, empty)).toThrow(
        expect.objectContaining({ status: 422, code: 'invalid_charger_address', message: 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247' }),
      )
    }
    for (const bad of [0, 248, 1.5, '1', true]) {
      expect(() => ops.setChargerAddress(cg3.id, bad)).toThrow(
        expect.objectContaining({ status: 422, code: 'invalid_charger_address', message: 'Endereço do carregador deve ser um número inteiro de 1 a 247' }),
      )
    }
    expect(() => ops.setChargerAddress(cg3.id, 2)).toThrow(expect.objectContaining({ status: 409, code: 'charger_address_taken' }))
    expect(() => ops.setChargerAddress(cg3.id, 2)).toThrow('O carregador 2 já está ligado ao ponto CG-002 deste posto. Escolha outro endereço.')
    expect(ops.setChargerAddress(cg3.id, 3).charger_address).toBe(3) // o mesmo ponto pode regravar o seu
    // Outro posto pode usar o mesmo endereço do primeiro (único só dentro do posto).
    const cg6 = data.STATIONS[1].connectors.find((c) => c.public_code === 'CG-006')!
    expect(() => ops.setChargerAddress(cg6.id, 1)).toThrow(expect.objectContaining({ status: 409 })) // CG-004 é o 1 daquele posto
    expect(ops.setChargerAddress(cg6.id, 10).charger_link).toMatchObject({ address: 10, host: 'cg-hca-10.local', link: 'offline' })
    expect(ops.setChargerAddress(cg3.id, 7).charger_link).toMatchObject({ address: 7, host: 'cg-hca-7.local' })
    ops.setChargerAddress(cg3.id, 3)
    ops.setChargerAddress(cg6.id, 3)
  })
})
