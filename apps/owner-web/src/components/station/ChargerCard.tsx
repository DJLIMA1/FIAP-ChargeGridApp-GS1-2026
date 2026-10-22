import { useMemo, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { ConnectorPatch } from '../../api/endpoints'
import type { Connector } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { CHARGER_STATE_META, CHARGER_STATUS_LABEL, CONNECTOR_TYPES, chargerState } from '../../lib/charger'
import { formatPower, formatTariff, toNumber } from '../../lib/format'
import { availabilityMeta } from '../../lib/labels'
import { toInputDecimal, validateDuration, validatePower, validatePowerLimit, validatePrice } from '../../lib/validate'
import { Icon } from '../Icon'
import { useToast } from '../Toast'
import { Badge, ErrorBanner, Field, Switch } from '../ui'
import { ChargerField, ChargerLinkLine } from './ChargerField'
import { useLiveDraft } from '../../lib/useLiveDraft'

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fields.length) return `${error.message}: ${error.fields.map((f) => f.field).join(', ')}`
    return error.message
  }
  return 'Não foi possível salvar. Tente novamente.'
}

/**
 * Cartão do carregador (um ponto da estação = um GoodWe HCA G2 simulado): cabeçalho com o status do
 * carregador, endereço/tipo/potência/limite na primeira linha e tarifa/duração na segunda. O endereço salva na hora; o resto em "Salvar carregador".
 */
