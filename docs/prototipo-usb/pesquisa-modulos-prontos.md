# Pesquisa de módulos prontos — saída USB-C

Consulta: 5 de outubro de 2026. Restrição vigente: somente módulos já montados, com envio nacional no Brasil e projeto completo até R$ 250, sem contar impressão e painel existente.

**Resultado: nenhuma placa foi qualificada, nesta pesquisa, para fornecer energia ao celular e permitir ao ESP32 alterar a capacidade anunciada de recarga, com interface documentada, compra nacional confirmada e orçamento completo atendido.** Isso registra o limite das ofertas verificadas; não prova que tal placa inexista no mercado. A BOM de potência permanece aberta.

A rota TPS25810 + INA260 avulsos foi excluída a pedido do usuário. Sua revisão técnica foi preservada como histórico em `revisao-eletrica.md` e `nets-plano.json`; não é a seleção atual, não deve originar compra de CIs e não autoriza a fabricação de uma PCB.

## Critério de seleção

A placa precisa operar como **source**: anunciar ao telefone o que consegue fornecer e entregar energia. Uma placa **sink/trigger** faz o contrário: pede energia a um carregador existente para alimentar outro circuito. Ter USB-C, PD, I²C ou seletores de 5/9/12 V no anúncio não resolve essa diferença.

Além da função source, é necessário verificar o módulo físico: interface externa acessível ao ESP32, níveis lógicos, documentação dos comandos, partida segura, proteção e comportamento ao reduzir o limite anunciado. As capacidades do CI não garantem que uma placa genérica exponha esses recursos. Não foi adotado controle de corrente por queda forçada de tensão, PWM da alimentação do celular ou alteração de componentes SMD.

## Ofertas concretas e descarte

| Candidata | Evidência técnica/comercial | Resultado para este projeto |
|---|---|---|
| Placas genéricas SW3518/SW3518S | O fabricante descreve um controlador source com I²C. Na consulta direta ao Mercado Livre, os 25 resultados pertinentes à eletrônica estavam marcados como internacionais/China; ativando o filtro de envio local, os resultados restantes eram autopeças sem relação. A oferta Shopee HUINET também declara produto internacional. | Não qualificada: envio nacional não encontrado. Ainda faltariam pinagem I²C acessível, versão exata da placa e validação dos comandos. |
| MIKROE-5682 USB-C Power Click | Placa montada com TPS25750S, interface I²C, lógica de 3,3 V, fonte de 5 V até 3 A; fabricante fornece esquema e CAD. Dimensões de placa: 57,15 × 25,4 mm. Distribuidor global encontrado, sem estoque nacional brasileiro confirmado. | Tecnicamente relevante, mas não atende a compra nacional demonstrada. Não foi somado preço externo como se fosse preço final brasileiro nem aprovada integração de firmware. |
| TUSB320EVM | A Texas Instruments documenta modos DFP/source, UFP/sink e DRP, configuração por DIP ou I²C e caminho de potência na placa de avaliação. | Alternativa técnica pronta, mas não foi encontrada oferta nacional elegível no orçamento. O TUSB320 avulso vendido por distribuidores não atende “módulo pronto”. |
| Toni Eletrônica, módulo USB-C PD 65 W, SKU 1317 | Loja anuncia R$ 25,99 ou R$ 24,69 via Pix, 8–30 V de entrada e negociação automática; página indica **fora de estoque**. Não identifica interface externa de comando pelo ESP32. | Não qualificada: indisponível e controle programável não documentado. Não inferir SW3518 nem I²C pelo formato da placa. |
| IP2368 bidirecional para bateria 4S | Oferta Shopee de R$ 49,42 explicitamente internacional. A descrição é de módulo de bateria, não de fonte simples alimentada pela rede com controle ESP32 comprovado. | Não atende envio nacional e acrescenta uma arquitetura de bateria não pedida; interface de controle não qualificada. |
| HUSB238/Adafruit 5807 e STUSB4500 | Os próprios fabricantes identificam essas soluções como **sink**. A HUSB238 permite I²C, mas negocia a energia recebida de uma fonte. | Função errada para a saída ao celular. Não substituem o controlador source, mesmo que se encontre revenda nacional. |

Os preços acima são observações de anúncio, sem frete calculado, não uma cotação aceita. Não houve compra, contato com fornecedor nem cadastro em aviso de estoque.

