import { useEffect, useRef, useState, type FocusEvent } from 'react'
import { reconcileDraft } from './draft'

/** Polling may update metadata; a focused form keeps its values and caret until it is left. */
export function useLiveDraft<T>(initial: T) {
  const [draft, setDraft] = useState(initial)
  const saved = useRef(initial)
  const latest = useRef(initial)
  const focused = useRef(false)
  latest.current = initial

  useEffect(() => {
    if (focused.current) return
    const previous = saved.current
    saved.current = initial
    setDraft((current) => reconcileDraft(current, previous, initial))
  }, [initial])

  const formEvents = {
    onFocusCapture: () => { focused.current = true },
    onBlurCapture: (event: FocusEvent<HTMLElement>) => {
      if (event.relatedTarget && event.currentTarget.contains(event.relatedTarget as Node)) return
      focused.current = false
      const previous = saved.current
      const next = latest.current
      saved.current = next
      setDraft((current) => reconcileDraft(current, previous, next))
    },
  }
  return [draft, setDraft, formEvents] as const
}
