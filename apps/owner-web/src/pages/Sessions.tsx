import { useEffect, useState } from 'react'
import { fetchAllSessions } from '../api/endpoints'
import type { SessionItem } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Badge, Card, Drawer, EmptyState, ErrorBanner, PageHead, SkeletonRows } from '../components/ui'
import { downloadText, exportFilename, sessionsCsv, sessionsJson } from '../lib/exporters'
import { useFilters } from '../lib/filters'
import { formatCurrency, formatDateTime, formatDuration, formatEnergy, formatNumber, formatShortDateTime, formatTariff } from '../lib/format'
import { END_REASON_LABELS, SESSION_STATUS, SESSION_STATUS_ORDER, SOURCE_LABELS } from '../lib/labels'
import { CHANNEL_LABELS, channelTone, isSimulated, paymentChannel, paymentMethodLabel } from '../lib/kiosk'
import { overstayCell, paymentBadge } from '../lib/overstay'
import { periodLabel } from '../lib/period'
import { useApi } from '../lib/useApi'

const PAGE_SIZE = 25

function StatusBadge({ status }: { status: string }) {
  const meta = SESSION_STATUS[status] ?? { label: status, tone: 'gray' as const }
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

/** Selo do pagamento: rótulo da API (sem a marca de ambiente) e capturado/devolvido. */
function PaymentBadge({ session, detail }: { session: SessionItem; detail?: boolean }) {
  const badge = paymentBadge(session.payment)
  if (!badge) return <span className="dim">—</span>
  // "Cobrado R$ 32,10 · Devolvido R$ 7,90": o selo leva a primeira parte e o resto vai abaixo.
  const [head, ...rest] = badge.label.split(' · ')
  return (
    <span style={{ display: 'inline-flex', flexDirection: 'column', gap: 3, alignItems: 'flex-start' }}>
      <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
        <Badge tone={badge.tone}>{head}</Badge>
      </span>
      {rest.length && !(detail && badge.detail) ? <span className="dim" style={{ fontSize: 11.5 }}>{rest.join(' · ')}</span> : null}
      {detail && badge.detail ? <span className="dim" style={{ fontSize: 11.5 }}>{badge.detail}</span> : null}
    </span>
  )
}

/** Selo do canal (App / QR do painel / Totem) e o método (Sem cobrança / Stripe). */
function ChannelBadge({ session }: { session: SessionItem }) {
  const channel = paymentChannel(session.payment)
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', flexWrap: 'wrap' }}>
      <Badge tone={channelTone(channel)}>{CHANNEL_LABELS[channel]}</Badge>
      {session.payment ? <span className="dim" style={{ fontSize: 11.5 }}>{paymentMethodLabel(session.payment)}</span> : null}
    </span>
  )
}

function OverstayValue({ session }: { session: SessionItem }) {
  const cell = overstayCell(session)
  return <span className={cell.text === '—' ? 'dim' : undefined}>{cell.text}</span>
}

