import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { StationPatch } from '../api/endpoints'
import type { Amenity, Connector, Station } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { AddressAutocomplete } from '../components/AddressAutocomplete'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { EconomicsCard } from '../components/station/EconomicsCard'
import { KioskField } from '../components/station/KioskField'
import { OverstayCard } from '../components/station/OverstayCard'
import { PowerCard } from '../components/station/PowerCard'
import { Badge, Card, EmptyState, ErrorBanner, Field, PageHead, Skeleton, Switch } from '../components/ui'
import { useFilters } from '../lib/filters'
import { formatPower, formatRelative, formatTariff } from '../lib/format'
import { AMENITY_KINDS, AMENITY_LABELS, availabilityMeta } from '../lib/labels'
import { useApi } from '../lib/useApi'
import { toInputDecimal, validateDuration, validatePower, validatePrice, validateText } from '../lib/validate'

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.fields.length) return `${error.message}: ${error.fields.map((f) => f.field).join(', ')}`
    return error.message
  }
  return 'Não foi possível salvar. Tente novamente.'
}

/* ------------------------------------------------------------ dados da estação */
export function StationForm({ station, onSaved }: { station: Station; onSaved(next: Station): void }) {
  const { ep } = useAuth()
  const toast = useToast()
  const [name, setName] = useState(station.name)
  const [address, setAddress] = useState(station.address)
  const [active, setActive] = useState(station.active)
  // Coordenadas da sugestão escolhida: o mapa do app passa a apontar para o novo endereço.
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)

  // Só os campos do formulário: ligar o totem (salvo na hora) não descarta o que está sendo digitado.
  useEffect(() => {
    setName(station.name)
    setAddress(station.address)
    setActive(station.active)
    setCoords(null)
  }, [station.name, station.address, station.active])

  const nameError = validateText(name, 'o nome da estação', 100)
  const addressError = validateText(address, 'o endereço', 300)
  const changes = useMemo(() => {
    const body: StationPatch = {}
    if (name.trim() !== station.name) body.name = name.trim()
    if (address.trim() !== station.address) {
      body.address = address.trim()
      if (coords) Object.assign(body, coords)
    }
    if (active !== station.active) body.active = active
    return body
  }, [name, address, active, coords, station])
  const dirty = Object.keys(changes).length > 0

  const save = async (event: FormEvent) => {
    event.preventDefault()
    setTouched(true)
    if (nameError || addressError || !dirty || saving) return
    if (changes.active === false && !window.confirm('Desativar a estação a esconde dos motoristas e bloqueia novas recargas. Continuar?')) return
    setSaving(true)
    setError(null)
    try {
      const next = await ep.patchStation(station.id, changes)
      onSaved(next)
      toast('Dados da estação salvos')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card title="Dados da estação" sub="Visíveis para os motoristas no app; o totem liga e desliga na hora" id="station-data">
      <form onSubmit={save} className="stack" noValidate>
        {error ? <ErrorBanner error={error} title="Alterações não salvas" /> : null}
        <div className="form-grid">
          <Field label="Nome da estação" error={touched || name !== station.name ? nameError : null}>
            <input className="input input-big" value={name} maxLength={100} onChange={(e) => setName(e.target.value)} aria-invalid={Boolean(nameError)} />
          </Field>
          <Field label="Status">
            <div className="segmented" role="group" aria-label="Status da estação" style={{ height: 52 }}>
              <button type="button" aria-pressed={active} onClick={() => setActive(true)} style={{ flex: 1, height: 50, minWidth: 110 }}>
                Ativa
              </button>
              <button type="button" aria-pressed={!active} onClick={() => setActive(false)} style={{ flex: 1, height: 50, minWidth: 110 }}>
                Inativa
              </button>
            </div>
          </Field>
          <div className="full">
            <Field label="Endereço" error={touched || address !== station.address ? addressError : null}>
              <AddressAutocomplete
                value={address}
                saved={station.address}
                invalid={Boolean(addressError)}
                onChange={(next) => {
                  setAddress(next)
                  setCoords(null)
                }}
                onPick={(item) =>
                  setCoords(item.latitude !== null && item.longitude !== null ? { latitude: item.latitude, longitude: item.longitude } : null)
                }
              />
            </Field>
          </div>
          <KioskField station={station} onSaved={onSaved} />
        </div>
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
          <button
            type="button"
            className="btn btn-ghost"
            disabled={!dirty || saving}
            onClick={() => {
              setName(station.name)
              setAddress(station.address)
              setActive(station.active)
              setCoords(null)
              setError(null)
            }}
          >
            Descartar
          </button>
          <button type="submit" className="btn btn-primary" disabled={!dirty || saving || Boolean(nameError || addressError)}>
            {saving ? 'Salvando…' : 'Salvar alterações'}
          </button>
        </div>
      </form>
    </Card>
  )
}

