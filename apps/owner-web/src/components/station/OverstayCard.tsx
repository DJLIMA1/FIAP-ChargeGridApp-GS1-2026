import { useEffect, useState, type FormEvent } from 'react'
import { ApiError } from '../../api/client'
import type { PricingRules } from '../../api/operations'
import type { Station } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { rotationForm, rotationSummary, validateRotation, withRotation, type RotationForm } from '../../lib/overstay'
import { useApi } from '../../lib/useApi'
import { useToast } from '../Toast'
import { Card, ErrorBanner, Field, Skeleton, Switch } from '../ui'

/**
 * "Taxa de permanência" (frente D): edita `rules.rotation` da tarifa do posto e
 * grava as regras inteiras (tarifa por horário e por demanda continuam iguais).
 */
export function OverstayCard({ station }: { station: Station }) {
  const { ep } = useAuth()
  const toast = useToast()
  const { data, error, reload } = useApi((signal) => ep.pricing(station.id, signal), `pricing|${station.id}`)
  const [rules, setRules] = useState<PricingRules | null>(null)
  const [form, setForm] = useState<RotationForm>(() => rotationForm(null))
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (data?.rules) {
      setRules(data.rules)
      setForm(rotationForm(data.rules))
    }
  }, [data])

  // Sem tarifa no posto (API antiga ou rota ausente), o cartão some.
  if (error && !rules && error.status === 404) return null

  const initial = rotationForm(rules)
  const check = validateRotation(form)
  const dirty = JSON.stringify(form) !== JSON.stringify(initial)
  const preview = check.values ? rotationSummary(check.values) : null

  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!rules || !check.values || !dirty || saving) return
    setSaving(true)
    setSaveError(null)
    try {
      const next = await ep.putPricing(station.id, withRotation(rules, check.values))
      setRules(next.rules)
      setForm(rotationForm(next.rules))
      toast(check.values.enabled ? 'Taxa de permanência salva' : 'Taxa de permanência desligada')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }
  const set = (patch: Partial<RotationForm>) => setForm((current) => ({ ...current, ...patch }))

  return (
    <Card title="Taxa de permanência" sub="Cobrada de quem continua na vaga depois que a recarga termina" id="overstay">
      {error && !rules ? <ErrorBanner error={error} onRetry={reload} /> : null}
      {!rules && !error ? <Skeleton height={160} /> : null}
      {rules ? (
        <form onSubmit={save} className="stack" noValidate>
          <Switch checked={form.enabled} disabled={saving} onChange={(enabled) => set({ enabled })} label={form.enabled ? 'Cobrar taxa de permanência' : 'Sem taxa de permanência'} />
          <div className="connector-fields fields-4" style={{ opacity: form.enabled ? 1 : 0.55, marginTop: 0 }}>
            <Field label="Tolerância" error={dirty ? check.errors.grace : null}>
              <div className="input-affix">
                <input className="input" inputMode="numeric" value={form.grace} disabled={!form.enabled} onChange={(e) => set({ grace: e.target.value })} aria-invalid={Boolean(check.errors.grace)} />
                <span className="affix">min</span>
              </div>
            </Field>
            <Field label="A cada" error={dirty ? check.errors.interval : null}>
              <div className="input-affix">
                <input className="input" inputMode="numeric" value={form.interval} disabled={!form.enabled} onChange={(e) => set({ interval: e.target.value })} aria-invalid={Boolean(check.errors.interval)} />
                <span className="affix">min</span>
              </div>
            </Field>
            <Field label="Valor" hint="por intervalo" error={dirty ? check.errors.amount : null}>
              <div className="input-affix">
                <span className="lead">R$</span>
                <input className="input" inputMode="decimal" value={form.amount} disabled={!form.enabled} onChange={(e) => set({ amount: e.target.value })} aria-invalid={Boolean(check.errors.amount)} />
              </div>
            </Field>
            <Field label="Máximo" hint="por recarga" error={dirty ? check.errors.max : null}>
              <div className="input-affix">
                <span className="lead">R$</span>
                <input className="input" inputMode="decimal" value={form.max} disabled={!form.enabled} onChange={(e) => set({ max: e.target.value })} aria-invalid={Boolean(check.errors.max)} />
              </div>
            </Field>
          </div>
          <p className="muted" style={{ margin: 0, fontSize: 13.5 }}>
            {preview ?? (dirty ? 'Corrija os campos destacados.' : station.overstay?.summary)}
          </p>
          <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
            O motorista aceita os termos ao iniciar a recarga; mudanças valem para as próximas. A contagem começa quando a recarga termina e para quando o carro é desconectado.
          </p>
          {saveError ? <ErrorBanner error={saveError} title="Taxa de permanência não salva" /> : null}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => { setForm(initial); setSaveError(null) }}>
              Descartar
            </button>
            <button type="submit" className="btn btn-primary" disabled={!dirty || saving || !check.values}>
              {saving ? 'Salvando…' : 'Salvar taxa'}
            </button>
          </div>
        </form>
      ) : null}
    </Card>
  )
}
