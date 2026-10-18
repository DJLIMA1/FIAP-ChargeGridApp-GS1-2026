/** Rótulos em português para códigos da API (mesmos do painel Flet). */

export type Tone = 'green' | 'blue' | 'amber' | 'red' | 'gray'

export const SESSION_STATUS: Record<string, { label: string; tone: Tone }> = {
  starting: { label: 'Iniciando', tone: 'blue' },
  charging: { label: 'Em recarga', tone: 'blue' },
  stopping: { label: 'Encerrando', tone: 'blue' },
  completed: { label: 'Concluída', tone: 'green' },
  interrupted: { label: 'Interrompida', tone: 'amber' },
  failed: { label: 'Falhou', tone: 'red' },
}

export const SESSION_STATUS_ORDER = ['completed', 'charging', 'starting', 'stopping', 'interrupted', 'failed'] as const

export const AVAILABILITY: Record<string, { label: string; tone: Tone }> = {
  available: { label: 'Disponível', tone: 'green' },
  charging: { label: 'Carregando', tone: 'blue' },
  occupied: { label: 'Conector em uso', tone: 'blue' },
  reserved: { label: 'Reservado', tone: 'amber' },
  reconciling: { label: 'Sincronizando', tone: 'amber' },
  offline: { label: 'Offline', tone: 'red' },
  fault: { label: 'Falha', tone: 'red' },
  disabled: { label: 'Desativado', tone: 'gray' },
}

export const SOURCE_LABELS: Record<string, string> = { simulated: 'Simulada', measured: 'Medida', estimated: 'Estimada' }

export const END_REASON_LABELS: Record<string, string> = {
  duration_limit: 'Limite de tempo',
  cost_limit: 'Limite de valor',
  requested: 'Pedido no app',
  local_stop: 'Parada no painel',
  communication_lost: 'Comunicação perdida',
  device_reboot: 'Reinício do painel',
  device_fault: 'Falha do equipamento',
  start_timeout: 'Início não confirmado',
}

export const SEVERITY: Record<string, { label: string; tone: Tone }> = {
  critical: { label: 'Crítico', tone: 'red' },
  warning: { label: 'Atenção', tone: 'amber' },
  info: { label: 'Informativo', tone: 'gray' },
}

export const IMPACT: Record<string, { label: string; tone: Tone }> = {
  high: { label: 'Alto impacto', tone: 'red' },
  medium: { label: 'Médio impacto', tone: 'amber' },
  low: { label: 'Baixo impacto', tone: 'gray' },
}

export const INSIGHT_KIND: Record<string, string> = { pricing: 'Preço', operations: 'Operação', marketing: 'Marketing' }

export const AMENITY_KINDS = ['restaurante', 'cafe', 'banheiro', 'shopping', 'conveniencia'] as const
export const AMENITY_LABELS: Record<string, string> = {
  restaurante: 'Restaurante',
  cafe: 'Café',
  banheiro: 'Banheiro',
  shopping: 'Shopping',
  conveniencia: 'Conveniência',
}

export function label<T extends { label: string }>(map: Record<string, T>, key: string | null | undefined, fallback = '—'): string {
  if (!key) return fallback
  return map[key]?.label ?? key
}
