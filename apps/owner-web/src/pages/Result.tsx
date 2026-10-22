import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { CentralRentLine, MarginReport, MarginRow } from '../api/operations'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Badge, Banner, Card, EmptyState, ErrorBanner, Kpi, PageHead, Skeleton, SkeletonRows } from '../components/ui'
import { downloadBlob } from '../lib/exporters'
import { useFilters } from '../lib/filters'
import { formatCurrency, formatEnergy, formatNumber, formatPercent, formatShortDateTime, toNumber } from '../lib/format'
import { buildCascade, cascadeWidth, feeLabel, marginExportFilename, monthLabel, NOT_PROFIT_TEXT, NOT_PROFIT_TITLE, rentExportFilename, stationsMissingCost, type CascadeStep } from '../lib/margin'
import { periodLabel } from '../lib/period'
import { useApi } from '../lib/useApi'

const PAGE_SIZE = 50

const SIGN: Record<CascadeStep['kind'], string> = { total: '', minus: '−', plus: '+', result: '=' }
const COLOR: Record<CascadeStep['kind'], string> = { total: '#3DBE7A', minus: '#D72B32', plus: '#6B9BFF', result: '#F2F2F2' }

function CostLink({ stationId, label = 'Configurar custo' }: { stationId?: string | null; label?: string }) {
  if (!stationId) return null
  return (
    <Link to={`/estacoes/${stationId}#economics`} className="card-link" style={{ fontSize: 12.5 }}>
      {label} <Icon name="chevronRight" size={14} />
    </Link>
  )
}

function Cascade({ report, firstMissing }: { report: MarginReport; firstMissing: string | null }) {
  const steps = buildCascade(report.totals, feeLabel(report.stations))
  return (
    <div className="stack" style={{ gap: 4 }} role="list" aria-label="Cascata do resultado">
      {steps.map((step) => {
        const strong = step.kind === 'total' || step.kind === 'result'
        const negative = step.kind === 'result' && (toNumber(step.value) ?? 0) < 0
        return (
          <div
            key={step.key}
            role="listitem"
            style={{ padding: '10px 0', borderTop: step.kind === 'result' || step.kind === 'total' && step.key !== 'gross' ? '1px solid #333' : undefined }}
          >
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ width: 16, textAlign: 'center', color: COLOR[step.kind], fontWeight: 700 }} aria-hidden>
                {SIGN[step.kind]}
              </span>
              <span style={{ flex: 1, minWidth: 160, fontWeight: strong ? 600 : 400, fontSize: step.kind === 'result' ? 17 : 14.5 }}>{step.label}</span>
              <span className={`tabular ${negative ? 'red' : ''}`} style={{ fontWeight: strong ? 700 : 500, fontSize: step.kind === 'result' ? 22 : 15.5 }}>
                {step.value === null ? '—' : `${step.kind === 'minus' ? '− ' : step.kind === 'plus' ? '+ ' : ''}${formatCurrency(step.value)}`}
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, paddingLeft: 28, marginTop: 6 }}>
              <span className="bar" style={{ flex: 1, maxWidth: 420 }} aria-hidden>
                <i style={{ width: `${cascadeWidth(step, report.totals.gross)}%`, background: COLOR[step.kind] }} />
              </span>
              {step.hint ? <span className="dim" style={{ fontSize: 12.5 }}>{step.hint}</span> : null}
              {step.missingCost && step.key === 'energy_cost' ? <CostLink stationId={firstMissing} /> : null}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function RentTable({ lines, total }: { lines: CentralRentLine[]; total: string }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Estação</th>
            <th>Central</th>
            <th>Mês</th>
            <th className="right">Dias</th>
            <th className="right">Mensal</th>
            <th className="right">Valor</th>
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => (
            <tr key={`${line.device_id}|${line.month}|${line.monthly_amount}`}>
              <td>{line.station_name}</td>
              <td className="strong">{line.central || '—'}</td>
              <td className="tabular">{monthLabel(line.month)}</td>
              <td className="right tabular">
                {line.days}/{line.days_in_month}
              </td>
              <td className="right tabular muted">{formatCurrency(line.monthly_amount)}</td>
              <td className="right tabular strong">{formatCurrency(line.amount)}</td>
            </tr>
          ))}
          <tr>
            <td colSpan={5} className="strong">
              Total descontado do repasse
            </td>
            <td className="right tabular strong">{formatCurrency(total)}</td>
          </tr>
        </tbody>
      </table>
    </div>
  )
}

