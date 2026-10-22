/**
 * Remover estação: zona de perigo no fim do detalhe do posto, `DELETE /stations/{id}`, textos dos
 * erros e o mock (some das listas e do painel; o histórico fica).
 */
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  REMOVE_STATION_DETAIL,
  REMOVE_STATION_HINT,
  STATION_BUSY_REMOVE_TEXT,
  removeStationErrorText,
  removeStationQuestion,
  removedStationText,
} from '../src/lib/charger'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

vi.mock('../src/auth/AuthContext', () => ({
  useAuth: () => ({ ep: {}, profile: { presentation_mode: false } }),
}))

const SOURCES = import.meta.glob<string>('../src/**/*.{ts,tsx}', { query: '?raw', import: 'default', eager: true })
const read = (path: string) => SOURCES[`../src/${path}`]!
const noop = () => undefined
const ONLINE_MESSAGE =
  'Restaure a central (Dados da estação → Restaurar) antes de remover a estação: ela volta ao QR de fábrica e pode ser usada em outro posto.'

describe('remover estação: textos', () => {
  it('pergunta, aviso e erros (station_busy com o texto do painel; central_online com o da API)', () => {
    expect(removeStationQuestion({ name: 'Villa Lobos' })).toBe('Remover Villa Lobos?')
    expect(removedStationText({ name: 'Villa Lobos' })).toBe('Estação Villa Lobos removida.')
    expect(REMOVE_STATION_HINT).toBe('Fecha o posto: ele sai do mapa e da sua lista. O histórico de recargas continua.')
    expect(REMOVE_STATION_DETAIL).toBe('A estação sai do mapa e da sua lista. Recargas e recibos continuam no histórico.')
    expect(removeStationErrorText(new ApiError(409, 'station_busy', 'x'))).toBe(STATION_BUSY_REMOVE_TEXT)
    expect(STATION_BUSY_REMOVE_TEXT).toBe('Há recarga, reserva ou pedido do totem em andamento. Encerre antes de remover.')
    expect(removeStationErrorText(new ApiError(409, 'central_online', ONLINE_MESSAGE))).toBe(ONLINE_MESSAGE)
    expect(removeStationErrorText(new Error('x'))).toBe('Não foi possível remover a estação. Tente novamente.')
  })
})

describe('remover estação: rota da API', () => {
  it('DELETE /stations/{id}: 204 resolve; 409 vira ApiError com o código', async () => {
    const responses = [new Response(null, { status: 204 }), Response.json({ error: { code: 'central_online', message: ONLINE_MESSAGE } }, { status: 409 })]
    const calls: { url: string; method: string }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET' })
      return responses.shift()!
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    await expect(ep.removeStation('s 1')).resolves.toBeUndefined()
    expect(calls).toEqual([{ url: '/v1/stations/s%201', method: 'DELETE' }])
    await expect(ep.removeStation('s1')).rejects.toMatchObject({ status: 409, code: 'central_online', message: ONLINE_MESSAGE })
  })
})

describe('remover estação: página', () => {
  it('zona de perigo é o último cartão do detalhe, com botão vermelho e confirmação', async () => {
    const { RemoveStationCard } = await import('../src/pages/StationDetail')
    const html = renderToStaticMarkup(createElement(RemoveStationCard, { station: data.STATIONS[0], onRemoved: noop }))
    expect(html).toContain('Remover estação')
    expect(html).toContain(REMOVE_STATION_HINT)
    expect(html).toMatch(/class="btn btn-danger" data-testid="remove-station"/)
    const page = read('pages/StationDetail.tsx')
    expect(page).toContain('ep.removeStation(station.id)')
    expect(page).toContain('removeStationErrorText(err)')
    expect(page).toContain('removeStationQuestion(station)')
    // Último cartão da página; depois de remover, volta para a lista recarregada.
    const stack = page.slice(page.indexOf('<StationForm station={station}'))
    expect(stack.indexOf('<RemoveStationCard')).toBeGreaterThan(stack.indexOf('<AmenitiesEditor'))
    expect(page).toMatch(/stationRemoved[\s\S]*reloadStations\(\)[\s\S]*navigate\('\/estacoes'/)
  })
})

describe('remover estação: mock', () => {
  it('central online → central_online; ocupada → station_busy; desligada → some das listas, o histórico fica', () => {
    const st = structuredClone(data.STATIONS[1])
    st.id = 'clone-station-rm'
    st.connectors.forEach((c) => (c.id = `srm-${c.id}`))
    data.STATIONS.push(st)
    try {
      st.connectors.forEach((c) => Object.assign(c, { availability_status: 'available', kiosk_in_use: false }))
      expect(() => ops.removeStation(st.id)).toThrow(expect.objectContaining({ status: 409, code: 'central_online', message: ONLINE_MESSAGE }))
      ops.setScreenOnline(st.id, false)
      st.connectors[0].availability_status = 'charging'
      expect(() => ops.removeStation(st.id)).toThrow(expect.objectContaining({ status: 409, code: 'station_busy' }))
      Object.assign(st.connectors[0], { availability_status: 'occupied', kiosk_in_use: true })
      expect(() => ops.removeStation(st.id)).toThrow(expect.objectContaining({ status: 409, code: 'station_busy' }))
      Object.assign(st.connectors[0], { availability_status: 'available', kiosk_in_use: false })
      const before = data.currentStations().length
      const sessions = data.SESSION_POOL.length
      ops.removeStation(st.id)
      expect(data.currentStations()).toHaveLength(before - 1)
      expect(data.currentStations().some((s) => s.id === st.id)).toBe(false)
      expect(st.active).toBe(false)
      expect(data.SESSION_POOL).toHaveLength(sessions)
      expect(() => ops.removeStation(st.id)).toThrow(expect.objectContaining({ status: 404, code: 'not_found' }))
    } finally {
      data.REMOVED_STATIONS.delete(st.id)
      ops.setScreenOnline(st.id, true)
      data.STATIONS.pop()
    }
  })
})
