# ChargeGrid — ensaio de passagem e retenção da trava, v4

## O que imprimir

**00FLEX4.gcode** imprime duas travas diferentes em **5min18s**, com estimativa de **0,41 g** de PLA. A tem **um risco** na face externa da cabeça; B tem **dois riscos**. São identificadores, não ranhuras para girar com ferramenta.

Reutilizar os blocos 17 (furo cego) e 18 (furo passante) que já foram impressos. Não imprimir a carcaça inteira nem repetir o pino grande neste ensaio. A v3 não foi aprovada: o usuário relatou pouca flexibilidade, haste apertada na placa e retenção insuficiente no bloco.

## Como testar e escolher

1. Deixe esfriar e retire o brim segurando a cabeça. Confira se a fenda entre os braços está livre de brim ou fios. Não aumentar os furos nem lixar a trava antes do teste.
2. Comece pela **A, um risco**, apenas na placa 18. A ponta pode oferecer resistência leve ao atravessar; depois que ela sair do outro lado, **a placa deve deslizar na haste até a cabeça sem prender**. Para retirar nessa etapa, os braços ficam acessíveis e podem ser aproximados levemente com os dedos. Se a haste ainda agarrar, parar e relatar esse ponto; não passar para a B tentando resolver aperto.
3. Monte 17 embaixo, com o furo cego voltado para cima; 18 por cima, furos alinhados. Insira A pelo lado do 18, reto, com os dedos. A cabeça permanece do lado de fora. Não girar como baioneta, colar ou martelar.
4. Confira se as duas placas permanecem juntas sob tração leve e se o pino pode ser retirado pela cabeça sem deformar. A retenção deve ocorrer na ponta dentro do 17, não pelo atrito da haste no 18.
5. Se A passar bem, mas ficar frouxa no conjunto, teste **B, dois riscos**. Ela tem a mesma haste e braços, mas abas de retenção um pouco maiores; pode exigir mais flexão e força. Se A já prender e sair bem, prefira A.
6. Na opção escolhida, faça até dez ciclos suaves de inserir, reter e retirar como triagem. Pare se houver trinca, embranquecimento ou necessidade de forçar. Se ambos falharem, informar o estágio; o próximo ajuste deve se apoiar em medidas dos furos/peças reais, evitando novas alterações amplas sem diagnóstico.

Relatar: **A ou B; haste desliza na placa 18?; prende os dois blocos?; sai inteira?; número de ciclos**. Veja também como-testar.png.

## Alterações em relação à v3

| Região | v3 | v4 |
|---|---:|---:|
| Haste principal | 4,30 mm | 3,80 mm |
| Fenda | 1,20 mm | 1,40 mm |
| Centro do término arredondado, medido da face externa da cabeça | 3,70 mm | 2,80 mm |
| Raio do término da fenda | 0,60 mm | 0,70 mm |
| Espessura da cabeça | 2,40 mm | 2,40 mm |
| Comprimento total | 9,80 mm | 9,80 mm |
| Retenção | Ressalto contornando a haste | Duas abas laterais acompanhando o fechamento dos braços |

A transição curta junto à cabeça chega a 3,90 mm, ainda abaixo dos 4,30 mm da haste anterior. A região flexível é mais longa e mais fina. A cabeça continua espessa e o término da fenda arredondado; o ganho de flexibilidade pode reduzir resistência, portanto o ensaio físico continua obrigatório antes de escolher a geometria final.

A largura máxima da ponta é 4,80 mm em A e 5,00 mm em B. As abas são limitadas a 2,80 mm na direção transversal ao fechamento. O perfil anterior tinha ressalto também nas laterais que não se aproximam quando os braços fecham em X; não era correto usar só a diferença entre diâmetros como medida da flexão necessária. A nova análise verifica a geometria completa da ponta.

O ressalto foi posicionado para alcançar o batente do segundo bloco com menos deslocamento axial nominal. A haste termina antes da ponta afunilada, para não anular esse afunilamento. A profundidade da ponta no furo cego e as geometrias dos dois blocos foram preservadas.

## Impressão e verificações

Mantido o perfil térmico e de movimento que funcionou: Ender-3 original, Bowden, bico 0,4 mm, PLA 1,75 mm; 210 °C inicial e 205 °C depois, mesa 60 °C; camadas 0,24 mm; retração 5 mm a 35 mm/s, retorno 25 mm/s. Preenchimento sólido nos pinos, como na v3. Impressão deitada na face plana, sem suporte dentro da fenda.

Foram conferidos: malhas fechadas e conectadas; ausência de interpenetração rígida na posição instalada; existência de interferência de retenção ao puxar; espaço geométrico para fechamento lateral da ponta; configurações do G-code, limites de movimento, aquecimento e reposições de retração. O 3MF inclui o perfil e foi reaberto/refatiado para conferência. O fatiador não emitiu alerta de estabilidade.

A checagem de fechamento é **apenas um deslocamento geométrico das pontas** para caber no furo nominal de 4,60 mm: aproximadamente 0,123 mm por braço em A e 0,246 mm em B. Não é simulação elástica, não calcula força ou fadiga e não representa o diâmetro real do furo impresso. Não houve ensaio físico desta revisão. Folga de montagem digital não comprova ajuste na peça real.

A carcaça completa depende da aprovação deste encaixe e da revisão dos suportes das demais peças. O pino grande 07 mantém a geometria aprovada e receberá suporte na produção.

Referência: [Makers Making Change — Snap Fit Connections](https://makersmakingchange.github.io/OpenAT_Design_Guide/Design_Elements_For_3D_Printed_Parts/Snap_Fits.html), sobre folga, geometria dos braços, orientação e compromisso entre flexibilidade e resistência. As dimensões e verificações deste pacote são próprias do ChargeGrid.
