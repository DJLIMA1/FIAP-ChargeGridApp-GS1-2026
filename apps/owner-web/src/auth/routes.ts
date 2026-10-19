import { useLocation } from 'react-router-dom'

/** Rotas públicas das telas de acesso. */
export const AUTH_ROUTES = {
  login: '/entrar',
  register: '/criar-conta',
  verify: '/verificar-email',
  forgot: '/esqueci-senha',
} as const

/**
 * O e-mail e os avisos viajam no estado do router (nunca na URL, para não
 * expor dados pessoais em histórico, logs ou Referer).
 */
export interface AuthRouteState {
  email?: string
  notice?: string
  noticeTone?: 'info' | 'ok' | 'error'
}

export function useAuthRouteState(): AuthRouteState {
  const state = useLocation().state as AuthRouteState | null
  return state && typeof state === 'object' ? state : {}
}
