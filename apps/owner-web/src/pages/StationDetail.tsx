import { useEffect, useMemo, useState, type FormEvent } from 'react'
import { Link, useLocation, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import type { StationPatch } from '../api/endpoints'
import type { Amenity, Connector, Station } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { AddressAutocomplete } from '../components/AddressAutocomplete'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { ChargerCard } from '../components/station/ChargerCard'
import { EconomicsCard } from '../components/station/EconomicsCard'
import { KioskField } from '../components/station/KioskField'
import { OverstayCard } from '../components/station/OverstayCard'
import { PowerCard } from '../components/station/PowerCard'
import { ScreenStatus } from '../components/station/ScreenStatus'
import { Badge, Banner, Card, ConfirmDialog, EmptyState, ErrorBanner, Field, PageHead, Skeleton } from '../components/ui'
import {
  REMOVE_CHARGER_HINT,
  STATION_SCREEN_META,
  addChargerErrorText,
  addChargerTarget,
  cgAddrHint,
  chargerName,
  nextFreeChargerAddress,
  offlineChargers,
  removableCharger,
  removeChargerErrorText,
  removeChargerQuestion,
  stationChargerSummary,
  stationScreenState,
} from '../lib/charger'
import { useFilters } from '../lib/filters'
import { formatRelative } from '../lib/format'
import { AMENITY_KINDS, AMENITY_LABELS } from '../lib/labels'
import { useStationView } from '../lib/useStationView'
import { useLiveDraft } from '../lib/useLiveDraft'
import { validateText } from '../lib/validate'

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
  const initial = useMemo(() => ({ name: station.name, address: station.address, active: station.active }),
    [station.name, station.address, station.active])
  const [draft, setDraft, formEvents] = useLiveDraft(initial)
  const { name, address, active } = draft
  const setName = (value: string) => setDraft((previous) => ({ ...previous, name: value }))
  const setAddress = (value: string) => setDraft((previous) => ({ ...previous, address: value }))
  const setActive = (value: boolean) => setDraft((previous) => ({ ...previous, active: value }))
  const [coords, setCoords] = useState<{ latitude: number; longitude: number } | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [touched, setTouched] = useState(false)

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
    <Card title="Dados da estação" sub="Dados visíveis para motoristas; a central gerencia os carregadores." id="station-data">
      <form onSubmit={save} className="stack" noValidate {...formEvents}>
        <ScreenStatus station={station} />
        {stationScreenState(station) === 'offline' ? <StationHealth station={station} /> : null}
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

/* -------------------------------------------------------------- carregadores */

/** Banner do estado da estação × carregadores: um carregador offline não derruba a estação. */
export function StationHealth({ station }: { station: Station }) {
  const state = stationScreenState(station)
  if (state === 'offline') {
    return (
      <Banner tone="error" icon="wifiOff" title="Estação offline">
        A central está sem contato: todos os carregadores ficam indisponíveis até ela voltar.
      </Banner>
    )
  }
  const offline = offlineChargers(station)
  if (state !== 'online' || !offline.length) return null
  const codes = offline.map((c) => c.public_code).join(', ')
  return (
    <Banner tone="info" icon="alert" title={offline.length === 1 ? `Carregador ${codes} offline` : `Carregadores ${codes} offline`}>
      {offline.length === 1 ? 'Só esse ponto fica indisponível' : 'Só esses pontos ficam indisponíveis'}; os motoristas são orientados a usar outro ponto da estação.
    </Banner>
  )
}

export function ChargersCard({
  station,
  onSaved,
  onAdded,
  onRemoved,
  suggestedAddress = null,
}: {
  station: Station
  onSaved(next: Connector): void
  onAdded(next: Connector): void
  onRemoved?(removed: Connector): void
  suggestedAddress?: number | null
}) {
  const { ep } = useAuth()
  const toast = useToast()
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState<string | null>(null)
  const [added, setAdded] = useState<Connector | null>(null)
  // Carregador a remover (diálogo aberto), o DELETE em andamento e o erro dele (mostrado no diálogo).
  const [removing, setRemoving] = useState<Connector | null>(null)
  const [removeBusy, setRemoveBusy] = useState(false)
  const [removeError, setRemoveError] = useState<string | null>(null)
  const points = station.connectors
  const target = addChargerTarget(station)

  const add = async () => {
    if (!target || adding) return
    setAdding(true)
    setAddError(null)
    try {
      const next = await ep.addCharger(target.id)
      setAdded(next)
      onAdded(next)
      toast(`Carregador ${next.public_code} adicionado`)
    } catch (err) {
      setAddError(addChargerErrorText(err))
    } finally {
      setAdding(false)
    }
  }

  const askRemove = (connector: Connector) => {
    setRemoveError(null)
    setRemoving(connector)
  }
  const remove = async () => {
    if (!removing || removeBusy) return
    setRemoveBusy(true)
    setRemoveError(null)
    try {
      await ep.removeCharger(removing.id)
      if (added?.id === removing.id) setAdded(null)
      onRemoved?.(removing)
      toast(`${chargerName(removing)} removido. O endereço ficou livre para outro carregador.`)
      setRemoving(null)
    } catch (err) {
      setRemoveError(removeChargerErrorText(err))
    } finally {
      setRemoveBusy(false)
    }
  }

  return (
    <Card
      title="Carregadores"
      sub="Cada carregador é um GoodWe HCA G2 (simulado) comandado pela central da estação"
      id="connectors"
      action={
        target ? (
          <button type="button" className="btn btn-secondary" disabled={adding} onClick={() => void add()} data-testid="add-charger">
            <Icon name="plus" size={16} /> {adding ? 'Adicionando…' : 'Adicionar carregador'}
          </button>
        ) : null
      }
    >
      <div className="stack" style={{ gap: 12 }}>
        {stationScreenState(station) !== 'offline' ? <StationHealth station={station} /> : null}
        {addError ? <ErrorBanner error={addError} title="Carregador não adicionado" /> : null}
        {added && added.charger_address !== null && added.charger_address !== undefined ? (
          <Banner tone="ok" icon="check" title={`Carregador ${added.public_code} adicionado no endereço ${added.charger_address}`}>
            <span data-testid="added-charger">
              Inativo por enquanto. {cgAddrHint(added.charger_address)}, mesma rede Wi-Fi da central; publique quando ele ficar online.
            </span>
          </Banner>
        ) : null}
        {points.length ? (
          points.map((connector) => (
            <ChargerCard
              key={connector.id}
              connector={connector}
              onSaved={onSaved}
              suggestedAddress={suggestedAddress}
              onRemove={onRemoved && removableCharger(connector) ? () => askRemove(connector) : undefined}
            />
          ))
        ) : (
          <EmptyState icon="plug" title="Nenhum carregador">
            A estação aparece aqui depois de vincular a central pelo QR de propriedade no app ChargeGrid.
          </EmptyState>
        )}
      </div>
      {removing ? (
        <ConfirmDialog
          title={removeChargerQuestion(removing)}
          confirmLabel="Remover"
          busyLabel="Removendo…"
          danger
          busy={removeBusy}
          error={removeError}
          errorTitle="Carregador não removido"
          onConfirm={() => void remove()}
          onCancel={() => setRemoving(null)}
        >
          {REMOVE_CHARGER_HINT}
        </ConfirmDialog>
      ) : null}
    </Card>
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
  const [rows, setRows, formEvents] = useLiveDraft(initial)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      <div className="stack" style={{ gap: 10 }} {...formEvents}>
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
  const { replaceStation } = useFilters()
  const { station, error, reload, update: acceptStation, lastRefresh } = useStationView(id)
  // Atalhos como /estacoes/:id#economics (do Resultado) rolam até o cartão.
  const { hash } = useLocation()
  const loaded = Boolean(station)
  useEffect(() => {
    if (!loaded || !hash) return
    const timer = setTimeout(() => document.getElementById(`${hash.slice(1)}-t`)?.scrollIntoView({ behavior: 'smooth', block: 'start' }), 80)
    return () => clearTimeout(timer)
  }, [loaded, hash])

  const update = (next: Station) => {
    acceptStation(next)
    replaceStation(next)
  }
  const updateConnector = (next: Connector) => {
    acceptStation((previous) => ({ ...previous,
      connectors: previous.connectors.map((c) => c.id === next.id ? { ...c, ...next } : c),
    }))
  }
  const addConnector = (next: Connector) => {
    acceptStation((previous) => ({ ...previous,
      connectors: [...previous.connectors.filter((c) => c.id !== next.id), next],
    }))
  }

  // Removido: some da lista na hora; o GET em seguida traz as centrais/endereços como a API ficou.
  const removeConnector = (removed: Connector) => {
    acceptStation((previous) => ({ ...previous,
      connectors: previous.connectors.filter((c) => c.id !== removed.id),
      screens: previous.screens?.map((s) => ({ ...s, charger_ids: s.charger_ids.filter((id) => id !== removed.id) })),
    }))
    reload()
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
  // Só para um ponto legado sem endereço: o próximo livre do posto (como a API faz na criação).
  const freeAddress = nextFreeChargerAddress(points.map((c) => c.charger_address))
  const screenState = stationScreenState(station)
  const screenMeta = STATION_SCREEN_META[screenState]
  return (
    <>
      <PageHead
        title={station.name}
        back={back}
        sub={
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <Badge tone={station.active ? 'green' : 'gray'}>{station.active ? 'Ativa' : 'Inativa'}</Badge>
            <Badge tone={screenMeta.tone}>{screenMeta.label}</Badge>
            {stationChargerSummary(station)} · atualizado {formatRelative(lastRefresh)}
          </span>
        }
        actions={
          <button type="button" className="btn btn-secondary" onClick={reload}>
            <Icon name="refresh" size={16} /> Recarregar
          </button>
        }
      />
      <div className="stack">
        {error ? <ErrorBanner error={error} title="Falha ao atualizar carregadores" onRetry={reload} /> : null}
        <StationForm station={station} onSaved={update} />
        <ChargersCard station={station} onSaved={updateConnector} onAdded={addConnector} onRemoved={removeConnector} suggestedAddress={freeAddress} />
        <PowerCard station={station} />
        <EconomicsCard stationId={station.id} />
        <OverstayCard station={station} />
        <AmenitiesEditor station={station} onSaved={update} />
      </div>
    </>
  )
}
