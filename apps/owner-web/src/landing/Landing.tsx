import { useEffect } from 'react'
import car from '../assets/car.webp'
import totem from '../assets/totem.webp'
import { Icon, type IconName } from '../components/Icon'
import { Logo } from '../components/ui'
import dashboardShot from './img/dashboard-visao-geral.webp'
import insightsShot from './img/dashboard-insights-ia.webp'
import panelShot from './img/painel-esp32-framebuffer.webp'
import './landing.css'

/** Endereço do painel do vendedor (o app React roda sob este prefixo). */
const DASHBOARD = '/dashboard'

const AUDIENCES: { icon: IconName; title: string; text: string }[] = [
  {
    icon: 'user',
    title: 'Para quem dirige',
    text: 'Encontra pontos por conector, tarifa, disponibilidade e distância, reserva, acompanha a recarga em etapas e recebe um recibo que explica cada valor.',
  },
  {
    icon: 'station',
    title: 'Para quem vende energia',
    text: 'Cadastra postos, tarifas e comodidades, vê receita, energia, ocupação e margem por sessão, e recebe alertas e recomendações de preço e operação.',
  },
  {
    icon: 'plug',
    title: 'No ponto de recarga',
    text: 'Um totem ESP32-S3 com tela touch recebe os comandos, confirma cada um (ACK) e encerra a sessão localmente se perder a comunicação.',
  },
]

const STEPS = [
  ['Escolha do ponto', 'O motorista compara os pontos e reserva pelo app.'],
  ['Reserva validada', 'A API aplica as regras e registra a reserva.'],
  ['Confirmação no totem', 'O ESP32 recebe o comando RESERVE e confirma.'],
  ['Início autorizado', 'A API só autoriza o START depois da confirmação do ponto.'],
  ['Recarga ao vivo', 'Potência, energia e custo aparecem no app, no painel e no totem.'],
  ['Encerramento', 'A parada vem do app, de um limite ou do próprio totem, e a sessão é reconciliada.'],
] as const

const COMPONENTS: { icon: IconName; title: string; stack: string; text: string }[] = [
  { icon: 'phone', title: 'Aplicativo', stack: 'Flet · Python', text: 'Busca (também em linguagem natural), reserva, recarga, histórico e assistente com IA.' },
  { icon: 'chart', title: 'Painel do vendedor', stack: 'React · TypeScript', text: 'KPIs, gráficos, potência e totem de cada posto, sessões, cupons, previsão e Insights IA.' },
  { icon: 'zap', title: 'API', stack: 'FastAPI · PostgreSQL', text: 'Única camada com acesso ao banco: autenticação, permissões, regras de recarga e comandos.' },
  { icon: 'power', title: 'Totem físico', stack: 'ESP32-S3 · LVGL', text: 'Interface touch, sincronização HTTPS, confirmação de comandos e parada local.' },
  { icon: 'sparkles', title: 'Inteligência artificial', stack: 'OpenRouter', text: 'Chat e insights com ferramentas somente leitura; sem chave, regras determinísticas assumem.' },
]

const FEATURES: { icon: IconName; title: string; text: string }[] = [
  { icon: 'gauge', title: 'Status ao vivo', text: 'Cada ponto com potência, energia e estado em tempo real.' },
  { icon: 'wallet', title: 'Margem por sessão', text: 'Receita, custo da energia, comissão e margem, com exportação.' },
  { icon: 'trendUp', title: 'Previsão de ocupação', text: 'Picos por dia e hora e o melhor horário para recarregar.' },
  { icon: 'clock', title: 'Tempo excedente', text: 'Aviso quando a bateria enche e o carro segue conectado, com tolerância e taxa.' },
  { icon: 'sparkles', title: 'Insights IA', text: 'Recomendações de preço e operação a partir dos dados do posto.' },
  { icon: 'ticket', title: 'Cupons e alertas', text: 'Campanhas de desconto e alertas de falha, ociosidade e não comparecimento.' },
]

