# ChargeGrid 50% — Ender 3 original — PLA

Preparado em 14/10/2026. Corpo de aproximadamente 225 × 104 × 82 mm, dividido para a mesa de 220 × 220 mm. Bico de 0,4 mm, filamento PLA de 1,75 mm. **Todos os arquivos já estão em meia escala: importar a 100%, em milímetros.**

## Como usar

Cada pasta numerada corresponde a uma impressão. Abra **o 3MF ou o STL**, nunca os dois juntos: contêm a mesma quantidade de peças nas mesmas posições. O 3MF mantém as peças como objetos separados; o STL contém todas as peças daquele lote, separadas fisicamente. Não desagrupar para imprimir uma peça sobre a outra e não aplicar disposição automática sem conferir o resultado.

São arquivos de geometria preparados para fatiamento. **Não contêm suportes gerados, perfil de impressão embutido ou G-code.** As configurações estão neste guia e no LEIA-ANTES.txt de cada pasta. Não houve execução em fatiador nem impressão física; não há previsão verificada de tempo ou consumo de PLA.

No Cura ou Creality Print, selecionar a **Creality Ender-3 original**, mesa 220 × 220 × 250 mm, bico 0,4 mm e PLA. Preservar o início/fim de G-code do perfil da sua máquina. Uma Ender original sem sensor não deve receber comandos de nivelamento automático acrescentados manualmente. Imprimir todas as peças por camadas, não sequencialmente por objeto.

1. Abrir a pasta 00, importar um dos arquivos e aplicar as configurações de testes.
2. Gerar os suportes necessários, revisar a prévia de camadas e exportar o G-code para a máquina.
3. Ensaiar baioneta, tampa e trilho como descrito abaixo antes dos lotes maiores.
4. Abrir uma impressão por vez, aplicar as configurações da tabela e conferir primeira camada, suportes, cavidades e limites da mesa.
5. Manter o mesmo PLA e a mesma calibração aprovados nos testes para os encaixes correspondentes.

## Ordem e configurações de cada impressão

| Pasta | Conteúdo | Quantidade | Camada | Preenchimento | Cor sugerida |
|---|---|---:|---:|---:|---|
| 00-teste-encaixes | Cupons e dois pinos de teste | 7 | 0,16 mm | 100% | Qualquer |
| 01-tampa-branca | Tampa frontal inteira | 1 | 0,20 mm | 25% | Branco |
| 02-traseira-superior | Metade superior traseira | 1 | 0,20 mm | 25% | Preto |
| 03-traseira-inferior | Metade inferior traseira | 1 | 0,20 mm | 25% | Preto |
| 04-quadro-superior | Metade superior do quadro | 1 | 0,20 mm | 25% | Cinza |
| 05-quadro-inferior | Metade inferior do quadro | 1 | 0,20 mm | 25% | Cinza |
| 06-chaves-das-emendas | Quatro chaves para as emendas | 4 | 0,16 mm | 100% | Qualquer |
| 07-pinos-quarto-de-volta | Quatro pinos de fechamento | 4 | 0,16 mm | 100% | Preto |
| 08-pinos-tampa-branca | Cinco pinos, com nº 5 de comprimento diferente | 5 | 0,16 mm | 100% | Qualquer |
| 09-bandeja-e-bercos | Bandeja e dois berços genéricos | 3 | 0,20 mm | 35% | Qualquer |
| 10-travas-e-espacadores | Duas travas por tipo e quatro calços por altura | 12 | 0,16 mm | 100% | Qualquer |
| 11-cabos-duplos-5mm-OPCIONAL | Inserto bipartido e quatro metades de presilha | 6 | 0,16 mm | 100% | Qualquer |

As peças da pasta 00 são para ensaio; a quantidade de montagem já está completa nas outras pastas. A pasta 11 é uma alternativa para dois cabos de 5 mm nominal: só imprimir após medir os cabos. A pasta pecas-individuais conserva as 35 variantes originais, incluindo insertos e presilhas de 4/5/6 mm, para reposição. Não é necessário imprimir todas essas variantes.

## Ajustes iniciais para PLA

Estes valores são pontos de partida, não um perfil fisicamente ensaiado:

- Bico **200 °C** e mesa **60 °C**, ajustando ao intervalo indicado pelo fabricante do PLA e ao resultado dos cupons.
- Primeira camada de **0,20 mm a 15 mm/s**. Ventoinha desligada na primeira camada, aumentando gradualmente até 100% por volta da quarta camada.
- Quatro perímetros; topo/fundo de aproximadamente 1 mm. Algumas paredes originais reduzidas têm 1,3–1,6 mm: quatro linhas não cabem em todas elas. Conferir paredes finas/largura variável e continuidade das paredes na prévia.
- Casca: **40 mm/s**, parede externa 25 mm/s, brim 6 mm.
- Bandeja e berços: **35 mm/s**, parede externa 25 mm/s, brim 5 mm.
- Pinos, travas, chaves e testes: **25 mm/s**, parede externa 20 mm/s, brim 5 mm. Tempo mínimo de camada inicial de 10 segundos para peças pequenas.
- Retração inicial para o Bowden original: **4 mm a 35 mm/s**. Ajustar conforme stringing e extrusão; não transportar esses valores para uma máquina convertida para direct drive.
- Fluxo inicial 100%; compensação horizontal inicial zero. Corrigir o pé de elefante pela calibração/compensação de primeira camada, sem escalar o conjunto para corrigir encaixes.

