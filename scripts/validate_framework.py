"""验证五层框架、内部链接与节假日数据时间口径；不验证模型效果。"""
import json
import re
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    config = json.loads((ROOT / 'configs/project.json').read_text(encoding='utf-8'))
    expected = ['数据层', '算法层', 'AIGC层', '应用层', '评估层']
    require([layer['name'] for layer in config['layers']] == expected, '五层定义不完整')
    require(len({layer['id'] for layer in config['layers']}) == 5, '层ID重复')
    for layer in config['layers']:
        require((ROOT / layer['spec']).is_file(), '缺少设计文件: ' + layer['spec'])
        require(bool(layer['status']), '缺少实现状态')
    for name in ['README.md', 'docs/project-plan.md', 'docs/report/outline.md']:
        require(config['project_name'] in (ROOT / name).read_text(encoding='utf-8'), '项目名称未同步: ' + name)

    markdown = [ROOT / 'README.md', ROOT / 'AGENTS.md']
    for directory in ['docs', 'data', 'backend', 'frontend', 'knowledge', 'experiments', 'prompts']:
        markdown.extend((ROOT / directory).rglob('*.md'))
    link_count = 0
    for path in markdown:
        content = path.read_text(encoding='utf-8')
        # 排除代码块中的示例，再检查普通Markdown内部文件链接。
        content = re.sub(r'```.*?```', '', content, flags=re.S)
        for target in re.findall(r'\]\(([^)]+)\)', content):
            parsed = urlsplit(target.strip('<>'))
            if parsed.scheme or not parsed.path:
                continue
            resolved = (path.parent / unquote(parsed.path)).resolve()
            require(resolved.exists(), f'失效链接: {path.relative_to(ROOT)} -> {target}')
            link_count += 1

    dataset = json.loads((ROOT / 'data/public/china-holiday-aviation-2025.json').read_text(encoding='utf-8'))
    entries = dataset['new_sources'] + dataset['reused_sources']
    sources = {item['id']: item for item in entries}
    require(len(sources) == len(entries), '来源ID重复')
    cutoff = date.fromisoformat(dataset['decision_cutoff'][:10])
    for source in entries:
        require(source['url'].startswith('https://'), '来源URL无效')
        require(bool(re.fullmatch(r'[0-9a-f]{64}', source['sha256'])), '来源哈希无效')
        date.fromisoformat(source['published_date'])
    observations = dataset['observations']
    require(len({row['id'] for row in observations}) == len(observations), '事实ID重复')
    for row in observations:
        require(row['source_id'] in sources, '事实缺少来源')
        source = sources[row['source_id']]
        require(row['published_date'] == source['published_date'], '发表日期不一致')
        published = date.fromisoformat(row['published_date'])
        require(row['available_before_decision_cutoff'] == (published <= cutoff), '截点标记错误')
        start, end = map(date.fromisoformat, row['statistic_period'])
        require(start <= end, '统计期倒置')
        require(bool(row['unit'] and row['geography'] and row['value_type']), '缺少指标口径')
        if row['observation_as_of']:
            require(date.fromisoformat(row['observation_as_of']) <= published, '观察日期晚于发表日')
    for row in dataset['popular_route_memberships']:
        require(row['source_id'] in sources, '航线名单缺少来源')
        require(row['rank'] is None and row['booking_count'] is None, '名单不能推断名次或票数')
    for row in dataset['route_supply_events']:
        require(row['source_id'] in sources, '供给事件缺少来源')
    for key in ['new_sources', 'reused_sources', 'observations', 'popular_route_memberships', 'route_supply_events']:
        require(dataset['counts'][key] == len(dataset[key]), '统计条数不一致: ' + key)
    print(f'Framework checks passed: 5 layers, {link_count} local links, {len(observations)} holiday observations.')


if __name__ == '__main__':
    main()
