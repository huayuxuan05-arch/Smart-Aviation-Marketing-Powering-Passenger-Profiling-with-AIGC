"""由GitHub Actions组装已上传数据，下载固定Qwen量化并制作Release资产。"""
from pathlib import Path
import base64,hashlib,json,os,sys,time,urllib.request,urllib.error
from concurrent.futures import ThreadPoolExecutor

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'航旅智策应用'))
from distribution_io import download,join_parts,sha256

def source_part(repository,spec):
 local=ROOT/'distribution/source'/spec['name']
 if local.exists():return local,spec
 local=ROOT/'release-source-cache'/spec['name'];local.parent.mkdir(exist_ok=True)
 if local.exists() and local.stat().st_size==spec['bytes'] and sha256(local)==spec['sha256']:return local,spec
 headers={'User-Agent':'AeroLens-release-builder','Accept':'application/vnd.github+json'}
 token=os.environ.get('GH_TOKEN')
 if token:headers['Authorization']='Bearer '+token
 url=f"https://api.github.com/repos/{repository}/git/blobs/{spec['git_blob_sha']}"
 deadline=time.monotonic()+45*60
 while True:
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:data=json.load(response)
   raw=base64.b64decode(data['content'])
   if data['sha']!=spec['git_blob_sha'] or len(raw)!=spec['bytes'] or hashlib.sha256(raw).hexdigest()!=spec['sha256']:raise ValueError('源分卷校验失败: '+spec['name'])
   local.write_bytes(raw);print('VERIFIED_SOURCE',spec['name'],flush=True);return local,spec
  except urllib.error.HTTPError as error:
   if error.code not in (404,403,429,500,502,503,504):raise
  except (TimeoutError,urllib.error.URLError):pass
  if time.monotonic()>deadline:raise TimeoutError('等待上传分卷超时: '+spec['name'])
  time.sleep(30)

def prepare_data(manifest,out):
 # 已发布时优先复用Release；首次发布从本仓库的临时Git Blob读取，不将大文件加入提交历史。
 bundle=manifest['bundle'];url=f"https://github.com/{manifest['repository']}/releases/download/{manifest['release_tag']}/{bundle['name']}"
 try:return download(url,out/bundle['name'],bundle)
 except Exception:pass
 with ThreadPoolExecutor(max_workers=6) as pool:
  parts=list(pool.map(lambda spec:source_part(manifest['repository'],spec),manifest['source_chunks']))
 return join_parts(parts,out/bundle['name'],bundle)

def main():
 manifest=json.loads((ROOT/'distribution/manifest.json').read_text(encoding='utf-8'))
 out=ROOT/'release-assets';out.mkdir(exist_ok=True)
 model=manifest['model'];temp=out.parent/'model-download'/model['name']
 with ThreadPoolExecutor(max_workers=2) as pool:
  data=pool.submit(prepare_data,manifest,out)
  weight=pool.submit(download,model['url'],temp,model)
  data.result();weight.result()
 model_parts=[]
 with temp.open('rb') as source:
  index=0
  while block:=source.read(1024**3):
   index+=1;name=f"{model['name']}.part-{index:03}";path=out/name
   path.write_bytes(block);model_parts.append({'name':name,'bytes':len(block),'sha256':hashlib.sha256(block).hexdigest()})
 temp.unlink()  # 仅清理本脚本创建并校验过的工作文件，减少Runner磁盘占用。
 release={**manifest,'model_parts':model_parts,'distribution':'GitHub Release；原始工作簿按字节保留；不含用户活动数据库'}
 (out/'release-manifest.json').write_text(json.dumps(release,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 (out/'LICENSE-Qwen3.5.txt').write_bytes((ROOT/'distribution/LICENSE-Qwen3.5.txt').read_bytes())
 (out/'MODEL-NOTICE.txt').write_bytes((ROOT/'distribution/MODEL-NOTICE.txt').read_bytes())
 print('RELEASE_ASSETS_READY',manifest['release_tag'],len(model_parts),'model parts',flush=True)

if __name__=='__main__':main()
