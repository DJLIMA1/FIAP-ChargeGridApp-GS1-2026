# ChargeGrid — pesquisa de módulos prontos e acessórios para hipótese QC

**Status em 7/10/2026: hipótese QC fora da rota ativa**, após o requisito de compatibilidade com qualquer celular USB-C. Esta lista preserva a pesquisa de 5/10; não constitui recomendação atual de compra. Ver [direção vigente](compatibilidade-usb-c.md).

Consulta: 05/10/2026. Documento de pesquisa, sem compra e sem aprovação elétrica da arquitetura. Controle variável continua obrigatório. As alternativas liga/desliga e TPS25810/INA260 avulsos não são a seleção atual. Estoque é o estado publicado pela página consultada, sujeito a alteração; fretes e prazo dependem do CEP e não foram fechados.

## Hipótese em revisão

Um carregador QC comercial completo e fechado alimentado por 12 V. A investigação avalia duas configurações da identificação da saída: passagem intacta de D+/D− para permitir negociação pelo telefone, ou isolamento dos dados do carregador e curto D+/D− apenas no lado do telefone para representar DCP. Uma mudança teria de interromper alimentação, verificar descarga efetiva de VBUS e só então mudar contatos e reconectar. **Isso não está validado**: depende do telefone, do comportamento real do carregador no reset, dos contatos e da medição. Não garante dois valores de potência, controle contínuo, nem modo rápido em aparelhos que só usam PD. Não aplicar 9/12 V diretamente ao telefone com um trigger.

O [estudo de perfis comutados](estudo-perfis-comutados.md) reúne a avaliação elétrica e as pendências. Em particular, bloquear D+/D− não elimina protocolos que se comuniquem por VBUS, como Pump Express. Esta lista responde à disponibilidade nacional e geometria publicada, sem substituir essa revisão.

## Fontes USB source prontas pesquisadas

