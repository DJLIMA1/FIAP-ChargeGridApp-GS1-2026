import { useEffect, useId, useRef, useState, type KeyboardEvent } from 'react'
import type { AddressSuggestion } from '../api/types'
import { useAuth } from '../auth/AuthContext'
import { ADDRESS_DEBOUNCE_MS, shouldSuggest, suggestionLines } from '../lib/address'

/**
 * Campo de endereço com sugestões da API própria (Photon/OpenStreetMap e ViaCEP, sem chave).
 * Combobox acessível: ↑/↓ navegam, Enter escolhe, Esc fecha. Sem rede ou sem resultado, a lista
 * não aparece e o texto digitado continua valendo.
 */
export function AddressAutocomplete({
  value,
  onChange,
  onPick,
  invalid,
  saved,
}: {
  value: string
  /** Endereço já salvo: não é pesquisado de novo (ex.: ao descartar alterações). */
  saved?: string
  onChange(next: string): void
  onPick(item: AddressSuggestion): void
  invalid?: boolean
}) {
  const { ep } = useAuth()
  const listId = useId()
  const [items, setItems] = useState<AddressSuggestion[]>([])
  const [attribution, setAttribution] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(-1)
  const picked = useRef<string | null>(value)

  useEffect(() => {
    if (!shouldSuggest(value, picked.current) || value.trim() === saved?.trim()) {
      setOpen(false)
      return
    }
    const controller = new AbortController()
    const timer = window.setTimeout(async () => {
      try {
        const result = await ep.addressSuggestions(value.trim(), controller.signal)
        setItems(result.items.slice(0, 5))
        setAttribution(result.attribution)
        setActive(-1)
        setOpen(result.items.length > 0)
      } catch {
        if (!controller.signal.aborted) setOpen(false)
      }
    }, ADDRESS_DEBOUNCE_MS)
    return () => {
      window.clearTimeout(timer)
      controller.abort() // resposta de uma busca antiga nunca sobrescreve a atual
    }
  }, [value, saved, ep])

  const choose = (item: AddressSuggestion) => {
    picked.current = item.label
    setOpen(false)
    onChange(item.label)
    onPick(item)
  }

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open) return
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      const step = event.key === 'ArrowDown' ? 1 : -1
      setActive((current) => (current + step + items.length) % items.length)
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault()
      choose(items[active])
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return (
    <div className="autocomplete">
      <input
        className="input input-big"
        value={value}
        maxLength={300}
        placeholder="Digite a rua e o número ou um CEP"
        autoComplete="off"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listId}
        aria-activedescendant={open && active >= 0 ? `${listId}-${active}` : undefined}
        aria-invalid={Boolean(invalid)}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={onKeyDown}
        onBlur={() => setOpen(false)}
      />
      {open ? (
        <div className="autocomplete-menu">
          <ul id={listId} role="listbox" aria-label="Sugestões de endereço">
            {items.map((item, index) => {
              const { title, detail } = suggestionLines(item)
              return (
                <li
                  key={item.label}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={index === active}
                  // mousedown antes do blur do campo: a escolha não se perde ao fechar a lista
                  onMouseDown={(e) => {
                    e.preventDefault()
                    choose(item)
                  }}
                  onMouseEnter={() => setActive(index)}
                >
                  <span className="autocomplete-title">{title}</span>
                  {detail ? <span className="autocomplete-detail">{detail}</span> : null}
                </li>
              )
            })}
          </ul>
          {attribution ? <div className="autocomplete-note">{attribution}</div> : null}
        </div>
      ) : null}
    </div>
  )
}
