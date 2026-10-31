"""Build a Windows single-file executable, keeping dependencies inside this folder."""
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent
environment = {**os.environ, 'PYTHONPATH': str(root / '_deps')}
subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', '--onefile', '--windowed',
                '--name', 'VertexPocketPC', '--distpath', str(root / 'dist'), '--workpath', str(root / 'build'),
                '--specpath', str(root), '--paths', str(root / '_deps'), str(root / 'app.py')], cwd=root, env=environment, check=True)
print(root / 'dist' / 'VertexPocketPC.exe')
