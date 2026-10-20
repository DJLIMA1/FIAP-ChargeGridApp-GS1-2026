/**
 * DEV-ONLY: interceptador de `fetch` para `/v1/*` com dados fictícios
 * (`VITE_MOCK=1 npm run dev`). Importado dinamicamente atrás de
 * `import.meta.env.DEV`, portanto ausente do build de produção.
 *
 * Contas de teste (qualquer senha, exceto "errada"):
 * - qualquer e-mail → vendedor "João Silva" com operação habilitada
 * - e-mail contendo "motorista" → conta de motorista (testa o bloqueio)
 * - e-mail contendo "pendente" → vendedor ainda sem operação habilitada
 * - e-mail contendo "naoconfirmado" → login pede confirmação de e-mail
 * Cadastro (`/auth/register`, sempre conta de vendedor):
 * - e-mail contendo "confirmar" → `requires_email_confirmation` (tela "Verifique seu e-mail")
 * - e-mail contendo "existe" → resposta neutra (aviso no login)
 * - e-mail contendo "limite" → 429 (também no reenvio)
 * - senha "senhafraca" → `weak_password`
 * - qualquer outro → já entra, como vendedor sem operação habilitada
 * Auto-login para capturas: abra com `?mock_login=1`.
 * Operação do posto (Resultado, energia do estabelecimento, pagamentos em teste e
 * permanência): `./operations.ts`.
 */
import type { Coupon, CouponInput, Profile } from '../api/types'
import { REFRESH_KEY } from '../auth/tokens'
import * as data from './data'
import * as forecastMock from './forecast'
import * as ops from './operations'

const PROFILE_KEY = 'chargegrid.mock.profile'
const NAME_KEY = 'chargegrid.mock.name'
let calls = 0

function json(body: unknown, status = 200): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}
const fail = (status: number, code: string, message: string) => json({ error: { code, message } }, status)
const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

function profile(): Profile {
  let kind = 'vendor'
  let name: string | null = null
  try {
    kind = sessionStorage.getItem(PROFILE_KEY) ?? 'vendor'
    name = sessionStorage.getItem(NAME_KEY)
  } catch {
    /* ignora */
  }
  return {
    id: 'f0001-6b1e-4c7a-9d2f-000000001eef',
    name: name ?? (kind === 'driver' ? 'Marina Costa' : 'João Silva'),
    account_type: kind === 'driver' ? 'consumer' : 'vendor',
    operator_enabled: kind === 'vendor',
    phone: null,
    vehicle_description: null,
    created_at: '2026-08-01T12:00:00Z',
  }
}

function tokens() {
  calls += 1
  return { access_token: `mock-access-${calls}`, refresh_token: `mock-refresh-${calls}`, token_type: 'bearer', expires_in: 3600 }
}

