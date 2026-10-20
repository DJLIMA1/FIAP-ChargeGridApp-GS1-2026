# ChargeGrid — trava C, revisão v5

## Imprimir e testar

No SD: **CGTRAVA5 → 00FIXA5.gcode**. O arquivo imprime **duas cópias iguais**, com **três riscos na cabeça**, em aproximadamente **5min18s**, usando **0,40 g** de PLA.

Reutilize os blocos 17 e 18 já impressos. Espere esfriar e remova o brim sem puxar pelos braços. Primeiro confira a passagem na placa 18 sozinha; depois sobreponha 18 ao bloco 17, furo cego para cima, e insira reto pelo 18. A cabeça deve encostar na placa e os blocos devem permanecer encostados. A ponta prende dentro do bloco 17. Não girar, colar ou martelar.

Confira se há abertura entre os blocos, se eles se soltam sob tração leve e se o pino pode ser retirado inteiro pela cabeça. Na placa isolada, os braços ficam acessíveis e podem ser aproximados levemente para retirar. Pare se surgir trinca, embranquecimento ou necessidade de forçar. Faça até dez ciclos suaves como triagem, sem insistir em uma peça presa.

Relate: **passou na placa? cabeça encostou? blocos ficaram juntos? segurou melhor que B? saiu inteira?** Se continuar falhando, antes de outra revisão dimensional precisamos medir a espessura real dos dois blocos e a profundidade do furo cego; os arquivos não substituem essas medidas.

## O que o usuário validou até aqui

- O perfil v2 de impressão funcionou na Ender-3.
- O pino grande de quarto de volta encaixou; a próxima produção terá suporte para evitar a deformação da ponta.
- V3: haste apertada e pouca flexibilidade; não aprovada.
- V4: passagem e flexibilidade melhoraram, mas ambas as pontas retiveram pouco; B (dois riscos, 5,0 mm) foi melhor que A.
- V5: ainda não testada fisicamente; a base é a B, com haste e braços preservados.

## Medidas conferidas — modelo 3D e G-code realmente utilizado

A inspeção dos STL encontrou, dentro da discretização da malha, furo de passagem de **4,60 mm** e rebaixo interno de **5,30 mm**. O piso do furo cego fica em Z=1,20 mm e a face inferior do batente em Z=2,70 mm no CAD.

| Grandeza | CAD | Envelope ideal das camadas do 00TESTE v2 |
|---|---:|---:|
| Altura do bloco 17 | 4,25 mm | 4,32 mm |
| Altura da placa 18 | 4,35 mm | 4,32 mm |
| Altura das duas peças encostadas | 8,60 mm | 8,64 mm |
| Da face externa da placa até o batente interno | 5,90 mm | 6,00 mm |
| Da face externa da placa até o fundo | 7,40 mm | 7,44 mm |

O G-code tem camadas de 0,24 mm. A transição do rebaixo largo para o furo estreito acontece na camada que termina em Z=2,88 mm; seu início ideal é Z=2,64 mm. Foram examinados os trajetos dos perímetros internos dos cupons no próprio 00TESTE.gcode v2. Os arquivos medidas-dos-cupons.json e medidas-gcode-cupons.json registram os dados, e medir-gcode-cupons.py reproduz a análise dos trajetos.

**Esses são valores digitais.** Espessura real, diâmetro, arredondamentos e deformação das linhas depositadas não foram medidos fisicamente. O envelope ideal das camadas não é uma reconstrução metrológica da peça impressa.

## Correção de alcance e retenção

Na v4, o comprimento abaixo da cabeça era **7,40 mm**, praticamente igual ao espaço disponível até o fundo. A checagem anterior de folga de 0,10 mm usava a cabeça também 0,10 mm afastada da placa: essa folga não existia no CAD com a cabeça totalmente assentada. Esse ponto foi corrigido na análise e no pino.

Alongar a ponta poderia fazê-la bater no fundo antes de a cabeça encostar. Nesta revisão, a ponta termina **7,15 mm abaixo da cabeça**: sobra **0,25 mm no CAD**, ou **0,29 mm no envelope ideal das camadas**. O ressalto continua alcançando a região de retenção; foi reposicionado, não simplesmente encurtado junto com a ponta.

| Região | V4 B | V5 C |
|---|---:|---:|
| Haste principal | 3,80 mm | 3,80 mm |
| Fenda dos braços | 1,40 mm | 1,40 mm |
| Cabeça | 2,40 mm | 2,40 mm |
| Largura máxima das abas | 5,00 mm | **5,10 mm** |
| Comprimento total | 9,80 mm | **9,55 mm** |
| Início da região de largura máxima, a partir da face externa da cabeça | 8,55 mm | **8,45 mm** |
| Extensão axial da região de largura máxima | 0,20 mm | **0,30 mm** |
| Rampa de retirada junto ao ressalto | 0,15 mm | **0,10 mm** |

O aumento escolhido para o próximo ensaio é **0,10 mm na largura das abas**, preservando 0,20 mm de diferença diametral para o rebaixo nominal de 5,30 mm. Não se adotou 5,30 mm, pois isso eliminaria a folga digital. O ressalto mais largo e a rampa mais curta podem aumentar a retenção e também a força de retirada; não há cálculo de força ou ensaio de fadiga.

A posição nova permite montar os dois blocos encostados e a cabeça assentada, sem interpenetração rígida no CAD nem no envelope ideal das camadas. A pequena movimentação axial calculada até o contato do ressalto é aproximadamente **0,11 mm no CAD**, contra 0,20 mm na B; no envelope ideal do G-code é aproximadamente **0,012 mm**. Essa última cifra é apenas resultado matemático do modelo: **não representa precisão alcançável garantida pela impressora nem promessa de folga zero**. Também não há pré-carga elástica calculada para comprimir as peças.

## Impressão e verificação

Mantidos a temperatura e os movimentos do perfil que funcionou: PLA, bico 0,4 mm, 210/205 °C, mesa 60 °C, camadas 0,24 mm; retração 5 mm a 35 mm/s e retorno a 25 mm/s. Pinos sólidos, deitados, sem suporte dentro da fenda. O modelo e a orientação dispensaram alertas de estabilidade no fatiador.

Foram conferidos: malhas fechadas e conectadas; alcance ao rebaixo; folga no fundo com cabeça assentada; ausência de interpenetração na montagem; espaço geométrico para fechar os braços; perfis, limites de movimento, temperaturas e reposição após retrações no G-code. O projeto 3MF inclui o perfil e foi refatiado para confirmar as configurações. As imagens são renderizações das malhas e dos trajetos reais, não provas físicas de encaixe.

A carcaça completa continua pendente da aprovação dessa trava e da preparação dos suportes das peças maiores. As versões anteriores foram preservadas para comparação.
