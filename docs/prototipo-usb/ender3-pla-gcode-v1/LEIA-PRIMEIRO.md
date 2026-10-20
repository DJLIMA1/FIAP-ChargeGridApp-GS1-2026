# ChargeGrid — G-code pronto — Ender 3 original / PLA / bico 0,4 mm

Fatiado em 14/10/2026 com **PrusaSlicer 2.9.6 estável**, a partir do perfil oficial da Ender-3 original, com ajustes para estas peças. Agora há G-code textual compatível com Marlin, suportes gerados, temperaturas, retração, velocidades e início/fim configurados.

**Para imprimir diretamente do cartão, usar os arquivos da pasta CGPRINT.** As pastas anteriores com STL/3MF são os modelos e não precisam ser usadas na impressora. Os nomes curtos 00TESTE, 01TAMPA etc. facilitam a seleção no visor. Não redimensionar nem editar os G-codes.

## Primeira impressão

1. Colocar PLA de 1,75 mm, conferir nivelamento manual e limpar a mesa. O bico considerado é o original de 0,4 mm, com extrusor Bowden original.
2. Manter grampos fora da área central de impressão e das duas linhas de purga próximas de X=5 mm, entre Y=25 e 190 mm. As posições e os suportes foram conferidos dentro de 220 × 220 mm.
3. Selecionar **00TESTE.gcode**. O arquivo aquece a mesa a 60 °C e o bico a 205 °C na primeira camada, depois 200 °C; faz homing e imprime. Não há nivelamento automático G29 nem alteração de EEPROM.
4. Acompanhar a primeira camada. Após esfriar, remover brim e suportes, testar encaixe e soltura dos cupons. A bandeja/trilhos, pino da tampa e pino de quarto de volta devem funcionar sem forçar. Fazer dez ciclos como triagem; se trincar ou travar, ajustar antes das peças grandes.
5. Imprimir os outros arquivos, **um por vez**. Os arquivos não mudam a cor automaticamente; carregar a cor desejada antes de iniciar cada impressão.

Os G-codes usam PLA genérico a 200–205 °C. Conferir que o intervalo recomendado no rolo inclui essas temperaturas. Esta não é uma calibração da marca/lote do filamento ou da máquina real. Não houve impressão física.

## Arquivos e estimativas

Tempos e massas são estimativas do fatiador, com suportes e brim, e podem mudar conforme firmware, calibração e pausas. Não incluem perdas de tentativa ou acabamento.

| Arquivo | Impressão | PLA | Tempo | Suportes |
|---|---|---:|---:|---|
| [00TESTE.gcode](gcode/00TESTE.gcode) | Teste dos encaixes | 14.0 g | 2h29 | Sim |
| [01TAMPA.gcode](gcode/01TAMPA.gcode) | Tampa branca | 45.3 g | 6h03 | Sim |
| [02TRSUP.gcode](gcode/02TRSUP.gcode) | Traseira superior | 47.9 g | 5h35 | Sim |
| [03TRINF.gcode](gcode/03TRINF.gcode) | Traseira inferior | 57.7 g | 7h40 | Sim |
| [04QDSUP.gcode](gcode/04QDSUP.gcode) | Quadro superior | 39.2 g | 4h56 | Sim |
| [05QDINF.gcode](gcode/05QDINF.gcode) | Quadro inferior | 65.5 g | 10h06 | Sim |
| [06CHAVE.gcode](gcode/06CHAVE.gcode) | Chaves das emendas | 2.9 g | 0h30 | Não necessários no preparo adotado |
| [07PINO.gcode](gcode/07PINO.gcode) | Pinos de fechamento | 4.3 g | 0h52 | Sim |
| [08PTAMP.gcode](gcode/08PTAMP.gcode) | Pinos da tampa | 0.9 g | 0h19 | Não necessários no preparo adotado |
| [09BERCO.gcode](gcode/09BERCO.gcode) | Bandeja e berços | 27.8 g | 3h53 | Não necessários no preparo adotado |
| [10TRAVA.gcode](gcode/10TRAVA.gcode) | Travas e calços | 3.0 g | 0h46 | Não necessários no preparo adotado |
| [11CABO.gcode](gcode/11CABO.gcode) | Cabos de 5 mm — opcional | 6.9 g | 1h33 | Não necessários no preparo adotado |

**Tudo, incluindo testes e opção de cabos: 315.3 g e aproximadamente 44h43.** Somente exterior e suas fixações (01 a 08): 263.7 g e 36h01. Reservar margem de material: cerca de 400 g disponíveis para o conjunto completo é prudente, sem garantir uma reimpressão integral.

