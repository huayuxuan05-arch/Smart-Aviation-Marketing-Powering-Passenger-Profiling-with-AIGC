"""Package authorized 4B weights/runtime and original data, never active user data."""
from pathlib import Path
import argparse,hashlib,json,shutil

ROOT=Path(__file__).resolve().parents[1]
TAG='portable-2026-10-16'
MODEL={'name':'Qwen3-4B-Q4_K_M.gguf','bytes':2497280256,'sha256':'7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5',
    'revision':'bc640142c66e1fdd12af0bd68f40445458f3869b','repository':'https://huggingface.co/Qwen/Qwen3-4B-GGUF','license':'Apache-2.0'}
RUNTIMES={'CPU':{'name':'llama-b11371-bin-win-cpu-x64.zip','bytes':19352488,'sha256':'085d650f1b4b0725a32c2421b970da5c5d2f769202cd16f89591ac9dcce835c6'},
    'Vulkan':{'name':'llama-b11371-bin-win-vulkan-x64.zip','bytes':33281583,'sha256':'dfc666fdf3137595e7d440b994bed0fa1f1dc726099685c1a75291c4bab2013f'}}

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def checked(path,spec):
    if path.stat().st_size!=spec['bytes'] or digest(path)!=spec['sha256']:raise ValueError('Asset fingerprint mismatch: '+path.name)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True);parser.add_argument('--runtime-directory',type=Path,required=True);args=parser.parse_args()
    out=ROOT/'航旅智策应用/runtime/portable-release';out.mkdir(parents=True,exist_ok=True)
    checked(args.model,MODEL);parts=[]
    with args.model.open('rb') as stream:
        index=0
        while block:=stream.read(1024**3):
            index+=1;name=MODEL['name']+f'.part-{index:03}';(out/name).write_bytes(block)
            parts.append({'name':name,'bytes':len(block),'sha256':hashlib.sha256(block).hexdigest()})
    for spec in RUNTIMES.values():
        source=args.runtime_directory/spec['name'];checked(source,spec);shutil.copyfile(source,out/spec['name'])
    legacy=json.loads((ROOT/'distribution/manifest.json').read_text(encoding='utf-8'))
    data=ROOT/'航旅智策应用/runtime/downloads'/legacy['bundle']['name'];checked(data,legacy['bundle']);shutil.copyfile(data,out/data.name)
    manifest={'version':1,'release_tag':TAG,'repository':legacy['repository'],'model':MODEL,'model_parts':parts,'runtimes':RUNTIMES,
        'data_bundle':legacy['bundle'],'data_contract':'distribution/manifest.json','legacy_9b_release':legacy['release_tag'],
        'choices':{'4b':{'backends':['CPU','Vulkan'],'default_backend':'CPU'},'9b':{'backends':['CUDA'],'default_backend':'CUDA'}},
        'private_state_included':False}
    text=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'
    (ROOT/'distribution/portable-manifest.json').write_text(text,encoding='utf-8');(out/'portable-manifest.json').write_text(text,encoding='utf-8')
    for name in ('LICENSE-Qwen3.txt','LICENSE-llama.cpp.txt','PORTABLE-NOTICE.txt'):shutil.copyfile(ROOT/'distribution'/name,out/name)
    print(json.dumps({'release_tag':TAG,'assets':len(list(out.iterdir())),'model_parts':len(parts),'private_state_included':False}))

if __name__=='__main__':main()
