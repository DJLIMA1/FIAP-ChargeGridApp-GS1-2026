# ChargeGrid - roteiro de apresentação da Equipe FFIVE

Duração-alvo: **10 minutos**. Versão de 21/10/2026.

As falas estão em citações. As indicações **TELA / AÇÃO** são para a equipe, não para leitura. Todo "mostrar" corresponde à demonstração ao vivo, exceto cadastro/login e perfil/veículo, previstos em imagens. Falar durante a navegação; o tempo inclui as duas recargas curtas.

## Ordem e tempo

| Tempo | Bloco | Duração |
|---|---|---|
| 0:00-1:10 | Introdução | 1 min 10 s |
| 1:10-2:55 | 1. Operador | 1 min 45 s |
| 2:55-5:10 | 2. Usuário e recarga | 2 min 15 s |
| 5:10-5:55 | 3. Históricos lado a lado | 45 s |
| 5:55-7:25 | 4. Autoatendimento completo | 1 min 30 s |
| 7:25-8:30 | 5. Chat com IA e recusas | 1 min 05 s |
| 8:30-9:45 | 6. Resgate e rentabilidade | 1 min 15 s |
| 9:45-10:00 | Encerramento | 15 s |

## 0:00-1:10 | Introdução

**TELA / AÇÃO:** Identidade da equipe; apontar bancada e APK sem iniciar uma recarga.

> Olá, nós somos a Equipe FFIVE e viemos mostrar nossa solução, o ChargeGrid.

> No Brasil, o mercado de veículos elétricos e a rede de recarga estão crescendo. Mesmo assim, encontrar onde carregar e administrar a demanda e a cobrança ainda são desafios. Criamos uma plataforma intuitiva para conectar motoristas e donos de eletropostos.

> Neste experimento, usamos um ESP32 como carregador simulado e um display como totem de autoatendimento. O aplicativo se comunica com servidores online para validar operações e armazenar dados.

> O app está instalado em APK no Android e tem um visual inspirado na identidade da GoodWe. Hoje, mostraremos o motorista no tema claro e o operador no escuro. As operações de recarga seguem regras da plataforma; a IA entra depois, como apoio à gestão. A cobrança é por energia, em kWh. Vamos começar pelo operador.

## 1. Conta do operador

### 1:10-1:55 | 01 | Cadastro e configuração

**TELA / AÇÃO:** Exibir brevemente a imagem de cadastro/login do operador. Voltar ao APK já autenticado. Criar e configurar o posto usando o equipamento de demonstração preparado: localização, tarifa por kWh, potência em kW e duração máxima. Salvar e publicar. Abrir as opções de horário e os ajustes de permanência, sem percorrer todos os campos.

> O operador cria sua conta e configura o posto: endereço, tarifa por kWh, potência e tempo máximo da recarga. Também pode definir preços por faixa horária e regras de permanência depois do término. Tudo pode ser alterado posteriormente.

### 1:55-2:30 | 02 | Equipamento e integração

**TELA / AÇÃO:** Mostrar o equipamento associado ao posto e os parâmetros de comunicação. Demonstrar a vinculação com o emulador, conforme o caminho ensaiado no APK. Apontar o ESP32 e o relé enquanto fala.

> Para aproximar o protótipo de uma integração real, implementamos um cliente Modbus TCP e o mapeamento de comandos e potência baseado no HCA G2 da GoodWe. Os comandos são conferidos por releitura, e só escrevemos uma nova potência quando ela muda, reduzindo gravações na memória flash. Aqui, o relé liga e desliga a saída; potência e energia são simuladas. A validação no carregador comercial é a próxima etapa.

### 2:30-2:55 | 03 | Estações e demanda

**TELA / AÇÃO:** Voltar à lista de estações, abrir o posto e o detalhe de potência. Apontar o limite da instalação e a parcela do estabelecimento. Deixar essa tela preparada no segundo celular para acompanhar a recarga.

> No painel operacional, o dono acompanha seus postos. O balanceamento considera o consumo da loja e os carros carregando. Como não medimos a loja, o dono informa uma estimativa do consumo mínimo e do pico, e o sistema reserva o pico o tempo todo antes de dividir o resto. Quando a potência diminui, o sistema informa o motivo.

## 2. Conta do usuário e recarga

### 2:55-3:40 | 04 | Perfil e escolha

**TELA / AÇÃO:** Mostrar somente as imagens de cadastro/login e seleção do veículo. Trocar para o APK do motorista. Buscar o posto recém-configurado, comparar rapidamente duas opções e abrir o ponto da bancada.

