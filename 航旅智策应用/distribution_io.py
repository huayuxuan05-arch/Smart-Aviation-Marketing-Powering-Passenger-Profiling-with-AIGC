"""发布包的流式下载、分卷合并、校验和安全还原。仅使用Python标准库。"""
from pathlib import Path
import hashlib,json,os,shutil,time,urllib.request,zipfile
import ssl
from urllib.parse import urlsplit

def configure_download_proxy():
 proxy=os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
 if not proxy or urlsplit(proxy).scheme not in ('http','https') or not urlsplit(proxy).hostname:raise ValueError('请先配置HTTPS_PROXY/https_proxy，下载不会绕过代理')
 import certifi
 context=ssl.create_default_context(cafile=os.environ.get('REQUESTS_CA_BUNDLE') or certifi.where())
 urllib.request.install_opener(urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy}),urllib.request.HTTPSHandler(context=context)))

def sha256(path):
 with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def valid(path,spec):
 path=Path(path)
 return path.is_file() and path.stat().st_size==spec['bytes'] and sha256(path)==spec['sha256']

def download(url,target,spec):
 target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
 if target.exists():
  if not valid(target,spec):raise ValueError('已有文件校验失败，未覆盖: '+str(target))
  print('VERIFIED_CACHE',target.name,flush=True);return target
 part=target.with_suffix(target.suffix+'.downloading')
 for attempt in range(5):
  try:
   offset=part.stat().st_size if part.exists() else 0
   if offset>spec['bytes']:raise ValueError('断点文件长度超过预期')
   if offset==spec['bytes']:break
   headers={'User-Agent':'AeroLens-demo-bootstrap'}
   if offset:headers['Range']=f'bytes={offset}-'
   with urllib.request.urlopen(urllib.request.Request(url,headers=headers),timeout=60) as response:
    resume=offset>0 and response.status==206
    if resume and not response.headers.get('Content-Range','').startswith(f'bytes {offset}-'):raise ValueError('断点范围不匹配')
    done=offset if resume else 0;last=time.monotonic()
    with part.open('ab' if resume else 'wb') as stream:
     while block:=response.read(4*1024**2):
      stream.write(block);done+=len(block)
      if done>spec['bytes']:raise ValueError('下载大小超过预期')
      if time.monotonic()-last>10:print('DOWNLOAD',target.name,round(done/spec['bytes']*100,1),'%',flush=True);last=time.monotonic()
   if part.stat().st_size!=spec['bytes']:raise ValueError('下载不完整')
   break
  except Exception:
   if attempt==4:raise
   time.sleep(min(2**attempt,8))
 if not valid(part,spec):raise ValueError('下载SHA256校验失败: '+target.name)
 part.replace(target);print('VERIFIED',target.name,flush=True);return target

def join_parts(parts,target,spec):
 target=Path(target)
 if target.exists():
  if not valid(target,spec):raise ValueError('已有合并文件校验失败，未覆盖: '+target.name)
  return target
 target.parent.mkdir(parents=True,exist_ok=True);temp=target.with_suffix(target.suffix+'.joining')
 with temp.open('wb') as output:
  for path,record in parts:
   if not valid(path,record):raise ValueError('分卷校验失败: '+str(path))
   with Path(path).open('rb') as source:shutil.copyfileobj(source,output,4*1024**2)
 if not valid(temp,spec):raise ValueError('完整文件SHA256校验失败')
 temp.replace(target);return target

def restore_bundle(bundle,root,manifest):
 root=Path(root).resolve();stage=root/'航旅智策应用/runtime/downloads/restore-stage';stage.mkdir(parents=True,exist_ok=True)
 if not valid(bundle,manifest['bundle']):raise ValueError('发布包SHA256校验失败')
 records={entry['path']:entry for entry in manifest['files']}
 if len(records)!=len(manifest['files']):raise ValueError('文件清单重复')
 with zipfile.ZipFile(bundle) as archive:
  if len(archive.infolist())!=len(records) or set(archive.namelist())!=set(records):raise ValueError('发布包文件清单不匹配')
  for entry in archive.infolist():
   target=(root/entry.filename).resolve();record=records[entry.filename]
   if not target.is_relative_to(root) or entry.is_dir() or '\\' in entry.filename or entry.file_size!=record['bytes']:raise ValueError('发布包路径或大小不合法')
   if target.exists() and not valid(target,record):raise ValueError('本地已有不同文件，未覆盖: '+entry.filename)
  staged=[]
  for entry in archive.infolist():
   target=root/entry.filename;record=records[entry.filename]
   if target.exists():continue
   temp=stage/entry.filename;temp.parent.mkdir(parents=True,exist_ok=True)
   with archive.open(entry) as source,temp.open('wb') as output:shutil.copyfileobj(source,output,4*1024**2)
   if not valid(temp,record):raise ValueError('解压后校验失败: '+entry.filename)
   staged.append((temp,target))
  for temp,target in staged:target.parent.mkdir(parents=True,exist_ok=True);temp.replace(target)
 print('DATA_AND_TRAINED_MODELS_READY',len(records),flush=True)

def load_json(url):
 with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'AeroLens-demo-bootstrap'}),timeout=60) as response:return json.load(response)
