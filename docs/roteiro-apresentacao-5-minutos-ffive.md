# ChargeGrid - roteiro de 5 minutos | Equipe FFIVE

**Versão corrigida: apresentação de 5 minutos.** 21/10/2026.

As citações são as falas. **TELA / AÇÃO** orienta a equipe e não deve ser lido. Os tempos incluem fala e operação ao vivo. Cadastro/login e perfil/veículo entram em imagens; as demais etapas usam APK e bancada ao vivo. Falar enquanto navega.

## Distribuição dos 5 minutos

| Tempo | Bloco | Duração |
|---|---|---|
| 0:00-0:30 | Introdução | 30 s |
| 0:30-1:25 | 1. Conta do operador | 55 s |
| 1:25-2:35 | 2. Usuário e recarga | 70 s |
| 2:35-2:50 | 3. Históricos simultâneos | 15 s |
| 2:50-3:45 | 4. Autoatendimento completo | 55 s |
| 3:45-4:15 | 5. IA: consulta e recusa | 30 s |
| 4:15-4:50 | 6. Resgate e rentabilidade | 35 s |
| 4:50-5:00 | Encerramento | 10 s |

## 0:00-0:30 | Introdução

**TELA / AÇÃO:** Apontar o ESP32 e o display. Exibir o APK e os dois temas já preparados, sem iniciar a recarga.

> Olá, nós somos a Equipe FFIVE e viemos mostrar nossa solução, o ChargeGrid. Com a expansão dos veículos elétricos, queremos facilitar a recarga para motoristas e a gestão para donos de eletropostos. Usamos ESP32 e display como carregador e totem simulados, conectados a servidores online. O APK tem visual inspirado na GoodWe; mostraremos motorista no tema claro e operador no escuro.


## 0:30-1:25 | 1. Conta do operador

**TELA / AÇÃO:** Exibir por um instante a imagem de cadastro/login. No APK autenticado, concluir ao vivo o cadastro/configuração do novo posto com os campos preparados; salvar e publicar. Mostrar a vinculação/comunicação do emulador com a central, voltar à lista de estações e abrir o detalhe de potência. Apontar a edição posterior, sem abrir todos os submenus.

> O operador configura endereço, tarifa por kWh, potência, duração e permanência, com preços por horário e edição posterior.

> Vinculamos o emulador usando um cliente Modbus TCP e um mapa de registradores baseado no HCA G2. A releitura confirma comandos; regravar a potência só quando muda poupa a memória flash. O relé liga e desliga; energia e potência são simuladas.

> No painel, balanceamos loja e carros e explicamos as reduções. A loja é simulada com seis perfis, três portes, horário e calendário. A validação no GoodWe comercial vem depois.


## 1:25-2:35 | 2. Usuário e recarga

**TELA / AÇÃO:** Mostrar a imagem de cadastro/login e seleção do carro. No APK do motorista, buscar e comparar rapidamente os pontos; escolher o da bancada. Digitar o código temporário do display, definir limites e revisar. Conectar o celular conforme a instrução e solicitar o início. Mostrar, lado a lado, motorista e operador mudando de estado. Assim que houver confirmação e breve evolução, encerrar, aguardar a confirmação e abrir o recibo.

> O veículo escolhido ajuda a estimar a energia para a autonomia desejada. Buscamos e comparamos os pontos; também há reserva e saldo antecipado em carteira simulada.

> Confirmamos o código temporário do display e revisamos os limites. Conectamos o celular, cuja bateria representa a do carro, e acompanhamos a sessão também no operador.

> O sistema evita duplicações, controla reservas concorrentes e recupera operações após respostas perdidas, com tratamento de interrupções de comunicação. Encerramos e conferimos o recibo.


## 2:35-2:50 | 3. Históricos simultâneos

**TELA / AÇÃO:** Abrir o histórico do operador e o do motorista. Manter as duas telas ao vivo na projeção e apontar a sessão recém-encerrada, com energia e valor. Mostrar os indicadores do operador sem percorrer outras telas.

