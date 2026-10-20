from pathlib import Path
import json,unicodedata
r=Path(__file__).resolve().parent
jobs=json.loads((r/'ordem-impressao.json').read_text());audit=json.loads((r/'verificacao/auditoria-gcode.json').read_text());rows={x['file']:x for x in audit['files']}
def duration(s):return f'{int(s//3600)}h{int(s%3600//60):02d}'
core=[x for x in audit['files'] if x['file']!='12CABO.gcode']
table=['| Ordem / arquivo | Conteúdo | PLA | Tempo | Suporte |','|---|---|---:|---:|---|']
for j in jobs:
 x=rows[j['id']+'.gcode'];table.append(f"| {j['id']}.gcode | {j['label']} | {x['grams_slicer']:.2f} g | {x['time_slicer']} | {'Sim' if j['support'] else 'Não'} |")
text='''# ChargeGrid — revisão v9 — Ender-3 original / PLA

Geometria v9 de 14/10/2026; revisão final digital de 15/10/2026. Carcaça em 50% da escala original, aproximadamente 225 × 104 × 82 mm. STL em milímetros, importar a 100%. Este pacote contém a revisão de CAD e fatiamento; a montagem física completa ainda não foi validada.

**01CHAVE e 02TRSUP estão preservados byte a byte, incluindo G-code, STL do lote, perfil e projeto. Não precisam ser reimpressos por esta revisão.** O usuário confirmou que 01CHAVE e 02TRSUP já foram impressos.

## Arquivos que substituem os do SD v6

| Antigo | Usar agora | Motivo |
|---|---|---|
| 03TRINF.gcode | 03TRINF7.gcode | Liberação dos alojamentos das duas chaves traseiras; correção já preparada na v7. |
| 05QDINF.gcode | 05QDINF8.gcode | Mesmo modelo; suporte ajustado ao contorno substitui o orgânico cujo registro apontava erro de ramificação. |
| 10BERCO.gcode | 10BERCO9.gcode | Bandeja com canais e reforços para duas cintas; mantém trilhos superiores corrigidos e suporte local. |
| 11TRAVA.gcode | 11TRAVA9.gcode | Dois bloqueios rígidos substituem as travas D flexíveis. Pinos dos berços e oito espaçadores preservados da v8. |

Os outros oito G-codes são idênticos aos da v6. A superfície externa não foi alterada nesta revisão v9. Não misture a bandeja e as travas internas antigas com as revisadas.

**O cartão SD ainda não foi atualizado; o conteúdo está preparado no Mac.** Com 01 e 02 já impressos, antes de iniciar 03, copie a versão atual e confira os nomes acima. Preserve os arquivos já usados apenas como histórico no computador, para não selecionar um antigo por engano no cartão. Não retire o cartão durante uma impressão.

## Ordem de impressão

Imprima um arquivo por vez, retire o lote e prepare a mesa antes do seguinte. Como 01 e 02 já foram impressos, continue em 03TRINF7 depois de atualizar o SD. O lote 12 é opcional.

'''+ '\n'.join(table)+f'''

Estimativa dos arquivos 01–11: **{sum(x['grams_slicer'] for x in core):.2f} g e {duration(sum(x['seconds_slicer'] for x in core))}**. Com o opcional 12: **{audit['total_grams']:.2f} g e {duration(audit['total_seconds'])}**. Inclui brim e suporte; não inclui tempo de acabamento, colagem ou reimpressões. A troca de suporte da peça 05 acrescentou 7,97 g e cerca de 3 minutos à estimativa anterior.

'''+'''Cores sugeridas: 02/03 preto, 04/05 cinza e 06 branco. Troque a cor manualmente entre arquivos. Não há troca de filamento programada no meio da impressão.

## Perfil mantido e suportes

Ender-3 original, placa 4.2.2, Bowden, bico original de 0,4 mm; PLA 1,75 mm, densidade 1,24 g/cm³. Perfil térmico e de movimentos igual ao teste que funcionou: camada 0,24 mm, três perímetros Arachne, quatro camadas de topo/fundo, bico 210 °C na primeira camada / 205 °C nas seguintes, mesa 60 °C. Retração 5 mm a 35 mm/s, retorno 25 mm/s, Z-hop 0,2 mm. Primeira camada 18 mm/s, externa 25, interna 40 e preenchimento 50; vazão configurada 6 mm³/s.

Casca, bandeja e berços: 15% de preenchimento. Chaves, pinos, travas, espaçadores e acessórios: 100%. Brim externo 3 mm com afastamento 0,1 mm, saia de uma linha, sem raft. Ventilação conforme perfil aprovado.

Suportes já incluídos em 02, 03, 04, 05, 06, 09 e 10. Distância de contato configurada 0,20 mm, duas camadas de interface, afastamento XY 0,35 mm. A peça 05 agora usa suporte ajustado ao contorno. O lote 10 tem apoio local pequeno nas saliências detectadas pelo fatiador. Não colocar suporte nos rasgos das travas impressas deitadas.

Após esfriar, remova brim e suportes com cuidado. Limpe trilhos, alojamentos e abas, sem alterar sua medida de projeto. A tampa tem suporte na face externa curva e pode exigir acabamento. A peça 05 é a mais longa, cerca de 10h53.

Todos os movimentos programados, incluindo purga e suportes, foram conferidos dentro de 220 × 220 × 250 mm. Deixe os grampos fora da purga em X=5–5,4 / Y=25–190 mm e fora das peças. Início com aquecimento aguardado, M83, fatores de velocidade/fluxo restaurados; sem comandos de nivelamento automático ou gravação de EEPROM. Final desliga bico, mesa e ventoinha.

## Montagem e manutenção

1. Limpe e apresente a seco as duas traseiras com duas chaves 01. Confira alinhamento antes de colar a emenda estrutural com cola compatível com PLA. Deixe curar alinhado; não preencha alojamentos. As chaves alinham a emenda e não substituem a cola.
2. Una as duas metades do quadro com as duas chaves restantes e o mesmo procedimento. A frente continua removível depois da colagem dessas emendas.
3. Posicione a tampa branca no quadro. Pelo lado interno, insira quatro travas 07PTAMP, com três riscos, nos pontos superiores e centrais. A trava 08PTINF, com quatro riscos, é exclusiva do ponto inferior. Não cole essas travas.
4. Os quatro pinos grandes 09PINO fecham quadro e traseira: retire seus suportes, alinhe as abas, insira por trás e gire 90°. Para abrir, desfaça o giro e retire os pinos; puxe o conjunto frontal para a frente.
5. Na bandeja 10BERCO9, monte primeiro o berço de potência (54 × 35 mm), na estação inferior, e depois o berço do ESP32 (42 × 64 mm), na superior. Entre pelo topo dos trilhos, deslize para baixo até o batente e insira um pino comprido de 11TRAVA9 em cada berço. A cabeça fica pelo lado da placa; as abas passam pelo furo e prendem atrás da bandeja. Não são os pinos da tampa.
6. Use **duas cintas de nylon 100 × 2,5 mm, espessura de referência 1,0 mm**. A referência dimensional é [HellermannTyton T18R 111-01711](https://www.hellermanntyton.com.br/produtos/abracadeiras-com-serrilhado-interno/t18r/111-01711): cabeça 4,45 × 4,8 mm, altura 3,7 mm. O projeto reserva 5 × 4,8 × 4 mm para a cabeça. Confira as dimensões se escolher outra marca; não trocar por cinta mais larga. São consumíveis comprados, não peças para imprimir.
7. Antes de instalar a bandeja, limpe os dois canais no verso. Em cada lado, passe a ponta livre da cinta pelo primeiro furo da aba do bloqueio rígido e pelo furo correspondente da bandeja. Dê o retorno pelo canal do verso e saia pelo segundo furo da bandeja. Deixe a cinta aberta, sem passar pela cabeça de travamento, e deixe o bloqueio afastado para não tapar a entrada larga do apoio. Só a ponta livre atravessa os furos; a cabeça da cinta fica na frente. Acomode o retorno no canal, pré-curvando a cinta suavemente se necessário, sem deixá-la saliente no verso.
8. Posicione a bandeja 5 mm acima da posição final, encaixe as cabeças dos quatro apoios nas entradas largas e deslize para baixo. Coloque os bloqueios D nas partes largas inferiores. **A aba perfurada de cada bloqueio aponta para o centro da bandeja; a face reta do D aponta para o apoio acima dele.** Passe a ponta livre pelo segundo furo do bloqueio, feche na cabeça da cinta e aperte à mão apenas até reter. Não usar alicate para tensionar: a cinta impede a saída do bloqueio, e o corpo rígido D impede a subida. Para manutenção, corte a cabeça/fivela da cinta pela frente com alicate de corte, sem atingir o PLA ou fios; retire as cintas e os bloqueios, suba a bandeja 5 mm e puxe para a frente. Use cintas novas para remontar.

Os dois **pinos compridos** de 11TRAVA9 continuam sendo as travas dos berços: conferir fisicamente que prendem berço e bandeja juntos, e que soltam ao comprimir as abas pelo verso. Não force se a impressão ficar rígida. Para separar os berços da bandeja fora da carcaça, solte os pinos e retire primeiro o ESP32: suba 10,5 mm e afaste-o dos trilhos; depois repita no berço de potência. Instale na ordem inversa. Desconecte/libere os fios antes de movimentar.

![Bloqueios rígidos e percurso das cintas](montagem-bloqueios-v9.png)

9. Fixe as placas reais com cintas e os espaçadores de 3 ou 5 mm sob áreas livres. Os berços são genéricos: posição dos componentes, conectores e antena ainda precisa ser conferida com as placas escolhidas.
10. 12CABO traz um par de insertos para dois cabos de aproximadamente 5 mm e dois pares de presilhas. Meça os cabos antes de selecionar. As alternativas individuais de 4/5/6 mm estão em stl/. Monte as metades ao redor dos cabos intactos e retenha com cintas, sem esmagar a capa. A flange dos insertos fica por dentro; eles saem para o interior, não puxando para baixo. Para manutenção, libere também as cintas.

![Identificação dos pinos da tampa](montagem-travas.png)

## Alcance da revisão

Foram conferidos os 31 STL individuais, 27 instâncias da montagem, 351 pares estáticos, 34 testes de movimento/retenção, variantes de acessórios, 12 lotes e seus G-codes. As malhas estão fechadas, com volume positivo e orientação consistente. Os projetos de fatiamento têm perfis embutidos e foram reabertos para verificar geometria, configuração e consumo; todos os 12 projetos foram reabertos e refatiados para conferência na revisão final de 15/10/2026.

Isso não é garantia de perfeição física. A montagem completa, a resistência das emendas coladas, a elasticidade e a vida útil dos pinos dos berços, a tolerância real da Ender-3 e a remoção dos suportes dependem de ensaio. O ajuste geométrico inferior da tampa (+0,25 mm) também não foi ensaiado fisicamente. Não houve FEA ou ensaio de carga/fadiga. Não foi certificada a capacidade elétrica, térmica nem a acomodação dos módulos finais, ainda não definidos.

O relatório detalhado está em RELATORIO-REVISAO.md. A [última revisão completa de 15/10/2026](REVISAO-FINAL-2026-10-15.md) registra a conferência final sem alterações nos arquivos técnicos. Um subagente independente identificou a rigidez excessiva da trava D anterior e reavaliou a correção: 351 pares estáticos e 592 verificações específicas passaram sem defeito digital confirmado em aberto. O parecer está em REVISAO-INDEPENDENTE.md. Isso não simula a flexão da cinta nem substitui ensaio físico. As verificações digitais não são contagem de ensaios independentes de resistência: várias são amostras de uma mesma trajetória.

## Recuperação

- gcode/: 12 impressões; 12CABO é opcional.
- projetos/: 3MF de cada lote com perfil embutido, para PrusaSlicer 2.9.6. Não importar o STL junto com seu projeto.
- modelos-fatiados/: STL de cada lote na orientação usada; stl/: peças individuais e alternativas.
- montagem/: conjunto para visualização. **Não fatiar o conjunto montado.**
- previas/: imagens dos trajetos reais; verificacao/: relatórios, estimativas, registros e hashes de escopo.
- SHA256SUMS.json: integridade dos arquivos deste pacote.

Para refatiar: `python3 refatiar.py /caminho/PrusaSlicer /pasta/de/saida`. Os 3MF, STL e INI bastam para recuperar o fatiamento. A fonte da correção interna e os scripts de auditoria ficam no projeto, em revisao-independente-v9/, e usam os pacotes históricos locais. A correção da traseira tem sua fonte no pacote histórico v7.
'''
(r/'LEIA-PRIMEIRO.md').write_text(text)
lines=['CHARGEGRID V9 - ENDER-3 ORIGINAL / PLA / BICO 0,4 MM','','01 e 02 preservados. Se ja impressos, nao reimprimir.','Atualizar o SD antes de seguir para 03. Este pacote ainda nao foi copiado ao SD.','Imprimir um arquivo por vez, na ordem abaixo.','']
for j in jobs:
 x=rows[j['id']+'.gcode'];lines.append(j['id']+'.gcode - '+j['label']+' - '+x['time_slicer'])
