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

O aplicativo 0.3.3 usa o tipo de conta somente no cadastro; entrar exige apenas e-mail e senha. Claro/escuro funcionam também na autenticação e na página inicial. Campos e botões foram padronizados, com navegação compacta e orientação retrato no aplicativo móvel. Há transições suaves, seletor deslizante sem efeito de onda, validação animada dos campos de autenticação, respeito à redução de movimento, proteção de formulários e controles de voltar sem interromper operações em andamento. O ícone e a abertura reutilizam a marca da tela de login.

O painel Waveshare conectado foi usado para validar reserva, recarga e parada como `CG-PAINEL-01` no posto fictício `ChargeGrid • Bancada QA`. Na versão 0.3.2, ele foi migrado para o novo ponto de fábrica `CG-PAINEL-02` e exibiu o QR de primeira vinculação. O ponto já foi vinculado e publicado por um vendedor; o anterior está inativo, com histórico preservado. Segure o logo por 5 segundos para configurar o Wi-Fi quando não houver operação ativa. Senha e chave permanecem mascaradas e não são mostradas depois de salvas em NVS.

No novo fluxo de propriedade, cada equipamento nasce na fábrica com chave própria e QR secreto de vínculo. O vendedor escaneia esse QR e se torna dono do ponto, sem aprovação manual. Um assistente de três etapas salva nome/localização, configura conector/tarifa e só publica após a revisão; rascunhos podem ser retomados em **Meus postos**. Proprietários legados são preservados. O código público usado para iniciar recarga é separado do segredo de propriedade. Consulte [o provisionamento de fábrica](docs/setup.md#provisionar-e-vincular-um-equipamento).

O controle de reserva e recarga é real pela API, mas SoC e energia vêm de `SimulatedSensors`; não representam medição de veículo. Uma reserva válida sobrevive ao reboot do ESP32, sem reiniciar seu prazo; o app diferencia reservado, offline e sincronizando de uma recarga em andamento. O firmware 0.3.4 apresenta uma interface voltada ao usuário final, com o mesmo símbolo de marca do login e buffers sincronizados com VSYNC para reduzir piscadas. Durante a recarga, o dispositivo sincroniza a cada 5 segundos; o app consulta `GET /me/summary` para o resumo mensal estimado.

Cadastros novos iniciam sessão sem confirmação de e-mail neste MVP. A recuperação por e-mail continua pendente de SMTP próprio.

Veja as evidências do MVP integrado em [docs/validacao-mvp-0.2.0.md](docs/validacao-mvp-0.2.0.md), do fluxo de propriedade em [docs/validacao-ownership-0.3.0.md](docs/validacao-ownership-0.3.0.md), da [validação 0.3.2](docs/validacao-0.3.2.md) e do [painel físico](docs/waveshare-panel.md). APKs e pacotes de firmware são artefatos locais em `builds/`, não arquivos versionados; os guias descrevem como gerá-los.

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
