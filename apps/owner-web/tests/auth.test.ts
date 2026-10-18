import { describe, expect, it, vi } from 'vitest'
import { ApiError, buildQuery, createApiClient } from '../src/api/client'
import { createTokenStore, REFRESH_KEY, type KeyValueStorage } from '../src/auth/tokens'
import { accessFor, isVendor } from '../src/auth/vendor'

function memoryStorage(): KeyValueStorage & { data: Map<string, string> } {
  const data = new Map<string, string>()
  return { data, getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) }
}

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
const tokens = (n: number) => ({ access_token: `access-${n}`, refresh_token: `refresh-${n}`, expires_in: 3600 })

type Handler = (url: string, init: RequestInit) => Response | Promise<Response>
function setup(handler: Handler, storage = memoryStorage()) {
  const calls: { url: string; auth: string | null; body?: string }[] = []
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = String(input)
    calls.push({ url, auth: new Headers(init.headers).get('Authorization'), body: init.body as string | undefined })
    return handler(url, init)
  })
  const store = createTokenStore(storage)
  const onAuthLost = vi.fn()
  const api = createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch, onAuthLost })
  return { api, store, storage, calls, onAuthLost, fetchImpl }
}

describe('tokens', () => {
  it('guarda o refresh token no storage e o access token só em memória', () => {
    const storage = memoryStorage()
    const store = createTokenStore(storage)
    store.setTokens(tokens(1), 1_000)
    expect(storage.data.get(REFRESH_KEY)).toBe('refresh-1')
    expect([...storage.data.values()]).not.toContain('access-1')
    expect(store.getAccess()).toBe('access-1')
    expect(store.getExpiry()).toBe(1_000 + 3_600_000)
    store.clear()
    expect(store.getRefresh()).toBeNull()
    expect(storage.data.size).toBe(0)
  })

  it('funciona quando o storage lança exceção (modo privado)', () => {
    const broken: KeyValueStorage = {
      getItem: () => {
        throw new Error('blocked')
      },
      setItem: () => {
        throw new Error('blocked')
      },
      removeItem: () => {
        throw new Error('blocked')
      },
    }
    const store = createTokenStore(broken)
    expect(store.getRefresh()).toBeNull()
    store.setTokens(tokens(2))
    expect(store.getRefresh()).toBe('refresh-2')
    expect(() => store.clear()).not.toThrow()
  })
})

