# Case inclinado para a tela Waveshare ESP32-S3-Touch-LCD-7

Case de mesa, impresso em 3D, para a placa usada no painel do posto (ESP32-S3-Touch-LCD-7, **com touch**, 800 × 480; ver [painel](../waveshare-panel.md)). É uma cunha baixa, estilo console de balcão: a tela fica **deitada a 30° da mesa**, com superfícies lisas e **sem nome ou logotipo**. O corpo apoia direto na mesa, sem placa estendida para trás, e a borda da frente fica levemente no ar, com uma saia inclinada embaixo. **Nenhum parafuso une as peças**: elas se encaixam por pressão, chaves borboleta impressas e cola. Os suportes M3 originais da tela ficam livres.

**Para imprimir na faculdade:** envie a pasta [`entrega-faculdade/`](entrega-faculdade/) ou o arquivo [`ChargeGrid-Case-Tela7-Faculdade-v4.zip`](ChargeGrid-Case-Tela7-Faculdade-v4.zip). Ela contém os 7 STL, as [configurações de impressão](entrega-faculdade/CONFIGURACOES-DE-IMPRESSAO.txt) e o [texto para o laboratório](entrega-faculdade/LEIA-ANTES-DE-ENVIAR.txt).

![Frente](previas/01-frente-3-4.png)

| Lateral | Traseira |
| --- | --- |
| ![Lateral](previas/02-lateral.png) | ![Traseira](previas/03-traseira-3-4.png) |

## Medidas da tela

