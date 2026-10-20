# Conteúdo pronto para o SD — ChargeGrid v9

**Preparado no Mac; ainda não copiado ao cartão.** O usuário confirmou que as peças já impressas são 01CHAVE e 02TRSUP. Elas permanecem idênticas aos arquivos registrados na entrega ao SD v6. A próxima impressão é 03TRINF7.

## Estrutura a copiar

Copiar o conteúdo de CONTEUDO-SD para a raiz do cartão, preservando:

- CGFINAL/: arquivos 01–11 em ordem. 01/02 ficam disponíveis para recuperação, mas devem ser pulados porque já foram impressos.
- CGFINAL/OPCIONAL/12CABO.gcode: só após conferir os cabos reais.
- CGDOC9/: guia, relatório, parecer independente, imagens, estimativas, hashes e ZIP completo de recuperação.
- COMECE.txt: orientação atualizada.

Não é necessário refatiar. Não importar STL nem iniciar arquivos de teste antigos. Os nomes dos G-codes têm até oito caracteres antes da extensão, mantendo os nomes das versões revisadas.

## Conferência feita nesta preparação

O manifesto oficial completo e os dois ZIP foram relidos e verificados na última revisão de 15/10/2026. Todos os 12 projetos foram reabertos/refatiados e todos os G-codes conferidos, preservando os 81 arquivos técnicos. Os G-codes finais 10/11 coincidem com os hashes conferidos pelo revisor independente. As correções de 03 e 05 são as versões verificadas anteriormente. As quatro travas padrão da tampa continuam idênticas ao STL v5 aprovado.

A montagem foi reconstruída com as quatro chaves e a traseira superior do pacote v6, combinadas com as outras peças v9. Passaram 120 pares que envolvem essas peças antigas, 196 posições de entrada das chaves e a retirada da bandeja carregada. Também foi conferido o envelope das chaves com espessura fatiada de 2,88 mm. Os oito arquivos de 01/02 (G-code, STL de lote, INI e 3MF) coincidem com a v6; os G-codes coincidem com o recibo de leitura do SD.

Isso confirma a compatibilidade digital com as versões já impressas, sem exigir sua reimpressão. O encaixe físico pode variar com a impressão: apresentar as emendas a seco antes de colar. Os novos bloqueios rígidos usam duas cintas; pinos dos berços, encaixe inferior da tampa e conjunto completo ainda dependem de ensaio físico.

## Quando o SD estiver disponível

1. Confirmar que nenhuma impressão está em andamento e identificar o cartão pelo volume/UUID; não reutilizar um identificador de disco antigo.
2. Fazer backup do conteúdo ChargeGrid existente. Substituir a pasta CGFINAL completa para não deixar G-codes antigos misturados; preservar arquivos não relacionados. Atualizar COMECE.txt e substituir a documentação antiga pela CGDOC9.
3. Copiar os arquivos e conferir com `python3 verificar-copia.py /Volumes/NOME_DO_CARTAO`, executado a partir desta pasta ou usando caminho absoluto do script.
4. Desmontar/remontar e repetir a leitura por hash. Devido às divergências observadas anteriormente nesse cartão/leitor, repetir em dois ciclos antes de ejetar com segurança. O teste local não comprova a integridade da próxima cópia.

Nenhuma dessas operações foi feita no cartão nesta etapa. O script verificar-copia.py é somente de leitura e também detecta G-codes antigos extras em CGFINAL.

O relatório desta última conferência está em CONTEUDO-SD/CGDOC9/REVISAO-FINAL-2026-10-15.md.
