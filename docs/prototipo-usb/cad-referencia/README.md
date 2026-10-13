# Referência geométrica da casca e reserva do cassete

A casca original foi extraída do STEP e escalada uniformemente para 70%, sem adaptar paredes, nervuras ou fixações industriais. As três peças selecionadas contêm nove sólidos. O envelope continua aproximadamente 145,973 mm em X, 115,305 mm em Y e 315,035 mm em Z. **São referências CAD, não peças prontas para impressão.**

## Integridade e formato

O arquivo de origem é identificado pelo SHA256 `dad2a7a04d5e5ee3a4910721e62fedfcc08763ce41629c49d8e0bb8d1eab153d`. Os sólidos extraídos e escalados passaram na validação BRep; o arquivo nativo `.brep` também foi escrito e lido de volta com nove sólidos válidos.

A exportação STEP da casca falhou na validação após reimportação, embora a geometria BRep nativa permaneça válida. Os STEP reexportados inválidos foram descartados. Não confundir essa limitação de intercâmbio com os STEP dos cupons ou dos volumes simples, que passaram nas suas verificações. O arquivo nativo pode ser aberto em programas que suportam OpenCASCADE BRep, incluindo FreeCAD; unidades em milímetros, sem alterar escala na importação.

`extrair-referencia.py` reproduz a extração a partir do STEP do usuário e gera `verificacao-referencia.json`. A pasta contém um arquivo ZIP com as referências nativas para economizar espaço. O estudo inicial com cassete a 40 mm preserva a situação que apresentou interferência; não é a posição corrigida.

## Teste que alterou a reserva inicial

O envelope inicial maciço de 84 × 156 × 40 mm, com plano traseiro em Y=123,2 mm, interceptou aproximadamente 109,35 mm³ de material do quadro original. Não houve interseção com a tampa ou a traseira nessa posição. Deslocar o envelope mantendo os 40 mm até Y=128,2 mm deixou 6,38 mm³ de interferência no quadro. Em Y=129,2 mm, a interseção com o quadro zerou, mas surgiu interferência de 235,70 mm³ com a traseira.

Esses resultados descartam as posições testadas com 40 mm; não provam que toda posição possível de 40 mm seja inviável. Também mostram por que a projeção de malha anterior era apenas uma triagem, e não validação de encaixe.

A revisão `reserva-corrigida.json` registra uma reserva reduzida de 84 × 156 × 36 mm e plano traseiro em Y=126,5 mm, junto com os testes detalhados. As coordenadas mantêm a origem do STEP escalada: X é largura, Y cresce para a traseira e Z cresce para cima. O intervalo vertical fica em Z=48,269 a 204,269 mm, equivalente às alturas 142 a 298 mm acima do ponto mais baixo da casca.

## Alcance da verificação

A interseção booleana verifica se o envelope cruza o material dos sólidos existentes. Ela não demonstra, sozinha, que o volume está dentro da cavidade, que a frente fecha, que novos suportes cabem ou que o cassete consegue entrar e sair. As peças industriais originais permanecem na referência; ainda precisam de reconstrução interna para impressão.

A distância nominal disponível não é tolerância aprovada de fabricação. Devem entrar na próxima revisão: paredes FDM, interfaces universais, deformação/folga, berços, antena, plugs e curvatura dos cabos. Os volumes genéricos do cassete não representam placas compradas e podem mudar com a seleção de módulos prontos.

## Arquivos da revisão atual

- `referencias-nativas-casca-e-estudo-inicial.zip`: descompactar para acessar a casca nativa de nove sólidos e a montagem histórica de 40 mm. O ZIP passou no teste de integridade CRC.
- `cassete-r2-36mm-POSICIONADO-ESTUDO.step`: nove volumes genéricos da reserva corrigida, em coordenadas compatíveis com a casca. Exportação e leitura de volta válidas.
- `cassete-reserva-36mm-POSICIONADO-ESTUDO.brep` e `envelope-84x156x36-POSICIONADO.brep`: versão nativa dos volumes e do envelope maciço.
- `reconstruir-cassete-r2.py`: regenera os volumes simples da r2 a partir do relatório, sem importar a casca.

A menor folga entre superfícies da r2 é 1,896 mm na traseira; no quadro principal, 2,073 mm; na tampa, 11,475 mm. O relatório conserva resultados brutos de distância que retornaram zero indevidamente para cinco pequenos sólidos decorativos, com pontos fora de suas próprias caixas envolventes. Para esses sólidos, a checagem entre faces retornou distâncias de aproximadamente 109–111 mm, coerentes com a separação mínima entre as caixas envolventes. Todos os nove sólidos continuaram incluídos na interseção booleana.
