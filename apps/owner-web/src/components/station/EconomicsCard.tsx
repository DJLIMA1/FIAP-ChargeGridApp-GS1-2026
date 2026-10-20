import { useEffect, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ApiError } from '../../api/client'
import type { StationEconomics } from '../../api/operations'
import { useAuth } from '../../auth/AuthContext'
import { formatNumber, toNumber } from '../../lib/format'
import { validateEnergyCost } from '../../lib/margin'
import { useApi } from '../../lib/useApi'
import { Icon } from '../Icon'
import { useToast } from '../Toast'
import { Card, ErrorBanner, Field, Skeleton } from '../ui'

function toInput(value: string | null | undefined): string {
  const number = toNumber(value)
  if (number === null) return ''
  // Até 4 casas, mantendo ao menos o centavo: "0,85", "0,8125", "1,00".
  return number.toFixed(4).replace(/0{1,2}$/, '').replace('.', ',')
}

/** "Custo da energia (R$/kWh)" editável e comissão da plataforma só leitura (frente C). */
export function EconomicsCard({ stationId }: { stationId: string }) {
  const { ep } = useAuth()
  const toast = useToast()
  const { data, error, reload } = useApi((signal) => ep.economics(stationId, signal), `economics|${stationId}`)
  const [saved, setSaved] = useState<StationEconomics | null>(null)
  const [draft, setDraft] = useState('')
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const current = saved ?? data ?? null

  useEffect(() => {
    if (data) {
      setSaved(data)
      setDraft(toInput(data.energy_cost_per_kwh))
    }
  }, [data])

  // API sem a frente C (404): o cartão some em vez de mostrar erro.
  if (error && !current && error.status === 404) return null

  const initial = toInput(current?.energy_cost_per_kwh)
  const check = validateEnergyCost(draft)
  const dirty = draft.trim() !== initial
  const save = async (event: FormEvent) => {
    event.preventDefault()
    if (!dirty || check.error || saving || check.value === undefined) return
    setSaving(true)
    setSaveError(null)
    try {
      const next = await ep.putEconomics(stationId, check.value)
      setSaved(next)
      setDraft(toInput(next.energy_cost_per_kwh))
      toast(next.energy_cost_per_kwh === null ? 'Custo da energia removido' : 'Custo da energia salvo')
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Card
      title="Custo da energia e comissão"
      sub="Usados no Resultado para estimar a margem de cada recarga"
      id="economics"
      action={
        <Link to="/resultado" className="card-link">
          Ver resultado <Icon name="chevronRight" size={16} />
        </Link>
      }
    >
      {error && !current ? <ErrorBanner error={error} onRetry={reload} /> : null}
      {!current && !error ? <Skeleton height={90} /> : null}
      {current ? (
        <form onSubmit={save} className="stack" noValidate>
          <div className="form-grid">
            <Field label="Custo da energia" hint="R$/kWh pago à distribuidora" error={dirty ? check.error : null}>
              <div className="input-affix">
                <span className="lead">R$</span>
                <input
                  className="input"
                  inputMode="decimal"
                  placeholder="não informado"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  aria-invalid={Boolean(check.error)}
                  aria-label="Custo da energia em reais por kWh"
                />
                <span className="affix">/kWh</span>
              </div>
            </Field>
            <Field label="Comissão da plataforma" hint="definida em contrato">
              <div className="input-affix">
                <input className="input" value={formatNumber(current.platform_fee_percent, Number.isInteger(toNumber(current.platform_fee_percent)) ? 0 : 2)} readOnly disabled aria-readonly="true" />
                <span className="affix">%</span>
              </div>
            </Field>
          </div>
          <p className="dim" style={{ margin: 0, fontSize: 12.5 }}>
            {current.energy_cost_per_kwh === null
              ? 'Sem o custo do kWh, o Resultado mostra a margem como "—" (nunca como zero). '
              : ''}
            Vale para as próximas recargas: as anteriores mantêm o custo travado no início. A comissão incide sobre o valor cobrado depois do cupom e só é alterada pela plataforma.
          </p>
          {saveError ? <ErrorBanner error={saveError} title="Custo não salvo" /> : null}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
            <button type="button" className="btn btn-ghost" disabled={!dirty || saving} onClick={() => { setDraft(initial); setSaveError(null) }}>
              Descartar
            </button>
            <button type="submit" className="btn btn-primary" disabled={!dirty || saving || Boolean(check.error)}>
              {saving ? 'Salvando…' : draft.trim() ? 'Salvar custo' : 'Remover custo'}
            </button>
          </div>
        </form>
      ) : null}
    </Card>
  )
}
