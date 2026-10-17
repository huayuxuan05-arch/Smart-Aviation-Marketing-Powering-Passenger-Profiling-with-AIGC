"""Restore a chosen model into this project; no paths to another project required."""
from pathlib import Path
import json,zipfile
from distribution_io import download,join_parts,valid
RUNTIME=Path(__file__).resolve().parent/'runtime'

def activate(profile,root=None):
    root=Path(root or RUNTIME/'local_aigc');root.mkdir(parents=True,exist_ok=True)
    target=root/'active_model.json';profiles=root/'profiles';profiles.mkdir(exist_ok=True)
    if target.exists():
        old=json.loads(target.read_text(encoding='utf-8-sig'))
        name='4b' if '-4B-' in old['model_name'] else '9b'
        (profiles/(name+'.json')).write_text(json.dumps(old,ensure_ascii=False,indent=2),encoding='utf-8')
    name='4b' if '-4B-' in profile['model_name'] else '9b'
    text=json.dumps(profile,ensure_ascii=False,indent=2)
    (profiles/(name+'.json')).write_text(text,encoding='utf-8')
    temporary=target.with_suffix('.tmp');temporary.write_text(text,encoding='utf-8');temporary.replace(target)

def prepare_4b(manifest,backend='Auto',root=None):
    root=Path(root or RUNTIME/'local_aigc');root.mkdir(parents=True,exist_ok=True)
    model_name=manifest['model']['name'].removesuffix('.gguf')
    active=root/'active_model.json'
    if backend=='Auto' and active.exists():
        profile=json.loads(active.read_text(encoding='utf-8-sig'))
        if profile.get('model_name')==model_name and Path(profile['executable']).is_file() and valid(Path(profile['model_file']),manifest['model']):return profile
    if backend=='Auto':backend='CPU'
    if backend not in manifest['runtimes']:raise ValueError('4B支持CPU或Vulkan，请选择相应运行方式')
    base=f"https://github.com/{manifest['repository']}/releases/download/{manifest['release_tag']}/"
    model=manifest['model'];target=root/model['name'];cache=root/'downloads';cache.mkdir(exist_ok=True)
    if not valid(target,model):
        if model.get('url'):
            download(model['url'],target,model)
        else:
            parts=[]
            for spec in manifest['model_parts']:
                name=spec['name']
                if Path(name).name!=name or not name.startswith(model['name']+'.part-'):raise ValueError('模型分卷路径无效')
                parts.append((download(base+name,cache/name,spec),spec))
            join_parts(parts,target,model)
    spec=manifest['runtimes'][backend];archive=download(base+spec['name'],cache/spec['name'],spec)
    runtime=root/('llama-'+backend.lower())
    with zipfile.ZipFile(archive) as z:
        if any(not (runtime/name).resolve().is_relative_to(runtime.resolve()) for name in z.namelist()):raise ValueError('运行程序压缩路径无效')
        z.extractall(runtime)
    executable=runtime/'llama-server.exe'
    if not executable.is_file():raise ValueError('推理程序缺少llama-server.exe')
    profile={'model_file':str(target.resolve()),'model_name':model_name,'revision':model['revision'],'alias':'aerolens-'+model_name.split('-Q4_')[0].lower(),
        'label':f'{model_name.split("-Q4_")[0]} · Q4_K_M · 本地{backend}','executable':str(executable.resolve()),'backend':backend,
        'device':'none' if backend=='CPU' else 'Vulkan0','bytes':model['bytes'],'sha256':model['sha256'],
        'source':'Pinned official Qwen weights and llama.cpp; restored from this repository release'}
    activate(profile,root);return profile

def activate_cuda(root=None):
    from aigc_config import MODEL_FILE,MODEL_NAME,MODEL_BYTES,MODEL_SHA256,REVISION,ALIAS,LABEL,RUNTIME_DIR
    root=Path(root or RUNTIME/'local_aigc')
    profile={'model_file':str((root/MODEL_FILE).resolve()),'model_name':MODEL_NAME,'revision':REVISION,'alias':ALIAS,'label':LABEL,
        'executable':str((root/RUNTIME_DIR/'llama-server.exe').resolve()),'backend':'CUDA13.4 / CUDA0','device':'CUDA0','bytes':MODEL_BYTES,'sha256':MODEL_SHA256}
    if not valid(Path(profile['model_file']),{'bytes':MODEL_BYTES,'sha256':MODEL_SHA256}) or not Path(profile['executable']).is_file():raise ValueError('4B权重或CUDA程序尚未准备完成')
    activate(profile,root);return profile