## Evidência verificável

- [SW3518S — fabricante iSmartWare](https://ismartware.com/details-4-12.html).
- [Mercado Livre — SW3518 com filtro de envio local aplicado](https://lista.mercadolivre.com.br/sw3518_NoIndex_True_SHIPPING*ORIGIN_10215068). A inspeção foi feita na interface com “Envio local — Produtos com frete nacional” marcado. A lista sem filtro mostrava 72 resultados e a filtrada 47; esses totais incluem itens irrelevantes e não representam 47 placas. Os resultados podem mudar.
- [Shopee — SW3518 HUINET, produto internacional](https://shopee.com.br/Adaptador-De-Carga-R%C3%A1pida-HUINET-USB-Tipo-C-SW3518-Mudule-QC4.0-QC3.0-1-2-4-Vias-i.427561812.53204123331).
- [MIKROE-5682 — fabricante, pinagem, esquema e CAD](https://www.mikroe.com/usb-c-power-click) e [oferta de distribuidor global](https://www.digikey.com/en/products/detail/mikroelektronika/MIKROE-5682/19200429). Uma página em português ou domínio regional não comprova expedição do Brasil.
- [TUSB320EVM — Texas Instruments](https://www.ti.com/tool/TUSB320EVM).
- [Toni Eletrônica — módulo PD 65 W, indisponível na consulta](https://tonieletronica.com/modulo-fonte-step-down-carregador-usb-c-pd-65w-qc4-0-qc3-0/).
- [Shopee — IP2368, produto internacional](https://shopee.com.br/1-PCS-IP2368-100W-M%C3%B3dulo-De-Carregamento-R%C3%A1pido-Bidirecional-Interface-Tipo-C-4S-Bateria-De-L%C3%ADtio-Placa-i.1413714152.56707444004).
- [Adafruit HUSB238: placa sink, não source](https://www.adafruit.com/product/5807) e [STUSB4500: fabricante confirma função sink](https://www.st.com/en/interfaces-and-transceivers/stusb4500.html).

Buscas complementares por módulos SW3526, CH213, FP6606, IP2723/IP2726 e FUSB302 não forneceram uma oferta nacional documentada que qualificasse a saída. Ausência de resultado de busca não foi tratada como prova de inexistência nem como validação elétrica.

## Direção vigente depois da pesquisa

Em 7/10/2026, o usuário acrescentou **compatibilidade com qualquer celular USB-C**. Controle variável permanece obrigatório; liga/desliga com telemetria não atende. As hipóteses QC/AFC de `estudo-perfis-comutados.md` passaram a histórico por dependerem de protocolos específicos. A direção é anúncio Type-C selecionável em 5 V, detalhada em [compatibilidade USB-C](compatibilidade-usb-c.md). O telefone continua decidindo o consumo efetivo.

Uma revisão dirigida em 7/10 das famílias SW3518/SW3526, TUSB320 e TPS25750 não qualificou oferta nacional adicional. Um telefone específico deixa de condicionar a arquitetura; os ensaios incluirão aparelhos distintos. Ainda falta validar interface, fonte, transições e custo final. A pesquisa não fornece lista fechada que cumpra o conjunto de requisitos. Datas e preços das linhas anteriores continuam os da consulta de 5/10.

Registro da revisão de 7/10: [Toni CTP1_C 30 W](https://tonieletronica.com/modulo-carga-rapida-tipo-c-30w-step-down-pd3-pps-qc4-10-30v/), R$ 24,99, continua sem interface externa de controle documentada; [SW3518 Shopee](https://shopee.com.br/M%C3%B3dulo-Carregamento-R%C3%A1pido-SW3518-100W-Para-Reuni%C3%B5es-Neg%C3%B3cios-E-Exposi%C3%A7%C3%A3o-i.191698542.41682792558), R$ 43,95, é oferta internacional. A [MIKROE-5682](https://www.mikroe.com/usb-c-power-click), US$ 18 na página do fabricante, permanece referência técnica sem estoque nacional demonstrado; esse valor não é custo entregue no Brasil. Não houve compra.

O progresso mecânico independente pode continuar nos trilhos, trava substituível e cassete modular. O suporte definitivo da placa de potência, a posição do conector e o dimensionamento térmico dependem da placa que for efetivamente escolhida. Dimensões do CI, fotos comerciais ou uma caixa conceitual não justificam furações definitivas.
