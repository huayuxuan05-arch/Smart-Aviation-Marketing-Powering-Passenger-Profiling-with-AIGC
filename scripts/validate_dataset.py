"""无需原始工作簿即可核对来源与发布契约；不伪称已经读取全量Excel。"""
import ast,json,re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def constants(path):
    values={}
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if isinstance(node,ast.Assign):
            try:value=ast.literal_eval(node.value)
            except (ValueError,TypeError):continue
            for target in node.targets:
                if isinstance(target,ast.Name):values[target.id]=value
    return values

def main():
    manifest=json.loads((ROOT/'distribution/manifest.json').read_text(encoding='utf-8'))
    data=constants(ROOT/'航旅智策应用/data_layer.py')
    model=constants(ROOT/'航旅智策应用/aigc_config.py')
    assert manifest['data_version']==data['VERSION']
    files={x['path']:x for x in manifest['files']}
    assert len(files)==len(manifest['files'])==7
    for name,digest in data['SOURCE_HASHES'].items():
        assert files['数据集/'+name]['sha256']==digest
    report=json.loads((ROOT/'experiments/results/local-demo-2026-10-12/artifact_manifest.json').read_text(encoding='utf-8'))
    assert report['source_sha256']==data['SOURCE_HASHES']
    for name,spec in report['artifacts'].items():
        entry=files['航旅智策应用/runtime/models/'+name]
        assert entry['sha256']==spec['sha256'] and entry['bytes']==spec['bytes']
    current=json.loads((ROOT/'distribution/qwen4b-2026-10-17.json').read_text(encoding='utf-8'))['inference']
    assert current['sha256']==model['MODEL_SHA256'] and current['bytes']==model['MODEL_BYTES']
    assert current['model_name']+'.gguf'==model['MODEL_FILE'] and current['revision']==model['REVISION']
    for entry in [manifest['bundle'],manifest['model'],*manifest['files'],*manifest['source_chunks']]:
        assert entry['bytes']>0 and re.fullmatch('[0-9a-f]{64}',entry['sha256'])
    assert sum(x['bytes'] for x in manifest['source_chunks'])==manifest['bundle']['bytes']
    print('Dataset contract passed: 3 workbook fingerprints, 7 restored files, trained artifacts and fixed Qwen source; original Excel not read by this check.')

if __name__=='__main__':main()
