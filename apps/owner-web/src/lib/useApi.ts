import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'

export interface ApiState<T> {
  data: T | undefined
  error: ApiError | null
  loading: boolean
  /** true depois da primeira resposta (sucesso ou erro). */
  settled: boolean
  reload(): void
}

function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  return new ApiError(0, 'unexpected', 'Algo deu errado ao carregar os dados. Tente novamente.')
}

/**
 * Executa `loader` quando `key` muda (e em `reload`). Mantém o dado anterior
 * enquanto recarrega, para os gráficos não piscarem; cancela respostas antigas.
 */
export function useApi<T>(loader: (signal: AbortSignal) => Promise<T>, key: string, enabled = true): ApiState<T> {
  const [data, setData] = useState<T | undefined>(undefined)
  const [error, setError] = useState<ApiError | null>(null)
  const [loading, setLoading] = useState(enabled)
  const [settled, setSettled] = useState(false)
  const [tick, setTick] = useState(0)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  useEffect(() => {
    if (!enabled) return
    const controller = new AbortController()
    setLoading(true)
    loaderRef
      .current(controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return
        setData(value)
        setError(null)
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return
        setError(asApiError(err))
      })
      .finally(() => {
        if (controller.signal.aborted) return
        setLoading(false)
        setSettled(true)
      })
    return () => controller.abort()
  }, [key, tick, enabled])

  const reload = useCallback(() => setTick((value) => value + 1), [])
  return { data, error, loading, settled, reload }
}