export function ChargerCard({
  connector,
  onSaved,
  suggestedAddress = null,
  onRemove,
}: {
  connector: Connector
  onSaved(next: Connector): void
  suggestedAddress?: number | null
  /** Só nos carregadores adicionais (`removableCharger`): abre a confirmação de "Remover carregador". */
  onRemove?(): void
}) {
  const { ep } = useAuth()
  const toast = useToast()
  const initial = useMemo(
    () => ({
      price: toInputDecimal(connector.price_per_kwh, 2),
      power: toInputDecimal(connector.power_kw),
      limit: toInputDecimal(connector.power_limit_kw),
      type: connector.connector_type,
      duration: String(connector.max_duration_minutes),
      active: connector.active,
    }),
    // Só os campos do formulário: salvar o endereço (na hora) não descarta o que está sendo digitado.
    [connector.price_per_kwh, connector.power_kw, connector.power_limit_kw, connector.connector_type, connector.max_duration_minutes, connector.active],
  )
  const [draft, setDraft, formEvents] = useLiveDraft(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const price = validatePrice(draft.price)
  const power = validatePower(draft.power)
  const limit = validatePowerLimit(draft.limit, power.value !== undefined ? Number(power.value) : toNumber(connector.power_kw))
  const duration = validateDuration(draft.duration)
  const type = draft.type.trim()
  const invalid = Boolean(price.error || power.error || limit.error || duration.error || !type)
  const body = useMemo(() => {
    const changes: ConnectorPatch = {}
    if (price.value !== undefined && Number(price.value) !== Number(connector.price_per_kwh)) changes.price_per_kwh = price.value
    if (power.value !== undefined && Number(power.value) !== Number(connector.power_kw)) changes.power_kw = power.value
    const savedLimit = toNumber(connector.power_limit_kw)
    if (limit.value !== undefined && (limit.value === null ? savedLimit !== null : Number(limit.value) !== savedLimit)) changes.power_limit_kw = limit.value
    if (type && type !== connector.connector_type) changes.connector_type = type
    if (duration.value !== undefined && duration.value !== connector.max_duration_minutes) changes.max_duration_minutes = duration.value
    if (draft.active !== connector.active) changes.active = draft.active
    return changes
  }, [price.value, power.value, limit.value, type, duration.value, draft.active, connector])
  const dirty = Object.keys(body).length > 0
  const busy = ['charging', 'reserved', 'reconciling'].includes(connector.availability_status ?? '')

  const state = chargerState(connector)
  const stateMeta = state ? CHARGER_STATE_META[state] : null
  const availability = availabilityMeta(connector)
  // "Offline" já está no selo do carregador e "Desativado" no interruptor: a disponibilidade só quando diz outra coisa.
  const showAvailability =
    availability && connector.availability_status !== 'disabled' && !(connector.availability_status === 'offline' && state && state !== 'online')
  const types = CONNECTOR_TYPES.includes(connector.connector_type as (typeof CONNECTOR_TYPES)[number]) ? CONNECTOR_TYPES : [connector.connector_type, ...CONNECTOR_TYPES]
  const address = connector.charger_address

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (invalid || !dirty || saving) return
    setSaving(true)
    setError(null)
    try {
      const next = await ep.patchConnector(connector.id, body)
      onSaved(next)
      toast(`Carregador ${connector.public_code} atualizado`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="connector-card" onSubmit={save} noValidate data-testid="charger-card" {...formEvents}>
      <div className="connector-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className={`tile ${stateMeta?.tone === 'gray' ? '' : (stateMeta?.tone ?? '')}`} style={{ width: 40, height: 40 }}>
          <Icon name="zap" size={19} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>
              {connector.public_code}
            </span>
            {stateMeta ? <Badge tone={stateMeta.tone}>{stateMeta.label}</Badge> : null}
            {showAvailability ? <Badge tone={availability.tone}>{availability.label}</Badge> : null}
            {connector.retired ? <Badge tone="gray">Em restauração</Badge> : null}
          </div>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {address !== undefined && address !== null ? `Carregador ${address} · ` : ''}
            {CHARGER_STATUS_LABEL} · {connector.connector_type} · {formatPower(connector.power_kw)} · {formatTariff(connector.price_per_kwh)}
          </div>
        </div>
        <Switch checked={draft.active} onChange={(value) => setDraft({ ...draft, active: value })} label={draft.active ? 'Publicado' : 'Inativo'} disabled={saving} />
      </div>

      <div className="connector-fields fields-4">
        <ChargerField connector={connector} onSaved={onSaved} suggested={suggestedAddress} />
        <Field label="Tipo de conector">
          <select className="select" value={draft.type} onChange={(e) => setDraft({ ...draft, type: e.target.value })}>
            {types.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Potência nominal" error={power.error && draft.power !== initial.power ? power.error : null}>
          <div className="input-affix">
            <input className="input" inputMode="decimal" value={draft.power} onChange={(e) => setDraft({ ...draft, power: e.target.value })} aria-invalid={Boolean(power.error)} />
            <span className="affix">kW</span>
          </div>
        </Field>
        <Field label="Limite" hint="vazio = nominal" error={limit.error && draft.limit !== initial.limit ? limit.error : null}>
          <div className="input-affix">
            <input className="input" inputMode="decimal" placeholder="Nominal" value={draft.limit} onChange={(e) => setDraft({ ...draft, limit: e.target.value })} aria-invalid={Boolean(limit.error)} />
            <span className="affix">kW</span>
          </div>
        </Field>
      </div>
      <div style={{ marginTop: 8 }}>
        <ChargerLinkLine connector={connector} />
      </div>

      <div className="connector-fields" style={{ gridTemplateColumns: 'repeat(2, minmax(0, 1fr))' }}>
        <Field label="Tarifa" error={price.error && draft.price !== initial.price ? price.error : null}>
          <div className="input-affix">
            <span className="lead">R$</span>
            <input className="input" inputMode="decimal" value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} aria-invalid={Boolean(price.error)} />
            <span className="affix">/kWh</span>
          </div>
        </Field>
        <Field label="Duração máxima" error={duration.error && draft.duration !== initial.duration ? duration.error : null}>
          <div className="input-affix">
            <input className="input" inputMode="numeric" value={draft.duration} onChange={(e) => setDraft({ ...draft, duration: e.target.value })} aria-invalid={Boolean(duration.error)} />
            <span className="affix">min</span>
          </div>
        </Field>
      </div>

      {error ? (
        <div style={{ marginTop: 12 }}>
          <ErrorBanner error={error} title="Carregador não atualizado" />
        </div>
      ) : null}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
        {onRemove ? (
          <button type="button" className="btn btn-danger" disabled={saving} onClick={onRemove} data-testid="remove-charger">
            <Icon name="trash" size={16} /> Remover carregador
          </button>
        ) : null}
        <span className="dim" style={{ fontSize: 12.5, flex: 1, minWidth: 200 }}>
          {busy ? 'Recarga ou reserva em andamento: agora só o limite pode mudar.' : ''}
        </span>
        <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => { setDraft(initial); setError(null) }}>
          Descartar
        </button>
        <button type="submit" className="btn btn-primary" disabled={!dirty || invalid || saving}>
          {saving ? 'Salvando…' : 'Salvar carregador'}
        </button>
      </div>
    </form>
  )
}
