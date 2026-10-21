# ChargeGrid · Painel do vendedor (React)

Painel web oficial e **exclusivo para vendedores** (donos e operadores de estações). Ele mostra os dados da operação e permite gerenciá-la: indicadores, gráficos, estações (dados, totem, conectores, potência e tarifas), sessões com exportação, cupons e Insights IA. Substitui a prévia Flet/Pyodide de [`apps/dashboard/`](../dashboard/), que continua no repositório.

Produção: <https://chargegrid-ffive.vercel.app> (apresentação do projeto na raiz; painel em <https://chargegrid-ffive.vercel.app/dashboard>)

## Stack

- Vite 6 + React 18 + TypeScript (strict), react-router 6, Recharts 3. Não há outras dependências de runtime.
- Cliente `fetch` próprio (`src/api/client.ts`): base same-origin `/v1`, `Bearer` automático, **um** refresh em caso de 401 (compartilhado entre requisições simultâneas). Se o refresh falhar, a sessão é encerrada. Uma queda de rede não derruba a sessão.
- Fontes Inter e Barlow Condensed (OFL) hospedadas no próprio site, convertidas para WOFF com subconjunto latino a partir de `apps/mobile/assets/`.
- Tokens visuais do app vendedor (tema escuro de referência): fundo `#1F1F1F`, cartões `#1A1A1A`/`#262626`, botão primário branco com texto preto, vermelho `#D72B32`, receita em verde e energia em azul.

## Páginas

