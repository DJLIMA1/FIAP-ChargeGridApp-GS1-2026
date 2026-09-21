# Instalação e configuração

Use Python 3.11 para a API e Python 3.12 para o aplicativo Flet. Os comandos abaixo funcionam no macOS e no Windows; altere apenas a ativação do ambiente virtual.

## Aplicativo Flet

Na raiz do repositório:

```bash
python3 -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
python src/main.py
```

Copie `.env.example` para `.env` na raiz do repositório. Defina `CHARGEGRID_API_URL` com a URL da API, incluindo `/v1`. Durante o desenvolvimento local, use `http://127.0.0.1:8000/v1` somente para o app local; ambientes publicados exigem HTTPS válido.

### Estado atual

Há um único `.env` na raiz do monorepo. A URL da API para o mobile é `https://chargegrid-api-preview-djlima1s-projects.vercel.app/v1`, servida pelo adaptador `api/index.py` na Vercel, na região `gru1` próxima ao banco. O MVP integrado 0.2.0 e a migração aditiva `c74ef532ab90` foram validados; consulte [o relatório](validacao-mvp-0.2.0.md). O app está na versão 0.2.3, build 13, com [seletor deslizante e validação animada](validacao-mobile-0.2.3.md). O SMTP externo ainda está pendente: a entrega geral de e-mails exige configuração própria neste ambiente.

### APK Android

O nome exibido pelo Android e o identificador do pacote ficam em `apps/mobile/pyproject.toml`. Para gerar um APK com o nome **ChargeGrid**, use o ambiente virtual criado na raiz:

```bash
.venv/bin/python tools/configure_mobile.py
cd apps/mobile
../../.venv/bin/flet build apk . --yes
```

O primeiro comando lê somente `CHARGEGRID_API_URL` do `.env` raiz e gera `apps/mobile/assets/app_config.json`, que contém apenas essa URL pública. O Flet 1.0.0 prepara automaticamente o Flutter 3.44.8, o JDK 17 e o Android SDK usados pelo build na primeira execução. O APK gerado fica em `apps/mobile/build/apk/chargegrid.apk`. Instale esse arquivo novamente no aparelho depois de cada build; o APK já instalado conserva os metadados da versão com que foi compilado. O build usa a identidade visual aprovada em `apps/mobile/assets/icon.png` e `apps/mobile/assets/splash_android.png`.

## API e PostgreSQL

Crie outro ambiente virtual dentro de `apps/api` e instale as dependências:

```bash
cd apps/api
python3 -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Use o mesmo `.env` da raiz. Preencha `DATABASE_URL` com o login de execução, associado ao papel SQL `chargegrid_api`, e `MIGRATION_DATABASE_URL` com a conexão administrativa usada somente para Alembic. No Supabase, prefira a string do pooler em modo transação para `DATABASE_URL`; mantenha a conexão administrativa separada para migrações. Ajuste também `SUPABASE_URL`, `SUPABASE_ANON_KEY` e, quando houver cliente web, `CORS_ORIGINS`. Em Vercel, as variáveis configuradas no painel têm precedência e o arquivo local não é enviado.

Antes da primeira execução, aplique o esquema em um banco vazio:

```bash
alembic upgrade head
# substitua pelo login presente em DATABASE_URL
psql "$MIGRATION_DATABASE_URL" -v runtime_role=nome_do_usuario -f sql/grant_runtime_role.sql
uvicorn app.main:app --reload
```

O servidor local atende em `http://127.0.0.1:8000`; a documentação OpenAPI fica em `/docs`. A migração cria o papel sem login `chargegrid_api`, aplica RLS às tabelas de domínio e revoga acesso de `anon` e `authenticated`. O administrador ainda precisa conceder esse papel ao login usado em `DATABASE_URL` (`GRANT chargegrid_api TO <runtime_login>`); o login de execução não pode ser dono das tabelas nem ter `BYPASSRLS`. Para criar `chargegrid_runtime` sem colocar a senha no comando, abra `psql "$MIGRATION_DATABASE_URL"`, execute `CREATE ROLE chargegrid_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT NOREPLICATION NOBYPASSRLS;` e `GRANT chargegrid_api TO chargegrid_runtime;`, depois use `\password chargegrid_runtime`: o `psql` solicitará a senha sem exibi-la. Não grave a senha no arquivo SQL nem no histórico do shell.

