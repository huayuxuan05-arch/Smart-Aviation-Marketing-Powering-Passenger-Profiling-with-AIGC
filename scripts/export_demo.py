"""导出合成数据及复现证据，默认仅写入被 Git 忽略的 output/。"""
import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.data import synthetic_passengers
from app.service import Service


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', default=str(ROOT / 'output' / 'demo'))
    args = parser.parse_args()
    target = Path(args.output)
    target.mkdir(parents=True, exist_ok=True)
    service = Service()
    try:
        for name, payload in [('passengers', synthetic_passengers()), ('profiles', service.profiles()),
                              ('overview', service.overview()), ('simulated_metrics', service.simulated_experiment())]:
            (target / f'{name}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        with (target / 'features.csv').open('w', newline='', encoding='utf-8-sig') as handle:
            columns = ['id','origin','segment','intent_score','consent','contacts_7d','data_source','as_of']
            writer = csv.DictWriter(handle, fieldnames=columns, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(service.profiles())
        print(f'已导出合成数据与规则基线证据：{target}')
    finally:
        service.db.close()


if __name__ == '__main__':
    main()
