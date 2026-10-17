"""从本仓库Release还原原始数据、训练产物和Qwen；不会重新训练需求模型。"""
from pathlib import Path
import argparse,json,os,subprocess,sys,shutil
from distribution_io import download,join_parts,restore_bundle,valid,configure_download_proxy

APP=Path(__file__).resolve().parent
REPO=APP.parent

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--data-only',action='store_true',help='仅还原数据和需求模型，不准备本地语言模型');parser.add_argument('--restore-only',action='store_true',help='还原并校验，不创建SQLite索引');parser.add_argument('--model',choices=['4b'],default='4b');parser.add_argument('--backend',choices=['Auto','CPU','Vulkan','CUDA'],default='Auto');args=parser.parse_args()
 if os.name=='nt' and REPO.drive.upper()=='C:':raise ValueError('请将仓库移至D盘等非C盘路径后再准备Demo')
 manifest=json.loads((REPO/'distribution/manifest.json').read_text(encoding='utf-8'))
 cache=APP/'runtime/downloads';cache.mkdir(parents=True,exist_ok=True)
 base=f"https://github.com/{manifest['repository']}/releases/download/{manifest['release_tag']}/"
 targets=[(REPO/entry['path'],entry) for entry in manifest['files']]
 if not all(valid(path,spec) for path,spec in targets):
  local_parts=[(REPO/'distribution/source'/entry['name'],entry) for entry in manifest['source_chunks']]
  if all(valid(path,spec) for path,spec in local_parts):bundle=join_parts(local_parts,cache/manifest['bundle']['name'],manifest['bundle'])
  else:
   configure_download_proxy()
   bundle=download(base+manifest['bundle']['name'],cache/manifest['bundle']['name'],manifest['bundle'])
  restore_bundle(bundle,REPO,manifest)
 else:print('VERIFIED_EXISTING_DATA_AND_MODELS',flush=True)
 if args.backend=='Auto':args.backend='CUDA' if shutil.which('nvidia-smi') else 'CPU'
 if not args.data_only and args.backend!='CUDA':
  configure_download_proxy()
  from portable_models import prepare_4b
  portable=json.loads((REPO/'distribution/portable-manifest.json').read_text(encoding='utf-8'))
  from aigc_config import MODEL_FILE,MODEL_BYTES,MODEL_SHA256,REVISION,REPOSITORY
  portable['model']={'name':MODEL_FILE,'bytes':MODEL_BYTES,'sha256':MODEL_SHA256,'revision':REVISION,'url':REPOSITORY+'/resolve/'+REVISION+'/'+MODEL_FILE}
  prepare_4b(portable,args.backend)
 if not args.data_only and args.backend=='CUDA':
  from portable_models import activate_cuda
  try:activate_cuda()
  except ValueError:
   subprocess.run([sys.executable,str(APP/'setup_local_aigc.py')],cwd=APP,check=True)
   activate_cuda()
 if not args.restore_only:subprocess.run([sys.executable,str(APP/'build_data.py')],cwd=APP,check=True)
 print('DEMO_PREPARED: 已还原全量原始Excel及训练产物，无需重新训练。',flush=True)
 if args.data_only:print('本次未准备Qwen；画像、航线等页面可用，生成新文案需要另行准备模型。',flush=True)

if __name__=='__main__':main()