## Suportes e orientação

As orientações anteriores foram mantidas. As peças estão apoiadas em Z=0 e os lotes centralizados, com margem livre mínima de 20 mm antes de brim/suportes. Conferir também os grampos da mesa, linha de purga e a expansão dos suportes no fatiador.

- **Quatro metades da carcaça:** emenda plana na mesa. Revisar apoios nas saliências, postes e alojamentos internos; somente suportes vindos da mesa podem não alcançar todas as regiões.
- **Tampa branca:** face externa curva voltada à mesa; precisa de suporte sob a curva. Interface de suporte ajuda no acabamento, mas haverá marcas. Não imprimir flutuando sobre o leito sem suporte.
- **Pinos de quarto de volta:** cabeça na mesa, suporte localizado sob as abas. Retirar esse suporte antes de encaixar. A resistência entre camadas ainda precisa ser ensaiada.
- **Pinos da tampa e travas:** conferir pequenas saliências; manter as pontas bipartidas livres. Não deixar suporte preso no rasgo.
- **Bandeja e berços:** bases planas, preservar folgas dos trilhos; revisar pequenas pontes e evitar suporte preso em canais fechados.

Ponto de partida para suportes: limiar de 55°, densidade 12%, interface ativada, distância Z de 0,20 mm (o fatiador pode arredondar à altura de camada) e distância XY de 0,4 mm. Inspecionar e ajustar por peça. Esses valores não garantem remoção ou acabamento; evitar apoiar estruturas dentro dos canais da baioneta e encaixes sem acesso para limpeza.

## Teste obrigatório dos encaixes em PLA

A geometria foi inicialmente concebida para PETG. A mudança para PLA **não incluiu redesenho ou validação mecânica das linguetas**. PLA pode romper em encaixes que exigem flexão; por isso a primeira impressão é a pasta 00.

- Pino 07 no cupom 16: alinhar abas, inserir, girar 90° e conferir retenção e liberação sem força excessiva.
- Pino 08-1 na placa 18 sobre a bucha 17: conferir encaixe e liberação da ponta bipartida.
- Trilho 20 e macho 21: conferir deslizamento e retenção.
- Fazer dez ciclos como triagem. Se aparecer trinca, esbranquiçamento ou necessidade de forçar, não avançar com os pinos de montagem; revisar encaixe/material e repetir o teste. Não corrigir com escala global.

As quatro emendas/alojamentos completos ainda exigem conferência durante a montagem; cupons não reproduzem todos os esforços da carcaça. PLA também precisa de avaliação térmica quando os módulos elétricos forem definidos.

## Montagem e limite do projeto

Seguir montagem-original-v1.md para a ordem de montagem e posição dos pinos; os nomes das peças individuais foram preservados da revisão original. **Para esta entrega, material, lotes e fatiamento são os deste guia.**

As duas emendas estruturais (traseira e quadro) usam chaves e cola compatível com PLA. A frente abre por quatro pinos removíveis. A bandeja e os dois berços são substituíveis. Placas e cabos usam espaçadores e abraçadeiras plásticas; não são fixados por parafusos.

A placa de potência e a variante exata do ESP32 ainda não foram fechadas. O exterior pode ser impresso para o protótipo visual, mas o espaço final para eletrônica, plugs, fios e dissipação não está validado. A modularidade permite trocar suportes; não aumenta o volume disponível. A revisão não garante que o conjunto elétrico futuro caiba sem ajustes.

## Verificação realizada

Conferência dos STL por releitura: malhas fechadas, orientação consistente, volume positivo e quantidade correta de componentes separados. Conferência independente do XML dos 3MF: unidades, quantidade de objetos, malhas fechadas e limites da mesa. Os arquivos 3MF e STL de cada lote possuem a mesma geometria. SHA256SUMS.json registra integridade. Não foi feito fatiamento, ensaio físico ou estimativa de tempo/filamento.

Referências de equipamento e material consultadas em 14/10/2026:

- [Creality — perguntas e especificações](https://www.creality.com/resources/faq)
- [Creality — materiais para Ender 3, V2 e Pro](https://forum.creality.com/t/choosing-the-right-filament-ender-3-v2-pro-s1-edition/23423)
