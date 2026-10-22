# ChargeGrid — guia para uma apresentação de 10 minutos

**Revisado em 21/10/2026**, sobre `main` no commit **`fc510e8` e as alterações locais presentes**, inclusive o novo mapa vetorial e os horários de tarifa ativáveis. A primeira análise usou `5f88d2a`, em 20/10. Entre esses commits mudaram 116 arquivos rastreados; as alterações locais foram consideradas separadamente. Código do produto não foi alterado por esta revisão.

Os **156 itens originais** foram reavaliados individualmente na [matriz de conferência](revisao-apresentacao-2026-10-21.md). O catálogo abaixo preserva seus IDs, corrige a redação necessária e acrescenta os achados novos na seção L.

Foram examinados app, painel React, API, modelos/migrações, regras compartilhadas, firmware do painel, firmware do emulador HCA, simuladores, mapas, testes e documentação mecânica. A análise dos arquivos CAD/G-code usa geradores, guias e relatórios; não é uma nova auditoria geométrica de todos os binários.

O guia descreve a implementação local. A versão publicada, as migrações da nuvem, a instalação nos aparelhos e a montagem elétrica não foram verificadas. **TCP/Modbus funcional em teste local, energia simulada e validação em hardware GoodWe são coisas distintas.**

## 1. A mensagem que deve conduzir a apresentação

> **“O ChargeGrid conecta a experiência do motorista, a operação do proprietário e o estado do equipamento. Nosso cuidado foi tratar o caminho inteiro: escolher, aceitar as condições, confirmar o comando, acompanhar e explicar o resultado.”**

O projeto fica mais convincente quando cada funcionalidade responde a uma situação concreta. Em vez de apenas listar tecnologias, mostre exemplos: duas pessoas tentando reservar o mesmo ponto; a loja aumentando o consumo; o motorista perdendo a conexão; o preço mudando antes do início; uma confirmação de pagamento chegando atrasada.

Os cinco destaques que eu preservaria mesmo com cortes de tempo:

1. **Integração local preparada para HCA G2**, com cliente Modbus TCP no painel e firmware de carregador emulado separado; ainda sem validação em um GoodWe real.
2. **Balanceamento considerando o consumo do estabelecimento**, agora com curva simulada por tipo/porte, além de ajuste confirmado antes de aproveitar a capacidade de outro carro.
3. **Pedido enviado e ação confirmada aparecem como estados diferentes**, do backend à interface.
4. **Preço e condições aceitas ficam registrados**, e o recibo explica os componentes do valor.
5. **Detalhes de uso e recuperação**, como código legível, QR privado separado, proteção contra toque repetido, dados antigos identificados e parada local.

## 2. Roteiro cronometrado — 10 minutos

São nove blocos de fala. Eles podem caber em sete slides, juntando abertura/jornada e qualidade/encerramento. A demonstração deve acontecer dentro dos tempos abaixo.

| Tempo | Assunto | O que mostrar | Detalhe pequeno para destacar |
|---|---|---|---|
| 0:00–0:45 | Problema e proposta | Motorista, proprietário e equipamento no mesmo fluxo | A promessa é “recarga com confirmação, do app ao ponto”. |
| 0:45–2:00 | Jornada do motorista e autoatendimento | Busca → revisão → início → acompanhamento; uma tela do totem | Código público legível e código temporário de presença têm papéis diferentes. |
| 2:00–3:20 | Preparação para GoodWe | API → painel mestre Modbus → ESP32 emulador HCA | Releitura confirma a escrita; gravar só quando muda poupa flash. |
| 3:20–4:40 | Gestão de potência | Exemplo de 30 kW, loja usando 12/24 kW e três carros | Um carro sozinho recebe seu máximo; contam as sessões em uso. |
| 4:40–5:50 | Confiabilidade e segurança | Estado pendente, confirmado e último dado recebido | Repetir um pedido não cria uma segunda sessão; reboot não reinicia recarga. |
| 5:50–7:00 | Preço, pagamento em teste e resultado | Revisão de preço, recibo e cascata financeira | Sem custo da energia informado, a margem fica desconhecida. |
| 7:00–8:20 | IA e previsão com critérios | Busca em linguagem natural e uma previsão | IA só consulta; o modelo de previsão precisa vencer a média para ser usado. |
| 8:20–9:20 | Visão do dono e acabamento | Potência dentro da estação, mapa vetorial e um detalhe físico | Atualização pausa com tela oculta; QR renderizado é decodificado nos testes. |
| 9:20–10:00 | Evidências, limite atual e próximo passo | Uma lâmina com testes e fronteira da bancada | Integração de software comprovada localmente; energia veicular ainda simulada. |

### 0:00–0:45 — problema e proposta

**Fala sugerida:**

“Para o motorista, encontrar um carregador é só o começo. Ele precisa saber se está disponível, quanto vai custar e se a recarga começou de verdade. Para o proprietário, a preocupação é acompanhar os pontos, controlar as condições e entender o resultado. O ChargeGrid reúne essas duas experiências com uma API e um painel físico. A ideia que orienta o projeto é recarga com confirmação, do app ao ponto.”

### 0:45–2:00 — jornada completa

**Fala sugerida:**

“O motorista compara pontos por conector, preço e disponibilidade, planeja sua recarga e revisa as condições antes de iniciar. Também há um fluxo de autoatendimento no totem. Um cuidado simples: o código que identifica o ponto é curto e evita caracteres que confundem, como zero e letra O. Já o código de presença muda a cada cinco minutos. E nenhum desses códigos é o segredo que permite vincular o equipamento ao proprietário.”

**Demonstração dentro do bloco:** abrir uma escolha já preparada, mostrar a revisão e o estado aguardando confirmação. Evitar preencher um cadastro inteiro ao vivo.

### 2:00–3:20 — GoodWe, com precisão

**Fala sugerida:**

“Agora temos um painel que atua como mestre Modbus TCP e um segundo firmware ESP32 que emula o HCA G2 de 7 kW. O protocolo já foi exercitado por TCP no computador. A decisão de potência vira uma escrita de registrador, e a confirmação só sai depois da releitura. Arredondamos para baixo e evitamos regravar a flash quando o valor não mudou. O adaptador Python também modela variantes de 11 e 22 kW; o novo firmware embarcado usa a de 7 kW. A energia continua simulada e a validação num GoodWe físico ainda é a próxima etapa.”

**Ressalva técnica:** o datasheet é uma fonte oficial para protocolo e características dos modelos. O mapa detalhado V1.0.15 foi obtido por transcrições públicas de um documento atribuído ao fabricante, com essa proveniência explicitada no código. Não apresentar esse mapa como uma publicação oficial acessada diretamente.

### 3:20–4:40 — balanceamento explicável

**Fala sugerida:**

“A capacidade disponível leva em conta o estabelecimento. Se a instalação tem 30 kW e a loja usa 12, sobram 18 para os carregadores, respeitando também os limites de cada equipamento e do motorista. Se a loja passa a usar 24, sobram 6. Com três pontos monofásicos compatíveis com esse piso, o exemplo pode ficar em 2 kW para cada um. A parte mais importante é a transição: o sistema espera a confirmação das reduções antes de aproveitar essa folga em outro ponto. E mostra ao motorista o motivo da limitação.”

**Limite a explicar se perguntarem:** um salto no consumo da loja pode produzir excesso transitório enquanto as reduções aguardam confirmação. O sistema registra esse excesso. Não é uma garantia elétrica de proteção instantânea. O consumo predial atual é simulado automaticamente por tipo, porte e horário; um valor manual de demonstração vale por 30 minutos. O exemplo 30/12/24 kW exige esse cenário controlado, pois o padrão automático pode dar outros valores.

### 4:40–5:50 — quando a rede falha

**Fala sugerida:**

