import { forwardRef, useState, type InputHTMLAttributes, type ReactNode } from 'react'
import car from '../assets/car.webp'
import totem from '../assets/totem.webp'
import { Icon } from './Icon'
import { Logo } from './ui'

/**
 * Lado direito das telas de acesso: o totem sobre o anel de luz vermelha,
 * como na tela inicial do app vendedor, com o carro ao fundo e um único
 * indicador "ao vivo" ancorado no ponto. Puramente decorativo (aria-hidden).
 */
export function AuthVisual() {
  return (
    <aside className="auth-visual" aria-hidden>
      <div className="av-stage">
        <div className="av-floor" />
        <div className="av-ring av-ring-outer" />
        <div className="av-car-shadow" />
        <img className="av-car" src={car} alt="" width={760} height={457} decoding="async" />
        <div className="av-ring av-ring-inner" />
        <div className="av-shadow" />
        <img className="av-totem" src={totem} alt="" width={279} height={660} decoding="async" />
        <div className="av-chip">
          <span className="av-chip-head">
            <span className="av-live" />
            Ponto CG-001
          </span>
          <span className="av-chip-value">
            <span className="av-charging">Carregando</span> · 51 kW
          </span>
        </div>
      </div>
      <div className="av-copy">
        <p className="av-title">Sua operação de recarga, em um só painel.</p>
        <p className="av-sub">Receita, energia e o status de cada ponto ao vivo, com os mesmos dados do app ChargeGrid.</p>
      </div>
    </aside>
  )
}

/** Versão compacta (só no celular, onde o painel lateral some): o totem sobre o anel. */
function AuthMiniVisual() {
  return (
    <div className="auth-mini" aria-hidden>
      <div className="av-stage">
        <div className="av-floor" />
        <div className="av-ring av-ring-outer" />
        <div className="av-ring av-ring-inner" />
        <div className="av-shadow" />
        <img className="av-totem" src={totem} alt="" width={279} height={660} decoding="async" />
      </div>
    </div>
  )
}

/** Moldura comum das telas de acesso: formulário à esquerda, visual à direita. */
export function AuthShell({ children, wide, compactHero = true }: { children: ReactNode; wide?: boolean; compactHero?: boolean }) {
  return (
    <div className="auth">
      <main className="auth-panel">
        <div className={`auth-form${wide ? ' wide' : ''}`}>
          <Logo height={26} />
          {compactHero ? <AuthMiniVisual /> : null}
          {children}
        </div>
      </main>
      <AuthVisual />
    </div>
  )
}

type PasswordInputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'type' | 'onChange' | 'value'> & { value: string; onChange(value: string): void }

/** Campo de senha com mostrar/ocultar, igual ao do login. */
export const PasswordInput = forwardRef<HTMLInputElement, PasswordInputProps>(function PasswordInput({ value, onChange, ...rest }, ref) {
  const [show, setShow] = useState(false)
  return (
    <div className="pw-wrap">
      <input {...rest} ref={ref} className="input input-big" type={show ? 'text' : 'password'} value={value} onChange={(e) => onChange(e.target.value)} />
      <button type="button" className="pw-toggle" onClick={() => setShow((v) => !v)} aria-label={show ? 'Ocultar senha' : 'Mostrar senha'} aria-pressed={show}>
        <Icon name={show ? 'eyeOff' : 'eye'} size={19} />
      </button>
    </div>
  )
})
