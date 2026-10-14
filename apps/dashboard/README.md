# Dashboard web do proprietário

Painel em **Flet web** para donos e operadores de postos acompanharem receita, energia, ocupação,
disponibilidade e alertas, gerenciarem postos/pontos, tarifas, comodidades e cupons e exportarem
sessões e reservas. Usa a **mesma conta do app** e a mesma API.

## O que é compartilhado com o app

| Do app (`apps/mobile/src/chargegrid_app`) | Uso no dashboard |
| --- | --- |
| `ui/theme.py`, `ui/components.py`, fontes Barlow e ícone (`apps/mobile/assets`) | identidade visual, temas claro/escuro |
| `screens/auth.py` | tela de login completa (entrar, criar conta, recuperar senha, conta demo) |
| `api_client.ApiClient`, `session.Session`, `owner_api.OwnerApiMixin` | chamadas autenticadas, refresh de token, downloads |
| `demo.DemoApi` + `demo_owner.py` | modo demo completo, sem rede |
| `screens/operator.py` (`station_form`, `connector_form`) e `screens/coupons.py` (`form`) | edição de posto, ponto/dispositivo e cupons |
| `ui/kpi.py`, `ui/charts.py`, `ui/tables.py` (novos, também usados na tela de operador do app) | cartões KPI, gráficos, mapa de calor, tabela, paginação, seletor de período, badge de status |
| `chargegrid_core.analytics` / `formatting` / `driver` | indicadores, séries, CSV, formatação pt-BR, tipos de comodidade |

O `main.py` acrescenta `apps/mobile/src` ao `sys.path`; não há cópia de código.

## Executar localmente

Na raiz do repositório, com o venv do app (`flet==1.0.0`, `httpx`):

```bash
# Conta demo (demo@chargegrid.example / demo1234), sem API
CHARGEGRID_ENABLE_DEMO=1 .venv/bin/flet run --web -p 8610 apps/dashboard/main.py

# Contra a API: o mesmo CHARGEGRID_API_URL do app (variável ou .env da raiz)
CHARGEGRID_API_URL=http://localhost:8000/v1 .venv/bin/flet run --web -p 8610 apps/dashboard/main.py
```

Abra `http://localhost:8610`. Os assets (fontes Barlow, `icon.png`) vêm de `apps/mobile/assets`
(ou de `apps/dashboard/assets`, se existir, para builds empacotados). A preferência de tema fica em
`dashboard-preferences.json` no armazenamento do Flet (`FLET_APP_STORAGE_DATA`), separada da do app.

Somente contas com `operator_enabled` entram no painel. Motoristas veem um aviso de acesso restrito;
vendedores ainda sem equipamento são orientados a vincular o primeiro ponto pelo app (QR).

## Seções

- **Visão geral**: 8 KPIs (receita estimada, energia, sessões, ticket médio, ocupação, disponibilidade,
  reservas, não comparecimento), receita e energia por dia/hora, mapa de calor dia × hora com horários de
  pico, ranking de pontos e alertas (offline, falha no equipamento, falhas de comando, ponto parado,
  ponto sem dispositivo). Atualiza a cada 30 s.
- **Postos e pontos**: status ao vivo (a cada 15 s) com sessão ativa (kWh, kW, valor), publicar/despublicar
  posto e ponto, editar tarifa, **comodidades** do posto (Modo Motorista), formulário completo do posto e do
  ponto/dispositivo (provisionar, rotacionar chave, revogar, restaurar) reaproveitado do app.
- **Sessões e reservas**: abas, filtro por status, busca, paginação e exportação **CSV/JSON**.
- **Cupons**: tabela, ativar/desativar e criação/edição com o formulário do app.
- **Insights IA**: chama `POST /v1/ai/owner-insights` sob demanda; 404/erro mostram estado vazio.
  Na demo, usa a IA real quando `OPENROUTER_API_KEY` está no processo e regras locais sem ela; o rodapé
  informa a origem ("Gerado por IA (modelo)" ou "Gerado por regras do ChargeGrid").

Cabeçalho: período (hoje / 7 dias / 30 dias / personalizado), posto, atualizar agora, tema claro/escuro e
conta. Menu lateral recolhível; abaixo de 1100 px ele fica só com ícones (tablets e telas de 1024 px), para as tabelas caberem inteiras.

## Testes

```bash
cd apps/dashboard && ../../.venv/bin/python -m pytest tests -q
../../.venv/bin/ruff check .
```

## Site estático (Vercel, sem servidor Python)

`flet build web` gera um site estático: o Python roda **no navegador** (Pyodide 3.14, empacotado junto,
sem CDN). Não há processo Python no servidor; a Vercel só serve arquivos e faz proxy da API.

### Gerar o build

Na raiz do repositório, com o venv do app (Flet 1.0 e Flutter 3.44.8 em cache):

