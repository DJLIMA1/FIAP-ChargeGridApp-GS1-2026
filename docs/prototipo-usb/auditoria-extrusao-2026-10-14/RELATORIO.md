# Auditoria do 00TESTE.gcode — 14/10/2026

O usuário confirmou falha no teste e filamento PLA com faixa indicada de 180–220 °C. A auditoria examinou os arquivos locais entregues anteriormente. O cartão não estava montado nesta conferência. Nenhuma impressora foi operada e nenhum G-code foi substituído.

## Resultado

Não foi encontrado erro de diâmetro configurado, mistura de extrusão absoluta/relativa ou retração sem reposição durante a impressão que explique, por si só, a necessidade relatada de 260 °C. Isso não comprova ausência de problema de fatiamento nem identifica a causa física.

Os 12 G-codes locais correspondem aos hashes registrados na entrega. No teste:

| Item | Resultado |
|---|---|
| Bico configurado | 0,4 mm; não comprova o bico fisicamente instalado |
| Filamento configurado | 1,75 mm |
| Multiplicador do fatiador | 1,00 |
| Aquecimento | Pré-aquecimento 150 °C; espera atingir 205 °C antes da purga |
| Temperatura na impressão | 205 °C na primeira camada; 200 °C desde a segunda |
| Mesa | 60 °C |
| Camadas | 0,20 mm inicial; 0,16 mm seguintes |
| Pico nominal de vazão da impressão | 3,5867 mm³/s, calculado dos movimentos; depende de overrides e interpretação do firmware |
| Maior velocidade de deposição | 35 mm/s |
| Retração | 4 mm, configuração de 35 mm/s, com wipe |
| Reposições completas antes de continuar a impressão | 1.229; nenhuma deposição iniciada com retração pendente acima da tolerância numérica |
| Encerramento | Retração de 4 mm do fatiador mais 2 mm do G-code final, total de 6 mm após a última deposição |
| Duração estimada | 2h29min06s; primeira camada estimada em 8min48s |

As temperaturas de impressão estão dentro da faixa informada no rolo. Se a temperatura for aumentada manualmente antes de iniciar o arquivo, ele volta a comandar 205 °C; ao iniciar a segunda camada, comanda 200 °C. A coincidência entre essa transição e a falha ainda não foi confirmada. O arquivo não comanda 260 °C.

## Limitações encontradas na preparação

1. **Inicialização dependente do estado anterior da impressora.** Não há `M200 D0`, `M220 S100` ou `M221 S100` para explicitar extrusão em comprimento, velocidade em 100% e fluxo em 100%. Além disso, `G21` aparece depois da purga. São lacunas de robustez: não provam que esses estados estivessem incorretos. Uma revisão deve colocar `G21` antes dos movimentos, explicitar os modos compatíveis com o firmware e documentar os resets de overrides. Não alterar EEPROM ou calibração de passos como parte disso.
2. **Teste de encaixes inadequado como primeiro diagnóstico de extrusão.** O lote leva cerca de duas horas e meia e contém numerosas retrações (30 na primeira camada, máximo de 40 em uma camada). Ele serve para avaliar encaixes, mas dificulta isolar alimentação e temperatura. O próximo diagnóstico deve ser curto, com geometria simples e poucas retrações, após conferir o funcionamento da extrusão.
3. **Retração duplicada ao encerrar.** O trecho final acrescenta 2 mm aos 4 mm já retraídos pelo fatiador. Convém remover o acréscimo redundante em uma revisão. Ele ocorre após a última deposição: não explica a falha durante este teste. A purga do próximo trabalho precisa ser considerada ao avaliar o reinício.
4. **Validação anterior apenas digital.** Dimensões, trajetos e limites foram conferidos, mas não houve calibração térmica, de retração ou ensaio físico nesta impressora. Apresentar o pacote como plenamente validado para ela seria incorreto.

## O que ainda falta para identificar a causa

A faixa do rolo não justifica subir para 260 °C. Não continuar compensando a falha com essa temperatura no conjunto original informado. É necessário distinguir se o filamento falha também com o bico afastado da mesa, sem executar este G-code, na faixa do fabricante. Essa observação separa problemas de alimentação/aquecimento de problemas associados à primeira camada ou ao percurso do teste; não constitui diagnóstico definitivo de obstrução, ventilação, sensor ou extrusor.

## Evidências e referências

- `resultados.json`: medições de todos os G-codes; `auditar.py`: análise reproduzível, somente leitura dos arquivos originais. Os limites físicos e os estados reais do firmware não são verificáveis por este script.
- Linhas do arquivo original: 21 (`M109 S205`), 2779 (`M104 S200`), 81977–81991 (retração final total de 6 mm).
- [Marlin — extrusão volumétrica e M200](https://marlinfw.org/docs/gcode/M200.html): o modo volumétrico interpreta E em volume; sua desativação deve ser coerente com o arquivo.
- [Marlin — velocidade M220](https://marlinfw.org/docs/gcode/M220.html) e [fluxo M221](https://marlinfw.org/docs/gcode/M221.html): multiplicadores independentes do perfil do fatiador.
- [Prusa — interrupção da extrusão e heat creep](https://help.prusa3d.com/article/extrusion-stopped-mid-print-heat-creep_1948): referência para hipóteses de falha térmica, sem diagnóstico remoto confirmado.
