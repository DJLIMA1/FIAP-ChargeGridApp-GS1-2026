import { useCallback, useState, type FormEvent } from 'react'
import { ApiError } from '../api/client'
import type { Coupon } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { Icon } from '../components/Icon'
import { useToast } from '../components/Toast'
import { Badge, Card, Drawer, EmptyState, ErrorBanner, Field, PageHead, SkeletonRows, Switch } from '../components/ui'
import { useFilters } from '../lib/filters'
import { formatDate } from '../lib/format'
import { localDate, localMidnight } from '../lib/period'
import { useApi } from '../lib/useApi'
import { validateCouponCode, validatePercent, validateText } from '../lib/validate'

function couponState(coupon: Coupon, now = Date.now()): { label: string; tone: 'green' | 'gray' | 'amber' } {
  if (new Date(coupon.valid_until).getTime() <= now) return { label: 'Expirado', tone: 'amber' }
  return coupon.active ? { label: 'Ativo', tone: 'green' } : { label: 'Inativo', tone: 'gray' }
}

function CreateCoupon({ onClose, onCreated }: { onClose(): void; onCreated(coupon: Coupon): void }) {
  const { ep } = useAuth()
  const { stations } = useFilters()
  const [code, setCode] = useState('')
  const [description, setDescription] = useState('')
  const [discount, setDiscount] = useState('10')
  const [stationId, setStationId] = useState('')
  const today = localDate(new Date())
  const [validUntil, setValidUntil] = useState(() => localDate(Date.now() + 30 * 86_400_000))
  const [touched, setTouched] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const codeError = validateCouponCode(code)
  const descriptionError = description.length > 200 ? 'Use até 200 caracteres' : validateText(description, 'uma descrição', 200)
  const percent = validatePercent(discount)
  const dateError = !validUntil ? 'Informe a validade' : validUntil < today ? 'A validade deve estar no futuro' : null
  const invalid = Boolean(codeError || descriptionError || percent.error || dateError)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setTouched(true)
    if (invalid || saving) return
    setSaving(true)
    setError(null)
    try {
      // Válido até o fim do dia escolhido (23:59:59 em São Paulo).
      const end = new Date(localMidnight(validUntil, 1).getTime() - 1000)
      const coupon = await ep.createCoupon({
        code: code.trim().toUpperCase(),
        description: description.trim(),
        discount_percent: percent.value!,
        station_id: stationId || null,
        valid_until: end.toISOString(),
      })
      onCreated(coupon)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível criar o cupom.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Drawer
      title="Novo cupom"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            Cancelar
          </button>
          <button type="submit" form="coupon-form" className="btn btn-primary" disabled={saving || (touched && invalid)}>
            {saving ? 'Criando…' : 'Criar cupom'}
          </button>
        </>
      }
    >
      <form id="coupon-form" className="stack" onSubmit={submit} noValidate>
        {error ? <ErrorBanner error={error} title="Cupom não criado" /> : null}
        <Field label="Código" hint="o motorista digita no app" error={touched ? codeError : null}>
          <input className="input input-big" value={code} onChange={(e) => setCode(e.target.value.toUpperCase())} placeholder="EX.: BEMVINDO10" maxLength={50} autoCapitalize="characters" aria-invalid={touched && Boolean(codeError)} />
        </Field>
        <Field label="Descrição" error={touched ? descriptionError : null}>
          <textarea className="textarea" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={200} rows={3} placeholder="Ex.: 10% de desconto em recargas aos fins de semana" />
        </Field>
        <div className="form-grid">
          <Field label="Desconto" error={touched ? percent.error : null}>
            <div className="input-affix">
              <input className="input" inputMode="numeric" value={discount} onChange={(e) => setDiscount(e.target.value)} aria-invalid={touched && Boolean(percent.error)} />
              <span className="affix">%</span>
            </div>
          </Field>
          <Field label="Válido até" error={touched ? dateError : null}>
            <input className="input" type="date" min={today} value={validUntil} onChange={(e) => setValidUntil(e.target.value)} />
          </Field>
        </div>
        <Field label="Estação" hint="opcional">
          <select className="select" value={stationId} onChange={(e) => setStationId(e.target.value)}>
            <option value="">Todas as minhas estações</option>
            {stations.map((station) => (
              <option key={station.id} value={station.id}>
                {station.name}
              </option>
            ))}
          </select>
        </Field>
        <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
          Os códigos são únicos em toda a plataforma e salvos em maiúsculas.
        </p>
      </form>
    </Drawer>
  )
}

