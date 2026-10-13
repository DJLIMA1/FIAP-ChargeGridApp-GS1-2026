# Auditoria de QA — outubro de 2026

Branch `feat/qa`. Escopo: app Flet (`apps/mobile`), API FastAPI (`apps/api`), pacote
`chargegrid_core` e a nova tela do modo motorista (`screens/driver.py`). O chat
(`screens/chat.py`) ficou fora por estar em reescrita. Cada bug corrigido tem teste de
regressão em `apps/api/tests/test_qa_regressions.py`,
`apps/mobile/tests/test_qa_regressions.py` ou `packages/chargegrid_core/tests/test_formatting.py`.

> **Nota sobre as medições.** Durante a auditoria a máquina esteve sob carga extrema
> (load average entre 70 e 250 em 8 núcleos, com outros agentes compilando e testando).
> Tempos absolutos variam muito. Por isso cada ganho é apresentado também por uma
> métrica estrutural, que não depende de carga (número de consultas, de downloads ou
> de bytes).

## 1. Bugs encontrados e corrigidos

### API

| # | Bug | Impacto | Correção |
|---|-----|---------|----------|
| A1 | **Cupom sensível a maiúsculas.** `DEMO10` criado pelo operador era recusado quando o motorista digitava `demo10`. | Cupom válido rejeitado no início da recarga. | Códigos novos são gravados em maiúsculas. A busca usa `upper()`, inclusive para cupons antigos com caixa mista (a correspondência exata tem prioridade). Duplicatas que diferem só na caixa retornam `409 coupon_exists`. A mesma regra vale no modo demo. |
| A2 | **Limite de taxa em janela fixa.** Era possível enviar 2× o máximo na virada do minuto. A rajada de 21 logins também atravessava a janela, e o teste `test_failed_logins_are_persistently_rate_limited` falhava de forma intermitente (falhou na linha de base). | Proteção contra força bruta contornável; teste instável. | Janela deslizante: a contagem atual mais a contagem da janela anterior, ponderada pelo tempo restante (`limit(..., clock=)`). |
| A3 | **IP do cliente atrás da Vercel.** O limite de autenticação usava `request.client.host`, que na Vercel é o proxy. | Todos os usuários dividiam o mesmo limite de 20/min (bloqueio coletivo). | `client_ip()` usa `X-Real-IP`/`X-Forwarded-For` **somente** com `VERCEL` definido, pois a plataforma sobrescreve esses cabeçalhos. Fora dela, cabeçalhos forjados são ignorados. |
| A4 | **Reset de senha sem `access_token`.** Uma resposta 200 do provedor sem sessão gerava `KeyError`. | Erro 500. | Retorna `401 auth_rejected`. |
| A5 | **Código público duplicado** em `PATCH /connectors/{id}`. | Retornava a mensagem genérica "Operação conflita com registro existente". | Retorna `409 public_code_taken` com uma mensagem clara. |
| A6 | **`/operator/summary` carregava todas as sessões** do operador na memória para somá-las. | Tempo e memória cresciam sem limite com o histórico. | Agregação em SQL (`count`/`sum`), com o mesmo formato de resposta. |
| A7 | **Teste de serialização de pontos.** A consulta de "ponto aposentado" passou a ser feita a partir de `device_commands`, preservando o contrato do teste existente de uma única leitura de `devices` por ponto. | — | Coberto pelo teste existente. |

### App

