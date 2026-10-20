import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { StationPower } from '../../api/operations'
import { useAuth } from '../../auth/AuthContext'
import { formatTime, toNumber } from '../../lib/format'
import {
  availabilityText,
  BUILDING_LOAD_DEBOUNCE_MS,
  debounce,
  formatKw,
  loadSliderMax,
  POWER_POLL_MS,
  POWER_STATE,
  POWER_TRIGGER,
  powerUsage,
  validateSiteLimit,
} from '../../lib/power'
import { useToast } from '../Toast'
import { Badge, Card, EmptyState, ErrorBanner, Field, Skeleton, Switch } from '../ui'

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Não foi possível salvar. Tente novamente.'
}

function limitInput(value: string | null | undefined): string {
  const number = toNumber(value)
  return number === null ? '' : String(Math.round(number * 10) / 10).replace('.', ',')
}

/** Lê a visão de potência do posto a cada ~1,5 s com a aba visível (para quando a página fecha). */
function usePowerView(stationId: string) {
  const { ep } = useAuth()
  const [view, setView] = useState<StationPower | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [unsupported, setUnsupported] = useState(false)
  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | null = null
    const schedule = () => {
      if (alive) timer = setTimeout(tick, POWER_POLL_MS)
    }
    const tick = async () => {
      if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return schedule()
      controller = new AbortController()
      try {
        const next = await ep.power(stationId, controller.signal)
        if (!alive) return
        setView(next)
        setError(null)
      } catch (err) {
        if (!alive || controller.signal.aborted) return
        if (err instanceof ApiError && err.status === 404) {
          setUnsupported(true)
          return
        }
        setError(err instanceof ApiError ? err : new ApiError(0, 'unexpected', 'Falha ao atualizar a potência.'))
      }
      schedule()
    }
    void tick()
    return () => {
      alive = false
      clearTimeout(timer)
      controller?.abort()
    }
  }, [ep, stationId])
  return { view, setView, error, unsupported }
}

