/**
 * Cliente HTTP mínimo da API ChargeGrid.
 *
 * - Base same-origin `/v1` (rewrite da Vercel em produção, proxy do Vite em dev).
 * - Envia `Authorization: Bearer <access>` quando há sessão.
 * - Em 401 tenta renovar o token UMA vez (refresh compartilhado entre
 *   requisições simultâneas) e repete a chamada; se falhar de novo, encerra a
 *   sessão local e avisa via `onAuthLost`.
 * - Erros viram `ApiError` com a mensagem em português vinda da API.
 */
import type { ApiErrorBody, TokenResponse } from './types'
import type { TokenStore } from '../auth/tokens'

export type QueryValue = string | number | boolean | null | undefined
export type Query = Record<string, QueryValue>

export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly fields: { field: string; message: string }[]

  constructor(status: number, code: string, message: string, fields: { field: string; message: string }[] = []) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.fields = fields
  }
}

export interface RequestOptions {
  body?: unknown
  query?: Query
  /** false = rota pública (login, refresh, esqueci a senha). */
  auth?: boolean
  signal?: AbortSignal
  timeoutMs?: number
}

export interface ApiClientConfig {
  baseUrl?: string
  store: TokenStore
  fetchImpl?: typeof fetch
  onAuthLost?: () => void
  /** Renova proativamente quando faltar menos que isto para expirar. */
  refreshSkewMs?: number
  now?: () => number
}

const DEFAULT_TIMEOUT = 25_000

export function buildQuery(query?: Query): string {
  if (!query) return ''
  const params = new URLSearchParams()
  for (const [key, value] of Object.entries(query)) {
    if (value === null || value === undefined || value === '') continue
    params.append(key, String(value))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

async function readError(response: Response): Promise<ApiError> {
  let body: ApiErrorBody | null
  try {
    body = (await response.json()) as ApiErrorBody
  } catch {
    body = null
  }
  const error = body?.error
  const fallback =
    response.status >= 500
      ? 'O servidor está indisponível no momento. Tente novamente em instantes.'
      : response.status === 404
        ? 'Recurso não encontrado.'
        : response.status === 403
          ? 'Você não tem permissão para esta ação.'
          : 'Não foi possível concluir a operação.'
  return new ApiError(response.status, error?.code || `http_${response.status}`, error?.message || fallback, error?.fields || [])
}

export type ApiClient = ReturnType<typeof createApiClient>

export function createApiClient(config: ApiClientConfig) {
  const baseUrl = (config.baseUrl ?? '/v1').replace(/\/$/, '')
  const doFetch: typeof fetch = config.fetchImpl ?? ((...args) => globalThis.fetch(...args))
  const store = config.store
  const skew = config.refreshSkewMs ?? 30_000
  const now = config.now ?? (() => Date.now())
  let refreshing: Promise<boolean> | null = null

  async function raw(method: string, path: string, options: RequestOptions, token: string | null): Promise<Response> {
    const headers: Record<string, string> = { Accept: 'application/json' }
    if (options.body !== undefined) headers['Content-Type'] = 'application/json'
    if (token) headers.Authorization = `Bearer ${token}`
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(new DOMException('timeout', 'TimeoutError')), options.timeoutMs ?? DEFAULT_TIMEOUT)
    const onAbort = () => controller.abort(options.signal?.reason)
    options.signal?.addEventListener('abort', onAbort)
    try {
      return await doFetch(`${baseUrl}${path}${buildQuery(options.query)}`, {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
        credentials: 'same-origin',
        cache: 'no-store',
      })
    } catch (error) {
      if (options.signal?.aborted) throw error
      const timedOut = controller.signal.aborted
      throw new ApiError(
        0,
        timedOut ? 'timeout' : 'network',
        timedOut
          ? 'O servidor demorou para responder. Tente novamente.'
          : 'Sem conexão com o servidor. Verifique a internet e tente novamente.',
      )
    } finally {
      clearTimeout(timer)
      options.signal?.removeEventListener('abort', onAbort)
    }
  }

  /**
   * Renova a sessão; requisições simultâneas compartilham a mesma tentativa.
   * Resolve `true`/`false` (aceito/recusado pelo servidor) e rejeita com
   * `ApiError` de rede — assim uma queda de conexão não derruba a sessão.
   */
  function refresh(): Promise<boolean> {
    if (refreshing) return refreshing
    const token = store.getRefresh()
    if (!token) return Promise.resolve(false)
    refreshing = (async () => {
      try {
        const response = await raw('POST', '/auth/refresh', { body: { refresh_token: token } }, null)
        if (response.status >= 500 || response.status === 429) throw await readError(response)
        if (!response.ok) return false
        const tokens = (await response.json().catch(() => null)) as TokenResponse | null
        if (!tokens?.access_token) return false
        store.setTokens(tokens, now())
        return true
      } finally {
        refreshing = null
      }
    })()
    return refreshing
  }

  function lose() {
    store.clear()
    config.onAuthLost?.()
  }

  async function request<T>(method: string, path: string, options: RequestOptions = {}): Promise<T> {
    const authed = options.auth !== false
    if (authed) {
      const expiry = store.getExpiry()
      const stale = !store.getAccess() || (expiry !== null && expiry - skew <= now())
      if (stale && store.getRefresh()) await refresh()
      if (!store.getAccess()) {
        lose()
        throw new ApiError(401, 'session_expired', 'Sua sessão expirou. Entre novamente.')
      }
    }
    let response = await raw(method, path, options, authed ? store.getAccess() : null)
    if (response.status === 401 && authed) {
      const renewed = await refresh()
      if (renewed) response = await raw(method, path, options, store.getAccess())
      if (!renewed || response.status === 401) {
        lose()
        throw new ApiError(401, 'session_expired', 'Sua sessão expirou. Entre novamente.')
      }
    }
    if (!response.ok) throw await readError(response)
    if (response.status === 204) return undefined as T
    const text = await response.text()
    return (text ? JSON.parse(text) : undefined) as T
  }

  return {
    request,
    refresh,
    store,
    get: <T>(path: string, query?: Query, signal?: AbortSignal) => request<T>('GET', path, { query, signal }),
    post: <T>(path: string, body?: unknown, options: Omit<RequestOptions, 'body'> = {}) =>
      request<T>('POST', path, { ...options, body }),
    patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
    async login(email: string, password: string): Promise<TokenResponse> {
      const tokens = await request<TokenResponse>('POST', '/auth/login', { body: { email, password }, auth: false })
      if (!tokens?.access_token) throw new ApiError(401, 'auth_rejected', 'Credenciais ou código inválidos')
      store.setTokens(tokens, now())
      return tokens
    },
    async logout(): Promise<void> {
      const token = store.getAccess()
      store.clear()
      if (!token) return
      try {
        await raw('POST', '/auth/logout', { timeoutMs: 8000 }, token)
      } catch {
        /* sair localmente mesmo sem rede */
      }
    },
    forgotPassword: (email: string) =>
      request<{ message: string }>('POST', '/auth/password/forgot', { body: { email }, auth: false }),
  }
}
