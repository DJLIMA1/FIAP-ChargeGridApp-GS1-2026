"""Confere leitura persistente e ejeta somente o cartão identificado pelo UUID."""
import json, subprocess, sys
from transferir import CARD, RECEIPT, identify, verify

mode = sys.argv[1]
receipt = json.loads(RECEIPT.read_text())
identity = identify()
if mode == 'eject':
    labels = {r['label'] for r in receipt['readbacks'] if r['passed']}
    assert {'immediate','remount_1','remount_2'} <= labels
    subprocess.run(['diskutil','eject',identity['ParentWholeDisk']],check=True)
    assert not CARD.exists()
    receipt['phase']='verified_twice_after_remount_and_ejected'
    receipt['safely_ejected']=True
else:
    assert mode in ['remount_1','remount_2']
    subprocess.run(['sync'],check=True)
    subprocess.run(['diskutil','unmount',str(CARD)],check=True)
    subprocess.run(['diskutil','mount',identity['DeviceIdentifier']],check=True)
    identity = identify()
    result = verify(CARD)
    receipt['readbacks'].append({'label':mode,'device':identity,**result})
    receipt['phase']=mode+'_passed'
RECEIPT.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'phase':receipt['phase'],'sd_written':True,'next_print':'CGFINAL/03TRINF7.gcode'}))
