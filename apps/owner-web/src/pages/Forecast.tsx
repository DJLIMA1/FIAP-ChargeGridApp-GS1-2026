import { useMemo, useState } from 'react'
import { ApiError } from '../api/client'
import { forecastEndpoints, type DailyMetrics, type ForecastMetrics, type ForecastSuggestion, type OccupancyHistory } from '../api/forecast'
import { useAuth } from '../auth/AuthContext'
import { ForecastChart } from '../components/ForecastChart'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Badge, Banner, Card, Drawer, EmptyState, ErrorBanner, PageHead, Skeleton } from '../components/ui'
import { useFilters } from '../lib/filters'
import { comparison, forecastPoints, methodLabel, occupancyColor, percent, points, totalEnergy } from '../lib/forecast'
import { formatDateTime, formatEnergy, formatTariff, toNumber } from '../lib/format'
import { useApi } from '../lib/useApi'

function MetricRow({ label, base, model, format }: { label: string; base: number | null | undefined; model?: number | null; format(v: number | null | undefined): string }) {
  return (
    <tr>
      <td>{label}</td>
      <td className="right num">{format(base)}</td>
      {model !== undefined ? <td className="right num">{format(model)}</td> : null}
    </tr>
  )
}

function MetricsTable({ base, model, daily }: { base: ForecastMetrics | null; model: ForecastMetrics | null; daily?: Record<string, DailyMetrics> }) {
  const showModel = model !== null && model !== undefined
  return (
    <div className="table-wrap" style={{ marginTop: 8 }}>
    <table className="table">
      <thead>
        <tr>
          <th>Métrica</th>
          <th className="right num">Média</th>
          {showModel ? <th className="right num">Modelo</th> : null}
        </tr>
      </thead>
      <tbody>
        <MetricRow label="Erro médio por hora (MAE)" base={base?.mae_pp} model={showModel ? model?.mae_pp : undefined} format={points} />
        <MetricRow label="Erro ponderado (WAPE)" base={base?.wape != null ? base.wape * 100 : null} model={showModel ? (model?.wape != null ? model.wape * 100 : null) : undefined} format={(v) => percent(v, 0)} />
        <MetricRow label="Acerto do horário de pico (±1 h)" base={daily?.baseline?.peak_hit_percent} model={showModel ? daily?.gbm?.peak_hit_percent : undefined} format={(v) => percent(v, 0)} />
        <MetricRow label="Acerto da energia do dia" base={daily?.baseline?.energy_day_accuracy_percent} model={showModel ? daily?.gbm?.energy_day_accuracy_percent : undefined} format={(v) => percent(v, 0)} />
      </tbody>
    </table>
    </div>
  )
}

function HistoryGrid({ data, metric }: { data: OccupancyHistory; metric: 'occupancy' | 'energy' }) {
  const values = metric === 'occupancy' ? data.occupancy_percent : data.energy_kwh
  const max = Math.max(0.001, ...values.flat().map((v) => toNumber(v) ?? 0))
  return (
    <div className="heatmap" role="table" aria-label={metric === 'occupancy' ? 'Ocupação média por dia da semana e hora' : 'Energia média por dia da semana e hora'}>
      <span />
      {data.hours.map((hour) => (
        <span key={hour} className="hour" aria-hidden>
          {hour}
        </span>
      ))}
      {data.days.map((day, row) => (
        <div key={day} role="row" style={{ display: 'contents' }}>
          <span className="day" role="rowheader">
            {day}
          </span>
          {values[row].map((raw, hour) => {
            const value = toNumber(raw)
            const scaled = metric === 'occupancy' ? value : value === null ? null : (value / max) * 100
            const text = value === null ? 'sem dados' : metric === 'occupancy' ? percent(value) : formatEnergy(raw)
            return (
              <span key={hour} role="cell" className="cell" style={{ background: occupancyColor(scaled) }}
                title={`${day} ${String(hour).padStart(2, '0')}h: ${text}`} aria-label={`${day} ${hour}h: ${text}`} />
            )
          })}
        </div>
      ))}
    </div>
  )
}

