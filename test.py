from pathlib import Path
import subprocess
r=Path(__file__).resolve().parent
j=Path(r'C:\Program Files\Java\jdk-24\bin')
out=r/'build'/'test-classes';out.mkdir(parents=True,exist_ok=True)
jar=r/'tools'/'json.jar'
sources=[r/'src'/'local'/'vertex'/'pocket'/s for s in ['GoogleAuth.java','Gateway.java']]+[r/'tests'/'GatewayTest.java']
subprocess.run([str(j/'javac.exe'),'-encoding','UTF-8','--release','8','-cp',str(jar),'-d',str(out),*[str(s) for s in sources]],check=True)
subprocess.run([str(j/'java.exe'),'-cp',str(out)+';'+str(jar),'local.vertex.pocket.GatewayTest'],check=True)
