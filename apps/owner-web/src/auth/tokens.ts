/**
 * Armazenamento de tokens: o access token fica só em memória; o refresh token
 * fica no localStorage (sobrevive a recarregar a página). Todo acesso ao
 * storage é protegido — em janela anônima/bloqueada o painel continua
 * funcionando, apenas sem lembrar a sessão.
 */
import type { TokenResponse } from '../api/types'

export const REFRESH_KEY = 'chargegrid.owner.refresh'

export interface TokenStore {
  getAccess(): string | null
  getRefresh(): string | null
  /** Epoch em ms em que o access token expira (null = desconhecido). */
  getExpiry(): number | null
  setTokens(tokens: TokenResponse, now?: number): void
  clear(): void
}

export interface KeyValueStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

function browserStorage(): KeyValueStorage | null {
  try {
    return typeof localStorage === 'undefined' ? null : localStorage
  } catch {
    return null
  }
}

export function createTokenStore(storage: KeyValueStorage | null = browserStorage()): TokenStore {
  let access: string | null = null
  let expiry: number | null = null
  let refreshFallback: string | null = null

  const readRefresh = () => {
    try {
      return storage?.getItem(REFRESH_KEY) ?? refreshFallback
    } catch {
      return refreshFallback
    }
  }

  return {
    getAccess: () => access,
    getRefresh: readRefresh,
    getExpiry: () => expiry,
    setTokens(tokens, now = Date.now()) {
      access = tokens.access_token || null
      if (typeof tokens.expires_at === 'number' && tokens.expires_at > 0) {
        expiry = tokens.expires_at * 1000
      } else if (typeof tokens.expires_in === 'number' && tokens.expires_in > 0) {
        expiry = now + tokens.expires_in * 1000
      } else {
        expiry = null
      }
      if (tokens.refresh_token) {
        refreshFallback = tokens.refresh_token
        try {
          storage?.setItem(REFRESH_KEY, tokens.refresh_token)
        } catch {
          /* storage cheio ou bloqueado: mantém só em memória */
        }
      }
    },
    clear() {
      access = null
      expiry = null
      refreshFallback = null
      try {
        storage?.removeItem(REFRESH_KEY)
      } catch {
        /* ignora */
      }
    },
  }
}
