"""下载固定版本Qwen3.5-9B量化权重与CUDA运行时；不读取旅客数据。"""
import urllib.request,json,hashlib,zipfile,time
from concurrent.futures import ThreadPoolExecutor
from aigc_config import *

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def download(spec):
 name,url,expected,size=spec;target=ROOT/name;temp=target.with_suffix(target.suffix+'.downloading')
 if target.exists():
  if target.stat().st_size!=size or digest(target)!=expected:raise ValueError(name+'缓存校验失败')
  print('VERIFIED_CACHE',name,flush=True);return target
 for attempt in range(5):
  try:
   offset=temp.stat().st_size if temp.exists() else 0
   if offset==size:break
   headers={'User-Agent':'AeroLens-local-demo'}
   if offset:headers['Range']=f'bytes={offset}-'
   with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:
    resume=offset>0 and response.status==206
    if resume and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('断点范围不匹配')
    done=offset if resume else 0;last=time.monotonic()
    with temp.open('ab' if resume else 'wb') as out:
     while block:=response.read(4*1024*1024):
      out.write(block);done+=len(block)
      if time.monotonic()-last>5:print('DOWNLOAD',name,round(done/size*100,1),'%',round(done/1024**2),'MiB',flush=True);last=time.monotonic()
   if temp.stat().st_size!=size:raise ValueError('文件长度不完整')
   break
  except Exception as e:
   if attempt==4:raise
   print('RETRY',name,attempt+1,type(e).__name__,flush=True);time.sleep(min(2**attempt,8))
 if temp.stat().st_size!=size or digest(temp)!=expected:raise ValueError(name+'SHA256校验失败')
 temp.replace(target);print('VERIFIED',name,expected,flush=True);return target

def main():
 ROOT.mkdir(parents=True,exist_ok=True)
 with ThreadPoolExecutor(max_workers=3) as pool:files=list(pool.map(download,FILES))
 dest=ROOT/RUNTIME_DIR
 for archive in files[:2]:
  with zipfile.ZipFile(archive) as z:
   if any(not (dest/p).resolve().is_relative_to(dest.resolve()) for p in z.namelist()):raise ValueError('压缩包路径不合法')
   z.extractall(dest)
 old=ROOT/'model_manifest.json'
 if old.exists() and 'Qwen2.5' in old.read_text(encoding='utf-8'):
  (ROOT/'model_manifest_qwen2.5.json').write_bytes(old.read_bytes())
 manifest={'model':MODEL_NAME,'base_repository':BASE_REPOSITORY,'repository':REPOSITORY,'quantizer':'Unsloth（基于官方Qwen权重的GGUF量化）','revision':REVISION,'sha256':MODEL_SHA256,'bytes':MODEL_BYTES,'license':'Apache-2.0','runtime':'llama.cpp '+RUNTIME_VERSION+' CUDA13.4','runtime_directory':RUNTIME_DIR,'runtime_sha256':{f[0]:f[2] for f in FILES[:2]},'context':8192,'parallel':1,'thinking':False,'mode':'本地GPU推理；模型未经本旅客数据微调；需求模型另用10000用户训练'}
 temp=ROOT/'model_manifest.json.tmp';temp.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(old)
 print('LOCAL_AIGC_READY',MODEL_NAME,flush=True)

if __name__=='__main__':main()
