import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient } from '../src/api/client'
import { endpoints } from '../src/api/endpoints'
import type { ChargerLink, ChargerScreen, Connector, Station } from '../src/api/types'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'
import {
  ADDRESS_FULL_TEXT,
  POINT_BUSY_REMOVE_TEXT,
  SCREEN_CHARGER_TEXT,
  SCREEN_REQUIRED_TEXT,
  addChargerErrorText,
  addChargerTarget,
  cgAddrHint,
  chargerName,
  chargerReadingText,
  chargerState,
  chargerStatusText,
  formatMeasuredPower,
  nextFreeChargerAddress,
  offlineChargers,
  removableCharger,
  removeChargerErrorText,
  removeChargerQuestion,
  stationChargerSummary,
  stationScreenState,
  stationSummary,
  validateChargerAddress,
} from '../src/lib/charger'
import { validatePowerLimit } from '../src/lib/validate'
import * as data from '../src/mock/data'
import * as ops from '../src/mock/operations'

/** `charger_link` do dono como a API devolve (`chargegrid_core.chargers.link.owner_block`). */
const API_LINK: ChargerLink = {
  model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, host: 'cg-hca-1.local', label: 'GoodWe HCA G2', simulated: true,
  link: 'online', last_online_at: '2026-10-21T12:00:00Z', measured_power_w: 7200,
  reported: { model: 'goodwe_hca_g2', transport: 'modbus_tcp', address: 1, link: 'online' },
}
const SCREEN: ChargerScreen = {
  device_id: 'd1', connector_id: 'c1', public_code: 'CG-001', online: true, last_seen: '2026-10-21T12:00:00Z', firmware_version: '1.6.0', role: 'screen', multi_charger: true,
}
const point = (over: Partial<Connector> = {}): Connector => ({
  id: 'c1', station_id: 's1', public_code: 'CG-001', connector_type: 'CCS2', power_kw: '60.000', price_per_kwh: '1.8900', max_duration_minutes: 60, active: true, ...over,
})
const station = (over: Partial<Station> = {}): Station => ({
  id: 's1', owner_id: null, name: 'Posto', address: 'Rua', latitude: 0, longitude: 0, active: true, amenities: [], connectors: [], ...over,
})

function client() {
  const calls: { url: string; method: string; body: unknown }[] = []
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body ? JSON.parse(String(init.body)) : undefined })
    return new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })
  })
  const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
  const store = createTokenStore(storage)
  store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
  return { ep: endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch })), calls }
}

