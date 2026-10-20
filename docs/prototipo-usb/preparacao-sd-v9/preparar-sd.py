from pathlib import Path
import hashlib,json,shutil,zipfile,re
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent;P=BASE/'ender3-pla-oficial-v9';OUT=ROOT/'CONTEUDO-SD';DOC=OUT/'CGDOC9'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert not OUT.exists(),'Staging already exists; inspect before replacing'
(OUT/'CGFINAL/OPCIONAL').mkdir(parents=True);DOC.mkdir()
jobs=json.loads((P/'ordem-impressao.json').read_text());audit=json.loads((P/'verificacao/auditoria-gcode.json').read_text());times={x['file']:x for x in audit['files']}
check=json.loads((ROOT/'compatibilidade-e-correcoes.json').read_text());assert check['all_v7_v8_v9_corrections_present'] and check['loaded_tray_clears_original_upper_rear']
for job in jobs:
 target=OUT/'CGFINAL'/('OPCIONAL' if job['optional'] else '')/(job['id']+'.gcode');shutil.copy2(P/'gcode'/target.name,target)
 assert h(target)==h(P/'gcode'/target.name)
for name in ['LEIA-PRIMEIRO.md','RELATORIO-REVISAO.md','REVISAO-INDEPENDENTE.md','montagem-bloqueios-v9.png','montagem-travas.png','todas-as-31-pecas.png']:
 shutil.copy2(P/name,DOC/name)
shutil.copy2(P/'verificacao/estimativas.csv',DOC/'TEMPOS.csv')
shutil.copy2(ROOT/'compatibilidade-e-correcoes.json',DOC/'COMPATIBILIDADE.json')
shutil.copy2(BASE/'ChargeGrid-Ender3-PLA-OFICIAL-v9.zip',DOC/'ChargeGrid-OFICIAL-v9.zip')
text='''CHARGEGRID V9 - ENDER-3 ORIGINAL - PLA - BICO 0,4 MM

01CHAVE e 02TRSUP ja foram impressos: NAO PRECISA REIMPRIMIR.
Os arquivos dessas duas pecas sao identicos aos enviados anteriormente.
As pecas atuais foram verificadas digitalmente com essas versoes antigas.

PROXIMA IMPRESSAO: CGFINAL/03TRINF7.gcode
Imprima um arquivo por vez. Remova a peca e prepare a mesa entre arquivos.
Nao altere a escala nem o perfil. G-codes ja incluem os suportes indicados.

ORDEM:
01CHAVE.gcode - chaves - JA IMPRESSO, preservado para recuperacao
02TRSUP.gcode - traseira superior - JA IMPRESSO, preservado para recuperacao
'''
for j in jobs:
 if j['id'] in ['01CHAVE','02TRSUP']:continue
 x=times[j['id']+'.gcode'];text+=j['id']+'.gcode - '+j['label']+' - '+x['time_slicer']+'\n'
