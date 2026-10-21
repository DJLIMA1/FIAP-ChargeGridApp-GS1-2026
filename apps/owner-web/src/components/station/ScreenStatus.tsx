import type { Station } from '../../api/types'
import { chargersLabel } from '../../lib/charger'
import { formatRelative } from '../../lib/format'
import { Badge } from '../ui'

/**
 * A estação É a tela: uma linha por tela do posto (`station.screens`, só o dono) com o status dela,
 * o ponto da tela, quantos carregadores ela comanda e o último contato. Some na API antiga.
 */
export function ScreenStatus({ station, now }: { station: Station; now?: Date }) {
  if (station.screens === undefined) return null
  if (!station.screens.length) {
    return (
      <div className="screen-row" data-testid="screen-status">
        <Badge tone="gray">Sem tela</Badge>
        <span className="dim">Vincule a tela da estação pelo QR no app ChargeGrid.</span>
      </div>
    )
  }
  return (
    <div className="stack" style={{ gap: 8 }} data-testid="screen-status">
      {station.screens.map((screen) => {
        // Conta pelos pontos da página: um carregador recém-adicionado já entra na conta.
        const linked = station.connectors.filter((c) => c.screen?.device_id === screen.device_id).length
        const count = Math.max(linked, screen.charger_ids.length)
        const parts = [`Tela no ponto ${screen.public_code}`, `comanda ${chargersLabel(count)}`, `contato ${formatRelative(screen.last_seen, now)}`]
        if (screen.firmware_version) parts.push(`firmware ${screen.firmware_version}`)
        return (
          <div key={screen.device_id} className="screen-row">
            <Badge tone={screen.online ? 'green' : 'red'}>{screen.online ? 'Tela online' : 'Tela offline'}</Badge>
            <span className="muted">{parts.join(' · ')}</span>
          </div>
        )
      })}
    </div>
  )
}
