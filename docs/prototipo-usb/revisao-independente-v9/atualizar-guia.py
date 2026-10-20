from pathlib import Path
import json
R=Path(__file__).resolve().parent;P=R.parent/'ender3-pla-oficial-v9';old=R.parent/'ender3-pla-oficial-v8'
p=P/'ordem-impressao.json';jobs=json.loads(p.read_text())
for j in jobs:
 if j['id']=='10BERCO9':j['source_previous_job']='10BERCO8';j['label']='Bandeja com canais das cintas e dois berços'
 if j['id']=='11TRAVA9':j['source_previous_job']='11TRAVA8';j['label']='Pinos dos berços, bloqueios rígidos e espaçadores'
p.write_text(json.dumps(jobs,ensure_ascii=False,indent=2)+'\n')
s=(old/'escrever-guia.py').read_text().replace('revisão v8','revisão v9').replace('Revisão v8','Revisão v9').replace('GUIA V8','GUIA V9').replace('10BERCO8','10BERCO9').replace('11TRAVA8','11TRAVA9')
s=s.replace('Bandeja com trilhos superiores 6 mm mais baixos, apoio completo sob as travas e suporte local no fatiamento.','Bandeja com canais e reforços para duas cintas; mantém trilhos superiores corrigidos e suporte local.')
s=s.replace('Dois pinos dos berços e duas travas da bandeja revisados. Os oito espaçadores continuam iguais.','Dois bloqueios rígidos substituem as travas D flexíveis. Pinos dos berços e oito espaçadores preservados da v8.')
s=s.replace('As novas travas internas ainda precisam de ensaio de inserção, retenção e soltura em PLA.','Os pinos dos berços e o conjunto completo ainda precisam de ensaio físico.')
s=s.replace('6. Posicione a bandeja montada aproximadamente 5 mm acima da posição final, passe as cabeças', '6. Posicione a bandeja montada aproximadamente 5 mm acima da posição final, passe as cabeças')
a=s.index('6. Posicione a bandeja montada');b=s.index('\n9. Fixe',a)
s=s[:a]+'''6. Use **duas cintas de nylon 100 × 2,5 mm, espessura de referência 1,0 mm**. A referência dimensional é [HellermannTyton T18R 111-01711](https://www.hellermanntyton.com.br/produtos/abracadeiras-com-serrilhado-interno/t18r/111-01711): cabeça 4,45 × 4,8 mm, altura 3,7 mm. O projeto reserva 5 × 4,8 × 4 mm para a cabeça. Confira as dimensões se escolher outra marca; não trocar por cinta mais larga. São consumíveis comprados, não peças para imprimir.
7. Antes de instalar a bandeja, limpe os dois canais no verso. Em cada lado, passe a ponta livre da cinta pelo primeiro furo da aba do bloqueio rígido e pelo furo correspondente da bandeja. Dê o retorno pelo canal do verso e saia pelo segundo furo da bandeja. Deixe a cinta aberta, sem passar pela cabeça de travamento, e deixe o bloqueio afastado para não tapar a entrada larga do apoio. Só a ponta livre atravessa os furos; a cabeça da cinta fica na frente. Acomode o retorno no canal, pré-curvando a cinta suavemente se necessário, sem deixá-la saliente no verso.
8. Posicione a bandeja 5 mm acima da posição final, encaixe as cabeças dos quatro apoios nas entradas largas e deslize para baixo. Coloque os bloqueios D nas partes largas inferiores. **A aba perfurada de cada bloqueio aponta para o centro da bandeja; a face reta do D aponta para o apoio acima dele.** Passe a ponta livre pelo segundo furo do bloqueio, feche na cabeça da cinta e aperte à mão apenas até reter. Não usar alicate para tensionar: a cinta impede a saída do bloqueio, e o corpo rígido D impede a subida. Para manutenção, corte a cabeça/fivela da cinta pela frente com alicate de corte, sem atingir o PLA ou fios; retire as cintas e os bloqueios, suba a bandeja 5 mm e puxe para a frente. Use cintas novas para remontar.

Os dois **pinos compridos** de 11TRAVA9 continuam sendo as travas dos berços: conferir fisicamente que prendem berço e bandeja juntos, e que soltam ao comprimir as abas pelo verso. Não force se a impressão ficar rígida. Para separar os berços da bandeja fora da carcaça, solte os pinos e retire primeiro o ESP32: suba 10,5 mm e afaste-o dos trilhos; depois repita no berço de potência. Instale na ordem inversa. Desconecte/libere os fios antes de movimentar.

![Bloqueios rígidos e percurso das cintas](montagem-bloqueios-v9.png)
''' +s[b:]
s=s.replace('Foram conferidos os 30 STL individuais','Foram conferidos os 31 STL individuais').replace('a elasticidade e a vida útil dos novos pinos','a elasticidade e a vida útil dos pinos dos berços')
s=s.replace('O relatório detalhado está em RELATORIO-REVISAO.md.','O relatório detalhado está em RELATORIO-REVISAO.md. Um subagente independente identificou a rigidez excessiva da trava D anterior e reavaliou a correção: 351 pares estáticos e 592 verificações específicas passaram sem defeito digital confirmado em aberto. O parecer está em REVISAO-INDEPENDENTE.md. Isso não simula a flexão da cinta nem substitui ensaio físico.')
s=s.replace('todas as 30','todas as 31').replace('em revisao-completa-v8/','em revisao-independente-v9/')
s=s.replace("'official_delivery':'v8'","'official_delivery':'v9'")
s=s.replace("'new_internal_pins_physically_tested':False", "'new_internal_pins_physically_tested':False,'independent_review_completed':True,'short_flexible_D_stop_removed':True,'new_rigid_stops_and_ties_physically_assembled':False")
s=s.replace('As novas travas internas precisam de conferencia fisica nos lotes 10 e 11.','Conferir os pinos dos bercos e os bloqueios rigidos com duas cintas novas de nylon.')
s=s.replace('CHARGEGRID V8','CHARGEGRID V9')
(P/'escrever-guia.py').write_text(s)
print('GUIDE GENERATOR UPDATED')
