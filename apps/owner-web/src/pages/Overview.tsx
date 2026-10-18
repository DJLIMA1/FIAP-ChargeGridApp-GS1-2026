import { Link } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { TrendChart, type Point } from '../components/Charts'
import { HeatmapGrid } from '../components/Heatmap'
import { Icon } from '../components/Icon'
import { LivePanel } from '../components/LivePanel'
import { AlertRow } from '../components/AlertRow'
import { Card, EmptyState, ErrorBanner, Kpi, PageHead, Skeleton, SkeletonRows } from '../components/ui'
import { useFilters } from '../lib/filters'
import {
  firstName,
  formatCurrency,
  formatEnergy,
  formatNumber,
  formatPercent,
  greeting,
  toNumber,
} from '../lib/format'
import { seriesPoints } from '../lib/series'
import { periodLabel, suggestedGranularity } from '../lib/period'
import { useApi } from '../lib/useApi'

export default function Overview() {
  const { ep, profile } = useAuth()
  const { query, refreshKey, period, stationId, stations } = useFilters()
  const granularity = suggestedGranularity(query)
  const overview = useApi((signal) => ep.overview(query, signal), `ov|${refreshKey}`)
  const series = useApi((signal) => ep.timeseries({ ...query, granularity }, signal), `ts|${refreshKey}|${granularity}`)
  const heatmap = useApi((signal) => ep.heatmap(query, signal), `hm|${refreshKey}`)
  const alerts = useApi((signal) => ep.alerts(stationId, signal), `al|${refreshKey}`)

  const kpis = overview.data?.kpis
  const loadingKpis = !overview.data && !overview.error
  const station = stations.find((s) => s.id === stationId)
  const revenuePoints = series.data ? seriesPoints(series.data, 'revenue') : []
  const energyPoints = series.data ? seriesPoints(series.data, 'energy_kwh') : []
  const peakEnergy = energyPoints.reduce<Point | null>((best, p) => (!best || p.value > best.value ? p : best), null)
  const peakRevenue = revenuePoints.reduce<Point | null>((best, p) => (!best || p.value > best.value ? p : best), null)
  const totalEnergy = energyPoints.reduce((sum, p) => sum + p.value, 0)
  const totalRevenue = revenuePoints.reduce((sum, p) => sum + p.value, 0)
  const ranking = overview.data?.ranking ?? []
  const maxRevenue = Math.max(1, ...ranking.map((r) => toNumber(r.revenue) ?? 0))
  const unit = granularity === 'hour' ? 'hora' : 'dia'

  return (
    <>
      <PageHead
        title={`${greeting()}, ${firstName(profile?.name) || 'vendedor'}!`}
        sub={`${periodLabel(period)} · ${station ? station.name : 'Todas as estações'}`}
      />
      {overview.error ? <ErrorBanner error={overview.error} onRetry={overview.reload} /> : null}

      <div className="grid kpis" style={{ marginTop: overview.error ? 16 : 0 }}>
        <Kpi variant="hero" label="Receita estimada" icon="wallet" loading={loadingKpis} value={formatCurrency(kpis?.revenue, { compact: true })} hint={kpis ? `${formatNumber(kpis.active_sessions)} recarga(s) em andamento` : undefined} />
        <Kpi label="Energia entregue" icon="zap" loading={loadingKpis} value={formatEnergy(kpis?.energy_kwh)} hint={kpis ? `${formatNumber(kpis.points_online)} de ${formatNumber(kpis.points)} pontos online` : undefined} />
        <Kpi label="Recargas" icon="plug" loading={loadingKpis} value={formatNumber(kpis?.sessions)} hint={kpis ? (kpis.interrupted_sessions || kpis.failed_sessions ? `${kpis.interrupted_sessions} interrompida(s) · ${kpis.failed_sessions} com falha` : 'Nenhuma falha no período') : undefined} hintTone={kpis && !kpis.failed_sessions && !kpis.interrupted_sessions ? 'good' : undefined} />
        <Kpi label="Ticket médio" icon="chart" loading={loadingKpis} value={formatCurrency(kpis?.average_ticket)} hint="Receita ÷ recargas concluídas" />
      </div>
      <div className="grid kpis-secondary section">
        <Kpi variant="small" label="Ocupação" loading={loadingKpis} value={formatPercent(kpis?.occupancy_percent)} hint="Tempo em recarga no período" />
        <Kpi variant="small" label="Disponibilidade" loading={loadingKpis} value={formatPercent(kpis?.uptime_percent)} hint="Pontos publicados online agora" hintTone={kpis && toNumber(kpis.uptime_percent) !== null && (toNumber(kpis.uptime_percent) ?? 0) < 80 ? 'bad' : undefined} />
        <Kpi variant="small" label="Reservas" loading={loadingKpis} value={formatNumber(kpis?.reservations)} hint="Criadas no período" />
        <Kpi variant="small" label="Não comparecimento" loading={loadingKpis} value={formatPercent(kpis?.no_show_percent)} hint={kpis ? `${formatNumber(kpis.no_shows)} reserva(s) expirada(s)` : undefined} hintTone={kpis && (toNumber(kpis.no_show_percent) ?? 0) >= 20 ? 'bad' : undefined} />
      </div>

      <div className="grid two section">
        <Card title="Receita por dia" sub={granularity === 'hour' ? 'Por hora, pelo término da recarga' : 'Pelo término da recarga (horário de São Paulo)'} id="rev">
          {series.error ? <ErrorBanner error={series.error} onRetry={series.reload} /> : null}
          {!series.data && !series.error ? <Skeleton height={300} /> : null}
          {series.data ? (
            <>
              <div className="chart-stats">
                <div>
                  <div className="label">Receita total</div>
                  <div className="value">{formatCurrency(totalRevenue)}</div>
                </div>
                <div>
                  <div className="label">Melhor {unit}</div>
                  <div className="value">{peakRevenue && peakRevenue.value > 0 ? formatCurrency(peakRevenue.value, { compact: true }) : '—'}</div>
                  {peakRevenue && peakRevenue.value > 0 ? <div className="green" style={{ fontSize: 12.5, fontWeight: 600 }}>{peakRevenue.tooltip}</div> : null}
                </div>
              </div>
              <TrendChart data={revenuePoints} color="#3DBE7A" label="Receita por período" format={(v) => formatCurrency(v)} axisFormat={(v) => (v >= 1000 ? `${formatNumber(v / 1000, 1)} mil` : formatNumber(v))} />
            </>
          ) : null}
        </Card>
        <Card title="Energia entregue · kWh" sub="Energia das recargas concluídas" id="energy">
          {series.error ? <ErrorBanner error={series.error} onRetry={series.reload} /> : null}
          {!series.data && !series.error ? <Skeleton height={300} /> : null}
          {series.data ? (
            <>
              <div className="chart-stats">
                <div>
                  <div className="label">Energia total</div>
                  <div className="value">{formatEnergy(totalEnergy)}</div>
                </div>
                <div>
                  <div className="label">Pico de consumo</div>
                  <div className="value">{peakEnergy && peakEnergy.value > 0 ? formatEnergy(peakEnergy.value) : '—'}</div>
                  {peakEnergy && peakEnergy.value > 0 ? <div className="green" style={{ fontSize: 12.5, fontWeight: 600 }}>{peakEnergy.tooltip}</div> : null}
                </div>
              </div>
              <TrendChart data={energyPoints} color="#6B9BFF" label="Energia entregue por período" format={(v) => formatEnergy(v)} axisFormat={(v) => formatNumber(v)} />
            </>
          ) : null}
        </Card>
      </div>

      <div className="grid split section">
        <Card title="Ocupação por dia e hora" sub="Sessões pelo horário de início" id="heat">
          {heatmap.error ? <ErrorBanner error={heatmap.error} onRetry={heatmap.reload} /> : null}
          {!heatmap.data && !heatmap.error ? <Skeleton height={230} /> : null}
          {heatmap.data ? (
            heatmap.data.max ? (
              <>
                <HeatmapGrid data={heatmap.data} />
                {heatmap.data.peak_hours.length ? (
                  <div style={{ marginTop: 16 }}>
                    <div className="muted" style={{ fontSize: 13, marginBottom: 8 }}>
                      Horários de pico
                    </div>
                    <div className="peaks">
                      {heatmap.data.peak_hours.map((peak) => (
                        <div className="peak" key={peak.hour}>
                          <b>
                            {String(peak.hour).padStart(2, '0')}h–{String((peak.hour + 1) % 24).padStart(2, '0')}h
                          </b>
                          <span>{formatNumber(peak.sessions)} sessões</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <EmptyState icon="clock" title="Sem recargas no período">
                O mapa de calor aparece quando houver sessões iniciadas no período selecionado.
              </EmptyState>
            )
          ) : null}
        </Card>
        <Card
          title="Alertas recentes"
          sub={alerts.data ? `${alerts.data.items.length} alerta(s) ativos` : undefined}
          action={
            <Link to="/alertas" className="card-link">
              Ver todos <Icon name="chevronRight" size={16} />
            </Link>
          }
          id="alerts"
        >
          {alerts.error ? <ErrorBanner error={alerts.error} onRetry={alerts.reload} /> : null}
          {!alerts.data && !alerts.error ? <SkeletonRows rows={4} height={36} /> : null}
          {alerts.data ? (
            alerts.data.items.length ? (
              <div>
                {alerts.data.items.slice(0, 5).map((alert) => (
                  <AlertRow key={`${alert.kind}-${alert.connector_id}`} alert={alert} />
                ))}
              </div>
            ) : (
              <EmptyState icon="check" title="Tudo funcionando">
                Nenhum alerta operacional nos seus pontos agora.
              </EmptyState>
            )
          ) : null}
        </Card>
      </div>

      <div className="section">
        <Card title="Ranking de pontos" sub="Ordenado por receita no período" id="rank">
          {!overview.data && !overview.error ? <SkeletonRows rows={5} height={28} /> : null}
          {overview.data && !ranking.length ? (
            <EmptyState icon="station" title="Nenhum ponto ainda">
              Os pontos vinculados às suas estações aparecem aqui com receita, energia e ocupação.
            </EmptyState>
          ) : null}
          {ranking.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th style={{ width: 40 }}>#</th>
                    <th>Ponto</th>
                    <th>Estação</th>
                    <th className="right">Receita</th>
                    <th className="right">Energia</th>
                    <th className="right">Recargas</th>
                    <th style={{ width: 180 }}>Ocupação</th>
                  </tr>
                </thead>
                <tbody>
                  {ranking.map((row, index) => (
                    <tr key={row.connector_id}>
                      <td>
                        <span className={`rank ${index === 0 ? 'top' : ''}`}>{index + 1}</span>
                      </td>
                      <td className="strong">{row.public_code}</td>
                      <td className="muted">{row.station_name}</td>
                      <td className="right strong tabular">
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 10 }}>
                          <span className="bar" style={{ width: 70 }} aria-hidden>
                            <i style={{ width: `${((toNumber(row.revenue) ?? 0) / maxRevenue) * 100}%` }} />
                          </span>
                          {formatCurrency(row.revenue)}
                        </div>
                      </td>
                      <td className="right tabular">{formatEnergy(row.energy_kwh)}</td>
                      <td className="right tabular">{formatNumber(row.sessions)}</td>
                      <td>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span className="bar" style={{ flex: 1 }} aria-hidden>
                            <i style={{ width: `${Math.min(100, toNumber(row.occupancy_percent) ?? 0)}%`, background: '#6B9BFF' }} />
                          </span>
                          <span className="tabular" style={{ width: 48, textAlign: 'right' }}>
                            {formatPercent(row.occupancy_percent)}
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </Card>
      </div>

      <div className="section">
        <LivePanel />
      </div>
    </>
  )
}