“Enviar um pedido não prova que o equipamento executou. Por isso reserva, início e parada têm estados pendentes e confirmação. Se a resposta se perder, o mesmo pedido pode ser repetido sem criar uma segunda sessão. Se duas pessoas tentarem reservar o mesmo ponto, a proteção também existe no banco. Na bancada, 45 segundos sem comunicação encerram a sessão localmente. Depois de um reboot, a recarga não recomeça sozinha. E o app informa quando está mostrando o último estado conhecido.”

**Detalhe extra, se couber:** “Fechar o app não é tratado como uma ordem para parar o equipamento.”

### 5:50–7:00 — preço e resultado compreensíveis

**Fala sugerida:**

“O proprietário configura tarifa por horário e regras de demanda. O preço aceito fica registrado na reserva ou no início, e o recibo explica tarifa, desconto, energia e eventuais ajustes. Existe integração Stripe em modo teste, com confirmação no servidor, captura parcial ou devolução da diferença conforme o método. Para o dono, o painel separa receita, comissão, repasse e custo da energia. Um detalhe importante: se ele não informou o custo, o sistema não inventa uma margem usando custo zero.”

**Se mostrar permanência:** “A recarga pode acabar e o carro continuar conectado. São estados separados, com tolerância e teto aceitos antes; lacunas sem evidência de conexão não entram na cobrança.”

### 7:00–8:20 — IA e previsão que precisam justificar seu uso

**Fala sugerida:**

“A IA consulta postos e dados permitidos da conta, ajuda na busca e explica resultados. Ela não inicia uma recarga nem cobra: oferece um botão que leva à confirmação normal. Sem o provedor, há orientações locais e respostas por regras. A previsão de ocupação é outra implementação, separada do chat: compara um modelo estatístico com uma média histórica e só usa o modelo quando ele reduz o erro pelo critério definido. A tela mostra o método escolhido, a qualidade e quando existe histórico sintético.”

**Número opcional:** no teste offline sintético documentado, o erro médio de ocupação caiu de 16,08 para 14,98 pontos percentuais. Dizer imediatamente que o teste usa dados sintéticos e não comprova desempenho comercial real.

### 8:20–9:20 — operação e acabamento

**Fala sugerida:**

“No painel do proprietário, os indicadores e alertas ficam na visão geral, e a potência é acompanhada dentro da estação. No app, o novo mapa vetorial preserva a câmera quando os pontos atualizam. Trabalhamos também nos detalhes: contraste testado nos dois temas do app, formulários que preservam os campos, proteção contra toque repetido e atualização que pausa quando o app fica oculto. No painel físico, o fluxo de autoatendimento tem estados próprios e retoma um pedido após falha de rede. Os testes chegam a renderizar e decodificar os QRs, verificando o conteúdo, além da aparência.”

**Objeto físico opcional:** apontar o projeto de case/manutenção ou a carcaça Mini. Informar o estágio real da peça que estiver levando; os arquivos mecânicos não comprovam a parte elétrica do Mini.

### 9:20–10:00 — fechar com evidência e próximo passo

**Fala sugerida:**

“Nesta revisão, passaram 1.607 testes nos grupos executados, incluindo a API com PostgreSQL e Modbus TCP local. Dois testes do app ainda falham em expectativas de energia e bateria que não consideram o novo limite aplicado. Também validamos controlador e telas no computador. A energia continua simulada e o pagamento é de teste. O próximo passo é conferir a montagem da bancada e validar a integração num HCA G2 físico.”

**Frase final:** “A preocupação foi fazer cada tela corresponder a um estado verificável do sistema.”

## 3. O ponto GoodWe que você comentou

O achado mais alinhado à sua observação está em [`adaptador-hca-g2.md`](adaptador-hca-g2.md), no [adaptador](../packages/chargegrid_core/chargegrid_core/chargers/goodwe_hca_g2.py) e no [contrato de aplicação e releitura](../packages/chargegrid_core/chargegrid_core/chargers/base.py).

**Formulação recomendada para a apresentação:**

> “Implementamos um cliente Modbus TCP no painel e um carregador HCA G2 emulado em firmware separado. Os testes locais exercitam o protocolo e a confirmação por releitura. Potência e energia ainda são simuladas; a compatibilidade com um GoodWe físico precisa ser validada.”

Isso demonstra preparação concreta. Evitar “já integra com o carregador oficial”, “é homologado pela GoodWe” ou “implementamos a API oficial GoodWe”.