export default function Forecast() {
  const { api } = useAuth()
  const toast = useToast()
  const fx = useMemo(() => forecastEndpoints(api), [api])
  const { stationId, stations, refreshKey } = useFilters()
  const target = stationId ?? stations[0]?.id ?? null
  const station = stations.find((s) => s.id === target)
  const [weeks, setWeeks] = useState(4)
  const [metric, setMetric] = useState<'occupancy' | 'energy'>('occupancy')
  const [pending, setPending] = useState<ForecastSuggestion | null>(null)
  const [applying, setApplying] = useState(false)
  const forecast = useApi((signal) => fx.forecast(target as string, signal), `fc|${target}|${refreshKey}`, !!target)
  const history = useApi((signal) => fx.history(target as string, weeks, signal), `fh|${target}|${weeks}|${refreshKey}`, !!target)
  const data = forecast.data
  const chart = useMemo(() => (data ? forecastPoints(data.hours) : []), [data])
  const accuracy = data?.accuracy

  const apply = async () => {
    if (!pending || !target) return
    setApplying(true)
    try {
      await fx.applyPricing(target, pending.action.patch)
      toast('Tarifa atualizada. O app e o painel já usam a nova regra.')
      setPending(null)
      forecast.reload()
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Não foi possível aplicar a sugestão', 'error')
    } finally {
      setApplying(false)
    }
  }

  if (!target) {
    return (
      <>
        <PageHead title="Previsão" sub="Ocupação e energia por hora" />
        <Card>
          <EmptyState icon="station" title="Nenhuma estação">Vincule um ponto para acompanhar a ocupação e ver a previsão.</EmptyState>
        </Card>
      </>
    )
  }

  return (
    <>
      <PageHead
        title="Previsão"
        sub={`${station?.name ?? 'Estação'} · ocupação e energia por hora, próximas 36 h`}
        actions={data ? <Badge tone={data.method === 'gbm' ? 'green' : 'blue'}>Em uso: {methodLabel(data.method)}</Badge> : null}
      />
      <div className="stack">
        {!stationId && stations.length > 1 ? (
          <Banner tone="info" title="Uma estação por vez">Mostrando {station?.name}. Escolha outra estação no filtro do topo.</Banner>
        ) : null}
        {data?.includes_synthetic || history.data?.includes_synthetic ? (
          <Banner tone="info" icon="alert" title="Inclui histórico sintético">
            Parte do histórico desta estação é sintética (rotulada). Os números de receita e recargas do painel não usam esses dados.
          </Banner>
        ) : null}
        {forecast.error ? <ErrorBanner error={forecast.error} onRetry={forecast.reload} /> : null}

        <Card title="Próximas 36 horas" sub={data ? `Ocupação prevista por hora · atualizado em ${formatDateTime(data.generated_at)}` : 'Ocupação prevista por hora'}>
          {!data && !forecast.error ? <Skeleton height={290} /> : null}
          {data && data.status === 'no_history' ? (
            <EmptyState icon="chart" title="Ainda sem histórico">{data.method_reason}</EmptyState>
          ) : null}
          {data && data.status === 'ok' ? (
            <>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
                {data.peaks.length ? (
                  data.peaks.slice(0, 3).map((peak) => (
                    <Badge key={peak.start} tone="amber">
                      {peak.label} ({percent(toNumber(peak.max_percent ?? null))})
                    </Badge>
                  ))
                ) : (
                  <Badge tone="green">Sem lotação prevista</Badge>
                )}
                {data.idle.slice(0, 1).map((quiet) => (
                  <Badge key={quiet.start} tone="gray">
                    {quiet.label}
                  </Badge>
                ))}
              </div>
              <ForecastChart data={chart} label="Ocupação prevista por hora nas próximas 36 horas" />
              <div className="chart-stats" style={{ marginTop: 12 }}>
                <div>
                  <div className="label">Energia prevista (próximas 24 h)</div>
                  <div className="value">{formatEnergy(totalEnergy(data.hours).toFixed(3))}</div>
                </div>
                <div>
                  <div className="label">Faixa</div>
                  <div className="value" style={{ fontSize: 15 }}>{data.band === 'não calibrada' ? 'Não calibrada' : 'p10–p90 do erro medido'}</div>
                </div>
              </div>
              <p className="dim" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
                Barras: previsão em uso. Linha azul tracejada: média do mesmo dia e hora. Laranja: hora prevista com 80% ou mais de ocupação. Energia estimada pela média do mesmo dia e hora.
              </p>
            </>
          ) : null}
        </Card>

        <div className="grid two">
          <Card title="Acerto medido" sub={accuracy ? `Últimos ${accuracy.window_days} dias desta estação · ${accuracy.origins} previsões refeitas` : 'Últimos 14 dias desta estação'}>
            {!data && !forecast.error ? <Skeleton height={180} /> : null}
            {data && accuracy ? (
              <>
                <p style={{ margin: 0 }}>
                  <strong>{methodLabel(data.method)}</strong> — {data.method_reason}
                </p>
                {accuracy.gbm && comparison(accuracy.gbm, accuracy.baseline) ? (
                  <p className="dim" style={{ margin: '4px 0 0', fontSize: 13 }}>Modelo: {comparison(accuracy.gbm, accuracy.baseline)} por hora.</p>
                ) : null}
                {accuracy.status === 'insufficient_history' ? (
                  <p className="dim" style={{ margin: '8px 0 0', fontSize: 12.5 }}>Menos de 7 dias medidos: o acerto ainda não é confiável.</p>
                ) : null}
                <MetricsTable base={accuracy.baseline} model={accuracy.gbm} daily={accuracy.daily} />
                <p className="dim" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
                  Cada dia foi previsto de novo usando só os dados anteriores a ele. O modelo só é usado quando erra pelo menos 5% menos que a média.
                </p>
              </>
            ) : null}
            {data && !accuracy ? <p className="dim">Sem histórico para medir.</p> : null}
          </Card>
          <Card title="Como o modelo foi validado" sub={data?.model ? data.model.trained_on : 'Validação offline'}>
            {data?.model ? (
              <>
                <p style={{ margin: 0 }}>
                  {data.model.library}, treinado só com histórico sintético rotulado e testado em semanas e estações que ele não viu ({data.model.offline_test.period}).
                  {' '}Na validação, o resultado foi: <strong>{data.model.selected === 'gbm' ? 'modelo venceu a média' : 'média venceu o modelo'}</strong>
                  {comparison(data.model.offline_test.gbm, data.model.offline_test.baseline) ? ` (${comparison(data.model.offline_test.gbm, data.model.offline_test.baseline)})` : ''}.
                </p>
                <MetricsTable base={data.model.offline_test.baseline} model={data.model.offline_test.gbm} daily={data.model.offline_test.daily} />
                <p className="dim" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
                  O modelo estima a hora típica (mediana): erra menos por hora, mas subestima a soma do dia. Por isso a energia usa a média.
                </p>
              </>
            ) : (
              <p className="dim">Modelo indisponível; usando a média do mesmo dia e hora.</p>
            )}
          </Card>
        </div>

        <Card title="Sugestões" sub="Aplicadas com a tarifa dinâmica e a tarifa por horário que você já usa">
          {data && data.suggestions.length === 0 ? <p className="dim" style={{ margin: 0 }}>Nenhuma sugestão para as próximas 36 horas.</p> : null}
          {!data && !forecast.error ? <Skeleton height={90} radius={14} /> : null}
          <div className="stack" style={{ gap: 12 }}>
            {data?.suggestions.map((item) => (
              <article className="insight" key={item.kind + item.window.start}>
                <span className="tile white">
                  <Icon name={item.kind === 'schedule_idle' ? 'clock' : 'trendUp'} size={21} />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h4>{item.title}</h4>
                  <p>{item.detail}</p>
                </div>
                <button type="button" className="btn btn-secondary" onClick={() => setPending(item)}>
                  Revisar
                </button>
              </article>
            ))}
          </div>
        </Card>

        <Card
          title="Histórico por dia e hora"
          sub={`Média das últimas ${weeks} semanas (horário de São Paulo)`}
          action={
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <div className="segmented" role="group" aria-label="Métrica">
                <button type="button" aria-pressed={metric === 'occupancy'} onClick={() => setMetric('occupancy')}>Ocupação</button>
                <button type="button" aria-pressed={metric === 'energy'} onClick={() => setMetric('energy')}>Energia</button>
              </div>
              <div className="segmented" role="group" aria-label="Período">
                <button type="button" aria-pressed={weeks === 4} onClick={() => setWeeks(4)}>4 sem.</button>
                <button type="button" aria-pressed={weeks === 8} onClick={() => setWeeks(8)}>8 sem.</button>
              </div>
            </div>
          }
        >
          {history.error ? <ErrorBanner error={history.error} onRetry={history.reload} /> : null}
          {!history.data && !history.error ? <Skeleton height={230} /> : null}
          {history.data ? <HistoryGrid data={history.data} metric={metric} /> : null}
          {history.data ? (
            <p className="dim" style={{ margin: '10px 0 0', fontSize: 12.5 }}>
              {history.data.coverage.days_measured} dia(s) medidos{history.data.coverage.days_synthetic ? ` e ${history.data.coverage.days_synthetic} sintéticos` : ''}. Os agregados por hora ficam guardados mesmo depois da limpeza da telemetria.
            </p>
          ) : null}
        </Card>
      </div>

      {pending ? (
        <Drawer
          title={pending.title}
          onClose={() => setPending(null)}
          footer={
            <>
              <button type="button" className="btn btn-ghost" onClick={() => setPending(null)} disabled={applying}>Cancelar</button>
              <button type="button" className="btn btn-primary" onClick={apply} disabled={applying}>
                <Icon name="check" size={17} /> {applying ? 'Aplicando…' : 'Aplicar na tarifa'}
              </button>
            </>
          }
        >
          <div className="stack">
            <p style={{ margin: 0 }}>{pending.detail}</p>
            {pending.action.preview ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>Ponto</th>
                    <th className="right num">Tarifa base hoje</th>
                    <th className="right num">No horário</th>
                  </tr>
                </thead>
                <tbody>
                  {pending.action.preview.map((row) => (
                    <tr key={row.connector_id}>
                      <td>{row.public_code}</td>
                      <td className="right num">{formatTariff(row.from)}</td>
                      <td className="right num">{formatTariff(row.to)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
              Recargas e reservas em andamento mantêm o preço travado. Você pode desfazer a qualquer momento nas tarifas da estação.
            </p>
          </div>
        </Drawer>
      ) : null}
    </>
  )
}