/* ------------------------------------------------------------------ conector */
function ConnectorEditor({ connector, onSaved }: { connector: Connector; onSaved(next: Connector): void }) {
  const { ep } = useAuth()
  const toast = useToast()
  const initial = useMemo(
    () => ({
      price: toInputDecimal(connector.price_per_kwh, 2),
      power: toInputDecimal(connector.power_kw),
      duration: String(connector.max_duration_minutes),
      active: connector.active,
    }),
    [connector],
  )
  const [draft, setDraft] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setDraft(initial), [initial])

  const price = validatePrice(draft.price)
  const power = validatePower(draft.power)
  const duration = validateDuration(draft.duration)
  const invalid = Boolean(price.error || power.error || duration.error)
  const body = useMemo(() => {
    const changes: Record<string, string | number | boolean> = {}
    if (price.value !== undefined && Number(price.value) !== Number(connector.price_per_kwh)) changes.price_per_kwh = price.value
    if (power.value !== undefined && Number(power.value) !== Number(connector.power_kw)) changes.power_kw = power.value
    if (duration.value !== undefined && duration.value !== connector.max_duration_minutes) changes.max_duration_minutes = duration.value
    if (draft.active !== connector.active) changes.active = draft.active
    return changes
  }, [price.value, power.value, duration.value, draft.active, connector])
  const dirty = Object.keys(body).length > 0
  const status = availabilityMeta(connector)
  const busy = ['charging', 'reserved', 'reconciling'].includes(connector.availability_status ?? '')

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (invalid || !dirty || saving) return
    setSaving(true)
    setError(null)
    try {
      const next = await ep.patchConnector(connector.id, body)
      onSaved(next)
      toast(`Conector ${connector.public_code} atualizado`)
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <form className="connector-card" onSubmit={save} noValidate>
      <div className="connector-head" style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <span className="tile" style={{ width: 40, height: 40, background: '#333' }}>
          <Icon name="zap" size={19} />
        </span>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span className="num" style={{ fontSize: 22, fontWeight: 600 }}>
              {connector.public_code}
            </span>
            {status ? <Badge tone={status.tone}>{status.label}</Badge> : null}
            {connector.retired ? <Badge tone="gray">Em restauração</Badge> : null}
          </div>
          <div className="muted" style={{ fontSize: 12.5 }}>
            {connector.connector_type} · {formatPower(connector.power_kw)} · {formatTariff(connector.price_per_kwh)}
          </div>
        </div>
        <Switch checked={draft.active} onChange={(value) => setDraft({ ...draft, active: value })} label={draft.active ? 'Publicado' : 'Desativado'} disabled={saving} />
      </div>
      <div className="connector-fields">
        <Field label="Tarifa" hint="R$/kWh" error={price.error && draft.price !== initial.price ? price.error : null}>
          <div className="input-affix">
            <span className="lead">R$</span>
            <input className="input" inputMode="decimal" value={draft.price} onChange={(e) => setDraft({ ...draft, price: e.target.value })} aria-invalid={Boolean(price.error)} />
            <span className="affix">/kWh</span>
          </div>
        </Field>
        <Field label="Potência" error={power.error && draft.power !== initial.power ? power.error : null}>
          <div className="input-affix">
            <input className="input" inputMode="decimal" value={draft.power} onChange={(e) => setDraft({ ...draft, power: e.target.value })} aria-invalid={Boolean(power.error)} />
            <span className="affix">kW</span>
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
          <ErrorBanner error={error} title="Conector não atualizado" />
        </div>
      ) : null}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 14, flexWrap: 'wrap' }}>
        <span className="dim" style={{ fontSize: 12.5, flex: 1, minWidth: 200 }}>
          {busy ? 'Há recarga ou reserva em andamento: a API só aceita alterações quando o ponto estiver livre.' : connector.online ? 'Dispositivo online' : 'Dispositivo offline'}
        </span>
        <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => { setDraft(initial); setError(null) }}>
          Descartar
        </button>
        <button type="submit" className="btn btn-primary" disabled={!dirty || invalid || saving}>
          {saving ? 'Salvando…' : 'Salvar conector'}
        </button>
      </div>
    </form>
  )
}