const TECH = ['React', 'TypeScript', 'Flet', 'FastAPI', 'PostgreSQL', 'Supabase Auth', 'ESP32-S3', 'LVGL', 'OpenRouter', 'Stripe', 'Vercel']

export default function Landing() {
  useEffect(() => {
    document.title = 'ChargeGrid · Recarga com confirmação, do app ao ponto'
  }, [])

  return (
    <div className="lp">
      <header className="lp-header">
        <div className="lp-wrap lp-header-row">
          <a href="/" className="lp-brand" aria-label="ChargeGrid — início">
            <Logo height={22} />
          </a>
          <nav className="lp-nav" aria-label="Seções">
            <a href="#projeto">Projeto</a>
            <a href="#como-funciona">Como funciona</a>
            <a href="#componentes">Componentes</a>
            <a href="#painel">Painel</a>
          </nav>
          <a className="btn btn-primary lp-cta-sm" href={DASHBOARD}>
            Acessar painel
          </a>
        </div>
      </header>

      <main>
        <section className="lp-hero">
          <div className="lp-wrap lp-hero-grid">
            <div className="lp-hero-copy">
              <p className="lp-eyebrow">FIAP · Global Solution 2026 · Equipe FFIVE</p>
              <h1>
                Recarga com confirmação, <span className="lp-accent">do app ao ponto.</span>
              </h1>
              <p className="lp-lead">
                O ChargeGrid integra aplicativo, painel web, API e um totem físico ESP32 para mostrar como a gestão de
                eletropostos pode ser simples para quem dirige e transparente para quem vende energia.
              </p>
              <div className="lp-actions">
                <a className="btn btn-primary lp-btn" href={DASHBOARD}>
                  Acessar painel do vendedor
                  <Icon name="chevronRight" size={18} />
                </a>
                <a className="btn btn-secondary lp-btn" href="#como-funciona">
                  Como funciona
                </a>
              </div>
              <p className="lp-note">O painel é exclusivo para contas de vendedor.</p>
            </div>
            <div className="lp-hero-visual" aria-hidden>
              <div className="lp-glow" />
              <img className="lp-car" src={car} alt="" width={760} height={457} decoding="async" />
              <img className="lp-totem" src={totem} alt="" width={279} height={660} decoding="async" />
              <div className="lp-chip">
                <span className="lp-chip-head">
                  <span className="lp-live" />
                  Ponto CG-001
                </span>
                <span className="lp-chip-value">
                  <span className="green">Carregando</span> · 51 kW
                </span>
              </div>
            </div>
          </div>
        </section>

        <section id="projeto" className="lp-section">
          <div className="lp-wrap">
            <p className="lp-kicker">O projeto</p>
            <h2>Um sistema, três pontas da recarga</h2>
            <p className="lp-section-lead">
              A expansão dos carros elétricos depende de pontos fáceis de achar, de usar e de administrar. O ChargeGrid
              liga essas três pontas com a mesma conta e a mesma API: a mesma pessoa pode recarregar e, depois de vincular
              um equipamento próprio, operar o ponto.
            </p>
            <div className="lp-grid lp-grid-3">
              {AUDIENCES.map((item) => (
                <article key={item.title} className="lp-card">
                  <span className="lp-icon">
                    <Icon name={item.icon} size={22} />
                  </span>
                  <h3>{item.title}</h3>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
          </div>
        </section>

        <section id="como-funciona" className="lp-section lp-section-alt">
          <div className="lp-wrap">
            <p className="lp-kicker">Como funciona</p>
            <h2>Nada acontece sem a confirmação do ponto</h2>
            <p className="lp-section-lead">
              O sistema só considera uma ação aplicada depois que o totem confirma. O vendedor vincula o equipamento por um
              QR privado; o motorista usa um código público diferente para iniciar a recarga.
            </p>
            <ol className="lp-steps">
              {STEPS.map(([title, text], index) => (
                <li key={title} className="lp-step">
                  <span className="lp-step-n num">{String(index + 1).padStart(2, '0')}</span>
                  <div>
                    <h3>{title}</h3>
                    <p>{text}</p>
                  </div>
                </li>
              ))}
            </ol>
            <div className="lp-facts">
              <div><span className="num">5 s</span>sincronização durante a recarga</div>
              <div><span className="num">10 s</span>sincronização fora dela</div>
              <div><span className="num">45 s</span>sem comunicação encerra a sessão no totem</div>
            </div>
          </div>
        </section>

        <section id="componentes" className="lp-section">
          <div className="lp-wrap">
            <p className="lp-kicker">Componentes</p>
            <h2>O que foi construído</h2>
            <div className="lp-grid lp-grid-5">
              {COMPONENTS.map((item) => (
                <article key={item.title} className="lp-card">
                  <span className="lp-icon">
                    <Icon name={item.icon} size={22} />
                  </span>
                  <h3>{item.title}</h3>
                  <p className="lp-stack">{item.stack}</p>
                  <p>{item.text}</p>
                </article>
              ))}
            </div>
            <figure className="lp-panel-shot">
              <img src={panelShot} alt="Tela do totem ESP32 mostrando um ponto disponível" width={400} height={240} loading="lazy" decoding="async" />
              <figcaption>Tela capturada do totem físico (ESP32-S3 com LCD touch).</figcaption>
            </figure>
          </div>
        </section>

        <section id="painel" className="lp-section lp-section-alt">
          <div className="lp-wrap">
            <p className="lp-kicker">Painel do vendedor</p>
            <h2>A operação inteira em uma tela</h2>
            <p className="lp-section-lead">
              Receita, energia, ocupação, disponibilidade e não comparecimento por período e por estação, com os mesmos dados
              que o app e o totem usam.
            </p>
            <figure className="lp-shot">
              <img src={dashboardShot} alt="Visão geral do painel com KPIs, receita e energia por dia, mapa de calor e ranking" width={1440} height={900} loading="lazy" decoding="async" />
            </figure>
            <div className="lp-grid lp-grid-3 lp-features">
              {FEATURES.map((item) => (
                <div key={item.title} className="lp-feature">
                  <Icon name={item.icon} size={20} />
                  <div>
                    <h3>{item.title}</h3>
                    <p>{item.text}</p>
                  </div>
                </div>
              ))}
            </div>
            <figure className="lp-shot lp-shot-sm">
              <img src={insightsShot} alt="Tela de Insights IA com recomendações de preço e operação" width={1440} height={900} loading="lazy" decoding="async" />
              <figcaption>Insights IA: recomendações geradas a partir dos dados do posto.</figcaption>
            </figure>
          </div>
        </section>

        <section className="lp-section">
          <div className="lp-wrap lp-scope">
            <div>
              <p className="lp-kicker">Escopo do protótipo</p>
              <h2>Como o protótipo funciona</h2>
              <p className="lp-section-lead">
                Reservas, comandos, confirmações e histórico passam pelo sistema integrado e pelo totem físico. Potência,
                energia e estado da bateria vêm da bancada do protótipo, que não mede um veículo nem aciona um carregador de
                potência.
              </p>
            </div>
            <ul className="lp-tech" aria-label="Tecnologias">
              {TECH.map((name) => (
                <li key={name}>{name}</li>
              ))}
            </ul>
          </div>
        </section>

        <section className="lp-final">
          <div className="lp-wrap lp-final-box">
            <h2>Conheça o painel do vendedor</h2>
            <p>Entre com uma conta de vendedor para ver estações, sessões, resultados e previsões.</p>
            <a className="btn btn-primary lp-btn" href={DASHBOARD}>
              Acessar painel
              <Icon name="chevronRight" size={18} />
            </a>
          </div>
        </section>
      </main>

      <footer className="lp-footer">
        <div className="lp-wrap lp-footer-row">
          <Logo height={18} />
          <span>Protótipo acadêmico da equipe FFIVE · FIAP 2026</span>
        </div>
      </footer>
    </div>
  )
}