O [datasheet oficial HCA G2](https://en.goodwe.com/Ftp/EN/Downloads/Datasheet/GW_HCA-G2_Datasheet-EN.pdf), consultado na primeira análise de 20/10, informa **Modbus TCP** e variantes **7/11/22 kW**. Ele não comprova que este adaptador funcione fisicamente, nem fornece por si só o mapa usado no projeto. A existência do aplicativo SEMS+ do fabricante também não comprova acesso a uma API externa de comandos.

### Detalhes do adaptador que rendem boas frases

| Detalhe verificado | Por que importa | Frase possível |
|---|---|---|
| Python modela GW7K/GW11K/GW22K; o firmware novo emula GW7K | Separa alcance do adaptador de alcance do embarcado | “O firmware atual é de 7 kW; as outras variantes estão modeladas no Python.” |
| Piso de 1,4 kW monofásico e 4,2 kW trifásico no mapa implementado | Evita comandar uma potência abaixo do mínimo modelado | “Quando não cabe o mínimo, o ponto pausa.” |
| Passos de 100 W e arredondamento para baixo | Evita exceder o limite decidido por arredondamento | “A conversão para o registrador nunca arredonda para cima.” |
| Registrador 10029 controla a potência máxima por ponto | Tradução específica em vez de comando genérico sem significado | “A decisão em watts vira um valor do mapa do equipamento.” |
| 10060 modela pausa e retomada | Zero de potência tem semântica própria | “Pausar não precisa encerrar toda a sessão.” |
| Só escreve o valor quando muda | Reduz gravações em registrador que usa flash | “Pensamos até no desgaste da memória do carregador.” |
| Não escreve 10024, 10025 e 10026 | Não confunde gestão interna e limite do local com limite do ponto | “Separamos o teto de cada ponto da configuração elétrica da instalação.” |
| Releitura após escrita | Um envio bem-sucedido não basta | “A confirmação depende do valor relido.” |
| Falhas de escrita podem ser injetadas no simulador | Exercita o caminho de erro | “Também testamos quando o comando se perde.” |
| Classe Python antiga de TCP é desabilitada, mas há cliente TCP C++ no painel | Corrige o alcance da afirmação antiga | “Agora há transporte TCP implementado; o equipamento que responde ainda é um emulador.” |
| Proveniência e confiança por registrador | Distingue documento, observação comunitária e inferência | “Registramos de onde veio cada informação do protocolo.” |
| Tradução na borda, agora no painel mestre Modbus | A nuvem não precisa acessar a rede local do carregador | “A API decide; o painel traduz e conversa pela rede local.” |

## 4. Catálogo minucioso: detalhes para distribuir pela fala ou guardar para perguntas

Os itens abaixo são um repertório. Tentar falar todos em dez minutos prejudicaria a apresentação. Escolha de cinco a oito detalhes pequenos para encaixar nos blocos principais e mantenha o restante como apoio.

### A. Experiência do motorista

Evidências: [busca e seleção no backend](../apps/api/app/modules/stations/discovery.py), [planejamento de recarga](../apps/mobile/src/chargegrid_app/services/booking.py), [confiança na jornada](../apps/mobile/tests/test_journey_trust.py), [navegação](../apps/mobile/src/chargegrid_app/navigation.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| A1 | Filtros por conector, disponibilidade e preço | “A busca considera compatibilidade e custo antes da escolha.” |
| A2 | Conector normalizado: Tipo 2/type2 e CCS/ccs2 | “Variações de escrita não atrapalham a busca.” |
| A3 | Preço e características do cartão se referem ao mesmo ponto elegível | “O preço barato exibido não pertence a um conector incompatível escondido no posto.” |
| A4 | Distância é calculada a partir da referência da busca | “A proximidade tem uma referência explícita.” É distância geográfica, não trajeto viário. |
| A5 | Intenção de tempo ou orçamento acompanha a escolha | “O usuário não precisa refazer o planejamento em cada etapa.” |
| A6 | Fluxo também contém planejamento por autonomia estimada | “O motorista pode pensar em quilômetros; o sistema converte para energia.” Depende do consumo e capacidade usados na estimativa. |
| A7 | Autonomia estimada é limitada ao espaço livre da bateria modelada | “Não prometemos uma quantidade de energia que a bateria estimada não comporta.” |
| A8 | Limites de duração e custo são revisados antes do início | “O usuário sabe quais condições está aceitando.” |
| A9 | Nova tarifa, potência ou condição exige nova revisão | “Uma mudança entre escolher e iniciar não passa escondida.” |
| A10 | Voltar preserva filtros, local e rascunho quando válido | “Navegar para trás não obriga a começar do zero.” |
| A11 | Estado de reserva/sessão muda a ação principal | “Quem já tem uma recarga encontra o acompanhamento.” |
| A12 | Perda de resposta mantém a identidade do pedido original | “Resultado desconhecido não vira automaticamente uma nova recarga.” |

### B. Identidade do equipamento e segurança de acesso

Evidências: [segurança](../apps/api/app/security.py), [vinculação](../apps/api/app/modules/ownership/routes.py), [código temporário](../apps/api/app/presence_code.py), [modelos](../apps/api/app/models.py), [provisionamento](../tools/provision_point.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| B1 | Código público `CG-` curto exclui 0/O e 1/I | “O código foi pensado para ler e ditar sem confusão.” |
| B2 | Código temporário `#F` muda a cada cinco minutos | “A confirmação usa um código atual mostrado pelo painel.” Não é prova inviolável de presença. |
| B3 | Código temporário usa segredo do posto e HMAC | “Não é apenas um número fixo impresso.” |
| B4 | Segredo de propriedade é diferente do código público | “Saber qual é o carregador não concede sua propriedade.” |
| B5 | Chave de comunicação também é independente do segredo de propriedade | “Identificação, vinculação e comunicação têm credenciais próprias.” |
| B6 | Banco armazena hashes de chave do dispositivo e claim | “As consultas comuns não devolvem a credencial original.” |
| B7 | Chave individual pode ser revogada ou rotacionada | “É possível retirar o acesso de um equipamento específico.” |
| B8 | Equipamento provisionado começa inativo e sem dono | “Cadastro de fábrica não publica automaticamente um ponto.” |
| B9 | Claim pelo mesmo dono é idempotente; outro dono é recusado | “Repetir a vinculação não transfere o equipamento.” |
| B10 | Declarar-se vendedor não concede acesso a posto alheio | “A autorização verifica a propriedade de cada recurso.” |
| B11 | JWT verifica assinatura, emissor, audiência e expiração | “Não basta enviar um identificador de usuário.” |
| B12 | Clientes passam pela API; há separação entre credencial de migração e execução | “As regras e permissões ficam no servidor.” Conferir aplicação das concessões no ambiente implantado. |

### C. Consistência de backend e banco

Evidências: [serviço comum](../apps/api/app/service.py), [início de recarga](../apps/api/app/modules/charging/service.py), [sincronização](../apps/api/app/modules/devices/service.py), [testes de controle](../apps/api/tests/test_control.py), [eventos](../apps/api/app/session_events.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| C1 | Estados `starting`, `charging`, `stopping` são diferentes | “A interface acompanha o ciclo real do comando.” |
| C2 | `Idempotency-Key` combina operação, usuário e corpo | “O mesmo pedido pode ser repetido sem duplicar o efeito.” |
| C3 | Mesma chave com conteúdo diferente gera conflito | “Uma tentativa de recuperação não pode trocar silenciosamente as condições.” |
| C4 | Travas transacionais serializam reservas concorrentes | “Duas pessoas não recebem confirmação para a mesma vaga.” |
| C5 | Índices únicos parciais reforçam reserva/sessão ativa por usuário e ponto | “A consistência também é protegida no banco.” |
| C6 | Comandos têm versão e validade | “Comando antigo ou expirado não volta a iniciar uma recarga.” |
| C7 | Telemetria identifica dispositivo, boot e sequência | “Reenvios podem ser reconhecidos.” |
| C8 | Replay não renova artificialmente o contato do dispositivo | “Uma mensagem velha não faz o ponto parecer online.” |
| C9 | Energia cumulativa não pode regredir na atualização da sessão | “Leituras inconsistentes são recusadas em vez de distorcer o histórico.” |
| C10 | Eventos têm chaves únicas | “Uma confirmação repetida não duplica o fato no histórico.” |
| C11 | Horário de captura e de recebimento são distintos | “O sistema sabe separar quando se mediu e quando a informação chegou.” |
| C12 | Código temporário ambíguo exige seleção explícita | “Uma coincidência entre códigos não manda o usuário para outro posto.” |

### D. Gestão de potência e comportamento diante de falhas

Evidências: [regra de balanceamento](../packages/chargegrid_core/chargegrid_core/balancing.py), [coordenação na API](../apps/api/app/modules/power/service.py), [testes de potência](../apps/api/tests/test_live_power.py), [controlador embarcado](../firmware/esp32/src/charging_controller.cpp).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| D1 | Disponível considera limite efetivo menos consumo simulado por perfil ou valor temporário | “A loja e os carregadores compartilham a instalação; o consumo atual ainda é uma simulação.” |
| D2 | Há teto adicional dos carregadores do posto | “O limite da instalação e o limite da recarga são conceitos separados.” |
| D3 | Pedido respeita nominal, limite do ponto, motorista e equipamento | “A potência final respeita a restrição mais baixa.” |
| D4 | Só sessões participantes disputam a divisão | “Um carro sozinho não fica limitado porque há tomadas vazias.” |
| D5 | Sem capacidade para todos os pisos, chegada anterior tem prioridade | “A pausa segue uma regra previsível.” Não alegar otimização por prazo ou justiça perfeita. |
| D6 | Firmware sem ajuste ao vivo é tratado como carga fixa | “O sistema considera a capacidade real de cada versão.” |
| D7 | Potência alvo, aplicada e estado ficam separados | “O valor desejado não aparece como se já tivesse sido aplicado.” |
| D8 | Aumento usa a folga confirmada, incluindo comandos pendentes | “Não distribuímos duas vezes a mesma capacidade.” |
| D9 | Redução sem confirmação é repetida uma vez; segunda falha leva a STOP | “Há um caminho de falha definido para o ajuste.” |
| D10 | Ponto offline mantém sua capacidade comprometida no cálculo | “Perder comunicação não prova que ele parou.” |
| D11 | Decisão registra entradas, motivo e eventual excesso transitório | “A limitação pode ser auditada e explicada.” |
| D12 | Mesmo motivo aparece em versão longa e curta | “App, dashboard, recibo e painel físico conseguem explicar a decisão.” |
| D13 | 0 W pausa a sessão sem acumular energia simulada | “Pausa e encerramento não são confundidos.” |
| D14 | Há três tempos: 45 s sem API, 5 s de perda do carregador na sessão Modbus e 15 s sem mestre no emulador | “Cada trecho da comunicação tem seu tratamento de falha; reboot não retoma a recarga.” Sem alegar proteção elétrica certificada. |

### E. Preço, recibo e resultado financeiro

Evidências: [tarifação](../packages/chargegrid_core/chargegrid_core/pricing.py), [recibo](../packages/chargegrid_core/chargegrid_core/receipt.py), [resultado](../packages/chargegrid_core/chargegrid_core/economics.py), [rotas de recibo](../apps/api/app/modules/receipts/routes.py), [permanência](../apps/api/app/overstay.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| E1 | Tarifa pode variar por horário e demanda | “O dono configura a política; o sistema calcula de forma determinística.” |
| E2 | Intervalos ativos sobrepostos são recusados, inclusive cruzando meia-noite/semana; intervalos desligados podem coexistir | “É possível desativar um horário sem apagá-lo; a reativação precisa respeitar os demais.” |
| E3 | Condições de preço são congeladas na reserva/início ou orçamento pago | “A sessão preserva o que foi aceito.” |
| E4 | Cupom, base, multiplicador e motivo acompanham os termos | “O recibo explica de onde veio o preço.” |
| E5 | Cupom ignora diferenças de maiúsculas/minúsculas | “Digitar o mesmo código em outra caixa não invalida o desconto.” |
| E6 | Dinheiro usa `Decimal` e regra explícita de arredondamento | “O centavo exibido segue o mesmo cálculo do servidor.” |
| E7 | Totais financeiros somam linhas arredondadas | “As linhas do relatório fecham com o total.” |
| E8 | Receita, comissão, tarifa do provedor, repasse e energia são separados | “O dono entende o caminho até a margem.” |
| E9 | Custo da energia ausente não vira zero | “Dado desconhecido continua desconhecido.” |
| E10 | Margem negativa é preservada e pode gerar aviso | “O painel não esconde um resultado desfavorável.” |
| E11 | Recibo diferencia provisório e confirmado | “Uma sessão ainda em andamento não vira comprovante final.” |
| E12 | Origem simulada/medida e bases estimadas aparecem no modelo | “O relatório carrega a origem dos números.” |
| E13 | Recarga concluída e veículo desconectado são estados distintos | “Parar a carga não significa liberar a vaga.” Na bancada, conexão também é simulada. |
| E14 | Permanência cobra só intervalos completos confirmados, com tolerância e teto | “A cobrança modelada é limitada e depende de evidência.” |
| E15 | Lacunas offline não são cobradas como tempo comprovado | “Ausência de informação não vira cobrança.” |
| E16 | Sem versão de termos aceita, permanência pode ser registrada com taxa zero | “Uma versão antiga do app não aceita uma taxa por omissão.” |

### F. Pagamento em teste e totem

Evidências: [gateway Stripe](../apps/api/app/modules/payments/gateway.py), [serviço de pagamento](../apps/api/app/modules/payments/service.py), [totem na API](../apps/api/app/modules/kiosk_totem/service.py), [fluxo C++](../firmware/esp32/src/kiosk_flow.cpp), [validação do totem](../apps/api/tests/test_kiosk_totem.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| F1 | Gateway Stripe aceita somente chaves de teste | “Este fluxo Stripe opera em modo teste.” Isso não é uma certificação geral de segurança financeira. |
| F2 | Checkout é hospedada pelo provedor | “O fluxo evita receber dados de cartão no app e na API.” |
| F3 | Retorno do navegador não confirma pagamento | “A confirmação vem de webhook assinado ou consulta do servidor.” |
| F4 | Captura/devolução usam idempotência | “Uma resposta perdida não deve duplicar o acerto.” |
| F5 | Cartão tem captura parcial; Pix pode devolver a diferença | “O valor final é conciliado com o consumo modelado.” Métodos disponíveis dependem da configuração. |
| F6 | Pagamento tardio após expiração não inicia automaticamente | “Uma confirmação atrasada tem tratamento próprio.” |
| F7 | Pedido aberto do totem bloqueia disputa do app pelo mesmo ponto | “Os dois canais compartilham a mesma regra de ocupação.” |
| F8 | Orçamento do totem usa a regra comum de preço | “Escolher outro canal não muda arbitrariamente o cálculo.” |
| F9 | Método simulado/Stripe vem do servidor | “O painel não escolhe sozinho uma forma mais permissiva de pagar.” |
| F10 | Pedido aberto fica na NVS para recuperação | “Após reboot, o totem verifica o pedido anterior.” Isso não autoriza reiniciar a recarga. |
| F11 | Mesmo no autoatendimento, START vem pelo fluxo autorizado normal | “Pagamento e energização não são o mesmo comando.” |
| F12 | Histórico e exportações carregam canal e método | “O operador distingue uma sessão do app de uma iniciada no totem.” |

### G. IA, busca natural e privacidade

Evidências: [prompt e limites](../packages/chargegrid_core/chargegrid_core/ai/prompt.py), [laço](../packages/chargegrid_core/chargegrid_core/ai/loop.py), [fonte autorizada](../apps/api/app/modules/ai/source.py), [serviço](../apps/api/app/modules/ai/service.py), [documentação e benchmark](ia-openrouter.md).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| G1 | Ferramentas consultam dados, sem iniciar, parar, reservar ou cobrar | “A IA ajuda a decidir; a ação passa pela confirmação normal.” |
| G2 | Identidade vem do usuário autenticado, sem `user_id` escolhido pelo modelo | “O modelo não escolhe de quem vai consultar o histórico.” |
| G3 | Indicadores de proprietário exigem permissão | “A IA respeita o mesmo recorte de acesso.” |
| G4 | Botões são derivados de IDs retornados pelas ferramentas | “O texto do modelo não inventa um destino interno.” |
| G5 | Fonte de leitura evita chamar conciliação que pode emitir comandos | “Até a consulta foi separada de rotinas com efeito.” |
| G6 | Regras tratam nomes e endereços como dados não confiáveis | “Uma instrução maliciosa no nome de um posto não deve mudar o papel do assistente.” Há testes, sem garantia absoluta contra toda injeção. |
| G7 | Orçamento de tempo, rodadas, mensagens e chamadas é limitado | “A conversa não cresce indefinidamente em custo e latência.” |
| G8 | API encerra a transação antes de aguardar o provedor | “O banco não fica preso enquanto a IA pensa.” |
| G9 | Uso registra custo, latência e ferramentas, sem salvar perguntas e respostas nessa tabela | “A observação técnica evita criar um histórico de conversa desnecessário.” O provedor ainda recebe o contexto necessário. |
| G10 | Falha do provedor tem fallback identificado | “O usuário sabe quando recebeu uma orientação local ou uma resposta por regras.” |
| G11 | Benchmark inclui português, ferramentas, ação e injeção | “A escolha do modelo foi avaliada pelo comportamento necessário no produto.” Resultados são do ensaio documentado. |
| G12 | Chave externa fica no backend e demo local é excluída do APK | “A credencial não precisa viajar com o aplicativo.” |

### H. Previsão e cuidado com os dados

Evidências: [documentação da previsão](previsao-ocupacao.md), [agregador](../packages/chargegrid_core/chargegrid_core/forecast/aggregate.py), [avaliação](../packages/chargegrid_core/chargegrid_core/forecast/evaluate.py), [rollup](../apps/api/app/modules/forecast/rollup.py), [tela](../apps/owner-web/src/pages/Forecast.tsx).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| H1 | Histórico por conector/hora é persistido | “Podemos conservar o histórico útil sem guardar toda telemetria para sempre.” |
| H2 | Energia usa diferenças de contador cumulativo | “Não somamos várias vezes a mesma energia.” |
| H3 | Agregação trata regressão de contador e virada de hora | “Reboot e mudança de hora não criam energia negativa ou duplicada.” |
| H4 | Energia horária conserva o total final da sessão | “O detalhe por hora precisa fechar com o total.” |
| H5 | Dados reais/simulados prevalecem sobre sintéticos na composição prevista | “Dado de demonstração não substitui observação operacional.” |
| H6 | Seed sintético não cria sessões nem receita | “Podemos demonstrar previsão sem fabricar faturamento.” |
| H7 | Modelo é comparado com baseline histórico | “A complexidade precisa melhorar uma referência simples.” |
| H8 | Avaliação separa períodos e inclui postos não vistos | “O resultado é medido fora das amostras de treino.” Tudo ainda sintético no ensaio offline. |
| H9 | Backtest do posto usa apenas passado e exige histórico suficiente | “A escolha do método depende também daquele posto.” |
| H10 | Modelo só é escolhido com WAPE no máximo 95% do baseline | “Ele precisa errar pelo menos 5% menos pelo critério usado.” |
| H11 | Faixa insuficientemente avaliada aparece como não calibrada | “A tela não inventa certeza estatística.” |
| H12 | Treino é offline; API avalia árvores exportadas em Python puro | “Não precisamos carregar a biblioteca de treinamento em cada requisição.” |
| H13 | Previsão de energia usa a média porque ela foi melhor para esse objetivo | “O método vencedor para ocupação não é imposto a todas as métricas.” |
| H14 | Sugestão de tarifa exige revisão do proprietário | “A previsão não altera o preço sozinha.” |
| H15 | Melhor horário explica preço estimado e ocupação | “Ajuda o motorista a escolher sem prometer preço futuro garantido.” |
| H16 | Manutenção respeita a marca da agregação antes de apagar telemetria | “Limpeza de dados não destrói a base ainda não consolidada.” |

### I. Painel do proprietário e qualidade de interface

Evidências: [painel React](../apps/owner-web/README.md), [rotas](../apps/owner-web/src/App.tsx), [potência da estação](../apps/owner-web/src/components/station/PowerCard.tsx), [cliente web](../apps/owner-web/src/api/client.ts), [acessibilidade do app](../apps/mobile/tests/test_brand_accessibility.py), [navegação](../apps/mobile/tests/test_motion_navigation.py), [cache](../apps/mobile/tests/test_speed.py).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| I1 | Visão geral reúne energia, receita, ocupação, reservas e não comparecimento | “O dono acompanha utilização e operação no mesmo lugar.” |
| I2 | Mapa de calor e ranking mostram padrões por ponto e horário | “O painel ajuda a localizar concentração e ociosidade.” |
| I3 | Alertas levam à estação correspondente | “O problema tem contexto e um caminho de ação.” |
| I4 | Filtros de período/estação acompanham relatórios | “O arquivo exportado respeita o recorte escolhido.” |
| I5 | Períodos usam o fuso de São Paulo | “Hoje começa na meia-noite local, e não na virada de UTC.” |
| I6 | Exportação CSV neutraliza fórmulas de texto | “Um nome cadastrado não deve virar uma fórmula ao abrir a planilha.” |
| I7 | Datas ausentes, sem histórico e dados desconhecidos têm estados próprios | “Ausência de dado não é mostrada como uma medição zero.” |
| I8 | Edição do painel aguarda resposta do servidor | “A tela não diz que salvou antes de receber confirmação.” |
| I9 | Consultas simultâneas compartilham renovação de token | “Expirar a sessão não dispara uma corrida de vários refreshes.” |
| I10 | Queda de rede não é tratada automaticamente como logout | “Problema de conexão e credencial inválida são situações diferentes.” |
| I11 | App pausa polling oculto e recua durante falhas | “Economizamos bateria, dados e chamadas quando não há tela ativa.” |
| I12 | Cache de leitura não substitui consultas de operações sensíveis | “Velocidade não transforma pagamento ou comando em dado antigo.” |
| I13 | Toque repetido e navegação durante ação pendente são controlados | “Um toque nervoso não vira uma segunda solicitação.” |
| I14 | Formulário alterado pede decisão antes de descartar | “O app protege o trabalho já digitado.” |
| I15 | Contraste ≥4,5:1 é testado em textos e badges compartilhados nos dois temas | “O visual foi verificado além da preferência estética.” Isso não certifica acessibilidade integral. |
| I16 | Foco de teclado, semântica de aba e movimento reduzido têm tratamento | “Há preocupação com formas diferentes de navegar.” |
| I17 | Mapas atuais usam MapLibre/OpenFreeMap, com carregamento e opção de tentar novamente | “Se o mapa falhar, mostramos a falha; o fallback esquemático pertence ao caminho antigo.” A demo também precisa de rede para tiles. |
| I18 | Fontes web são locais e páginas carregam sob demanda | “Há cuidado com dependências e carregamento.” |
| I19 | Mock web é condicionado a desenvolvimento e há verificação do build | “Os números fictícios não precisam entrar no pacote publicado.” |
| I20 | APK tem consulta de versão e oferta de atualização | “Também pensamos na continuidade depois da primeira instalação.” O usuário confirma a instalação. |

### J. Painel físico, scanner e engenharia de manutenção

Evidências: [firmware](../firmware/esp32/README.md), [scanner](../apps/mobile/packages/chargegrid_scanner/README.md), [validador](../tools/validate_firmware.py), [case do painel](case-tela-waveshare-7/README.md), [plano Mini](plano-prototipo-usb.md), [revisão mecânica v9](prototipo-usb/ender3-pla-oficial-v9/REVISAO-FINAL-2026-10-15.md).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| J1 | Painel sem configuração mostra estado de configuração, sem inventar ponto | “O primeiro uso tem um estado próprio.” |
| J2 | Configuração de Wi-Fi mascara senha e não a envia ao log | “A manutenção evita expor a credencial na frente de outras pessoas.” |
| J3 | Limpar rede e trocar identidade são operações separadas | “Manutenção de conectividade não precisa apagar o vínculo.” |
| J4 | Alterações sensíveis são bloqueadas durante estados incompatíveis | “A configuração não interrompe uma sessão inadvertidamente.” |
| J5 | Parada local não depende do app; em sessão Modbus solicita desligamento e verifica o carregador | “A parada pode partir do painel.” Sem confirmação, há repetição e watchdog; estado da tela não mede abertura física do relé. |
| J6 | Não há comando serial START de manutenção | “Diagnóstico não cria um atalho para iniciar fora da autorização normal.” |
| J7 | QR de propriedade desaparece depois da vinculação | “O segredo não fica exposto como se fosse o código público.” |
| J8 | Testes decodificam QR realmente renderizado pelo LVGL | “Não basta desenhar algo parecido com um QR.” |
| J9 | Scanner Android usa decodificação local e não exporta imagem | “A leitura do QR não precisa enviar a câmera a um serviço.” |
| J10 | Câmera começa por ação explícita e encerra antes de entregar a leitura | “A permissão e o uso da câmera têm começo e fim definidos.” |
| J11 | Cancelamento, retorno e permissão tardia liberam a câmera | “Fechar o scanner não deixa uma captura perdida em segundo plano.” |
| J12 | Há alternativa de colar código em plataforma sem scanner | “Uma limitação da câmera não encerra o fluxo.” |
| J13 | Fluxo do totem é C++ puro separado do desenho LVGL | “Podemos testar a jornada e trocar o visual sem misturar as duas responsabilidades.” |
| J14 | Telas do totem são criadas/liberadas conforme uso | “A interface considera a memória limitada da placa.” |
| J15 | Firmware novo reconhece campos recusados por API anterior | “Existe uma estratégia de compatibilidade entre versões.” |
| J16 | Case do painel prevê USB, RESET/BOOT, ventilação e desmontagem | “O objeto foi pensado para uso e manutenção.” Projeto digital; impressão/encaixe completo não comprovados nesta revisão. |
| J17 | Case foi dividido para o volume da impressora e tem amostras de encaixe | “Podemos testar a tolerância antes de gastar material na peça inteira.” |
| J18 | Mini mantém CAD com bandeja/berços substituíveis; há também firmware novo de emulador HCA com relé | “A mecânica facilita manutenção, e o emulador tem software próprio.” Não confundir liga/desliga do relé com controle variável de potência USB. |
| J19 | Revisões mecânicas registram colisões, movimentos, perfis e hashes | “A peça é reproduzível e tem histórico de verificação.” São verificações digitais. |
| J20 | Revisão R10 muda orientação/fatiamento somente da peça 5 e registra preservação das demais | “A correção considera o que já foi produzido e evita refazer peças sem necessidade.” Impressão física R10 ainda não comprovada. |

### K. Organização e testes

Evidências: [núcleo](../packages/chargegrid_core/README.md), [verificação de cópias](../tools/sync_core.py), [CI](../.github/workflows/ci.yml), [orçamento de consultas](../apps/api/tests/test_query_budget.py), [migrações](../apps/api/migrations/versions).

| ID | Detalhe | Como explicar o valor |
|---|---|---|
| K1 | Regras de domínio puras ficam em pacote compartilhado | “Preço e cálculo não precisam ser reinventados em cada tela.” |
| K2 | Cópias para app/API têm checagem de igualdade | “A distribuição do pacote tem proteção contra divergência.” |
| K3 | Migrações versionam mudanças no banco | “O esquema pode evoluir de forma reproduzível.” |
| K4 | Consultas em lote e agregações SQL evitam N+1 | “A quantidade de consultas não precisa crescer uma vez por ponto exibido.” Há testes específicos; sem novo benchmark de carga nesta revisão. |
| K5 | Testes cobrem concorrência, repetição e comunicação perdida; API completa reexecutada em PostgreSQL descartável | “A verificação considera caminhos de erro, inclusive na camada de banco.” Foram 425 testes de API aprovados. |
| K6 | Teste de importação exige nome de banco descartável | “A própria validação contém proteção para não apagar o banco errado.” |
| K7 | CI configura API/PostgreSQL, app, core, scanner e firmware base | “Há automação de qualidade, com cobertura ainda a ampliar.” Faltam jobs do React, extensão de mapa e build do novo firmware HCA. |
| K8 | Simulador de dispositivo usa o contrato de sincronização | “Podemos exercitar a integração sem depender sempre de uma placa disponível.” |
| K9 | Empacotamento exclui `.env`, testes e prévia de IA do APK | “A entrega contém o necessário para o usuário.” |
| K10 | Dados fictícios e artefatos de provisionamento têm tratamento separado | “A demonstração não exige publicar credenciais do equipamento.” |

### L. Achados novos desde a primeira análise

Evidências: [link de carregador](../packages/chargegrid_core/chargegrid_core/chargers/link.py), [firmware emulador](../firmware/goodwe-hca-sim/src/main.cpp), [cliente do painel](../firmware/esp32/src/charger_link.cpp), [consumo predial](../packages/chargegrid_core/chargegrid_core/site_load.py), [mapa vetorial](../apps/mobile/src/chargegrid_app/ui/vector_map.py), [R10 da peça 5](prototipo-usb/peca5-revisao-2026-10-21/ENTREGA/LEIA-PRIMEIRO.md).

| ID | Detalhe novo | Frase possível e limite |
|---|---|---|
| L1 | Cada conector tem endereço de carregador obrigatório, de 1 a 247, único no posto | “Dois pontos do mesmo posto não ficam configurados para disputar o mesmo endereço.” |
| L2 | Gatilho do banco escolhe o menor endereço livre, inclusive para INSERT SQL | “O provisionamento também recebe um endereço sem depender de preencher o app.” Concorrência de INSERT pode gerar conflito, não promete alocação infalível. |
| L3 | Alteração de endereço é recusada com ponto ocupado | “Não trocamos o destino dos comandos no meio da recarga.” |
| L4 | Endereço/link são informações do proprietário, omitidas no payload do motorista | “O motorista recebe o que precisa para usar o ponto, sem detalhes da rede de controle.” |
| L5 | mDNS `cg-hca-N.local` e opção de IP fixo de diagnóstico no painel | “Há descoberta local e um recurso quando a rede bloqueia essa descoberta.” Não funciona em redes isoladas automaticamente. |
| L6 | A escolha entre Modbus e simulação interna ocorre no START e vale até o fim | “A sessão não troca de fonte de energia quando outro equipamento aparece na rede.” |
| L7 | Se o carregador surge depois, só a próxima sessão o utiliza | “A chegada tardia do equipamento não muda uma recarga já aceita.” |
| L8 | Equipamento encontrado ligado sem sessão no painel recebe STOP | “Há tratamento para um carregador órfão após reinício do painel.” |
| L9 | STOP sem releitura confirmada fica pendente e é repetido | “O painel continua tentando desligar.” Isso não é medição física do relé. |
| L10 | Firmware emulador fecha/abre relé GPIO13 e tem perfis WROOM e ESP32-S3 | “O carregador emulado é um segundo equipamento, com software próprio.” A montagem não foi ensaiada nesta revisão. |
| L11 | Relé é binário; mudar 10029 altera potência/energia simuladas | “O número em kW representa a simulação; não regula a potência real do celular.” |
| L12 | Registradores 19000–19006 são extensão explicitamente simulada | “As facilidades de teste não são apresentadas como parte oficial do HCA.” |
| L13 | Servidor e cliente compartilham mapa e parser Modbus C++ | “Os testes locais exercitam o mesmo núcleo de protocolo do firmware.” |
| L14 | Escrita múltipla valida todos os registradores antes de aplicar | “Um pedido inválido não deixa metade da alteração aplicada no emulador.” |
| L15 | Consumo predial possui seis tipos e três portes | “A simulação de uma padaria não segue a mesma curva de um shopping.” São hipóteses de modelo. |
| L16 | Curvas consideram hora, dia da semana, sazonalidade e ruído reproduzível | “A demonstração tem variação controlada e pode ser repetida por posto.” |
| L17 | Consumo fica estável em janelas de cinco minutos | “Evitamos recalcular decisões por ruído a cada segundo.” |
| L18 | Valor manual de consumo vale 30 minutos e depois volta à curva | “O número usado na demonstração não fica travado indefinidamente.” |
| L19 | Limite ausente recebe padrão explicitado pelo tipo/porte | “O sistema informa quando usa um padrão.” É heurística, não dimensionamento elétrico nem demanda contratada verificada. |
| L20 | Rebalanceamento nasce ligado no modelo e na migração nova | “A configuração inicial já considera a instalação.” Depende de aplicar a migração no ambiente. |
| L21 | Potência tem tela própria no app e cartão da estação no web | “Disponível, loja e carros aparecem juntos, com consumo rotulado como simulado.” |
| L22 | Horário tarifário pode ser desligado sem exclusão | “O dono preserva a configuração para reutilizar depois.” |
| L23 | MapLibre desenha geografia vetorial com estilos claro/escuro compartilhados | “O mapa corresponde às coordenadas, inclusive na conta demo.” Tiles ainda dependem de rede. |
| L24 | Polling troca marcadores sem remontar o mapa e sem reposicionar a câmera | “A atualização dos postos não atrapalha quem está explorando a região.” |
| L25 | Painel arrastável preserva filtros e desloca os créditos acima dele | “A lista e o mapa continuam utilizáveis juntos.” |
| L26 | Coordenadas inválidas são recusadas antes de criar pinos | “Um dado inválido não vira um marcador em uma posição inventada.” |
| L27 | Atribuição tem botão para reabrir créditos e licenças | “Os créditos do mapa continuam acessíveis.” Testes verificam o controle, sem certificar conformidade jurídica. |
| L28 | Runtime web do mapa é local; dados cartográficos são externos | “Não dependemos de um CDN para baixar o código MapLibre, mas precisamos de rede para os tiles.” |
| L29 | Build Android tem regras R8/JNI e verificação da fábrica MapLibre no APK | “A entrega confere um ponto que pode quebrar apenas na versão release.” Verificação estática não substitui abrir o mapa no aparelho. |
| L30 | Peça 5 R10 muda orientação e reduz retrações sem redesenhar geometria de produção | “A correção busca reduzir o esforço de impressão preservando o encaixe.” Relatórios são digitais; resultado físico ainda pendente. |

## 5. Banco de frases curtas

Estas frases podem aparecer durante a navegação, sem virar slides próprios:

- “O código evita zero e letra O para facilitar a leitura.”
- “O QR de propriedade não é o código público de recarga.”
- “Pedido recebido ainda não é comando aplicado.”
- “A potência que aparece como aplicada já foi confirmada pelo equipamento.”
- “Não liberamos a capacidade de um ponto só porque ele perdeu a rede.”
- “Um carro sozinho pode aproveitar o máximo permitido.”
- “O carregador trifásico tem um piso diferente do monofásico no modelo implementado.”
- “O adaptador só grava na flash quando o valor muda.”
- “A confirmação depende da releitura, não apenas do envio.”
- “Se o preço mudou, pedimos uma nova revisão.”
- “Se a resposta se perdeu, recuperamos o mesmo pedido.”
- “Uma falha de conexão não vira cobrança por tempo sem evidência.”
- “Receita bruta, repasse e margem são valores diferentes.”
- “Custo desconhecido não é tratado como custo zero.”
- “Os números do CSV precisam fechar com a tela.”
- “A IA consulta; o usuário confirma a ação.”
- “Até uma consulta da IA evita chamar rotinas que poderiam emitir comandos.”
- “O modelo de previsão precisa vencer a média para ser usado.”
- “Histórico sintético não cria faturamento.”
- “Sem dados suficientes, a faixa de previsão aparece como não calibrada.”
- “A atualização pausa quando o app fica oculto.”
- “O mapa não bloqueia o carregamento do conteúdo principal.”
- “A câmera encerra antes de entregar o QR lido.”
- “Nós decodificamos o QR desenhado nos testes.”
- “A carcaça permite manutenção sem reimprimir o corpo inteiro.”

## 6. Mapa de funcionalidades e estágio

| Área | O que foi encontrado | Como apresentar |
|---|---|---|
| App Flet | Acesso, busca, comparação, reserva, revisão, sessão, histórico, recibos, chat, gestão do vendedor, tarifas e outras telas | Implementação existente; conferir no build que será demonstrado. |
| React/TypeScript | Painel oficial com visão geral, estações, sessões, resultado, alertas, cupons, insights e previsão | Cliente da mesma API, com mock de desenvolvimento separado. |
| Dashboard Flet | Versão anterior mantida | Contexto de evolução, sem ocupar tempo de demonstração. |
| FastAPI | Regras, autenticação, autorização, comandos, sincronização, relatórios, pagamentos e previsão | Camada central das regras de acesso e operação. |
| PostgreSQL | 22 tabelas de domínio nos modelos atuais: contas, equipamentos, sessões, comandos, telemetria, pagamentos, decisões e agregados | Modelo que guarda tanto resultado quanto evidências do fluxo. `alembic_version` é infraestrutura à parte. |
| ESP32-S3/LVGL | Firmware 0.8.0 no código, touch, autoatendimento e cliente Modbus TCP | Energia continua simulada; versão instalada não foi conferida. |
| HCA G2 | Adaptador Python com três variantes e firmware emulador GW7K + mestre TCP no painel | Testes com TCP local aprovados; GoodWe físico não validado. |
| Balanceamento | Comandos/ACK, motivo, histórico e consumo predial por perfil | Seis tipos, três portes, valor temporário e limite padrão; consumo simulado. |
| Stripe | Checkout, webhook, consulta, autorização/captura/devolução | Somente modo teste; funcionamento publicado/configuração não verificados agora. |
| Carteira/resgate | Saldo e movimentos locais/simulados; vendedor deriva base de repasse da API | Não representam carteira financeira ou saque bancário efetivo. |
| Notificações | Avisos derivados dos dados consultados, leitura local | Não apresentar como infraestrutura de push/inbox durável do servidor. |
| Ajuda/suporte | Perguntas e respostas locais | Não abre chamado nem representa atendimento humano. |
| IA | Ferramentas de leitura, busca, resumos e insights; alternativas por regras | Recursos distintos de uma automação de comandos. |
| Previsão | Média, Gradient Boosting exportado, backtest, métricas, sugestões e melhor horário | Avaliação offline sintética; qualidade real depende de histórico por posto. |
| Modo Motorista | Código histórico preservado, `DISCONTINUED=True`; `/driver/*` responde 410 | Descontinuado em 20/10/2026 no código atual. Retirar dos diferenciais ativos. |
| MCP externo | Planejamento em documentação; não foi encontrada implementação nas áreas de código inspecionadas | Não afirmar que há servidor MCP público funcional. |
| Exportações | CSV/JSON de operação; CSV/PDF em recibos, histórico e resultado, conforme a rota | Não prometer XLSX implementado apenas porque consta no planejamento. |
| Mini e emulador físico | CAD v9 + peça 5 R10; firmware HCA com relé em projeto separado | Relé liga/desliga; USB variável e medição real não estão comprovados. |
| Mapa do app | Extensão MapLibre/OpenFreeMap e exploração sem remontar câmera | Alteração local ainda não commitada; sem ensaio físico do mapa nesta revisão. |

### Dados de backend que vale saber para perguntas

- **Operação:** postos e conectores são entidades distintas; um endereço pode ter vários pontos.
- **Autorização:** perfil, proprietário, claim e chave de dispositivo têm papéis diferentes.
- **Reserva:** prazo de confirmação e prazo de uso não são o mesmo campo.
- **Sessão:** guarda preço, desconto, origem, energia, limites e os termos econômicos aceitos.
- **Controle:** comandos têm versão, validade, status e erro; telemetria tem boot e sequência.
- **Auditoria:** eventos de sessão, eventos de pagamento e decisões de potência registram fatos diferentes.
- **Pagamento:** autorização, confirmação, captura, devolução e acerto não são colapsados num único “pago”.
- **Previsão:** agregados horários e marca de consolidação preservam o histórico útil para além da retenção de telemetria.
- **IA:** registro de uso acompanha custo/latência sem persistir perguntas e respostas nessa tabela.

## 7. Pontos a ajustar no material da apresentação

Este guia e a matriz de revisão foram atualizados; o código e os guias técnicos antigos foram preservados. Estes pontos evitam levar uma explicação desatualizada para a banca:

1. **README versus pagamentos:** o README principal ainda diz que não há processamento de pagamento. O código atual contém Stripe em teste. A formulação atual é “sem cobrança real; integração em modo teste”.
2. **Modo Motorista:** screenshots e guias anteriores ainda o destacam. O código atual o descontinua. Não usar as capturas antigas como prova de funcionalidade ativa.
3. **Prazo de reserva:** a ajuda local menciona dez minutos, mas `RESERVATION_MINUTES` está em quinze no backend atual. Para falar um número, conferir a versão demonstrada e o prazo retornado pela API.
4. **Frequência de sincronização:** o README principal menciona 5/10 segundos. A resposta atual da API usa **1 segundo** com sessão/reserva/comandos/pedido aberto e **5 segundos** fora disso. Prefira “sincronização periódica” na fala se não tiver conferido o ambiente.
5. **Documentação HCA:** o guia ainda trata o firmware 0.5.0 como próximo; o código está em 0.8.0 e contém `SET_POWER`. A existência no código não prova que a placa já foi atualizada.
6. **Bateria:** SoC do veículo é modelado. No modo apresentação, o celular pode representar o carro; fora dele há estado simulado. Não afirmar leitura de BMS/OBD ou integração com o carro.
7. **Planos de outubro:** documentos em `planejamento-features` são propostas. Parte foi implementada depois; cada alegação deve usar código atual como evidência.
8. **Arquivos de impressão:** a base mecânica v9 agora tem uma substituição R10 específica da peça 5. Usar o guia de 21/10; as demais peças não foram refatiadas nessa revisão.
9. **Testes não equivalem a implantação:** passou no computador não significa migrado no Supabase ou instalado na placa.
10. **Qualidade tem limites atuais:** há dois testes do app falhando, avisos de depreciação e lacunas no CI para React/mapa/firmware HCA. Não apresentar “zero pendências” ou certificação integral de acessibilidade/segurança.

## 8. Evidências de verificação — 21/10/2026

| Verificação executada | Resultado | Alcance |
|---|---:|---|
| Núcleo Python completo | **246 aprovados** | Inclui consumo predial, endereço do carregador e horários ativáveis. |
| API completa | **425 aprovados** | PostgreSQL 16 descartável, sem usar banco existente; migrações até head aprovadas. |
| Painel React | **120 aprovados / 15 arquivos** | Inclui potência, endereço e reorganização das telas. Typecheck aprovado. |
| App completo | **762 aprovados, 2 falhas, 129 subtestes aprovados** | Cinco avisos de depreciação. Falhas explicadas abaixo. |
| Seleção de ferramentas | **47 aprovados** | Modbus em memória, dispositivo, igualdade do core e proteção do release Android. |
| Modbus TCP local | **5 aprovados** | Socket real contra núcleo do firmware emulado no computador. |
| Extensão Flutter de mapa | **2 aprovados** | Comportamento do controle de créditos; não é ensaio de renderização em aparelho. |
| Total dos grupos acima | **1.607 aprovados e 2 falhas** | Subtestes não foram somados novamente. Não é toda a suíte de ferramentas do repo. |
| Firmware / LVGL / link HCA em host | **Aprovado** | Controlador, totem, releitura, falhas, parser, watchdog e QRs decodificados. |

**Duas falhas encontradas:** `test_demo_summary_reports_live_demo_result_and_demo_guidance` e `test_simulated_soc_rises_with_energy_and_stops_battery_full`. As expectativas assumem potência nominal, mas o novo consumo predial reduz a potência efetiva. No cenário reproduzido, nominal de 60 kW, aplicada de 56,8 kW, energia de 473,333 Wh e SoC de 94,73% para bateria inicial de 90%/10 kWh: o SoC corresponde à energia registrada. Isso aponta expectativas antigas a revisar; não se deve apagar as falhas ou declarar a suíte integralmente verde. Não foi feita correção do produto ou dos testes nesta tarefa.

O host registrou pico de **34.720 bytes / 65.536 bytes (53%)** nas telas do totem. Isso é memória do pool LVGL no executável do computador, não consumo total da SRAM da placa.

Os primeiros testes de banco/socket foram bloqueados pelo sandbox; foram reexecutados com autorização de execução local e passaram. O PostgreSQL descartável foi encerrado ao final. Não houve rejeição da revisão automática de aprovação.

Não foram feitos nesta revisão: deploy, migração na nuvem, build/instalação de novo APK, gravação em ESP32, ensaio elétrico/relé/câmera/mapa em aparelho, Stripe externo, teste com GoodWe comercial, nova impressão ou auditoria geométrica completa. Evidências físicas antigas continuam limitadas às respectivas datas e versões.

## 9. Perguntas prováveis e respostas seguras

**“Já funciona no carregador GoodWe?”**

“O painel já tem cliente TCP e há um firmware emulador separado. O protocolo passou nos testes locais por socket. A energia continua simulada e ainda falta validar o HCA G2 físico.”

**“Por que a tradução fica fora da API?”**

“A API decide os limites; o próprio painel atua como mestre Modbus na rede local. O carregador emulado é outro firmware ESP32.”

**“Isso impede qualquer sobrecarga da instalação?”**

“O algoritmo coordena os limites e evita aumentos sobre capacidade ainda não liberada. Um salto no consumo da loja pode causar excesso transitório até as confirmações. Proteção elétrica e medição real precisam do equipamento e da instalação adequados.”

**“O que acontece sem internet?”**

“Sem API há o watchdog de 45 s; na sessão Modbus o painel trata a perda do carregador em 5 s e o emulador abre sua saída após 15 s sem mestre. Na fonte de mapas, falta de rede mostra erro e nova tentativa. Reboot não reinicia a recarga.”

**“A IA pode reservar ou cobrar sozinha?”**

“Não. As ferramentas consultam dados permitidos e oferecem caminhos para as telas de confirmação.”

**“A previsão realmente usa aprendizado de máquina?”**

“Sim, há Gradient Boosting treinado offline e exportado para avaliação sem scikit-learn na API. Ele concorre com uma média histórica e só é escolhido pelo critério de melhoria. Os resultados offline apresentados usam dados sintéticos.”

**“Por que usar média se já têm modelo?”**

“Porque a média pode ser melhor ou mais defensável com pouco histórico. Mostramos o método e as métricas em vez de usar o modelo por obrigação.”

**“O pagamento já é real?”**

“A integração é Stripe em modo teste. O fluxo modela autorização, confirmação e acerto, mas não há cobrança comercial real nesta entrega.”

**“O celular está sendo carregado por esse sistema?”**

“O firmware do emulador controla um relé de liga/desliga e pode comandar a alimentação de uma carga de demonstração. Os kW e kWh são simulados; não medem o consumo do telefone nem regulam sua corrente. A montagem e o funcionamento físico não foram ensaiados nesta revisão.”

**“Quais testes vocês fizeram?”**

“Foram 1.607 testes aprovados nos grupos executados e duas falhas do app documentadas, mais o controlador e a UI LVGL no host. A API foi testada em PostgreSQL descartável e o Modbus por socket local. Não é um teste em produção ou em GoodWe físico.”

**“E o benefício ambiental?”**

“O projeto apoia a organização da recarga. Ainda não medimos redução de emissão ou economia ambiental, então não apresentamos um número de CO₂ evitado.”

## 10. Preparação prática para caber no tempo

- Preparar uma jornada de motorista, uma decisão de potência e um recibo; evitar muitas contas e cadastros na hora.
- Conferir quais versões estão realmente no APK, API e placa antes do ensaio.
- Usar a mesma estação e sessão nas telas relacionadas para facilitar a compreensão.
- Se usar mock ou histórico sintético, manter a identificação visível.
- Ensaiar o carregador presente/ausente antes do START: a sessão mantém o modo escolhido.
- Mapas vetoriais precisam de tiles externos, inclusive na demo; preparar uma captura para falta de rede.
- Para demonstrar exatamente 30/12/24 kW, configurar o cenário antes e lembrar que o valor manual expira em 30 minutos.
- Levar capturas ou vídeo curto do mesmo fluxo como reserva para falha de rede; distinguir gravação de demonstração ao vivo.
- Mostrar apenas informações públicas no telão. Não abrir `.env`, serial de provisionamento ou QR privado de propriedade para a plateia.
- Se a frase está técnica demais, explicar primeiro o efeito: “não duplica a sessão”, depois nomear “idempotência” se houver pergunta.
- Cortar primeiro telas históricas, versões de frameworks, número de registradores e parâmetros do treinamento. Preservar jornada, GoodWe, confirmação e limites da bancada.

**Critério para escolher um detalhe:** ele deve responder “que problema isso evita?” ou “que cuidado isso demonstra?”. Se a resposta for só “porque existe no código”, deixe para as perguntas.