text+='''
12CABO fica em CGFINAL/OPCIONAL e so serve para dois cabos de aproximadamente 5mm.

RETENCAO INTERNA ATUAL:
10BERCO9 e 11TRAVA9 devem ser usados juntos.
Dois bloqueios D rigidos substituem as travas curtas flexiveis antigas.
Usar duas cintas de nylon 100x2,5mm, espessura de referencia 1,0mm.
Referencia dimensional e sequencia ilustrada: CGDOC9/LEIA-PRIMEIRO.md.
Apertar apenas a mao; para manutencao, cortar as fivelas e usar cintas novas.

Versoes antigas 03TRINF, 05QDINF, 10BERCO, 11TRAVA, 10BERCO8 e 11TRAVA8
nao devem permanecer junto dos arquivos atuais no cartao.
00TESTE e os outros testes antigos nao fazem parte desta fila de impressao.

A revisao digital passou. Montagem completa e resistencia fisica ainda
precisam ser conferidas na impressao real; apresentar emendas a seco antes de colar.
Documentos e pacote completo de recuperacao: CGDOC9 (abrir no computador).
'''
import unicodedata
(OUT/'COMECE.txt').write_text(unicodedata.normalize('NFKD',text).encode('ascii','ignore').decode())
(DOC/'ORDEM.txt').write_bytes((OUT/'COMECE.txt').read_bytes())
readme='''# Conteúdo pronto para o SD — ChargeGrid v9

**Preparado no Mac; ainda não copiado ao cartão.** O usuário confirmou que as peças já impressas são 01CHAVE e 02TRSUP. Elas permanecem idênticas aos arquivos registrados na entrega ao SD v6. A próxima impressão é 03TRINF7.

## Estrutura a copiar

Copiar o conteúdo de CONTEUDO-SD para a raiz do cartão, preservando:

- CGFINAL/: arquivos 01–11 em ordem. 01/02 ficam disponíveis para recuperação, mas devem ser pulados porque já foram impressos.
- CGFINAL/OPCIONAL/12CABO.gcode: só após conferir os cabos reais.
- CGDOC9/: guia, relatório, parecer independente, imagens, estimativas, hashes e ZIP completo de recuperação.
- COMECE.txt: orientação atualizada.

Não é necessário refatiar. Não importar STL nem iniciar arquivos de teste antigos. Os nomes dos G-codes têm até oito caracteres antes da extensão, mantendo os nomes das versões revisadas.

## Conferência feita nesta preparação

Foram relidos os 161 arquivos do manifesto oficial e o ZIP completo. Os G-codes finais 10/11 coincidem com os hashes conferidos pelo revisor independente. As correções de 03 e 05 são as versões verificadas anteriormente. As quatro travas padrão da tampa continuam idênticas ao STL v5 aprovado.

A montagem foi reconstruída com as quatro chaves e a traseira superior do pacote v6, combinadas com as outras peças v9. Passaram 120 pares que envolvem essas peças antigas, 196 posições de entrada das chaves e a retirada da bandeja carregada. Também foi conferido o envelope das chaves com espessura fatiada de 2,88 mm. Os oito arquivos de 01/02 (G-code, STL de lote, INI e 3MF) coincidem com a v6; os G-codes coincidem com o recibo de leitura do SD.

Isso confirma a compatibilidade digital com as versões já impressas, sem exigir sua reimpressão. O encaixe físico pode variar com a impressão: apresentar as emendas a seco antes de colar. Os novos bloqueios rígidos usam duas cintas; pinos dos berços, encaixe inferior da tampa e conjunto completo ainda dependem de ensaio físico.

## Quando o SD estiver disponível

1. Confirmar que nenhuma impressão está em andamento e identificar o cartão pelo volume/UUID; não reutilizar um identificador de disco antigo.
2. Fazer backup do conteúdo ChargeGrid existente. Substituir a pasta CGFINAL completa para não deixar G-codes antigos misturados; preservar arquivos não relacionados. Atualizar COMECE.txt e substituir a documentação antiga pela CGDOC9.
3. Copiar os arquivos e conferir com `python3 verificar-copia.py /Volumes/NOME_DO_CARTAO`, executado a partir desta pasta ou usando caminho absoluto do script.
4. Desmontar/remontar e repetir a leitura por hash. Devido às divergências observadas anteriormente nesse cartão/leitor, repetir em dois ciclos antes de ejetar com segurança. O teste local não comprova a integridade da próxima cópia.

Nenhuma dessas operações foi feita no cartão nesta etapa. O script verificar-copia.py é somente de leitura e também detecta G-codes antigos extras em CGFINAL.
'''
(ROOT/'LEIA-ANTES-DA-COPIA.md').write_text(readme)
files={str(f.relative_to(OUT)):h(f) for f in sorted(OUT.rglob('*')) if f.is_file()}
manifest={'release':'v9','algorithm':'sha256','files':files,'already_printed':['01CHAVE.gcode','02TRSUP.gcode'],'next_print':'03TRINF7.gcode','card_written':False}
(DOC/'MANIFESTO-SD.json').write_text(json.dumps(manifest,indent=2)+'\n');(ROOT/'manifesto-esperado.json').write_bytes((DOC/'MANIFESTO-SD.json').read_bytes())
zip_path=BASE/'ChargeGrid-SD-PRONTO-v9.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for f in sorted(OUT.rglob('*')):
  if f.is_file():z.write(f,'CONTEUDO-SD/'+str(f.relative_to(OUT)))
 z.write(ROOT/'LEIA-ANTES-DA-COPIA.md','LEIA-ANTES-DA-COPIA.md')
with zipfile.ZipFile(zip_path) as z:
 assert z.testzip() is None
 for n,d in files.items():assert hashlib.sha256(z.read('CONTEUDO-SD/'+n)).hexdigest()==d
receipt={'prepared_release':'v9','prepared_files':len(files)+1,'content_bytes':sum(f.stat().st_size for f in OUT.rglob('*') if f.is_file()),'zip_sha256':h(zip_path),'zip_verified':True,'local_readback_passed':True,'sd_written':False,'user_confirmed_printed':['01CHAVE','02TRSUP']}
(ROOT/'recibo-preparacao.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))

# Finalize current copy instructions and include the read-only verifier.
import subprocess,sys
subprocess.run([sys.executable,str(ROOT/"fechar.py")],check=True)
