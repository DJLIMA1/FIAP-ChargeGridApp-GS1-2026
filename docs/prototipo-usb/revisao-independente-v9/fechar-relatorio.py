from pathlib import Path
import hashlib,json,shutil
R=Path(__file__).resolve().parent;P=R.parent/'ender3-pla-oficial-v9';old=R.parent/'ender3-pla-oficial-v8';v6=R.parent/'ender3-pla-oficial-v6'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protected=json.loads((R/'arquivos-01-02-preservar.json').read_text())
for n,d in protected.items():assert h(P/n)==d
changes=[];renames={'03TRINF7':'03TRINF','05QDINF8':'05QDINF','10BERCO9':'10BERCO','11TRAVA9':'11TRAVA'}
for p in sorted((P/'gcode').glob('*.gcode')):
 n=renames.get(p.stem,p.stem)+'.gcode';changes.append({'file':p.name,'v6_file':n,'unchanged_from_v6':h(p)==h(v6/'gcode'/n),'sha256':h(p)})
assert [x['file'] for x in changes if not x['unchanged_from_v6']]==['03TRINF7.gcode','05QDINF8.gcode','10BERCO9.gcode','11TRAVA9.gcode']
for p in (P/'gcode').glob('*.gcode'):
 if p.stem not in ['10BERCO9','11TRAVA9']:assert h(p)==h(old/'gcode'/p.name)
static=json.loads((R/'auditoria-estatica.json').read_text());motions=json.loads((R/'movimentos.json').read_text());parts=json.loads((R/'congruencia-lotes-v9.json').read_text())
assert not static['collisions'] and not motions['failed'] and len(parts)==39
assert all(x['watertight'] and x['consistent_winding'] and x['positive_volume'] and x['components']==1 for x in static['individual_parts'])
report='''# Revisão integral após parecer independente — ChargeGrid v9

14/10/2026. O usuário pediu uma revisão independente com correções, preservando 01 e 02. Um subagente revisou a v8 sem modificar produção e encontrou um defeito na trava curta D: braços curtos e espessos exigiam flexão excessiva para uma solução confiável em PLA. A estimativa foi um diagnóstico por proporções de viga, não FEA.

**O defeito foi eliminado substituindo essas travas por bloqueios rígidos presos por cintas de nylon. O mesmo revisor conferiu a correção final e os dois novos lotes. Não há defeito digital confirmado em aberto nos casos verificados. A montagem, a resistência e a tolerância físicas continuam pendentes de ensaio.**

## Preservação das impressões existentes

01CHAVE e 02TRSUP preservam byte a byte os oito arquivos protegidos: G-code, STL do lote, INI e 3MF de cada um. Os hashes coincidem com o pacote v6 enviado ao cartão. **Esta revisão não exige reimpressão de 01 ou 02.** Os STL individuais correspondentes também não foram alterados.

## O que mudou nesta rodada

- O bloqueio D deixou de ter rasgo, braços flexíveis ou ressalto de encaixe. Agora há um bloqueio esquerdo e um direito, com abas voltadas para o centro.
- Cada aba recebe uma cinta: a função dela é impedir que o bloqueio saia para a frente. O corpo D continua impedindo a subida que liberaria a bandeja.
- A bandeja recebeu dois pares de furos e canais traseiros de 1,3 mm, evitando que as cintas esbarrem na nervura da traseira durante a instalação. O reforço frontal local chega a 2,8 mm, deixando nominalmente 1,5 mm de material acima do canal. A menor distância no plano ao rasgo existente é aproximadamente 2,05 mm.
- Os canais frontais dos bloqueios têm 0,3 mm de profundidade numa aba de 2 mm. Os furos têm 3,2 × 1,8 mm. A cinta é apertada apenas manualmente, o suficiente para reter.
- Somente os G-codes 10BERCO9 e 11TRAVA9 mudaram em relação à v8. Os pinos compridos dos berços, os oito espaçadores, os berços e toda a carcaça permanecem iguais à v8. O perfil de impressão aprovado continua preservado.

Referência dimensional da cinta: [HellermannTyton T18R 111-01711](https://www.hellermanntyton.com.br/produtos/abracadeiras-com-serrilhado-interno/t18r/111-01711), 100 × 2,5 × 1,0 mm e cabeça de 4,45 × 4,8 × 3,7 mm. São necessárias duas unidades novas por montagem; o envelope CAD reserva cabeça de 5 × 4,8 × 4 mm. Outras marcas só após conferir a fita e a cabeça. As cintas são compradas, não impressas.

![Retenção revisada](montagem-bloqueios-v9.png)

## Evidência da conferência

- 31 STL individuais: leitura após exportação, malhas fechadas, orientação consistente, volume positivo e um corpo conectado em cada arquivo.
- 27 instâncias da montagem e 351 pares estáticos sem interseções acima de 0,001 mm³.
- 34 testes de movimento/retenção do conjunto: giro/extração dos pinos grandes, frente, tampa, bandeja carregada, berços e retirada dos bloqueios após cortar as cintas.
- 242 verificações de acessórios, passagem dos cabos e reservas genéricas de eletrônica; incluem amostras de trajetórias e não são ensaios de carga.
- 39 instâncias nos 12 lotes comparadas aos STL individuais por transformação rígida e nuvens de vértices. As 27 instâncias da montagem também correspondem às peças entregues.
- 592 verificações próprias do revisor na correção: cintas contra peças, subida em passos de 0,05 mm, retirada dos bloqueios em passos de 0,1 mm e corredor de acesso frontal. Sem falhas.
- 12 G-codes com limites, temperaturas, retrações, início/final e suportes conferidos. Os dez G-codes inalterados preservam a auditoria anterior por identidade de conteúdo; os dois novos foram auditados e seus projetos reabertos/refatiados. O revisor conferiu os dois novos G-codes, os perfis embutidos e a correspondência dos 3MF com os STL de lote.
- Nenhum registro corrente de geração/reabertura contém aviso ou erro do fatiador. As correções anteriores de 03 e dos suportes de 05 permanecem aplicadas.

O parecer separado [REVISAO-INDEPENDENTE.md](REVISAO-INDEPENDENTE.md) registra as evidências, dimensões, limites e hashes conferidos pelo revisor. Os JSON detalhados estão em verificacao/. Os scripts usados pelo revisor foram preservados em fontes-revisao/.

## Substituições para o cartão ainda na versão v6

| Arquivo antigo | Usar |
|---|---|
| 03TRINF.gcode | 03TRINF7.gcode |
| 05QDINF.gcode | 05QDINF8.gcode |
| 10BERCO.gcode | 10BERCO9.gcode |
| 11TRAVA.gcode | 11TRAVA9.gcode |

Se a v8 já tiver sido copiada depois desta conversa, somente 10BERCO8 e 11TRAVA8 precisam ser substituídos pelos lotes 9. Os outros oito arquivos da v6 seguem idênticos. **O SD não foi atualizado nesta rodada.** Deixe 02 terminar e atualize o cartão antes de iniciar 03. Não retire o cartão durante uma impressão.

## Instalação e ensaio físico

Com a bandeja fora, passe a ponta de cada cinta pelo primeiro furo do bloqueio e da bandeja, dê o retorno no canal traseiro e saia pelo segundo furo da bandeja. Deixe o bloqueio afastado e a cinta aberta. Assente a bandeja nos apoios e deslize 5 mm para baixo; então assente os D, passe a ponta pelo segundo furo do bloqueio e feche as cintas manualmente. Cabeça e ponta ficam acessíveis pela frente. Não tente passar a fivela pelos furos.

Para manutenção, corte as fivelas pela frente, retire as cintas e os D, suba a bandeja 5 mm e retire-a. Não há necessidade de flexionar o PLA dos D. Use cintas novas para remontar. O guia inclui imagem e instruções detalhadas, inclusive a ordem de retirada dos berços: ESP32 primeiro, potência depois.

Verifique na impressão que os canais estão limpos, que a cinta se acomoda sem saliência no verso e que as cabeças não encostam em fios/placas. O envelope digital não simula a curvatura da cinta; pode ser necessário pré-curvá-la suavemente. Não force nem tensione com ferramenta.

## Limites que permanecem

A revisão não garante perfeição física. Os pinos compridos dos berços, a variante inferior da tampa, os encaixes completos, as emendas coladas e os bloqueios com cintas ainda precisam de montagem e ensaio reais. Não foram medidos força de retenção, fadiga, empenamento, encolhimento, aderência nem acabamento. As interseções de retenção comprovam obstáculo geométrico, não resistência. As trajetórias são amostradas.

Os módulos eletrônicos finais não foram escolhidos/medidos; berços e reservas continuam genéricos. Não foi certificado encaixe de conectores, passagem final de fios, antena, refrigeração ou funcionamento elétrico. O estado do cartão SD também não foi certificado nesta rodada; a próxima cópia deve ser conferida após remontagem.

## Inventário final

Dimensões dos STL individuais em milímetros, na orientação do arquivo. Alguns lotes aplicam outra orientação; importar a 100%.

| STL | X × Y × Z (mm) |
|---|---|
'''
for x in static['individual_parts']:report+='| '+x['file']+' | '+' × '.join(f'{d:.3f}' for d in x['dimensions_mm'])+' |'+chr(10)
report+='\n![31 peças individuais](todas-as-31-pecas.png)\n'
(P/'RELATORIO-REVISAO.md').write_text(report);(R/'RELATORIO.md').write_text(report)
for name in ['auditoria-estatica.json','congruencia.json','movimentos.json','acessorios.json','verificacao-cintas.json','cintas.json','congruencia-lotes-v9.json','arquivos-01-02-preservar.json','revisor-independente-evidencias.json','revisor-fatiamento.json']:
 shutil.copy2(R/name,P/'verificacao'/name)