/* --------------------------------------------------------------- comodidades */
interface AmenityDraft {
  kind: Amenity['kind']
  name: string
  distance: string
}

function AmenitiesEditor({ station, onSaved }: { station: Station; onSaved(next: Station): void }) {
  const { ep } = useAuth()
  const toast = useToast()
  const initial = useMemo<AmenityDraft[]>(
    () => (station.amenities ?? []).map((a) => ({ kind: a.kind, name: a.name ?? '', distance: a.distance_m === null || a.distance_m === undefined ? '' : String(a.distance_m) })),
    [station],
  )
  const [rows, setRows] = useState(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setRows(initial), [initial])

  const problems = rows.map((row) => {
    if (row.name.length > 80) return 'Nome com até 80 caracteres'
    if (row.distance && (!/^\d+$/.test(row.distance) || Number(row.distance) > 5000)) return 'Distância de 0 a 5.000 m'
    return null
  })
  const dirty = JSON.stringify(rows) !== JSON.stringify(initial)
  const invalid = problems.some(Boolean)

  const save = async () => {
    if (!dirty || invalid || saving) return
    setSaving(true)
    setError(null)
    try {
      const amenities = rows.map((row) => ({ kind: row.kind, name: row.name.trim(), distance_m: row.distance ? Number(row.distance) : null }))
      const next = await ep.patchStation(station.id, { amenities })
      onSaved(next)
      toast('Comodidades salvas')
    } catch (err) {
      setError(errorText(err))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="Comodidades"
      sub="Ajudam o motorista a aproveitar o tempo de recarga (até 12)"
      id="amenities"
      action={
        <button type="button" className="btn btn-secondary" disabled={rows.length >= 12} onClick={() => setRows([...rows, { kind: 'cafe', name: '', distance: '' }])}>
          <Icon name="plus" size={16} /> Adicionar
        </button>
      }
    >
      <div className="stack" style={{ gap: 10 }}>
        {!rows.length ? (
          <p className="muted" style={{ margin: 0 }}>
            Nenhuma comodidade cadastrada.
          </p>
        ) : null}
        {rows.map((row, index) => (
          <div key={index}>
            <div className="amenity-row">
              <select className="select" aria-label="Tipo" value={row.kind} onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, kind: e.target.value as Amenity['kind'] } : r)))}>
                {AMENITY_KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {AMENITY_LABELS[kind]}
                  </option>
                ))}
              </select>
              <input className="input full-sm" placeholder="Nome (opcional)" aria-label="Nome" maxLength={80} value={row.name} onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, name: e.target.value } : r)))} />
              <div className="input-affix">
                <input className="input" placeholder="Distância" aria-label="Distância em metros" inputMode="numeric" value={row.distance} onChange={(e) => setRows(rows.map((r, i) => (i === index ? { ...r, distance: e.target.value } : r)))} aria-invalid={Boolean(problems[index])} />
                <span className="affix">m</span>
              </div>
              <button type="button" className="icon-btn" aria-label="Remover comodidade" onClick={() => setRows(rows.filter((_, i) => i !== index))}>
                <Icon name="trash" size={16} />
              </button>
            </div>
            {problems[index] ? <div className="red" style={{ fontSize: 12.5, marginTop: 4 }}>{problems[index]}</div> : null}
          </div>
        ))}
        {error ? <ErrorBanner error={error} title="Comodidades não salvas" /> : null}
        <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 10 }}>
          <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => setRows(initial)}>
            Descartar
          </button>
          <button type="button" className="btn btn-primary" disabled={!dirty || invalid || saving} onClick={save}>
            {saving ? 'Salvando…' : 'Salvar comodidades'}
          </button>
        </div>
      </div>
    </Card>
  )
}