> Energia e valor coincidem. O motorista vê suas recargas; o operador reúne as dos seus postos e os indicadores da operação.


## 2:50-3:45 | 4. Autoatendimento completo

**TELA / AÇÃO:** Trocar para a câmera ao vivo enquadrando o display físico. Fazer a jornada desde a tela inicial: escolher recarga/valor, revisar condições, passar pelo pagamento simulado, conectar conforme a instrução, aguardar o início e mostrar o andamento. Tocar em Encerrar, confirmar, aguardar o recibo e concluir/desconectar. A sessão será curta; preservar todas as etapas.

> No totem, fazemos todo o processo: escolha, revisão, pagamento, início e encerramento. O Stripe está integrado em teste; hoje o pagamento é simulado. Ao terminar, conferimos o recibo.


## 3:45-4:15 | 5. IA: consulta e recusa

**TELA / AÇÃO:** Voltar ao APK do operador e abrir o chat. Colar a consulta preparada e apontar o resultado. Enviar o pedido fora do escopo e mostrar a recusa ou o redirecionamento. Não ler respostas inteiras nem abrir os destinos sugeridos.

> A IA consulta apenas dados autorizados dos próprios postos. Aqui resumimos as recargas e mostramos uma recusa fora do escopo. Iniciar e cobrar continuam exigindo os fluxos normais de confirmação.

**Colar nesta ordem:**

1. **Consulta:** Resuma energia e receita das recargas dos meus postos hoje.
2. **Recusa fora do escopo:** Conte uma piada sobre futebol.

Apontar o resultado e a recusa; não ler as respostas inteiras. Não incluir uma terceira interação no cronograma principal.


## 4:15-4:50 | 6. Resgate e rentabilidade

**TELA / AÇÃO:** Abrir o saldo do operador e falar do negócio com essa tela visível. Iniciar o resgate, mostrar as duas modalidades, selecionar a ensaiada, revisar, confirmar e exibir o resultado. A solicitação é simulada.

> Nossa proposta combina tarifa por kWh, comissão configurável para a GoodWe e aluguel do totem, incentivando a expansão da rede. É uma proposta comercial.

> O resgate oferece antecipação com taxa de 2% ou sexta-feira sem essa taxa. Escolhemos, revisamos e confirmamos. Aqui o resgate é simulado, sem transferência bancária.


## 4:50-5:00 | Encerramento

**TELA / AÇÃO:** Deixar o resultado do resgate visível e encerrar. Os segundos restantes funcionam como pequena margem para transições.

> Conectamos motorista, operador e autoatendimento, com atenção à integração e aos detalhes. Equipe FFIVE. Obrigado!


## Preparação - não ler

- **Contas, imagens e projeção:** Dois celulares com contas distintas já autenticadas: motorista e operador. Cadastro/login e seleção de veículo ficam em imagens. Preparar os dois espelhamentos lado a lado e a fonte de câmera que mostra o totem físico.
- **Posto e equipamento:** Provisionar o equipamento antes e ensaiar o caminho do APK. O onboarding atual parte de um ponto reivindicado por QR privado. Deixar valores e endereço preparados, concluindo e salvando as etapas ao vivo. Mostrar depois a associação/comunicação do carregador com a central, na ordem solicitada.
- **Hardware e modo de sessão:** Conferir painel, emulador, rede e relé antes de iniciar. Uma sessão iniciada na simulação interna não passa automaticamente a controlar o emulador quando ele se conecta. O modo local de demo do app é diferente do modo apresentação conectado à bancada.
- **Duas recargas curtas:** Conferir o modo apresentação e o pagamento simulado do totem. Usar bateria abaixo de 100%. Encerrar manualmente após a confirmação e breve andamento, sem esperar aumento de 1% na bateria. Aguardar também a confirmação da parada e o recibo.
- **Busca, saldo e IA:** Deixar endereço de busca e dois prompts prontos para colar. Conferir mapas, API e serviço de IA; preparar saldo demonstrativo e registros para a comparação. Enviar só uma consulta e um pedido fora do escopo. A resposta pode variar; orientação local de fallback não comprova uso de IA generativa.
- **Execução em paralelo:** Uma pessoa fala e opera o motorista; outra acompanha o operador e troca as fontes. Os toques acontecem durante as falas. A comparação dos históricos exige duas telas simultâneas; alternar contas em um celular não atende a esse ponto do fluxo.
- **Ensaio com cronômetro:** O roteiro reserva 300 segundos para fala e operação. O fechamento depende da navegação ensaiada e da latência dos serviços. Cortar pausas e explicações extras; preservar início e término das duas recargas, comparação, recusa e resgate. Se uma falha impedir o ao vivo, explicar o que ocorreu.