function SessionDrawer({ session, onClose }: { session: SessionItem; onClose(): void }) {
  return (
    <Drawer title={`Sessão ${session.public_code}`} onClose={onClose}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span className="tile white">
          <Icon name="zap" size={22} />
        </span>
        <div>
          <div style={{ fontWeight: 600 }}>{session.station_name}</div>
          <StatusBadge status={session.status} />
        </div>
      </div>
      <div className="card" style={{ background: '#262626', border: 0 }}>
        <div className="chart-stats" style={{ margin: 0 }}>
          <div>
            <div className="label">Valor estimado</div>
            <div className="value">{formatCurrency(session.cost_estimate)}</div>
          </div>
          <div>
            <div className="label">Energia</div>
            <div className="value">{formatEnergy(session.energy_kwh)}</div>
          </div>
        </div>
      </div>
      <dl className="dl">
        <div>
          <dt>Criada em</dt>
          <dd>{formatDateTime(session.created_at)}</dd>
        </div>
        <div>
          <dt>Duração</dt>
          <dd>{formatDuration(session.duration_minutes)}</dd>
        </div>
        <div>
          <dt>Início</dt>
          <dd>{formatDateTime(session.started_at)}</dd>
        </div>
        <div>
          <dt>Fim</dt>
          <dd>{formatDateTime(session.ended_at, session.status === 'charging' ? 'Em andamento' : '—')}</dd>
        </div>
        <div>
          <dt>Tarifa</dt>
          <dd>{formatTariff(session.price_per_kwh)}</dd>
        </div>
        <div>
          <dt>Desconto</dt>
          <dd>{session.discount_percent ? `${session.discount_percent}%` : 'Sem cupom'}</dd>
        </div>
        <div>
          <dt>Origem da medição</dt>
          <dd>{SOURCE_LABELS[session.source] ?? (session.source || '—')}</dd>
        </div>
        <div>
          <dt>Motivo de término</dt>
          <dd>{END_REASON_LABELS[session.end_reason] ?? (session.end_reason || '—')}</dd>
        </div>
        {'payment' in session ? (
          <div className="full">
            <dt>{isSimulated(session.payment) ? 'Pagamento' : 'Pagamento (Stripe)'}</dt>
            <dd>
              <PaymentBadge session={session} detail />
              {session.payment ? (
                <div className="dim" style={{ fontSize: 12, fontWeight: 400, marginTop: 4 }}>
                  Teto autorizado {formatCurrency(session.payment.amount)}
                  {` · ${CHANNEL_LABELS[paymentChannel(session.payment)]}`}
                  {isSimulated(session.payment) ? ' · sem cobrança' : session.payment.method ? ` · ${session.payment.method === 'pix' ? 'Pix' : 'cartão'}` : ''}
                </div>
              ) : null}
            </dd>
          </div>
        ) : null}
        {'payment' in session ? (
          <div>
            <dt>Canal</dt>
            <dd>
              <ChannelBadge session={session} />
            </dd>
          </div>
        ) : null}
        {'payment' in session ? (
          <div>
            <dt>Método</dt>
            <dd>{paymentMethodLabel(session.payment)}</dd>
          </div>
        ) : null}
        {'overstay_fee' in session ? (
          <div className="full">
            <dt>Permanência após a recarga</dt>
            <dd>
              <OverstayValue session={session} />
            </dd>
          </div>
        ) : null}
        <div className="full">
          <dt>ID da sessão</dt>
          <dd className="mono">{session.id}</dd>
        </div>
      </dl>
      <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
        Os relatórios não incluem dados pessoais do motorista. Valores são estimativas baseadas na energia registrada.
      </p>
    </Drawer>
  )
}

