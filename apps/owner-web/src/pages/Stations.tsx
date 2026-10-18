import { Link } from 'react-router-dom'
import type { Station } from '../api/types'
import { Icon } from '../components/Icon'
import { Badge, EmptyState, ErrorBanner, PageHead, Skeleton } from '../components/ui'
import { useFilters } from '../lib/filters'
import { formatTariff, toNumber } from '../lib/format'

function stationSummary(station: Station): { line: string; tone: 'green' | 'amber' | 'red' | 'gray' } {
  const points = station.connectors.filter((c) => !c.retired)
  if (!station.active) return { line: 'Inativa · oculta para motoristas', tone: 'gray' }
  if (!points.length) return { line: 'Sem conectores vinculados', tone: 'amber' }
  const online = points.filter((c) => c.online).length
  const busy = points.filter((c) => ['charging', 'occupied', 'reserved'].includes(c.availability_status ?? '')).length
  const problems = points.filter((c) => ['offline', 'fault'].includes(c.availability_status ?? '')).length
  if (!online) return { line: 'Offline · nenhum conector respondendo', tone: 'red' }
  const parts = [`Online · ${busy ? `${busy} de ${points.length} conectores em uso` : `${points.length} conector(es) livre(s)`}`]
  if (problems) parts.push(`${problems} com problema`)
  return { line: parts.join(' · '), tone: problems ? 'amber' : 'green' }
}

function baseTariff(station: Station): string {
  const prices = station.connectors.map((c) => toNumber(c.price_per_kwh)).filter((p): p is number => p !== null)
  if (!prices.length) return '—'
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  return min === max ? formatTariff(min) : `${formatTariff(min).replace('/kWh', '')} – ${formatTariff(max)}`
}

export default function Stations() {
  const { stations, stationsLoading, stationsError, reloadStations } = useFilters()
  const active = stations.filter((s) => s.active).length
  const connectors = stations.reduce((sum, s) => sum + s.connectors.filter((c) => !c.retired).length, 0)

  return (
    <>
      <PageHead
        title="Suas estações"
        sub={stations.length ? `${active} de ${stations.length} ativas · ${connectors} conectores` : 'Gerencie dados, tarifas e comodidades de cada estação'}
      />
      {stationsError ? <ErrorBanner error={stationsError} onRetry={reloadStations} /> : null}
      {stationsLoading && !stations.length ? (
        <div className="stack">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} height={84} radius={16} />
          ))}
        </div>
      ) : null}
      {!stationsLoading && !stationsError && !stations.length ? (
        <div className="card">
          <EmptyState icon="station" title="Nenhuma estação vinculada">
            Escaneie o QR de propriedade do equipamento no app ChargeGrid para cadastrar sua primeira estação.
          </EmptyState>
        </div>
      ) : null}
      <div className="stack" style={{ gap: 12 }}>
        {stations.map((station) => {
          const summary = stationSummary(station)
          return (
            <Link key={station.id} to={`/estacoes/${station.id}`} className="row-link">
              <span className="tile">
                <Icon name="station" size={22} />
              </span>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  <span style={{ fontWeight: 600, fontSize: 16 }}>{station.name}</span>
                  <Badge tone={station.active ? 'green' : 'gray'}>{station.active ? 'Ativa' : 'Inativa'}</Badge>
                </div>
                <div className="muted" style={{ fontSize: 13, marginTop: 3 }}>
                  {station.address}
                </div>
                <div style={{ fontSize: 13, marginTop: 3 }} className={summary.tone === 'red' ? 'red' : summary.tone === 'green' ? 'green' : 'muted'}>
                  {summary.line}
                </div>
              </div>
              <div style={{ textAlign: 'right' }} className="desktop-tariff">
                <div style={{ fontWeight: 700, fontSize: 15 }}>{baseTariff(station)}</div>
                <div className="dim" style={{ fontSize: 12 }}>
                  {station.connectors.length} conector(es)
                </div>
              </div>
              <Icon name="chevronRight" size={20} className="dim" />
            </Link>
          )
        })}
      </div>
    </>
  )
}
