# ChargeGrid — teste da trava da tampa em PLA, revisão v3

## Imprimir agora

No cartão SD: **CGTRAVA3 → 00TRAVA.gcode**.

**00TRAVA.gcode**: duas unidades iguais do pino pequeno revisado. Estimativa: **5min39s e 0,50 g**. Uma unidade é reserva. Não inclui o pino grande de quarto de volta, já validado no encaixe pelo usuário.

**01ENCAIX.gcode** é opcional: reimprime os dois blocos de ensaio 17 e 18, sem alteração dimensional. Estimativa: 15min01s e 2,15 g. Não é necessário se os blocos anteriores estiverem íntegros.

Ender-3 original, Bowden, bico 0,4 mm, PLA 1,75 mm. Mantidos os parâmetros de temperatura e movimento do perfil v2 que funcionou: 210/205 °C, mesa 60 °C, camada 0,24 mm, retração 5 mm a 35 mm/s e retorno a 25 mm/s. Nesta revisão, apenas o preenchimento dos pinos foi elevado a 100%. Imprimir os G-codes diretamente; os STL já estão na escala final.

## Qual é a trava e onde ela será usada

É o **pino 08**, para prender a **tampa branca ao quadro frontal**, inserido pelo lado interno do quadro. Não é o pino 07 de quarto de volta nem a trava dos berços eletrônicos.

Na carcaça, há cinco posições: duas no alto, duas no meio e uma embaixo. O teste de agora usa o comprimento padrão das quatro posições superiores. O pino inferior tem comprimento próprio: o STL está incluído como protótipo, mas não foi colocado neste teste. A validação deste ensaio não substitui a conferência das cinco posições na montagem real.

## Como testar usando o que já foi impresso

Veja **como-testar.png**, renderizado com as geometrias reais.

1. Separe os dois bloquinhos quadrados de aproximadamente 16 × 16 mm. O **17 tem um furo cego** (a ponta não atravessa); o **18 tem um furo passante**. Não usar o bloco comprido do pino grande.
2. Deixe o 17 com a abertura para cima. Sobreponha o 18, alinhando os furos. Não cole.
3. Espere as novas peças esfriarem e remova o brim com cuidado, segurando a cabeça, sem puxar pelas duas pontas. A fenda deve estar livre. Não aumentar os furos nem lixar a trava antes do primeiro teste, para preservar a comparação dimensional.
4. Introduza o pino pelo furo do 18, com a ponta dividida voltada para o bloco 17. Pressione reto com os dedos. A cabeça fica sobre o 18. Não é uma baioneta: **não precisa girar 90°**.
5. Confira se as placas permanecem juntas ao tentar separá-las suavemente. Depois retire o pino pela cabeça, em linha reta, sem dobrar lateralmente as pontas. Não usar martelo ou alicate para vencer um encaixe duro.
6. Como triagem, repetir até **10 ciclos** de inserir, reter e retirar. Parar antes se houver trinca, embranquecimento, deformação permanente ou necessidade de força excessiva. Se ficar preso, interromper e relatar; não destruir o cupom para completar os ciclos.
7. Informar: entrou facilmente ou apertado; reteve as placas ou ficou frouxo; saiu inteiro; quantos ciclos completou. Se quebrar, indicar ponta, haste ou junto à cabeça.

## Alterações no pino

- Cabeça de 1,60 para **2,40 mm**, mantendo o diâmetro nominal máximo de 6,80 mm para caber no alojamento existente.
- Haste nominal de 4,16 para **4,30 mm**; fenda de 1,30 para **1,20 mm**, com término arredondado.
- Ressalto de retenção de 4,96 para **4,80 mm**, com rampa adicional de retirada. A interferência radial nominal para atravessar o furo de 4,60 mm caiu de 0,18 para **0,10 mm**. Isso reduz a flexão exigida, mas pode diminuir a retenção; o ensaio físico decide se o compromisso funciona.
- Face plana ao longo do pino para imprimir **deitado**, com os dois braços lado a lado sobre a mesa. A cabeça mais espessa projeta 0,8 mm a mais para o lado interno; a profundidade da ponta no furo cego foi preservada.
- Preenchimento sólido nos pinos. A geometria deitada não precisou de suportes segundo a análise do fatiador; isso evita suporte preso dentro da fenda. O pedido de suporte para o pino grande permanece registrado para a próxima produção.

Essas alterações visam resistência e facilidade de impressão; **não há ensaio físico nem promessa de resistência ou vida útil**. O usuário confirmou que a quebra anterior ocorreu na união dos dois braços separados com a cabeça. Mantida a revisão v3 para ensaio: a orientação deitada, a cabeça mais espessa, a haste maior, a raiz arredondada e a menor interferência de inserção são as alterações relevantes para essa região. O ensaio continua necessário para confirmar se o problema foi resolvido.

## Verificações e próximo passo

STL fechado, volume positivo e uma peça conectada; encaixe rígido instalado sem interpenetração nos dois cupons; interferência geométrica positiva ao puxar para conferir a existência do batente. Isso não é simulação elástica ou prova de força de retenção. O fatiador não emitiu avisos de estabilidade nos dois novos trabalhos.

Os dois G-codes tiveram limites, temperaturas, vazão e reposições de retração conferidos. Ambos os 3MF incluem o perfil; o projeto da trava também foi reaberto e refatiado sem INI externo, com configurações correspondentes. Foram inspecionadas as prévias do G-code e a ilustração de montagem.

**A carcaça completa continua pendente deste teste e da preparação dos suportes.** Após validar a trava, consolidar os pinos revisados e refatiar as peças da carcaça com suporte nas regiões necessárias. O pino 07 manterá a geometria aprovada, com suporte para evitar a deformação relatada. Não usar o pacote v2 sem suportes como versão final da carcaça.

Referência de projeto: [Prusa — modelagem para impressão 3D](https://help.prusa3d.com/article/modeling-with-3d-printing-in-mind_164135), sobre influência da orientação e necessidade de testar tolerâncias reais. As dimensões e os resultados acima são próprios deste protótipo.
