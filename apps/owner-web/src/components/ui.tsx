import { useEffect, useId, useRef, type CSSProperties, type ReactNode } from 'react'
import type { ApiError } from '../api/client'
import type { Tone } from '../lib/labels'
import { Icon, type IconName } from './Icon'
import wordmark from './wordmark.svg'

export function Logo({ height = 22 }: { height?: number }) {
  return <img src={wordmark} alt="ChargeGrid" height={height} width={Math.round((height * 101) / 21)} style={{ display: 'block' }} />
}

export function Card({ title, sub, action, children, className = '', id }: { title?: ReactNode; sub?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; id?: string }) {
  return (
    <section className={`card ${className}`} aria-labelledby={title && id ? `${id}-t` : undefined}>
      {title || action ? (
        <div className="card-head">
          <div>
            {title ? (
              <h2 className="card-title" id={id ? `${id}-t` : undefined}>
                {title}
              </h2>
            ) : null}
            {sub ? <p className="card-sub">{sub}</p> : null}
          </div>
          {action}
        </div>
      ) : null}
      {children}
    </section>
  )
}

export function Kpi({ label, value, hint, hintTone, icon, variant, loading }: { label: string; value: ReactNode; hint?: ReactNode; hintTone?: 'good' | 'bad'; icon?: IconName; variant?: 'hero' | 'small'; loading?: boolean }) {
  return (
    <div className={`card kpi ${variant ?? ''}`}>
      {icon ? (
        <span className="kpi-tile" aria-hidden>
          <Icon name={icon} size={18} />
        </span>
      ) : null}
      <span className="kpi-label">{label}</span>
      {loading ? <Skeleton width="60%" height={variant === 'small' ? 30 : 40} /> : <span className="kpi-value">{value}</span>}
      {loading ? <Skeleton width="40%" height={12} /> : hint ? <span className={`kpi-hint ${hintTone ?? ''}`}>{hint}</span> : null}
    </div>
  )
}

export function Skeleton({ width = '100%', height = 16, radius = 8, style }: { width?: number | string; height?: number | string; radius?: number; style?: CSSProperties }) {
  return <span className="skeleton" style={{ display: 'block', width, height, borderRadius: radius, ...style }} aria-hidden />
}

export function SkeletonRows({ rows = 4, height = 18 }: { rows?: number; height?: number }) {
  return (
    <div className="stack" style={{ gap: 14 }} aria-busy="true" aria-label="Carregando">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} height={height} width={`${92 - ((i * 13) % 30)}%`} />
      ))}
    </div>
  )
}

export function ErrorBanner({ error, onRetry, title = 'Não foi possível carregar' }: { error: ApiError | string | null; onRetry?: () => void; title?: string }) {
  if (!error) return null
  const message = typeof error === 'string' ? error : error.message
  return (
    <div className="banner" role="alert">
      <Icon name="alert" size={20} />
      <div className="grow">
        <b>{title}</b>
        {message}
      </div>
      {onRetry ? (
        <button type="button" className="btn btn-secondary" style={{ height: 34 }} onClick={onRetry}>
          Tentar novamente
        </button>
      ) : null}
    </div>
  )
}

export function Banner({ tone = 'info', icon = 'info', title, children }: { tone?: 'info' | 'ok' | 'error'; icon?: IconName; title?: string; children: ReactNode }) {
  return (
    <div className={`banner ${tone === 'error' ? '' : tone}`} role={tone === 'error' ? 'alert' : 'status'}>
      <Icon name={icon} size={20} />
      <div className="grow">
        {title ? <b>{title}</b> : null}
        {children}
      </div>
    </div>
  )
}

export function EmptyState({ icon = 'info', title, children, action }: { icon?: IconName; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="empty">
      <span className="tile">
        <Icon name={icon} size={24} />
      </span>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
      {action}
    </div>
  )
}

export function Badge({ tone, children, plain }: { tone: Tone | 'solid-green'; children: ReactNode; plain?: boolean }) {
  return <span className={`badge ${tone} ${plain ? 'plain' : ''}`}>{children}</span>
}

