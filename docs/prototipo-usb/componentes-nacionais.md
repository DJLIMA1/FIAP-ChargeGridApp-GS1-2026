# Componentes nacionais do ChargeGrid Mini

Pesquisa de compra e engenharia realizada em 5 de outubro de 2026. Teto de R$ 250 por unidade, sem impressão ou painel. Preços de produto sem frete, sem pedidos realizados. Não foi fornecido CEP; prazos e descontos exibidos nas lojas não constituem cotação de entrega para o grupo.

**Situação atual após a resposta do grupo:** somente módulos prontos; sem fabricação ou montagem de PCB com CIs avulsos. Assim, TPS25810 e INA260 avulsos estão excluídos da seleção de compra. A pesquisa abaixo conserva as comparações e motivos, mas a rota de controle variável ainda não está fechada. A seleção atual é apenas a família ESP32 WROOM; fonte, sensor, módulo USB e seus berços dependem de uma combinação pronta compatível.

O SW3518 de R$ 40 previsto no plano inicial foi retirado da seleção nacional. Aquele valor era uma reserva, não um produto validado. O grupo reafirmou controle variável como requisito obrigatório; a versão apenas liga/desliga foi descartada como solução final. A pesquisa de módulos e a hipótese de perfis comutados estão nos documentos vinculados pelo plano principal.

## Critério para uma escolha definitiva

Uma opção precisa passar por quatro verificações: função elétrica correta; estoque e origem do envio; custo entregue; geometria da placa e dos conectores. “Selecionado como referência” significa escolha de projeto; não significa ensaio concluído ou compra integral autorizada pelo orçamento.

A disponibilidade abaixo é a anunciada na consulta. Catálogo com botão de compra é evidência mais fraca que quantidade de estoque. Componentes de lojas nacionais ainda precisam de conferência de lote. Não usar dimensões de um clone ou de um chip para fabricar o suporte de outra placa.

## Controlador definido pelo grupo

O usuário definiu um ESP32 com módulo WROOM de origem chinesa, sem compra da placa RoboCore. A hipótese de montagem é uma placa de desenvolvimento com USB e pinos; o modelo, o custo e a posse prévia ainda não foram informados. A família do controlador está escolhida; dimensões e furação da placa permanecem pendentes. O berço será substituível e ajustável, sem furos específicos na carcaça.

As opções abaixo ficam apenas como comparação de mercado da pesquisa anterior, não como seleção de fornecedor.

