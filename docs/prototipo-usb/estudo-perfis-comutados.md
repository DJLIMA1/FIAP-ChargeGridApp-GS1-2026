# Estudo histórico — perfis de recarga por comutação

**Status em 7/10/2026: fora da rota ativa.** O usuário exige compatibilidade com qualquer celular USB-C. As hipóteses QC/AFC abaixo dependem de protocolos específicos e não satisfazem esse requisito para variação universal. As perguntas sobre um telefone específico pertencem ao estudo de 5/10 preservado abaixo. Ver [direção vigente](compatibilidade-usb-c.md).

Data: 5 de outubro de 2026. **Hipóteses de engenharia, sem aprovação para montar ou conectar a um celular. Não é BOM fechada, esquema fabricável ou declaração de conformidade USB.** O usuário exige controle variável e somente módulos prontos nacionais; controle de sessões isoladamente não atende.

## O que esta rota poderia realizar

O ESP32 selecionaria modos discretos de recarga reais: por exemplo, uma fonte convencional de 5 V e uma fonte QC/AFC capaz de negociar 9 V com um telefone compatível. O telefone continuaria negociando com a fonte pronta. O ESP32 não aplicaria 9 V por conta própria nem usaria subtensão/PWM para forçar corrente.

Essa seleção pode mudar a capacidade de recarga disponível. Não obriga o aparelho a consumir uma potência exata, não implementa limites arbitrários de 0,5/1/1,5 A e não garante diferença observável quando a bateria está quase cheia ou o aparelho limita sua carga. Se o requisito for ajuste contínuo de corrente, essas hipóteses não o satisfazem. A API teria seleção de perfis, potência efetivamente medida e confirmação da transição, sem publicar um limite de corrente que o hardware não consegue aplicar.

