import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import type { Connector } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { CHARGER_WAITING_TEXT, chargerStatusText, validateChargerAddress } from '../../lib/charger'
import { useToast } from '../Toast'
import { Field } from '../ui'

/**
 * Este conector É um carregador GoodWe HCA G2, como no app (Conectores → conector): endereço
 * (automático pela ordem do posto, editável, nunca vazio) salvo na hora por `PATCH /connectors/{id}`
 * (`charger_address`) e o status numa linha ("Carregador GoodWe · endereço 1 · online" ou
 * "… · aguardando carregador (simulação da tela)"). Some com a API antiga (sem o campo).
 * `suggested` só preenche o campo de um dado legado sem endereço (`null`).
 */
export function ChargerField({ connector, onSaved, suggested = null }: { connector: Connector; onSaved(next: Connector): void; suggested?: number | null }) {
  const { ep } = useAuth()
  const toast = useToast()
  const saved = connector.charger_address ?? null
  const fallback = saved ?? suggested
  const [text, setText] = useState(fallback === null ? '' : String(fallback))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setText(fallback === null ? '' : String(fallback)), [fallback])
  if (connector.charger_address === undefined) return null

  const parsed = validateChargerAddress(text)
  const unchanged = parsed.value !== undefined && parsed.value === saved

  const save = async () => {
    if (saving) return
    // Vazio/fora da faixa: mensagem no campo, sem request (o endereço nunca fica vazio).
    if (parsed.error) return setError(parsed.error)
    if (unchanged) return
    setSaving(true)
    setError(null)
    try {
      const next = await ep.patchConnector(connector.id, { charger_address: parsed.value })
      onSaved(next)
      toast(`${connector.public_code}: carregador GoodWe no endereço ${parsed.value}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }
  // Sem `charger_link` (resposta parcial/legado): endereço salvo aparece aguardando o carregador.
  const status =
    chargerStatusText(connector.charger_link) ||
    (saved === null ? 'Carregador GoodWe · sem endereço: informe um número de 1 a 247' : `Carregador GoodWe · endereço ${saved} · ${CHARGER_WAITING_TEXT}`)

  return (
    <div style={{ marginTop: 12 }} data-testid="charger-field">
      <Field label="Carregador GoodWe (endereço)" hint="1 a 247 · único no posto · Modbus TCP na rede da tela" error={error}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            className="input"
            inputMode="numeric"
            data-testid="charger-address"
            style={{ maxWidth: 140 }}
            value={text}
            disabled={saving}
            onChange={(e) => {
              setText(e.target.value)
              setError(null)
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                void save()
              }
            }}
            aria-invalid={Boolean(error)}
          />
          <button type="button" className="btn btn-secondary" disabled={saving || unchanged} onClick={() => void save()}>
            {saving ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </Field>
      <div data-testid="charger-status" className="dim" style={{ fontSize: 12.5, marginTop: 6 }}>
        {status}
      </div>
    </div>
  )
}
