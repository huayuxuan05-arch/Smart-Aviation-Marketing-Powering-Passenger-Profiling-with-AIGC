"""将用户授权发布的原始Excel及训练产物打包；活动数据库不进入发布包。"""
from pathlib import Path
import argparse,hashlib,json,zipfile

REPO=Path(__file__).resolve().parents[1]
REPOSITORY='huayuxuan05-arch/Smart-Aviation-Marketing-Powering-Passenger-Profiling-with-AIGC'
TAG='demo-2026-10-12'

def digest(path):
 with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path,required=True);args=parser.parse_args()
 source=args.source_root.resolve();app=source/'航旅智策应用';out=app/'runtime/distribution';out.mkdir(parents=True,exist_ok=True)
 report=json.loads((app/'runtime/models/artifact_manifest.json').read_text(encoding='utf-8'))
 files=[]
 for name,expected in report['source_sha256'].items():
  path=source/'数据集'/name
  if digest(path)!=expected:raise ValueError('原始来源指纹不符: '+name)
  files.append((path,'数据集/'+name))
 for name,spec in report['artifacts'].items():
  path=app/'runtime/models'/name
  if path.stat().st_size!=spec['bytes'] or digest(path)!=spec['sha256']:raise ValueError('训练产物校验失败: '+name)
  files.append((path,'航旅智策应用/runtime/models/'+name))
 files.append((app/'runtime/models/artifact_manifest.json','航旅智策应用/runtime/models/artifact_manifest.json'))
 package=out/'demo-data-models.zip';file_records=[]
 with zipfile.ZipFile(package,'w',compression=zipfile.ZIP_STORED,allowZip64=True) as archive:
  for path,name in files:
   archive.write(path,name);file_records.append({'path':name,'bytes':path.stat().st_size,'sha256':digest(path)})
 chunks=[]
 with package.open('rb') as stream:
  index=0
  while block:=stream.read(4*1024**2):
   index+=1;name=f'source-{index:03}.bin';target=out/name;target.write_bytes(block)
   chunks.append({'name':name,'bytes':len(block),'sha256':hashlib.sha256(block).hexdigest(),'git_blob_sha':hashlib.sha1(b'blob '+str(len(block)).encode()+b'\0'+block).hexdigest()})
 manifest={'version':1,'repository':REPOSITORY,'release_tag':TAG,'data_version':'DAILY_SYN_2024_V2_SUBSET_10K','bundle':{'name':package.name,'bytes':package.stat().st_size,'sha256':digest(package)},'files':file_records,'source_chunks':chunks,'model':{'name':'Qwen3.5-9B-Q4_K_M.gguf','bytes':5680522464,'sha256':'03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8','revision':'3885219b6810b007914f3a7950a8d1b469d598a5','url':'https://huggingface.co/unsloth/Qwen3.5-9B-GGUF/resolve/3885219b6810b007914f3a7950a8d1b469d598a5/Qwen3.5-9B-Q4_K_M.gguf','license':'Apache-2.0'}}
 target=REPO/'distribution/manifest.json';target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'bundle_bytes':manifest['bundle']['bytes'],'source_chunks':len(chunks),'directory':str(out)},ensure_ascii=False))

if __name__=='__main__':main()
