"""在全新D盘临时目录还原完整数据和需求模型、重建索引并检查网站。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import argparse,json,os,shutil,socket,subprocess,sys,time,urllib.request

REPO=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(REPO/'航旅智策应用'))
from distribution_io import restore_bundle

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--temporary-root',type=Path,required=True);args=parser.parse_args()
 temp_root=args.temporary_root.resolve();temp_root.mkdir(parents=True,exist_ok=True)
 manifest=json.loads((REPO/'distribution/manifest.json').read_text(encoding='utf-8'))
 with TemporaryDirectory(prefix='portable-demo-',dir=temp_root) as temporary:
  root=Path(temporary).resolve();assert root.is_relative_to(temp_root)
  app=root/'航旅智策应用';shutil.copytree(REPO/'航旅智策应用',app,ignore=shutil.ignore_patterns('runtime','__pycache__','.venv'))
  restore_bundle(args.bundle,root,manifest)
  environment=os.environ.copy();environment.update(PYTHONDONTWRITEBYTECODE='1',PYTHONIOENCODING='utf-8',TEMP=str(root),TMP=str(root),TMPDIR=str(root))
  subprocess.run([sys.executable,str(app/'build_data.py')],cwd=app,env=environment,check=True)
  with socket.socket() as listener:listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
  log_path=root/'server-check.log'
  with log_path.open('wb') as log:
   process=subprocess.Popen([sys.executable,str(app/'server.py'),'--port',str(port)],cwd=app,env=environment,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
  def rpc(path,body=None):
   request=urllib.request.Request(f'http://127.0.0.1:{port}'+path,data=json.dumps(body).encode() if body is not None else None,headers={'Content-Type':'application/json'})
   with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
  try:
   for _ in range(120):
    if process.poll() is not None:raise RuntimeError(log_path.read_text(encoding='utf-8'))
    try:
     health=rpc('/api/health');break
    except OSError:time.sleep(.5)
   else:raise RuntimeError('Fresh demo did not become ready')
   assert health['status']=='ok'
   meta=rpc('/api/mkt/meta');assert meta['report']['users']==10000
   audience=rpc('/api/mkt/insights',{'holiday':'national','limit':1});assert len(audience['audience'])==1
   assert audience['model']!='未训练'
   with urllib.request.urlopen(f'http://127.0.0.1:{port}/',timeout=30) as response:assert response.status==200
   result={'status':'passed','fresh_directory':True,'raw_workbooks':3,'trained_model_restored':True,'users':meta['report']['users'],'sqlite_rebuilt':True,'homepage':200,'audience_prediction':'passed','language_model_hardware_test':'已有开发机先前完成；本项只验证数据与需求模型的全新还原'}
   destination=temp_root/'portable-restore-results.json';destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)
  finally:
   process.terminate()
   try:process.wait(timeout=15)
   except subprocess.TimeoutExpired:process.kill();process.wait(timeout=15)

if __name__=='__main__':main()
