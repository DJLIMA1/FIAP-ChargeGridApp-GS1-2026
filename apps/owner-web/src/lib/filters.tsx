import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import type { Station } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { periodQuery, validatePeriod, type PeriodQuery, type PeriodState } from './period'

const STORAGE_KEY = 'chargegrid.owner.filters'

interface Saved {
  period: PeriodState
  stationId: string | null
}

function load(): Saved {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Saved
      if (parsed?.period?.preset && !validatePeriod(parsed.period)) return parsed
    }
  } catch {
    /* sem storage */
  }
  return { period: { preset: '7d' }, stationId: null }
}

interface FiltersValue {
  period: PeriodState
  setPeriod(period: PeriodState): void
  stationId: string | null
  setStationId(id: string | null): void
  /** Parâmetros from/to/station_id do período atual (recalculados a cada atualização). */
  query: PeriodQuery
  /** Chave estável para recarregar dados quando filtros mudam ou o usuário atualiza. */
  refreshKey: string
  refresh(): void
  lastRefresh: Date
  stations: Station[]
  stationsLoading: boolean
  stationsError: string | null
  reloadStations(): void
  replaceStation(station: Station): void
}

const FiltersContext = createContext<FiltersValue | null>(null)

export function FiltersProvider({ children }: { children: ReactNode }) {
  const { ep } = useAuth()
  const initial = useMemo(load, [])
  const [period, setPeriodState] = useState<PeriodState>(initial.period)
  const [stationId, setStationIdState] = useState<string | null>(initial.stationId)
  const [lastRefresh, setLastRefresh] = useState(() => new Date())
  const [stations, setStations] = useState<Station[]>([])
  const [stationsLoading, setStationsLoading] = useState(true)
  const [stationsError, setStationsError] = useState<string | null>(null)
  const [stationsTick, setStationsTick] = useState(0)

  useEffect(() => {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ period, stationId }))
    } catch {
      /* ignora */
    }
  }, [period, stationId])

  useEffect(() => {
    const controller = new AbortController()
    setStationsLoading(true)
    ep.stations(controller.signal)
      .then((page) => {
        setStations(page.items)
        setStationsError(null)
        setStationIdState((current) => (current && !page.items.some((s) => s.id === current) ? null : current))
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) setStationsError(error.message)
      })
      .finally(() => {
        if (!controller.signal.aborted) setStationsLoading(false)
      })
    return () => controller.abort()
  }, [ep, stationsTick])

  const setPeriod = useCallback((next: PeriodState) => {
    setPeriodState(next)
    setLastRefresh(new Date())
  }, [])
  const setStationId = useCallback((id: string | null) => {
    setStationIdState(id)
    setLastRefresh(new Date())
  }, [])
  const refresh = useCallback(() => setLastRefresh(new Date()), [])
  const reloadStations = useCallback(() => setStationsTick((t) => t + 1), [])
  const replaceStation = useCallback(
    (station: Station) => setStations((list) => list.map((item) => (item.id === station.id ? station : item))),
    [],
  )

  const query = useMemo(() => periodQuery(period, stationId, lastRefresh), [period, stationId, lastRefresh])
  const refreshKey = `${query.from}|${query.to}|${query.station_id ?? ''}`

  const value = useMemo<FiltersValue>(
    () => ({
      period,
      setPeriod,
      stationId,
      setStationId,
      query,
      refreshKey,
      refresh,
      lastRefresh,
      stations,
      stationsLoading,
      stationsError,
      reloadStations,
      replaceStation,
    }),
    [period, setPeriod, stationId, setStationId, query, refreshKey, refresh, lastRefresh, stations, stationsLoading, stationsError, reloadStations, replaceStation],
  )
  return <FiltersContext.Provider value={value}>{children}</FiltersContext.Provider>
}

export function useFilters(): FiltersValue {
  const value = useContext(FiltersContext)
  if (!value) throw new Error('useFilters fora do FiltersProvider')
  return value
}
