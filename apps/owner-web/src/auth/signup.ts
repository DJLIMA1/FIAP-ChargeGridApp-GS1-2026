/**
 * Regras do cadastro e das telas de acesso, iguais às do app
 * (`apps/mobile/src/chargegrid_app/screens/auth.py`) e aos limites de
 * `RegisterInput` na API (nome 1–100, e-mail até 254, senha 8–128).
 */
import { ApiError } from '../api/client'
import type { TokenResponse } from '../api/types'

export const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
export const PASSWORD_MIN = 8
export const PASSWORD_MAX = 128
export const NAME_MAX = 100
export const EMAIL_MAX = 254

/** Mensagens neutras: não revelam se o e-mail já tem conta. */
export const NEUTRAL_SIGNUP_MESSAGE = 'Confira seu e-mail. Se já tem uma conta, entre com sua senha.'
export const RESEND_MESSAGE = 'Se a conta ainda precisar de confirmação, uma nova mensagem será enviada.'
export const FORGOT_MESSAGE = 'Se a conta existir, você receberá instruções para recuperar a senha.'

export type SignupField = 'name' | 'email' | 'password' | 'confirm'
export type SignupErrors = Partial<Record<SignupField, string>>

export interface SignupInput {
  name: string
  email: string
  password: string
  confirm?: string
}

export function emailError(value: string): string | null {
  const email = value.trim()
  if (email.length > EMAIL_MAX) return 'O e-mail informado é muito longo.'
  if (!EMAIL_PATTERN.test(email)) return 'Informe um e-mail válido.'
  return null
}

export function passwordError(value: string): string | null {
  if (value.length < PASSWORD_MIN) return `A senha precisa ter pelo menos ${PASSWORD_MIN} caracteres.`
  if (value.length > PASSWORD_MAX) return `Use até ${PASSWORD_MAX} caracteres na senha.`
  return null
}

/** Valida todos os campos de uma vez (o formulário mostra cada erro ao lado do campo). */
export function validateSignup(input: SignupInput): SignupErrors {
  const errors: SignupErrors = {}
  const name = input.name.trim()
  if (!name) errors.name = 'Informe seu nome completo.'
  else if (name.length > NAME_MAX) errors.name = `Use até ${NAME_MAX} caracteres no nome.`
  const email = emailError(input.email)
  if (email) errors.email = email
  // A senha é opaca: não é aparada, exatamente como a API a recebe.
  const password = passwordError(input.password)
  if (password) errors.password = password
  if (input.confirm !== undefined && !errors.password) {
    if (!input.confirm) errors.confirm = 'Repita a senha para confirmar.'
    else if (input.confirm !== input.password) errors.confirm = 'As senhas não conferem.'
  }
  return errors
}

export const firstError = (errors: SignupErrors): SignupField | null =>
  (['name', 'email', 'password', 'confirm'] as const).find((field) => errors[field]) ?? null

/** Corpo de `POST /v1/auth/register`: este painel só cria contas de vendedor. */
export function registerBody(input: SignupInput) {
  return { email: input.email.trim(), password: input.password, name: input.name.trim(), account_type: 'vendor' as const }
}

export interface RegisterResult extends Partial<TokenResponse> {
  requires_email_confirmation?: boolean
  message?: string
}

export type RegisterOutcome =
  | { kind: 'tokens'; tokens: TokenResponse }
  | { kind: 'confirm' }
  | { kind: 'neutral' }

/** Mesma ordem do app: tokens → entra; confirmação → "Verifique seu e-mail"; senão, aviso neutro. */
export function interpretRegister(result: RegisterResult | null | undefined): RegisterOutcome {
  if (result?.access_token && result.refresh_token) {
    return { kind: 'tokens', tokens: result as TokenResponse }
  }
  if (result?.requires_email_confirmation) return { kind: 'confirm' }
  return { kind: 'neutral' }
}

export type AuthFlow = 'login' | 'register' | 'forgot' | 'resend'

/** Erro da API → mensagem amigável em pt-BR e, quando couber, o campo a destacar. */
export function authErrorMessage(error: unknown, flow: AuthFlow): { message: string; field?: SignupField } {
  if (!(error instanceof ApiError)) {
    return { message: 'Algo deu errado. Tente novamente em instantes.' }
  }
  switch (error.code) {
    case 'network':
      return { message: 'Sem conexão com o servidor. Verifique a internet e tente novamente.' }
    case 'timeout':
      return { message: 'O servidor demorou para responder. Tente novamente.' }
    case 'weak_password':
      return { field: 'password', message: 'Escolha uma senha mais forte, com pelo menos 8 caracteres. Evite senhas comuns.' }
    case 'invalid_email':
      return { field: 'email', message: 'Informe um e-mail válido.' }
    case 'auth_rejected':
      return { message: flow === 'login' ? 'E-mail ou senha incorretos.' : 'Não foi possível concluir. Confira os dados e tente novamente.' }
    case 'email_not_confirmed':
      return { message: 'Confirme seu e-mail para entrar. Você pode pedir uma nova mensagem.' }
    case 'signup_disabled':
      return { message: 'O cadastro está temporariamente indisponível. Tente novamente mais tarde.' }
    case 'email_unavailable':
      return { message: 'O envio de e-mails está indisponível no momento. Tente novamente mais tarde.' }
    case 'auth_unavailable':
      return { message: 'A autenticação está temporariamente indisponível. Tente novamente em instantes.' }
  }
  if (error.status === 429 || error.code === 'rate_limited') {
    return {
      message:
        flow === 'resend' || flow === 'forgot'
          ? 'Você pediu muitas mensagens seguidas. Aguarde um minuto e tente de novo.'
          : 'Muitas tentativas seguidas. Aguarde um instante e tente de novo.',
    }
  }
  if (error.status === 422 || error.code === 'validation_error') {
    const field = error.fields.map((item) => item.field).find((name): name is SignupField => ['name', 'email', 'password'].includes(name))
    const byField: Record<string, string> = {
      name: 'Confira o nome: use de 1 a 100 caracteres.',
      email: 'Informe um e-mail válido.',
      password: `A senha precisa ter de ${PASSWORD_MIN} a ${PASSWORD_MAX} caracteres.`,
    }
    return field ? { field, message: byField[field] } : { message: 'Confira os dados informados e tente novamente.' }
  }
  if (error.status >= 500) return { message: 'O servidor está indisponível no momento. Tente novamente em instantes.' }
  return { message: error.message || 'Não foi possível concluir a operação.' }
}