A impressão 11 é apenas para dois cabos de diâmetro nominal próximo de 5 mm. Os módulos reais ainda não foram escolhidos: a impressão 09 contém os berços genéricos. Nenhuma dessas opções é necessária para conferir o exterior.

## O que foi otimizado

- **Quatro perímetros**, mantendo resistência nas paredes, com **15% de preenchimento nas regiões espessas da casca** e 20% na bandeja/berços. Em paredes finas, o fatiador usa a quantidade de linhas que cabe; não altera a espessura geométrica.
- Camadas de **0,24 mm nas quatro metades da carcaça**, 0,20 mm na tampa branca e 0,16 mm nos encaixes, fixações e conjunto bandeja/berços.
- Pequenas fixações em 100% de preenchimento: como são pequenas, a economia por deixá-las ocas seria mínima. Os pinos de fechamento estão deitados, com suporte, para favorecer continuidade das camadas ao longo da haste; resistência real ainda depende do teste.
- Suportes ajustados ao contorno na tampa, traseiras e quadro superior. Suportes orgânicos no quadro inferior, que consumiram menos material que as alternativas comparadas. Sem raft.
- Brim de 5 mm nas peças maiores e 3 mm nas fixações. Velocidade de parede externa de 20–25 mm/s, perímetros até 40 mm/s, preenchimento até 50 mm/s, aceleração de impressão de 500 mm/s². Fluxo volumétrico nominal limitado a 6 mm³/s.
- Retração de 4 mm a 35 mm/s para o Bowden original; ventilação progressiva, chegando a 100%. O fatiador desacelera camadas pequenas.

As orientações foram comparadas por consumo/tempo e inspecionadas. Isso é uma otimização entre as alternativas testadas, não uma garantia de mínimo absoluto. O quadro inferior ainda é a peça mais lenta devido ao formato e aos apoios internos.

**Correção da orientação indicada nos guias antigos:** a descrição textual anterior da tampa estava invertida em relação ao STL. Para este G-code, a face externa curva fica voltada aos suportes e a cavidade para cima. Isso reduz o consumo/tempo, mas pode exigir acabamento da face branca após remover suportes. As orientações de impressão atuais estão em modelos-fatiados/ e projetos/; não aplicar novamente as rotações dos estudos.

## Suportes e montagem

Os apoios e brim são material de descarte. Remover cuidadosamente depois de esfriar, em especial sob a haste/abas dos pinos e nos alojamentos. Não forçar a peça para compensar suporte residual. Algumas paredes originais têm aproximadamente 1,3–1,6 mm; retirar suportes em porções pequenas para não danificá-las.

A montagem continua sem parafusos: emendas estruturais alinhadas por chaves e coladas com adesivo compatível com PLA; fechamento de manutenção por pinos; bandeja e berços removíveis. Instruções em montagem.md. PLA substituiu o PETG inicialmente previsto e as linguetas ainda não foram qualificadas nesse material; o teste 00 é necessário. O projeto elétrico, encaixe de módulos reais e dissipação permanecem pendentes.

## Arquivos para recuperação e refatiamento

- **gcode/**: os 12 arquivos que já podem ser selecionados na Ender-3 original.
- **projetos/**: 12 projetos 3MF com geometria e perfis incorporados para o PrusaSlicer. Foram reabertos e refatiados sem INI externo para conferir a persistência das configurações. Suportes são recalculados ao refatiar; pequenas diferenças de estimativa podem ocorrer.
- **perfis/**: ajustes explícitos de cada lote em INI.
- **modelos-fatiados/**: STL na orientação utilizada; escala final, importar a 100%.
- **previas/**: imagens dos trajetos reais, primeira camada e uma seção intermediária. Azul indica suportes, laranja indica peça e cinza indica brim. A vista 3D é uma projeção resumida; não é uma fotografia nem previsão exata do acabamento.
- **verificacao/**: auditoria de comandos, temperaturas, limites, consumo e estimativas; comparação de orientações e resultado de reabertura dos 3MF.
- **SHA256SUMS.json**: hashes de integridade.

A auditoria percorreu os movimentos e extrusões, incluindo suportes e purga: limites de 220 × 220 × 250 mm, aquecimento anterior à extrusão, homing, desligamento de mesa/bico/ventoinha e liberação dos motores X/Y/E ao final. Nenhuma simulação comprova aderência, resistência, folga ou qualidade física da máquina real.

Referências: [PrusaSlicer 2.9.6 oficial](https://github.com/prusa3d/PrusaSlicer/releases/tag/version_2.9.6), [relação entre perímetros e resistência](https://help.prusa3d.com/article/layers-and-perimeters_1748), [preenchimento](https://help.prusa3d.com/article/infill_42).
