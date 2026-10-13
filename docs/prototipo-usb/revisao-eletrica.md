# Revisão elétrica histórica — TPS25810 + INA260 (rota excluída)

**ROTA EXCLUÍDA pela exigência posterior do usuário: somente módulos prontos. TPS25810 e INA260 avulsos exigem montagem SMD e PCB própria, portanto não são a seleção atual. O conteúdo abaixo é registro técnico histórico, sem liberação para compra ou fabricação.**

Revisão de 5 de outubro de 2026. **Esquema funcional conceitual; não é PCB fabricável, BOM fechada, produto certificado ou autorização de compra.** O arquivo `nets-plano.json` registra as conexões para a próxima revisão de esquema. Não fornece footprints de conectores, dimensionamento de cobre ou Gerber.

## Decisão de arquitetura

Manter fonte externa isolada, entrada de baixa tensão, ESP32-WROOM-32 clássico, TPS25810 como fonte USB-C e INA260 no caminho de VBUS. O resultado pretendido é anunciar capacidade de **1,5 A ou 3 A a 5 V**, habilitar/interromper a porta e medir energia entregue no receptáculo. Não controla diretamente bateria, tensão interna, porcentagem ou corrente escolhida pelo telefone. Não oferece PD, QC, 9 V, 12 V nem ajuste contínuo de potência.

