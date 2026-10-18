# ChargeGrid · Painel do vendedor (React)

Painel web oficial e **exclusivo para vendedores** (donos e operadores de estações). Ele mostra os dados da operação e permite gerenciá-la: indicadores, gráficos, status ao vivo dos pontos, estações e tarifas, sessões com exportação, cupons e Insights IA. Substitui a prévia Flet/Pyodide de [`apps/dashboard/`](../dashboard/), que continua no repositório.

Produção: <https://chargegrid-painel.vercel.app>

## Stack

- Vite 6 + React 18 + TypeScript (strict), react-router 6, Recharts 3. Não há outras dependências de runtime.
- Cliente `fetch` próprio (`src/api/client.ts`): base same-origin `/v1`, `Bearer` automático, **um** refresh em caso de 401 (compartilhado entre requisições simultâneas). Se o refresh falhar, a sessão é encerrada. Uma queda de rede não derruba a sessão.
- Fontes Inter e Barlow Condensed (OFL) hospedadas no próprio site, convertidas para WOFF com subconjunto latino a partir de `apps/mobile/assets/`.
- Tokens visuais do app vendedor (tema escuro de referência): fundo `#1F1F1F`, cartões `#1A1A1A`/`#262626`, botão primário branco com texto preto, vermelho `#D72B32`, receita em verde e energia em azul.

## Páginas

| Rota | Conteúdo |
| --- | --- |
| `/` Visão geral | KPIs (receita estimada, energia entregue, recargas, ticket médio, ocupação, disponibilidade, reservas, não comparecimento), receita e energia por dia (por hora em "Hoje"), mapa de calor dia × hora com horários de pico, alertas recentes, ranking de pontos e status ao vivo (`/owner/live`, atualizado a cada 30 s com a aba visível) |
| `/estacoes` | Lista de estações com status, conectores e faixa de tarifa |
| `/estacoes/:id` | Nome, endereço e status (ativa/inativa); por conector, tarifa, potência, duração máxima e publicação; comodidades. Os campos são validados com os limites da API, e a tela só muda depois da resposta do servidor (sem atualização otimista). Erros como `point_busy` aparecem ao lado do conector |
| `/sessoes` | Filtros por status, busca, paginação de 25 itens, detalhe em painel lateral e exportação **CSV** e **JSON** do resultado filtrado (no navegador, no mesmo formato de `/owner/export`) |
| `/alertas` | Alertas operacionais por severidade, com link para a estação |
| `/cupons` | Lista, criação (código, descrição, % de desconto, validade e estação opcional) e ativação/desativação |
| `/insights` | Gera `POST /v1/ai/owner-insights` para o período e a estação escolhidos. Mostra quando o resultado veio das regras automáticas, por falta de IA, e trata os erros de limite e de indisponibilidade |

A barra superior traz o período (Hoje, 7 dias, 30 dias ou Personalizado), o filtro de estação, o botão de atualizar e o menu da conta com Sair. No celular, a navegação vai para uma barra inferior e o menu lateral abre como gaveta.

O período segue a mesma regra de `chargegrid_core.analytics.period_bounds`. Os períodos prontos começam à meia-noite de São Paulo e terminam agora. No personalizado, as datas são inclusivas.

## Autenticação e acesso

1. `POST /v1/auth/login`: o access token fica **só em memória** e o refresh token fica no `localStorage` (`chargegrid.owner.refresh`, com todo acesso protegido por try/catch).
2. `GET /v1/me` decide o acesso:
   - `operator_enabled` → acesso liberado;
   - `account_type == "vendor"` sem operação habilitada → orientação para vincular o primeiro equipamento pelo app, com botão Sair;
   - qualquer outra conta → logout e a mensagem *"Este painel é exclusivo para vendedores. Use o app ChargeGrid como motorista."*
3. Ao recarregar a página, a sessão é retomada com `POST /v1/auth/refresh`. O link "Esqueci minha senha" chama `POST /v1/auth/password/forgot`.

## Desenvolvimento

```bash
cd apps/owner-web
npm ci
npm run dev        # http://localhost:5199, com proxy de /v1 para a API pública de prévia
npm run dev:mock   # mesmo servidor com dados fictícios (VITE_MOCK=1)
```

**Modo demonstração** (somente `npm run dev`): use `http://localhost:5199/?mock_login=1` para entrar direto, ou entre com qualquer e-mail e senha.

| E-mail | Resultado |
| --- | --- |
| e-mail com `motorista` | testa o bloqueio de contas que não são de vendedor |
| e-mail com `pendente` | vendedor sem operação habilitada |
| senha `errada` | erro de credenciais |

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
npm test            # Vitest: formatação, período → query, token/refresh, acesso de vendedor, CSV/JSON
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