A Qualcomm descreve o telefone como quem solicita a tensão em QC3.0 e confirma que o protocolo pode usar conectores USB-A e USB-C. USB-C sozinho, entretanto, não informa se o telefone aceita QC/AFC; aparelhos dependentes exclusivamente de USB PD podem ficar em 5 V nessa rota. [Qualcomm QC3.0](https://www.qualcomm.com/news/onq/2015/09/introducing-quick-charge-30-next-generation-fast-charging-technology), [FAQ de compatibilidade](https://www.qualcomm.com/products/features/quick-charge/faq).

## Hipótese A — duas fontes completas

Selecionar conjuntamente VBUS, D+ e D− de duas fontes, deixando a fonte não escolhida isolada. O retorno GND pode ser comum se ambos os estágios compartilham a mesma alimentação DC e isso for confirmado nos seus esquemas. Não unir saídas de potência, usar cabo Y nem deixar os dois circuitos de identificação ligados às mesmas linhas.

A troca precisa abrir a saída, confirmar queda da tensão no lado do telefone, interromper a alimentação do estágio rápido para eliminar a negociação anterior, aguardar reset/descarga, selecionar a nova fonte e só então conectar sua saída após confirmar partida em 5 V. Um seletor break-before-make precisa ter essa característica documentada; dois relés acionados por software não garantem exclusão em falhas. Durante comutação não se admite uma fonte enviar corrente de volta à outra.

**Candidatos encontrados, ainda não selecionados:**

| Função | Produto/oferta observada | O que falta para qualificar |
|---|---|---|
| Fonte convencional | [Copel, REF12801, USB 5 V](https://www.copeleletronica.com.br/p-modulo-regulador-de-tensao-stedown-usb-3a-12801), R$17, pronta entrega, entrada 7,5–28 V, saída anunciada 3 A máxima/2 A contínua, 42 × 16 × 5 mm | Identificação de carga em D+/D− não documentada; “5 V/3 A” não comprova BC1.2, corrente anunciada nem capacidade térmica na carcaça. |
| Fonte rápida pronta | [5+ 044-0007, KaBuM/MIXTOU](https://www.kabum.com.br/produto/210985/fonte-usb-mobile-usb-automotivo-12v-2-1a-preto), R$19,90 Pix e compra habilitada | Ficha do fornecedor informa entrada 12–24 V e faixas QC3.0 de 5 V/3 A, 9 V/2 A e 12 V/1,5 A. Não informa CI, partida/reset, relação entre suas duas portas ou proteção reversa. Não presumir que a segunda porta seja uma fonte independente fixa. |

A [ficha 5+ do fornecedor](https://santanaimport.com.br/central-de-midias/044-0007/044-0007_ficha.pdf) informa também “30 W”, mas as faixas individuais listadas chegam a 18 W; não assumir 30 W numa porta. A dimensão “unidade 14 × 4,2 × 2,7 cm” pode incluir a embalagem, portanto não foi convertida em suporte 3D. Um carregador veicular fechado exigiria soquete 12 V com retenção mecânica, sem abrir ou dessoldar o produto. Frete e prazo não foram calculados.

A hipótese A é plausível como arquitetura, mas ainda faltam identificação do modo convencional, seletor pronto adequado e orçamento de perdas. Não está qualificada.

## Hipótese B — uma fonte rápida e seleção dos sinais

No modo rápido, D+ e D− do telefone se conectariam integralmente aos correspondentes da fonte QC. No modo convencional, ambas as linhas da fonte seriam isoladas e D+ e D− do telefone seriam unidos para apresentar identificação DCP. A TI documenta a assinatura BC1.2 como curto entre essas linhas com resistência máxima de 200 Ω. Isso é identificação de porta; não é um limitador físico ajustado a 1,5 A. [TPS251xx, seção 8.3.2](https://www.ti.com/lit/ds/symlink/tps2513a.pdf).

Arranjo conceitual de sinais: dois contatos SPDT com COM ligados respectivamente a D+ e D− do telefone; NO aos D+ e D− da fonte; os dois NC unidos entre si, sem conexão a VBUS ou GND. Sem comutação de dados enquanto energizado. Cabe confirmar o módulo de relés, retorno ao estado inicial e tempos; essa descrição não autoriza usar qualquer placa com relé.

**Impedimento encontrado:** a família IP6505, associada a alguns módulos MH-KC24, também suporta Pump Express 1.1/2.0. A MediaTek documenta que esses protocolos se comunicam por padrões de corrente em VBUS. Portanto, desligar D+/D− não garante 5 V para todos os telefones compatíveis com esse módulo. É necessário identificar o CI da placa comprável e eliminar essa via de negociação por documentação ou restringir e validar o aparelho de demonstração. O nome MH-KC24 e uma foto semelhante não comprovam o CI nem sua revisão. [Datasheet do fabricante Injoinic, distribuído pela LCSC](https://datasheet.lcsc.com/datasheet/pdf/5808847efeb66c1123b46871e419d398.pdf?productCode=C188335), [MediaTek: meios de comunicação dos protocolos](https://i.mediatek.com/hubfs/MtkSpecSheet_v2.pdf), [MediaTek: funcionamento do Pump Express Plus](https://www.mediatek.com/hubfs/MediaTek%20Assets/Pdfs/White_Papers/Pump-Express-Plus.pdf?hsLang=en).

Uma fonte que anuncie apenas QC também não prova ausência de outros protocolos internos. A confirmação precisa ser positiva. Neste momento a hipótese B é condicionada ao módulo e ao telefone, não uma solução universal ou uma seleção fechada.

## Reset, descarga e medição

O projeto de referência IP6505 inclui resistor de descarga de 3,3 kΩ e capacitores de saída de 220 µF, 10 µF e opcionalmente 100 µF. Para 330 µF ideais, `t = R × C × ln(Vinicial/Vfinal)` resulta em aproximadamente 2,95 s de 12 V até 0,8 V. É uma estimativa do circuito de referência, não um tempo garantido para o módulo genérico. Tolerâncias, telefone, cabo e carga alteram o resultado; 500 ms fixos não provam descarga. [Injoinic, aplicação típica, página 7](https://datasheet.lcsc.com/datasheet/pdf/5808847efeb66c1123b46871e419d398.pdf?productCode=C188335).

Cortar apenas os 12 V não produz isolamento instantâneo na porta. Em reset inesperado do ESP32, relés de dados podem voltar aos NC antes de o capacitor de saída descarregar. Uma implementação segura precisa resolver isso em hardware, por exemplo com corte normalmente aberto de VBUS e sequenciamento adequado, ou retenção dos sinais até a descarga. Um atraso no firmware não cobre um reset durante o modo rápido. Também não foi comprovado bloqueio de retorno de energia se um telefone operar como fonte/OTG.

Se houver corte separado de VBUS, confirmar tensão baixa tanto na porta do telefone quanto na saída do estágio antes de reconectar. Medir só o lado isolado do telefone pode ocultar 9/12 V ainda presentes no capacitor da fonte. A colocação de um sensor muda quais desses pontos são medidos; um único INA219 não mede simultaneamente os dois nós separados pelo corte.

## Relés, quedas de tensão e fonte de entrada

Relés para potência não são automaticamente adequados a D+/D−: a Omron explica que contatos de prata podem formar filmes e se tornar pouco confiáveis com correntes muito pequenas; sugere contatos apropriados para sinais e validação nas condições reais. Uma placa marcada “10 A” não comprova essa característica. [Omron — aplicações com correntes pequenas](https://www.ia.omron.com/support/faq/answer/36/faq02098/).

Antes de escolher relés, somar a resistência máxima dos contatos de potência, shunt do sensor, conectores e fios. Exemplo puramente orçamentário: dois contatos de 0,10 Ω cada e INA219 com shunt de 0,10 Ω totalizam 0,30 Ω; a 1,5 A perdem 0,45 V antes do cabo. Este exemplo não é medição de uma placa selecionada. Priorizar comutação dos 12 V quando possível reduz perdas diretamente no caminho de 5 V, mas não elimina o problema de descarga/reset na saída. Não elevar a tensão arbitrariamente para compensar um circuito inadequado.

A fonte DC precisa alimentar o maior modo que o módulo realmente permite ao telefone negociar, mais ESP32, relés e perdas. Um módulo que suporta 24 W de saída não pode ser liberado irrestritamente com fonte de 12 V/2 A de 24 W compartilhada: a conversão não tem 100% de eficiência. Módulos apenas step-down também não garantem 12 V regulados quando recebem exatamente 12 V. Perfil de anúncio, capacidade de entrada e limites térmicos devem concordar.

## Condições mínimas para avançar

1. Informar o modelo exato do telefone; confirmar QC/AFC ou outro protocolo compatível, além do conector USB-C.
2. Confirmar que seleção discreta de modos reais atende ao requisito de variação; ajustes contínuos/arbitrários não são implementados por esta rota.
3. Identificar a placa pronta e os protocolos efetivamente habilitados, seu comportamento de partida e descarga, sem presumir o CI.
4. Qualificar módulos de comutação e medição, incluindo lógica de 3,3 V, partida com ESP32 desligado, reset durante carga e estados de falha.
5. Medir 5 V inicial, renegociação, tensão residual, perdas, consumo e aquecimento primeiro com carga/instrumentação e depois com o telefone escolhido.
6. Só depois fechar frete, custo completo, geometria física dos módulos e suportes internos. Não houve compra nem contato com vendedores.

**Conclusão do estudo:** selecionar perfis prontos pode ser uma maneira legítima de obter variação discreta real sem programar o controlador USB. A pesquisa ainda não sustenta uma lista fechada e segura de módulos. A versão com uma fonte e bloqueio de D+/D− tem uma limitação concreta com Pump Express; a versão com duas fontes acrescenta comutação, perdas e reset que também precisam ser resolvidos.
