# Projeto Simulado:

Para acessar o projeto Simulado vá na Branch de simulado, onde haverá uma pasta escrito Simulado, lá estará toda a documentação do aplicativo que pode ser executado localmente permitindo alteração locais em JSON, juntamente com seus arquivos. Nesse arquivo está a fundação da aplicação física, necessitando do hardware e da conexão real com servidores e apk. A parte simulada é a base do projeto, sendo atualmente colocada em Branch como forma de preservar seu conteúdo e testar novas ideias e conceitos, seu ReadME é feito especificamente para ela e contém outras categorias e entendimentos do projeto não nesse ReadME


## O que é o projeto:

O ChargeGrid busca ser uma solução comercial para facilitar a realização de transações e gestão de eletropostos para o mercado varejista. O aplicativo se foca em ser rápido, intuitivo e informativo, permitindo que a mesma conta seja acessada através de perfis de "Consumidor" ou "Vendedor". Ele facilita a realização de recargas de forma dinâmica e fácil de entender, além de proporcionar as informações do histórico de maneira organizada e ágil para ambas as partes.

## Objetivo do ChargeGrid

O ChargeGrid deseja facilitar a vida dos donos de eletropostos com a ajuda de meios para verificar, ajustar suas tarifas e gerir suas estações de maneira personalizada, mantendo a alta usabilidade como nosso maior foco. Com este aplicativo, potencializamos a sustentabilidade ambiental, já que uma rede de eletropostos eficiente incentiva a transição para carros elétricos, reduzindo emissões de CO2 e a dependência de combustíveis fósseis. O ecossistema também foi projetado pensando na facilidade de integração em redes inteligentes e na adoção fluida de sistemas modernos de precificação.

# Avisos

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

## Estado do A

O aplicativo 0.3.5 usa o tipo de conta somente no cadastro; entrar exige apenas e-mail e senha. Claro/escuro funcionam também na autenticação e na página inicial. Campos e botões foram padronizados, com navegação compacta e orientação retrato no aplicativo móvel. Há transições suaves, seletor deslizante sem efeito de onda, validação animada dos campos de autenticação, respeito à redução de movimento, proteção de formulários e controles de voltar sem interromper operações em andamento. O ícone e a abertura reutilizam a marca da tela de login. Em **Meus postos → Editar ponto / dispositivo**, o vendedor pode restaurar o ESP32 de fábrica após confirmação; não é uma restauração das preferências do celular.


No fluxo de propriedade, cada equipamento possui chave própria e QR secreto de vínculo. O vendedor escaneia esse QR e se torna dono do ponto, sem aprovação manual. Um assistente de três etapas salva nome/localização, configura conector/tarifa e só publica após a revisão; rascunhos podem ser retomados em **Meus postos**. Proprietários legados são preservados. O código público usado para iniciar recarga é separado do segredo de propriedade. Consulte [o provisionamento de fábrica](docs/setup.md#provisionar-e-vincular-um-equipamento).

O controle de reserva e recarga é real pela API, mas SoC e energia vêm de `SimulatedSensors`; não representam medição de veículo. Uma reserva válida sobrevive ao reboot do ESP32, sem reiniciar seu prazo; o app diferencia reservado, offline e sincronizando de uma recarga em andamento. O firmware apresenta uma interface voltada ao usuário final, com o mesmo símbolo de marca do login e buffers sincronizados com VSYNC para reduzir piscadas. A restauração só é aceita com equipamento ocioso, online e sem reserva/recarga; ela apaga Wi-Fi e vínculo antigos no ESP, gera um QR novo e preserva o histórico no servidor. Durante a recarga, o dispositivo sincroniza a cada 5 segundos; o app consulta `GET /me/summary` para o resumo mensal estimado.

Cadastros novos iniciam sessão sem confirmação de e-mail. A recuperação por e-mail continua pendente de SMTP próprio.

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