## Auth, SMTP e permissões

No Supabase, `Confirm email` está desativado por decisão explícita para este MVP: o SMTP padrão só entrega a membros da equipe, limita o projeto a duas mensagens por hora e não oferece SLA. Cadastros novos retornam sessão imediatamente e continuam protegidos por senha, JWT, limites da API e autorização por usuário. A `Site URL` permanece em `https://chargegrid-api-preview-djlima1s-projects.vercel.app/auth/confirmed` para compatibilidade. Essa escolha não valida a posse do e-mail e aumenta o risco de cadastro indevido; antes de uso público, configure SMTP próprio ou OAuth e reative a confirmação. Recuperação de senha por e-mail não é confiável neste ambiente. Consulte a [documentação SMTP](https://supabase.com/docs/guides/auth/auth-smtp).

Desligue a Data API no painel do Supabase. A migração remove permissões de `anon` e `authenticated` sobre tabelas do domínio; use a chave anônima apenas nas chamadas de Auth. A service role, a senha administrativa do banco e os segredos de SMTP nunca pertencem ao app, firmware ou arquivos versionados.

## Vercel

Crie o projeto a partir deste repositório e escolha `apps/api` como **Root Directory**. Cadastre na Vercel somente `DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_ANON_KEY` e `CORS_ORIGINS`. Não cadastre `MIGRATION_DATABASE_URL`, senha administrativa, service role ou segredo SMTP no runtime. Execute `alembic upgrade head` localmente ou em um job administrativo efêmero com `MIGRATION_DATABASE_URL`, antes de apontar a implantação para um banco novo; remova essa credencial do ambiente ao terminar. Confirme em produção que `/docs` abre e que o emissor do JWT corresponde a `SUPABASE_URL`.

## ESP32 e simulador

Em `firmware/esp32`, copie `include/config.example.h` para `include/chargegrid_config.h`. Informe Wi-Fi, URL HTTPS da API sem `/v1`, a chave individual do dispositivo e o certificado raiz PEM da cadeia do servidor. Esse arquivo é ignorado pelo Git.

```bash
cd firmware/esp32
pio run
# Com uma placa compatível conectada:
pio run -t upload
pio device monitor
```

O firmware é uma bancada simulada e não deve controlar energia real. Para testar o mesmo protocolo sem placa, na raiz instale `httpx`, defina a chave e execute:

```bash
# macOS/Linux
export CHARGEGRID_DEVICE_KEY='chave-individual'
python3 tools/device_simulator.py --api https://sua-api
# API local somente
python3 tools/device_simulator.py --api http://127.0.0.1:8000 --allow-local-http
```

No Windows PowerShell, use `$env:CHARGEGRID_DEVICE_KEY = 'chave-individual'`. O simulador cria `.device-simulator-state.json`; mantenha esse estado privado e use um arquivo distinto por dispositivo.

## Verificação

```bash
cd apps/api && ruff check app tests && DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/chargegrid_test TEST_DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/chargegrid_test pytest
cd ../.. && python3 -m ruff check tools && python3 -m pytest tools/tests
cd apps/mobile && python3 -m ruff check src tests && PYTHONPATH=src python3 -m pytest tests
```

Os testes da API exigem PostgreSQL real em `TEST_DATABASE_URL`; para que a inicialização da API use o mesmo banco descartável, defina também `DATABASE_URL` com a mesma URL. Em PowerShell, prefira atribuir ambas as variáveis antes de executar `pytest`. Os testes unitários administrativos usam mocks. A integração da importação usa apenas um PostgreSQL descartável indicado por `CHARGEGRID_IMPORT_TEST_DATABASE_URL`; `LEGACY_IMPORT_DATABASE_URL` é reservado exclusivamente ao comando de importação real.

Para exercitar a importação em PostgreSQL, use um banco descartável cujo nome termine em `_test`, aplique antes as migrações e defina `CHARGEGRID_IMPORT_TEST_DATABASE_URL`. O teste apaga os registros de importação desse banco e verifica repetição e reversão por conflito:

```bash
cd apps/api
MIGRATION_DATABASE_URL=postgresql+psycopg://usuario:senha@localhost:5432/chargegrid_import_test alembic upgrade head
cd ../..
CHARGEGRID_IMPORT_TEST_DATABASE_URL=postgresql://usuario:senha@localhost:5432/chargegrid_import_test python3 -m pytest tools/tests
```

## Ferramentas administrativas

Execute a partir da raiz, usando o ambiente Python da API (httpx, psycopg e pytest). Segredos são fornecidos por variáveis de ambiente; nunca publique seus valores nem os inclua em argumentos de comandos.

As ferramentas de linha de comando não carregam arquivos `.env` automaticamente. Para usar a configuração local raiz em macOS/Linux, carregue-a no terminal antes do comando:

```bash
set -a
source .env
set +a
```

- `python tools/seed_demo.py --points 1`: usa `CHARGEGRID_API_URL` (incluindo `/v1`) e `CHARGEGRID_OPERATOR_TOKEN`, obtido pelo login de uma conta confirmada e aprovada como operador. Cria/reutiliza o posto fictício `ChargeGrid Demo FIAP` do próprio operador e pontos de demonstração. Repetições sequenciais reutilizam os recursos. Execute uma instância por vez. Não cria contas, senhas, sessões ou chaves de dispositivo.
- `python tools/maintenance.py`: com `DATABASE_URL`, conta telemetria recebida há mais de sete dias e limites de requisição vencidos. `--apply` exclui apenas esses registros em uma transação; falhas revertem a transação. Estado de boots/replay, sessões, comandos e idempotência são preservados. Agende externamente somente depois de revisar a prévia.
- `python tools/import_legacy.py /caminho/privado/arquivo.json`: lê somente o arquivo escolhido, sem buscar `ev_data.json` automaticamente. A prévia mostra contagens de `users/usuarios`, `stations/estacoes`, `coupons/cupons`, `history/historico` e categorias desconhecidas. Nunca mostra valores pessoais ou credenciais e nunca grava dados.

Para aplicar uma importação, use `--apply --account-map /caminho/privado/mapa.json --source-id <identificador-estável>` e informe o tipo de conector quando os dados não o trouxerem. A ferramenta exige `SUPABASE_URL` HTTPS, `SUPABASE_SERVICE_ROLE_KEY` e `LEGACY_IMPORT_DATABASE_URL` de forma explícita. Antes de abrir a transação, ela confere cada identidade `{email: UUID}` diretamente no Auth administrativo, inclusive confirmação de e-mail. Os IDs determinísticos derivados do `source-id`, o bloqueio transacional e a validação de colisões tornam a repetição segura; qualquer falha reverte a transação. Nenhuma senha, token, Pix ou sessão ativa é importada. Conserve o original e os mapas fora do repositório e nunca use o banco da demonstração para essa operação.

Validação isolada: `python -m pytest tools/tests/test_admin_tools.py -q`. Os testes unitários usam mocks e dados fictícios; a integração com PostgreSQL é opcional e usa somente o banco descartável configurado, sem ler a base legada real.

### Aprovar uma conta de vendedor

O vendedor escolhe o tipo no cadastro e conclui o primeiro acesso para persistir o perfil. Um administrador autorizado deve conferir o UUID exato do perfil, disponível em `GET /v1/me` da própria conta, e disponibilizar `MIGRATION_DATABASE_URL` no ambiente. A ferramenta exige essa variável explicitamente; não carrega `.env` automaticamente. Substitua `UUID_DO_PERFIL` nos comandos:

```bash
python tools/approve_operator.py UUID_DO_PERFIL
python tools/approve_operator.py UUID_DO_PERFIL --apply
```

O primeiro comando mostra a prévia. `--apply` aprova somente aquele perfil de vendedor em uma transação; perfis ausentes ou de consumidor são recusados. Repetir a aprovação de um vendedor já habilitado não altera dados. A saída contém apenas UUID e estado, sem nomes, e-mails ou credenciais. Depois da aprovação, o vendedor entra novamente no app para acessar a gestão de postos. Testes isolados: `python -m pytest tools/tests/test_approve_operator.py -q`.