lines+=['','Novos: 03TRINF7, 05QDINF8, 10BERCO9, 11TRAVA9.','12CABO opcional, so para dois cabos de aproximadamente 5 mm.','Conferir os pinos dos bercos e os bloqueios rigidos com duas cintas novas de nylon.','Para desmontar os bercos: ESP32 primeiro, potencia depois.','Leia LEIA-PRIMEIRO.md e RELATORIO-REVISAO.md antes de montar.']
(r/'COMECE.txt').write_text(unicodedata.normalize('NFKD','\n'.join(lines)+'\n').encode('ascii','ignore').decode())
(r/'registro-validacao.json').write_text(json.dumps({'date':'2026-10-15','official_delivery':'v9','validated_cover_snap_revision':'v5 C','user_reported_previous_coupons_passed':True,'changed_jobs_since_sd_v6':['03TRINF7','05QDINF8','10BERCO9','11TRAVA9'],'already_printed_keys_unchanged':True,'job_02_printed_unchanged':True,'user_confirmed_printed_jobs':['01CHAVE','02TRSUP'],'new_internal_pins_physically_tested':False,'independent_review_completed':True,'short_flexible_D_stop_removed':True,'new_rigid_stops_and_ties_physically_assembled':False,'complete_enclosure_physically_assembled':False,'physical_join_fit_pending':True,'sd_updated':False,'electronics_final_fit_pending':True,'digital_review_complete':True},indent=2)+'\n')
print('GUIA V9 PRONTO',audit['total_grams'],duration(audit['total_seconds']))