shutil.copy2(R/'REVISAO-INDEPENDENTE.md',P/'REVISAO-INDEPENDENTE.md')
(P/'verificacao/escopo-da-correcao.json').write_text(json.dumps({'release':'v9','gcodes':changes,'protected':protected,'changed_gcodes_from_v8':['10BERCO9','11TRAVA9'],'sd_updated':False},indent=2)+'\n')
(P/'verificacao/revisao-interna-v9.json').write_text(json.dumps({'rigid_D_stops_replaced_short_flexible_stops':True,'tie_count':2,'tie_strap_mm':[2.5,1.0],'rear_channel_depth_mm':1.3,'local_tray_total_thickness_mm':2.8,'remaining_web_mm':1.5,'independent_reviewer_closed_confirmed_digital_findings':True,'physical_validation_pending':True},indent=2)+'\n')
(P/'verificacao/revisao-interna-v8.json').unlink(missing_ok=True)
(P/'todas-as-30-pecas.png').unlink(missing_ok=True)
for name in ['10BERCO8','11TRAVA8']:
 for f in (P/'verificacao').glob(name+'-*.log'):f.unlink()
(P/'fontes-revisao').mkdir(exist_ok=True)
for filename in ['chargegrid-independent-review-v8.py','chargegrid-independent-review-v9.py']:
 f=Path('/tmp')/filename
 if f.exists():shutil.copy2(f,P/'fontes-revisao'/filename)
print('V9 REPORT AND SCOPE COMPLETE')