```bash
.venv/bin/python tools/build_dashboard_web.py
```

O script (`tools/build_dashboard_web.py`):

1. monta `apps/dashboard/build/web-src` com `main.py`, `chargegrid_dashboard/`, `src/chargegrid_app`,
   `src/chargegrid_core` e só os assets do painel (fontes Barlow, ícone, marca, `figma/`);
   **remove `demo_ai.py`** (prévia de IA que fala com o OpenRouter), `.env*` e `app_config.json`;
2. grava `dashboard_config.json` na raiz do pacote Python com `{"demo": true}` — só o build do dashboard
   liga a conta demo; o APK do app continua com a demo desligada;
3. roda `flet build web --base-url / --route-url-strategy hash --no-cdn` (≈ 40 s com cache);
4. confere o `assets/app/app.zip`: falha se encontrar `demo_ai`, `.env`, `OPENROUTER_API_KEY`,
   `sk-or-`, `DATABASE_URL=` ou se faltar `dashboard_config.json`;
5. prepara **`apps/dashboard/build/vercel/`**: `vercel.json` (cópia de `apps/dashboard/vercel.json`) +
   `public/` (o site, sem símbolos de depuração). Um vínculo `.vercel/` existente é preservado.

Opções: `--no-demo` (sem o botão "Entrar na conta demo"), `--api-url https://.../v1` (API em outra
origem; exige CORS), `--cdn` (Pyodide/CanvasKit de CDNs, site menor), `--stage-only`.

### Publicar

```bash
cd apps/dashboard/build/vercel
vercel --prod        # na primeira vez, crie/vincule um projeto próprio (ex.: chargegrid-painel)
```

O `vercel.json` não tem build (`buildCommand` vazio, `outputDirectory: public`) e:

- reescreve **`/v1/*` → `https://chargegrid-api-preview-djlima1s-projects.vercel.app/v1/*`**: no navegador,
  o `ApiClient` usa a mesma origem (`<window.location.origin>/v1`), então não há CORS;
- devolve `index.html` para rotas desconhecidas (fallback SPA);
- `Cache-Control: no-cache` (revalida por ETag) para `index.html`, `main.dart.js`, `flutter_bootstrap.js`,
  `python*.js` e `assets/app/app.zip` (o código Python muda a cada deploy); 7 dias para `pyodide/`,
  `canvaskit/`, `.wasm` e fontes (versões fixadas pelo `flet==1.0.0`).

Para trocar a API, edite o `destination` do rewrite (ou gere com `--api-url`).

### Como funciona no navegador

- **HTTP**: `httpx` não abre sockets no Pyodide. Quando `sys.platform == "emscripten"`, o `ApiClient`
  usa `chargegrid_app.web_transport.PyodideFetchTransport` (`pyodide.http.pyfetch`), com tempo-limite,
  `redirect: "error"` (equivale a `follow_redirects=False`) e erros de rede viram as mesmas mensagens do app.
  Exportação CSV/JSON (`download()`) usa o mesmo transporte e baixa o arquivo pelo navegador.
- **URL da API**: `chargegrid_app.config.api_url()` no navegador usa `<origem>/v1`; `dashboard_config.json`
  pode trazer `"api_url"` (relativa como `/v1` ou absoluta). Fora do navegador nada muda.
- **Demo**: `demo_enabled()` é verdadeiro com `CHARGEGRID_ENABLE_DEMO=1` **ou** com `{"demo": true}` no
  pacote do dashboard. Os insights IA da demo usam o exemplo local (sem chave no site); os da conta real
  vão pela API (`POST /v1/ai/owner-insights`).
- Tamanho: ≈ 56 MB no disco; a primeira visita baixa ≈ 32 MB (≈ 14 MB com compressão gzip/brotli).

### Testar localmente como na Vercel

```bash
# só a demo (sem API)
.venv/bin/python tools/serve_dashboard_web.py --port 8650
# com a API local real (veja tools/live_contract_check): /v1 vai para o uvicorn local e
# owner@live.test (qualquer senha) recebe o token local de teste, simulando o Supabase
.venv/bin/python tools/serve_dashboard_web.py --port 8650 --api http://127.0.0.1:8651 \
  --login-tokens /tmp/tokens.json
```

O servidor serve `apps/dashboard/build/vercel/public` com gzip e fallback SPA e só aceita API em localhost.

Medido em Chrome headless, cache vazio, até a tela de login: ≈ 3,4 s local; ≈ 5,3 s em 50 Mbit/s;
≈ 13 s em 12 Mbit/s (4G). Login demo, visão geral, postos, sessões, exportação CSV, cupons e insights
funcionaram, assim como o fluxo pela API local real.

Nunca publique `.env`, nem habilite a demo em builds do app.
