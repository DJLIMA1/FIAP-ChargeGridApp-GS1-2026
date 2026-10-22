import { useEffect, useState, type CSSProperties, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { StationPower } from '../../api/operations'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import {
  budget,
  capText,
  connectorLine,
  connectorPower,
  equation,
  ESTIMATE_HELP,
  ESTIMATE_LABEL,
  formatKw,
  limitInput,
  limitsChanges,
  limitsDraft,
  moveCap,
  moveLimit,
  moveStore,
  POWER_POLL_MS,
  powerSummary,
  REBALANCE_HELP,
  remainder,
  restoreDefaults,
  segments,
  storeText,
  typedValues,
  type LimitsDraft,
  type Move,
  type PowerSiteBody,
} from '../../lib/power'
import { useToast } from '../Toast'
import { Badge, Card, ErrorBanner, FieldGroup, Skeleton } from '../ui'

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : 'Não foi possível salvar. Tente novamente.'
}

/** Lê `GET /stations/{id}/power` a cada 3 s com a aba visível (para quando a página fecha). */
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

function Stat({ label, value, detail, badge }: { label: string; value: string; detail: string; badge?: string }) {
  return (
    <div className="power-stat">
      <span className="label">
        {label} {badge ? <Badge tone="gray">{badge}</Badge> : null}
      </span>
      <span className="value tabular">{value}</span>
      <span className="dim" style={{ fontSize: 12.5 }}>
        {detail}
      </span>
    </div>
  )
}

const pct = (kw: number, scale: number) => `${(Math.max(0, kw) / scale) * 100}%`

/**
 * Régua 0→escala: loja (âmbar, listrada = estimativa), carros em uso / carregadores (verde), parte
 * bloqueada pelo teto, marcador do contratado e trilho acima dele. Mesmas faixas do app.
 */
function LimitsBar({ draft, used }: { draft: LimitsDraft; used?: number | null }) {
  const live = used !== undefined
  const items = segments(draft, used)
  const label = `Régua de 0 a ${formatKw(draft.scale)}: loja ${storeText(draft)} (estimativa), ${formatKw(budget(draft))} para os carregadores, contratado ${formatKw(draft.limit)}.`
  return (
    <div className="limits-ruler">
      <div className="limits-bar" role="img" aria-label={label} data-testid="limits-bar">
        {items.map((item) => (
          <span key={item.key} className={`seg ${item.key}${live && item.key === 'chargers' ? ' free' : ''}`} style={{ width: pct(item.kw, draft.scale) }} />
        ))}
        <span className="marker" style={{ left: pct(draft.limit, draft.scale) }} aria-hidden />
      </div>
      <div className="limits-axis dim">
        <span>0</span>
        <span>{formatKw(draft.scale)}</span>
      </div>
      <div className="limits-legend dim">
        <span>
          <i className="dot store" /> Loja (estimativa)
        </span>
        {live ? (
          <>
            <span>
              <i className="dot cars" /> Em uso
            </span>
            <span>
              <i className="dot free" /> Livre
            </span>
          </>
        ) : (
          <span>
            <i className="dot cars" /> Carregadores
          </span>
        )}
        <span>
          <i className="dot marker" /> Contratado {formatKw(draft.limit)}
        </span>
      </div>
    </div>
  )
}

function Lane({ dot, title, value, badge, children, help }: { dot: string; title: string; value: string; badge?: string; children: React.ReactNode; help: string }) {
  return (
    <div className="limits-lane">
      <div className="lane-head">
        <span className="lane-title">
          <i className={`dot ${dot}`} /> {title} {badge ? <Badge tone="gray">{badge}</Badge> : null}
        </span>
        <span className="strong tabular">{value}</span>
      </div>
      {children}
      <div className="dim lane-help">{help}</div>
    </div>
  )
}

/**
 * Potência do posto (mesmo conteúdo da tela Potência do app): disponível para os carregadores, a régua com
 * os carros agora, limite contratado, margem ESTIMADA da loja (o pico fica reservado o tempo todo; nada é
 * medido nem simulado), rebalanceamento (ligado por padrão), Limites com faixas de arrastar alinhadas à
 * régua (loja mínimo–pico, contratado, máximo dos carregadores) e a potência configurada × efetiva.
 */