| # | Bug | Impacto | Correção |
|---|-----|---------|----------|
| M1 | **Dinheiro arredondado com `float`.** `R$ 2,675` virava `R$ 2,67`, e `1234.5` aparecia como `R$ 1234,50`, sem separador de milhar. | Valores errados por um centavo e pouco legíveis. | `chargegrid_core.formatting` agora usa `Decimal` com arredondamento meio para cima e aceita strings decimais da API. `money()`, o mapa e os novos `percent`/`integer` do painel usam esse módulo. `km(9.96)` passou de "10,0 km" para "10 km". |
| M2 | **Sair sem rede.** Uma falha em `POST auth/logout` propagava o erro, e a saída mostrava um erro em vez de concluir. | A saída parecia ter falhado. | A sessão local é sempre encerrada. Sem conexão, o app avisa que o acesso expira sozinho. Um token já expirado (401) sai em silêncio. |
| M3 | **Contraste no tema escuro.** Textos com `theme.RED` (3,3:1), `theme.AMBER` (2,8:1) e ícones âmbar ficavam abaixo do AA sobre cartões escuros (histórico demo, onboarding, operador, vinculação, motorista). | Ilegível no tema escuro. | Usamos `ACCENT` e o novo token `WARNING` (claro `#9A5300`, escuro `#F5B76B`). O resumo da recarga, sempre branco, usa `#B91C24`. Um teste AST impede usar `RED`/`AMBER`/`BLUE`/`SLATE` como cor de texto. |
| M4 | **Bordas de campo depreciadas** no Flet 1.0 (`border_color`, `border_radius`, `focused_border_color`), que serão removidas na 1.3. | Avisos de depreciação e quebra futura. | Novo `input_border()`/`mark_input()` com bordas por estado (`OutlineInputBorder`/`UnderlineInputBorder`). O foco e o erro usam cores AA sobre o campo branco. A suíte do app passa com `-W error::DeprecationWarning`. |
| M5 | **Alvos de toque de 40 px na web.** O Flutter aplica densidade COMPACT na web e no desktop, e os botões de 48 px renderizavam com cerca de 36 a 40 px. | Abaixo dos 48 px recomendados. | `Theme(visual_density=STANDARD)`. |
| M6 | **Conteúdo de seções expansíveis centralizado** (padrão do Flet). Em "Preferências e acesso", por exemplo, botões estreitos ficavam no meio do cartão. | Layout quebrado. | `expanded_cross_axis_alignment` explícito em todas as `ExpansionTile` (com teste AST). |
| M7 | **Plurais e kWh ambíguo no painel do operador.** Apareciam "1 pontos" e "1 postos", e "4,800 kWh" (lido como 4 800). | Texto errado ou ambíguo. | Plurais corretos e kWh com 2 casas no painel, no resumo da home e no histórico. |
| M8 | **Filtro mostrava a chave interna** ("Comparação: type2"). | Texto técnico para o usuário. | Mostra o rótulo ("Tipo 2"). |
| M9 | **Modo motorista: bateria 0 % virava 60 %** (`or` tratava 0 como ausente). | Plano calculado com a carga errada. | Só um valor ausente usa o próximo padrão. |
| M10 | **Modo motorista sem rede.** Uma falha no `GET driver/profile` derrubava a tela inteira, mesmo com perfil salvo no aparelho. | A tela não abria offline. | A tela abre com o perfil local e avisa que está sem conexão. |
| M11 | **Polling em segundo plano e sem recuo.** O app consultava a API a cada 5 a 10 s mesmo minimizado e mantinha o intervalo durante falhas. | Bateria, dados e carga no servidor. | Pausa em `HIDE`/`PAUSE` com atualização imediata ao voltar e recuo exponencial durante falhas (5 → 10 → 20 → 40 → 60 s). |

### Ambiente de testes

- `conftest.py` usava `drop_all`, que falha quando o banco de teste contém tabelas de
  outra branch que referenciam as nossas (`driver_profiles → profiles`). Agora usa
  `DROP TABLE ... CASCADE` uma vez por execução.

## 2. Desempenho (antes → depois)

| Área | Antes | Depois | Como foi medido |
|------|-------|--------|-----------------|
| `GET /v1/stations` (20 postos × 2 pontos) | **183 consultas** (9,4 s e 20,4 s sob carga) | **8 consultas** (6,0 s e 3,7 s) | `bench_queries.py`: contador `before_cursor_execute`, mesmo banco e mesmos dados, código antigo × novo. |
| `GET /v1/stations?available_only=true` | 182 consultas (8,0 s e 11,1 s) | 7 consultas (2,4 s e 2,1 s) | idem |
| `GET /v1/me/charging-sessions` (40 sessões) | **123 consultas** (4,6 s e 9,1 s) | **6 consultas** (1,2 s e 1,7 s) | idem |
| Planejamento do motorista (até 40 postos) | `station_row` por posto (N+1) | serialização em lote (`station_rows`) | mesma função das listagens acima |
| Número de consultas por página | crescia com postos e sessões | constante | testes `test_*_query_count_does_not_grow_*` |
| Home: primeira pintura com tiles frios (1,2 s por tile) | **7,0 s** (e o mapa expirava, caindo no esquemático) | **0,36 s** (mapa entra depois, no lugar do esqueleto) | `bench_home.py`, 3 execuções cada |
| Mapa real com tiles frios | 7,25 s → timeout e mapa esquemático | 2,7 s, mapa real (downloads em paralelo) | `bench_map.py` |
| Redesenho do mesmo mapa (polling) | 7 s (recompõe e recodifica) | **4 ms** (cache LRU da imagem composta) | idem |
| Tamanho do mapa enviado ao cliente | PNG de 461 KB (~615 KB em base64) | JPEG q85 de 138 KB (~184 KB) | tiles reais de OSM 720×497 |
| Mapa offline | até 7 s por tentativa | falha imediata por 60 s após o primeiro erro de rede | teste `test_offline_tiles_fail_fast_*` |
| Polling com o app minimizado | 1 requisição a cada 5 a 10 s | 0 | teste `test_hidden_app_does_not_poll_*` |
| Painel do operador | `summary` e `stations` em sequência | em paralelo (`asyncio.gather`) | — |
| Suíte da API | `drop_all`+`create_all` de 15 tabelas e 22 índices **por teste** (~55 DDL com fsync × 151 testes) | 1 criação de schema + 1 `TRUNCATE ... RESTART IDENTITY CASCADE` por teste | Recriar o schema levava de 7,8 a 13,5 s por teste sob carga, contra cerca de 1,7 s do `TRUNCATE`. Suíte completa: 834,7 s na linha de base (load 120–250, com 1 falha intermitente) e 706 a 736 s depois (load ~70, 0 falhas). Subconjunto A/B: 66 s → 41 s e 92 s → 86 s. A CPU do processo de teste foi de apenas ~10 s, então o tempo restante é espera de I/O e carga da máquina. |
| Cold start da API | — | sem mudança | `-X importtime`: o tempo é dominado por FastAPI, SQLAlchemy e psycopg, que são obrigatórios. Não há import opcional pesado para adiar sem risco. |