A documentação do repositório citava apenas o modelo. As medidas abaixo vêm do material oficial da Waveshare: [wiki](https://www.waveshare.com/wiki/ESP32-S3-Touch-LCD-7), [desenho com touch](https://www.waveshare.com/w/upload/e/e8/ESP32-S3-Touch-LCD-7-details-size-2.png) e [pacote 3D (PDF + STEP)](https://files.waveshare.com/wiki/ESP32-S3-Touch-LCD-7/ESP32-S3-Touch-LCD-7in0_Drawing.zip). As caixas dos componentes da PCB, extraídas do STEP, ficam em [`referencia/pcb-componentes-step.json`](referencia/pcb-componentes-step.json).

| Item | Medida (mm) |
| --- | --- |
| Vidro touch (contorno) | 192,96 × 110,76, cantos R7,88 |
| Área ativa | 154,88 × 86,72; bordas pretas de 19,04 nas laterais, 13,04 em cima e 11,00 embaixo |
| Vidro + LCD | 5,00 de espessura |
| Quadro metálico do LCD (verso) | 165,72 × 97,60 |
| Suportes M3 (4, com porca) | 126,20 × 65,65 entre centros |
| PCB | 106,01 × 73,01; face voltada ao LCD a 8,5 da frente do vidro |
| Profundidade total | 18,4 da frente do vidro até o topo dos conectores mais altos |
| Portas (vista de frente) | dois USB-C na lateral **direita**: em cima **UART1**, embaixo **USB**; botões RESET e BOOT na borda inferior da PCB |

## Peças

O case montado mede 204 mm de largura e não cabe inteiro numa impressora de 180 × 180 × 180 mm, o limite informado pela faculdade. Por isso a moldura e o corpo são divididos em metades no centro. A maior medida de qualquer arquivo é 129 mm.

| Arquivo | Peça | Tamanho (mm) | Volume |
| --- | --- | --- | --- |
| `00-TESTE-encaixe-moldura.stl` | 2 tiras de teste da moldura | 26 × 129 × 26 | 2,9 cm³ |
| `00-TESTE-encaixe-corpo.stl` | fatia de teste do corpo (impressa como o corpo real) | 26 × 126 × 83 | 20,5 cm³ |
| `01-MOLDURA-esquerda.stl` / `-direita` | moldura frontal, segura o vidro | 102 × 129 × 26 cada | 13,6 cm³ cada |
| `02-CORPO-esquerdo.stl` / `-direito` | corpo em cunha (imprime deitado sobre o fundo) | 102 × 126 × 83 cada | 108,3 + 103,5 cm³ |
| `04-CHAVES-8un.stl` | 8 chaves borboleta: 3 + 2 reservas para o corpo (3 mm), 1 + 2 reservas para a moldura (1,4 mm) | 84 × 58 × 3 | 3,7 cm³ |

As paredes principais têm 3 mm, conforme a recomendação do laboratório. Ficam mais finas de propósito as partes que flexionam ou encaixam: ganchos (1,6 mm), molas (1,2 mm), saia da moldura (2 mm) e chaves (1,4 e 3 mm).

Montado, o case mede 204 mm de largura, 85 mm de altura (com a moldura) e 127 mm de profundidade, com 31 mm de espessura atrás da tela (incluindo a moldura).

## Como a tela fica presa

![Explodida](previas/05-explodida.png)

- **Moldura → vidro:** o vidro entra num bolso com 0,35 mm de folga por lado. Um lábio de 2,5 mm cobre a borda preta do vidro e não chega à área ativa.
- **Corpo → tela:** seis molas impressas (dedos a 60° com ressalto arredondado) empurram o verso metálico do LCD com 0,35 mm de pré-carga efetiva (0,50 mm no modelo, menos os 0,15 mm de folga dos ganchos), cerca de 4 N cada. A tela fica prensada entre o lábio da moldura e as molas, sem parafusos. As molas evitam a PCB, os suportes M3 e os cabos flexíveis.
- **Moldura → corpo:** seis ganchos de 16 mm. Os **dois de baixo** travam a 90° em janelas da saia frontal e soltam com uma chave de fenda. Os **dois de cima e os dois laterais** ficam escondidos em bolsos com rampa de 45°: seguram a moldura, mas soltam quando se puxa com firmeza. Todos têm 0,15 mm de folga axial, para tolerar pequenos cedimentos da impressão; por isso a moldura pode ficar até 0,15 mm à frente do corpo. A raiz de cada gancho tem um reforço a 45°, e a deformação na montagem fica em torno de 1%.
- **Metades:** chaves borboleta impressas, coladas nas cavidades que atravessam a emenda central. O corpo tem 3 chaves numa nervura do piso, por dentro. A moldura tem 1 chave no verso do queixo. Nenhuma aparece por fora.

| Interior e chaves | Corte no centro | Molas |
| --- | --- | --- |
| ![Interior](previas/09-interior.png) | ![Corte](previas/06-corte-centro.png) | ![Molas](previas/07-corte-molas.png) |

## Impressão

Configurações completas em [`CONFIGURACOES-DE-IMPRESSAO.txt`](textos-entrega/CONFIGURACOES-DE-IMPRESSAO.txt). Em resumo:

- **Material:** PLA, bico 0,4 mm.
- **Qualidade:** camada de 0,2 mm, 4 paredes, 5 camadas no topo e no fundo, preenchimento de 20% (as chaves com 100%).
- **Suporte:** nenhum. Um suporte automático encheria os ganchos e os encaixes.
- **Orientação:** como entregue; não girar as peças.
- **Adesão:** brim de 5 mm no corpo e nos testes.
- **Filamento:** cerca de 280 g de PLA no total (o fatiador dá o valor exato).

Os STL já estão na orientação de impressão: a moldura com a frente na mesa, o corpo deitado sobre o fundo e as chaves deitadas. Nada precisa de suporte. Os únicos balanços são detalhes pequenos, que imprimem sem ajuda: as faces de trava dos ganchos (ressalto de até 1 mm, faces a 60° e tetos dos bolsos a 75°, de 17 mm²), o topo dos furos USB-C (ponte de 13,5 mm numa parede de 3 mm), o topo das fendas de ventilação (3 mm) e o interior dos furos de pino de 2,2 mm.

| Moldura | Corpo | Chaves |
| --- | --- | --- |
| ![](previas/impressao-01-MOLDURA-esquerda.png) | ![](previas/impressao-02-CORPO-esquerdo.png) | ![](previas/impressao-04-CHAVES-8un.png) |

Se possível, imprima primeiro os dois arquivos **00-TESTE**, cerca de 2 a 3 h. O do corpo é uma fatia completa, impressa na mesma posição do corpo real, então o teste vale para a peça grande. Encaixe a tira da moldura na fatia do corpo: o gancho de cima deve soltar puxando, e o de baixo só deve soltar empurrando o dente pela janela. Se ficar duro, aumente `clr_fit` em `gerar.py` (folga entre saia e corpo; padrão de 0,25 mm) e gere de novo.

## Montagem

1. **Corpo:** encaixe as 3 chaves grossas (3 mm) na nervura central do piso de uma metade, sem cola, e apresente a outra metade para conferir. Depois passe cola instantânea (cianoacrilato) ou epóxi nas chaves e nas faces da emenda, una as metades sobre uma mesa plana e segure até firmar.
2. **Moldura:** coloque as duas metades de frente para baixo sobre uma mesa plana, com a chave fina (1,4 mm) no verso do queixo. Confira o alinhamento encaixando a tela **a seco**, retire a tela e só então cole a emenda e a chave. Não deixe cola escorrer para o bolso do vidro.
3. Com tudo seco, coloque a moldura de frente para baixo sobre um pano e encaixe a tela com o vidro para baixo. O lado dos conectores USB-C fica à direita de quem olha a frente da tela.
4. **Ligue o cabo antes de fechar:** passe o plugue USB-C de fora para dentro pelo furo lateral do corpo, **de baixo (USB)** ou **de cima (UART1)**, e encaixe-o na porta da placa com o case ainda aberto. Plugues de até 12,5 × 6,5 mm passam pelo furo. A porta fica 44 mm para dentro, então encaixar depois de fechado é possível, mas às cegas.
5. Desça o corpo sobre a moldura, com a abertura para baixo, deixando o cabo deslizar pelo furo. Segure o plugue durante a descida para não forçar a porta. Pressione até ouvir os seis cliques.
6. Opcional: cole pés de borracha ou silicone por baixo para o case não escorregar.

Na saia inclinada abaixo da tela ficam dois furos de pino: RESET (à direita, vista de frente) e BOOT (à esquerda). Eles alcançam os botões com um clipe de papel. Para tirar a tela, solte os dois ganchos inferiores pelas janelas da saia e puxe a moldura para cima. O cartão microSD só fica acessível com o case aberto.

| Furos USB-C | Saia frontal e fundo |
| --- | --- |
| ![Furos USB-C](previas/04-lateral-direita-usb.png) | ![Por baixo](previas/13-corpo-por-baixo.png) |

## Verificação digital

`gerar.py` reconstrói todas as peças e grava os resultados em `parametros.json`, em `verificacao`:

- **Interferência zero (0 mm³):** moldura × corpo, tela × moldura, tela × corpo, plugues USB-C × case, chaves × peças/tela e entre as tiras de teste. Os únicos contatos com a tela são os ressaltos das molas, por causa da pré-carga intencional.
- **Folga mínima** entre o corpo e a tela/PCB, sem contar as molas: 0,63 mm.
- **Arquivos gravados:** os 7 STL são estanques e não têm triângulos nulos. A maior medida é 129 mm, dentro do limite de 180 mm. O [`CONFERENCIA.json`](entrega-faculdade/CONFERENCIA.json) traz o SHA-256 de cada arquivo.
- **Estabilidade** contra um toque perpendicular ao vidro, com massa estimada de 230 g para a tela: tocar no centro ou na parte de baixo da tela só empurra o case contra a mesa, então ele não tomba. No topo da área ativa, só tomba com 21 N (cerca de 2 kg de força). Um toque capacitivo comum tem 0,5 a 1 N.

## Limitações e o que conferir na peça física

- **Nada foi impresso ainda.** Folgas, pré-carga das molas e força dos ganchos são valores de projeto para PLA e dependem da impressora. Os testes 00 existem para validar isso.
- **Base traseira:** continua disponível em `gerar.py` (`usar_base=True`), mas não é necessária com a tela deitada.
- **Emendas:** na frente, as emendas da moldura ficam no centro do topo e do queixo. Com a cola, viram uma linha fina; se quiser, lixe e pinte.
- **Pré-carga das molas:** 0,35 mm efetiva (`spring_preload` = 0,50 menos a folga de 0,15 dos ganchos), calculada com a espessura vidro + LCD de 5,00 mm do desenho oficial. Se a tela ficar solta, aumente `spring_preload`; se ficar apertada demais, reduza.
- **Suportes M3:** a altura deles no verso não aparece no desenho. Usei um envelope estimado de até 8,6 mm atrás do vidro e mantive as molas e os postes afastados.
- **Massa da tela:** é estimada (230 g), e a estabilidade depende dela.

## Regenerar

```bash
pip install numpy trimesh manifold3d pillow
```

```bash
python gerar.py
```

```bash
python renderizar.py
```

```bash
python preparar_entrega.py
```

Todos os parâmetros ficam no dicionário `P` no início de `gerar.py`: inclinação (`tilt_deg`, medida a partir do vertical; hoje 60°, ou seja, tela a 30° da mesa), folgas, espessuras, queixo, molas, ganchos, chaves e a base opcional. Para estudos sem editar o arquivo, use `CASE_PARAMS='{"tilt_deg": 45}' python gerar.py`. Os textos do pacote ficam em `textos-entrega/`.