export function PowerCard({ station }: { station: Station }) {
  const { ep } = useAuth()
  const toast = useToast()
  const { view, setView, error, unsupported } = usePowerView(station.id)
  const [edited, setEdited] = useState<LimitsDraft | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [typed, setTyped] = useState<{ limit: string; min: string; peak: string; cap: string } | null>(null)
  const [typedError, setTypedError] = useState<string | null>(null)
  const [saving, setSaving] = useState<null | 'site' | 'toggle'>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  if (unsupported) return null
  // O rascunho começa com o que vale agora e não acompanha a atualização periódica.
  const original = view ? limitsDraft(view) : null
  const draft = edited ?? original
  const changes: PowerSiteBody = draft && original ? limitsChanges(draft, original) : {}
  const dirty = Object.keys(changes).length > 0

  const apply = (move: Move) => {
    setEdited(move.draft)
    setHint(move.hint)
  }

  const put = async (body: PowerSiteBody, kind: 'site' | 'toggle') => {
    setSaving(kind)
    setSaveError(null)
    try {
      const next = await ep.putPowerSite(station.id, body)
      setView(next)
      if (kind === 'site') {
        setEdited(null)
        setHint(null)
      }
      toast(kind === 'toggle' ? (next.rebalance_enabled ? 'Rebalanceamento ligado' : 'Rebalanceamento desligado') : 'Limites salvos')
    } catch (err) {
      setSaveError(errorText(err))
    } finally {
      setSaving(null)
    }
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!dirty || saving) return
    void put(changes, 'site')
  }
  const openTyped = () => {
    if (!draft) return
    setTypedError(null)
    setTyped({ limit: limitInput(draft.limit), min: limitInput(draft.min), peak: limitInput(draft.peak), cap: draft.cap === null ? '' : limitInput(draft.cap) })
  }
  const applyTyped = () => {
    if (!draft || !typed) return
    const result = typedValues(draft, typed)
    if (result.error) return setTypedError(result.error)
    setEdited(result.draft!)
    setHint(null)
    setTyped(null)
  }

  const summary = view ? powerSummary(view) : null
  const points = station.connectors.filter((c) => !c.retired)
  const step = draft?.step ?? 1
  const left = draft ? remainder(draft) : 0
  const used = view ? Number(view.envelope_kw ?? view.allocated_kw ?? 0) : 0

  return (
    <Card title="Potência" sub={`${REBALANCE_HELP} Atualiza a cada ${POWER_POLL_MS / 1000} s.`} id="power">
      {error && !view ? <ErrorBanner error={error} /> : null}
      {!view && !error ? <Skeleton height={220} /> : null}
      {view && summary && draft && original ? (
        <div className="stack" style={{ gap: 18 }}>
          <div className="power-hero" data-testid="power-available">
            <span className="label">Disponível para os carregadores</span>
            <span className="value tabular">{summary.available}</span>
            <LimitsBar draft={original} used={used} />
          </div>
          <div className="power-stats">
            <Stat label="Limite contratado" value={`${summary.limit}${view.site_limit_default ? ' (padrão)' : ''}`} detail={summary.limitDetail} />
            <Stat label="Margem da loja" badge={ESTIMATE_LABEL} value={summary.store} detail={summary.storeDetail} />
            <Stat label="Carros agora" value={summary.cars} detail={summary.carsDetail} />
          </div>
          {summary.over ? (
            <p className="red" style={{ margin: 0, fontSize: 13, fontWeight: 600 }}>
              {summary.over}
            </p>
          ) : null}

          <FieldGroup label="Rebalanceamento">
            <div className="segmented" data-testid="rebalance" style={{ height: 52, maxWidth: 340 }}>
              <button type="button" aria-pressed={view.rebalance_enabled} disabled={saving !== null} onClick={() => !view.rebalance_enabled && void put({ rebalance_enabled: true }, 'toggle')} style={{ flex: 1, height: 50 }}>
                Ligado
              </button>
              <button type="button" aria-pressed={!view.rebalance_enabled} disabled={saving !== null} onClick={() => view.rebalance_enabled && void put({ rebalance_enabled: false }, 'toggle')} style={{ flex: 1, height: 50 }}>
                Desligado
              </button>
            </div>
            <div className="dim" style={{ fontSize: 12.5 }}>
              {view.rebalance_enabled
                ? 'Ligado: ajusta os carregadores a cada sincronização.'
                : 'Desligado: os limites valem no início de cada recarga, divididos entre os carregadores ativos.'}
            </div>
          </FieldGroup>

          <form className="limits-form stack" onSubmit={submit} noValidate data-testid="limits">
            <div>
              <div className="strong" style={{ fontSize: 15 }}>
                Limites
              </div>
              <div className="dim" style={{ fontSize: 12.5 }}>
                Quanto o posto pode puxar da rede e quanto fica guardado para a loja.
              </div>
            </div>
            <div className="limits-head">
              <span className="label">Para os carregadores</span>
              <span className="value tabular" data-testid="limits-budget">
                {formatKw(budget(draft))}
              </span>
              <span className="dim" style={{ fontSize: 12.5 }}>
                {equation(draft)}
              </span>
            </div>
            <LimitsBar draft={draft} />

            <Lane dot="store" title="Loja" badge={ESTIMATE_LABEL} value={storeText(draft)} help={ESTIMATE_HELP}>
              <div className="limits-track dual">
                <span className="band store" style={{ '--f-left': draft.min / draft.scale, '--f-width': (draft.peak - draft.min) / draft.scale } as CSSProperties} />
                <input type="range" className="limits-range" aria-label="Consumo mínimo estimado da loja" data-testid="store-min" min={0} max={draft.scale} step={step} value={draft.min} onChange={(e) => apply(moveStore(draft, Number(e.target.value), draft.peak))} />
                <input type="range" className="limits-range" aria-label="Pico estimado da loja" data-testid="store-peak" min={0} max={draft.scale} step={step} value={draft.peak} onChange={(e) => apply(moveStore(draft, Math.min(draft.min, Number(e.target.value)), Number(e.target.value)))} />
              </div>
            </Lane>
            <Lane dot="marker" title="Limite contratado" value={`${formatKw(draft.limit)}${draft.limitDefault ? ' (padrão)' : ''}`} help="Demanda da instalação inteira, loja incluída (a da conta de luz).">
              <div className="limits-track">
                <input type="range" className="limits-range solo contracted" aria-label="Limite contratado" data-testid="site-limit" min={0} max={draft.scale} step={step} value={draft.limit} onChange={(e) => apply(moveLimit(draft, Number(e.target.value)))} />
              </div>
            </Lane>
            <Lane dot="cars" title="Máximo dos carregadores" value={capText(draft)} help="Soma máxima dos carregadores. No fim da faixa: sem teto próprio.">
              <div className="limits-track">
                <div className="cap-lane" style={{ '--f-left': draft.peak / draft.scale, '--f-width': left / draft.scale } as CSSProperties}>
                  <input type="range" className="limits-range solo chargers" aria-label="Máximo dos carregadores" data-testid="chargers-cap" min={0} max={Math.max(left, 0.1)} step={step} value={Math.min(budget(draft), left)} onChange={(e) => apply(moveCap(draft, Number(e.target.value)))} />
                </div>
              </div>
            </Lane>
            {hint ? (
              <p className="amber" style={{ margin: 0, fontSize: 12.5, fontWeight: 600 }} data-testid="limits-hint">
                {hint}
              </p>
            ) : null}

            {typed ? (
              <div className="limits-typed" data-testid="limits-typed">
                {(
                  [
                    ['limit', 'Limite contratado'],
                    ['min', 'Loja · mínimo estimado'],
                    ['peak', 'Loja · pico estimado'],
                    ['cap', 'Máximo dos carregadores (vazio = sem teto)'],
                  ] as const
                ).map(([key, label]) => (
                  <label key={key} className="field">
                    <span>{label}</span>
                    <div className="input-affix">
                      <input className="input" inputMode="decimal" value={typed[key]} onChange={(e) => setTyped({ ...typed, [key]: e.target.value })} />
                      <span className="affix">kW</span>
                    </div>
                  </label>
                ))}
                {typedError ? <p className="red" style={{ margin: 0, fontSize: 12.5 }}>{typedError}</p> : null}
                <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                  <button type="button" className="btn btn-ghost" onClick={() => setTyped(null)}>
                    Cancelar
                  </button>
                  <button type="button" className="btn btn-primary" onClick={applyTyped}>
                    Aplicar
                  </button>
                </div>
              </div>
            ) : (
              <button type="button" className="btn btn-ghost" style={{ alignSelf: 'flex-start' }} onClick={openTyped}>
                Digitar valores
              </button>
            )}

            <FieldGroup label="Avisar quando os limites reduzirem uma recarga">
              <div className="segmented" style={{ maxWidth: 340 }}>
                {([true, false] as const).map((flag) => (
                  <button key={String(flag)} type="button" aria-pressed={draft.notify === flag} onClick={() => setEdited({ ...draft, notify: flag })} style={{ flex: 1 }}>
                    {flag ? 'Ligado' : 'Desligado'}
                  </button>
                ))}
              </div>
            </FieldGroup>

            {saveError ? <ErrorBanner error={saveError} title="Limites não salvos" /> : null}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button type="button" className="btn btn-ghost" disabled={saving !== null} onClick={() => { setEdited(restoreDefaults(draft)); setHint(null) }}>
                Restaurar padrão
              </button>
              <button type="button" className="btn btn-ghost" disabled={!dirty || saving !== null} onClick={() => { setEdited(null); setHint(null); setSaveError(null) }}>
                Descartar
              </button>
              <button type="submit" className="btn btn-primary" disabled={!dirty || saving !== null}>
                {saving === 'site' ? 'Salvando…' : 'Salvar limites'}
              </button>
            </div>
          </form>

          {points.length ? (
            <div>
              <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
                Por carregador
              </div>
              {points.map((connector) => {
                const line = connectorLine(connectorPower(connector, view))
                const session = view.points.find((p) => p.connector_id === connector.id)?.session
                return (
                  <div key={connector.id} className="list-row" data-testid="connector-power" style={{ padding: '10px 0' }}>
                    <span className="strong num" style={{ width: 92, flex: 'none' }}>
                      {connector.public_code}
                    </span>
                    <div className="grow">
                      <div className="tabular" style={{ fontSize: 13.5 }}>
                        {line}
                      </div>
                      <div className="dim" style={{ fontSize: 12 }}>
                        {connector.connector_type}
                        {session?.reason_short ? ` · ${session.reason_short}` : ''}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : null}
          {error ? <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>Última atualização falhou: {error.message}</p> : null}
        </div>
      ) : null}
    </Card>
  )
}