describe('cliente da API', () => {
  it('monta a query ignorando vazios', () => {
    expect(buildQuery({ from: '2026-10-01T03:00:00.000Z', station_id: undefined, q: '', limit: 25 })).toBe('?from=2026-10-01T03%3A00%3A00.000Z&limit=25')
    expect(buildQuery({})).toBe('')
  })

  it('faz login e envia o Bearer nas chamadas seguintes', async () => {
    const { api, calls } = setup((url) => (url.endsWith('/auth/login') ? json(tokens(1)) : json({ ok: true })))
    await api.login('dono@chargegrid.com', 'segredo')
    await api.get('/me')
    expect(calls[0].url).toBe('/v1/auth/login')
    expect(calls[0].auth).toBeNull()
    expect(JSON.parse(calls[0].body!)).toEqual({ email: 'dono@chargegrid.com', password: 'segredo' })
    expect(calls[1].auth).toBe('Bearer access-1')
  })

  it('propaga a mensagem de erro da API no login', async () => {
    const { api } = setup(() => json({ error: { code: 'auth_rejected', message: 'Credenciais ou código inválidos' } }, 401))
    await expect(api.login('x@y.com', 'errada')).rejects.toMatchObject({ status: 401, code: 'auth_rejected', message: 'Credenciais ou código inválidos' })
  })

  it('renova o token uma vez em 401 e repete a requisição', async () => {
    let refreshed = false
    const { api, store, calls, onAuthLost } = setup((url, init) => {
      if (url.endsWith('/auth/refresh')) {
        refreshed = true
        return json(tokens(2))
      }
      const auth = new Headers(init.headers).get('Authorization')
      return auth === 'Bearer access-2' ? json({ name: 'João' }) : json({ error: { code: 'unauthorized' } }, 401)
    })
    store.setTokens(tokens(1))
    await expect(api.get('/me')).resolves.toEqual({ name: 'João' })
    expect(refreshed).toBe(true)
    expect(calls.map((c) => c.url)).toEqual(['/v1/me', '/v1/auth/refresh', '/v1/me'])
    expect(JSON.parse(calls[1].body!)).toEqual({ refresh_token: 'refresh-1' })
    expect(store.getRefresh()).toBe('refresh-2')
    expect(onAuthLost).not.toHaveBeenCalled()
  })

  it('encerra a sessão quando o refresh é recusado', async () => {
    const { api, store, onAuthLost } = setup((url) => (url.endsWith('/auth/refresh') ? json({ error: { code: 'auth_rejected' } }, 401) : json({}, 401)))
    store.setTokens(tokens(1))
    await expect(api.get('/me')).rejects.toMatchObject({ status: 401, code: 'session_expired' })
    expect(onAuthLost).toHaveBeenCalledTimes(1)
    expect(store.getRefresh()).toBeNull()
    expect(store.getAccess()).toBeNull()
  })

  it('não entra em laço se a repetição também der 401', async () => {
    const { api, store, calls, onAuthLost } = setup((url) => (url.endsWith('/auth/refresh') ? json(tokens(2)) : json({}, 401)))
    store.setTokens(tokens(1))
    await expect(api.get('/owner/overview')).rejects.toBeInstanceOf(ApiError)
    expect(calls.filter((c) => c.url.endsWith('/auth/refresh'))).toHaveLength(1)
    expect(calls).toHaveLength(3)
    expect(onAuthLost).toHaveBeenCalledTimes(1)
  })

  it('compartilha um único refresh entre requisições simultâneas', async () => {
    let refreshes = 0
    const { api, store } = setup(async (url, init) => {
      if (url.endsWith('/auth/refresh')) {
        refreshes += 1
        await new Promise((r) => setTimeout(r, 10))
        return json(tokens(2))
      }
      return new Headers(init.headers).get('Authorization') === 'Bearer access-2' ? json({ ok: url }) : json({}, 401)
    })
    store.setTokens(tokens(1))
    const results = await Promise.all([api.get('/owner/overview'), api.get('/owner/heatmap'), api.get('/owner/alerts')])
    expect(results).toHaveLength(3)
    expect(refreshes).toBe(1)
  })

  it('renova antes de expirar e não derruba a sessão em falha de rede', async () => {
    let now = 0
    const storage = memoryStorage()
    const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith('/auth/refresh')) throw new TypeError('Failed to fetch')
      return json({})
    })
    const store = createTokenStore(storage)
    const onAuthLost = vi.fn()
    const api = createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch, onAuthLost, now: () => now })
    store.setTokens({ ...tokens(1), expires_in: 60 }, 0)
    now = 50_000 // faltam 10 s: dentro da margem de 30 s
    await expect(api.get('/me')).rejects.toMatchObject({ status: 0, code: 'network' })
    expect(onAuthLost).not.toHaveBeenCalled()
    expect(store.getRefresh()).toBe('refresh-1')
  })

  it('sem sessão, chamadas autenticadas falham sem ir à rede', async () => {
    const { api, fetchImpl, onAuthLost } = setup(() => json({}))
    await expect(api.get('/me')).rejects.toMatchObject({ status: 401 })
    expect(fetchImpl).not.toHaveBeenCalled()
    expect(onAuthLost).toHaveBeenCalled()
  })

  it('logout limpa a sessão mesmo sem rede', async () => {
    const { api, store } = setup(() => {
      throw new TypeError('offline')
    })
    store.setTokens(tokens(1))
    await api.logout()
    expect(store.getAccess()).toBeNull()
    expect(store.getRefresh()).toBeNull()
  })

  it('esqueci a senha chama a rota pública', async () => {
    const { api, calls } = setup(() => json({ message: 'Se a conta existir, você receberá instruções' }))
    await api.forgotPassword('dono@chargegrid.com')
    expect(calls[0].url).toBe('/v1/auth/password/forgot')
    expect(calls[0].auth).toBeNull()
  })
})

describe('acesso exclusivo para vendedores', () => {
  it('reconhece vendedor por operator_enabled ou account_type', () => {
    expect(isVendor({ operator_enabled: true, account_type: 'consumer' })).toBe(true)
    expect(isVendor({ operator_enabled: false, account_type: 'vendor' })).toBe(true)
    expect(isVendor({ operator_enabled: false, account_type: 'consumer' })).toBe(false)
    expect(isVendor(null)).toBe(false)
  })

  it('decide o acesso ao painel', () => {
    expect(accessFor({ operator_enabled: true, account_type: 'vendor' })).toBe('granted')
    expect(accessFor({ operator_enabled: false, account_type: 'vendor' })).toBe('operator_pending')
    expect(accessFor({ operator_enabled: false, account_type: 'consumer' })).toBe('not_vendor')
  })
})
