import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from 'react'
import { Icon } from './Icon'

interface ToastItem {
  id: number
  message: string
  tone: 'ok' | 'error'
}

const ToastContext = createContext<(message: string, tone?: 'ok' | 'error') => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const push = useCallback((message: string, tone: 'ok' | 'error' = 'ok') => {
    const id = Date.now() + Math.random()
    setItems((list) => [...list.slice(-2), { id, message, tone }])
    setTimeout(() => setItems((list) => list.filter((item) => item.id !== id)), tone === 'error' ? 6000 : 3200)
  }, [])
  const value = useMemo(() => push, [push])
  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite">
        {items.map((item) => (
          <div key={item.id} className={`toast ${item.tone === 'error' ? 'error' : ''}`} role={item.tone === 'error' ? 'alert' : 'status'}>
            <Icon name={item.tone === 'error' ? 'alert' : 'check'} size={18} />
            {item.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  return useContext(ToastContext)
}