export default function Sessions() {
  const { ep } = useAuth()
  const toast = useToast()
  const { query, refreshKey, period } = useFilters()
  const [statuses, setStatuses] = useState<string[]>([])
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [page, setPage] = useState(0)
  const [selected, setSelected] = useState<SessionItem | null>(null)
  const [exporting, setExporting] = useState<null | 'csv' | 'json'>(null)

  useEffect(() => {
    const timer = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(timer)
  }, [search])
  useEffect(() => setPage(0), [refreshKey, q, statuses])

  const filters = { ...query, status: statuses.join(',') || undefined, q: q || undefined }
  const { data, error, loading, reload } = useApi(
    (signal) => ep.sessions({ ...filters, limit: PAGE_SIZE, offset: page * PAGE_SIZE }, signal),
    `sessions|${refreshKey}|${statuses.join(',')}|${q}|${page}`,
  )
  const total = data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  // Colunas das frentes A e D só aparecem quando a API envia os campos.
  const showPayment = Boolean(data?.items.some((item) => 'payment' in item))
  const showOverstay = Boolean(data?.items.some((item) => 'overstay_fee' in item))

  const toggle = (status: string) => setStatuses((list) => (list.includes(status) ? list.filter((s) => s !== status) : [...list, status]))

  const exportAs = async (format: 'csv' | 'json') => {
    setExporting(format)
    try {
      const result = await fetchAllSessions(ep, filters)
      if (!result.items.length) {
        toast('Nenhuma sessão para exportar com estes filtros', 'error')
        return
      }
      const now = new Date()
      if (format === 'csv') downloadText(exportFilename('csv', now), sessionsCsv(result.items), 'text/csv;charset=utf-8')
      else downloadText(exportFilename('json', now), sessionsJson(result.items, filters, now), 'application/json')
      toast(result.truncated ? `Exportadas as ${formatNumber(result.items.length)} sessões mais recentes de ${formatNumber(result.total)}` : `${formatNumber(result.items.length)} sessões exportadas`)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Falha ao exportar', 'error')
    } finally {
      setExporting(null)
    }
  }

  return (
    <>
      <PageHead
        title="Sessões"
        sub={`${periodLabel(period)} · ${data ? `${formatNumber(total)} sessão(ões)` : 'carregando…'}`}
        actions={
          <>
            <button type="button" className="btn btn-secondary" onClick={() => exportAs('csv')} disabled={Boolean(exporting) || !total}>
              <Icon name="download" size={16} /> {exporting === 'csv' ? 'Exportando…' : 'CSV'}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => exportAs('json')} disabled={Boolean(exporting) || !total}>
              <Icon name="download" size={16} /> {exporting === 'json' ? 'Exportando…' : 'JSON'}
            </button>
          </>
        }
      />
      <Card>
        <div className="toolbar">
          <div className="input-affix search">
            <span className="lead">
              <Icon name="search" size={17} />
            </span>
            <input className="input" type="search" placeholder="Buscar por estação, ponto ou ID" value={search} onChange={(e) => setSearch(e.target.value)} aria-label="Buscar sessões" maxLength={100} style={{ width: '100%' }} />
          </div>
          <div className="chips" role="group" aria-label="Filtrar por status">
            {SESSION_STATUS_ORDER.map((status) => (
              <button key={status} type="button" className="chip" aria-pressed={statuses.includes(status)} onClick={() => toggle(status)}>
                {SESSION_STATUS[status].label}
              </button>
            ))}
            {statuses.length ? (
              <button type="button" className="chip" onClick={() => setStatuses([])}>
                Limpar
              </button>
            ) : null}
          </div>
        </div>
        {error ? <ErrorBanner error={error} onRetry={reload} /> : null}
        {!data && !error ? <SkeletonRows rows={8} height={22} /> : null}
        {data && !data.items.length ? (
          <EmptyState icon="clock" title="Nenhuma sessão encontrada">
            {q || statuses.length ? 'Ajuste a busca ou os filtros de status.' : 'Não houve recargas no período selecionado.'}
          </EmptyState>
        ) : null}
        {data && data.items.length ? (
          <>
            <div className="table-wrap" style={{ opacity: loading ? 0.6 : 1, transition: 'opacity .15s' }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Criada em</th>
                    <th>Estação</th>
                    <th>Ponto</th>
                    <th>Status</th>
                    <th className="right">Duração</th>
                    <th className="right">Energia</th>
                    <th className="right">Tarifa</th>
                    <th className="right">Valor</th>
                    {showOverstay ? <th className="right">Permanência</th> : null}
                    {showPayment ? <th>Canal</th> : null}
                    {showPayment ? <th>Pagamento</th> : null}
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr
                      key={item.id}
                      className="clickable"
                      tabIndex={0}
                      onClick={() => setSelected(item)}
                      onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && (e.preventDefault(), setSelected(item))}
                      aria-label={`Ver detalhes da sessão ${item.public_code} de ${formatShortDateTime(item.created_at)}`}
                    >
                      <td className="tabular">{formatShortDateTime(item.created_at)}</td>
                      <td>{item.station_name}</td>
                      <td className="strong">{item.public_code}</td>
                      <td>
                        <StatusBadge status={item.status} />
                      </td>
                      <td className="right tabular">{formatDuration(item.duration_minutes)}</td>
                      <td className="right tabular">{formatEnergy(item.energy_kwh)}</td>
                      <td className="right tabular muted">{formatTariff(item.price_per_kwh)}</td>
                      <td className="right tabular strong">{formatCurrency(item.cost_estimate)}</td>
                      {showOverstay ? (
                        <td className="right tabular">
                          <OverstayValue session={item} />
                        </td>
                      ) : null}
                      {showPayment ? (
                        <td>
                          <ChannelBadge session={item} />
                        </td>
                      ) : null}
                      {showPayment ? (
                        <td>
                          <PaymentBadge session={item} />
                        </td>
                      ) : null}
                    </tr>
                  ))}
                </tbody>
              </table>
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
      </Card>
      {selected ? <SessionDrawer session={selected} onClose={() => setSelected(null)} /> : null}
    </>
  )
}