O modelo do telefone continua indispensável para validar a demonstração. Há relato documentado de testes da própria placa TI nos quais celulares consumiram menos que 3 A apesar do anúncio correto; a equipe TI aponta dependência do protocolo aceito pelo aparelho. Logo, diferença visível entre os dois níveis não está garantida só pelo conector USB-C. [Suporte TI: testes com celulares](https://e2e.ti.com/support/power-management-group/power-management/f/power-management-forum/1125278/tps25810-tests-with-phones).

```text
Fonte externa → entrada/proteção a dimensionar → +5V_POWER
                                     ├─ alimentação da placa ESP32 → +3V3_LOGIC
                                     ├─ TPS.IN2 → VCONN via CC1/CC2
                                     └─ TPS.IN1 → TPS.OUT → INA.IN+ → INA.IN− → USB.VBUS
                                                          │                      │
                                                bleeder opcional            INA.VBUS
ESP GPIO → EN / CHG / CHG_HI            ESP I²C ← INA260           TPS CC1/CC2 ↔ USB
```

Todos os retornos de potência compartilham GND, dimensionado para a corrente. O desenho não indica bitola, comprimento nem queda zero. Os terminais de potência não passam por breadboard, Dupont ou pistas estreitas de adaptador DIP sem análise.

## Referências técnicas e conexões confirmadas

- [TPS25810, SLVSCR1C](https://www.ti.com/lit/ds/symlink/tps25810.pdf): pinagem p. 3; limites p. 4–8; operação p. 14–21; aplicação p. 23; alimentação/layout p. 27–28; encapsulamento no final.
- [INA260, SBOS656C](https://www.ti.com/lit/ds/symlink/ina260.pdf): pinagem p. 4; medições p. 12–16; endereços/registradores p. 17–26; alimentação/layout p. 29.
- [Guia TPS25810EVM-745](https://www.ti.com/lit/ug/slvuai0a/slvuai0a.pdf): referência de esquema, layout e BOM. A nomenclatura antiga do pino 9 não substitui REF_RTN no datasheet atual.
- [ESP32-WROOM-32](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf) e [GPIO no ESP-IDF](https://docs.espressif.com/projects/esp-idf/en/stable/esp32/api-reference/peripherals/gpio.html).

| TPS25810 U1 | Rede proposta |
|---|---|
| 1 FAULT# | TPS_FAULT_N → GPIO 33; pull-up 100 kΩ a 3,3 V |
| 2/3 IN1; 4 IN2 | +5V_POWER |
| 5 AUX | +3V3_LOGIC |
| 6 EN; 7 CHG; 8 CHG_HI | GPIO 25/26/27 respectivamente; cada entrada com pulldown externo 10 kΩ |
| 9 REF_RTN | Somente R_REF; **não aterrar** |
| 10 REF | R_REF 100 kΩ, 1%, ≤100 ppm/K, até pino 9 |
| 11 CC1; 13 CC2 | CC1/CC2 independentes do receptáculo |
| 12 GND; pad inferior | GND/plano térmico |
| 14/15 OUT | VBUS_SWITCHED → INA260 IN+ |
| 19 UFP# | TPS_UFP_N → GPIO 32; pull-up 100 kΩ a 3,3 V |
| 16 DEBUG#; 17 AUDIO#; 18 POL#; 20 LD_DET# | Sem conexão funcional; pads de teste opcionais |

AUX em 3,3 V simplifica as saídas de estado e faz o controlador depender da alimentação lógica. Não ligar seus pull-ups a 5 V. Todos os sinais do ESP32 ficam em 3,3 V. As entradas EN/CHG/CHG_HI aceitam esse nível. O desenho depende de a placa ESP32 escolhida fornecer3,3 V adequadamente; a entrada5 V dela e a coexistência com USB de programação exigem conferir o esquema da placa real.

| INA260 U2 | Rede proposta |
|---|---|
| 1/2/3 IN+ | VBUS_SWITCHED, todos os terminais conectados |
| 14/15/16 IN− | VBUS_PORT, todos os terminais conectados |
| 12 VBUS | Sense de VBUS_PORT próximo ao receptáculo |
| 10 VS; 6/11 GND | +3V3_LOGIC; GND |
| 4 A1; 5 A0 | GND; endereço I²C7 bits 0x40 |
| 8 SDA; 9 SCL | GPIO 21/22; pull-ups externos 4,7 kΩ a 3,3 V como ponto de partida |
| 7 ALERT# | GPIO 34; pull-up externo 10 kΩ a 3,3 V |
| 13 NC | Não conectado |

Não criar resistência externa de shunt: o INA260 já a integra. O caminho completo é aproximadamente 4,5 mΩ típicos;2 mΩ é apenas o elemento de medição interno. O adaptador comercial não documenta corrente de suas pistas. Deve-se projetar cobre para todos os terminais de corrente.

## Sensor, descarga e significado das leituras

**Escolha proposta: sensor depois da chave TPS, antes do receptáculo.** Assim a corrente exclui ESP32, consumo interno do TPS e VCONN, pois IN2 deriva antes do sensor. A tensão é lida no receptáculo e não no telefone. Perdas no cabo USB, conversão dentro do telefone e energia realmente acumulada na bateria não são medidas.

Colocar o sensor antes de IN1 também permitiria medir o ramo de VBUS, mas incluiria efeitos da chave/bypass a jusante e exigiria manter o sense de tensão separado na porta. Colocá-lo antes da derivação IN1/IN2 mediria também VCONN; isso não é a grandeza escolhida para o painel.

O shunt é bidirecional e não deve receber diodo em série: o capacitor de VBUS_PORT pode descarregar de volta através dele até o circuito de descarga em OUT. Esse transiente pode produzir corrente negativa. Reservar um bleeder opcional de 1 kΩ/0,125 W em **VBUS_SWITCHED**, antes do sensor: consumiria5 mA/25 mW a 5 V sem somar esse consumo à energia da porta durante regime. Seu povoamento é uma decisão de ensaio, não componente já comprado.

O tempo de descarga do TPS publicado foi medido após remoção da assinatura CC. Não extrapolar automaticamente esse número para EN=0, perda de AUX ou todas as capacitâncias de telefone/cabo. Ensaiar essas situações separadamente. Após stop, verificar tensão baixa na porta antes de permitir nova partida; se ela continuar alimentada, registrar falha em vez de presumir sucesso. O limiar inicial de bancada proposto é 0,8 V e timeout 1 s; são parâmetros de projeto a validar, não promessa de conformidade derivada só deste documento.

O registrador de potência do INA260 permanece positivo mesmo com corrente reversa. Para telemetria assinada, calcular `power_w = voltage_v × current_a`, usando corrente como inteiro16 bits com sinal. Integrar somente amostras novas e válidas; distinguir energia positiva entregue, retorno e energia de inicialização. Não integrar lacunas de comunicação como se fossem medições. O aparelho não precisa consumir o teto anunciado para o comando ter sido aplicado.

## Inicialização e estados seguros

| EN | CHG | CHG_HI | Interpretação |
|---:|---:|---:|---|
| 0 | 0 | 0 | Repouso por resistores; controlador desabilitado |
| 0 | 1 | 0/1 | Capacidade preparada, porta ainda desabilitada |
| 1 | 0 | 0/1 | STD; não expor como perfil comercial deste protótipo |
| 1 | 1 | 0 | Anúncio1,5 A; proteção de corrente típica1,7 A |
| 1 | 1 | 1 | Anúncio3 A; proteção típica3,4 A |

Os pulldowns10 kΩ são uma proposta de circuito e precisam estar fisicamente próximos a U1. Eles mantêm EN baixo quando o ESP32 fica em alta impedância, é removido ou reinicia. Não são substituídos por configuração de software. Uma CPU travada com saída alta continuará habilitando a porta até watchdog/reset; o esquema não contém supervisão externa independente.

Sequência proposta: manter EN baixo; inicializar I²C e verificar identidade/resposta do INA260; configurar e conferir medições; configurar CHG=1 e CHG_HI=0; só habilitar EN após comando de sessão válido. Para parar, baixar EN primeiro. Não retomar carga automaticamente depois de reset/brownout ou falha de sensor. Separar `TPS_EN` do `EN/CHIP_PU` que reinicia o ESP32.

Quando EN=0, a detecção CC do TPS também está desabilitada. `UFP#=1` nessa condição **não comprova ausência de cabo**: reportar presença desconhecida. É uma limitação desta arquitetura para emular o estado de conexão de um carregador veicular. Uma detecção física permanente sem energizar o telefone exigiria outra arquitetura, ainda não aprovada.

Mapa lógico para ESP32-WROOM-32 clássico: SDA21, SCL22, EN25, CHG26, CHG_HI27, UFP#32, FAULT#33 e ALERT#34. GPIO 34 é somente entrada, sem pull-up interno. Foram evitados straps 0/2/5/12/15, flash 6–11 e UART 1/3; ainda é preciso verificar ocupação desses GPIOs na placa real. São números de GPIO, não posições de header. GPIO 35/ADC1 pode ficar reservado a NTC externo, cujo beta, divisor, calibração e limite térmico ainda não estão definidos.

## Alterar capacidade com o telefone conectado

A TI permite CHG/CHG_HI dinâmicos e descreve, na seção 7.3.3.13, resposta do sink à redução do anúncio em até 60 ms. Isso confirma que não é necessário desconectar obrigatoriamente a cada mudança. **Não confirma que todo celular aceitou a mudança nem que o consumo mudará para exatamente1,5/3 A.**

Manter CHG=1 e alterar somente CHG_HI. A redução3→1,5 A também troca o limite da chave. Não encontrei especificação separada garantindo atraso do limitador por 60 ms; não inventar tal intervalo. Uma queda de VBUS ou FAULT durante a redução precisa ser observada e tratada, sem ignorar falha por um temporizador arbitrário.

Política proposta antes da bancada: anunciar suporte a dois perfis, mas `online_capacity_change_verified=false`. Validar mudança online com carga USB-C que responda a CC e depois com o telefone escolhido. Se o conjunto precisar de desligamento/reconexão para aplicar o nível, reportar explicitamente transição com interrupção. Uma carga eletrônica comum fixa em 3 A não simula a resposta CC de um telefone e não serve sozinha para aprovar esse comportamento.

O INA260 pode fornecer amostras rápidas, mas um painel a 1 Hz não verifica transientes de 60 ms. Para bancada, propor média 1 e conversões de corrente/tensão de 140 µs (`CONFIG=0x6007`), e registrar `conversion-ready`; não confundir taxa de consulta com amostra nova. Para operação inicial, a configuração 0x6127 produz conversões nominais de 1,1 ms por grandeza, sem média. Verificar esses valores por leitura de volta antes de aplicar. Osciloscópio/carga apropriada continuam necessários para quedas rápidas.

ALERT oferece uma função de limiar de cada vez, além de conversion-ready opcional. Não prometer sobrecorrente e subtensão independentes simultâneas nessa saída. Proteção rápida permanece no TPS; alerta digital e firmware complementam, não substituem esse circuito. O limiar específico de ALERT ainda depende da política de falha e dos ensaios.

## Conector, capacitores e ESD

Usar receptáculo USB-C com CC1 e CC2 acessíveis individualmente e corrente declarada para3 A. Os nomes A/B abaixo são contatos USB-C lógicos; a numeração de pads depende do conector comprado. Conectar todos os VBUS disponíveis, todos os GND e as ancoragens conforme desenho do fabricante. CC1(A5)→U1.11 e CC2(B5)→U1.13, sem juntá-los e sem resistores Rd de 5,1 kΩ de placas sink. Não adicionar Rp externo em paralelo ao controlador.

IN2 alimenta VCONN no CC não usado, quando o cabo identificado o exige. Proteção CC deve tolerar a tensão de VCONN; não usar clamp de 3,3 V por conveniência. O TPS possui especificação ESD nos CC, mas isso não valida a placa montada. Reservar proteção junto ao conector e selecionar posteriormente part number, fuga, capacitância e comportamento de clamp. VBUS também precisa de revisão de sobretensão/ESD; TVS e fusível não podem ser escolhidos apenas pela palavra “5 V”.

D+/D−, SBU e pares SuperSpeed ficam sem função no conceito. Não montar BC1.2 ou curto D+/D− inadvertidamente: isso altera o comportamento do telefone e exige nova validação dos níveis. A soldagem/footprint do receptáculo e conexão da blindagem ainda precisam de decisão explícita de layout/ESD.

Proposta de desacoplamento: bulk de 150 µF com capacitância mínima≥ 120 µF na entrada de potência, cerâmico local de 0,1 µF e capacitor local adicional conforme resposta da fonte;0,1 µF em AUX e em VS do INA260. Não transferir o bulk para a porta fria.

**Divergência documental a resolver:** a figura inicial do TPS25810 Rev.C usa6,8 µF na saída, enquanto o texto ainda recomenda10 µF. A TI explica em [TPS25740 §8.1.1](https://www.ti.com/lit/ds/symlink/tps25740.pdf) a necessidade de capacitância abaixo 10 µF no receptáculo vazio. Propor6,8 µF como ponto de partida, contabilizando tolerância e todos os paralelos, e validar transientes/capacitância efetiva antes de congelar valores. Não copiar10 µF±20% mais capacitores em paralelo sem revisão. Capacitores cerâmicos perdem capacitância com polarização; seu código comercial precisa ser escolhido e conferido.

## Orçamento de tensão e temperatura

O critério inicial para o receptáculo é 4,75–5,5 V, conforme a seção 9 do TPS25810. A corrente indicada na etiqueta de uma fonte não assegura regulação adequada. Adotar a maior resistência publicada do TPS na faixa inteira e a resistência típica do INA apenas para triagem; o segundo valor não é um limite máximo garantido do conjunto.

| Cálculo | A1,5 A | A3 A |
|---|---:|---:|
| TPS,55 mΩ | 82,5 mV /0,124 W | 165 mV /0,495 W |
| INA260,4,5 mΩ típicos completos | 6,75 mV /0,010 W | 13,5 mV /0,0405 W |
| Queda combinada desses dois caminhos | 89,25 mV | 178,5 mV |
| Margem restante, fonte real5,00 V até 4,75 V | 160,75 mV | **71,5 mV** |
| Resistência restante de ida+retorno | 107,2 mΩ | **23,8 mΩ** |

A margem restante deve pagar cabo DC, contatos, fusível, proteção de polaridade, cobre e retorno de GND até o receptáculo. Se os5,00 V forem medidos já na entrada da PCB, as perdas anteriores foram absorvidas nessa medição e não devem ser contadas novamente. Com4,90 V na fonte, TPS+INA já deixariam aproximadamente 4,7215 V a 3 A, antes dessas outras perdas. Portanto, **a fonte candidata5 V/5 A não está aprovada**. Não há evidência de ajuste disponível nela; não recomendar alterá-la.

O cabo USB vem depois desse orçamento. Exemplo calculado, não medido:4,7615 V na porta e resistência de loop do cabo de 0,10 Ω resultariam em 4,4615 V no telefone a 3 A. Não aplicar automaticamente o limite do receptáculo da fonte ao terminal do celular. Medir ambos, identificar queda/limitação escolhida pelo aparelho e validar o cabo real. Caso a fonte fixa não passe, mudar a fonte para uma opção regulada documentada e refazer custo/dimensões; não compensar perda prometendo tensão ajustável inexistente.

Provisionar alimentação para a porta, ESP32 e VCONN. A fonte deve suportar também transientes e o limite real da chave, que pode superar3 A;5 A de etiqueta não comprova isso. O limite total, fusível e conector de entrada continuam pendentes.

O pad térmico de U1 precisa estar soldado ao plano adequado, sem plástico pressionando o CI. Reservar área de cobre/ventilação; não transformar RθJA de placa de referência em previsão da carcaça impressa. Ensaiar3 A continuamente com a caixa fechada, Wi-Fi ativo e fonte/cabo reais. A proteção interna por temperatura protege o silício em falha; seu limiar não é temperatura aceitável para PETG, conectores ou toque. NTC externo, posição e limite de desligamento precisam ser validados antes da apresentação.

## Contingência de alimentação: 12 V e XL4015

A [EasyTronics REF1106](https://www.easytronics.com.br/xl4015-modulo-step-down-5a) oferece módulo XL4015 por R$ 12,70, com dissipador e dimensão anunciada de 54 × 23 × 15 mm. A combinação com a fonte externa RoboCore 12 V/2 A de R$ 21,90 soma R$ 34,60 antes de fretes. São preços de alternativas, sem mudar automaticamente a rota principal ou declarar esse conjunto aprovado.

O [datasheet XLSEMI](https://www.xlsemi.com/datasheet/XL4015-EN.pdf) confirma entrada de 8–36 V, ajuste resistivo de saída e comutação de 180 kHz. A referência típica de 12 V→5 V/5 A apresenta eficiência de 87%; isso não é garantia do módulo comercial nem eficiência medida a 3 A. O tab metálico do CI é **SW**, um nó comutado, e não GND. Conferir isolamento do dissipador e impedir contato com outros condutores. O valor “5 A” do anúncio não dispensa análise térmica do indutor, diodo, PCB e conexões.

Se a fonte fixa reprovar, essa alternativa permite ajustar o conversor uma vez para uma meta inicial de 5,10 V, conferir com carga, depois proteger o trimpot contra movimento. Não usar o trimpot, PWM ou um limite analógico para comandar a velocidade do telefone: o controle continua sendo CHG_HI do TPS. Medir overshoot na partida, sem carga e na retirada brusca de carga, ripple, regulação, desligamento e temperatura. Nunca conectar a saída antes de medi-la. Não alimentar diretamente TPS/ESP32 com 12 V.

Há uma troca de margem elétrica por calor e espaço. Exemplo de cálculo, com consumo de controle **assumido** em 0,5 A e VCONN em 0,25 A: `(3 + 0,5 + 0,25) × 5,1 = 19,125 W` na saída. Com eficiência ilustrativa de 87%, são cerca de 22 W/1,83 A em 12 V; a fonte de 24 W tem pouca margem. Considerando o máximo publicado do limitador TPS (3,64 A) e VCONN (0,41 A), mantendo a mesma reserva de controle, o exemplo passa a 26,7 W, acima de 24 W. Uma fonte 12 V/3 A documentada, ou outra revisão dos limites e da proteção, pode ser necessária. O conjunto 12 V/2 A ainda precisa passar por degraus e falhas sem provocar religamentos indevidos.

O dissipador aumenta a reserva mecânica e o calor do conversor fica dentro da caixa. As medidas do anúncio não informam furação, altura final da solda, bordas de apoio ou isolamento: o berço modular só pode ser congelado após inspeção. A fonte de 12 V também desloca a queda do cabo de entrada para antes do regulador, mas a resistência entre o conversor e a porta USB continua no orçamento de tensão.

## Ensaios que liberam a próxima etapa

1. Conferir marcação dos CIs, pin1, continuidade, polaridade e ausência de curto; revisar esquema antes de fabricar PCB.
2. Alimentar inicialmente com fonte de bancada limitada. Sem telefone, verificar 3,3 V, GPIOs e EN baixo durante ligar/reset/programar/desconectar o ESP32.
3. Testar conexão nos dois sentidos com uma assinatura Rd em um CC por vez; VBUS deve aparecer somente após conexão válida e autorização. Uma carga só em VBUS não substitui esse teste. Nunca deixar os resistores de fixture conectados em paralelo com um telefone.
4. Validar1,5 A e3 A com carga apropriada; medir fonte, IN1, OUT, VBUS_PORT e ponta do cabo; observar corrente, FAULT, aquecimento e resposta a degraus. Ensaiar limite/curto com equipamento apropriado antes de conectar celular.
5. Testar retirada de cabo, stop por EN, reset do ESP32, perda deAUX/3,3 V, perda da fonte5 V e falha I²C. Registrar descarga e eventual retorno de energia. Não religar se VBUS residual ou falha persistir.
6. Ensaiar3→1,5→3 A com resposta CC, sem extrapolar limite de tempo ou mascarar FAULT. Repetir com telefone escolhido, nível de bateria e temperatura registrados.
7. Conferir leituras/energia contra instrumento externo, inclusive corrente negativa. Só então definir limites, publicar capacidades reais e congelar footprint/berço da PCB.

Pendências que impedem fabricação: part numbers de fonte/conector/proteções/passivos; confirmação do lote TPS; cotação PCB/montagem; cálculo de cobre e temperatura; teste do telefone; esquema da placa ESP32 e alimentação USB; política de falha/descarga e dimensões reais. A pesquisa anterior de módulos prontos nacionais não forneceu nova alternativa verificável; esta revisão não repete nem substitui essa evidência.