| Opção e fornecedor | Preço anunciado | Evidência e decisão |
| --- | ---: | --- |
| [ESP32 RoboCore 1013 Micro-USB](https://www.robocore.net/wifi/esp32-wifi-bluetooth) | R$ 42,90 no [catálogo](https://www.robocore.net/wifi) | Não selecionado pelo usuário. As cotas 54 × 29 × 13 mm pertencem somente a esta placa; não aplicá-las ao ESP32 do grupo. |
| [ESP32 MakerHero 6WL55](https://www.makerhero.com/produto/modulo-wifi-esp32-bluetooth/) | R$ 42,90; R$ 40,75 no Pix | Em estoque. Mesmo preço, mas sem desenho dimensional da placa. Alternativa se o frete conjunto compensar; conferir outro berço. |
| [DOIT ESP32 Saravati](https://www.saravati.com.br/placa-esp32-wifi-bluetooth-devkit-v1-30-pinos.html) | R$ 65,90 | Estoque anunciado. Custo maior sem benefício necessário à demonstração. |
| [Kit ESP32 USB-C no Mercado Livre](https://produto.mercadolivre.com.br/MLB-4981064683-kit-esp32-devkit-v1-wifi-bluetooth-usb-c-30-pinos-cabo-_JM) | R$ 61,99 | Inclui cabo, mas variante e origem do envio não ficaram completamente determinadas. Não escolhido. |

O [datasheet Espressif](https://www.espressif.com/sites/default/files/documentation/esp32-wroom-32_datasheet_en.pdf) descreve o módulo eletrônico WROOM, não os furos de uma placa de desenvolvimento genérica. O fabricante publica desenhos específicos para suas [placas DevKitC](https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32/esp32-devkitc/user_guide.html); essas cotas também não devem ser transplantadas para outro modelo. Reservar acesso ao USB, BOOT e EN conforme a placa escolhida; apoiar apenas bordas livres verificadas no lote. A antena precisa ficar afastada de cabos e metais, segundo as [orientações de projeto da Espressif](https://docs.espressif.com/projects/esp-hardware-design-guidelines/en/latest/esp32/pcb-layout-design.html).

## Comparação do estágio USB

| Opção | Compra encontrada | Decisão |
| --- | --- | --- |
| [TPS25810, kit de três, CRAME no Mercado Livre](https://www.mercadolivre.com.br/kit-com-3-circuitos-integrados-tps25810-controlador-de-driver-usb-c/p/MLB50168984) | R$ 29,50; mais de 50 disponíveis; entrega nacional indicada no navegador | **Excluído pela exigência de módulos prontos.** Anúncio contradiz foto ao mencionar marcação A36; confirmar lote. Contabilizar o kit completo no desembolso. |
| [TPS25810, segundo anúncio CRAME](https://www.mercadolivre.com.br/kit-3-ci-25810-driver-controlador-usbc-wqfn20-tps25810rvcr/up/MLBU1150074991) | R$ 32,50; mesma loja e ressalva | Sem vantagem técnica; mais caro. |
| [Módulo PD 65 W Toni](https://tonieletronica.com/modulo-fonte-step-down-carregador-usb-c-pd-65w-qc4-0-qc3-0/) | R$ 25,99; fora de estoque; 44 × 20 × 10 mm declarados | Chip e interface programável não publicados. Não atende à seleção. |
| [SW3518 em marketplace](https://shopee.com.br/Adaptador-De-Carga-R%C3%A1pida-HUINET-USB-Tipo-C-SW3518-Mudule-QC4.0-QC3.0-1-2-4-Vias-i.427561812.53204123331) | R$ 18,27–66,31 conforme variante; internacional | Excluído pela origem do envio. Resultados Mercado Livre consultados também indicavam China. |
| [MIKROE-5682 / TPS25750S](https://www.mikroe.com/usb-c-power-click) | Referência US$ 18, estoque externo | Sem fornecimento nacional comprovado; excluído da compra local. |

Na rota TPS25810, a proposta muda para **5 V com capacidade anunciada de 1,5 A ou 3 A**, equivalentes a 7,5 W ou 15 W nominais. Isso exige revisar a fonte, o sensor e a dissipação. Os antigos perfis 0,5/1/1,5 A não estão aprovados. O telefone continua escolhendo o consumo efetivo. [Funções do TPS25810](https://www.ti.com/product/TPS25810).

O TPS25810 é controlador USB-C de fonte, sem USB Power Delivery. Usa EN para habilitação e CHG/CHG_HI para os níveis STD, 1,5 A e 3 A. STD não equivale a um limitador físico de 500 mA. Entradas aceitam comando de 3,3 V; sinais de estado precisam de pull-ups adequados. Corpo WQFN20 de 3 × 4 mm, altura máxima 0,8 mm e passo 0,5 mm; o pad inferior deve ser soldado. Essas são cotas do chip, sem furação mecânica. Não existe ainda uma placa montada para medir. [Datasheet TI, incluindo desenho RVC0020A](https://www.ti.com/lit/ds/symlink/tps25810.pdf).

O [guia da placa de avaliação TI](https://www.ti.com/lit/ug/slvuai0a/slvuai0a.pdf) contém esquema, layout e lista de materiais. Serve de referência; não copiar nomenclatura antiga sem conferir a revisão atual, particularmente o pino REF_RTN. Precisaremos de conector USB-C fonte, capacitores, resistor de referência, tratamento de ESD, trilhas e plano térmico. Não é uma montagem adequada em protoboard.

A [RSCAD](https://www.rscad.com.br/) oferece fabricação e montagem SMD sob orçamento. A [RB Circuitos](https://www.rbcircuitos.com.br/) também trabalha com protótipos nacionais. Não há cotação obtida para esta placa. Um site que anuncia produção nacional, [Circuit Darwin](https://www.circuitdarwin.com.br/), ainda informava estar finalizando a operação; não foi contado como fornecedor disponível.

## Comparação de medição

| Opção | Preço e disponibilidade | Uso e decisão |
| --- | --- | --- |
| [INA219 MakerHero 9SS68](https://www.makerhero.com/produto/sensor-de-corrente-dc-ina219-i2c/) | R$ 12,90; em estoque | Melhor preço encontrado para módulo pronto. Seu shunt comum R100 prejudica o caminho USB a 3 A; não escolhido para essa rota. |
| [INA219 TekniMas](https://loja.teknimas.com.br/sensor-de-corrente-dc-ina219-i2c-iot) | R$ 30,04; envio imediato; placa 27 × 24 mm | Mesmo problema de shunt; não justifica o custo maior. |
| [INA219 DR. Eletrônico](https://www.dreletronico.com.br/produto/modulo-sensor-de-tensao-e-corrente-ina219/) | R$ 17,78; cinco em estoque | Dimensões comerciais arredondadas não são desenho de fabricação. |
| [INA226 Toni](https://tonieletronica.com/ina226-modulo-sensor-de-corrente-tensao-dc-alta-precisao-i2c/) | R$ 30,99; página indicava estoque | Não informa shunt ou cotas suficientes. Não aprovar presumindo R002. |
| [INA260 EasyTronics 13290](https://www.easytronics.com.br/ina260-monitor-de-tensao-corrente-e-energia) | R$ 27,00; disponível para compra | **Excluído pela exigência de módulos prontos.** CI e adaptador são enviados sem solda; não é módulo pronto. |

Pelo [datasheet INA219](https://www.ti.com/lit/ds/symlink/ina219.pdf), a faixa de shunt configurável chega a ±320 mV. Isso não elimina a perda resistiva: R100 a 3 A provoca 0,3 V e 0,9 W, calculados por V=IR e P=I²R. Na entrada de um conversor de 12 V a perda relativa pode ser menor, mas essa leitura inclui perdas do conversor e não é a energia medida na porta do telefone.

O [INA226](https://www.ti.com/lit/ds/symlink/ina226.pdf) tem outra faixa diferencial: ±81,92 mV. Com R100, o limite de leitura seria aproximadamente 0,819 A. Não escolher pela corrente escrita no anúncio sem verificar a placa.

O [INA260](https://www.ti.com/lit/ds/symlink/ina260.pdf) integra o shunt de medição de 2 mΩ; o caminho completo tem aproximadamente 4,5 mΩ típicos. A 3 A, isso corresponde a 13,5 mV e 40,5 mW, sem contar a PCB. Corpo TSSOP16 nominal 5 × 4,4 mm; largura incluindo terminais 6,2–6,6 mm, altura máxima 1,2 mm e passo 0,65 mm. Usar todos os terminais de corrente e layout adequado. Adaptador DIP genérico não comprova capacidade de condução.

## Fontes e conversores

| Opção | Preço | Decisão de uso |
| --- | ---: | --- |
| [RoboCore 5 V / 5 A, SKU 1114](https://www.robocore.net/fonte/fonte-chaveada-5v-5a) | R$ 49,90 no [catálogo](https://www.robocore.net/power-supply?newlang=english) | Candidata externa para TPS25810 com 3 A na porta e margem para controle. Regulação sob carga ainda precisa ser ensaiada. |
| [RoboCore 5 V / 3 A P4](https://www.robocore.net/fonte/fonte-chaveada-5v-3a-com-conector-dc-p4) | R$ 39,00 | Serve à investigação de saída de até 1,5 A; não reservar 3 A inteiros ao telefone e alimentar o ESP32 pela mesma fonte. |
| [BitMaker 5 V / 3 A Micro-USB](https://www.bitmaker.com.br/fonte-de-alimentacao-5v-3a-micro-usb-para-esp32-e-raspberry-pi) | R$ 29,90; 16 disponíveis | Mais barata, mas muda a entrada e exige conferir o caminho de corrente. |
| [RoboCore 12 V / 2 A, SKU 1360](https://www.robocore.net/fonte/fonte-chaveada-12v-2a) | R$ 21,90 | Alternativa para estágio conversor de 12 V; não alimentar TPS25810 diretamente. |
| [MakerHero 12 V / 2 A](https://www.makerhero.com/produto/fonte-dc-chaveada-12v-2a-plug-p4/) | R$ 29,90; em estoque | Alternativa conforme frete conjunto. |
| [Mini 560 fixo 5 V RoboCore 3250](https://www.robocore.net/regulador-de-tensao/conversor-dc-dc-step-down-mini-560-5v) | R$ 7,50 | Somente para ramo de controle se a entrada for 12 V. Placa 29 × 18 × 5,4 mm; CI e furos não documentados. |
| [LM2596 Eletrogate](https://www.eletrogate.com/modulo-regulador-de-tensao-step-down-lm2596) / [MakerHero](https://www.makerhero.com/produto/regulador-de-tensao-lm2596-conversor-dc-dc-step-down/) | R$ 8,90 / R$ 9,90 | Alternativas ajustáveis. Confirmar saída antes de conectar. Eletrogate declara 50 × 23 mm; não transferir cotas entre fornecedores. |

A fonte fica fora da carcaça. Sua geometria externa não determina os berços internos, mas plug, polaridade, corrente e cabo determinam a entrada removível. A fonte 5 V/5 A não publica uma curva de regulação; o próprio fornecedor registra limitações de corrente em respostas antigas. Por isso, é candidata de bancada e não fonte já homologada para esta montagem.

O [datasheet LM2596 da TI](https://www.ti.com/lit/ds/symlink/lm2596.pdf) documenta o regulador, não assegura a qualidade do chip, indutor ou dissipação de qualquer módulo genérico. O Mini 560 não oferece identificação técnica suficiente do CI para atribuir um datasheet específico. Não há buck adicional necessário se a arquitetura partir de 5 V regulados adequados.

## Corte e componentes auxiliares

| Função | Escolha de referência e alternativa | Pendência dimensional ou elétrica |
| --- | --- | --- |
| Corte DC independente, se necessário | [Relé RoboCore 258](https://www.robocore.net/driver-motor/modulo-rele), R$ 10,50 no [catálogo](https://www.robocore.net/busca/rele?newlang=brazilian); [Marino 3 V](https://www.marinostore.com/automacao/modulos-rele/modulo-rele-1-canal-3v-com-borne), R$ 18,50 | RoboCore selecionado como opção de corte, não regulador de potência. Na placa TPS25810, EN já controla a chave interna; decidir se relé extra é necessário antes de comprar. |
| Cabo para telefone | [RoboCore C/C 1 m](https://www.robocore.net/cabo/cabo-usb-c-x-usb-c), R$ 19,90 no [catálogo](https://www.robocore.net/cabo); [Elgin C/C](https://www.pontofrio.com.br/cabo-usb-tipo-c-p-tipo-c-1m-branco-elgin/p/1573383676), R$ 41,57 | Cotar cabo com corrente declarada de 3 A; o anúncio RoboCore não fecha essa especificação. Diâmetro, plug e raio de curva não publicados. |
| Temperatura | [NTC MakerHero 10 kΩ](https://www.makerhero.com/produto/termistor-ntc-10k-ohm/), R$ 0,99; EasyTronics B3950 10 kΩ, R$ 1,90 no [catálogo](https://www.easytronics.com.br/controle-automacao) | NTC escolhido como tecnologia; confirmar coeficiente beta e tolerância do lote antes do firmware. Não mede temperatura da bateria. |
| Indicação | [LED RGB 5 mm MakerHero](https://www.makerhero.com/produto/led-alto-brilho-5-mm-rgb/), R$ 0,49–0,59; [difuso](https://www.makerhero.com/produto/led-rgb-difuso-5mm/), R$ 1,90 | Fixar variante cátodo comum, pinagem e três resistores; berço próprio permite substituir o LED. |
| Entrada e chicote de potência | [Conectores RoboCore](https://www.robocore.net/conector/?newlang=brazilian): P4 de painel R$ 0,90, emenda 2 vias R$ 3,20, XT60 par R$ 12,90 | P4 barato sem curva de corrente não será aprovado só por encaixar. Especificação de corrente e polaridade dependem da rota. Escolher conector dimensionado antes de fabricar inserto. |
| Fios | [Cabo bicolor 2 × 1 mm²](https://www.robocore.net/cabo), R$ 6,00; jumpers F/F R$ 6,90 | Fio de potência separado de sinais. Dupont somente para ensaio de lógica, com retenção adequada. |
| Fusível e suporte | [Eletrogate](https://www.eletrogate.com/fusivel): suporte de fio 5 × 20 mm R$ 1,90; fusível 2,5 A R$ 0,32 | Preço de referência. O calibre 2,5 A não é escolha para uma porta de 3 A; corrente, curva e coordenação ainda dependem do circuito. |

O relé RoboCore aceita comando de 3,3 V e alimentação de 5 V; contato normalmente aberto e pulldown no comando dão estado de repouso aberto. Isso não substitui proteção eletrônica. O [desenho da placa](https://d229kd5ey79jzj.cloudfront.net/258/Modulo.Rele_v2.2_mechanical.png) informa 43,8 × 25,4 mm, quatro furos de 3,4 mm e retângulo de centros de 38,7 × 20,3 mm. Conferir a revisão recebida. O [datasheet Metaltex AX](https://d229kd5ey79jzj.cloudfront.net/258/Relay_AX.pdf) informa corpo de 18,8 × 15 × 15,4 mm, sem representar a altura do módulo inteiro.

Rejeitados para esta função: SSR de triac para corrente alternada, IRF520 genérico como chave de VBUS comandada diretamente por 3,3 V, TP4056 para substituir carregador USB e placas PD trigger/sink para atuar como fonte.

## Conta honesta da rota com placa própria

| Item de referência | Desembolso de produto |
| --- | ---: |
| ESP32 WROOM definido pelo grupo | Custo ainda não informado |
| Fonte candidata 5 V / 5 A | R$ 49,90 |
| Kit nacional com três TPS25810 | R$ 29,50 |
| INA260 avulso | R$ 27,00 |
| Cabo C/C candidato | R$ 19,90 |
| **Subtotal dos quatro itens com preço, sem ESP32** | **R$ 126,30** |
| **Saldo para ESP32 e demais custos até o teto de R$ 250** | **R$ 123,70** |

O saldo precisa pagar o ESP32, se houver aquisição, além de PCB, USB-C receptáculo, capacitores, resistores, proteção, entrada, chicotes, LED, sensor térmico, montagem SMD e todos os fretes. Com relé opcional, o saldo antes de contabilizar o ESP32 cai para R$ 113,20. Não assumir custo zero sem confirmação de que o grupo já dispõe da placa. **Esse saldo não é uma cotação de fabricação.** Uma compra mínima de três chips ou quatro placas deve ser contada integralmente no orçamento de uma unidade, sem dividir artificialmente por unidades que o grupo não pretende construir.

Não declarar que o kit completo cabe em R$ 250 até conferir essa soma. Sem laboratório e sem uma cotação compatível, a rota com placa própria não satisfaz simultaneamente os requisitos de facilidade e orçamento. A contingência de 5 V fixos mantém recarga e medição reais, mas perde o ajuste de capacidade; não foi adotada automaticamente.

## Dados que faltam para liberar compra e berços

- CEP para comparar custo entregue, não apenas preço do item.
- Modelo do telefone e comportamento de consumo nos níveis oferecidos.
- Acesso à fabricação e montagem SMD ou orçamento de serviço.
- Confirmação de marcação e revisão dos TPS25810 anunciados.
- Dimensões das placas comerciais recebidas, plugs e fios; furos não publicados permanecem desconhecidos.
- Fonte e cabo capazes de manter tensão adequada na porta sob a maior carga.

Perguntas já preparadas para fornecedores, sem envio: confirmar part number e marcação do TPS25810; informar cotas/revisão da placa ESP32; confirmar shunt e foto da placa de medição; informar corrente e dimensões dos conectores/cabos; cotar PCB e montagem com lista de materiais completa. Não foi realizado contato comercial nem compra.

## Alternativas pesquisadas para a alimentação

Na rota com TPS25810 agora excluída, a fonte fixa de 5 V permaneceu sem aprovação: o cálculo da [revisão elétrica](revisao-eletrica.md) mostra pouca margem para cabos e contatos no modo de 3 A. A alternativa abaixo permite estudar uma alimentação regulada localmente, mantendo o controle USB-C no TPS25810.

| Item adicional ou alternativa | Preço anunciado e disponibilidade | Decisão |
| --- | --- | --- |
| [XL4015 EasyTronics 1106](https://www.easytronics.com.br/xl4015-modulo-step-down-5a) | R$ 12,70; disponível para compra, sem quantidade publicada; dissipador incluído | Alternativa para receber 12 V e produzir aproximadamente 5,1 V, ajustados e ensaiados em bancada. Placa declarada 54 × 23 × 15 mm; furação e altura com dissipador não suficientemente documentadas. |
| [XL4015 Makkers CB5-G15](https://www.makkers.com.br/modulo-regulador-de-tensao-step-down-xl4015-5a) | R$ 24,00; 18 unidades anunciadas | Mesmo envelope comercial de 54 × 23 × 15 mm; preço superior. Não transferir furação entre fornecedores. |
| [XL4015 BR Eletrônica BR-507](https://www.breletronica.com.br/regulador-tensao-dc-dc-xl4015-5a-step-down) | R$ 16,99; 43 unidades anunciadas | Anúncio informa 300 kHz e entrada de 5 V, divergindo do datasheet XL4015 de 180 kHz e mínimo de 8 V. Não selecionado sem identificação do módulo. |
| [Conector USB-C Smart Kits SK5865](https://www.smartkits.com.br/conector-usb-tipo-c-femea-de-16-pinos) | R$ 2,90; disponibilidade imediata | Candidato de 16 pinos, 3 A declarados, dimensões aproximadas 8,9 × 7,3 × 3,2 mm. Falta desenho de terminais/abas para fechar footprint; não usar só o retângulo externo. |
| [Conector USB-C Proesi 16 pinos](https://www.proesi.com.br/conector-usb-c-femea-90-smd-16-pinos-11x7mm) | Preço e estoque não confirmados na consulta | Alternativa declarada de 11 × 7 × 3 mm e 3 A; também sem desenho suficiente para liberar PCB. |

Fonte 12 V/2 A de R$ 21,90 mais XL4015 de R$ 12,70 somam R$ 34,60, R$ 15,30 abaixo da fonte 5 V/5 A de referência, antes de fretes e auxiliares. Substituindo apenas essa alimentação, o subtotal parcial seria R$ 111,00, ainda sem ESP32, PCB, montagem, conectores, demais auxiliares e fretes. É uma comparação condicional, não um novo total fechado.

O [datasheet XLSEMI](https://www.xlsemi.com/datasheet/XL4015-EN.pdf) confirma o regulador ajustável, mas não qualifica termicamente a placa comercial. Essa rota acrescenta calor, volume, calibração e risco de ajuste incorreto; validar ripple, partida e carga antes do telefone. O trimpot define uma tensão fixa de trabalho e não será usado para controlar a velocidade. O anúncio de capacidade USB-C continua sendo responsabilidade do TPS25810. Se a alimentação fixa passar nos ensaios, sua simplicidade permanece uma vantagem.

A fonte 12 V/2 A de 24 W também não está aprovada para todo o envelope de falha/transientes. Somar consumo do ESP32 e VCONN, perdas do conversor e corrente máxima real de proteção pode exigir uma fonte de 12 V/3 A, com nova cotação. A aleta metálica do XL4015 é o nó de comutação SW; conferir o isolamento do dissipador. Esses pontos impedem contar a economia de R$ 15,30 como garantida.
