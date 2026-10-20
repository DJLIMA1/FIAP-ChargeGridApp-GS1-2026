# Parecer independente da correção v9 — ChargeGrid

14/10/2026. Revisão por subagente independente, solicitada pelo usuário. Este revisor não alterou arquivos de produção.

## Conclusão mecânica

**A correção v9 elimina o defeito encontrado na trava D da v8:** a retenção deixou de exigir flexão de braços curtos e espessos em PLA. Dois bloqueios D rígidos, espelhados e retidos por cintas, impedem a subida da bandeja. Os arquivos protegidos 01CHAVE e 02TRSUP permanecem idênticos à v6.

Após a correção e o rebaixo traseiro para as cintas, não encontrei outra interferência ou impossibilidade de movimento nos casos digitais que executei. Isso não garante tolerância, resistência, força de montagem ou durabilidade físicas.

## Verificações próprias, lendo as malhas entregues

- **31 STL:** malhas fechadas, orientação consistente, volume positivo e um corpo conectado por peça. A contagem cresceu porque os bloqueios esquerdo e direito agora são arquivos distintos.
- **27 instâncias / 351 pares montados:** nenhuma interseção volumétrica maior que 0,001 mm³.
- **592 checagens específicas da correção:** envelopes das duas cintas contra as peças montadas; subida de 0 a 5 mm em passos de 0,05 mm contra a traseira e suas chaves; retirada de cada bloqueio de 0 a 15 mm em passos de 0,1 mm, sem a cinta e com a frente retirada; corredor de acesso frontal. Nenhuma falhou.
- **01 e 02:** oito arquivos protegidos — G-code, STL de lote, INI e projeto 3MF de cada um — comparados por SHA-256 com a v6 e preservados.

Evidências: `revisor-independente-evidencias.json`. Script próprio executado: `/tmp/chargegrid-independent-review-v9.py`. Os 592 itens incluem amostras de trajetórias; não são ensaios independentes de resistência.

## Detalhes mecânicos conferidos

Os bloqueios são rígidos, sem rasgos ou abas sobredimensionadas de encaixe elástico. A cabeça/aba tem 2 mm de espessura, e o canal frontal de 0,3 mm deixa nominalmente 1,7 mm. Os furos têm 3,2 × 1,8 mm para a reserva de cinta de 2,5 × 1,0 mm. O centro da cinta foi deslocado para 7,5 mm em relação ao eixo do D; a aba foi alargada mantendo sua conexão com a cabeça.

A menor distância nominal no plano entre o rebaixo novo e a entrada circular é aproximadamente 2,05 mm. O canal traseiro tem 1,3 mm de profundidade, com reforço frontal da base até 2,8 mm, deixando 1,5 mm localmente. A cabeça/aba D foi elevada 0,4 mm para manter folga em relação a esse reforço. Não é uma medição de carga admissível: apertar a cinta apenas à mão, o suficiente para manter o D assentado, sem torcer a bandeja nem usar alicate para tensionar. A força de bloqueio vertical é transmitida pelo corpo D; a cinta impede sua extração.

O retorno traseiro da cinta fica dentro da espessura da bandeja, com envelope nominal em Z local 0,15–1,15 mm. Isso evita a interferência com uma nervura da traseira inferior durante a subida, detectada pelo agente principal na primeira versão da solução com cinta.

A orientação de impressão coloca a face da cabeça/aba na mesa, com a haste para cima. A região rebaixada do canal deixa um pequeno vão de aproximadamente 2,9 mm a transpor, não um braço longo suspenso. Os furos continuam abertos. A avaliação de esforço não é FEA.

## Instalação e manutenção

A sequência descrita pelo agente principal é praticável geometricamente e deve constar no guia:

1. Com a bandeja fora da carcaça, passar a **ponta livre** da cinta pelo primeiro furo do bloqueio e pelo primeiro furo da bandeja. A cabeça da cinta permanece na frente e não deve atravessar o furo.
2. Levar a ponta pelo canal traseiro e fazê-la sair no segundo furo da bandeja. Manter a cinta aberta e o D solto, afastado da entrada larga; não bloquear essa entrada antes de encaixar a bandeja nos apoios.
3. Manter o retorno assentado no canal, instalar a bandeja 5 mm acima e deslizá-la para baixo. Assentar cada D com sua aba voltada para o centro.
4. Passar a ponta livre pelo segundo furo do D e fechar a cinta. Apertar apenas para reter, sem deformar as peças.
5. Para manutenção, retirar a frente e cortar a **cabeça/fivela da cinta pelo lado frontal**, remover a cinta e o D, subir a bandeja 5 mm e puxar para a frente. Usar cintas novas na remontagem.

O modelo de fivela cobre praticamente todo o trecho frontal da cinta; não se deve prometer uma faixa livre sob a qual qualquer tesoura possa entrar. O corredor frontal verificado é uma reserva de acesso, não uma simulação de um modelo particular de alicate. Confirmar as dimensões da cinta/fivela comprada; foram reservados 2,5 × 1,0 mm para a fita e 5 × 4,8 × 4 mm para a fivela. Manter fios afastados do ponto de corte. O envelope não simula a curvatura da cinta: pré-dobrar e assentar manualmente o retorno no canal; conferir a peça impressa e remover qualquer suporte ou rebarba desse canal.

A referência real é a **HellermannTyton T18R 111-01711**: fita 100 × 2,5 × 1,0 mm, cabeça 4,45 × 4,8 × 3,7 mm e fechamento não reutilizável. Essas dimensões foram conferidas diretamente na [página técnica do fabricante](https://www.hellermanntyton.com.br/produtos/abracadeiras-com-serrilhado-interno/t18r/111-01711). A reserva CAD de 5 × 4,8 × 4 mm comporta as dimensões nominais; uma cinta genérica de mesma largura pode ter outra espessura ou cabeça.

## Limites mantidos

Os pinos compridos dos berços e a variante inferior da trava da tampa ainda dependem de teste físico. A correção da trava D não valida automaticamente todas as outras travas. A apresentação a seco e alinhamento das emendas precedem a colagem; os berços continuam genéricos porque a eletrônica final não foi medida. Não houve ensaio de carga/fadiga, avaliação térmica, medição de encolhimento da impressão nem inspeção física do SD.

## Entrega e fatiamento

Conferi os G-codes finais **10BERCO9** e **11TRAVA9**, seus registros de fatiamento, os perfis embutidos e a geometria dos projetos 3MF. Os registros de geração não contêm aviso ou erro. Os projetos têm, respectivamente, 3 e 12 corpos, com dimensões e volumes correspondentes aos STL dos lotes; diferenças de volume inferiores a 0,00002 mm³. Camada 0,24 mm, bico 0,4 mm, filamento 1,75 mm, temperaturas 210/205 °C e mesa 60 °C concordam entre G-code e 3MF. O lote 10 usa 15% de preenchimento e suporte; o lote 11 usa 100%, sem suporte. Evidência: `revisor-fatiamento.json`.

Hashes dos G-codes conferidos:

- 10BERCO9: `05cccf3fc24380b2c1639b42152a7b0a79c374c606704f30823bd77f3dde544a`.
- 11TRAVA9: `1dfa6ceb018f9951e184383ecb68fd4b9e044ba0492c93b9787d5e2017a818c3`.

A última geometria foi novamente submetida aos 351 pares e às 592 verificações específicas, todas sem falha. Não há outro defeito digital confirmado aberto nesta revisão. O empacotamento final, os hashes globais e a cópia ao SD ficam a cargo do agente principal; este parecer não afirma que o cartão foi atualizado nem que ocorreu validação física.
