/**
 * Resultado do dono (frente C): cascata receita → comissão → repasse → custo da
 * energia → margem, a faixa "Receita bruta não é lucro" e a exportação.
 *
 * Os valores já chegam calculados pela API (`chargegrid_core.economics`, ao
 * centavo e fechando com o CSV/PDF); aqui só organizamos e rotulamos. Custo da
 * energia ausente nunca vira zero: a margem fica "—".
 */
import type { MarginReport, MarginStationConfig, MarginTotals } from '../api/operations'
import { formatCurrency, formatNumber, toNumber } from './format'

export const NOT_PROFIT_TITLE = 'Receita bruta não é lucro'
export const NOT_PROFIT_TEXT =
  'A margem de contribuição é o que sobra da receita cobrada depois da comissão da plataforma, da tarifa do provedor de pagamento e do custo estimado da energia. Ela não inclui custos fixos (equipamento, manutenção) nem a tarifa de demanda (R$/kW). O aluguel das centrais é descontado do repasse e do resultado.'

export type CascadeKind = 'total' | 'minus' | 'plus' | 'result'

export interface CascadeStep {
  key: string
  label: string
  kind: CascadeKind
  /** Valor positivo em reais (string decimal da API) ou `null` = sem dado ("—"). */
  value: string | null
  hint?: string
  /** Custo da energia não informado: a tela mostra o atalho para configurar. */
  missingCost?: boolean
}

/** "25%" quando todos os postos têm a mesma comissão; "25% a 20%" quando variam. */
export function feeLabel(stations: Pick<MarginStationConfig, 'platform_fee_percent'>[], fallback = '25'): string {
  const values = [...new Set(stations.map((s) => toNumber(s.platform_fee_percent)).filter((v): v is number => v !== null))]
  if (!values.length) return `${formatNumber(fallback, 0)}%`
  const fmt = (v: number) => `${formatNumber(v, Number.isInteger(v) ? 0 : 2)}%`
  if (values.length === 1) return fmt(values[0])
  return `${fmt(Math.min(...values))} a ${fmt(Math.max(...values))}`
}

function hasValue(value: string | null | undefined): value is string {
  return value !== null && value !== undefined && toNumber(value) !== null
}

/**
 * Passos da cascata, na ordem da tela e do PDF:
 * Receita bruta → − Descontos/cupons → (+ Permanência) → (± Ajuste do pagamento) → = Receita cobrada →
 * − Comissão → (− Tarifa do provedor) → = Repasse → (− Aluguel das centrais → = Repasse líquido) →
 * − Custo da energia → = Margem (ou Resultado, com aluguel).
 */
