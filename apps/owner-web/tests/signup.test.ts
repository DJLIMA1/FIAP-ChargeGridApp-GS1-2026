import { describe, expect, it, vi } from 'vitest'
import { ApiError, createApiClient } from '../src/api/client'
import { authErrorMessage, emailError, firstError, interpretRegister, registerBody, validateSignup } from '../src/auth/signup'
import { createTokenStore, type KeyValueStorage } from '../src/auth/tokens'

const valid = { name: 'Joana Prado', email: 'joana@empresa.com.br', password: 'segredo123', confirm: 'segredo123' }

describe('validação do cadastro', () => {
  it('aceita dados válidos', () => {
    expect(validateSignup(valid)).toEqual({})
  })

  it('usa as mesmas mensagens do app para cada campo', () => {
    const errors = validateSignup({ name: '   ', email: 'joana@', password: '1234567', confirm: '' })
    expect(errors).toEqual({
      name: 'Informe seu nome completo.',
      email: 'Informe um e-mail válido.',
      password: 'A senha precisa ter pelo menos 8 caracteres.',
    })
    expect(firstError(errors)).toBe('name')
  })

  it('respeita os limites da API (nome 100, e-mail 254, senha 8–128)', () => {
    expect(validateSignup({ ...valid, name: 'a'.repeat(101) }).name).toBe('Use até 100 caracteres no nome.')
    expect(validateSignup({ ...valid, name: 'a'.repeat(100) }).name).toBeUndefined()
    expect(emailError(`${'a'.repeat(250)}@x.com`)).toBe('O e-mail informado é muito longo.')
    const long = 'a'.repeat(129)
    expect(validateSignup({ ...valid, password: long, confirm: long }).password).toBe('Use até 128 caracteres na senha.')
    const max = 'a'.repeat(128)
    expect(validateSignup({ ...valid, password: max, confirm: max })).toEqual({})
    expect(validateSignup({ ...valid, password: '12345678', confirm: '12345678' })).toEqual({})
  })

  it('não apara a senha (espaços contam, como na API)', () => {
    expect(validateSignup({ ...valid, password: ' 1234567', confirm: ' 1234567' })).toEqual({})
    expect(validateSignup({ ...valid, password: '  abc  ', confirm: '  abc  ' }).password).toBeDefined()
  })

  it('confere a confirmação de senha', () => {
    expect(validateSignup({ ...valid, confirm: '' }).confirm).toBe('Repita a senha para confirmar.')
    expect(validateSignup({ ...valid, confirm: 'segredo124' }).confirm).toBe('As senhas não conferem.')
    // Sem confirmação no formulário (ex.: outro fluxo), nada a conferir.
    expect(validateSignup({ name: valid.name, email: valid.email, password: valid.password })).toEqual({})
  })

  it('o corpo do cadastro é sempre de vendedor, com nome e e-mail aparados', () => {
    expect(registerBody({ name: '  Joana Prado ', email: ' joana@empresa.com.br ', password: ' s3nha-longa ' })).toEqual({
      name: 'Joana Prado',
      email: 'joana@empresa.com.br',
      password: ' s3nha-longa ',
      account_type: 'vendor',
    })
  })
})

describe('resposta do cadastro', () => {
  it('tokens → entra direto', () => {
    const outcome = interpretRegister({ access_token: 'a', refresh_token: 'r', expires_in: 3600, requires_email_confirmation: false })
    expect(outcome.kind).toBe('tokens')
    if (outcome.kind === 'tokens') expect(outcome.tokens.refresh_token).toBe('r')
  })

  it('confirmação pendente → tela "Verifique seu e-mail"', () => {
    expect(interpretRegister({ requires_email_confirmation: true })).toEqual({ kind: 'confirm' })
  })

  it('qualquer outra resposta → aviso neutro (não revela se a conta existe)', () => {
    expect(interpretRegister({ message: 'Cadastro recebido', requires_email_confirmation: false })).toEqual({ kind: 'neutral' })
    expect(interpretRegister({})).toEqual({ kind: 'neutral' })
    expect(interpretRegister(null)).toEqual({ kind: 'neutral' })
    // Só o access token não basta: o app exige os dois.
    expect(interpretRegister({ access_token: 'a' })).toEqual({ kind: 'neutral' })
  })
})