function SessionsTable({ items }: { items: MarginRow[] }) {
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Fim</th>
            <th>Posto</th>
            <th>Ponto</th>
            <th className="right">Energia</th>
            <th className="right">Receita cobrada</th>
            <th className="right">Comissão</th>
            <th className="right">Repasse</th>
            <th className="right">Custo energia</th>
            <th className="right">Margem</th>
          </tr>
        </thead>
        <tbody>
          {items.map((row) => {
            const margin = toNumber(row.margin)
            return (
              <tr key={row.session_id}>
                <td className="tabular">{formatShortDateTime(row.ended_at)}</td>
                <td>{row.station_name}</td>
                <td className="strong">
                  {row.public_code}
                  {row.coupon_code ? (
                    <span style={{ marginLeft: 6 }}>
                      <Badge tone="gray">{row.coupon_code}</Badge>
                    </span>
                  ) : null}
                  {toNumber(row.demand_multiplier) !== null && (toNumber(row.demand_multiplier) ?? 1) > 1 ? (
                    <span style={{ marginLeft: 6 }}>
                      <Badge tone="amber">{formatNumber(row.demand_multiplier, 2)}×</Badge>
                    </span>
                  ) : null}
                </td>
                <td className="right tabular">{formatEnergy(row.energy_kwh)}</td>
                <td className="right tabular">
                  {formatCurrency(row.revenue_total)}
                  {row.revenue_basis === 'captured' ? <div className="dim" style={{ fontSize: 11.5 }}>pago</div> : null}
                </td>
                <td className="right tabular muted">− {formatCurrency(row.platform_fee)}</td>
                <td className="right tabular">{formatCurrency(row.owner_net)}</td>
                <td className="right tabular muted">{row.energy_cost === null ? '—' : `− ${formatCurrency(row.energy_cost)}`}</td>
                <td className={`right tabular strong ${margin !== null && margin < 0 ? 'red' : ''}`}>
                  {row.margin === null ? (
                    <span className="dim" title="Custo da energia não informado">
                      —
                    </span>
                  ) : (
                    formatCurrency(row.margin)
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export default function Result() {
  const { ep } = useAuth()
  const toast = useToast()
  const { query, refreshKey, period, stationId, stations } = useFilters()
  const [page, setPage] = useState(0)
  const [exporting, setExporting] = useState<null | 'csv' | 'pdf' | 'rent'>(null)
  useEffect(() => setPage(0), [refreshKey])
  const { data, error, loading, reload } = useApi(
    (signal) => ep.margin({ ...query, limit: PAGE_SIZE, offset: page * PAGE_SIZE }, signal),
    `margin|${refreshKey}|${page}`,
  )
  const station = stations.find((s) => s.id === stationId)
  const totals = data?.totals
  const missing = data ? stationsMissingCost(data) : []
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const rent = data?.central_rent ?? null
  const hasRent = Boolean(totals && totals.central_rent !== null && totals.central_rent !== undefined)
  const exportRent = async () => {
    setExporting('rent')
    try {
      const blob = await ep.exportCentralRent(query)
      downloadBlob(rentExportFilename(new Date(), station?.name), blob)
      toast('CSV do aluguel das centrais exportado')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Falha ao exportar', 'error')
    } finally {
      setExporting(null)
    }
  }

  const exportAs = async (fmt: 'csv' | 'pdf') => {
    setExporting(fmt)
    try {
      const blob = await ep.exportMargin(fmt, query)
      downloadBlob(marginExportFilename(fmt, new Date(), station?.name), blob)
      toast(fmt === 'csv' ? 'CSV do resultado exportado' : 'PDF do resultado exportado')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Falha ao exportar', 'error')
    } finally {
      setExporting(null)
    }
  }

  return (
    <>
      <PageHead
        title="Resultado"
        sub={`${periodLabel(period)} · ${station ? station.name : 'Todas as estações'} · margem de contribuição estimada`}
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => exportAs('csv')} disabled={Boolean(exporting) || !total}>
              <Icon name="download" size={16} /> {exporting === 'csv' ? 'Exportando…' : 'CSV'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => exportAs('pdf')} disabled={Boolean(exporting) || !total}>
              <Icon name="download" size={16} /> {exporting === 'pdf' ? 'Exportando…' : 'PDF'}
            </button>
          </>
        }
      />
      <div className="stack">
        <Banner tone="info" icon="info" title={NOT_PROFIT_TITLE}>
          {NOT_PROFIT_TEXT}
        </Banner>
        {error ? <ErrorBanner error={error} onRetry={reload} /> : null}

        <div className="grid kpis">
          <Kpi variant="hero" label="Receita bruta" icon="wallet" loading={!data && !error} value={formatCurrency(totals?.gross, { compact: true })} hint={totals ? `${formatNumber(totals.sessions)} recarga(s) · ${formatEnergy(totals.energy_kwh)}` : undefined} />
          {hasRent ? (
            <Kpi label="Repasse líquido" icon="trendUp" loading={!data && !error} value={formatCurrency(totals?.owner_net_after_rent)} hint={`Repasse ${formatCurrency(totals?.owner_net)} − aluguel das centrais ${formatCurrency(totals?.central_rent)}`} />
          ) : (
            <Kpi label="Repasse" icon="trendUp" loading={!data && !error} value={formatCurrency(totals?.owner_net)} hint="Receita cobrada − comissão − tarifa do provedor" />
          )}
          <Kpi label="Custo da energia" icon="zap" loading={!data && !error} value={totals && !totals.coverage.missing_energy_cost ? formatCurrency(totals.energy_cost) : '—'} hint={totals?.coverage.missing_energy_cost ? `${formatNumber(totals.coverage.missing_energy_cost)} sessão(ões) sem custo informado` : 'kWh × custo do kWh do posto'} hintTone={totals?.coverage.missing_energy_cost ? 'bad' : undefined} />
          {hasRent ? (
            <Kpi label="Resultado estimado" icon="chart" loading={!data && !error} value={totals && totals.result !== null && totals.result !== undefined && !totals.coverage.missing_energy_cost ? formatCurrency(totals.result) : '—'} hint={totals && !totals.coverage.missing_energy_cost ? `Margem antes do aluguel: ${formatCurrency(totals.margin)}` : 'Informe o custo do kWh para calcular'} hintTone={totals && (toNumber(totals.result) ?? 0) < 0 ? 'bad' : undefined} />
          ) : (
            <Kpi label="Margem estimada" icon="chart" loading={!data && !error} value={totals && totals.margin !== null && !totals.coverage.missing_energy_cost ? formatCurrency(totals.margin) : '—'} hint={totals && totals.margin_percent !== null && !totals.coverage.missing_energy_cost ? `${formatPercent(totals.margin_percent)} da receita cobrada` : 'Informe o custo do kWh para calcular'} hintTone={totals && (toNumber(totals.margin) ?? 0) < 0 ? 'bad' : undefined} />
          )}
        </div>

        {data?.warnings.length ? (
          <Banner tone="info" icon="alert" title="Atenção">
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {data.warnings.map((w) => (
                <li key={w}>{w}</li>
              ))}
            </ul>
          </Banner>
        ) : null}

        <div className="grid split">
          <Card title="Da receita à margem" sub="Valores do período, somados por sessão ao centavo (fecham com o CSV e o PDF)" id="cascade">
            {!data && !error ? <SkeletonRows rows={8} height={26} /> : null}
            {data && !data.totals.sessions ? (
              <EmptyState icon="chart" title="Sem recargas encerradas no período">
                O resultado considera recargas concluídas ou interrompidas com energia, pela data de término.
              </EmptyState>
            ) : null}
            {data && data.totals.sessions ? <Cascade report={data} firstMissing={missing[0]?.station_id ?? null} /> : null}
          </Card>
          <div className="stack">
            <Card title="Preço dinâmico" sub="Quanto a tarifa por horário e a demanda somaram à tarifa base" id="dynamic">
              {!data ? (
                <Skeleton height={90} />
              ) : (
                <div className="chart-stats" style={{ margin: 0 }}>
                  <div>
                    <div className="label">Efeito da demanda</div>
                    <div className="value">{formatCurrency(data.dynamic_pricing.demand_effect)}</div>
                    <div className="dim" style={{ fontSize: 12.5 }}>
                      {data.dynamic_pricing.sessions_with_increase
                        ? `${formatNumber(data.dynamic_pricing.sessions_with_increase)} recarga(s) com acréscimo · média ${formatNumber(data.dynamic_pricing.average_multiplier, 2)}×`
                        : 'Nenhuma recarga com acréscimo'}
                    </div>
                  </div>
                  <div>
                    <div className="label">Efeito do horário</div>
                    <div className="value">{data.dynamic_pricing.schedule_effect === null ? '—' : formatCurrency(data.dynamic_pricing.schedule_effect)}</div>
                    <div className="dim" style={{ fontSize: 12.5 }}>Diferença para a tarifa base do conector</div>
                  </div>
                  {data.dynamic_pricing.speed_effect !== null && data.dynamic_pricing.speed_effect !== undefined ? (
                    <div>
                      <div className="label">Efeito da velocidade</div>
                      <div className="value">{formatCurrency(data.dynamic_pricing.speed_effect)}</div>
                      <div className="dim" style={{ fontSize: 12.5 }}>Velocidade reduzida ou tarifa própria escolhida</div>
                    </div>
                  ) : null}
                </div>
              )}
            </Card>
            <Card title="Cupons" sub="O desconto é do posto e sai antes da comissão" id="coupons-effect">
              {!data ? (
                <Skeleton height={70} />
              ) : (
                <div className="chart-stats" style={{ margin: 0 }}>
                  <div>
                    <div className="label">Desconto concedido</div>
                    <div className="value">{formatCurrency(data.coupons.discount)}</div>
                  </div>
                  <div>
                    <div className="label">Recargas com cupom</div>
                    <div className="value">{formatNumber(data.coupons.sessions)}</div>
                  </div>
                </div>
              )}
            </Card>
            <Card title="Custo do kWh por posto" sub="Informado pelo dono; comissão definida em contrato" id="costs">
              {!data ? (
                <SkeletonRows rows={3} height={20} />
              ) : (
                <div>
                  {data.stations.map((s) => (
                    <div key={s.station_id} className="list-row" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 0' }}>
                      <span style={{ flex: 1, minWidth: 0 }}>{s.station_name}</span>
                      <span className="tabular muted" style={{ fontSize: 13 }}>
                        {formatNumber(s.platform_fee_percent, 0)}%
                      </span>
                      {s.energy_cost_per_kwh === null ? (
                        <CostLink stationId={s.station_id} label="— · Configurar" />
                      ) : (
                        <Link to={`/estacoes/${s.station_id}#economics`} className="tabular strong" style={{ fontSize: 13.5 }}>
                          {formatCurrency(s.energy_cost_per_kwh)}/kWh
                        </Link>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>

        {rent && rent.lines.length ? (
          <Card
            title="Aluguel das centrais"
            sub={`${formatNumber(rent.centrals)} ${rent.centrals === 1 ? 'central' : 'centrais'} · valor mensal rateado pelos dias de vínculo no mês e descontado do repasse`}
            id="central-rent"
            action={
              <button type="button" className="btn btn-secondary" onClick={exportRent} disabled={Boolean(exporting)}>
                <Icon name="download" size={16} /> {exporting === 'rent' ? 'Exportando…' : 'CSV do aluguel'}
              </button>
            }
          >
            <RentTable lines={rent.lines} total={rent.total} />
          </Card>
        ) : null}

        <Card title="Por sessão" sub={data ? `${formatNumber(total)} recarga(s) encerrada(s) no período` : undefined} id="margin-sessions">
          {!data && !error ? <SkeletonRows rows={6} height={22} /> : null}
          {data && !data.items.length ? (
            <EmptyState icon="clock" title="Nenhuma sessão no período">
              Ajuste o período ou a estação no topo da página.
            </EmptyState>
          ) : null}
          {data && data.items.length ? (
            <>
              <div style={{ opacity: loading ? 0.6 : 1, transition: 'opacity .15s' }}>
                <SessionsTable items={data.items} />
              </div>
              <div className="pager">
                <span>
                  {formatNumber(page * PAGE_SIZE + 1)}–{formatNumber(Math.min(total, (page + 1) * PAGE_SIZE))} de {formatNumber(total)}
                </span>
                <div className="btns">
                  <button type="button" className="btn btn-secondary" disabled={page === 0 || loading} onClick={() => setPage((p) => p - 1)} aria-label="Página anterior">
                    <Icon name="chevronLeft" size={16} /> Anterior
                  </button>
                  <span style={{ alignSelf: 'center' }}>
                    {page + 1} / {pages}
                  </span>
                  <button type="button" className="btn btn-secondary" disabled={page + 1 >= pages || loading} onClick={() => setPage((p) => p + 1)} aria-label="Próxima página">
                    Próxima <Icon name="chevronRight" size={16} />
                  </button>
                </div>
              </div>
            </>
          ) : null}
          {data?.methodology.length ? (
            <details style={{ marginTop: 14 }}>
              <summary className="muted" style={{ cursor: 'pointer', fontSize: 13 }}>
                Como calculamos
              </summary>
              <ul className="dim" style={{ fontSize: 12.5, margin: '8px 0 0', paddingLeft: 18 }}>
                {data.methodology.map((m) => (
                  <li key={m}>{m}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </Card>
      </div>
    </>
  )
}
