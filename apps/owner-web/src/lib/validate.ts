/** Validação dos formulários com os mesmos limites dos schemas da API. */

/** "1,89" / "1.89" / "R$ 1,89" → "1.89"; null se não for número. Aceita milhar com ponto ("1.234,5"). */
export function parseDecimal(input: string): string | null {
  let text = input.replace(/[R$\s]/g, '').trim()
  if (!text) return null
  if (text.includes(',')) text = text.replace(/\./g, '').replace(',', '.')
  if (!/^\d+(\.\d+)?$/.test(text)) return null
  return text.replace(/^0+(?=\d)/, '')
}

export function decimalPlaces(value: string): number {
  const index = value.indexOf('.')
  return index === -1 ? 0 : value.length - index - 1
}

/** Valor da API ("1.8900") → texto de edição pt-BR ("1,89"). */
export function toInputDecimal(value: string | number | null | undefined, minDigits = 0): string {
  if (value === null || value === undefined || value === '') return ''
  const number = Number(value)
  if (!Number.isFinite(number)) return ''
  const text = String(Number(number.toFixed(6)))
  const [int, frac = ''] = text.split('.')
  const padded = frac.padEnd(minDigits, '0')
  return padded ? `${int},${padded}` : int
}

export function validatePrice(input: string): { value?: string; error?: string } {
  const value = parseDecimal(input)
  if (value === null) return { error: 'Informe um valor em reais, ex.: 1,89' }
  if (Number(value) > 10000) return { error: 'Use até R$ 10.000,00 por kWh' }
  if (decimalPlaces(value) > 4) return { error: 'Use no máximo 4 casas decimais' }
  return { value }
}

export function validatePower(input: string): { value?: string; error?: string } {
  const value = parseDecimal(input)
  if (value === null) return { error: 'Informe a potência em kW, ex.: 22' }
  if (Number(value) <= 0) return { error: 'A potência deve ser maior que zero' }
  if (Number(value) > 1000) return { error: 'Use até 1.000 kW' }
  if (decimalPlaces(value) > 3) return { error: 'Use no máximo 3 casas decimais' }
  return { value }
}

export function validateDuration(input: string): { value?: number; error?: string } {
  const text = input.trim()
  if (!/^\d+$/.test(text)) return { error: 'Informe minutos inteiros' }
  const value = Number(text)
  if (value < 1 || value > 1440) return { error: 'Entre 1 e 1.440 minutos (24 h)' }
  return { value }
}

export function validateText(input: string, label: string, max: number): string | null {
  const text = input.trim()
  if (!text) return `Informe ${label}`
  if (text.length > max) return `Use até ${max} caracteres`
  return null
}

export function validateCouponCode(input: string): string | null {
  const text = input.trim()
  if (!text) return 'Informe o código'
  if (text.length > 50) return 'Use até 50 caracteres'
  if (!/^[A-Za-z0-9_-]+$/.test(text)) return 'Use letras, números, hífen ou sublinhado (sem espaços)'
  return null
}

export function validatePercent(input: string): { value?: number; error?: string } {
  const text = input.trim().replace('%', '')
  if (!/^\d+$/.test(text)) return { error: 'Informe um número inteiro de 0 a 100' }
  const value = Number(text)
  if (value < 0 || value > 100) return { error: 'Informe um número inteiro de 0 a 100' }
  return { value }
}