Índices novos (migração `4d7e1a9c2b60`, `down_revision = a3f1c9d2e7b4`):
`ix_telemetry_device_received` (cada sync do dispositivo lê a última amostra),
`ix_device_commands_session_id`, `ix_charging_sessions_user_created` (histórico) e
`ix_coupons_operator_id`. A migração foi testada com `upgrade`, `downgrade -1` e
`upgrade` em banco local, e `alembic heads` mostra um head único.

## 3. UI/UX

- **Histórico.** Cada sessão virou um cartão compacto: chip de estado, data, posto,
  conector, energia e custo. O recibo completo fica em "Detalhes da sessão", e a
  contagem aparece no título ("1–2 de 2 sessões").
- **Estados vazios ilustrados** (`ui/states.py`) no histórico (motorista e operador) e
  em cupons, com o próximo passo ("Encontrar um posto").
- **Esqueleto do mapa** (`ui/deferred.py`). A home e a lista de postos pintam em até
  350 ms. O mapa entra no lugar quando fica pronto e nunca cai em outra tela.
- **Recarga mais fluida.** A etapa 2 ganhou durações de um toque (15/30/60 min e
  "Máx. N min", sempre dentro do limite do ponto).
- **Cupons.** O código aparece destacado e selecionável, com "N% OFF". O formulário
  normaliza para maiúsculas, e o texto explica onde usar o cupom.
- Contraste AA nos dois temas, alvos de toque de 48 px na web, bordas de foco e erro
  visíveis no campo branco, e textos mais claros em pt-BR (plurais, kWh, rótulos de
  filtro).
- Microanimações já respeitam reduced motion. O esqueleto usa um ícone estático
  quando o movimento está reduzido.

## 4. Como verificar

```bash
# App, núcleo, painel e ferramentas
cd apps/mobile && PYTHONPATH=src ../../.venv/bin/python -m pytest tests -q -W error::DeprecationWarning
cd packages/chargegrid_core && ../../.venv/bin/python -m pytest tests -q
cd apps/dashboard && ../../.venv/bin/python -m pytest tests -q
.venv/bin/python -m pytest tools/tests -q
# API (banco local descartável)
cd apps/api && TEST_DATABASE_URL=postgresql+psycopg://localhost/chargegrid_qa_test \
  DATABASE_URL=postgresql+psycopg://localhost/chargegrid_qa_test .venv/bin/python -m pytest -q
```

Demonstração: entre na conta demo, abra **Histórico** (cartões novos), **Recarga →
Ver pontos → Já estou aqui** (durações de um toque) e **Conta → Preferências** (seção
alinhada; troca de tema com contraste AA).

## 5. Pendências e riscos

- Os índices da migração `4d7e1a9c2b60` usam `CREATE INDEX` comum, sem `CONCURRENTLY`.
  As tabelas do piloto são pequenas, mas, em produção com muitos dados, prefira uma
  janela de manutenção.
- Cupons antigos com códigos que diferem só na caixa continuam no banco. A busca
  prioriza a correspondência exata, mas convém normalizá-los com um script de
  manutenção.
- O JPEG do mapa pode mostrar leves artefatos nos rótulos das ruas. Para voltar ao
  PNG, basta `MAP_IMAGE_FORMAT = 'PNG'`.
- Sob carga extrema, os tempos medidos variam muito. As métricas estruturais
  (consultas, bytes, downloads) são as referências confiáveis.
