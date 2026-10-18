import type { Profile } from '../api/types'

export const NOT_VENDOR_MESSAGE = 'Este painel é exclusivo para vendedores. Use o app ChargeGrid como motorista.'
export const OPERATOR_PENDING_MESSAGE =
  'Sua conta de vendedor ainda não tem estações vinculadas. Vincule seu primeiro equipamento pelo app ChargeGrid (QR de propriedade) e volte aqui para acompanhar a operação.'

/** Vendedor = operador habilitado ou conta do tipo "vendor" (mesma regra do app). */
export function isVendor(profile: Pick<Profile, 'operator_enabled' | 'account_type'> | null | undefined): boolean {
  return Boolean(profile && (profile.operator_enabled === true || profile.account_type === 'vendor'))
}

export type AccessDecision = 'granted' | 'operator_pending' | 'not_vendor'

/**
 * - `granted`: operador habilitado — os endpoints /owner/* respondem.
 * - `operator_pending`: conta vendedora sem operação habilitada (a API
 *   responderia 403 nos indicadores); mostra orientação em vez de erros.
 * - `not_vendor`: motorista — o painel encerra a sessão.
 */
export function accessFor(profile: Pick<Profile, 'operator_enabled' | 'account_type'> | null | undefined): AccessDecision {
  if (!isVendor(profile)) return 'not_vendor'
  return profile!.operator_enabled ? 'granted' : 'operator_pending'
}