export default function Coupons() {
  const { ep } = useAuth()
  const toast = useToast()
  const { stations } = useFilters()
  const { data, error, reload } = useApi((signal) => ep.coupons(signal), 'coupons')
  const [overrides, setOverrides] = useState<Record<string, Coupon>>({})
  const [created, setCreated] = useState<Coupon[]>([])
  const [creating, setCreating] = useState(false)
  const [pending, setPending] = useState<string | null>(null)
  const closeCreate = useCallback(() => setCreating(false), [])

  const coupons = [...created, ...(data?.items ?? []).filter((c) => !created.some((n) => n.id === c.id))].map((c) => overrides[c.id] ?? c)
  const stationName = (id: string | null) => (id ? (stations.find((s) => s.id === id)?.name ?? 'Estação') : 'Todas as estações')
  const activeCount = coupons.filter((c) => couponState(c).label === 'Ativo').length

  const toggle = async (coupon: Coupon, active: boolean) => {
    setPending(coupon.id)
    try {
      const next = await ep.patchCoupon(coupon.id, { active })
      setOverrides((map) => ({ ...map, [coupon.id]: next }))
      toast(active ? `Cupom ${coupon.code} ativado` : `Cupom ${coupon.code} desativado`)
    } catch (err) {
      toast(err instanceof ApiError ? err.message : 'Não foi possível atualizar o cupom', 'error')
    } finally {
      setPending(null)
    }
  }

  return (
    <>
      <PageHead
        title="Cupons"
        sub={data ? `${activeCount} ativo(s) de ${coupons.length}` : 'Descontos para atrair motoristas às suas estações'}
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>
            <Icon name="plus" size={16} /> Novo cupom
          </button>
        }
      />
      <Card>
        {error ? <ErrorBanner error={error} onRetry={reload} /> : null}
        {!data && !error ? <SkeletonRows rows={4} height={40} /> : null}
        {data && !coupons.length ? (
          <EmptyState icon="ticket" title="Nenhum cupom criado" action={<button type="button" className="btn btn-primary" onClick={() => setCreating(true)}>Criar primeiro cupom</button>}>
            Cupons dão desconto percentual na recarga e ajudam a ocupar horários vazios.
          </EmptyState>
        ) : null}
        {coupons.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Descrição</th>
                  <th className="right">Desconto</th>
                  <th>Estação</th>
                  <th>Válido até</th>
                  <th>Situação</th>
                  <th className="right">Ativo</th>
                </tr>
              </thead>
              <tbody>
                {coupons.map((coupon) => {
                  const state = couponState(coupon)
                  const expired = state.label === 'Expirado'
                  return (
                    <tr key={coupon.id}>
                      <td>
                        <span className="num" style={{ fontSize: 18, fontWeight: 600, letterSpacing: 0.8 }}>
                          {coupon.code}
                        </span>
                      </td>
                      <td className="muted" style={{ whiteSpace: 'normal', minWidth: 220 }}>
                        {coupon.description || '—'}
                      </td>
                      <td className="right strong tabular">{coupon.discount_percent}%</td>
                      <td>{stationName(coupon.station_id)}</td>
                      <td className="tabular">{formatDate(coupon.valid_until)}</td>
                      <td>
                        <Badge tone={state.tone}>{state.label}</Badge>
                      </td>
                      <td className="right">
                        <span title={expired && !coupon.active ? 'Cupom expirado: a API exige nova validade para reativar' : undefined}>
                          <Switch
                            checked={coupon.active}
                            disabled={pending === coupon.id || (expired && !coupon.active)}
                            onChange={(value) => void toggle(coupon, value)}
                            label={<span className="sr-only">{coupon.active ? 'Desativar' : 'Ativar'} {coupon.code}</span>}
                          />
                        </span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        ) : null}
      </Card>
      {creating ? (
        <CreateCoupon
          onClose={closeCreate}
          onCreated={(coupon) => {
            setCreated((list) => [coupon, ...list])
            setCreating(false)
            toast(`Cupom ${coupon.code} criado`)
          }}
        />
      ) : null}
    </>
  )
}
