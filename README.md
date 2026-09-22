## Equipe FFIVE

- Augusto de Souza Ávila — RM:570839 
- Davi Simoncelo — RM: 571738 
- João Pedro Sousa — RM: 573962 
- Matheus Evangelista Silva — RM: 568593 
- Murilo Lima de Carvalho — RM:570156

## O que é o projeto:

O ChargeGrid busca ser uma solução comercial para facilitar a realização de transações e gestão de eletropostos para o mercado varejista. O aplicativo se foca em ser rápido, intuitivo e informativo, permitindo que a mesma conta seja acessada através de perfis de "Consumidor" ou "Vendedor". Ele facilita a realização de recargas de forma dinâmica e fácil de entender, além de proporcionar as informações do histórico de maneira organizada e ágil para ambas as partes.

## Objetivo do ChargeGrid

O ChargeGrid deseja facilitar a vida dos donos de eletropostos com a ajuda de meios para verificar, ajustar suas tarifas e gerir suas estações de maneira personalizada, mantendo a alta usabilidade como nosso maior foco. Com este aplicativo, potencializamos a sustentabilidade ambiental, já que uma rede de eletropostos eficiente incentiva a transição para carros elétricos, reduzindo emissões de CO2 e a dependência de combustíveis fósseis. O ecossistema também foi projetado pensando na facilidade de integração em redes inteligentes e na adoção fluida de sistemas modernos de precificação.

# Simulação:
Essa branch do projeto foca em permitir que o usuário veja a versão simulada do projeto, permitindo ver como está o aplicativo sem os componentes físicos. Por ser a versão mais defasada está nessa branch focada nele, ainda há os arquivos do físico por precaução, para acessar o projeto acesse a pasta "Simulado" onde haverá os arquivos em python com os requirements e ícones.

## Estrutura do projeto: 

O aplicativo foi estruturado em Python, utilizando o framework **Flet** para a interface gráfica, garantindo um layout responsivo, moderno e preparado estruturalmente para futuras compilações multiplataforma e mobile. O gerenciamento de dados é simulado em Json onde toda a persistência de informações, histórico e configurações flui através da classe `DataManager` (no arquivo `data_manager.py`), que sincroniza o estado global dentro de um único arquivo local, o `ev_data.json. Toda a orquestração e roteamento de telas são centralizados na classe principal `ChargeGridApp` (em `main.py`), a qual emprega rotinas assíncronas do pacote `asyncio` para rodar os laços de simulação de carga em segundo plano de forma nativa e não bloqueante, perfeitos para a simulação.

## Bibliotecas usadas: 

flet | pillow | asyncio | json | os | hashlib | math | urllib | re | ssl | time

## Funcionalidades:

- Interface multiplataforma moderna com suporte ativo e integrado a Modo Claro/Escuro.
- Sistema de login permitindo cadastro e persistência, juntamente com alteração de senhas.
- Sistema de papéis: um único cadastro permite atuar como consumidor ou gerenciar postos como vendedor na tela de login.
- Sistema de Geolocalização: rastreamento do dispositivo via API do sistema, com alternativas automáticas para coordenadas baseadas em Conta ou em geolocalização de rede por IP.
- Renderização de Mapas: integração ao OpenStreetMap (baixando tiles dinâmicos gerados no cache pelo `Pillow`) ou fallback automático para mapas esquemáticos offline.
- Integração nativa com ViaCEP e Nominatim para geocodificação de busca de endereços.
- Execução de tarefas de recarga em segundo plano com progressão em tempo real escalonado (1 segundo real equivale a 1 minuto simulado).
- Mecânica de recarga flexível: o cliente configura a estação definindo o tempo desejado de conexão ou o o valor(R$) da transação.
- Chatbot virtual embutido simulando um assistente para resolução rápida de dúvidas de usuários.
- Gestão de infraestrutura: cada usuário vendedor é capaz de configurar velocidade de KW, tarifa por kWh, limites de uso e cupons regionais aplicáveis unicamente à sua conta, e para cada um de seus carregadores.
- Visualização de históricos de usuário e vendedor, de forma única ao usuário.
- Criação de documento JSON simulando o banco de dados do aplicativo.

## Instruções e avisos de uso:

1 - Ao iniciar o aplicativo pela primeira vez será criado um JSON de histórico, faça o cadastro e ficará salvo podendo acessar o aplicativo.

2 - A tela de login mostra opções de email e senha; caso não tenha login, crie sua conta na opção inferior. Retorne e selecione visualmente em qual formato de negócio deseja conectar hoje (Consumidor ou Vendedor) clicando no botão correspondente antes de logar.

3 - No painel do **Consumidor**, o app se ramifica em abas (Início, Recarga, Histórico, Chat, Conta). A aba Início exibe o mapa de carregadores baseado na sua posição. Caso a localização não resolva instantaneamente, dirija-se à aba "Conta" e adicione seu CEP ou rua no sistema para reancorar o radar ao seu endereço real.

4 - O processo de recarga opera em camadas lógicas: ao entrar na aba, ocorre a busca simulada de Bluetooth; a partir daí selecione o carregador, escolha o modo de tempo ou dinheiro gasto e finalize na interface simulada do Pix. Feito o pagamento, a progressão inicia e a estação ficará indisponível a outros usuários até ser liberada.

5 - O histórico do Consumidor lê transações dinamicamente formatadas em formato de pilha (o uso mais recente no topo).

6 - O chat apresenta um chatbot feito para o aplicativo focado em responder perguntas referentes aos gastos e usos do usuário.

7 - A aba de conta permite ao usuário trocar aspectos como senhas ou informações pessoais e também trocar entre modo claro e escuro do aplicativo, ficando definido mesmo ao deslogar.

8 - No painel do **Vendedor**, o app se ramifica em abas (Início, Estações, Histórico, Descontos, Conta). A aba início mostra a receita gerada pelos carregadore e uma visão rápida para gerenciar cada estação.

9 - a aba de estações permite de maneira rápida adicionar, remover ou configurar cada estação, por meio de botões nos cards. Cada estação pode ser condigurada em: nome, CEP, tempo de máximo de uso por sessão, potência, preço por kWh, status.

10 - O histórico do Vendedor lê transações dinamicamente formatadas em formato de pilha (o uso mais recente no topo), podendo ser lidas em geral ou para cada estação de forma separada.

11 - A aba de descontos permite criar cupons dinâmicos à escolha do vendedor, necessitando, após clicar no botão, de: Código, descrição, qual estação será efetivado, data de validade e status.

12 - A aba de conta permite ao usuário trocar aspectos como senhas ou informações pessoais e dados bancários e também trocar entre modo claro e escuro do aplicativo, ficando definido mesmo ao deslogar.

13 - O aplicativo dispõe de salvamento persistente por conta; se fechar a janela com o JSON presente na pasta raiz, seus pontos de progresso, relatórios, histórico financeiro e estações ativas continuarão integralmente salvos. 


pip install flet pillow
python main.py