describe('carregador: textos (iguais ao core `chargers.link`)', () => {
  it('status_text: online, offline e aguardando a central; sem "simulação da tela"', () => {
    expect(chargerStatusText(API_LINK)).toBe('Carregador 1 · GoodWe HCA G2 (simulado) · online')
    expect(chargerStatusText({ ...API_LINK, address: 3, link: 'offline' })).toBe('Carregador 3 · GoodWe HCA G2 (simulado) · offline')
    expect(chargerStatusText({ ...API_LINK, link: 'pending', reported: null })).toBe('Carregador 1 · GoodWe HCA G2 (simulado) · aguardando a central')
    expect(chargerStatusText({ ...API_LINK, link: 'desconhecido' })).toBe('Carregador 1 · GoodWe HCA G2 (simulado) · aguardando a central')
    expect(chargerStatusText({ ...API_LINK, simulated: false })).toBe('Carregador 1 · GoodWe HCA G2 · online')
    expect(chargerStatusText(null)).toBe('')
    expect(chargerStatusText(undefined)).toBe('')
    expect(chargerStatusText({ ...API_LINK, link: 'offline' })).not.toMatch(/simulação da tela/)
  })

  it('estado do carregador: charger_link; sem bloco, o online do ponto; API antiga sem nada → null', () => {
    expect(chargerState(point({ charger_link: API_LINK }))).toBe('online')
    expect(chargerState(point({ charger_link: { ...API_LINK, link: 'offline' }, online: true }))).toBe('offline')
    expect(chargerState(point({ charger_link: { ...API_LINK, link: 'x' } }))).toBe('pending')
    expect(chargerState(point({ online: false }))).toBe('offline')
    expect(chargerState(point())).toBeNull()
  })

  it('leitura: última leitura + potência lida (só online); aguardando a central sem leitura = vazio', () => {
    const now = new Date('2026-10-21T12:00:03Z')
    expect(chargerReadingText(API_LINK, now)).toBe('última leitura agora · lendo 7,2 kW')
    expect(chargerReadingText({ ...API_LINK, link: 'offline', last_online_at: '2026-10-21T09:00:00Z', measured_power_w: null }, now)).toBe('última leitura há 3 h')
    expect(chargerReadingText({ ...API_LINK, link: 'offline', last_online_at: null }, now)).toBe('sem leitura ainda')
    expect(chargerReadingText({ ...API_LINK, link: 'pending', last_online_at: null, measured_power_w: null }, now)).toBe('')
    expect(chargerReadingText(null)).toBe('')
    expect(formatMeasuredPower(53600)).toBe('53,6 kW')
    expect(formatMeasuredPower(0)).toBe('0 kW')
    expect(formatMeasuredPower(null)).toBeNull()
    expect(cgAddrHint(4)).toBe('No ESP do carregador: CG_ADDR = 4')
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

  it('limite de potência: vazio = nominal (null), > 0 e até a nominal', () => {
    expect(validatePowerLimit('')).toEqual({ value: null })
    expect(validatePowerLimit('11,5', 22)).toEqual({ value: '11.5' })
    expect(validatePowerLimit('22', 22)).toEqual({ value: '22' })
    expect(validatePowerLimit('23', 22).error).toBe('O limite não pode passar da potência nominal')
    expect(validatePowerLimit('0', 22).error).toBe('O limite deve ser maior que zero')
    expect(validatePowerLimit('abc').error).toBe('Informe o limite em kW ou deixe vazio')
  })
})

describe('estação = a tela; carregador offline não derruba a estação', () => {
  const online = point({ id: 'c1', public_code: 'CG-001', charger_link: API_LINK, online: true, available: true, availability_status: 'available', screen: SCREEN })
  const offline = point({
    id: 'c2', public_code: 'CG-002', online: false, unavailable_reason: 'charger_offline', availability_status: 'offline',
    charger_link: { ...API_LINK, address: 2, link: 'offline' }, screen: { ...SCREEN, role: 'charger' },
  })

  it('status da estação pelo screen_online; API antiga: algum ponto online', () => {
    expect(stationScreenState(station({ screen_online: true, connectors: [offline] }))).toBe('online')
    expect(stationScreenState(station({ screen_online: false, connectors: [online] }))).toBe('offline')
    expect(stationScreenState(station({ screen_online: null, connectors: [online] }))).toBe('none')
    expect(stationScreenState(station({ connectors: [online, offline] }))).toBe('online')
    expect(stationScreenState(station({ connectors: [offline] }))).toBe('offline')
    expect(stationScreenState(station())).toBe('none')
  })

  it('carregadores offline só com a tela online; resumo "N carregadores · M online"', () => {
    const st = station({ screen_online: true, connectors: [online, offline] })
    expect(offlineChargers(st).map((c) => c.public_code)).toEqual(['CG-002'])
    expect(offlineChargers({ ...st, screen_online: false })).toEqual([])
    expect(offlineChargers(station({ screen_online: true, connectors: [online, { ...offline, active: false }] }))).toEqual([]) // inativo não conta
    expect(stationChargerSummary(st)).toBe('2 carregadores · 1 online')
    expect(stationChargerSummary(station({ connectors: [online] }))).toBe('1 carregador · 1 online')
  })

  it('linha da lista de estações: estação online × carregador offline', () => {
    expect(stationSummary(station({ screen_online: true, connectors: [online, offline] }))).toEqual({
      line: 'Estação online · 1 carregador livre · carregador CG-002 offline', tone: 'amber',
    })
    expect(stationSummary(station({ screen_online: true, connectors: [online] })).tone).toBe('green')
    expect(stationSummary(station({ screen_online: false, connectors: [online] }))).toEqual({ line: 'Estação offline · central sem contato', tone: 'red' })
    expect(stationSummary(station({ screen_online: null, connectors: [online] })).line).toBe('Sem central vinculada')
    expect(stationSummary(station({ active: false, connectors: [online] })).line).toBe('Inativa · oculta para motoristas')
    expect(stationSummary(station()).line).toBe('Sem carregadores vinculados')
  })

  it('tela online com todos os carregadores offline não anuncia pontos livres', () => {
    const st = station({ screen_online: true, connectors: [offline, { ...offline, id: 'c3', public_code: 'CG-003' }] })
    expect(stationSummary(st)).toEqual({
      line: 'Estação online · 0 carregadores livres · 2 carregadores offline', tone: 'amber',
    })
  })

  it('conta os livres reais sem incluir ocupado, inativo, offline ou restaurado', () => {
    const available = { ...online, availability_status: 'available', available: true }
    const st = station({ screen_online: true, connectors: [
      available,
      { ...online, id: 'busy', availability_status: 'occupied', available: false },
      { ...available, id: 'inactive', active: false },
      { ...available, id: 'down', online: false },
      { ...available, id: 'retired', retired: true },
    ] })
    expect(stationSummary(st)).toEqual({
      line: 'Estação online · 1 de 4 carregadores em uso · 1 carregador livre', tone: 'green',
    })
  })

  it('API antiga só conta livre quando available é true', () => {
    const legacy = { ...online, availability_status: undefined, available: true }
    const unknown = { ...online, availability_status: undefined, available: undefined }
    expect(stationSummary(station({ screen_online: true, connectors: [legacy, unknown] })).line)
      .toBe('Estação online · 1 carregador livre')
  })

  it('Adicionar carregador usa o ponto da tela; senão qualquer ponto com tela; sem tela, o primeiro', () => {
    const extra = { ...offline, screen: { ...SCREEN, role: 'charger' } }
    expect(addChargerTarget(station({ connectors: [extra, online] }))?.id).toBe('c1')
    expect(addChargerTarget(station({ connectors: [point({ id: 'x', screen: null }), extra] }))?.id).toBe('c2')
    expect(addChargerTarget(station({ connectors: [point({ id: 'x', screen: null })] }))?.id).toBe('x')
    expect(addChargerTarget(station())).toBeNull()
  })

  it('erros do POST: 409 screen_required / charger_address_full com texto claro', () => {
    expect(addChargerErrorText(new ApiError(409, 'screen_required', 'Este ponto não tem central vinculada'))).toBe(SCREEN_REQUIRED_TEXT)
    expect(addChargerErrorText(new ApiError(409, 'charger_address_full', 'Posto sem endereço'))).toBe(ADDRESS_FULL_TEXT)
    expect(addChargerErrorText(new ApiError(404, 'not_found', 'Ponto não encontrado'))).toBe('Ponto não encontrado')
    expect(addChargerErrorText(new Error('x'))).toBe('Não foi possível adicionar o carregador. Tente novamente.')
  })
})

describe('carregador: remover (só os adicionais da central)', () => {
  it('removível pelo papel na central; sem papel, quando a central fica em outro ponto (como o app)', () => {
    expect(removableCharger(point({ screen: SCREEN }))).toBe(false) // o ponto da própria central
    expect(removableCharger(point({ id: 'c2', screen: { ...SCREEN, role: 'charger' } }))).toBe(true)
    expect(removableCharger(point({ id: 'c2', screen: { ...SCREEN, role: 'screen' } }))).toBe(false) // o papel manda
    expect(removableCharger(point({ id: 'c2', screen: { ...SCREEN, role: '' } }))).toBe(true) // c1 é a central
    expect(removableCharger(point({ screen: { ...SCREEN, role: '' } }))).toBe(false)
    expect(removableCharger(point({ id: 'c2', screen: { ...SCREEN, role: '', connector_id: '' } }))).toBe(false)
    expect(removableCharger(point({ id: 'c2', screen: null }))).toBe(false)
    expect(removableCharger(point({ id: 'c2' }))).toBe(false) // API antiga, sem `screen`
    expect(removableCharger(point({ id: 'c2', retired: true, screen: { ...SCREEN, role: 'charger' } }))).toBe(false)
  })

  it('textos: pergunta pelo endereço (sem endereço, o código) e erros do DELETE', () => {
    expect(removeChargerQuestion(point({ charger_address: 3 }))).toBe('Remover carregador 3?')
    expect(removeChargerQuestion(point({ charger_address: null }))).toBe('Remover carregador CG-001?')
    expect(chargerName(point({ charger_address: 2 }))).toBe('Carregador 2')
    expect(removeChargerErrorText(new ApiError(409, 'screen_charger', 'Este é o carregador da própria central; ele não pode ser removido.'))).toBe(SCREEN_CHARGER_TEXT)
    expect(SCREEN_CHARGER_TEXT).toBe('Este é o carregador da própria central e não pode ser removido.')
    expect(removeChargerErrorText(new ApiError(409, 'point_busy', 'Encerre reservas/recargas antes de remover o carregador'))).toBe(POINT_BUSY_REMOVE_TEXT)
    expect(POINT_BUSY_REMOVE_TEXT).toBe('Este carregador tem recarga ou reserva em andamento. Encerre-a antes de remover.')
    expect(removeChargerErrorText(new ApiError(404, 'not_found', 'Ponto não encontrado'))).toBe('Ponto não encontrado')
    expect(removeChargerErrorText(new Error('x'))).toBe('Não foi possível remover o carregador. Tente novamente.')
  })

  it('DELETE /connectors/{id}: 204 sem corpo resolve; erro 409 vira ApiError com o código', async () => {
    const responses = [new Response(null, { status: 204 }), Response.json({ error: { code: 'screen_charger', message: 'central' } }, { status: 409 })]
    const calls: { url: string; method: string; body: unknown }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), method: init.method ?? 'GET', body: init.body })
      return responses.shift()!
    })
    const storage: KeyValueStorage = { getItem: () => null, setItem: () => undefined, removeItem: () => undefined }
    const store = createTokenStore(storage)
    store.setTokens({ access_token: 'a', refresh_token: 'r', expires_in: 3600 }, Date.now())
    const ep = endpoints(createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch }))
    await expect(ep.removeCharger('c 2')).resolves.toBeUndefined()
    expect(calls).toEqual([{ url: '/v1/connectors/c%202', method: 'DELETE', body: undefined }])
    await expect(ep.removeCharger('c1')).rejects.toMatchObject({ status: 409, code: 'screen_charger' })
  })
})

