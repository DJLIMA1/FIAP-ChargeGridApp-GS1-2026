import { useState } from 'react'
import { ApiError } from '../../api/client'
import type { Connector } from '../../api/types'
import { useAuth } from '../../auth/AuthContext'
import { cgAddrHint, chargerReadingText, chargerState, validateChargerAddress } from '../../lib/charger'
import { useToast } from '../Toast'
import { Field } from '../ui'
import { useLiveDraft } from '../../lib/useLiveDraft'

/**
 * Endereço Modbus do carregador (1–247, único no posto, nunca vazio), salvo na hora por
 * `PATCH /connectors/{id}` (`charger_address`). Some com a API antiga (sem o campo). `suggested` só
 * preenche o campo de um dado legado sem endereço (`null`).
 */
export function ChargerField({ connector, onSaved, suggested = null }: { connector: Connector; onSaved(next: Connector): void; suggested?: number | null }) {
  const { ep } = useAuth()
  const toast = useToast()
  const saved = connector.charger_address ?? null
  const fallback = saved ?? suggested
  const [text, setText, formEvents] = useLiveDraft(fallback === null ? '' : String(fallback))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
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
      toast(`${connector.public_code}: carregador no endereço ${parsed.value}`)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Não foi possível salvar. Tente novamente.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div data-testid="charger-field" {...formEvents}>
      <Field label="Endereço" hint={saved === null ? 'sem endereço · 1 a 247' : '1 a 247'} error={error}>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="input"
            inputMode="numeric"
            data-testid="charger-address"
            style={{ minWidth: 0, flex: 1 }}
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
    </div>
  )
}

/**
 * Linha do carregador: `Carregador 1 · online · última leitura agora · lendo 53,6 kW`; fora do ar
 * ou aguardando a central, também o `CG_ADDR` que o ESP do carregador precisa ter.
 */
export function ChargerLinkLine({ connector, now }: { connector: Connector; now?: Date }) {
  const state = chargerState(connector)
  const address = connector.charger_address
  if (address === undefined || address === null || !state) return null
  const reading = chargerReadingText(connector.charger_link, now)
  // "Carregador N" e o estado já estão no cabeçalho do cartão: aqui só a leitura e a dica do CG_ADDR.
  if (!reading && state === 'online') return null
  return (
    <div data-testid="charger-status" className="dim" style={{ fontSize: 12.5 }}>
      {reading ?? ''}
      {state !== 'online' ? <span data-testid="charger-cgaddr">{reading ? ' · ' : ''}{cgAddrHint(address)}</span> : null}
    </div>
  )
}