/** Foco no diálogo, Esc fecha, rolagem da página travada; ao fechar, o foco volta para quem abriu. */
function useModal(onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null)
  const closeRef = useRef(onClose)
  closeRef.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.focus()
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeRef.current()
    }
    document.addEventListener('keydown', onKey)
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = overflow
      previous?.focus?.()
    }
  }, [])
  return ref
}

export function Drawer({ title, onClose, children, footer }: { title: ReactNode; onClose(): void; children: ReactNode; footer?: ReactNode }) {
  const ref = useModal(onClose)
  const titleId = useId()
  return (
    <>
      <div className="overlay" onClick={onClose} aria-hidden />
      <div className="drawer" role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1} ref={ref}>
        <div className="drawer-head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="icon-btn" onClick={onClose} aria-label="Fechar">
            <Icon name="close" size={18} />
          </button>
        </div>
        <div className="drawer-body">{children}</div>
        {footer ? <div className="drawer-foot">{footer}</div> : null}
      </div>
    </>
  )
}

/**
 * Confirmação de uma ação (ex.: "Remover carregador 3?"): Cancelar e o botão da ação (`danger` =
 * destrutiva). Enquanto `busy`, não fecha (Esc/fundo/Cancelar) e o botão mostra `busyLabel`.
 */
export function ConfirmDialog({
  title,
  children,
  confirmLabel,
  busyLabel,
  busy = false,
  danger = false,
  error,
  errorTitle,
  onConfirm,
  onCancel,
}: {
  title: ReactNode
  children?: ReactNode
  confirmLabel: string
  busyLabel?: string
  busy?: boolean
  danger?: boolean
  error?: string | null
  errorTitle?: string
  onConfirm(): void
  onCancel(): void
}) {
  const cancel = () => {
    if (!busy) onCancel()
  }
  const ref = useModal(cancel)
  const titleId = useId()
  const bodyId = useId()
  return (
    <>
      <div className="overlay" onClick={cancel} aria-hidden />
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={children ? bodyId : undefined} tabIndex={-1} ref={ref} data-testid="confirm-dialog">
        <h2 id={titleId}>{title}</h2>
        {children ? <div id={bodyId} className="muted">{children}</div> : null}
        {error ? <ErrorBanner error={error} title={errorTitle} /> : null}
        <div className="dialog-foot">
          <button type="button" className="btn btn-ghost" disabled={busy} onClick={cancel}>
            Cancelar
          </button>
          <button type="button" className={`btn ${danger ? 'btn-danger' : 'btn-primary'}`} disabled={busy} onClick={onConfirm}>
            {busy && busyLabel ? busyLabel : confirmLabel}
          </button>
        </div>
      </div>
    </>
  )
}

export function Switch({ checked, onChange, label, disabled }: { checked: boolean; onChange(value: boolean): void; label: ReactNode; disabled?: boolean }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
      <span className="track" aria-hidden />
      <span>{label}</span>
    </label>
  )
}

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string | null; children: ReactNode }) {
  return (
    <label className="field">
      <span>
        {label} {hint ? <span className="hint">· {hint}</span> : null}
      </span>
      {children}
      {error ? <span className="error">{error}</span> : null}
    </label>
  )
}

/** Como `Field`, mas sem `<label>`: para botões (um clique no texto não aciona o primeiro botão). */
export function FieldGroup({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="field" role="group" aria-label={label}>
      <span>{label}</span>
      {children}
    </div>
  )
}

export function PageHead({ title, sub, actions, back }: { title: string; sub?: ReactNode; actions?: ReactNode; back?: ReactNode }) {
  return (
    <div>
      {back}
      <div className="page-head">
        <div>
          <h1 className="page-title">{title}</h1>
          {sub ? <p className="page-sub">{sub}</p> : null}
        </div>
        {actions ? <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>{actions}</div> : null}
      </div>
    </div>
  )
}