/* ---------------------------------------------------------------------- page */
export default function StationDetail() {
  const { id = '' } = useParams()
  const { ep } = useAuth()
  const { replaceStation } = useFilters()
  const { data, error, reload } = useApi((signal) => ep.station(id, signal), `station|${id}`)
  const [station, setStation] = useState<Station | null>(null)
  useEffect(() => {
    if (data) setStation(data)
  }, [data])
  // Atalhos como /estacoes/:id#economics (do Resultado) rolam até o cartão.
  const { hash } = useLocation()
  const loaded = Boolean(station)
  useEffect(() => {
    if (!loaded || !hash) return
    const timer = setTimeout(() => document.getElementById(`${hash.slice(1)}-t`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
    return () => clearTimeout(timer)
  }, [loaded, hash])

  const update = (next: Station) => {
    // A resposta do PATCH é a fonte da verdade (sem atualização otimista).
    setStation(next)
    replaceStation(next)
  }
  const updateConnector = (next: Connector) => {
    if (!station) return
    const merged = { ...station, connectors: station.connectors.map((c) => (c.id === next.id ? { ...c, ...next } : c)) }
    update(merged)
  }

  const back = (
    <Link to="/estacoes" className="back-link">
      <Icon name="chevronLeft" size={18} /> Estações
    </Link>
  )

  if (error && !station) {
    return (
      <>
        <PageHead title="Estação" back={back} />
        {error.status === 404 ? (
          <div className="card">
            <EmptyState icon="station" title="Estação não encontrada">
              Ela pode ter sido removida ou pertencer a outra conta.
            </EmptyState>
          </div>
        ) : (
          <ErrorBanner error={error} onRetry={reload} />
        )}
      </>
    )
  }
  if (!station) {
    return (
      <>
        <PageHead title="Carregando estação…" back={back} />
        <div className="stack">
          <Skeleton height={260} radius={16} />
          <Skeleton height={200} radius={16} />
        </div>
      </>
    )
  }

  const points = station.connectors
  const online = points.filter((c) => c.online).length
  return (
    <>
      <PageHead
        title={station.name}
        back={back}
        sub={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Badge tone={station.active ? 'green' : 'gray'}>{station.active ? 'Ativa' : 'Inativa'}</Badge>
            {points.length} conector(es) · {online} online · atualizado {formatRelative(new Date())}
          </span>
        }
        actions={
          <button type="button" className="btn btn-secondary" onClick={reload}>
            <Icon name="refresh" size={16} /> Recarregar
          </button>
        }
      />
      <div className="stack">
        <StationForm station={station} onSaved={update} />
        <Card title="Conectores e tarifas" sub="Tarifa base, potência e limite de duração por conector" id="connectors">
          {points.length ? (
            <div className="stack" style={{ gap: 12 }}>
              {points.map((connector) => (
                <ConnectorEditor key={connector.id} connector={connector} onSaved={updateConnector} />
              ))}
            </div>
          ) : (
            <EmptyState icon="plug" title="Nenhum conector">
              Novos pontos são adicionados escaneando o QR de propriedade do equipamento no app ChargeGrid.
            </EmptyState>
          )}
        </Card>
        <PowerCard station={station} />
        <EconomicsCard stationId={station.id} />
        <OverstayCard station={station} />
        <AmenitiesEditor station={station} onSaved={update} />
      </div>
    </>
  )
}
