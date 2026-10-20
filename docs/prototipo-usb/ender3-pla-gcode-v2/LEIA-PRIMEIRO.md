# ChargeGrid — perfil v2 para teste — 14/10/2026

No cartão SD, selecione **CGTEST2 → 00TESTE.gcode**. CGPRINT contém a versão anterior.

Perfil informado pelo usuário: Ender-3 original, Bowden, bico 0,4 mm, PLA 1,75 mm; camada 0,24 mm inclusive primeira, 3 perímetros Arachne, 4 camadas de topo/fundo, preenchimento retilíneo de 15%, reforço sólido abaixo de 70 mm². Bico 210 °C na primeira camada e 205 °C depois; mesa 60 °C. Retração 5 mm a 35 mm/s, retorno 25 mm/s. Brim 3 mm, skirt 1 volta a 2 mm do brim. Suportes e raft desligados em todos os arquivos, conforme solicitado.

Inicialização corrigida: milímetros antes dos movimentos; extrusão relativa em comprimento; velocidade e fluxo em 100%. Nenhuma gravação na EEPROM. Removida a retração adicional do trecho de encerramento. A retração final do fatiador é de 5 mm. Deslocamentos Z limitados a 5 mm/s, inclusive no início e fim.

Geometria e orientação preservadas da versão anterior para comparar o perfil. Configurações não especificadas na tabela do usuário foram herdadas do perfil anterior; por exemplo, wipe e posição da costura. O perfil completo está em perfis/. Os projetos 3MF incluem as configurações efetivamente exportadas.

## Limite desta versão

É uma versão experimental sem suportes. O fatiador emitiu avisos em 00TESTE, 01TAMPA, 02TRSUP, 03TRINF, 04QDSUP, 05QDINF, 07PINO e 09BERCO: pontes, trechos sem sustentação e/ou pouca adesão à mesa, conforme a peça. Não houve ensaio físico e a conferência de G-code não garante que essas geometrias imprimam bem sem suportes. Ver avisos detalhados em verificacao/avisos-sem-suportes.json. Começar pelo teste; não iniciar toda a carcaça antes de avaliar o resultado.

Esta revisão não comprova a causa nem a resolução da falha de extrusão relatada. Não aumentar para 260 °C para compensar falhas com o PLA de faixa 180–220 °C informado.

## Estimativas do fatiador

| Arquivo | Filamento | Tempo |
|---|---:|---|
| 00TESTE.gcode | 9.41 g | 1h 3m 27s |
| 01TAMPA.gcode | 28.59 g | 3h 12m 35s |
| 02TRSUP.gcode | 48.24 g | 5h 26m 26s |
| 03TRINF.gcode | 46.07 g | 5h 45m 16s |
| 04QDSUP.gcode | 30.18 g | 3h 30m 58s |
| 05QDINF.gcode | 41.24 g | 5h 18m 40s |
| 06CHAVE.gcode | 2.52 g | 16m 37s |
| 07PINO.gcode | 3.53 g | 26m 21s |
| 08PTAMP.gcode | 0.96 g | 14m 58s |
| 09BERCO.gcode | 28.44 g | 2h 46m 20s |
| 10TRAVA.gcode | 3.10 g | 33m 39s |
| 11CABO.gcode | 6.56 g | 1h 1m 3s |

Conferidos: parâmetros solicitados nos 12 G-codes e 12 projetos, limites de movimento, temperaturas, desligamento, ausência de suportes e reposição após retrações. Dois projetos (teste e tampa) também foram reabertos e refatiados sem perfil externo.
