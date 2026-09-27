"""检查公开事实的来源引用、时间边界和缺失值含义。"""
import csv
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'data/public'

def rows(name):
    with (ROOT / name).open(encoding='utf-8-sig', newline='') as handle:
        return list(csv.DictReader(handle))

def main():
    sources = rows('sources.csv')
    lookup = {item['source_id']: item for item in sources}
    assert len(lookup) == len(sources), 'Duplicate source IDs'
    for source in sources:
        assert source['url'].startswith('https://')
        assert len(source['content_sha256']) == 64
        date.fromisoformat(source['published_date'])
    facts = rows('observations.csv')
    assert len({item['observation_id'] for item in facts}) == len(facts)
    for item in facts:
        assert item['source_id'] in lookup
        assert date.fromisoformat(item['period_start']) <= date.fromisoformat(item['period_end'])
        assert float(item['value']) >= 0 and item['unit']
        assert item['value_type'] in {'reported', 'reported_estimate', 'derived'}
        if item['value_type'] == 'derived':
            assert item['note'], 'Derived fact requires formula explanation'
    for item in rows('destination_snapshot.csv'):
        assert item['source_id'] in lookup
        assert item['available_date'] == lookup[item['source_id']]['published_date']
        assert date.fromisoformat(item['available_date']) <= date(2025, 9, 30)
        assert item['observed_origin'] == 'unknown'
        assert all(item[key] == '' for key in ['rank', 'order_count', 'search_index', 'holiday_city_tourists'])
    for item in rows('search_index_template.csv'):
        assert item['value'] == '' and item['date'] == '', 'Template must not masquerade as observations'
    normalized = {item['metric']: item for item in rows('holiday_normalization.csv')}
    for metric, new, old in [('domestic_tourist_trips', 8.88, 7.65), ('domestic_tourist_spending', 8090.06, 7008.17)]:
        item = normalized[metric]
        assert abs(float(item['total_growth_percent']) - (new / old - 1) * 100) < 0.0001
        assert abs(float(item['daily_average_growth_percent']) - ((new / 8) / (old / 7) - 1) * 100) < 0.0001
    print('Public data validation passed: sources, provenance, dates, missing fields and normalization.')

if __name__ == '__main__':
    main()
