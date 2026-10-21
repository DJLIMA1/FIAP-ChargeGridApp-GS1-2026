/**
 * Cada conector É um carregador GoodWe HCA G2 (`connectors.charger_address`, 1–247, único por posto,
 * automático pela ordem do posto e editável pelo dono; nunca vazio). Enquanto o carregador do
 * endereço não responde, a tela carrega com a simulação interna dela. Mesmas regras e texto do app
 * e da API (`chargegrid_core.chargers.link`).
 */
import type { ChargerLink, ChargerLinkState } from '../api/types'

export const CHARGER_MODEL = 'goodwe_hca_g2'
export const CHARGER_TRANSPORT = 'modbus_tcp'
export const CHARGER_LABEL = 'GoodWe HCA G2'
export const CHARGER_MIN_ADDRESS = 1
export const CHARGER_MAX_ADDRESS = 247

/** Mensagens da API (422 `invalid_charger_address`), reaproveitadas na validação do campo. */
export const CHARGER_ADDRESS_EMPTY = 'Endereço do carregador não pode ficar vazio: informe um número de 1 a 247'
export const CHARGER_ADDRESS_INVALID = 'Endereço do carregador deve ser um número inteiro de 1 a 247'

/** Sem resposta do carregador (`offline`) ou tela que ainda não confirmou o endereço (`pending`). */
export const CHARGER_WAITING_TEXT = 'aguardando carregador (simulação da tela)'

export const CHARGER_LINK_TEXT: Record<ChargerLinkState, string> = {
  online: 'online',
  offline: CHARGER_WAITING_TEXT,
  pending: CHARGER_WAITING_TEXT,
}

export function chargerHost(address: number): string {
  return `cg-hca-${address}.local`
}

/** Menor endereço livre do posto (1, 2, 3…), ignorando vazios; posto cheio → `null`. */
export function nextFreeChargerAddress(used: Iterable<number | null | undefined>): number | null {
  const taken = new Set<number>()
  for (const value of used) if (typeof value === 'number') taken.add(value)
  for (let address = CHARGER_MIN_ADDRESS; address <= CHARGER_MAX_ADDRESS; address++) {
    if (!taken.has(address)) return address
  }
  return null
}

/** `Carregador GoodWe · endereço 1 · online` ou `… · aguardando carregador (simulação da tela)` (vazio sem bloco). */
export function chargerStatusText(link: ChargerLink | null | undefined): string {
  if (!link || link.address === null || link.address === undefined) return ''
  const state = CHARGER_LINK_TEXT[link.link as ChargerLinkState] ?? CHARGER_WAITING_TEXT
  return `Carregador GoodWe · endereço ${link.address} · ${state}`
}

/** Endereço digitado → inteiro 1–247. Vazio é erro: todo conector é um carregador. */
export function validateChargerAddress(text: string): { value?: number; error?: string } {
  const raw = text.trim()
  if (!raw) return { error: CHARGER_ADDRESS_EMPTY }
  if (!/^\d+$/.test(raw)) return { error: CHARGER_ADDRESS_INVALID }
  const value = Number(raw)
  if (value < CHARGER_MIN_ADDRESS || value > CHARGER_MAX_ADDRESS) return { error: CHARGER_ADDRESS_INVALID }
  return { value }
}
