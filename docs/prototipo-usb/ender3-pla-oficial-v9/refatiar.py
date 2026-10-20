"""Usage: python3 refatiar.py /path/to/PrusaSlicer [output_directory]. Uses embedded profiles."""
from pathlib import Path
import subprocess,sys
root=Path(__file__).resolve().parent
out=Path(sys.argv[2]) if len(sys.argv)>2 else root/'refatiado'
out.mkdir(parents=True,exist_ok=True)
for project in sorted((root/'projetos').glob('*.3mf')):
    subprocess.run([sys.argv[1],'--threads','4','--export-gcode','--output',str(out/(project.stem+'.gcode')),str(project)],check=True)
