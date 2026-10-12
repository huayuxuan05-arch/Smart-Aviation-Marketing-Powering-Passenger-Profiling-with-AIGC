"""校验当前Demo的五层定义、源码依赖、文档与静态资源；不声称业务测试。"""
import ast,json,re
from pathlib import Path
from urllib.parse import unquote,urlsplit

ROOT=Path(__file__).resolve().parents[1]

def require(condition,message):
    if not condition:raise ValueError(message)

def main():
    config=json.loads((ROOT/'configs/project.json').read_text(encoding='utf-8'))
    require([x['name'] for x in config['layers']]==['数据层','算法层','AIGC层','应用层','评估层'],'五层定义不完整')
    require(len({x['id'] for x in config['layers']})==5,'层ID重复')
    for layer in config['layers']:
        require((ROOT/layer['spec']).is_file() and layer['status'],'缺少五层说明或状态')
    require(config['project_name'] in (ROOT/'README.md').read_text(encoding='utf-8'),'项目名称未同步')
    links=0
    paths=[ROOT/'README.md',ROOT/'AGENTS.md']
    for folder in ['docs','distribution','数据集','experiments','航旅智策应用']:
        paths.extend(p for p in (ROOT/folder).rglob('*.md') if not any(x in p.parts for x in ['runtime','.venv','node_modules']))
    for path in paths:
        content=path.read_text(encoding='utf-8')
        for target in re.findall(r'\]\(([^)]+)\)',content):
            parsed=urlsplit(target.strip('<>'))
            if parsed.scheme or not parsed.path:continue
            require((path.parent/unquote(parsed.path)).exists(),f'失效链接: {path.relative_to(ROOT)} -> {target}')
            links+=1
    app=ROOT/'航旅智策应用'
    retired={'aigc_layer','traveler_layer'}
    sources=list(app.glob('*.py'))+list((ROOT/'scripts').glob('*.py'))
    for path in sources:
        tree=ast.parse(path.read_text(encoding='utf-8'),filename=str(path))
        for node in ast.walk(tree):
            names=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) else []
            require(not retired.intersection(names),'源码仍依赖已移除模块: '+str(path))
    for target in ['data','deliverables','prompts','航旅智策应用/web/research','航旅智策应用/web/traveler']:
        folder=ROOT/target
        require(not folder.exists() or not any(p.is_file() for p in folder.rglob('*')),'仍含旧版文件: '+target)
    assets=re.findall(r'(?:src|href)="(/[^"?#]+\.(?:js|css))"',(app/'web/marketing/index.html').read_text(encoding='utf-8'))
    for asset in assets:require((app/'web'/asset.lstrip('/')).is_file(),'缺少网页资源: '+asset)
    print(f'Demo framework passed: 5 layers, {links} local links, {len(sources)} Python sources, {len(assets)} web assets.')

if __name__=='__main__':main()