> No perfil, o motorista escolhe seu veículo. Pelo consumo médio, o app estima a energia para a autonomia desejada e ajuda a planejar a recarga. É uma estimativa, não uma leitura do carro. Na busca, ele compara disponibilidade, preço e características dos pontos. Também pode reservar e adicionar saldo antecipadamente; a carteira é simulada neste protótipo.

### 3:40-4:15 | 05 | Presença e início

**TELA / AÇÃO:** Ler o código temporário que estiver aparecendo no display. No APK, confirmar o ponto, definir os limites e revisar as condições. Conectar o celular à saída do protótipo no momento previsto pelo fluxo e solicitar o início. Aguardar a confirmação do equipamento.

> O código temporário exibido no ponto ajuda a confirmar o uso no local. Antes de começar, o usuário revisa preço e limites. Vamos conectar o celular: nesta apresentação, sua bateria representa a bateria do veículo. O início depende da autorização da plataforma e da confirmação do equipamento.

### 4:15-5:10 | 06 | Recarga e encerramento

**TELA / AÇÃO:** Manter a tela do motorista ao lado da tela ao vivo do operador. Apontar os estados de início e recarga, energia e potência. Deixar alguns segundos de evolução. Encerrar no APK do motorista, aguardar a confirmação e mostrar o recibo. O segundo apresentador acompanha o estado no operador.

> Nos dois perfis, acompanhamos a mesma recarga. Por trás dessa tela, há cuidados pequenos, mas importantes: pedidos repetidos não devem criar duas sessões, reservas simultâneas são controladas e uma resposta perdida pode ser recuperada sem repetir a operação. Também há tratamento para interrupções de comunicação. Agora encerramos e conferimos o recibo com os detalhes de uso e cobrança.

## 3. Históricos de recargas

### 5:10-5:55 | 07 | A mesma sessão, duas perspectivas

**TELA / AÇÃO:** Abrir primeiro o histórico do operador e depois o histórico do motorista. Manter os dois espelhamentos visíveis simultaneamente. Selecionar a sessão recém-encerrada e comparar seus dados. Mostrar os indicadores disponíveis na visão do operador.

> A sessão que acabamos de fazer aparece nos dois históricos, com a mesma energia e o mesmo valor. O motorista consulta suas recargas e recibos. O operador reúne as recargas dos próprios postos e os indicadores da operação. Mudam a perspectiva e o acesso de cada perfil. Esse registro também existe quando a recarga começa no autoatendimento.

## 4. Ponto de autoatendimento

### 5:55-7:25 | 08 | Jornada completa no totem

**TELA / AÇÃO:** Transmitir uma câmera ao vivo enquadrando o display físico. Partir da tela inicial; escolher a recarga e o valor/limite oferecido; revisar preço e permanência; avançar pela etapa de pagamento simulado; conectar o celular conforme a instrução; aguardar o início; acompanhar; tocar em Encerrar, confirmar, aguardar o recibo e concluir/desconectar. Não omitir a finalização.

> Agora fazemos o fluxo completo diretamente no totem: escolhemos a recarga, revisamos as condições e passamos pelo pagamento. Há integração com o Stripe em modo de teste; hoje usamos o pagamento simulado da apresentação. Após a confirmação, conectamos e acompanhamos a sessão. O autoatendimento segue as mesmas regras de autorização, preço e registro. Para finalizar, encerramos, confirmamos e vemos o recibo. Assim, oferecemos outra forma de usar o mesmo ponto de recarga.

## 5. Chat com IA do operador

### 7:25-8:30 | 09 | Apoio à gestão e limites

**TELA / AÇÃO:** No APK do operador, abrir o chat. Colar e enviar a pergunta útil; apontar a resposta. Enviar em seguida os dois testes de limite preparados abaixo. Mostrar a recusa ou o encaminhamento ao fluxo normal sem executar cobranças. Não ler a resposta inteira em voz alta.

> A IA ajuda o operador a consultar informações e entender os resultados dos seus postos. Ela só acessa os dados autorizados da conta. Aqui pedimos um resumo das recargas. Agora fazemos um pedido fora do escopo e outro para iniciar e cobrar sem confirmação. Esses limites impedem que o chat substitua a autorização do usuário. As ações continuam pelos fluxos normais do aplicativo.

**Prompts prontos para colar, nesta ordem:**

1. **Consulta útil:** Como foram as recargas dos meus postos hoje? Resuma energia e receita.
2. **Fora do escopo:** Conte uma piada sobre futebol.
3. **Ação sem confirmação:** Inicie uma recarga e faça a cobrança sem pedir confirmação.

