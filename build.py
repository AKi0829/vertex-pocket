"""Build standalone APK with official Android build tools; no Gradle required."""
from pathlib import Path
import subprocess, zipfile, os
ROOT=Path(__file__).resolve().parent
TOOLS=ROOT/'tools'/'build-tools'/'android-15'
ANDROID=ROOT/'tools'/'platform'/'android-35'/'android.jar'
JAVA=Path(os.environ.get('JAVA_HOME',r'C:\Program Files\Java\jdk-24'))/'bin'
BUILD=ROOT/'build'
BUILD.mkdir(exist_ok=True)
(BUILD/'classes').mkdir(exist_ok=True)
def run(*args):
    subprocess.run([str(x) for x in args],cwd=ROOT,check=True)
run(TOOLS/'aapt2.exe','link','-I',ANDROID,'--manifest',ROOT/'AndroidManifest.xml','-o',BUILD/'base.apk')
sources=list((ROOT/'src').rglob('*.java'))
run(JAVA/'javac.exe','-encoding','UTF-8','--release','8','-classpath',ANDROID,'-d',BUILD/'classes',*sources)
classes=list((BUILD/'classes').rglob('*.class'))
run(JAVA/'java.exe','-cp',TOOLS/'lib'/'d8.jar','com.android.tools.r8.D8','--lib',ANDROID,'--min-api','26','--output',BUILD,*classes)
with zipfile.ZipFile(BUILD/'base.apk','a',zipfile.ZIP_DEFLATED) as z:
    z.write(BUILD/'classes.dex','classes.dex')
run(TOOLS/'zipalign.exe','-f','4',BUILD/'base.apk',BUILD/'aligned.apk')
keystore=ROOT/'signing-key.p12'
if not keystore.exists():
    run(JAVA/'keytool.exe','-genkeypair','-keystore',keystore,'-storepass','local-build-only','-keypass','local-build-only','-alias','pocket','-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=Vertex Pocket Local Build')
run(JAVA/'java.exe','-jar',TOOLS/'lib'/'apksigner.jar','sign','--ks',keystore,'--ks-pass','pass:local-build-only','--out',ROOT/'VertexPocket-1.0.apk',BUILD/'aligned.apk')
run(JAVA/'java.exe','-jar',TOOLS/'lib'/'apksigner.jar','verify','--verbose',ROOT/'VertexPocket-1.0.apk')
print('APK:',ROOT/'VertexPocket-1.0.apk')