/** Energia do estabelecimento (frente B): limite contratado, rebalanceamento e consumo simulado da loja. */
export function SitePowerCard({ stationId }: { stationId: string }) {
  const { ep } = useAuth()
  const toast = useToast()
  const { view, setView, error, unsupported } = usePowerView(stationId)
  const [limit, setLimit] = useState('')
  const [limitTouched, setLimitTouched] = useState(false)
  const [saving, setSaving] = useState<null | 'limit' | 'toggle'>(null)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [load, setLoad] = useState<number | null>(null)
  const [loadSending, setLoadSending] = useState(false)
  const queue = useRef<Promise<unknown>>(Promise.resolve())
  const pendingLoad = useRef(false)

  useEffect(() => {
    if (view && !limitTouched) setLimit(limitInput(view.site_limit_kw))
    // Enquanto o vendedor arrasta (ou o envio está pendente) o controle fica com o valor local.
    if (view && !pendingLoad.current) setLoad(toNumber(view.building_load_kw) ?? 0)
  }, [view, limitTouched])

  const sendLoad = useMemo(
    () =>
      debounce((kw: number) => {
        setLoadSending(true)
        queue.current = queue.current
          .then(() => ep.putBuildingLoad(stationId, kw.toFixed(1)))
          .then((next) => setView(next))
          .catch((err) => setSaveError(errorText(err)))
          .finally(() => {
            pendingLoad.current = false
            setLoadSending(false)
          })
      }, BUILDING_LOAD_DEBOUNCE_MS),
    [ep, stationId, setView],
  )
  useEffect(() => () => sendLoad.flush(), [sendLoad])

  if (unsupported) return null

  const usage = view ? powerUsage(view) : null
  const limitCheck = validateSiteLimit(limit)
  const limitDirty = view ? limit.trim() !== limitInput(view.site_limit_kw) : false
  const max = view ? loadSliderMax(view) : 100

  const saveSite = async (body: { site_limit_kw?: string | null; rebalance_enabled?: boolean }, kind: 'limit' | 'toggle') => {
    setSaving(kind)
    setSaveError(null)
    try {
      const next = await ep.putPowerSite(stationId, body)
      setView(next)
      setLimitTouched(false)
      setLimit(limitInput(next.site_limit_kw))
      toast(kind === 'toggle' ? (next.rebalance_enabled ? 'Rebalanceamento ligado' : 'Rebalanceamento desligado') : 'Limite contratado salvo')
    } catch (err) {
      setSaveError(errorText(err))
    } finally {
      setSaving(null)
    }
  }
  const submitLimit = (event: FormEvent) => {
    event.preventDefault()
    if (!limitDirty || limitCheck.error || limitCheck.value === undefined || saving) return
    void saveSite({ site_limit_kw: limitCheck.value }, 'limit')
  }
  const onSlide = (value: number) => {
    pendingLoad.current = true
    setLoad(value)
    sendLoad(value)
  }

  return (
    <Card
      title={
        <span>
          <span className="live-dot" aria-hidden />
          Energia do estabelecimento
        </span>
      }
      sub={`Divide a potência entre os carros sem passar do limite contratado · atualiza a cada ${POWER_POLL_MS / 1000} s`}
      id="site-power"
    >
      {error && !view ? <ErrorBanner error={error} /> : null}
      {!view && !error ? <Skeleton height={220} /> : null}
      {view && usage ? (
        <div className="stack" style={{ gap: 18 }}>
          <form className="form-grid" onSubmit={submitLimit} noValidate>
            <Field label="Limite contratado" hint="instalação inteira, loja incluída" error={limitDirty ? limitCheck.error : null}>
              <div style={{ display: 'flex', gap: 8 }}>
                <div className="input-affix" style={{ flex: 1 }}>
                  <input
                    className="input"
                    inputMode="decimal"
                    placeholder="sem limite"
                    value={limit}
                    onChange={(e) => {
                      setLimit(e.target.value)
                      setLimitTouched(true)
                    }}
                    aria-invalid={Boolean(limitCheck.error)}
                  />
                  <span className="affix">kW</span>
                </div>
                <button type="submit" className="btn btn-primary" disabled={!limitDirty || Boolean(limitCheck.error) || saving !== null}>
                  {saving === 'limit' ? 'Salvando…' : 'Salvar'}
                </button>
              </div>
            </Field>
            <Field label="Rebalanceamento ao vivo">
              <div style={{ minHeight: 44, display: 'flex', alignItems: 'center' }}>
                <Switch
                  checked={view.rebalance_enabled}
                  disabled={saving !== null}
                  onChange={(value) => void saveSite({ rebalance_enabled: value }, 'toggle')}
                  label={view.rebalance_enabled ? 'Ligado: ajusta os pontos a cada sincronização' : 'Desligado: vale a potência do início'}
                />
              </div>
            </Field>
          </form>

          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8, flexWrap: 'wrap' }}>
              <label htmlFor={`load-${stationId}`} style={{ fontWeight: 600, fontSize: 14 }}>
                Consumo da loja
              </label>
              <Badge tone="amber">SIMULADO</Badge>
              <span className="spacer" style={{ flex: 1 }} />
              <span className="tabular" style={{ fontWeight: 600 }}>
                {formatKw(load)}
              </span>
              {loadSending ? <span className="dim" style={{ fontSize: 12 }}>enviando…</span> : null}
            </div>
            <input
              id={`load-${stationId}`}
              type="range"
              min={0}
              max={max}
              step={0.5}
              value={load ?? 0}
              onChange={(e) => onSlide(Number(e.target.value))}
              onPointerUp={() => sendLoad.flush()}
              onKeyUp={() => sendLoad.flush()}
              style={{ width: '100%', accentColor: '#6B9BFF' }}
              aria-valuetext={`${formatKw(load)} de consumo simulado da loja`}
            />
            <div className="dim" style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12 }}>
              <span>0 kW</span>
              <span>Sem medidor: valor simulado para a demonstração</span>
              <span>{formatKw(max)}</span>
            </div>
          </div>

          <div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap', marginBottom: 8 }}>
              <span style={{ fontWeight: 600 }}>
                Em uso <span className="tabular">{formatKw(usage.used)}</span> de <span className="tabular">{formatKw(usage.available)}</span> disponíveis
              </span>
              <span className="muted" style={{ fontSize: 13 }}>
                {view.cars} carro(s) carregando
              </span>
            </div>
            <span className="bar" style={{ display: 'block', height: 10 }} aria-hidden>
              <i style={{ width: `${usage.percent}%`, background: usage.over ? '#D72B32' : '#6B9BFF' }} />
            </span>
            <p className="dim" style={{ margin: '8px 0 0', fontSize: 12.5 }}>
              {availabilityText(view)}
            </p>
            {usage.exceeded > 0 ? (
              <p className="red" style={{ margin: '6px 0 0', fontSize: 13, fontWeight: 600 }}>
                Excesso transitório de {formatKw(usage.exceeded)}: as reduções já foram enviadas e aguardam a confirmação dos equipamentos.
              </p>
            ) : null}
          </div>

          {view.points.length ? (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Ponto</th>
                    <th className="right">Alvo</th>
                    <th className="right">Aplicada</th>
                    <th>Estado</th>
                    <th>Motivo</th>
                  </tr>
                </thead>
                <tbody>
                  {view.points.map((point) => {
                    const session = point.session
                    const state = session?.power_state ? (POWER_STATE[session.power_state] ?? { label: session.power_state, tone: 'gray' as const }) : null
                    return (
                      <tr key={point.connector_id}>
                        <td className="strong">
                          {point.public_code}
                          <div className="dim" style={{ fontSize: 11.5, fontWeight: 400 }}>
                            {formatKw(point.power_kw)} nominal{point.adjustable ? '' : ' · carga fixa'}
                            {point.online ? '' : ' · offline'}
                          </div>
                        </td>
                        <td className="right tabular">{session ? formatKw(session.target_kw) : '—'}</td>
                        <td className="right tabular strong">{session ? formatKw(session.applied_kw) : '—'}</td>
                        <td>{state ? <Badge tone={state.tone}>{state.label}</Badge> : <span className="dim">Livre</span>}</td>
                        <td className="muted" style={{ fontSize: 13, whiteSpace: 'normal', minWidth: 220 }}>
                          {session?.reason ?? session?.reason_short ?? '—'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <EmptyState icon="plug" title="Nenhum ponto neste posto" />
          )}

          <div>
            <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
              Últimas decisões
            </div>
            {view.decisions.length ? (
              <div>
                {view.decisions.slice(0, 5).map((decision) => (
                  <div key={decision.id} className="list-row" style={{ padding: '8px 0', alignItems: 'flex-start' }}>
                    <span className="tabular dim" style={{ fontSize: 12.5, width: 44, flex: 'none' }}>
                      {formatTime(decision.created_at)}
                    </span>
                    <div className="grow">
                      <div style={{ fontSize: 13.5 }}>{decision.summary}</div>
                      <div className="dim" style={{ fontSize: 12 }}>
                        {POWER_TRIGGER[decision.trigger] ?? decision.trigger} · {formatKw(decision.available_kw)} disponíveis
                        {(toNumber(decision.exceeded_kw) ?? 0) > 0 ? <span className="red"> · excesso {formatKw(decision.exceeded_kw)}</span> : null}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="dim" style={{ margin: 0, fontSize: 13 }}>
                Nenhuma decisão registrada ainda.
              </p>
            )}
          </div>
          {saveError ? <ErrorBanner error={saveError} title="Alteração de energia não salva" /> : null}
          {error ? <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>Última atualização falhou: {error.message}</p> : null}
        </div>
      ) : null}
    </Card>
  )
}
