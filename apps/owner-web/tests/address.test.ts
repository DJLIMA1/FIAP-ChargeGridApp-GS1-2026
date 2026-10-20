import { describe, expect, it } from 'vitest'
import { shouldSuggest, suggestionLines } from '../src/lib/address'

const paulista = {
  label: 'Avenida Paulista, 1000, Bela Vista, São Paulo - SP',
  street: 'Avenida Paulista',
  number: '1000',
  district: 'Bela Vista',
  city: 'São Paulo',
  state: 'SP',
  postcode: '01310-100',
  latitude: -23.56,
  longitude: -46.65,
}

describe('autocomplete de endereço', () => {
  it('consulta a partir de 3 letras ou de um CEP completo, nunca o endereço já escolhido', () => {
    expect(shouldSuggest('av', null)).toBe(false)
    expect(shouldSuggest('  av ', null)).toBe(false)
    expect(shouldSuggest('av paulista', null)).toBe(true)
    expect(shouldSuggest('01310-100', null)).toBe(true)
    expect(shouldSuggest(paulista.label, paulista.label)).toBe(false)
  })

  it('separa título (rua e número ou local) e detalhe (bairro, cidade, CEP)', () => {
    expect(suggestionLines(paulista)).toEqual({
      title: 'Avenida Paulista, 1000',
      detail: 'Bela Vista, São Paulo - SP, CEP 01310-100',
    })
    expect(suggestionLines({ ...paulista, place: 'Shopping Exemplo' })).toEqual({
      title: 'Shopping Exemplo',
      detail: 'Avenida Paulista, 1000, Bela Vista, São Paulo - SP, CEP 01310-100',
    })
  })
})
