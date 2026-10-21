/**
 * Carregador GoodWe HCA G2 ligado a um ponto/tela (`connectors.charger_address`, 1–247, `null` = sem
 * carregador externo). Mesmas regras e texto do app e da API (`chargegrid_core.chargers.link`).
 */
import type { ChargerLink, ChargerLinkState } from '../api/types'

export const CHARGER_MODEL = 'goodwe_hca_g2'
export const CHARGER_TRANSPORT = 'modbus_tcp'
export const CHARGER_LABEL = 'GoodWe HCA G2'
export const CHARGER_SUGGESTED_ADDRESS = 1
export const CHARGER_MIN_ADDRESS = 1
export const CHARGER_MAX_ADDRESS = 247

export const CHARGER_LINK_TEXT: Record<ChargerLinkState, string> = {
  online: 'online',
  offline: 'offline',
  pending: 'aguardando a tela',
}

export function chargerHost(address: number): string {
  return `cg-hca-${address}.local`
}

/** `Carregador 1 · GoodWe HCA G2 (simulado) · online` (vazio sem carregador). */
export function chargerStatusText(link: ChargerLink | null | undefined): string {
  if (!link || link.address === null || link.address === undefined) return ''
  let label = link.label || CHARGER_LABEL
  if (link.simulated ?? true) label += ' (simulado)'
  const state = CHARGER_LINK_TEXT[link.link as ChargerLinkState] ?? CHARGER_LINK_TEXT.pending
  return `Carregador ${link.address} · ${label} · ${state}`
}

/** Endereço digitado → inteiro 1–247 (vazio = erro; remover é um botão próprio). */
export function validateChargerAddress(text: string): { value?: number; error?: string } {
  const raw = text.trim()
  if (!raw) return { error: 'Informe o endereço do carregador (1 a 247).' }
  if (!/^\d+$/.test(raw)) return { error: 'Use um número inteiro de 1 a 247.' }
  const value = Number(raw)
  if (value < CHARGER_MIN_ADDRESS || value > CHARGER_MAX_ADDRESS) return { error: 'O endereço vai de 1 a 247.' }
  return { value }
}
