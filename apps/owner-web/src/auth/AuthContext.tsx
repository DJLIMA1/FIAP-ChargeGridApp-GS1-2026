import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { ApiError, createApiClient, type ApiClient } from '../api/client'
import { endpoints, type Endpoints } from '../api/endpoints'
import type { Profile } from '../api/types'
import { createTokenStore } from './tokens'
import { accessFor, NOT_VENDOR_MESSAGE } from './vendor'

export type AuthStatus = 'booting' | 'signed_out' | 'granted' | 'operator_pending'

interface AuthValue {
  status: AuthStatus
  profile: Profile | null
  api: ApiClient
  ep: Endpoints
  /** Mensagem para a tela de login (sessão expirada, conta de motorista...). */
  notice: string | null
  login(email: string, password: string): Promise<void>
  logout(message?: string): Promise<void>
}

const AuthContext = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('booting')
  const [profile, setProfile] = useState<Profile | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const statusRef = useRef(status)
  statusRef.current = status

  const api = useMemo(
    () =>
      createApiClient({
        store: createTokenStore(),
        onAuthLost: () => {
          setProfile(null)
          if (statusRef.current !== 'signed_out') setNotice('Sua sessão expirou. Entre novamente.')
          setStatus('signed_out')
        },
      }),
    [],
  )
  const ep = useMemo(() => endpoints(api), [api])

  const resolveProfile = useCallback(async () => {
    const me = await ep.me()
    const decision = accessFor(me)
    if (decision === 'not_vendor') {
      await api.logout()
      setProfile(null)
      setNotice(NOT_VENDOR_MESSAGE)
      setStatus('signed_out')
      return
    }
    setProfile(me)
    setNotice(null)
    setStatus(decision)
  }, [api, ep])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      if (!api.store.getRefresh()) {
        setStatus('signed_out')
        return
      }
      try {
        if (!(await api.refresh())) throw new ApiError(401, 'session_expired', 'Sessão expirada')
        if (!cancelled) await resolveProfile()
      } catch (error) {
        if (cancelled) return
        // Falha de rede/servidor não apaga a sessão salva: basta tentar de novo.
        if (error instanceof ApiError && error.status !== 401) setNotice(error.message)
        else api.store.clear()
        setStatus('signed_out')
      }
    })()
    return () => {
      cancelled = true
    }
  }, [api, resolveProfile])

  const login = useCallback(
    async (email: string, password: string) => {
      setNotice(null)
      await api.login(email.trim(), password)
      await resolveProfile()
    },
    [api, resolveProfile],
  )

  const logout = useCallback(
    async (message?: string) => {
      await api.logout()
      setProfile(null)
      setNotice(message ?? null)
      setStatus('signed_out')
    },
    [api],
  )

  const value = useMemo<AuthValue>(
    () => ({ status, profile, api, ep, notice, login, logout }),
    [status, profile, api, ep, notice, login, logout],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth fora do AuthProvider')
  return value
}