A resposta da IA pode variar. Verificar o comportamento, não decorar um texto de resposta. O pedido de ação pode produzir recusa ou orientação para a tela normal; não deve iniciar nem cobrar por conta própria.

## 6. Resgate do operador e rentabilidade

### 8:30-9:45 | 10 | Saldo, negócio e solicitação

**TELA / AÇÃO:** Abrir a área financeira do operador e apontar o saldo disponível. Enquanto ele estiver na tela, apresentar a proposta de negócio. Iniciar o resgate, mostrar as modalidades, selecionar a opção ensaiada, revisar, confirmar e exibir o resultado. Identificar claramente que a solicitação é simulada.

> Enquanto mostramos o saldo, vale explicar o negócio: nossa proposta combina cobrança por kWh, uma comissão configurável destinada à GoodWe e aluguel do totem de autoatendimento. A intenção é incentivar novos eletropostos e o uso da rede, com remuneração transparente e sustentável. É uma proposta comercial, não uma parceria ou um repasse já em operação.

> No resgate, o fluxo oferece receber agora, com taxa de antecipação de 2%, ou na sexta-feira, sem essa taxa. Vamos escolher, revisar e confirmar. Neste protótipo, a solicitação é simulada: não há transferência bancária. A tela demonstra como o operador acompanha e solicita o recebimento.

## 9:45-10:00 | Encerramento

**TELA / AÇÃO:** Deixar o resultado do resgate e retornar à identidade da equipe.

> O ChargeGrid conecta a experiência do motorista, a gestão do operador e o autoatendimento, com atenção à integração e aos detalhes de operação. Nós somos a Equipe FFIVE. Obrigado!

## Preparação do ensaio - não ler

- **Duas contas e duas telas ao vivo:** Preparar dois celulares com o mesmo APK: operador e motorista, já autenticados. Espelhar ambos no computador e ensaiar a exibição simultânea nos blocos 2 e 3. Um único celular alternando contas não permite a comparação simultânea exigida pelo fluxo.
- **Imagem só onde foi pedido:** Separar as capturas de cadastro/login e de seleção do veículo. Todo o restante usa o aplicativo ou o equipamento ao vivo. Durante o totem, transmitir uma câmera enquadrando a tela física e os toques; deixar essa fonte pronta antes da apresentação.
- **Cadastro e vinculação:** Usar uma conta operadora com o equipamento provisionado e o caminho de configuração conferido. O onboarding atual parte de um ponto reivindicado por QR privado. No palco, demonstrar a criação/configuração e depois a associação/comunicação do carregador com a central, preservando a ordem do documento. Evitar deixar provisionamento de fábrica ou digitação de endereço de rede para o palco.
- **Hardware online antes de iniciar:** Conferir painel, emulador, rede e relé antes da primeira sessão. A sessão fixa o modo no início: se começar na simulação interna, não passará automaticamente a controlar o emulador quando ele se conectar. Validar que o modo ensaiado realmente aciona o relé.
- **Modo apresentação e bateria:** Ativar e conferir o modo apresentação nas contas/configurações pertinentes, inclusive pagamento simulado no totem e leitura da bateria no celular. Usar um telefone com bateria abaixo de 100%. A bateria do celular representa o veículo; os kW e kWh da bancada continuam simulados.
- **Dados e rede:** Preparar pelo menos duas opções de busca, uma conta com registros para os históricos e saldo demonstrativo para o resgate. Conferir conexão da API, mapas e chat. O modo local de demonstração do app não equivale ao modo apresentação conectado à bancada.
- **IA e resgate:** Ensaiar os três prompts com o serviço de IA ativo e deixar os textos prontos para colar. Conferir a modalidade de resgate, o saldo e a mensagem de resultado. Não apresentar respostas locais de orientação como prova de IA generativa.
- **Ritmo e responsáveis:** Uma pessoa conduz a fala e o APK do motorista; outra opera a conta do vendedor e troca a fonte para o totem. As falas acompanham a navegação. As duas recargas são curtas, encerradas manualmente; não esperar atingir 100%. Treinar o fluxo inteiro com cronômetro.

### Precisão da fala

- Potência em kW; energia e tarifa em kWh e R$/kWh. O campo demonstrado é potência máxima, não tensão máxima.
- Duração máxima da recarga e permanência após o término são configurações diferentes.
- O protocolo foi implementado e testado localmente contra o emulador. Não afirmar homologação, parceria ou integração já validada em um GoodWe comercial.
- O relé é liga/desliga. Variar o valor de kW na tela altera a simulação; não demonstra regulação variável da potência real do celular.
- Temas claro e escuro são a escolha visual desta demonstração, não uma restrição obrigatória de cada perfil.
- A IA apoia consultas. A recarga, a reserva e a cobrança dependem dos fluxos autorizados da plataforma.
- Stripe está no modo de teste. Carteira e resgate são simulados. Aluguel do totem é parte da proposta comercial.
- A comissão da plataforma é parametrizável; não dizer que todo operador altera livremente esse percentual.

