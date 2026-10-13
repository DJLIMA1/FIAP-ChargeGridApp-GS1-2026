# Compatibilidade USB-C do ChargeGrid Mini

Revisão elétrica: 7 de outubro de 2026; estado mecânico atualizado em 9/10. Requisitos: qualquer celular USB-C, controle variável, ESP32 WROOM genérico, módulos prontos com envio nacional e até R$ 250 por carregador. Este documento define a direção elétrica; não confirma uma montagem disponível ou ensaiada.

## Alcance da compatibilidade

Projetar recarga básica para celulares conformes ao padrão USB-C, sem depender de marca, aplicativo no telefone ou protocolo proprietário. Um modelo específico deixa de ser condição para escolher a arquitetura; modelos concretos serão usados nos ensaios.

**Capacidade oferecida e consumo são diferentes.** O ESP32 deverá selecionar o teto anunciado. O telefone decide quanto utiliza: pode consumir 1 A tanto com teto de 1,5 A quanto com teto de 3 A. A mudança de capacidade foi real, mas a potência medida não mudou. Não prometer uma velocidade diferente ou uma corrente exata para todo celular. [Explicação da Texas Instruments](https://e2e.ti.com/support/interface-group/interface/f/interface-forum/940254/tusb320-cant-get-3a-at-load-site).

O controle variável permanece obrigatório. O usuário aceitou que a velocidade real possa não variar entre os perfis, pois será uma simulação. Isso permite prosseguir com o modelo mecânico sem prometer corrente exata no telefone. Liga/desliga isoladamente continua rejeitado; o módulo elétrico segue pendente.

## Direção elétrica

Priorizar porta USB-C fonte em 5 V, com anúncio Type-C selecionável pelo ESP32 e cabo C–C completo, substituível, de pelo menos 3 A.

| Perfil de estudo | Tensão nominal | Capacidade anunciada | Potência nominal disponível |
|---|---:|---:|---:|
| Reduzido | 5 V | Até 1,5 A | Até 7,5 W |
| Ampliado | 5 V | Até 3 A | Até 15 W |

São perfis de estudo, não capacidades implementadas. O [TUSB320 documenta anúncio de 1,5/3 A por I²C](https://www.ti.com/lit/ds/symlink/tusb320.pdf); o CI sozinho não entrega potência nem constitui o módulo pronto que falta selecionar.

A USB-IF exige que carregadores Type-C anunciem pelo menos 1,5 A e unam D+/D− com resistência inferior a 200 Ω. Não adotar 0,5 A como modo universal de carregador dedicado. USB PD não é necessário para os dois perfis de 5 V acima. [USB-IF, esclarecimento BC1.2 de outubro de 2022](https://compliance.usb.org/index.asp?Format=Standard&UpdateFile=USBC).

Se um módulo também oferecer PD, será necessário controlar seus contratos: com contrato PD ativo, alterar somente o anúncio Type-C não modifica o limite contratado. Negociação automática não equivale a controle pelo ESP32. [USB-IF, testes funcionais 2024, §4.6.2.1 e TD4.10.2](https://www.usb.org/sites/default/files/USB%20Type%20C%20Functional%20Test%20Specification%202024%2003%2003.pdf).

## Seleção e orçamento

As hipóteses QC/AFC de `estudo-perfis-comutados.md` deixam a rota ativa: dependiam de protocolos específicos para obter modos diferentes. Seus preços permanecem como histórico. A placa própria TPS25810/INA260 continua excluída pela restrição de módulos prontos.

**Ainda não há lista de compra qualificada para todos os requisitos.** A revisão dirigida de 7/10 das famílias SW3518/SW3526, TUSB320 e TPS25750 não confirmou uma placa fonte controlável, documentada e com envio nacional que permita fechar o conjunto em R$ 250. Isso não prova inexistência no mercado. O subtotal atual permanece indefinido.

A placa pronta precisa comprovar função fonte, interface externa de controle, anúncio e entrega coerentes, transições e comportamento no reset. Fonte, medição e cabo serão dimensionados com ela. O desenho da placa comercial e a medição física deverão definir o berço; cotas do CI ou fotos de uma placa parecida não bastam.

## API, mecânica e validação

O painel permanece separado. A API deverá distinguir perfil solicitado, capacidade aplicada e V/A/W/Wh medidos. Selecionar teto de 15 W não significa que o celular esteja consumindo 15 W. Esta revisão não torna operacionais os perfis do OpenAPI histórico.

A escala externa foi alterada pelo usuário para 50%. A [revisão de impressão v1](cad-impressao-50-v1/README.md) contém a carcaça, bandeja de 60 × 112 mm, berços genéricos e inserto bipartido para cabo inteiro. O canal frontal permite instalar o cabo sem cortar CC ou emendar condutores. Reservar plug interno, curvatura e acesso para substituição. O módulo real continua necessário para confirmar berço e dissipação; a validação geométrica das reservas não comprova o encaixe de placas comerciais ainda não escolhidas.

Ensaiar separadamente a capacidade anunciada e o comportamento de celulares distintos, incluindo aparelho sem PD, aparelho com PD e fabricantes diferentes. Testar ambas as orientações dos plugs. Registrar modelo, cabo, condição aproximada da bateria, perfil e potência medida. Uma amostra não comprova compatibilidade absoluta com todo produto existente. O acesso à instrumentação para validar o conjunto ainda precisa ser resolvido.

Na apresentação, demonstrar a alteração da capacidade e a energia realmente entregue. A telemetria deve continuar correta quando o celular não aproveitar o teto adicional.