describe('mensagens de erro', () => {
  it('weak_password destaca o campo de senha', () => {
    const result = authErrorMessage(new ApiError(422, 'weak_password', 'Escolha uma senha mais forte'), 'register')
    expect(result.field).toBe('password')
    expect(result.message).toMatch(/senha mais forte/)
  })

  it('validation_error aponta o campo recusado', () => {
    const error = new ApiError(422, 'validation_error', 'Dados inválidos', [{ field: 'email', message: 'string does not match' }])
    expect(authErrorMessage(error, 'register')).toEqual({ field: 'email', message: 'Informe um e-mail válido.' })
    const generic = new ApiError(422, 'validation_error', 'Dados inválidos', [{ field: 'account_type', message: 'x' }])
    expect(authErrorMessage(generic, 'register')).toEqual({ message: 'Confira os dados informados e tente novamente.' })
    expect(authErrorMessage(new ApiError(422, 'invalid_email', 'Informe um e-mail válido'), 'register').field).toBe('email')
  })

  it('limite de tentativas (429) vira mensagem amigável por fluxo', () => {
    const limited = new ApiError(429, 'rate_limited', 'Aguarde antes de repetir')
    expect(authErrorMessage(limited, 'register').message).toBe('Muitas tentativas seguidas. Aguarde um instante e tente de novo.')
    expect(authErrorMessage(limited, 'resend').message).toBe('Você pediu muitas mensagens seguidas. Aguarde um minuto e tente de novo.')
  })

  it('rede, tempo esgotado, indisponibilidade e credenciais', () => {
    expect(authErrorMessage(new ApiError(0, 'network', 'x'), 'register').message).toMatch(/Sem conexão/)
    expect(authErrorMessage(new ApiError(0, 'timeout', 'x'), 'register').message).toMatch(/demorou/)
    expect(authErrorMessage(new ApiError(503, 'signup_disabled', 'x'), 'register').message).toMatch(/cadastro está temporariamente indisponível/)
    expect(authErrorMessage(new ApiError(503, 'http_503', 'x'), 'register').message).toMatch(/servidor está indisponível/)
    expect(authErrorMessage(new ApiError(401, 'auth_rejected', 'x'), 'login').message).toBe('E-mail ou senha incorretos.')
    expect(authErrorMessage(new TypeError('boom'), 'register').message).toBe('Algo deu errado. Tente novamente em instantes.')
  })
})

describe('cliente: cadastro e reenvio', () => {
  function memoryStorage(): KeyValueStorage {
    const data = new Map<string, string>()
    return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => void data.set(k, v), removeItem: (k) => void data.delete(k) }
  }

  it('envia o cadastro sem Authorization e devolve o corpo bruto', async () => {
    const calls: { url: string; auth: string | null; body: unknown }[] = []
    const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      calls.push({ url: String(input), auth: new Headers(init.headers).get('Authorization'), body: JSON.parse(String(init.body)) })
      return new Response(JSON.stringify({ requires_email_confirmation: true }), { status: 200 })
    })
    const store = createTokenStore(memoryStorage())
    const api = createApiClient({ store, fetchImpl: fetchImpl as unknown as typeof fetch })
    const result = await api.register(registerBody(valid))
    expect(interpretRegister(result).kind).toBe('confirm')
    expect(calls[0]).toEqual({ url: '/v1/auth/register', auth: null, body: { email: valid.email, password: valid.password, name: valid.name, account_type: 'vendor' } })
    expect(store.getRefresh()).toBeNull()

    await api.resendSignup('joana@empresa.com.br')
    expect(calls[1].url).toBe('/v1/auth/resend-signup')
    expect(calls[1].body).toEqual({ email: 'joana@empresa.com.br' })
  })

  it('adota os tokens de um cadastro que já entra', () => {
    const store = createTokenStore(memoryStorage())
    const api = createApiClient({ store, fetchImpl: vi.fn() as unknown as typeof fetch, now: () => 1_000 })
    api.adoptTokens({ access_token: 'a', refresh_token: 'r', expires_in: 60 })
    expect(store.getAccess()).toBe('a')
    expect(store.getRefresh()).toBe('r')
    expect(store.getExpiry()).toBe(61_000)
  })

  it('erros do cadastro chegam como ApiError com o código da API', async () => {
    const fetchImpl = vi.fn(async () => new Response(JSON.stringify({ error: { code: 'rate_limited', message: 'Aguarde antes de repetir' } }), { status: 429 }))
    const api = createApiClient({ store: createTokenStore(memoryStorage()), fetchImpl: fetchImpl as unknown as typeof fetch })
    const error = await api.register(registerBody(valid)).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(429)
    expect(authErrorMessage(error, 'register').message).toMatch(/Muitas tentativas/)
  })
})