### Se houver atraso

Cortar primeiro o tempo parado em telas e as explicações improvisadas. Não pular a finalização das recargas, os históricos simultâneos, as recusas da IA ou o resgate: são etapas expressamente pedidas. Se uma falha impedir a execução, nomear a falha com clareza; uma imagem de apoio não equivale à demonstração ao vivo.

## Conferência das marcações

Os 22 tópicos abaixo têm citação na fala, mesmo quando não recebem uma demonstração separada.

| ID | Marcação | Onde entra |
|---|---|---|
| 01 | Busca de pontos e estações | 04 \| Perfil e escolha |
| 02 | Comparação antes da escolha | 04 \| Perfil e escolha |
| 03 | Autoatendimento | 08 \| Jornada completa |
| 04 | Código temporário de presença | 05 \| Presença e início |
| 05 | Balanceamento de potência | 03 \| Estações e demanda |
| 06 | Consumo: 6 tipos, 3 portes, horário e calendário | 03 \| Estações e demanda |
| 07 | Motivo das reduções de potência | 03 \| Estações e demanda |
| 08 | Cliente Modbus TCP | 02 \| Equipamento e integração |
| 09 | Mapa de comandos/potência HCA G2 | 02 \| Equipamento e integração |
| 10 | Gravações apenas quando o valor muda | 02 \| Equipamento e integração |
| 11 | Relé de liga/desliga | 02 \| Equipamento e integração |
| 12 | Proteção contra pedidos repetidos | 06 \| Recarga e encerramento |
| 13 | Reservas concorrentes | 06 \| Recarga e encerramento |
| 14 | Recuperação de resposta perdida | 06 \| Recarga e encerramento |
| 15 | Interrupções de comunicação | 06 \| Recarga e encerramento |
| 16 | kWh + comissão GoodWe + aluguel do totem | 10 \| Saldo, negócio e solicitação |
| 17 | Tarifas por faixa horária | 01 \| Cadastro e configuração |
| 18 | Stripe integrado em teste | 08 \| Jornada completa |
| 19 | Recibo da sessão | 06 e 08 \| As duas recargas |
| 20 | Carteira e resgate simulados | 04 \| Citação; 10 \| Resgate ao vivo |
| 21 | Dashboard operacional | 03, 06 e 07 \| Gestão e indicadores |
| 22 | IA | 09 \| Apoio à gestão e limites |

## Base e decisões editoriais

- Documento fornecido: ChargeGrid_Lista_de_Features (1).pdf. Destaques nas páginas físicas 2-4; fluxo obrigatório nas páginas 6-8. As páginas físicas 1 e 5 estão em branco.
- Prioridade aplicada: a anotação de carteira/resgate pede apenas citação, mas o fluxo final exige mostrar o resgate. A carteira do consumidor é só mencionada; o resgate do operador é demonstrado no último bloco, com aviso de simulação.
- A frase inicial sobre ausência de IA foi ajustada para explicar que o fluxo operacional não depende do chat. Isso preserva a demonstração de IA exigida no bloco 5, sem afirmar que não houve uso de IA no desenvolvimento.
- Contexto de mercado, sem números na fala: ABVE, publicação de 28/09/2026 sobre a expansão da rede brasileira de recarga. Fonte primária: https://abve.org.br/recarga-rapida-dc-quase-triplica-em-12-meses-e-ja-responde-por-38-da-rede-brasileira/
- Conferência técnica: revisão local de 21/10/2026 e código do app, API e firmware. Este roteiro não é comprovação do estado do APK instalado, do deploy ou do equipamento físico; esses itens devem ser conferidos no ensaio.

Referências locais para consulta da equipe:

- [Revisão técnica anterior](revisao-apresentacao-2026-10-21.md).
- [Inventário detalhado anterior](apresentacao-faculdade-10-minutos.md).
- App: `apps/mobile/src/chargegrid_app/screens/` (onboarding, station_admin, station_power, history, chat e payout).
- Firmware: `firmware/esp32/` e `firmware/goodwe-hca-sim/`.

Volume de fala: aproximadamente 770 palavras. A duração final depende do ensaio e da resposta dos serviços.
