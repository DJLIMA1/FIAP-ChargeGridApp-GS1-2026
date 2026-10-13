# Roteiro de montagem e validação do ChargeGrid Mini

> Atualização de 9/10/2026: a revisão mecânica ativa é a [v1 em 50%](cad-impressao-50-v1/README.md), com carcaça e interiores para impressão. Usar os cupons da [prancha 00](cad-impressao-50-v1/pranchas/00-ensaios.3mf). O texto abaixo conserva o planejamento anterior de 70% e as hipóteses elétricas ainda não implementadas; suas dimensões e encaixes não definem a revisão atual.

O primeiro protótipo deve demonstrar três fatos: o painel comanda um equipamento independente; esse equipamento fornece energia real ao celular; e o resultado da sessão vem da medição. A aparência externa continua derivada do carregador original. A compra completa e a impressão da casca dependem dos ensaios abaixo. O grupo confirmou uso exclusivo de módulos prontos e manteve controle variável obrigatório; a placa própria TPS25810/INA260 foi excluída da montagem atual. Os testes específicos dessa rota permanecem como referência e serão ajustados ao módulo escolhido.

## Ordem prática

1. **Confirmar o conjunto de montagem.** Identificar a placa ESP32 WROOM do grupo, impressora e módulos prontos disponíveis. A arquitetura deve atender celulares USB-C sem depender de um modelo específico; separar aparelhos diversos para os ensaios. A família ESP32 já está decidida; falta a variante da placa. A alternativa TPS25810 avulsa foi excluída porque exigia PCB própria e soldagem do pad inferior.
2. **Imprimir apenas os cupons.** Usar o mesmo PETG, bico e perfil previstos para a carcaça. Comparar folgas e testar a trava removível. Registrar resultado; não escalar os STL para corrigir folga.
3. **Fechar os módulos e o chicote.** Conferir esquema, documentação, protocolo, alimentação e proteção de cada módulo pronto. Exigir revisão do conjunto antes de comprar. A revisão elétrica com CIs avulsos é referência arquivada, não a montagem selecionada.
4. **Montar e testar fora da carcaça.** Começar por alimentação e cargas de bancada. Conectar o telefone somente após comprovar tensão, controle CC, desligamento e medição.
5. **Desenvolver o firmware em projeto próprio.** Implementar o contrato da API com drivers reais. Um simulador de software, se usado antes, deve identificar sua telemetria como simulada.
6. **Medir as placas e imprimir um berço.** Incluir componentes, pinos, cabo conectado, acesso a BOOT/EN/USB e área da antena. Corrigir o berço antes de integrar o cassete.
7. **Concluir a casca.** Reconstruir paredes e eliminar apoios industriais incompatíveis, posicionar interfaces universais, verificar colisões e movimento de montagem, fatiar e imprimir.
8. **Ensaiar o conjunto fechado e a apresentação.** Repetir carga, temperatura, Wi-Fi e recuperação com os cabos e a fonte que irão ao pitch.

## Medidas para congelar cada berço

| Item | Registro necessário |
| --- | --- |
| ESP32 | Comprimento/largura/espessura da PCB; projeções acima e abaixo; largura das duas fileiras de pinos; USB e plug conectado; acesso a BOOT e EN; contorno e posição da antena. |
| PCB de potência | Contorno final e revisão; altura máxima por região; cobre/terminais expostos; furos se houver; conector USB-C e direção de inserção; área quente e cabos. |
| Entrada de energia | Modelo exato, corrente nominal, polaridade, corpo, linguetas/pinos e plug inteiro. |
| Cabo de saída | Cabo completo com corrente declarada; diâmetro real; comprimentos dos plugs; curvatura sem esforço e área admitida para retenção. |
| Encaixes | Material/perfil da impressora, folga aprovada nos cupons, acesso para destravar, espaço para a mão e direção de retirada. |

Registrar fotos superior/inferior com escala e medidas por paquímetro. Cotas do anúncio servem para reserva de espaço; medidas de lote e desenho do fabricante definem o berço.

## Ensaios elétricos

Usar instrumentos do laboratório, se disponíveis: fonte de bancada com limitação, multímetro, carga eletrônica com conexão USB-C sink adequada e osciloscópio. Ferramentas não foram incluídas no teto de componentes. Um resistor conectado apenas a VBUS não garante que o controlador reconheça um sink no canal CC.