async function handle(method: string, url: URL, body: unknown, auth: string | null): Promise<Response> {
  const path = url.pathname.replace(/^\/v1/, '')
  const p = url.searchParams
  await wait(path.startsWith('/ai/') ? 1400 : 220 + Math.random() * 260)

  if (path === '/auth/login' && method === 'POST') {
    const { email = '', password = '' } = (body ?? {}) as { email?: string; password?: string }
    if (password === 'errada' || !email.includes('@')) return fail(401, 'auth_rejected', 'Credenciais ou código inválidos')
    if (email.includes('naoconfirmado')) return fail(401, 'email_not_confirmed', 'Confirme seu e-mail para entrar. Você pode solicitar uma nova mensagem.')
    const kind = email.includes('motorista') ? 'driver' : email.includes('pendente') ? 'pending' : 'vendor'
    try {
      sessionStorage.setItem(PROFILE_KEY, kind)
      sessionStorage.removeItem(NAME_KEY)
    } catch {
      /* ignora */
    }
    return json(tokens())
  }
  if (path === '/auth/refresh' && method === 'POST') {
    const token = (body as { refresh_token?: string })?.refresh_token ?? ''
    return token.startsWith('mock-refresh') ? json(tokens()) : fail(401, 'auth_rejected', 'Credenciais ou código inválidos')
  }
  if (path === '/auth/register' && method === 'POST') {
    const { email = '', password = '', name = '', account_type } = (body ?? {}) as { email?: string; password?: string; name?: string; account_type?: string }
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email) || password.length < 8 || !name.trim() || account_type !== 'vendor') {
      return json({ error: { code: 'validation_error', message: 'Dados inválidos', fields: [{ field: password.length < 8 ? 'password' : 'email', message: 'invalid' }] } }, 422)
    }
    if (email.includes('limite')) return fail(429, 'rate_limited', 'Aguarde antes de repetir')
    if (password === 'senhafraca') return fail(422, 'weak_password', 'Escolha uma senha mais forte, com pelo menos 8 caracteres; evite senhas comuns')
    if (email.includes('confirmar')) return json({ id: 'mock-user', user: { email }, requires_email_confirmation: true })
    if (email.includes('existe')) return json({ message: 'Cadastro recebido', requires_email_confirmation: false })
    try {
      sessionStorage.setItem(PROFILE_KEY, 'pending')
      sessionStorage.setItem(NAME_KEY, name.trim())
    } catch {
      /* ignora */
    }
    return json({ ...tokens(), requires_email_confirmation: false })
  }
  if (path === '/auth/resend-signup' && method === 'POST') {
    const { email = '' } = (body ?? {}) as { email?: string }
    if (email.includes('limite')) return fail(429, 'rate_limited', 'Aguarde antes de repetir')
    return json({ message: 'Se a conta puder receber mensagens, uma confirmação será enviada' })
  }
  if (path === '/auth/password/forgot') return json({ message: 'Se a conta existir, você receberá instruções para recuperar a senha' })
  if (!auth?.startsWith('Bearer mock-access')) return fail(401, 'unauthorized', 'Não autenticado')
  if (path === '/auth/logout') return json({})
  if (path === '/me') return json(profile())

  const from = Date.parse(p.get('from') ?? '') || Date.now() - 7 * 86_400_000
  const to = Date.parse(p.get('to') ?? '') || Date.now()
  const station = p.get('station_id')
  switch (path) {
    case '/owner/overview':
      return json(data.overview(from, to, station))
    case '/owner/timeseries':
      return json(data.timeseries(from, to, (p.get('granularity') as 'hour' | 'day') ?? 'day', station))
    case '/owner/heatmap':
      return json(data.heatmap(from, to, station))
    case '/owner/sessions': {
      const page = data.sessions(p)
      return json({ ...page, items: page.items.map(ops.decorateSession) })
    }
    case '/owner/margin':
      return json(ops.marginReport(p))
    case '/owner/export/margin.csv':
      return new Response(ops.marginCsv(p), { status: 200, headers: { 'Content-Type': 'text/csv; charset=utf-8' } })
    case '/owner/export/margin.pdf':
      return new Response(new Blob([ops.marginPdf(p) as BlobPart], { type: 'application/pdf' }), { status: 200, headers: { 'Content-Type': 'application/pdf' } })
    case '/owner/alerts':
      return json(data.alerts(station))
    case '/owner/live':
      return json(ops.decorateLive(data.live(station)))
    case '/owner/forecast':
      return json(forecastMock.forecast(station ?? data.STATIONS[0].id))
    case '/owner/occupancy-history':
      return json(forecastMock.history(station ?? data.STATIONS[0].id, Number(p.get('weeks') ?? 4)))
    case '/operator/stations':
      return json({ items: data.STATIONS, total: data.STATIONS.length, limit: 100, offset: 0 })
    case '/coupons':
      if (method === 'POST') {
        const input = body as CouponInput
        const code = input.code.trim().toUpperCase()
        if (data.COUPONS.some((c) => c.code === code)) return fail(409, 'coupon_exists', 'Já existe um cupom com este código. Escolha outro.')
        const coupon: Coupon = { ...input, code, id: `b0${Date.now().toString(16)}-6b1e-4c7a-9d2f-000000000000`, operator_id: profile().id, active: true }
        data.COUPONS.unshift(coupon)
        return json(coupon, 201)
      }
      return json({ items: data.COUPONS, total: data.COUPONS.length, limit: 100, offset: 0 })
    case '/ai/owner-insights':
      return json({
        summary:
          'Receita de R$ 8.420 em 7 dias, com alta de fim de semana (sábado e domingo concentram 32% do faturamento). A ocupação média de 23,4% indica espaço para crescer fora dos picos das 8h e das 18h. Dois pontos estão fora do ar e respondem por cerca de 12% da receita potencial.',
        recommendations: [
          { title: 'Tarifa reduzida entre 22h e 6h', detail: 'A ocupação noturna fica abaixo de 5%. Um desconto de 15% (R$ 1,61/kWh) pode atrair motoristas de aplicativo sem afetar o pico.', impact: 'high', kind: 'pricing' },
          { title: 'Recuperar CG-007 e CG-009', detail: 'Offline há 3 h e com falha no painel. Juntos somam 12% da receita esperada da semana; priorize a visita técnica.', impact: 'high', kind: 'operations' },
          { title: 'Divulgar a Villa Olímpia no almoço', detail: 'A estação tem 20% da receita, mas está a 60 m de uma conveniência 24h. Um cupom de almoço pode elevar a ocupação entre 12h e 14h.', impact: 'medium', kind: 'marketing' },
        ],
        generated_at: new Date().toISOString(),
        model: 'mock-ia',
      })
  }
  if (path === '/geo/address-suggestions' && method === 'GET') {
    const words = (p.get('q') ?? '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').split(/[\s,]+/).filter((w) => w && !/^\d+$/.test(w))
    const items = data.ADDRESS_SUGGESTIONS.filter((item) => {
      const haystack = `${item.street} ${item.district}`.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
      return words.length > 0 && words.every((w) => haystack.includes(w))
    })
    return json({ items, available: true, attribution: 'Dados © colaboradores do OpenStreetMap' })
  }
  const opsMatch = /^\/stations\/([^/]+)\/(economics|power|power-site|building-load|pricing)$/.exec(path)
  if (opsMatch) {
    const [, stationId, resource] = opsMatch
    if (!data.STATIONS.some((s) => s.id === stationId)) return fail(404, 'not_found', 'Posto não encontrado')
    try {
      const input = (body ?? {}) as Record<string, unknown>
      if (resource === 'economics') return json(method === 'PUT' ? ops.putEconomics(stationId, input) : ops.economics(stationId))
      if (resource === 'power' && method === 'GET') return json(ops.power(stationId))
      if (resource === 'power-site' && method === 'PUT') return json(ops.putPowerSite(stationId, input))
      if (resource === 'building-load' && method === 'PUT') return json(ops.putBuildingLoad(stationId, input))
      if (resource === 'pricing') return json(method === 'PUT' ? ops.putPricing(stationId, input) : ops.pricing(stationId))
    } catch (error) {
      if (error instanceof ops.MockFailure) return fail(error.status, error.code, error.message)
      throw error
    }
    return fail(405, 'method_not_allowed', 'Método não suportado na demonstração')
  }
  const stationMatch = /^\/stations\/([^/]+)$/.exec(path)
  if (stationMatch) {
    const target = data.STATIONS.find((s) => s.id === stationMatch[1])
    if (!target) return fail(404, 'not_found', 'Posto não encontrado')
    if (method === 'PATCH') {
      const patch = body as Partial<typeof target>
      if (patch.active === false && target.connectors.some((c) => c.availability_status === 'charging')) {
        return fail(409, 'point_busy', 'Encerre reservas/recargas antes de desativar')
      }
      Object.assign(target, patch)
    }
    return json(structuredClone(target))
  }
  if (/^\/stations\/[^/]+\/pricing$/.test(path) && method === 'PUT') return json({ rules: body })
  const connectorMatch = /^\/connectors\/([^/]+)$/.exec(path)
  if (connectorMatch && method === 'PATCH') {
    const owner = data.STATIONS.find((s) => s.connectors.some((c) => c.id === connectorMatch[1]))
    const connector = owner?.connectors.find((c) => c.id === connectorMatch[1])
    if (!connector) return fail(404, 'not_found', 'Ponto não encontrado')
    if (['charging', 'reserved'].includes(connector.availability_status ?? '')) {
      return fail(409, 'point_busy', 'Encerre reservas/recargas antes de alterar o ponto')
    }
    Object.assign(connector, body)
    return json(structuredClone(connector))
  }
  const couponMatch = /^\/coupons\/([^/]+)$/.exec(path)
  if (couponMatch && method === 'PATCH') {
    const coupon = data.COUPONS.find((c) => c.id === couponMatch[1])
    if (!coupon) return fail(404, 'not_found', 'Cupom não encontrado')
    const patch = body as Partial<Coupon>
    if (patch.active && new Date(coupon.valid_until).getTime() <= Date.now()) {
      return fail(422, 'invalid_time', 'Atualize a validade antes de reativar o cupom')
    }
    Object.assign(coupon, patch)
    return json(coupon)
  }
  return fail(404, 'not_found', 'Rota de demonstração inexistente')
}

export function installMock(): void {
  const params = new URLSearchParams(window.location.search)
  if (params.get('mock_login') === '1') {
    try {
      localStorage.setItem(REFRESH_KEY, 'mock-refresh-seed')
      sessionStorage.setItem(PROFILE_KEY, params.get('mock_profile') ?? 'vendor')
    } catch {
      /* ignora */
    }
    params.delete('mock_login')
    params.delete('mock_profile')
    const query = params.toString()
    window.history.replaceState(null, '', `${window.location.pathname}${query ? `?${query}` : ''}`)
  }
  const original = window.fetch.bind(window)
  window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, window.location.origin)
    if (url.origin !== window.location.origin || !url.pathname.startsWith('/v1/')) return original(input, init)
    const headers = new Headers(init?.headers)
    const body = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    if (init?.signal?.aborted) throw new DOMException('Aborted', 'AbortError')
    return handle((init?.method ?? 'GET').toUpperCase(), url, body, headers.get('Authorization'))
  }
  console.info('[ChargeGrid] Modo demonstração ativo: dados fictícios (somente desenvolvimento).')
}
