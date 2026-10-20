from pathlib import Path
import json,hashlib,re,shutil
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent;P=BASE/'ender3-pla-oficial-v9';A=BASE/'revisao-independente-v9'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
protected=json.loads((ROOT/'arquivos-tecnicos-antes.json').read_text())
for n,d in protected.items():assert h(P/n)==d,('technical_file_changed',n)
s=json.loads((A/'auditoria-estatica.json').read_text());m=json.loads((A/'movimentos.json').read_text());a=json.loads((A/'acessorios.json').read_text());ind=json.loads((A/'revisor-independente-evidencias.json').read_text());lot=json.loads((A/'congruencia-lotes-v9.json').read_text());g=json.loads((P/'verificacao/auditoria-gcode.json').read_text());cfg=json.loads((P/'verificacao/perfis-e-projetos.json').read_text())
assert len(s['individual_parts'])==31 and not s['collisions'] and all(x['watertight'] and x['consistent_winding'] and x['positive_volume'] and x['components']==1 for x in s['individual_parts'])
assert not m['failed'] and len(m['results'])==34
assert not ind['failures'] and len(ind['correction_checks'])==592 and not ind['static_collisions']
assert all(x['pass'] for x in a['results']) and len(lot)==39
assert len(g['files'])==12 and len(cfg)==12
for x in cfg:assert x['restore_balance_pass'] and x['project_embedded_profile_matches'] and x['reopened_project_settings_geometry_and_material_match']
for f in (P/'verificacao').glob('*.log'):assert not re.search(r'warning|error',f.read_text(),re.I),f
report={'date':'2026-10-15','release':'v9','stl_files':31,'static_pairs':s['all_static_pairs'],'static_collisions':0,'motion_tests':34,'independent_review_script_reexecuted_cases':592,'correction_failures':0,'accessory_checks':len(a['results']),'printed_instances_matched_to_stl':len(lot),'gcodes_audited':12,'projects_reopened_and_resliced':12,'unchanged_technical_files':len(protected),'gcode_or_geometry_changed':False,'already_printed_preserved':['01CHAVE','02TRSUP'],'documentation_corrected':'Recovery guide now records both01 and02 as printed; final audit date and all12project checks updated','physical_full_assembly_validated':False,'sd_written':False}
(ROOT/'resultado.json').write_text(json.dumps(report,indent=2)+'\n')
text=f'''# Última revisão completa — 15/10/2026

**Resultado: nenhuma nova falha digital confirmada.** As correções v7, v8 e v9 estão aplicadas e coerentes no pacote preparado para o cartão. Nenhum G-code, STL, perfil, 3MF de impressão ou geometria de montagem precisou ser alterado nesta revisão.

**01CHAVE e 02TRSUP permanecem idênticos aos arquivos usados nas impressões já realizadas. Não precisam ser reimpressos por esta revisão.** A comparação usa os arquivos da v6 e o recibo da cópia efetivamente lida no cartão. O conjunto atual foi novamente verificado com as chaves e traseira superior antigas: 120 pares sem colisão, 196 posições de entrada das chaves e percurso da bandeja carregada livres. Foi incluída a espessura de 2,88 mm resultante do fatiamento das chaves.

## Conferências concluídas

| Conferência | Resultado |
|---|---|
| 31 STL individuais | Fechados, orientados corretamente, volume positivo, um corpo por peça |
| 27 peças posicionadas / 351 pares | Sem colisões volumétricas acima de 0,001 mm³ |
| 34 testes de movimento e retenção | Passaram |
| 592 verificações do roteiro do revisor independente, reexecutadas | Passaram; incluem várias posições de cada trajetória |
| 242 verificações de acessórios/reservas | Passaram |
| 39 instâncias dos 12 lotes | Correspondem aos STL individuais |
| 12 G-codes | Limites de mesa, temperaturas, extrusão, retração, suportes, início e final conferidos |
| 12 projetos 3MF | Reabertos e refatiados; perfil, geometria, quantidade e consumo conferidos |
| {len(protected)} arquivos técnicos | Permanecem idênticos aos da v9 anterior a esta revisão |
| Registros de geração/reabertura | Sem aviso ou erro do fatiador |

Os suportes estão presentes em 02, 03, 04, 05, 06, 09 e 10. A temperatura permanece 210 °C na primeira camada e 205 °C nas demais, mesa a 60 °C, PLA 1,75 mm e bico de 0,4 mm. O máximo de vazão configurado continua 6 mm³/s. Nenhuma configuração de impressão foi alterada.

## Ajuste realizado

O guia dentro do pacote completo ainda descrevia 02TRSUP como uma impressão em andamento. Atualizei esse registro para refletir sua confirmação de que **01 e 02 já foram impressos**, uniformizei as instruções e registrei esta última revisão. O conteúdo de recuperação e o pacote pronto para SD foram reempacotados e verificados; os hashes dos pacotes mudam por causa dos documentos, não por mudança nas peças.

## Continuação

Depois da cópia verificada ao SD, continuar por **CGFINAL/03TRINF7.gcode**. Na sequência: 04QDSUP, 05QDINF8, 06TAMPA, 07PTAMP, 08PTINF, 09PINO, 10BERCO9 e 11TRAVA9. 12CABO fica em OPCIONAL e depende do diâmetro dos cabos. 01/02 ficam disponíveis para recuperação, mas não precisam ser repetidos.

Os bloqueios D atuais são rígidos, retidos por duas cintas de nylon. As cintas entram pelos canais previstos e são substituídas quando cortadas na manutenção. As travas curtas flexíveis antigas não estão no lote atual. Leia a sequência ilustrada antes de instalar a bandeja.

## O que esta revisão não comprova

Não houve nova impressão ou montagem física, ensaio de força, fadiga ou medição de tolerâncias da impressora. A elasticidade dos pinos dos berços, a variante inferior da tampa, as emendas coladas e a acomodação física das cintas continuam sujeitos à montagem real. Apresente as emendas a seco antes de colar; não force encaixes. Os componentes eletrônicos finais ainda não foram definidos/medidos, e esta revisão não certifica seu encaixe ou desempenho térmico/elétrico.

**O SD não foi escrito nesta etapa.** A verificação local/ZIP não substitui a conferência de leitura após copiar e remontar o cartão.
'''
(ROOT/'RELATORIO.md').write_text(text);(P/'REVISAO-FINAL-2026-10-15.md').write_text(text);(P/'verificacao/revisao-final-2026-10-15.json').write_text(json.dumps(report,indent=2)+'\n')
for n in ['auditoria-estatica.json','movimentos.json','acessorios.json','revisor-independente-evidencias.json','congruencia-lotes-v9.json','verificacao-cintas.json']:shutil.copy2(A/n,P/'verificacao'/n)
# Keep the historical review, while removing stale statements about the current print state.
f=P/'RELATORIO-REVISAO.md';t=f.read_text();t=t.replace('14/10/2026. O usuário','Projeto revisado em 14/10/2026; última conferência completa em 15/10/2026. O usuário').replace('Os dez G-codes inalterados preservam a auditoria anterior por identidade de conteúdo; os dois novos foram auditados e seus projetos reabertos/refatiados.','Todos os 12 G-codes foram novamente auditados e os 12 projetos reabertos/refatiados na revisão final de 15/10/2026, sem alterar os arquivos de impressão entregues.').replace('Deixe 02 terminar e atualize o cartão antes de iniciar 03.','01 e 02 já foram impressos; atualize o cartão antes de iniciar 03.')
t+='\nA [última revisão completa de 15/10/2026](REVISAO-FINAL-2026-10-15.md) registra a conferência final sem alteração dos arquivos técnicos.\n';f.write_text(t)
print(json.dumps(report))
