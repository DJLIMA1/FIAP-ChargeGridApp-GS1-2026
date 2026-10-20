import type { AddressSuggestion } from '../api/types'

/** Espera sem digitação antes de consultar (o servidor também limita 60 buscas/min). */
export const ADDRESS_DEBOUNCE_MS = 350

const cepDigits = (text: string) => text.replace(/[\s.-]/g, '')

/** Consulta a partir de 3 caracteres, ou um CEP completo. */
export function shouldSuggest(text: string, picked: string | null): boolean {
  const query = text.trim()
  if (!query || query === picked) return false
  return query.length >= 3 || /^\d{8}$/.test(cepDigits(query))
}

/** Linha principal (local ou rua + número) e linha de apoio (bairro, cidade - UF, CEP). */
export function suggestionLines(item: AddressSuggestion): { title: string; detail: string } {
  const street = [item.street, item.number].filter(Boolean).join(', ')
  const title = item.place || street || item.label
  const rest = item.place && street ? [street] : []
  if (item.district) rest.push(item.district)
  if (item.city) rest.push(item.state ? `${item.city} - ${item.state}` : item.city)
  if (item.postcode) rest.push(`CEP ${item.postcode}`)
  return { title, detail: rest.join(', ') }
}
