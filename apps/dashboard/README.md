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
  Na demo, um exemplo é gerado localmente.

Cabeçalho: período (hoje / 7 dias / 30 dias / personalizado), posto, atualizar agora, tema claro/escuro e
conta. Menu lateral recolhível; abaixo de 900 px ele fica só com ícones (tablet).

## Testes

```bash
cd apps/dashboard && ../../.venv/bin/python -m pytest tests -q
../../.venv/bin/ruff check .
```

## Publicar como site estático (não publicado)

`flet build web` gera um site estático (Python roda no navegador via Pyodide). Como o código é
compartilhado com `apps/mobile/src`, monte um diretório de build com tudo lado a lado:

```bash
rm -rf /tmp/cg-dashboard-web && mkdir -p /tmp/cg-dashboard-web/src
cp -R apps/dashboard/main.py apps/dashboard/pyproject.toml apps/dashboard/chargegrid_dashboard /tmp/cg-dashboard-web/
cp -R apps/mobile/src/chargegrid_app apps/mobile/src/chargegrid_core /tmp/cg-dashboard-web/src/
cp -R apps/mobile/assets /tmp/cg-dashboard-web/assets
cd /tmp/cg-dashboard-web && flet build web --base-url /painel/ --route-url-strategy hash
# saída em build/web → qualquer hospedagem estática (Vercel, GitHub Pages, S3)
```

Antes de publicar:

- Configure a URL pública da API (`CHARGEGRID_API_URL` não existe no navegador; use
  `assets/app_config.json` com `{"api_url": "https://.../v1"}`, lido por `chargegrid_app.config`;
  `tools/configure_mobile.py` gera esse arquivo para o app).
- Inclua a origem do site em `CORS_ORIGINS` da API.
- **Risco**: o `ApiClient` usa `httpx`, que no Pyodide precisa de transporte compatível com `fetch`.
  Valide o build; se falhar, publique o dashboard como app Flet servido (`flet run --web`/contêiner
  com `ft.run(..., view=None)`) — a forma usada e testada neste protótipo.
- Nunca habilite `CHARGEGRID_ENABLE_DEMO` em produção nem empacote `.env`.
