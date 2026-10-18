import { useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertRow } from '../components/AlertRow'
import { Icon } from '../components/Icon'
import { Card, EmptyState, ErrorBanner, Kpi, PageHead, SkeletonRows } from '../components/ui'
import { useAuth } from '../auth/AuthContext'
import { useFilters } from '../lib/filters'
import { formatTime } from '../lib/format'
import { SEVERITY } from '../lib/labels'
import { useApi } from '../lib/useApi'

const FILTERS = ['all', 'critical', 'warning', 'info'] as const

export default function Alerts() {
  const { ep } = useAuth()
  const { stationId, refreshKey } = useFilters()
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all')
  const { data, error, reload } = useApi((signal) => ep.alerts(stationId, signal), `alerts|${refreshKey}`)
  const items = data?.items ?? []
  const count = (severity: string) => items.filter((item) => item.severity === severity).length
  const shown = filter === 'all' ? items : items.filter((item) => item.severity === filter)

  return (
    <>
      <PageHead title="Alertas" sub={data ? `Situação atual dos pontos · verificado às ${formatTime(data.generated_at)}` : 'Situação atual dos pontos'} />
      <div className="grid kpis" style={{ marginBottom: 16 }}>
        <Kpi variant="small" label="Críticos" loading={!data && !error} value={<span className={count('critical') ? 'red' : ''}>{count('critical')}</span>} hint="Offline ou com falha" />
        <Kpi variant="small" label="Atenção" loading={!data && !error} value={count('warning')} hint="Sem dispositivo ou comandos falhos" />
        <Kpi variant="small" label="Informativos" loading={!data && !error} value={count('info')} hint="Pontos parados há 72 h ou mais" />
        <Kpi variant="small" label="Total" loading={!data && !error} value={items.length} hint={items.length ? 'Resolva pelo app ou no equipamento' : 'Tudo em ordem'} hintTone={items.length ? undefined : 'good'} />
      </div>
      <Card
        title="Alertas operacionais"
        action={
          <div className="chips" role="group" aria-label="Filtrar por severidade">
            {FILTERS.map((key) => (
              <button key={key} type="button" className="chip" aria-pressed={filter === key} onClick={() => setFilter(key)}>
                {key === 'all' ? 'Todos' : SEVERITY[key].label}
              </button>
            ))}
          </div>
        }
      >
        {error ? <ErrorBanner error={error} onRetry={reload} /> : null}
        {!data && !error ? <SkeletonRows rows={6} height={36} /> : null}
        {data && !shown.length ? (
          <EmptyState icon="check" title={items.length ? 'Nenhum alerta nesta categoria' : 'Tudo funcionando'}>
            {items.length ? 'Escolha outra severidade para ver os demais alertas.' : 'Nenhum ponto offline, com falha ou parado agora.'}
          </EmptyState>
        ) : null}
        {shown.length ? (
          <div>
            {shown.map((alert) => (
              <AlertRow
                key={`${alert.kind}-${alert.connector_id}`}
                alert={alert}
                action={
                  <Link to={`/estacoes/${alert.station_id}`} className="icon-btn" aria-label={`Abrir estação ${alert.station_name}`} title="Abrir estação">
                    <Icon name="chevronRight" size={18} />
                  </Link>
                }
              />
            ))}
          </div>
        ) : null}
      </Card>
    </>
  )
}
