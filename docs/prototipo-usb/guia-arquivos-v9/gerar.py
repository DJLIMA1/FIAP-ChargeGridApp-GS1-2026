"""Guia visual dos lotes oficiais: renderização direta dos STL, sem alterar peças."""
from pathlib import Path
import json
import numpy as np
import trimesh
from PIL import Image, ImageDraw

OUT=Path(__file__).resolve().parent
BASE=OUT.parent/'ender3-pla-oficial-v9'
REF=OUT.parent/'cad-impressao-50-v1/renderizar.py'
ns={'__file__':str(REF)}
exec(REF.read_text().split('scene=trimesh.load',1)[0],ns)
render,font=ns['render'],ns['font']
jobs=[
 ('01CHAVE','Chaves das emendas',4,['Unem e alinham as metades da traseira','e da moldura. Usar junto da colagem.'],'JÁ IMPRESSO • removido do SD'),
 ('02TRSUP','Traseira superior',1,['Metade de cima da parte traseira.','Forma a carcaça traseira junto com 03.'],'JÁ IMPRESSO • removido do SD'),
 ('03TRINF7','Traseira inferior',1,['Metade de baixo da parte traseira.','Une-se a 02 com duas chaves de 01.'],''),
 ('04QDSUP','Moldura frontal superior',1,['Metade de cima do quadro da frente.','Une-se à metade inferior, arquivo 05.'],''),
 ('05QDINF8','Moldura frontal inferior',1,['Metade de baixo do quadro da frente.','Une-se a 04 com duas chaves de 01.'],''),
 ('06TAMPA','Tampa frontal',1,['Painel frontal externo, sugerido em branco.','Fica preso à moldura 04 + 05.'],''),
 ('07PTAMP','Travas da tampa: alto e meio',4,['Quatro travas v5, com 3 riscos na cabeça.','Prendem a tampa à moldura nesses pontos.'],''),
 ('08PTINF','Trava da tampa: ponto inferior',1,['Uma trava com 4 riscos, 0,25 mm mais longa.','Usar somente no ponto inferior da tampa.'],''),
 ('09PINO','Pinos de fechamento',4,['Quatro pinos que giram 90° para fechar.','Prendem a moldura frontal à traseira.'],''),
 ('10BERCO9','Bandeja e berços internos',3,['Uma bandeja removível e dois berços','genéricos: ESP32 e módulo de potência.'],''),
 ('11TRAVA9','Fixações internas',12,['2 pinos dos berços + 2 bloqueios rígidos D','+ 8 espaçadores. Os D usam cintas de nylon.'],''),
 ('12CABO','Saída e presilhas dos cabos',6,['2 metades do inserto + 4 meias presilhas.','Para dois cabos de aproximadamente 5 mm.'],'OPCIONAL • pasta CGFINAL/OPCIONAL'),
]

evidence=[]
for page in range(3):
    im=Image.new('RGB',(1560,1290),'#e5edf1');d=ImageDraw.Draw(im)
    d.text((40,25),'ChargeGrid • o que imprime cada arquivo',font=font(39),fill='#183746')
    d.text((42,81),f'Arquivos {page*4+1:02d}–{page*4+4:02d}  |  Geometria oficial v9  |  Ender-3 / PLA',font=font(25),fill='#415d6d')
    for j,(name,title,count,lines,badge) in enumerate(jobs[page*4:page*4+4]):
        x=30+(j%2)*765;y=135+(j//2)*545
        d.rounded_rectangle((x,y,x+735,y+525),radius=15,fill='#f0f4f7')
        d.text((x+22,y+18),name+'.gcode',font=font(31),fill='#126d7b')
        d.text((x+22,y+60),title,font=font(27),fill='#183746')
        mesh=trimesh.load(BASE/'modelos-fatiados'/(name+'.stl'),force='mesh')
        parts=list(mesh.split(only_watertight=False))
        assert len(parts)==count,(name,len(parts),count)
        evidence.append({'file':name+'.gcode','pieces':count,'source_stl':str(BASE/'modelos-fatiados'/(name+'.stl'))})
        colors=[np.array(c,float) for c in [(57,151,172),(95,171,184),(40,121,153),(135,184,190)]]
        pic=render([(m.triangles,colors[k%len(colors)]) for k,m in enumerate(parts)],(.55,-1,1.1),(691,300))
        im.paste(pic,(x+22,y+94))
        d.text((x+22,y+395),f'{count} '+('peça' if count==1 else 'peças')+' neste arquivo',font=font(22),fill='#126d7b')
        for k,line in enumerate(lines):d.text((x+22,y+430+k*28),line,font=font(23),fill='#183746')
        if badge:d.text((x+22,y+494),badge,font=font(19),fill='#8b5b19' if name=='12CABO' else '#236644')
    d.text((42,1244),'Vistas sem suportes e brim. Cada quadro tem escala própria; as cores servem para identificação.',font=font(22),fill='#415d6d')
    im.save(OUT/f'arquivos-{page*4+1:02d}-{page*4+4:02d}.png')

(OUT/'fontes.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
md=['# ChargeGrid — identificação dos arquivos v9','',
    '01CHAVE e 02TRSUP já foram impressos e retirados do SD. Os arquivos no cartão começam em 03TRINF7. 12CABO fica em CGFINAL/OPCIONAL. O número no começo determina a ordem; o 7, 8 ou 9 no fim do nome indica a revisão.','',
    'As imagens são renderizadas diretamente dos STL de lote oficiais. Cada quadro mostra todas as peças daquele G-code, sem suportes ou brim e em escala própria.','',
    '| Arquivo | Peças | Conteúdo / função |','|---|---:|---|']
for name,title,count,lines,badge in jobs:md.append(f'| {name}.gcode | {count} | **{title}.** '+ ' '.join(lines)+(f' {badge}.' if badge else '')+' |')
for page in range(3):md.extend(['',f'![Arquivos {page*4+1:02d} a {page*4+4:02d}](arquivos-{page*4+1:02d}-{page*4+4:02d}.png)'])
md.extend(['','Os dois bloqueios D do arquivo 11 precisam de duas cintas de nylon compradas. Os berços do arquivo 10 são genéricos; o encaixe dos módulos eletrônicos reais precisa ser conferido. Nenhum STL, perfil ou G-code foi alterado para gerar este guia.',''])
(OUT/'GUIA.md').write_text('\n'.join(md))
print(json.dumps({'pages':3,'jobs':len(jobs),'printed_parts':sum(j[2] for j in jobs),'production_files_changed':False}))