| Rota | Conteúdo |
| --- | --- |
| `/` Visão geral | KPIs (receita bruta estimada, energia entregue, recargas, ticket médio, ocupação, disponibilidade, reservas, não comparecimento), receita e energia por dia (por hora em "Hoje"), mapa de calor dia × hora com horários de pico, alertas recentes e ranking de pontos. A antiga seção "Ao vivo" saiu, como no app (`GET /owner/live` continua na API) |
| `/estacoes` | Lista de estações com status, conectores e faixa de tarifa |
| `/estacoes/:id` | Mesma organização do app do vendedor. **Dados da estação:** nome, endereço, status (ativa/inativa) e o **totem de autoatendimento** (Ligado/Desligado em `kiosk_mode`, salvo na hora e sem atualização otimista) com o status numa linha pelo `kiosk_status` do posto e o Modo apresentação da conta: "Pagamento: Stripe (teste)", "Pagamento simulado (Modo apresentação)" ou o motivo de indisponível. **Conectores e tarifas:** por conector, tarifa, potência, duração máxima e publicação; erros como `point_busy` aparecem ao lado do conector. **Potência** (`GET /stations/{id}/power` a cada 3 s com a aba visível): disponível para os carregadores, limite contratado (o do dono ou o padrão do tipo/porte, `max(75 kW, pico × 1,3)`), loja agora (SIMULADO, pela curva do tipo/porte), carros agora, rebalanceamento Ligado/Desligado (ligado por padrão), tipo e porte do estabelecimento e, por conector, a potência configurada × efetiva. O `PUT /stations/{id}/power-site` leva só o que o dono mudou: o campo do limite fica vazio no padrão e `site_limit_kw` só vai quando ele altera (vazio = `null`, volta ao padrão). **Custo da energia e comissão** (`GET/PUT /stations/{id}/economics`; comissão só leitura), **Taxa de permanência** (`rules.rotation` em `GET/PUT /stations/{id}/pricing`; PUT parcial com só `{ rotation }`) e comodidades. Cada parte some se a API não tiver a rota ou o campo; a tela só muda depois da resposta do servidor. O pagamento é automático (Stripe · teste; simulado em Modo apresentação): os antigos "Energia do estabelecimento" (controle do consumo da loja) e "Pagamentos" (`prepay_required`/`kiosk_payments`) saíram, como no app |
| `/sessoes` | Filtros por status, busca, paginação de 25 itens, detalhe em painel lateral e exportação **CSV** e **JSON** do resultado filtrado (no navegador, no mesmo formato de `/owner/export`). Colunas **Permanência** (`overstay_fee` e `overstay_minutes` de `/owner/sessions`) e **Pagamento** (selo com o `status_label` da API, capturado/devolvido e "teste") aparecem só quando a API envia os campos |
| `/resultado` | **Receita bruta não é lucro** (faixa fixa com a margem de contribuição). Cascata receita bruta → descontos/cupons → (+ permanência) → receita cobrada → − comissão → (− tarifa do provedor) → = repasse → − custo estimado da energia → = margem estimada; efeito do preço dinâmico e dos cupons; custo do kWh por posto; tabela por sessão (50 por página) e **CSV**/**PDF** de `/owner/export/margin.{csv,pdf}` com o período e a estação do topo (baixados como arquivo, nome montado no cliente: `chargegrid-resultado-AAAAMMDD-HHMM[-posto].csv`). Sem custo do kWh, custo e margem aparecem como "—" (nunca zero) com o atalho "Configurar custo" para o cartão do posto (`/estacoes/:id#economics`) |
| `/alertas` | Alertas operacionais por severidade, com link para a estação |
| `/cupons` | Lista, criação (código, descrição, % de desconto, validade e estação opcional) e ativação/desativação |
| `/insights` | Gera `POST /v1/ai/owner-insights` para o período e a estação escolhidos. Mostra quando o resultado veio das regras automáticas, por falta de IA, e trata os erros de limite e de indisponibilidade |

A barra superior traz o período (Hoje, 7 dias, 30 dias ou Personalizado), o filtro de estação, o botão de atualizar e o menu da conta com Sair. No celular, a navegação vai para uma barra inferior e o menu lateral abre como gaveta.

O período segue a mesma regra de `chargegrid_core.analytics.period_bounds`. Os períodos prontos começam à meia-noite de São Paulo e terminam agora. No personalizado, as datas são inclusivas.

## Autenticação e acesso

Telas públicas (mesmo layout: formulário à esquerda e, à direita, o totem sobre o anel de luz do app vendedor; abaixo de 900 px o painel some e uma versão compacta aparece acima do formulário):

| Rota | Conteúdo |
| --- | --- |
| `/entrar` | Login (qualquer outro endereço sem sessão também mostra o login e, depois de entrar, continua no mesmo endereço) |
| `/criar-conta` | Cadastro de vendedor: nome completo, e-mail, senha e confirmação, com a validação do app (nome até 100, senha de 8 a 128) |
| `/verificar-email` | "Verifique seu e-mail", com "Voltar para entrar" e "Reenviar confirmação" (`POST /v1/auth/resend-signup`, mensagem neutra e espera de 60 s) |
| `/esqueci-senha` | `POST /v1/auth/password/forgot` |

O e-mail digitado passa de uma tela para outra pelo estado do router, nunca pela URL.

1. `POST /v1/auth/login`: o access token fica **só em memória** e o refresh token fica no `localStorage` (`chargegrid.owner.refresh`, com todo acesso protegido por try/catch). Se a API responder `email_not_confirmed`, o painel abre "Verifique seu e-mail".
2. `POST /v1/auth/register` com `account_type: "vendor"`. A resposta é tratada como no app: com `access_token` e `refresh_token`, a sessão abre direto; com `requires_email_confirmation`, abre "Verifique seu e-mail"; em qualquer outro caso, volta ao login com o aviso neutro *"Confira seu e-mail. Se já tem uma conta, entre com sua senha."* Os erros (`weak_password`, validação, 429, rede) viram mensagens em português ao lado do campo ou no topo do formulário (`src/auth/signup.ts`).
3. `GET /v1/me` decide o acesso:
   - `operator_enabled` → acesso liberado;
   - `account_type == "vendor"` sem operação habilitada → passo a passo para vincular o primeiro equipamento (instalar o app, escanear o QR do totem, publicar e voltar), com "Já vinculei · Atualizar" (consulta `/me` de novo) e Sair;
   - qualquer outra conta → logout e a mensagem *"Este painel é exclusivo para vendedores. Use o app ChargeGrid como motorista."*
4. Ao recarregar a página, a sessão é retomada com `POST /v1/auth/refresh`.

## Desenvolvimento

```bash
cd apps/owner-web
npm ci
npm run dev        # http://localhost:5199, com proxy de /v1 para a API pública de prévia
npm run dev:mock   # mesmo servidor com dados fictícios (VITE_MOCK=1)
```

**Modo demonstração** (somente `npm run dev`): use `http://localhost:5199/dashboard/?mock_login=1` para entrar direto, ou entre com qualquer e-mail e senha.

| E-mail | Resultado |
| --- | --- |
| e-mail com `motorista` | testa o bloqueio de contas que não são de vendedor |
| e-mail com `pendente` | vendedor sem operação habilitada |
| senha `errada` | erro de credenciais |
| e-mail com `naoconfirmado` | login pede a confirmação do e-mail |

No cadastro (`/criar-conta`): e-mail com `confirmar` → "Verifique seu e-mail"; com `existe` → aviso neutro no login; com `limite` → erro 429 (também no reenvio); senha `senhafraca` → `weak_password`; qualquer outro → a conta entra direto como vendedor sem operação habilitada.

As telas de operação também têm dados fictícios (`src/mock/operations.ts`): Villa Olímpia começa sem custo do kWh (margem "—"; informe o custo no posto e a margem total aparece), o consumo simulado da loja reduz a potência com confirmação do equipamento ~1,2 s depois (excesso transitório visível), CG-002 e CG-006 mostram um carro na vaga após a recarga (tolerância e cobrança), e parte das sessões tem pagamento em teste e taxa de permanência. O Resultado soma o histórico fictício de sessões, por isso não bate exatamente com os totais da visão geral.

Os dados de 7 dias batem com a referência visual: R$ 8.420, 2.184 kWh, 184 recargas e ticket de R$ 45,76. O mock é importado só atrás de `import.meta.env.DEV`, por isso fica fora do build de produção. `npm run check:dist` confirma isso.

Variáveis (opcionais, somente em desenvolvimento; veja `.env.example`):

| Variável | Uso |
| --- | --- |
| `VITE_MOCK=1` | liga o modo demonstração |
| `VITE_API_PROXY` | destino do proxy `/v1` no `dev` e no `preview` (padrão: `https://chargegrid-api-preview-djlima1s-projects.vercel.app`) |

## Qualidade

```bash
npm run lint        # ESLint (typescript-eslint + react-hooks), zero avisos
npm run typecheck   # tsc strict
npm test            # Vitest: formatação, período → query, token/refresh, acesso de vendedor, cadastro, CSV/JSON, cascata/margem, faixa "não é lucro", exportação do resultado com filtros, potência (formatação e debounce), tarifa preservando as regras, mock fechando
npm run build       # tsc + vite build → dist/
npm run check:dist  # garante que nada do modo demonstração foi para dist/
```

## Deploy (Vercel)

O projeto `chargegrid-painel` usa **Root Directory = `apps/owner-web`**. O `vercel.json` define:

- framework `vite`, `npm ci`, `npm run build` e saída em `dist`;
- rewrite de `/v1/:path*` para `https://chargegrid-api-preview-djlima1s-projects.vercel.app/v1/:path*`, para a API ficar same-origin, sem CORS e sem URL no bundle;
- fallback de SPA para `index.html`;
- cache `immutable` de 1 ano em `/assets/*` (arquivos com hash) e `no-cache` no `index.html`;
- CSP `default-src 'self'` (scripts apenas do próprio site, fontes locais, `connect-src 'self'`, `frame-ancestors 'none'`), além de `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy` e `Permissions-Policy`.

```bash
cd apps/owner-web
vercel link --project chargegrid-painel   # uma vez
vercel deploy --prod
```

Em produção não é preciso definir variáveis de ambiente.

## Licenças das fontes

Inter e Barlow Condensed são distribuídas sob a SIL Open Font License 1.1 (`public/fonts/Inter-OFL.txt`; Barlow: © 2017 The Barlow Project Authors).