| Ensaio | Evidência de aprovação |
| --- | --- |
| Inspeção desenergizada | Polaridade, ausência de curto, soldagem e continuidade conferidas, especialmente QFN e caminhos de corrente. |
| Primeiro boot e reset | Saída permanece desligada; GPIOs flutuantes não habilitam EN; nenhum comando antigo retoma sessão. |
| Sensor | Tensão e corrente comparadas ao instrumento de referência em diferentes cargas; erro e configuração registrados. Integrar energia usando tempo monotônico. |
| Porta habilitada sem telefone | Estados CC e VBUS condizem com o datasheet; não usar a ausência de corrente como prova de cabo desconectado. |
| Perfis de 1,5 A e 3 A | Confirmar capacidade CC anunciada e comportamento sob cargas controladas. Medir tensão no receptáculo e na ponta do cabo separadamente. “3 A” no anúncio da fonte não comprova o resultado. |
| Mudança de perfil | Registrar corrente e VBUS nas duas transições. Verificar se o telefone adapta consumo ou reconecta; publicar essa capacidade real na API. |
| Parada e perda de autorização | EN desabilita, VBUS descarrega conforme circuito; comando só fica concluído após confirmação física. Falha mantém registro coerente. |
| Falha de medição/comunicação | Sensor desconectado, amostra velha, perda de Wi-Fi e lease expirado levam ao estado previsto sem reinício espontâneo da carga. |
| Fonte e cabo finais | Testar boot Wi-Fi e maior carga simultaneamente, aquecimento, ripple e transientes. Aprovar 3 A somente se todo o caminho atender, não somente o CI. |
| Uso do USB de programação | Comprovar que o computador não recebe energia da fonte externa; conferir circuito da placa ESP32 antes de conectar as duas alimentações. |

Testar proteção de sobrecorrente com fonte limitada e carga apropriada, sob supervisão do laboratório. Não usar o celular como carga de falha. Resultados de tensão, temperatura e tempos devem ser medidos; não há valores de ensaio preenchidos nesta fase.

## Ensaios mecânicos e recuperação

A finalidade dos cupons é escolher a folga e observar a trava antes da casca. Testar montagem e soltura manual, retenção, deformação residual e pelo menos 10 ciclos como triagem do protótipo. Esse número é um critério interno inicial, não uma qualificação de vida útil. Registrar também a retenção após repouso sob esforço; PETG pode deformar com carga prolongada.

Reprovar encaixe que exija forçar a PCB, encoste em soldas/componentes, impeça acesso ao USB ou deixe a trava inacessível. Trava ou trilho danificado deve sair sozinho. A carcaça recebe apoios rígidos; as peças que flexionam são substituíveis.

O cabo deve transmitir tração ao inserto e ao corpo, e não à solda do conector. O inserto bipartido permite manutenção do cabo inteiro. A retenção não pode esmagar a isolação; sua geometria depende do cabo recebido.

Para recuperação, manter uma cópia dos parâmetros, código gerador CAD, STEP e STL aprovados, perfil do fatiador e firmware estável. A versão de cada berço precisa indicar qual revisão de placa e folga atende. Configuração recuperada não autoriza religar energia; nova sessão exige novo comando válido.

## Critério para a demonstração

Atualização de 7/10: seguir a [revisão de compatibilidade USB-C](compatibilidade-usb-c.md). Incluir aparelhos com e sem PD, fabricantes distintos e ambas as orientações dos plugs. Uma amostra não comprova compatibilidade absoluta. Separar os testes de capacidade oferecida dos testes de consumo dos celulares.

O teste de bancada deverá comprovar a mudança de capacidade da fonte; o telefone mostra o comportamento de uma carga real. Ele pode consumir menos nos dois modos conforme bateria e temperatura. Ensaiar previamente com o aparelho escolhido e não prometer que selecionar o dobro da capacidade reduzirá o tempo de carga pela metade.

No painel, apresentar separadamente capacidade anunciada, potência medida e energia entregue na porta. Não apresentar porcentagem da bateria sem informação obtida do telefone. A simulação atual do projeto e a telemetria real precisam ter origem identificável durante a integração.

## Dados ainda necessários

O fechamento de compra precisa do CEP, preço/variante do ESP32 e seleção do módulo USB pronto. O fechamento físico precisa da impressora e dos componentes recebidos. Os ensaios precisam registrar modelos dos aparelhos disponíveis e instrumentos que o grupo poderá usar; um modelo específico não é mais pré-requisito da arquitetura. Enquanto esses dados não chegam, o contrato, a geometria de referência e os cupons permitem avançar sem comprometer a casca.