| Produto e fornecedor | Preço publicado | Disponibilidade | Evidência e pendência |
|---|---:|---|---|
| [Toni CTP1_C, SKU1354, USB-C 30 W](https://tonieletronica.com/modulo-carga-rapida-tipo-c-30w-step-down-pd3-pps-qc4-10-30v/) | R$24,99; Pix R$23,74 | Resultado indexado do próprio fornecedor informa em estoque | Entrada 10–30 V; PCB 37 × 21 mm, altura não publicada. PD/PPS/QC automáticos anunciados; somente IN+/IN− documentados. Nenhum controle ESP32 de limites documentado. A presença de PD não cria uma API de source. |
| [Toni SKU1283, USB-A QC24 W](https://tonieletronica.com/modulo-carregador-rapido-qc3-0-qc2-0-step-down-24w-dc-5v-32v/) | R$24,99 em catálogo indexado Mercado Livre; não reconfirmado na página exata | Não confirmada nesta leitura | Não foi possível identificar o CI. A página pública retornou desafio de acesso, sem fotografias utilizáveis. Não afirmar IP6505/IP6505T por semelhança com MH-KC24. |
| [Casa da Robótica NC05, USB duplo](https://www.casadarobotica.com/fontes-conversores/conversores-dc-dc/step-down/modulo-regulador-de-tensao-dc-dc-step-down-5v-p-carregamento-rapido-com-2-saidas-usb) | R$21,99; Pix R$20,89 | Compra habilitada, 652 unidades publicadas | PCB 40 × 50 mm; altura e furos não documentados. Embora título diga 5 V, descrição inclui QC3/2 e saída automática 3–12 V. Não tratar como estágio fixo 5 V. BC1.2/DCP também anunciados; CI e controle externo não documentados. |
| [HR2 módulo USB 6–32 V](https://www.hr2.net.br/produtos/modulo-carregador-usb-6v-32v/) | R$22,00 | Esgotado | QC24 W; excluído da lista comprável. |
| [Toni USB-C 65 W, SKU1317](https://tonieletronica.com/modulo-fonte-step-down-carregador-usb-c-pd-65w-qc4-0-qc3-0/) | R$25,99; Pix R$24,69 | Fora de estoque | 44 × 20 × 10 mm publicados; excluído da lista comprável. |

[Manual comercial Toni QC24 W](https://tonieletronica.com/manual-modulo-carregador-rapido-qc3-0-qc2-0-step-down/) descreve saída automática e repouso em 5 V, mas mistura versões/links. Não basta para confirmar o chip ou comportamento do SKU1283 específico. Nenhum módulo pronto nacional identificado de forma suficiente com IP6505/IP6503/FP6601 e entrada externa de controle documentada foi fechado nesta pesquisa.

O carregador veicular 5+ 0440007 encontrado pela outra revisão é candidato separado, com fonte do importador e preço KaBuM; não repliquei aqui a confirmação de estoque/modelo. Seu uso fechado evita presumir o CI de um módulo genérico, mas não resolve automaticamente as pendências de comutação e reset.

## Fonte externa 12 V / 3 A fechada

| Opção | Preço | Estoque / origem | Geometria e avaliação |
|---|---:|---|---|
| [SmartProjects AA-PP2](https://www.smartprojectsbrasil.com.br/fonte-chaveada-carregador-plug-p4-12v-3a) | R$26,00; Pix R$24,42 | Disponível; loja brasileira, CNPJ22.360.915/0001-40, atende Brasil | 100/220 VAC →12 V/3 A, plug P4. Dimensões do corpo, diâmetros exatos do plug e polaridade não informados no texto. Melhor preço entre opções desta tabela; fonte fica externa. Confirmar etiqueta/polaridade antes de conectar. |
| [Casa da Robótica UD01](https://www.casadarobotica.com/fontes-conversores/fontes/fontes-chaveadas/fonte-dc-chaveada-12v-3a-plug-p4-bivolt) | R$49,99; à vista R$47,49 | 8 unidades; Vitória da Conquista/BA | Corpo 82 × 45 × 31 mm, 145 g, fio1,7 m, P4 angular90°, parede bivolt. Melhor documentação dimensional, mas mais cara. |
| [CPA fonte12V3A plástica](https://www.cpacomputadores.com.br/fonte-12v-3a-plastica) | R$30,00 | Resultado indexado indica estoque imediato; não reconfirmado ao abrir | Reserva comercial, sem cotas verificadas. |

Potência nominal impressa não equivale a ensaio de regulação/ripple/temperatura. A opção econômica não possui ficha pública suficiente para garantir 3 A contínuos no gabinete escolhido. Nenhuma parte AC deve entrar na carcaça impressa.

## Soquete automotivo fêmea e chicote

| Opção | Preço / estoque | Montagem e pendências |
|---|---:|---|
| [Eletro Áquila 28.085, extensor macho–fêmea1,8 m](https://www.eletroaquila.com.br/cabo-extensor-de-tomada-de-acendedor-automotivo-12v-10a-1-8m-macho-para-femea-28-085) | R$39,90; 2 unidades | Conjunto com fios pronto, vendedor declara12V/10A e fusível no macho. Para obter só a fêmea com chicote, cortar/terminar condutores elimina o fusível do macho; seria necessária proteção separada. Sem medidas do corpo da tomada. |
| [Eletro Áquila 28.083, fêmea com bornes](https://www.eletroaquila.com.br/femea-acendedor-cigarro-12v-veicular-28-083) | R$29,90; 27 unidades | Vendedor informa bornes de conexão; cabos não confirmados. Permite montagem em fios sem mexer no carregador. Tipo exato dos bornes e cotas precisam de inspeção do item. |
| [Eletro Áquila 28.084, fêmea de extensão](https://www.eletroaquila.com.br/soquete-acendedor-de-cigarro-plug-femea-extensao-12v-24v-conector-veicular-universal-28-084) | R$19,90; 26 unidades | Terminais internos; não é chicote pré-montado. Não prometer montagem sem solda por falta de detalhe do terminal. |
| [Odison plug acendedor fêmea](https://www.odisoneletronica.com.br/produtos/plugacendedor/) | R$11,57; compra habilitada | 55 mm comprimento ×25 mm boca publicados. Fiação e corrente nominal não confirmadas, portanto apenas comparação de custo. |

Eletro Áquila tem endereço em São José dos Campos/SP. A opção realmente documentada com fio custa mais; o volume do par carregador+soquete+USB encaixado deve ser medido montado, e não obtido somando apenas comprimentos de catálogo.

## Acesso aos quatro condutores USB-A

| Opção | Preço / estoque | Resultado |
|---|---:|---|
| [Usinainfo08107, macho USB passivo4 fios30 cm](https://www.usinainfo.com.br/cabo-usb/cabo-usb-macho-com-4-fios-diy-5024.html) | Pix R$6,46; cartãoR$6,80. Categoria cruzada informa disponível; página contém simultaneamente alerta de últimas unidades e bloco genérico avise-me | 2 condutores energia+2 dados, ponta preparada para soldagem. Sem bitola/corrente nominal. Não aprovar passagem de3A sem qualificação. Confirmar estoque final. |
| [Mustafar USB-A fêmea →PH2.0 quatro vias15 cm](https://produto.mercadolivre.com.br/MLB-5336736398-usb-tipo-a-fmea-diy-p-ph-20-4-via-cabo-15cm-carga-e-dados-_JM) | R$14,90 no catálogo ML, preço exato sujeito a reconfirmação; anúncio >50 unidades, envio nacional | 24AWG segundo fornecedor. Passivo de dados e energia. Conector PH2.0 requer contra-peça ou corte/terminação de fios. Corrente do conjunto não publicada; bitola não certifica contato de3A. |
| [Usinainfo06584, extensãoUSB2.0 A macho–fêmea2 m](https://www.usinainfo.com.br/cabo-usb/cabo-extensor-usb-20-macho-x-femea-2m-3295.html) | R$10,45; PixR$9,88 | **Excluir do caminho de potência:** especificação do vendedor limita a900mA. Não selecionar só por ter quatro vias e preço baixo. |

Cabos USB–TTL PL2303/CH340 de quatro fios são conversores seriais, não extensões passivas D+/D−. Adaptadores de borne USB achados em ML/Magalu eram importados; não entram na seleção nacional. Este é um ponto ainda não fechado para3A/rápido.

## Relés prontos para lógica3,3 V

| Opção | Preço / estoque | Evidência e limites |
|---|---:|---|
| [RoboCore258, Metaltex5V](https://www.robocore.net/driver-motor/modulo-rele) | R$10,50 cada no [catálogo](https://www.robocore.net/busca/rele?newlang=brazilian); compra habilitada | Próprio fornecedor confirma sinal3,3V; bobina5V/75mA; sinal ativo alto. PCB43,8 ×25,4mm; quatro furosØ3,4, centros38,7 ×20,3mm. Melhor documentação. Três unidadesR$31,50. Adequação dos contatos a sinais de identificação USB não demonstrada. |
| [COPEL12587, dois canais5V](https://www.copeleletronica.com.br/p-modulo-rele-2-canais-5v-10a-12587) | R$14,00; pronta entrega, Sorocaba/SP | Texto confirma lógica3,3V/5V, opto e PCB50 ×45mm. Altura, furos, nível ativo e circuito não publicados. EconomizaR$7 em dois contatos, mas deixa mais parâmetros desconhecidos. Não substituir no esquemático sem revisar driver/boot. |
| [CurtoCircuito3,3V dois canais](https://curtocircuito.com.br/modulo-rele-3-3v-10a-2-canais.html) | R$19,30 | Esgotado; excluído. |

Desenho oficial RoboCore: https://d229kd5ey79jzj.cloudfront.net/258/Modulo.Rele_v2.2_mechanical.png . Datasheet do relé fornecido pela loja: https://d229kd5ey79jzj.cloudfront.net/258/Relay_AX.pdf . Altura total do módulo continua sem cota publicada; altura do corpo do relé não inclui PCB/pinos/solda.

Três bobinas consomem até225mA em5V; alimentação do ESP32/relés precisa ser independente do ramo de telefone que será desligado. Reservar buck5V para isso. O sinal de comando3,3V compatível não prova contato adequado para correntes pequenas de D+/D−. Não ligar alimentação da bobina ao GPIO.

## Resultado prático

Fonte12V, ESP32 e relés têm opções nacionais econômicas. Não há ainda lista definitiva apta à compra: faltam fechar o telefone/protocolo, comprovar comportamento do carregador e a comutação, medir VBUS com queda compatível, e qualificar os chicotes USB para corrente. Não transformar preços parciais em total do projeto: ainda entram sensor, buck, cabo A–C, fusível, conectores, terminais, fios, alívio de tração e fretes.

Para CAD, manter a carcaça e bandeja independentes da elétrica. Reservar cartucho substituível para source+soquete, outro para relés e outro para interfaces/cabos. Furos definitivos só onde há desenho do SKU; nos demais, cotas recebidas devem substituir envelopes provisórios. O berço de um carregador cilíndrico deve evitar esforço no contato central e permitir retirar o conjunto sem quebrar a carcaça.
