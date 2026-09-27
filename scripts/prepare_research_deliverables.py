"""将人工核验的首轮公开事实整理成台账；不推断缺失城市数据。"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/public'
SOURCES = [
    ('S01', 'c605a0728ea71798', '国务院办公厅关于2025年部分节假日安排的通知', '2024-11-12', '国务院办公厅', 'official_primary', 'calendar'),
    ('S02', 'd624d4ab5bffa46d', '2025年国庆中秋假期文旅消费热点预测', '2025-09-24', '文化和旅游部信息中心（转载中国旅游新闻客户端）', 'official_hosted_platform_report', 'preholiday_snapshot'),
    ('S03', '7105811368892e04', '2025年国庆中秋假期国内出游8.88亿人次', '2025-10-09', '文化和旅游部', 'official_primary', 'postholiday_evaluation'),
    ('S04', '7898031da0d71418', '2025年国庆中秋假期四川省文化和旅游市场情况综述', '2025-10-09', '四川省文化和旅游厅', 'official_primary_estimate', 'postholiday_evaluation'),
    ('S05', 'd351d82d889f2970', '2025年三亚市经济运行稳中有进', '2026-01-28', '三亚市统计局', 'official_primary', 'annual_background_only'),
]

def write_csv(name, rows):
    with (OUT / name).open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    ledger = []
    for sid, cache, title, published, publisher, tier, role in SOURCES:
        metadata = json.loads((ROOT / 'output/public-research' / (cache + '.meta.json')).read_text(encoding='utf-8'))
        assert metadata['status'] == 200 and metadata['proxy_configured']
        ledger.append(dict(source_id=sid, title=title, publisher=publisher, published_date=published, url=metadata['final_url'], source_tier=tier, use_role=role, retrieved_at=metadata['retrieved_at'], content_sha256=metadata['sha256'], access_status='verified', limitations='仅公开聚合信息；非上海客源或旅客个人数据'))
    write_csv('sources.csv', ledger)
    facts = []
    def fact(sid, geo, start, end, metric, value, unit, kind='reported', note=''):
        facts.append(dict(observation_id='O%02d' % (len(facts)+1), source_id=sid, geography=geo, origin_region='unknown', period_start=start, period_end=end, metric=metric, value=value, unit=unit, value_type=kind, note=note))
    fact('S01', '全国', '2025-10-01', '2025-10-08', 'holiday_days', 8, '天')
    fact('S03', '全国', '2025-10-01', '2025-10-08', 'domestic_tourist_trips', 8.88, '亿人次')
    fact('S03', '全国', '2025-10-01', '2025-10-08', 'domestic_tourist_spending', 8090.06, '亿元')
    fact('S03', '全国', '2024-10-01', '2024-10-07', 'domestic_tourist_trips', round(8.88-1.23, 2), '亿人次', 'derived', '2025总量减去报道的增加量；7天假期')
    fact('S03', '全国', '2024-10-01', '2024-10-07', 'domestic_tourist_spending', round(8090.06-1081.89, 2), '亿元', 'derived', '2025总量减去报道的增加量；7天假期')
    fact('S04', '四川省', '2025-10-01', '2025-10-08', 'tourist_trips', 4734.15, '万人次', 'reported_estimate', '第三方大数据综合测算；不等于成都市或A级景区接待量')
    fact('S04', '四川省', '2025-10-01', '2025-10-08', 'tourism_spending', 384.01, '亿元', 'reported_estimate', '按可比口径同比增长6.53%；比较口径细节未披露')
    fact('S05', '三亚市', '2025-01-01', '2025-12-31', 'overnight_tourist_trips', 2708.30, '万人次', note='全年过夜游客；不可与国庆全部游客直接比较')
    fact('S05', '三亚市', '2025-01-01', '2025-12-31', 'overnight_tourist_spending', 984.26, '亿元')
    fact('S05', '三亚市', '2025-01-01', '2025-12-31', 'tourist_hotel_occupancy', 69.0, '%', note='旅游饭店全年平均开房率；非航空客座率')
    write_csv('observations.csv', facts)
    write_csv('destination_snapshot.csv', [dict(destination=city, planned_origin='上海（研究设定）', observed_origin='unknown', source_id='S02', available_date='2025-09-24', metric='domestic_car_rental_order_top10_membership', in_top10='true', rank='', order_count='', search_index='', holiday_city_tourists='', note='仅确认名单成员；未获取订单量、城市搜索指数及上海出发分布') for city in ['成都', '三亚', '昆明']])
    write_csv('search_index_template.csv', [dict(date='', keyword=city+'旅游', platform='待选', region_filter='上海', index_type='', value='', exported_at='', source_file='', note='空白采集模板；不是已获取数据') for city in ['成都', '三亚', '昆明']])
    growth = [dict(metric=metric, total_growth_percent=round((new/old-1)*100, 4), daily_average_growth_percent=round(((new/8)/(old/7)-1)*100, 4), source_id='S03', note='根据报道舍入数推导；日均校正仅处理天数，不处理天气和节日结构等差异') for metric,new,old in [('domestic_tourist_trips',8.88,7.65), ('domestic_tourist_spending',8090.06,7008.17)]]
    write_csv('holiday_normalization.csv', growth)
    print('Prepared 5 sources, 10 observations, 3 destination memberships and an empty collection template.')

if __name__ == '__main__':
    main()