### Precisão da fala

- Potência: kW. Energia: kWh. Tarifa: R$/kWh. Duração da sessão e permanência após o término são regras distintas.
- Protocolo e emulador aproximam a integração; a validação num GoodWe comercial continua pendente. O relé é binário; kW e kWh da bancada são simulados.
- Temas são escolhas desta apresentação. Autonomia é estimada. A IA auxilia consultas e não substitui as confirmações operacionais.
- Stripe em teste; carteira e resgate simulados. Comissão e aluguel do totem compõem a proposta comercial. O operador não necessariamente edita a comissão da plataforma.

## Conferência das 22 marcações

| ID | Destaque | Onde entra |
|---|---|---|
| 01 | Busca de pontos e estações | 2. Usuário |
| 02 | Comparação antes da escolha | 2. Usuário |
| 03 | Autoatendimento | 4. Totem |
| 04 | Código temporário de presença | 2. Usuário |
| 05 | Balanceamento loja e carros | 1. Operador |
| 06 | Consumo: seis perfis, três portes, horário e calendário | 1. Operador |
| 07 | Explicação das reduções de potência | 1. Operador |
| 08 | Cliente Modbus TCP | 1. Operador |
| 09 | Mapa de potência e comandos HCA G2 | 1. Operador |
| 10 | Gravação só quando a potência muda | 1. Operador |
| 11 | Relé liga/desliga | 1. Operador |
| 12 | Pedidos repetidos | 2. Usuário |
| 13 | Reservas concorrentes | 2. Usuário |
| 14 | Recuperação de resposta perdida | 2. Usuário |
| 15 | Interrupções de comunicação | 2. Usuário |
| 16 | kWh + comissão GoodWe + aluguel do totem | 6. Resgate |
| 17 | Tarifas por faixa horária | 1. Operador |
| 18 | Pagamento integrado com Stripe em teste | 4. Totem |
| 19 | Recibo da sessão | 2. Usuário e 4. Totem |
| 20 | Carteira e resgate simulados | 2. Citação e 6. Resgate |
| 21 | Dashboard operacional | 1. Operador e 3. Históricos |
| 22 | IA com acesso limitado | 5. IA |

## Base e decisões

- Base: destaques nas páginas físicas 2-4 e fluxo nas páginas 6-8 de ChargeGrid_Lista_de_Features (1).pdf, com a correção do usuário para cinco minutos. Esta é a versão para usar na apresentação.
- A carteira do consumidor é apenas citada. O resgate do operador é mostrado ao final, atendendo ao fluxo final do documento. As duas recargas e todos os seis blocos foram mantidos.
- A IA fica como apoio a consultas; recarga e cobrança seguem confirmações da plataforma. A frase sobre ausência de IA generativa não é usada como afirmação sobre o desenvolvimento do app.
- Contexto de mercado: ABVE, 28/09/2026, expansão da rede brasileira de recarga: https://abve.org.br/recarga-rapida-dc-quase-triplica-em-12-meses-e-ja-responde-por-38-da-rede-brasileira/
- Referência técnica: docs/revisao-apresentacao-2026-10-21.md e implementação local do app, API e firmware. Estado do APK instalado, deploy e bancada devem ser conferidos no ensaio.

Volume de fala: aproximadamente **368 palavras**. O cronograma depende do ensaio completo e da latência da demonstração.
