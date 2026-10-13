> Versão anterior arquivada. A seleção de componentes e o orçamento desta versão foram substituídos pela pesquisa nacional. Não usar como lista de compras.

# ChargeGrid Mini — plano do emulador físico de carregador

Proposta para discussão com a equipe, atualizada em 5 de outubro de 2026.

O objetivo é criar um equipamento autônomo que represente o carregador GoodWe, com carcaça derivada do STEP recebido, ESP32 próprio, API própria e fornecimento real de energia a um celular USB-C. O painel de gestão existente continuará sendo outro equipamento e outro software. O orçamento máximo é R$ 250 por carregador, equivalente a R$ 50 por integrante, sem impressão e sem o painel já existente.

**Situação:** arquitetura e orçamento de referência preparados; interface USB ainda em seleção. Não há circuito validado, firmware novo implementado, CAD adaptado ou STL liberado para impressão. A possibilidade de variar a capacidade USB dentro desse orçamento depende da validação do módulo de potência e do telefone escolhido.

## Decisões confirmadas e propostas

| Tema | Definição |
| --- | --- |
| Controlador do carregador | ESP32 independente, programado com framework Arduino |
| Software do painel | Separado; futuramente consumirá a API do emulador |
| Telefone | Conector USB-C confirmado; modelo e protocolos ainda desconhecidos |
| Orçamento | R$ 250 máximos por unidade, incluindo fonte, cabo e montagem elétrica |
| Carcaça | Preservar superfícies externas e proporções do modelo original |
| Escala | Proposta de 70%; ainda depende da impressora e do encaixe dos componentes |
| Montagem | Preferência por travas, trilhos e berços removíveis sem parafusos |
| Saída inicial | Proposta de 5 V; perfis de capacidade sujeitos à negociação e ensaio |

Pendências que afetam a escolha final: modelo do celular, data do pitch, impressora/volume útil, acesso a soldagem e instrumentos, quantidade de carregadores e disponibilidade de um módulo USB com I²C acessível. Não presumir suporte a USB Power Delivery apenas porque o conector é USB-C.

## Identidade e proposta da demonstração

Nome de trabalho: **ChargeGrid Mini — emulador físico de carregador**. Manter ChargeGrid como projeto principal e o desenho externo da unidade fornecida. Identificação didática discreta na base ou traseira; evitar alterar a frente para inserir outra tela. O painel continua separado.

Mensagem para o pitch: **“O painel autoriza a sessão, o carregador executa e a energia entregue confirma a operação.”**

O celular representa a carga atendida. São reais a comunicação, o acionamento, a alimentação USB e as medições. Veículo, potência de um eletroposto e eventual bateria de carro são representações. Uma escala didática deve aparecer separada da potência real, sem apresentar 5 W como 5 kW medidos.

A proposta emula o comportamento de um ponto de recarga. Compatibilidade com o protocolo de um GoodWe real depende da documentação do modelo e de testes futuros: não afirmar que esta API HTTP própria é uma API oficial GoodWe, OCPP ou SEMS.

Roteiro de apresentação: selecionar o ponto no painel; autorizar uma sessão; observar início da recarga no telefone e confirmação do equipamento; acompanhar potência e energia; solicitar outro perfil se validado; encerrar e confirmar corte/energia final. Para dois pontos, o painel distribui o orçamento entre duas unidades independentes. Primeiro validar uma unidade completa.

## Separação do software

Fluxo proposto: **plataforma/painel existente → adaptador de comunicação → API local do carregador → firmware ESP32 → eletrônica USB → celular**. A telemetria percorre o caminho de volta.

O painel continua responsável pela experiência do usuário e pela integração com reservas, clientes e regras da plataforma. O carregador recebe comandos autorizados e executa sessões, limites suportados, medição e proteções locais. Não deve precisar conhecer dados pessoais dos clientes.

O novo código terá projeto e compilação próprios, por exemplo `firmware/charger-emulator/`, com módulos para API, estado de sessão, driver USB, medição, proteção e persistência. O nome da pasta é proposta; esta rodada não criou firmware nem alterou o código existente.

A inspeção do repositório encontrou simulação de potência fixa e SoC no firmware atual, além de contratos de telemetria no backend. Isso serve como contexto de integração. Não migrar automaticamente essas responsabilidades para o novo carregador nem duplicar sua identidade/chave. O adaptador do painel será uma integração posterior e explícita.

