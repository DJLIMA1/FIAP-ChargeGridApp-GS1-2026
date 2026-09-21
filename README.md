# ChargeGrid

O ChargeGrid é o MVP acadêmico da equipe FFIVE para localizar eletropostos, reservar um ponto e acompanhar uma recarga confirmada por dispositivo. O aplicativo Flet conversa com uma API FastAPI; a API é a única camada que acessa PostgreSQL e valida permissões.

Consulte [a instalação](docs/setup.md), [a arquitetura](docs/architecture.md), [o contrato HTTP](docs/api.md), [o protocolo do ESP32](docs/esp32-protocol.md) e [o roteiro de demonstração](docs/demo.md).

Use um único `.env` na raiz do monorepo: copie `.env.example` e preencha as variáveis locais. O arquivo real permanece ignorado pelo Git.

## Estrutura

```text
apps/api/        API FastAPI, migrações e testes de regras
apps/mobile/     aplicativo Flet
firmware/esp32/  firmware de bancada para ESP32
tools/           simulador de dispositivo e seus testes
docs/            decisões, operação e apresentação
```

## Estado do MVP

O aplicativo 0.2.3 usa o tipo de conta somente no cadastro; entrar exige apenas e-mail e senha. Claro/escuro funcionam também na autenticação e na página inicial. Campos e botões foram padronizados, com navegação compacta e orientação retrato no aplicativo móvel. A atualização inclui transições suaves, seletor deslizante sem efeito de onda, validação animada dos campos de autenticação, respeito à redução de movimento, proteção de formulários e controles de voltar sem interromper operações em andamento.

O painel Waveshare conectado foi atualizado e provisionado como `CG-PAINEL-01`, no posto fictício `ChargeGrid • Bancada QA`. Reserva, recarga e parada foram validadas entre interface, API publicada e ESP32 físico. Segure o logo por 5 segundos para abrir a manutenção quando não houver operação ativa. Senha e chave permanecem mascaradas e não são mostradas depois de salvas em NVS.

Para vincular um painel, uma pessoa precisa primeiro ter aprovação de operador, criar o posto e o ponto e então usar **Provisionar dispositivo**. A chave é exibida uma vez. O controle de reserva e recarga é real pela API, mas SoC e energia vêm de `SimulatedSensors`; não representam medição de veículo. Durante a recarga, o dispositivo sincroniza a cada 5 segundos; o app consulta `GET /me/summary` para o resumo mensal estimado.

Cadastros novos iniciam sessão sem confirmação de e-mail neste MVP. A recuperação por e-mail continua pendente de SMTP próprio.

Veja as evidências do MVP integrado em [docs/validacao-mvp-0.2.0.md](docs/validacao-mvp-0.2.0.md) e da atualização do app em [docs/validacao-mobile-0.2.3.md](docs/validacao-mobile-0.2.3.md). APKs e pacotes de firmware são artefatos locais em `builds/`, não arquivos versionados; os guias descrevem como gerá-los.

## Execução local rápida

O requisito da raiz instala as dependências do aplicativo. Para API, firmware e variáveis de ambiente, siga o guia completo em [docs/setup.md](docs/setup.md).

```bash
python3 -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows: python -m venv .venv; .venv\Scripts\activate
pip install -r requirements.txt
python src/main.py
```

## Limites do MVP

Pagamentos são demonstrativos. A bancada do ESP32 e o simulador Python usam medições identificadas como `simulated`; não controlam energia, veículo ou carregador real. Chaves de dispositivos, senhas, certificados ou chaves privadas e arquivos `.env` não devem ser enviados ao Git. Uma CA pública necessária para validação TLS pode ser versionada, como `apps/api/certs/supabase-prod-ca-2021.crt`.

## Equipe FFIVE

- Augusto de Souza Ávila — RM: 570839
- Davi Simoncelo — RM: 571738
- João Pedro Sousa — RM: 573962
- Matheus Evangelista Silva — RM: 568593
- Murilo Lima de Carvalho — RM: 570156
