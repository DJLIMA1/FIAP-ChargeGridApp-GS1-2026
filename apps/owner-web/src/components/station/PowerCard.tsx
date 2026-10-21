import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { StationPower } from '../../api/operations'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import {
  BUILDING_PROFILES,
  BUILDING_SIZES,
  connectorLine,
  connectorPower,
  defaultSiteLimitKw,
  formatKw,
  POWER_POLL_MS,
  powerSummary,
  REBALANCE_HELP,
  siteChanges,
  siteDraft,
  type BuildingProfile,
  type BuildingSize,
  type PowerSiteBody,
  type SiteDraft,
} from '../../lib/power'
import { useToast } from '../Toast'
import { Badge, Card, ErrorBanner, Field, FieldGroup, Skeleton } from '../ui'

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
        {label} {badge ? <Badge tone="amber">{badge}</Badge> : null}
      </span>
      <span className="value tabular">{value}</span>
      <span className="dim" style={{ fontSize: 12.5 }}>
        {detail}
      </span>
    </div>
  )
}

/**
 * Potência do posto (mesmo conteúdo da tela Potência do app): disponível para os carregadores, limite
 * contratado (o do dono ou o padrão do tipo/porte), loja agora (SIMULADO), carros agora, rebalanceamento
 * (ligado por padrão), tipo e porte do estabelecimento e a potência configurada × efetiva por conector.
 */
export function PowerCard({ station }: { station: Station }) {
  const { ep } = useAuth()
  const toast = useToast()
  const { view, setView, error, unsupported } = usePowerView(station.id)
  const [draft, setDraft] = useState<SiteDraft | null>(null)
  const [saving, setSaving] = useState<null | 'site' | 'toggle'>(null)
  const [saveError, setSaveError] = useState<string | null>(null)

  // O formulário começa com o que o dono informou (vazio = padrão) e não acompanha a atualização periódica.
  const saved = view ? siteDraft(view) : null
  const current = draft ?? saved
  if (unsupported) return null

  const changes = view && current ? siteChanges(view, current) : { body: {} as PowerSiteBody }
  const dirty = Object.keys(changes.body).length > 0
  const limitTouched = Boolean(view && current && saved && current.limit.trim() !== saved.limit)
  const previewDefault = current ? defaultSiteLimitKw(current.profile, current.size) : null

  const put = async (body: PowerSiteBody & { rebalance_enabled?: boolean }, kind: 'site' | 'toggle') => {
    setSaving(kind)
    setSaveError(null)
    try {
      const next = await ep.putPowerSite(station.id, body)
      setView(next)
      if (kind === 'site') setDraft(null)
      toast(kind === 'toggle' ? (next.rebalance_enabled ? 'Rebalanceamento ligado' : 'Rebalanceamento desligado') : 'Limite contratado salvo')
    } catch (err) {
      setSaveError(errorText(err))
    } finally {
      setSaving(null)
    }
  }
  const submit = (event: FormEvent) => {
    event.preventDefault()
    if (!dirty || changes.error || saving) return
    void put(changes.body, 'site')
  }
  const edit = (patch: Partial<SiteDraft>) => current && setDraft({ ...current, ...patch })

  const summary = view ? powerSummary(view) : null
  const points = station.connectors.filter((c) => !c.retired)

  return (
    <Card title="Potência" sub={`${REBALANCE_HELP} Atualiza a cada ${POWER_POLL_MS / 1000} s.`} id="power">
      {error && !view ? <ErrorBanner error={error} /> : null}
      {!view && !error ? <Skeleton height={220} /> : null}
      {view && summary && current ? (
        <div className="stack" style={{ gap: 18 }}>
          <div className="power-hero" data-testid="power-available">
            <span className="label">Disponível para os carregadores</span>
            <span className="value tabular">{summary.available}</span>
          </div>
          <div className="power-stats">
            <Stat label="Limite contratado" value={`${summary.limit}${view.site_limit_default ? ' (padrão)' : ''}`} detail={summary.limitDetail} />
            <Stat label="Loja agora" badge="SIMULADO" value={summary.load} detail={summary.loadDetail} />
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
              {view.rebalance_enabled ? 'Ligado: ajusta os carregadores a cada sincronização.' : 'Desligado: vale a potência definida no início de cada recarga.'}
            </div>
          </FieldGroup>

          <form className="stack" onSubmit={submit} noValidate>
            <div className="form-grid">
              <Field label="Limite contratado" hint="instalação inteira, loja incluída · vazio = padrão" error={limitTouched ? changes.error : null}>
                <div className="input-affix">
                  <input
                    className="input"
                    inputMode="decimal"
                    data-testid="site-limit"
                    placeholder={`Padrão: ${formatKw(previewDefault)}`}
                    value={current.limit}
                    onChange={(e) => edit({ limit: e.target.value })}
                    aria-invalid={Boolean(limitTouched && changes.error)}
                  />
                  <span className="affix">kW</span>
                </div>
              </Field>
              <div className="form-grid" style={{ gap: 12 }}>
                <Field label="Tipo de estabelecimento">
                  <select className="select" data-testid="building-profile" value={current.profile} onChange={(e) => edit({ profile: e.target.value as BuildingProfile })}>
                    {BUILDING_PROFILES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Porte">
                  <select className="select" data-testid="building-size" value={current.size} onChange={(e) => edit({ size: e.target.value as BuildingSize })}>
                    {BUILDING_SIZES.map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            </div>
            <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
              Sem medidor: o consumo da loja é simulado pelo tipo e porte do estabelecimento. Sem limite informado, vale o padrão{' '}
              {formatKw(previewDefault)} (o maior entre 75 kW e o pico simulado × 1,3).
            </p>
            {saveError ? <ErrorBanner error={saveError} title="Potência não salva" /> : null}
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
              <button type="button" className="btn btn-ghost" disabled={!dirty || saving !== null} onClick={() => { setDraft(null); setSaveError(null) }}>
                Descartar
              </button>
              <button type="submit" className="btn btn-primary" disabled={!dirty || Boolean(changes.error) || saving !== null}>
                {saving === 'site' ? 'Salvando…' : 'Salvar'}
              </button>
            </div>
          </form>

          {points.length ? (
            <div>
              <div className="muted" style={{ fontSize: 13, marginBottom: 6 }}>
                Por conector
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