### Contrato inicial da API

HTTP/JSON em uma rede local de demonstração, com autenticação por unidade e sem exposição pública. Preferir Wi-Fi dedicado ao pitch, sem depender da rede da faculdade. HTTP simples só é aceitável nessa rede isolada; acesso fora dela exige transporte protegido. Descoberta e endereçamento devem ser ensaiados previamente.

| Operação proposta | Finalidade |
| --- | --- |
| `GET /v1/capabilities` | Identidade, versão, perfis realmente suportados e recursos de medição |
| `GET /v1/status` | Estado, sessão, tensão/corrente, energia e falhas |
| `POST /v1/sessions` | Solicitar início com `command_id`, `session_id`, perfil e autorização com validade |
| `PUT /v1/sessions/{id}/limit` | Solicitar alteração de perfil; nunca aceitar valor fora das capacidades |
| `POST /v1/sessions/{id}/stop` | Encerrar de maneira idempotente e guardar medição final |
| `POST /v1/sessions/{id}/heartbeat` | Renovar a autorização temporária de operação |
| `GET /v1/commands/{id}` | Consultar `pending`, `applied`, `rejected` ou `failed` com motivo |

Estados sugeridos: `available`, `starting`, `charging`, `suspended`, `stopping`, `faulted`. A presença do telefone é um campo separado; corrente zero não prova desconexão ou bateria cheia.

Distinguir `requested_limit_w`, `advertised_limit_w`, `negotiated_limit_w` e `measured_power_w`. Usar nulo quando o hardware não permitir determinar um valor. Confirmar configuração lida de volta separadamente de contrato negociado; não inventar confirmação de PD que a placa não exponha. Perfis não comprovados não entram em `capabilities`.

Repetir um comando não pode iniciar outra sessão. Após reset, permanecer sem fornecer energia e informar interrupção da sessão anterior. Perda de autorização por timeout deve suspender a saída localmente. O prazo será configurável e ensaiado; não depende de um STOP chegar pela rede. Proteção e amostragem não podem ficar bloqueadas por HTTP.

A telemetria terá unidade e fronteira de medição, além de sequência e tempo monotônico. `soc_percent` permanece nulo sem integração específica com o telefone. Energia em Wh ou mWh; a 5 W constantes, um minuto entrega apenas aproximadamente 0,083 Wh. A demonstração não deve inflar isso para produzir um preço visível.

## Controle elétrico: o que o ESP32 pode fazer

O ESP32 habilita a saída, configura capacidades suportadas pelo controlador USB e acompanha consumo e falhas. O telefone decide a corrente efetiva conforme bateria, temperatura, cabo e sua própria política. Portanto, limitar capacidade não garante uma velocidade exata nem fornece controle direto da tensão da bateria.

A proposta inicial mantém 5 V e investiga perfis de 0,5 A, 1 A e 1,5 A, correspondentes a tetos nominais de 2,5 W, 5 W e 7,5 W. São alvos de ensaio, não capacidades já confirmadas. O modo sem contrato PD precisa respeitar a corrente anunciada em USB-C; não anunciar 3 A enquanto se pretende fornecer 0,5 A. Se não existir um modo compatível, rejeitar o perfil ou manter a saída suspensa.

Não aplicar PWM ao VBUS do celular para simular velocidade. Também não variar livremente a tensão. Tensões superiores a 5 V exigem negociação e estágio de potência compatíveis; ficam fora do primeiro ciclo. Um limite analógico que derruba a tensão pode provocar repetidas reconexões e não substitui negociação USB.

### Candidato econômico: módulo fonte SW3518/SW3518S

