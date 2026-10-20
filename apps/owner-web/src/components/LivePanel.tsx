import { useEffect, useState } from 'react'
import type { LiveItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { useFilters } from '../lib/filters'
import { formatCurrency, formatEnergy, formatPower, formatRelative, formatTariff, formatTime, toNumber } from '../lib/format'
import { AVAILABILITY } from '../lib/labels'
import { OVERSTAY_STATUS, occupancyText } from '../lib/overstay'
import { formatKw } from '../lib/power'
import { useApi } from '../lib/useApi'
import { Icon } from './Icon'
import { Badge, Card, EmptyState, ErrorBanner, Skeleton } from './ui'

export const LIVE_INTERVAL_MS = 3_000

/** Quem continua na vaga depois da recarga (frente D): fase, tolerância restante e taxa. */
function Occupancy({ item }: { item: LiveItem }) {
  const occupancy = item.occupancy
  if (!occupancy) return null
  const meta = OVERSTAY_STATUS[occupancy.status] ?? { label: occupancy.status, tone: 'gray' as const }
  return (
    <div className="point-occupancy">
      <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
        <Badge tone={meta.tone}>{meta.label}</Badge>
        {occupancy.driver_label ? <span className="dim">{occupancy.driver_label}</span> : null}
      </span>
      <span className="tabular">
        <b>{occupancyText(occupancy)}</b>
      </span>
      {occupancy.started_at ? <span className="dim">Recarga terminou às {formatTime(occupancy.started_at)}</span> : null}
    </div>
  )
}

function PointCard({ item, now }: { item: LiveItem; now: Date }) {
  const status = AVAILABILITY[item.availability_status] ?? { label: item.availability_status, tone: 'gray' as const }
  const session = item.session
  const powerKw = session?.power_w ? (toNumber(session.power_w) ?? 0) / 1000 : null
  const energyKwh = session ? (toNumber(session.energy_wh) ?? 0) / 1000 : null
  const soc = toNumber(session?.soc_percent)
  const problem = ['offline', 'fault'].includes(item.availability_status)
  return (
    <article className={`point ${item.availability_status === 'charging' ? 'charging' : ''} ${problem ? 'alert' : ''}`}>
      <div className="point-head">
        <div style={{ minWidth: 0 }}>
          <div className="point-code">{item.public_code}</div>
          <div className="point-station">{item.station_name}</div>
        </div>
        <Badge tone={status.tone}>{status.label}</Badge>
      </div>
      {session ? (
        <>
          <div className="point-meta">
            <span>
              <b className="tabular">{formatEnergy(energyKwh)}</b> entregues
            </span>
            {powerKw !== null ? (
              <span>
                <b className="tabular">{formatPower(powerKw)}</b> agora
              </span>
            ) : null}
            {session.applied_power_kw ? (
              <span>
                <b className="tabular">{formatKw(session.applied_power_kw)}</b> aplicada
              </span>
            ) : null}
            <span>
              <b className="tabular">{formatCurrency(session.cost_estimate)}</b>
            </span>
          </div>
          {soc !== null ? (
            <div>
              <div className="point-progress" aria-label={`Bateria em ${Math.round(soc)}%`}>
                <i style={{ width: `${Math.max(2, Math.min(100, soc))}%` }} />
              </div>
            </div>
          ) : null}
          {session.power_reason ? <div className="point-power">{session.power_reason}</div> : null}
          <div className="point-meta">Iniciada às {formatTime(session.started_at)}</div>
        </>
      ) : (
        <div className="point-meta">
          <span>
            <b>{formatPower(item.power_kw)}</b> · {item.connector_type}
          </span>
          <span>
            <b>{formatTariff(item.price_per_kwh)}</b>
          </span>
        </div>
      )}
      <Occupancy item={item} />
      <div className="point-meta" style={{ marginTop: 'auto' }}>
        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <Icon name={item.online ? 'zap' : 'wifiOff'} size={14} />
          {item.has_device ? (item.online ? 'Online' : `Último contato ${formatRelative(item.last_seen, now)}`) : 'Sem dispositivo'}
        </span>
        {item.reserved_until ? <span>Reservado até {formatTime(item.reserved_until)}</span> : null}
      </div>
    </article>
  )
}

export function LivePanel({ limit }: { limit?: number }) {
  const { ep } = useAuth()
  const { stationId, refreshKey } = useFilters()
  const [tick, setTick] = useState(0)
  const [now, setNow] = useState(() => new Date())
  const { data, error, loading, settled, reload } = useApi((signal) => ep.live(stationId, signal), `live|${stationId}|${refreshKey}|${tick}`)
  // O ícone só gira no clique (a atualização automática a cada 3 s não pisca a tela).
  const [manual, setManual] = useState(false)
  useEffect(() => {
    if (!loading) setManual(false)
  }, [loading])

  useEffect(() => {
    const timer = setInterval(() => {
      if (document.visibilityState === 'visible') setTick((t) => t + 1)
      setNow(new Date())
    }, LIVE_INTERVAL_MS)
    return () => clearInterval(timer)
  }, [])

  const items = data?.items.filter((item) => !item.retired) ?? []
  const order = ['charging', 'occupied', 'reserved', 'fault', 'offline', 'reconciling', 'available', 'disabled']
  const sorted = [...items].sort((a, b) => order.indexOf(a.availability_status) - order.indexOf(b.availability_status))
  const shown = limit ? sorted.slice(0, limit) : sorted
  const counts = items.reduce<Record<string, number>>((acc, item) => {
    acc[item.availability_status] = (acc[item.availability_status] ?? 0) + 1
    return acc
  }, {})

  return (
    <Card
      title={
        <span>
          <span className="live-dot" aria-hidden />
          Status ao vivo dos pontos
        </span>
      }
      sub={
        data
          ? `${counts.charging ?? 0} carregando · ${counts.available ?? 0} disponíveis · ${(counts.offline ?? 0) + (counts.fault ?? 0)} com problema · atualiza a cada ${LIVE_INTERVAL_MS / 1000} s (${formatTime(data.generated_at)})`
          : `Atualiza automaticamente a cada ${LIVE_INTERVAL_MS / 1000} segundos`
      }
      action={
        <button type="button" className={`icon-btn ${loading && manual ? 'spinning' : ''}`} onClick={() => { setManual(true); reload() }} aria-label="Atualizar status ao vivo">
          <Icon name="refresh" size={16} />
        </button>
      }
    >
      {error && !data ? <ErrorBanner error={error} onRetry={reload} /> : null}
      {!settled && !data ? (
        <div className="live-grid">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height={132} radius={14} />
          ))}
        </div>
      ) : null}
      {data && !items.length ? (
        <EmptyState icon="plug" title="Nenhum ponto cadastrado">
          Vincule um equipamento pelo app ChargeGrid para acompanhar o status em tempo real.
        </EmptyState>
      ) : null}
      {shown.length ? (
        <div className="live-grid">
          {shown.map((item) => (
            <PointCard key={item.connector_id} item={item} now={now} />
          ))}
        </div>
      ) : null}
      {error && data ? <p className="dim" style={{ margin: '12px 0 0', fontSize: 12.5 }}>Última atualização falhou: {error.message}</p> : null}
    </Card>
  )
}
