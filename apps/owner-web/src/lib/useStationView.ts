import { useCallback, useEffect, useRef, useState } from 'react'
import { ApiError } from '../api/client'
import type { Station } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { StationRefresh } from './stationRefresh'

export function useStationView(id: string) {
  const { ep } = useAuth()
  const [station, setStation] = useState<Station | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const current = useRef<Station | null>(null)
  const poll = useRef<StationRefresh | null>(null)

  useEffect(() => {
    current.current = null
    setStation(null)
    setError(null)
    setLastRefresh(null)
    const refresh = new StationRefresh(
      (signal) => ep.station(id, signal),
      (next) => {
        current.current = next
        setStation(next)
        setError(null)
        setLastRefresh(new Date())
      },
      (err) => setError(err instanceof ApiError ? err : new ApiError(0, 'unexpected', 'Falha ao atualizar carregadores.')),
    )
    poll.current = refresh
    const resume = () => {
      if (document.visibilityState === 'visible') void refresh.refresh()
      else refresh.pause()
    }
    document.addEventListener('visibilitychange', resume)
    void refresh.refresh()
    return () => {
      refresh.stop()
      document.removeEventListener('visibilitychange', resume)
      if (poll.current === refresh) poll.current = null
    }
  }, [ep, id])

  const update = useCallback((next: Station | ((previous: Station) => Station)) => {
    const value = typeof next === 'function' ? current.current && next(current.current) : next
    if (value) poll.current?.accept(value)
  }, [])
  const reload = useCallback(() => { void poll.current?.refresh() }, [])
  return { station, error, lastRefresh, reload, update }
}
