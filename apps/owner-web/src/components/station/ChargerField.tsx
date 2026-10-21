import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'
import type { Connector } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { CHARGER_SUGGESTED_ADDRESS, chargerStatusText, validateChargerAddress } from '../../lib/charger'
import { useToast } from '../Toast'
import { Field } from '../ui'

/**
 * Carregador GoodWe HCA G2 ligado à tela deste ponto, como no app (Conectores → conector): endereço
 * (1 sugerido) salvo na hora por `PATCH /connectors/{id}` (`charger_address`; Remover envia `null`)
 * e o status numa linha ("Carregador 1 · GoodWe HCA G2 (simulado) · online"). Some com a API antiga.
 */
export function ChargerField({ connector, onSaved }: { connector: Connector; onSaved(next: Connector): void }) {
  const { ep } = useAuth()
  const toast = useToast()
  const saved = connector.charger_address ?? null
  const [text, setText] = useState(String(saved ?? CHARGER_SUGGESTED_ADDRESS))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => setText(String(saved ?? CHARGER_SUGGESTED_ADDRESS)), [saved])
  if (connector.charger_address === undefined) return null

  const parsed = validateChargerAddress(text)
  const unchanged = parsed.value !== undefined && parsed.value === saved

  const persist = async (value: number | null) => {
    if (saving) return
    setSaving(true)
    setError(null)
    try {
      const next = await ep.patchConnector(connector.id, { charger_address: value })
      onSaved(next)
      toast(value === null ? `Carregador removido de ${connector.public_code}` : `Carregador ${value} ligado a ${connector.public_code}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }
  const save = () => {
    if (parsed.error) return setError(parsed.error)
    if (!unchanged) void persist(parsed.value as number)
  }
  const status = chargerStatusText(connector.charger_link)

  return (
    <div style={{ marginTop: 12 }} data-testid="charger-field">
      <Field label="Carregador GoodWe (endereço)" hint="1 a 247 · Modbus TCP na rede da tela" error={error}>
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
                save()
              }
            }}
            aria-invalid={Boolean(error)}
          />
          <button type="button" className="btn btn-secondary" disabled={saving || unchanged} onClick={save}>
            {saving ? 'Salvando…' : 'Salvar'}
          </button>
          {saved !== null ? (
            <button type="button" className="btn btn-ghost" disabled={saving} onClick={() => void persist(null)}>
              Remover
            </button>
          ) : null}
        </div>
      </Field>
      <div data-testid="charger-status" className="dim" style={{ fontSize: 12.5, marginTop: 6 }}>
        {status || 'Sem carregador externo: a tela usa a simulação interna.'}
      </div>
    </div>
  )
}