export function buildCascade(totals: MarginTotals, fee: string): CascadeStep[] {
  const steps: CascadeStep[] = [
    { key: 'gross', label: 'Receita bruta', kind: 'total', value: totals.gross, hint: 'kWh × preço travado, antes do cupom' },
    { key: 'discount', label: 'Descontos e cupons', kind: 'minus', value: totals.discount },
  ]
  if (hasValue(totals.overstay_revenue)) {
    steps.push({ key: 'overstay', label: 'Taxa de permanência', kind: 'plus', value: totals.overstay_revenue })
  }
  const adjustment = toNumber(totals.payment_adjustment)
  if (adjustment) {
    // Valor capturado no pagamento diferente do calculado (perdoado acima do teto, abaixo do mínimo...).
    steps.push({
      key: 'payment_adjustment',
      label: 'Ajuste do pagamento',
      kind: adjustment < 0 ? 'minus' : 'plus',
      value: Math.abs(adjustment).toFixed(2),
      hint: 'Perdoado ou não cobrado no pagamento confirmado',
    })
  }
  steps.push({ key: 'revenue_total', label: 'Receita cobrada', kind: 'total', value: totals.revenue_total })
  steps.push({ key: 'platform_fee', label: `Comissão da plataforma (${fee})`, kind: 'minus', value: totals.platform_fee })
  if (hasValue(totals.provider_fee)) {
    steps.push({ key: 'provider_fee', label: 'Tarifa do provedor de pagamento', kind: 'minus', value: totals.provider_fee })
  }
  const rent = hasValue(totals.central_rent) ? totals.central_rent : null
  steps.push({ key: 'owner_net', label: rent ? 'Repasse das recargas' : 'Repasse', kind: 'total', value: totals.owner_net, hint: rent ? undefined : 'O que a plataforma repassa ao posto' })
  if (rent) {
    const count = totals.centrals ?? 0
    steps.push({ key: 'central_rent', label: `Aluguel das centrais (${formatNumber(count)} ${count === 1 ? 'central' : 'centrais'})`, kind: 'minus', value: rent, hint: 'Valor mensal por central, rateado pelos dias de vínculo' })
    steps.push({ key: 'owner_net_after_rent', label: 'Repasse líquido', kind: 'total', value: totals.owner_net_after_rent ?? null, hint: 'O que a plataforma repassa ao posto (descontado da folha)' })
  }
  const { missing_energy_cost: missing, sessions } = totals.coverage
  steps.push({
    key: 'energy_cost',
    label: 'Custo estimado da energia',
    kind: 'minus',
    value: missing ? null : totals.energy_cost,
    missingCost: missing > 0,
    hint: missing ? `${formatNumber(missing)} de ${formatNumber(sessions)} sessão(ões) sem custo do kWh informado` : 'kWh × custo do kWh informado no posto',
  })
  if (rent) {
    steps.push({
      key: 'result',
      label: 'Resultado estimado',
      kind: 'result',
      value: missing ? null : (totals.result ?? null),
      missingCost: missing > 0,
      hint: missing ? undefined : `Margem de contribuição antes do aluguel: ${formatCurrency(totals.margin)}`,
    })
    return steps
  }
  steps.push({
    key: 'margin',
    label: 'Margem estimada',
    kind: 'result',
    value: missing ? null : totals.margin,
    missingCost: missing > 0,
    hint:
      missing && sessions > missing
        ? `Parcial: ${formatCurrency(totals.margin_covered)} em ${formatNumber(sessions - missing)} sessão(ões) com custo`
        : totals.margin_percent !== null && !missing
          ? `${formatNumber(totals.margin_percent, 1)}% da receita cobrada`
          : undefined,
  })
  return steps
}

/** Largura relativa (0–100) de cada passo em relação à receita bruta. */
export function cascadeWidth(step: CascadeStep, gross: string | null): number {
  const base = toNumber(gross) ?? 0
  const value = Math.abs(toNumber(step.value) ?? 0)
  if (base <= 0) return 0
  return Math.max(0, Math.min(100, (value / base) * 100))
}

/** Postos sem custo do kWh informado (para o atalho "Configurar"). */
export function stationsMissingCost(report: Pick<MarginReport, 'stations'>): MarginStationConfig[] {
  return report.stations.filter((s) => s.energy_cost_per_kwh === null || s.energy_cost_per_kwh === undefined)
}

/** Custo do kWh digitado ("0,85") → string da API, `null` (vazio = não informado) ou erro. */
export function validateEnergyCost(text: string): { value?: string | null; error?: string } {
  const raw = text.trim()
  if (!raw) return { value: null }
  if (!/^\d{1,3}([.,]\d{1,4})?$/.test(raw)) return { error: 'Use números, por exemplo 0,85 (até 4 casas).' }
  const number = Number(raw.replace(',', '.'))
  if (number < 0 || number > 100) return { error: 'O custo do kWh vai de R$ 0,00 a R$ 100,00.' }
  return { value: number.toFixed(4) }
}

function slug(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

/** "10/2026" a partir de "2026-10". */
export function monthLabel(month: string): string {
  const [year, number] = month.split('-')
  return number ? `${number}/${year}` : month
}

/** "chargegrid-aluguel-centrais-20261020-1405[-villa-lobos].csv". */
export function rentExportFilename(now: Date = new Date(), stationName?: string | null): string {
  return marginExportFilename('csv', now, stationName).replace('chargegrid-resultado-', 'chargegrid-aluguel-centrais-')
}

/** "chargegrid-resultado-20261020-1405[-villa-lobos].csv" no horário de São Paulo. */
export function marginExportFilename(fmt: 'csv' | 'pdf', now: Date = new Date(), stationName?: string | null): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Sao_Paulo',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(now)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  const suffix = stationName ? slug(stationName) : ''
  return `chargegrid-resultado-${get('year')}${get('month')}${get('day')}-${get('hour')}${get('minute')}${suffix ? `-${suffix}` : ''}.${fmt}`
}
