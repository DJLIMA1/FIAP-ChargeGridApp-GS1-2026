# Revisão independente — pacote ChargeGrid v8

14/10/2026. Revisão por subagente independente, a pedido explícito do usuário. Produção não alterada pelo revisor. Escopo protegido: 01CHAVE e 02TRSUP.

## Resultado

**A v8 não deve ser considerada mecanicamente encerrada:** encontrei um problema de plausibilidade de flexão na trava curta em D (`13-trava-bandeja.stl`). O fechamento puramente geométrico do rasgo não demonstra que a peça possa flexionar o necessário sem quebra ou deformação permanente. A correção pode ficar inteiramente na bandeja removível e no lote de travas, sem mudar 01 ou 02.

Não encontrei outra interferência estática confirmada no conjunto. Isso não constitui certificação de montagem física ou de resistência.

## Achado funcional prioritário: trava D curta e espessa

Arquivo e fonte: `stl/13-trava-bandeja.stl` e `revisao-completa-v8/preparar-v8.py`, construção de `stop`.

- Corpo com raio 3,6 mm; meio rasgo de 0,6 mm. A largura radial máxima de cada braço é aproximadamente 3,0 mm.
- Centro da raiz arredondada em Z=2,2 mm, raio 0,6 mm; separação começa aproximadamente em Z=1,6 mm.
- Maior aba de retenção em Z=4,2–4,35 mm, raio 3,95 mm; comprimento disponível para flexão é da ordem de 2,0–2,6 mm.
- Fechamento exigido pelo próprio envelope da v8: **0,1264 mm por braço**.
- Como estimativa indicativa, uma viga em balanço de seção retangular dá deformação superficial aproximada `3 t δ / (2 L²)`. Usando t=3,0 mm, δ=0,1264 mm e L=2,0–2,6 mm, resulta **8,4–14,2%**. Esta conta não é FEA, não reproduz a seção curva exata e não é uma medição das propriedades do PLA. Ela identifica um braço muito curto e espesso, que exige deformação significativa para fazer um movimento pequeno.
- A geometria real foi seccionada em Z=1,59 / 1,61 / 2,2 / 3 / 4,2 mm, confirmando a transição entre corpo contínuo e braços partidos. A peça é impressa com cabeça na mesa: a região curta também atravessa camadas.

**Recomendação:** substituir essa trava por bloqueio rígido, sem retenção dependente da flexão desses braços. A solução em análise pelo agente principal — corpo D liso retido por cinta acessível pelo lado frontal — elimina a causa, desde que a cinta tenha canal anti-escorregamento, percurso livre, folga para a cabeça de fechamento e acesso para corte na manutenção. Confirmar que as janelas novas não cortam o apoio dos encaixes da bandeja.

O pino comprido 12 é diferente: comprimento flexível de aproximadamente 8 mm e espessura radial próxima de 0,95 mm; não encontrei nele o mesmo problema de proporção. Continua pendente seu teste físico, especialmente retenção, tolerância e soltura.

## Verificações próprias realizadas

Reexecutadas por código independente, lendo os arquivos entregues:

- **30 STL:** todos fechados, com orientação consistente, um corpo conectado e volume positivo.
- **27 instâncias montadas / 351 pares:** nenhuma interseção volumétrica maior que 0,001 mm³ na posição montada.
- **01CHAVE e 02TRSUP:** G-code, STL do lote, INI e 3MF comparados por SHA-256 com a v6. Os oito arquivos são idênticos.
- **Manifesto da v8:** 151 entradas, todos os hashes conferem, nenhum arquivo não listado além do próprio manifesto.

Além disso, li a implementação dos testes de movimento, a fonte de bandeja/berços/travas, a construção dos acessórios, o perfil do lote de travas e o guia de montagem. O procedimento de remover os berços fora da carcaça, retirando primeiro o ESP32, é essencial e está corretamente escrito no guia. A retirada da bandeja inteira com os berços evita exigir acesso aos pinos dos berços enquanto a bandeja ainda está presa na carcaça.

Os testes de retenção por interseção rígida não são testes de força. Os 34 cenários de movimento da auditoria anterior não foram todos reexecutados por este revisor; a implementação foi inspecionada. Não reclassifico sua contagem como 34 ensaios independentes próprios.

Evidências próprias: `revisor-independente-evidencias.json`. O script de verificação foi executado em `/tmp/chargegrid-independent-review.py`.

## Pendências que a geometria não resolve

- Resistência/fadiga, tolerância da Ender-3 e esforço de inserção/extração dos pinos necessitam montagem real.
- A geometria de quarto de volta garante obstáculo à extração na posição travada; não foi demonstrado torque para giro, retenção contra giro acidental ou esforço sob carga.
- A variante inferior da trava de tampa tem +0,25 mm; o relato físico de sucesso foi da versão padrão v5.
- As placas finais ainda não foram escolhidas e medidas. Não está demonstrada a posição de conectores, dissipação de calor, antena ou caminho real dos cabos.
- A colagem das emendas deve ser apresentada a seco e feita com alinhamento; as chaves impressas não substituem essa união estrutural.
- Não houve inspeção física do SD ou da impressão em andamento.

## Condição para encerrar esta revisão

Substituir a trava D curta, verificar o percurso real de sua retenção, atualizar coerentemente bandeja/lote/3MF/perfil/G-code/guia/manifesto e preservar os oito arquivos de 01 e 02. Depois disso, a conclusão admissível é “não foram encontrados outros defeitos digitais no escopo verificado”; não “garantia de perfeição física”.