Foi encontrada a biblioteca independente [SW35xx_lib](https://github.com/dimitar-grigorov/SW35xx_lib), cujo código oferece leitura de tensão/corrente e configuração das correntes máximas dos perfis PD. O [cabeçalho](https://github.com/dimitar-grigorov/SW35xx_lib/blob/main/src/SW35xx_lib.h) descreve `setMaxCurrentsFixed` e opções para PPS.

Há uma ressalva concreta: na [implementação de `rebroadcastPDO`](https://github.com/dimitar-grigorov/SW35xx_lib/blob/main/src/SW35xx_lib.cpp), o próprio autor deixa a função marcada como pendente de verificação. Assim, mudança de perfil durante a sessão pode exigir nova negociação ou reconexão controlada; a biblioteca não comprova funcionamento contínuo no nosso telefone.

A placa precisa expor SDA/SCL em pontos acessíveis, permitir inicialização e corte adequados, ter documentação da revisão e operar com níveis lógicos compatíveis. A facilidade de compra do módulo genérico não significa facilidade de integração. Se exigir solda diretamente nos terminais minúsculos do chip, perde a vantagem para este grupo.

Anúncios internacionais de módulos SW3516/SW3518 encontrados na pesquisa exibiam valores de aproximadamente R$ 22–27, antes de encargos e seleção da variante. Eles não comprovaram todos esses requisitos. A reserva de R$ 40 abaixo é teto de aquisição entregue, não cotação fechada nem recomendação para comprar uma variante aleatória.

Antes da compra definitiva, verificar: chip e revisão; I²C acessível; configuração apenas de 5 V; comportamento de saída durante boot; método de desligamento físico; indicação de negociação/presença; dimensões e custo entregue. Antes da ligação ao telefone, comprovar esses comportamentos com instrumentos e carga apropriada.

### Alternativa documentada e alternativas insuficientes

A [USB-C Power Click MIKROE-5682](https://www.mikroe.com/usb-c-power-click), baseada no TPS25750, oferece documentação mais estruturada. O preço consultado era US$ 18 antes de frete e tributos; não foi escolhida para o teto de R$ 250. A [interface TI](https://www.ti.com/lit/ug/slvuc05a/slvuc05a.pdf) distingue capacidades anunciadas, comandos e contrato ativo; configuração e firmware continuam necessários.

HUSB238 e placas vendidas como PD trigger/sink recebem energia de uma fonte: não cumprem automaticamente o papel de carregador para o telefone. A [documentação Adafruit](https://learn.adafruit.com/adafruit-usb-type-c-power-delivery-switchable-breakout/overview) mostra essa direção de funcionamento. LM2596 isolado não negocia USB, e TP4056 é destinado à carga de células, não a substituir uma fonte USB para celular.

Uma versão de 5 V fixos com liga/desliga e medição pode servir de contingência para o pitch. Ela não atende ao requisito de variar capacidade e não deve ser apresentada como se atendesse. Se o candidato econômico falhar, registrar a limitação e discutir essa redução de escopo, em vez de simular silenciosamente o efeito elétrico.

## Orçamento máximo: R$ 250 por unidade

Valores pesquisados em 05/10/2026. A coluna de reserva define a distribuição pretendida do orçamento. Não é um carrinho de compra fechado: faltam variante USB, circuito de corte, frete e conferência final de estoque.

| Componente | Referência pesquisada / requisito | Reserva |
| --- | --- | ---: |
| ESP32 DevKit | Catálogo RoboCore: R$ 42,90 | R$ 43 |
| Módulo fonte USB-C SW3518/S | Candidato; teto já incluindo encargos dessa importação | R$ 40 |
| Fonte externa fechada 12 V / 2 A | Catálogo RoboCore: R$ 21,90; entrada para conversão interna | R$ 22 |
| Conversor 12 V → 5 V do ESP32 | LM2596 Eletrogate: R$ 8,90; ajustar e conferir antes de conectar | R$ 9 |
| Medidor INA226 | Toni Eletrônica: R$ 30,99; shunt e faixa precisam ser conferidos | R$ 31 |
| Corte DC e proteção | Chave de potência, fusível e componentes auxiliares; modelo pendente | R$ 20 |
| Cabo USB-C | Cabo adequado, íntegro e com retenção mecânica | R$ 20 |
| Fios, conectores e montagem | Chicote, entrada DC, placa auxiliar e isolamento | R$ 20 |
| Temperatura e indicação | NTC, LED e resistores | R$ 8 |
| **Subtotal reservado** | | **R$ 213** |
| **Fretes nacionais e imprevistos** | Margem conjunta, sem contar duas vezes encargos do módulo USB | **R$ 37** |
| **Teto total** | **5 integrantes × R$ 50** | **R$ 250** |

Referências: [ESP32](https://www.robocore.net/wifi), [fonte 12 V / 2 A](https://www.robocore.net/fonte/fonte-chaveada-12v-2a), [catálogo de fontes](https://www.robocore.net/robotica-automacao), [LM2596](https://www.eletrogate.com/modulo-regulador-de-tensao-step-down-lm2596), [INA226](https://tonieletronica.com/ina226-modulo-sensor-de-corrente-tensao-dc-alta-precisao-i2c/).

A soma fecha como meta, mas a viabilidade do kit completo ainda não está comprovada. Consolidar fornecedores ajuda a preservar a reserva. A fonte de 12 V alimenta o estágio conversor; não vai diretamente ao telefone nem ao ESP32. Não destinar orçamento a uma segunda tela, RFID ou bateria interna nesta versão.

Impressão, acabamento, instrumentos e ferramentas não estão incluídos. Prever empréstimo de multímetro, fonte/carga de bancada e, para validar negociação, analisador USB apropriado do laboratório. Um medidor USB simples não comprova sozinho todos os estados PD. Se esses recursos precisarem ser comprados, o orçamento deverá ser revisto explicitamente.

## Arquitetura elétrica a detalhar

A fonte externa isolada de 12 V entra por um conector protegido e se divide em dois ramais:

1. Conversor de 5 V para ESP32 e circuitos de controle, permanentemente alimentados enquanto a fonte estiver ligada.
2. Medição do ramal de potência, módulo fonte USB-C e mecanismo de habilitação/corte → cabo → telefone.

O caminho exato de corte depende da placa escolhida. Deve permitir configurar o controlador USB enquanto a porta permanece sem energia autorizada e evitar alimentação transitória no boot. Não basta colocar um relé antes do módulo e presumir que será possível configurá-lo desligado. Também não cortar sinais CC ou o retorno de forma improvisada. Exigir desenho do circuito e ensaio de inicialização antes de declarar esse requisito atendido.

O ESP32 conversa por I²C com sensor e controlador. GPIOs não conduzem corrente de carga. Conferir pull-ups e níveis lógicos; usar adaptação se necessária. Prever acesso à programação e impedir retorno indevido de alimentação ao computador durante USB de serviço.

O INA226 pode medir o ramal na entrada do conversor USB: nesse caso, a telemetria se chama **energia do ramal USB**, incluindo perdas do conversor. A medição interna de saída do SW3518, se disponível e calibrada, é outra fronteira. Não calcular corrente do telefone dividindo potência de entrada por 5 V e apresentá-la como medida. Nenhuma dessas leituras equivale a energia efetivamente armazenada na bateria.

Conferir o shunt instalado: segundo a [TI](https://www.ti.com/product/INA226), a faixa de tensão diferencial é limitada. Um shunt de 0,1 Ω pode saturar o INA226 acima de aproximadamente 0,819 A. A descrição comercial de um módulo não resolve sua faixa real. Preferir variante adequada, calibrada, evitando retrabalho fino de solda.

Saída padrão desligada em boot/reset, configuração incompleta e falhas. Corte local por sobrecorrente/temperatura e autorização expirada; proteção elétrica não depende apenas da rede. Fios e conectores adequados à corrente, sem Dupont no caminho final de potência. Somente baixa tensão dentro da carcaça; fonte de rede fechada do lado de fora. Verificar dissipação com a montagem fechada.

## Carcaça derivada do STEP

Envelope medido do corpo original: aproximadamente **450,05 × 208,53 × 164,72 mm**, altura × largura × profundidade. Em 70%: **315,03 × 145,97 × 115,30 mm**. São dimensões externas; o espaço útil será menor e depende do redesenho.

O STEP contém uma montagem industrial, não um modelo preparado para FDM. Preservar as superfícies externas e suas divisões visuais; remover suportes e eletrônica originais; reconstruir paredes, encaixes e berços com dimensões próprias para impressão. Não escalar simplesmente toda a estrutura interna.

### Construção proposta sem parafusos

- Traseira estrutural com trilhos para bandeja.
- Frente e tampa superior seguindo as superfícies originais.
- Bandeja removível com berços substituíveis para as placas.
- Inserto inferior com alívio de tração do cabo USB-C.
- Base ou suporte de bancada separado, conforme estabilidade.

A tampa encaixa primeiro em ganchos e fecha em duas linguetas liberáveis por trás/baixo. As placas ficam apoiadas pelas bordas, sem pressionar componentes, antena ou conectores. A bandeja desliza e trava. Puxar o cabo não pode transmitir esforço ao conector da placa.

“Sem parafusos” aplica-se inicialmente à carcaça e à fixação das placas. Bornes elétricos podem ter parafusos; se também forem indesejados, escolher conectores de mola ou chicotes crimpados dimensionados. Não depender de cola permanente para acessar a manutenção.

Ponto de partida para ensaio: PETG, paredes de 2,0–2,4 mm e folgas de 0,25–0,40 mm por lado. Esses valores não são uma receita validada; imprimir cupons de encaixe e orientar camadas para resistência das linguetas. PLA pode servir à prova visual. Referências: [PETG Prusa](https://help.prusa3d.com/article/petg_2059) e [projeto para impressão](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135).

### Organização interna preliminar

| Região | Uso proposto | Reserva de estudo, ainda sem verificação de interferência |
| --- | --- | --- |
| Superior | ESP32 e acesso de programação | 65 × 40 × 25 mm, mais espaço da antena |
| Central | Módulo USB de potência | 70 × 45 × 30 mm |
| Lateral central | Conversor do ESP32 e medidor | Dois berços separados, dimensões após seleção |
| Inferior | Proteção, entrada DC e retenção do cabo | 65 × 40 × 30 mm, mais curvatura dos fios |

Bandeja inicial de estudo em torno de 210 × 85 mm. Essas reservas são hipóteses, não um desenho de encaixe concluído. O STEP precisa de análise de interferências depois de inserir os modelos dimensionais das placas efetivamente compradas. O painel externo não ocupa essa carcaça.

Uma peça de 315 mm não deve ser presumida imprimível inteira em uma máquina de 220/256 mm. Precisamos do volume útil e da orientação de impressão. Usar máquina adequada ou dividir peças em locais discretos, com acabamento das emendas. A meta é conservar o desenho externo; as emendas e tolerâncias de fabricação ainda precisam ser resolvidas.

## Sequência de desenvolvimento e aceite

1. **Fechar a interface USB.** Confirmar placa com I²C acessível, documentação, perfis e corte; verificar total entregue. Sem isso, não liberar a lista final de compra nem prometer variação de velocidade.
2. **Bancada independente.** Montar alimentação, proteção e medição; testar com carga apropriada antes do telefone. Comprovar saída desligada no boot e controle local de falhas.
3. **Prova de perfis.** Validar telefone e negociação a 5 V, mudança de capacidade, interrupções e estabilidade. Se não for possível, registrar a função não suportada; nunca confirmar um limite apenas porque a variável mudou.
4. **Firmware e API novos.** Implementar máquina de estados, comandos idempotentes, medição, limites, expiração de autorização e registros finais. Testar inicialmente com um cliente simples, independente do painel.
5. **Integração com o painel.** Adicionar adaptador para consumir a API do emulador, mantendo software e identidades separados. Ensaiar START, alteração de perfil e STOP com confirmação real.
6. **CAD para impressão.** Congelar placas e dimensões, revisar interferências, gerar bandeja e encaixes; testar cupons antes da carcaça. Só então exportar STEP adaptado, STL/3MF e orientação de montagem.
7. **Ensaio do pitch.** Testar rede, reset, falta de alimentação, temperatura, energia final e cabo. A demonstração de potência depende de o telefone estar consumindo o suficiente; definir condição de bateria e tela para repetibilidade.

Critérios: sem início indevido após reset; rejeição de comandos inválidos/repetidos; energia monotônica e sessão final recuperável; medição comparada com instrumento em três pontos; proteção local mesmo com rede bloqueada; dez ciclos iniciais de abertura sem ruptura; retenção de cabo sem esforço nos conectores; ensaio térmico na maior carga aprovada com carcaça fechada.

## Próximas informações úteis

Modelo exato do celular e impressora disponível são as duas informações que mais reduzem incerteza agora. Depois delas e da escolha do módulo USB, é possível fechar o esquema, a compra e a modelagem interna. O orçamento está limitado a R$ 250; a variação de capacidade permanece um requisito a provar, não uma promessa baseada no anúncio da placa.
