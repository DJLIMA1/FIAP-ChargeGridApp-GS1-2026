from pathlib import Path
import json,shutil
r=Path(__file__).resolve().parent;p=r.parent/'ender3-pla-oficial-v8'
s=json.loads((r/'auditoria-estatica.json').read_text());m=json.loads((r/'movimentos.json').read_text());a=json.loads((r/'acessorios.json').read_text());g=json.loads((p/'verificacao/auditoria-gcode.json').read_text());c=json.loads((r/'congruencia.json').read_text())
assert not s['collisions'] and not m['failed'] and all(x['pass'] for x in a['results'])
assert all(x['watertight'] and x['consistent_winding'] and x['positive_volume'] and x['components']==1 for x in s['individual_parts'])
assert len(g['files'])==12
text='''# Revisão integral mecânica e de impressão — ChargeGrid v8

14 de outubro de 2026. Resultado: os defeitos encontrados nesta auditoria foram corrigidos nos arquivos locais e as verificações digitais descritas abaixo passaram. **Não é possível garantir que o conjunto físico esteja perfeito antes de imprimi-lo e montá-lo.** As novas travas internas ainda precisam de ensaio de inserção, retenção e soltura em PLA.

## Correções efetivas

| Item | Problema encontrado | Correção e efeito na impressão |
|---|---|---|
| Alojamentos traseiros | Dois apoios da bandeja invadiam o volume das chaves em cerca de 12,54 mm³ por chave, na v6. | Correção v7 mantida: 03TRINF7 substitui 03TRINF. Chaves e traseira superior preservadas. |
| Bandeja carregada | O berço superior alcançava o teto ao subir os 5 mm necessários à retirada. | Estação superior desceu 6 mm. A retirada completa com berços e pinos passou sem colisão. O berço em si mantém 42 × 64 mm. |
| Apoios dos pinos dos berços | A ventilação passava sob o apoio inferior: o pino não tinha material para engatar atrás; no superior, o apoio era parcial. | Ambos os apoios agora chegam à base; os dois pinos apresentam retenção geométrica. |
| Pinos internos | Abas circulares e raízes dos rasgos sem arredondamento não aproveitavam bem a direção de flexão. | Abas laterais, raízes arredondadas e pino do berço impresso deitado. Envelope geométrico de fechamento verificado; resistência/flexibilidade não simuladas. |
| Fatiamento do lote 10 | Aviso de ancoragem de ponte flutuante nas saliências dos trilhos. | Suporte local ativado em 10BERCO8; novo fatiamento sem esse aviso. |
| Suporte da peça 05 | Registro da v6/v7: `Error: Potentially lost branch!, critical: 1` no suporte orgânico. | Mesmo STL, suporte ajustado ao contorno em 05QDINF8; geração e reabertura sem esse erro. Acréscimo estimado de 7,97 g e 3min02. |

Os problemas de percurso da bandeja, apoio dos pinos e registros de suporte não tinham sido identificados na validação anterior. Por isso, a afirmação anterior de prontidão era mais ampla do que a evidência permitia.

## Cobertura realizada

'''
text+=f'''- **{s['individual_stl_count']} arquivos STL individuais:** leitura após exportação, malha fechada, orientação consistente, volume positivo e um corpo conectado por peça; dimensões abaixo.
- **{s['assembly_instances']} instâncias no conjunto:** correspondência dos STL com a montagem, incluindo comparação da nuvem de vértices após transformação rígida; erro máximo {max(x['rigid_vertex_cloud_max_error_mm'] for x in c):.7f} mm.
- **{s['all_static_pairs']} pares estáticos:** nenhuma interseção volumétrica acima de 0,001 mm³ na posição montada.
- **{len(m['results'])} testes de movimento/retenção**, com {sum(len(x['samples']) for x in m['results'])} posições amostradas: giro e retirada dos quatro pinos de quarto de volta, abertura frontal, retirada da tampa, retenção dos cinco pinos da tampa, retirada da bandeja carregada, trilhos e travas internas.
- **{len(a['results'])} verificações de acessórios e reservas:** quatro pares de insertos, suas trajetórias de retirada e retenção pela flange, canais para cabos nominais, três presilhas, folga nominal dos espaçadores e volumes genéricos de placas. Várias verificações são amostras de uma mesma trajetória, não ensaios físicos independentes.
- **12 lotes, 39 instâncias impressas incluindo o lote opcional**, contagens e volume útil de 220 × 220 × 250 mm conferidos.
- **12 G-codes:** comandos de posição/extrusão, temperaturas, retrações, limites de movimento, presença dos suportes, aquecimento, encerramento e consumo. Configuração de vazão 6 mm³/s; máximo calculado em segmentos curtos arredondados {max(x['max_nominal_flow_mm3_s'] for x in g['files']):.2f} mm³/s.
- **12 projetos com perfil embutido:** configuração, geometria, quantidade e consumo verificados ao reabrir. Nove inalterados conservam o resultado anterior com identidade por hash; os três novos foram reabertos e refatiados nesta revisão.
- **Emendas:** verificação v7 preservada, pois sua geometria não mudou na v8: quatro chaves, folgas no plano de ±0,15 mm e 49 posições de inserção por chave. As hastes dos apoios traseiros foram preservadas. Isso não mede a resistência da colagem.

'''
text+='''As inspeções visuais usam as malhas e os trajetos entregues. Não são imagens geradas por IA nem medições de peças impressas.

![Todas as peças individuais revisadas](todas-as-30-pecas.png)

## Inventário dimensional dos STL

Medidas do arquivo na orientação individual; alguns lotes aplicam outra orientação de impressão. Dimensão em Z pode ser quantizada pelo fatiador em camadas de 0,24 mm.

| Arquivo individual | Dimensões X × Y × Z (mm) | Malha |
|---|---|---|
'''
for x in s['individual_parts']:text+='| '+x['file']+' | '+' × '.join(f'{z:.3f}' for z in x['dimensions_mm'])+' | Fechada, um corpo |'+chr(10)
text+='''
## Identidade das peças já impressas

01CHAVE e 02TRSUP preservam G-code, STL do lote, perfil INI e projeto 3MF byte a byte em relação à v6. A revisão v8 não exige reimpressão dessas peças.

Em relação ao conteúdo v6 enviado ao SD, há quatro substituições: 03TRINF → 03TRINF7, 05QDINF → 05QDINF8, 10BERCO → 10BERCO8 e 11TRAVA → 11TRAVA8. Os outros oito G-codes são idênticos. Em relação à v7, mudaram somente 05, 10 e 11. A carcaça externa e as quatro travas de tampa iguais à v5 aprovada foram preservadas.

## Montagem: pontos que devem ser conferidos fisicamente

- Apresentar a seco as duas emendas, conferir alinhamento e assentamento antes de colar. As chaves alinham; a união estrutural depende da cola.
- Remover integralmente os suportes dos alojamentos e dos pinos grandes, sem desgastar as superfícies de retenção.
- A trava inferior da tampa é 0,25 mm mais longa; a validação física informada foi da trava v5 padrão, não dessa variante.
- No lote 11TRAVA8, os dois pinos compridos fixam os berços à bandeja; as duas travas curtas em D bloqueiam as entradas largas inferiores da bandeja. Conferir retenção e soltura reais. Se a inserção exigir força excessiva ou houver deformação permanente, parar e ajustar somente essas peças modulares.
- Para remover o conjunto interno, tirar as duas travas em D, subir 5 mm e puxar para a frente. Para desmontar os berços da bandeja, tirar os pinos e remover o ESP32 primeiro; subir 10,5 mm antes de afastar dos trilhos. Potência depois. Montar na ordem inversa.
- Medir os cabos reais antes de imprimir o lote opcional. Presilhas são específicas do diâmetro nominal; insertos têm 0,25 mm de folga radial. Isso não garante a compressão adequada de qualquer capa de cabo.

## Limites desta revisão

Não foram medidos força de inserção, flexibilidade do PLA, fadiga, carga nas hastes, resistência das emendas coladas, empenamento, encolhimento, acabamento ou repetibilidade da Ender-3. A verificação de retenção usa interferência de corpos rígidos ao tentar extraí-los: comprova a existência do obstáculo geométrico, não sua força de retenção. As trajetórias foram amostradas, não certificadas por uma prova contínua de colisão. O envelope de fechamento das abas exige cerca de 0,140 mm por braço no pino do berço e 0,126 mm na trava em D; essas medidas não são uma previsão da elasticidade do material.

A eletrônica final não está definida. Os berços são suportes genéricos, com reservas de 32 × 58 × 8 mm e 48 × 29 × 15 mm. Não foi demonstrado encaixe de uma placa comprada específica, posição de conectores/antena, caminho de fios, refrigeração nem funcionamento elétrico. Essa pendência pode exigir troca dos berços e da bandeja, preservando a casca se o conjunto escolhido couber no volume disponível.

O SD estava na impressora e não foi atualizado. Os problemas anteriores de consistência de leitura do cartão não são resolvidos pela revisão CAD; a próxima cópia precisa de nova conferência por hash após remontagem. Não há aqui certificação do estado do cartão ou da impressora.

## Evidências e recuperação

Os JSON em verificacao/ registram pares, trajetórias, dimensões, configurações e escopo das mudanças. SHA256SUMS.json identifica o pacote. O guia LEIA-PRIMEIRO.md traz os nomes exatos, a ordem e a montagem. A pasta de auditoria no projeto conserva os scripts e os resultados anteriores v7 que motivaram as correções. Os arquivos da v7 e da v6 permanecem como histórico no Mac.
'''
(r/'RELATORIO.md').write_text(text)
(p/'RELATORIO-REVISAO.md').write_text(text)
for n in ['todas-as-30-pecas.png','interior-revisado.png']:shutil.copy2(r/n,p/n)
for n in ['auditoria-estatica.json','movimentos.json','acessorios.json','congruencia.json']:shutil.copy2(r/n,p/'verificacao'/n)
# Eliminate obsolete logs from the current release; originals remain in the v7 archive.
for n in ['05QDINF','10BERCO','11TRAVA']:
 for f in (p/'verificacao').glob(n+'-*.log'):f.unlink()
(p/'CORRECAO-PECA-03.txt').unlink(missing_ok=True)
(p/'preparar.py').unlink(missing_ok=True)
# Do not ship the old generation script where running it would regress the new assembly.
q=p/'LEIA-PRIMEIRO.md';q.write_text(q.read_text().replace('Não executar preparar.py pensando que ele gera a v8 completa: ele é o registro da correção da traseira v7.','A correção da traseira tem sua fonte no pacote histórico v7.'))
f=p/'escrever-guia.py';f.write_text(f.read_text().replace('Não executar preparar.py pensando que ele gera a v8 completa: ele é o registro da correção da traseira v7.','A correção da traseira tem sua fonte no pacote histórico v7.'))
print('REPORT COMPLETE')
