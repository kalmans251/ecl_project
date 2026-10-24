"""Rebuild the checked-in browser bundle with Emscripten 3.1.64 (emcc on PATH)."""
from pathlib import Path
import argparse,subprocess,shutil,hashlib,json,tarfile,io,base64
p=argparse.ArgumentParser();p.add_argument('--source',type=Path);args=p.parse_args()
root=Path(__file__).resolve().parents[1];out=root/'src/main/resources/static/codec2';out.mkdir(parents=True,exist_ok=True)
rev='3e347e0b70fc72af9357fbbd32b10a125321d6c5'
source=args.source or root/'target/browser-codec-source'
if not source.exists():subprocess.run(['git','clone','https://github.com/meshtastic/codec2.git',str(source)],check=True)
subprocess.run(['git','-C',str(source),'checkout','--detach',rev],check=True)
if subprocess.check_output(['git','-C',str(source),'status','--porcelain']).strip():raise SystemExit('Codec2 source must be clean')
version=subprocess.check_output(['emcc','--version'],text=True).splitlines()[0]
if '3.1.64' not in version:raise SystemExit('Use Emscripten 3.1.64 for reproducible builds')
cmd=['emcc',*[str(f) for f in sorted((source/'src').glob('*.c'))],'-I'+str(source/'src'),'-O2','-DCODEC2_MODE_EN_DEFAULT=0','-DCODEC2_MODE_2400_EN=1','-sMODULARIZE=1','-sEXPORT_NAME=Codec2Wasm','-sSINGLE_FILE=1','-sENVIRONMENT=worker,node','-sFILESYSTEM=0','-sALLOW_MEMORY_GROWTH=1','-sEXPORTED_FUNCTIONS=["_malloc","_free","_codec2_create","_codec2_destroy","_codec2_encode","_codec2_decode","_codec2_samples_per_frame","_codec2_bits_per_frame"]','-o',str(out/'codec2.js')]
subprocess.run(cmd,check=True)
shutil.copyfile(source/'LICENSE',out/'LICENSE.txt')
# Exact corresponding source, served with the binary, including its Git history-independent build inputs.
buffer=io.BytesIO()
with tarfile.open(fileobj=buffer,mode='w:gz') as archive:
 for item in sorted((source/'src').rglob('*')):
  if item.is_file():archive.add(item,arcname='codec2/src/'+str(item.relative_to(source/'src')))
 archive.add(source/'LICENSE',arcname='codec2/LICENSE')
 archive.add(Path(__file__),arcname='build-codec-browser.py')
(out/'source.tar.gz.base64.txt').write_text(base64.b64encode(buffer.getvalue()).decode()+'\n')
(out/'manifest.json').write_text(json.dumps(dict(codec2_revision=rev,emscripten='3.1.64',mode=2400,sha256=hashlib.sha256((out/'codec2.js').read_bytes()).hexdigest()),indent=2)+'\n')