describe('carregador: rotas da API', () => {
  it('PATCH charger_address/power_limit_kw e POST /connectors/{id}/chargers', async () => {
    const { ep, calls } = client()
    await ep.patchConnector('c1', { charger_address: 2 })
    await ep.patchConnector('c1', { power_limit_kw: null })
    await ep.addCharger('c1')
    expect(calls).toEqual([
      { url: '/v1/connectors/c1', method: 'PATCH', body: { charger_address: 2 } },
      { url: '/v1/connectors/c1', method: 'PATCH', body: { power_limit_kw: null } },
      { url: '/v1/connectors/c1/chargers', method: 'POST', body: {} },
    ])
  })
})

describe('mock: estação (tela) × carregadores', () => {
  const code = (c: string) => data.STATIONS.flatMap((s) => s.connectors).find((p) => p.public_code === c)!

  it('cada posto: uma tela online no primeiro ponto comandando todos os carregadores (1..N)', () => {
    for (const st of data.STATIONS) {
      expect(st.connectors.map((c) => c.charger_address)).toEqual(st.connectors.map((_, i) => i + 1))
      expect(st.screen_online).toBe(true)
      expect(st.screens).toHaveLength(1)
      const [screen] = st.screens!
      expect(screen).toMatchObject({ connector_id: st.connectors[0].id, public_code: st.connectors[0].public_code, online: true, multi_charger: true })
      expect(screen.charger_ids).toEqual(st.connectors.map((c) => c.id))
      st.connectors.forEach((c, i) => {
        expect(c.screen).toMatchObject({ device_id: screen.device_id, connector_id: screen.connector_id, role: i === 0 ? 'screen' : 'charger', online: true })
        expect(c.screen_online).toBe(true)
        expect(c.charger_link).toMatchObject({ address: c.charger_address, host: `cg-hca-${c.charger_address}.local`, label: 'GoodWe HCA G2', simulated: true })
      })
    }
  })

  it('carregadores online para a demo, com última leitura e potência lida (a efetiva ao carregar)', () => {
    const cg1 = code('CG-001')
    expect(cg1).toMatchObject({ online: true, unavailable_reason: null, availability_status: 'charging' })
    ops.decorateChargers(data.STATIONS[0]) // como o GET: a potência lida segue a divisão do cartão Potência
    const measured = cg1.charger_link!.measured_power_w!
    expect(cg1.charger_link!.link).toBe('online')
    expect(measured).toBeGreaterThan(0)
    expect(measured).toBeLessThanOrEqual(Math.round(Number(cg1.effective_power_kw) * 1000))
    const target = ops.power(data.STATIONS[0].id).points.find((p) => p.connector_id === cg1.id)?.session?.target_kw
    if (target) expect(measured).toBe(Math.round(Number(target) * 1000))
    expect(Date.now() - Date.parse(cg1.charger_link!.last_online_at!)).toBeLessThan(60_000)
    expect(code('CG-002').charger_link).toMatchObject({ link: 'online', measured_power_w: 0 })
    const online = data.STATIONS.flatMap((s) => s.connectors).filter((c) => c.charger_link?.link === 'online')
    expect(online.length).toBeGreaterThanOrEqual(8)
  })

  it('Marginal Pinheiros: estação online × carregador CG-007 offline; CG-010 aguardando a central', () => {
    const marginal = data.STATIONS[1]
    expect(stationScreenState(marginal)).toBe('online')
    expect(offlineChargers(marginal).map((c) => c.public_code)).toEqual(['CG-007'])
    expect(code('CG-007')).toMatchObject({ online: false, screen_online: true, unavailable_reason: 'charger_offline', availability_status: 'offline', available: false })
    expect(code('CG-007').charger_link).toMatchObject({ link: 'offline', measured_power_w: null, reported: { model: 'esp32_bench', link: 'offline' } })
    expect(code('CG-010').charger_link).toMatchObject({ link: 'pending', last_online_at: null, reported: null })
    expect(stationSummary(marginal).line).toBe('Estação online · 2 de 4 carregadores em uso · 1 carregador livre · carregador CG-007 offline')
    expect(stationSummary(data.STATIONS[2]).line).toBe('Estação online · 1 de 3 carregadores em uso · 0 carregadores livres · 1 com falha') // CG-010 inativo, aguardando a central
  })

  it('ponto novo recebe o próximo endereço livre do posto', () => {
    const st = structuredClone(data.STATIONS[0])
    st.connectors[1].charger_address = 5 // CG-002 movido: o 2 ficou livre
    const fresh = { ...structuredClone(st.connectors[2]), id: 'novo', public_code: 'CG-099', charger_address: undefined, charger_link: undefined } as Connector
    st.connectors.push(fresh)
    ops.ensureChargerAddresses(st)
    expect(st.connectors.map((c) => c.charger_address)).toEqual([1, 5, 3, 2])
    expect(fresh.charger_link).toMatchObject({ address: 2 })
  })

  it('PATCH charger_address: 1–247 e vazio (422), único por posto (409), endereço novo aguarda a tela', () => {
    const st = data.STATIONS[0]
    const cg3 = st.connectors.find((c) => c.public_code === 'CG-003')!
    for (const empty of [null, undefined]) {
      expect(() => ops.setChargerAddress(cg3.id, empty)).toThrow(
        expect.objectContaining({ status: 422, code: 'invalid_charger_address', message: 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247' }),
      )
    }
    for (const bad of [0, 248, 1.5, '1', true]) {
      expect(() => ops.setChargerAddress(cg3.id, bad)).toThrow(expect.objectContaining({ status: 422, code: 'invalid_charger_address' }))
    }
    expect(() => ops.setChargerAddress(cg3.id, 2)).toThrow('O carregador 2 já está ligado ao ponto CG-002 deste posto. Escolha outro endereço.')
    expect(ops.setChargerAddress(cg3.id, 3).charger_link?.link).toBe('online') // mesmo endereço: nada muda
    const cg6 = data.STATIONS[1].connectors.find((c) => c.public_code === 'CG-006')!
    expect(() => ops.setChargerAddress(cg6.id, 1)).toThrow(expect.objectContaining({ status: 409 })) // CG-004 é o 1 daquele posto
    expect(ops.setChargerAddress(cg6.id, 10).charger_link).toMatchObject({ address: 10, host: 'cg-hca-10.local', link: 'pending' })
    expect(cg6).toMatchObject({ online: false, unavailable_reason: 'charger_offline' })
    ops.setChargerAddress(cg6.id, 3)
    ops.setLinkState(cg6.id, 'online')
    ops.decorateChargers(data.STATIONS[1])
    expect(cg6.online).toBe(true)
  })

  it('Adicionar carregador: próximo endereço, inativo, aguardando a central, copiando o ponto da tela', () => {
    const st = data.STATIONS[0]
    const before = st.connectors.length
    const home = st.connectors[0]
    const fresh = ops.addCharger(st.connectors[2].id) // de um carregador adicional: usa a tela dele
    expect(fresh).toMatchObject({
      station_id: st.id, public_code: 'CG-011', charger_address: 4, active: false, availability_status: 'disabled', online: false,
      connector_type: home.connector_type, power_kw: home.power_kw, price_per_kwh: home.price_per_kwh, max_duration_minutes: home.max_duration_minutes,
    })
    expect(fresh.charger_link).toMatchObject({ address: 4, link: 'pending', last_online_at: null })
    expect(fresh.screen).toMatchObject({ connector_id: home.id, role: 'charger' })
    expect(st.connectors).toHaveLength(before + 1)
    expect(st.screens![0].charger_ids).toContain(fresh.id)
    st.connectors.pop()
    ops.decorateChargers(st)
  })

  it('Adicionar carregador: 409 screen_required sem tela; 409 charger_address_full com 1–247 ocupados; 404', () => {
    const st = structuredClone(data.STATIONS[2])
    st.id = 'clone'
    st.connectors.forEach((c) => (c.id = `clone-${c.id}`))
    data.STATIONS.push(st)
    try {
      ops.decorateChargers(st)
      st.connectors[0].screen = null
      expect(() => ops.addCharger(st.connectors[0].id)).toThrow(expect.objectContaining({ status: 409, code: 'screen_required', message: 'Este ponto não tem central vinculada' }))
      ops.decorateChargers(st)
      st.connectors.forEach((c, i) => (c.charger_address = 245 + i))
      st.connectors.push(...Array.from({ length: 244 }, (_, i) => ({ ...structuredClone(st.connectors[0]), id: `fill-${i}`, charger_address: i + 1 })))
      expect(() => ops.addCharger(st.connectors[0].id)).toThrow(expect.objectContaining({ status: 409, code: 'charger_address_full' }))
    } finally {
      data.STATIONS.pop()
    }
    expect(() => ops.addCharger('inexistente')).toThrow(expect.objectContaining({ status: 404 }))
  })

  it('Remover carregador: 409 screen_charger na central, 409 point_busy ocupado; o endereço volta para o próximo', () => {
    const st = structuredClone(data.STATIONS[1])
    st.id = 'clone-rm'
    st.connectors.forEach((c) => (c.id = `rm-${c.id}`))
    data.STATIONS.push(st)
    try {
      ops.decorateChargers(st)
      const [home, busy, extra, kiosk] = st.connectors
      expect(() => ops.removeCharger(home.id)).toThrow(expect.objectContaining({ status: 409, code: 'screen_charger' }))
      for (const status of ['charging', 'reserved']) {
        busy.availability_status = status
        expect(() => ops.removeCharger(busy.id)).toThrow(expect.objectContaining({ status: 409, code: 'point_busy' }))
      }
      Object.assign(kiosk, { availability_status: 'occupied', kiosk_in_use: true })
      expect(() => ops.removeCharger(kiosk.id)).toThrow(expect.objectContaining({ status: 409, code: 'point_busy' }))
      Object.assign(extra, { availability_status: 'available', kiosk_in_use: false })
      const address = extra.charger_address
      const before = st.connectors.length
      ops.removeCharger(extra.id)
      expect(st.connectors).toHaveLength(before - 1)
      expect(st.connectors.some((c) => c.id === extra.id)).toBe(false)
      expect(st.screens![0].charger_ids).not.toContain(extra.id)
      expect(() => ops.removeCharger(extra.id)).toThrow(expect.objectContaining({ status: 404, code: 'not_found' }))
      const fresh = ops.addCharger(home.id)
      expect(fresh.charger_address).toBe(address)
      expect(fresh.public_code).not.toBe(extra.public_code)
    } finally {
      data.STATIONS.pop()
    }
  })
})
