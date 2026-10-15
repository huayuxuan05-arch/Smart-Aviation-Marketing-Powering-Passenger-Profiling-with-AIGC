"""行程证据、候选约束与本地模拟资格；不改变已训练模型和代理标签。"""
from datetime import timedelta
import math

from marketing_ml import BASE_DATE, day_index

DECISION_VERSION = 'trip-intent-v2'


def trip_intent(arrays, user, destination, asof, holiday):
    """预算只有与当前目的地、明确计划日期一致时才作为硬上限。"""
    cutoff = day_index(asof)
    recent = range(cutoff, max(-1, cutoff - 30), -1)
    plan_day = None
    plan_observed = None
    reference = None
    budget_rows = []
    for day in recent:
        if int(arrays['dest'][day, user]) != destination:
            continue
        travel = int(arrays['travel'][day, user])
        if plan_day is None and travel > cutoff:
            plan_day, plan_observed = travel, day
        value = float(arrays['budget'][day, user])
        if int(arrays['type'][day, user]) == 3 and math.isfinite(value) and value > 0:
            budget_rows.append((day, travel, value))
            if reference is None:
                reference = value
    date = (BASE_DATE + timedelta(days=plan_day)).date().isoformat() if plan_day is not None else None
    in_holiday = date is not None and holiday['start'] <= date <= holiday['end']
    matching = [(day, value) for day, travel, value in budget_rows if plan_day is not None and travel == plan_day]
    budget = matching[0][1] if matching and in_holiday else None
    scenario = max(holiday['start'], (BASE_DATE + timedelta(days=cutoff + 1)).date().isoformat())
    return {
        'version': DECISION_VERSION,
        'stage': '计划比较' if date else '灵感浏览',
        'plan_status': 'confirmed' if in_holiday else 'outside_holiday' if date else 'unknown',
        'travel_date': date or scenario,
        'date_basis': '截点前明确计划' if date else '营销假期情景假设',
        'plan_observed_on': (BASE_DATE + timedelta(days=plan_observed)).date().isoformat() if plan_observed is not None else None,
        'budget': budget,
        'budget_status': 'confirmed' if budget is not None else 'reference' if reference is not None else 'unknown',
        'budget_reference': reference,
        'budget_evidence': len(matching) if budget is not None else 0,
        'budget_observed_on': (BASE_DATE + timedelta(days=matching[0][0])).date().isoformat() if budget is not None else None,
        'budget_basis': '最近一次同目的地、同计划日期的查询上限' if budget is not None else '同目的地历史预算仅作参考' if reference is not None else '尚无本次行程预算',
        'evidence_window': [max('2023-12-01', (BASE_DATE + timedelta(days=cutoff - 29)).date().isoformat()), asof],
    }


def business_checks(row):
    intent = row.get('intent', {})
    flight = row.get('flight')
    version_ok = intent.get('version') == DECISION_VERSION
    plan_ok = intent.get('plan_status') == 'confirmed' and row.get('travel_date') == intent.get('travel_date')
    budget = row.get('budget')
    budget_ok = intent.get('budget_status') == 'confirmed' and isinstance(budget, (int, float)) and math.isfinite(budget) and budget > 0 and budget == intent.get('budget')
    route_ok = bool(flight) and (flight.get('出发城市'), flight.get('到达城市'), flight.get('出发日')) == (row.get('usual_departure_city'), row.get('destination'), row.get('travel_date'))
    price = flight.get('机票票价') if flight else None
    price_ok = route_ok and isinstance(price, (int, float)) and math.isfinite(price) and price > 0 and (not budget_ok or price <= budget)
    return [
        {'key': 'decision_version', 'passed': version_ok, 'reason': '旧版名单需按新规则重新创建活动'},
        {'key': 'plan', 'passed': plan_ok, 'reason': '明确计划不在本次假期' if intent.get('plan_status') == 'outside_holiday' else '需确认本次出行日期'},
        {'key': 'budget', 'passed': budget_ok, 'reason': '需确认本次行程预算上限'},
        {'key': 'product', 'passed': route_ok and price_ok, 'reason': '缺少满足城市、日期与预算的历史候选'},
    ]


def business_ready(row):
    return all(check['passed'] for check in business_checks(row))


def select_candidate(candidates):
    """明确计划和预算均满足的候选优先；仅在用户既有兴趣候选内比较。"""
    return min(candidates, key=lambda r: (not business_ready(r), not bool(r['flight']), r['preference_rank']))


def approved_materials(campaign):
    return {(m['destination'], m['theme']): m for m in reversed(campaign.get('creatives', []))
            if not m.get('deleted_at') and m['status'] == '已审核'
            and m['campaign_revision'] == campaign['revision']
            and m.get('review', {}).get('revision') == m['revision']}


def execution_readiness(campaign, source, state):
    """以模拟执行时刻重查退订、原始候选与跨活动频控，素材与业务分列。"""
    day = (BASE_DATE + timedelta(days=day_index(campaign['settings']['asof']) + 1)).date().isoformat()
    unsubscribed = {}
    for event in source.execute('SELECT user_id,MIN(event_time_cst) FROM events WHERE feedback_type="unsubscribe" AND event_time_cst<=? GROUP BY user_id', (day + ' 23:59:59',)):
        unsubscribed[event[0]] = event[1]
    sent = {row[0] for row in state.execute('SELECT user_id FROM deliveries WHERE day=?', (day,))}
    materials = approved_materials(campaign)
    items = []
    product_cache = {}
    for row in campaign['audience']:
        material = materials.get((row['destination'], row['theme']))
        checks = business_checks(row)
        flight = row.get('flight')
        source_ok = False
        if flight:
            identity = flight.get('candidate_id', '')
            if identity not in product_cache:
                number = identity.removeprefix('FLIGHT_ROW_')
                original = source.execute('SELECT * FROM flights WHERE rowid=?', (int(number) - 1,)).fetchone() if number.isdigit() else None
                product_cache[identity] = dict(original) if original else None
            original = product_cache[identity]
            source_ok = bool(original) and all(original.get(key) == flight.get(key) for key in ['出发日', '出发城市', '到达城市', '航班号', '机票票价'])
        hour = row.get('hour', -1)
        valid_hour = isinstance(hour, int) and 8 <= hour < 22
        scheduled = f'{day} {hour:02}:00:00' if isinstance(hour, int) and 0 <= hour <= 23 else day + ' 00:00:00'
        opted_out = row.get('unsubscribed', False) or (row['user_id'] in unsubscribed and unsubscribed[row['user_id']] <= scheduled)
        checks.extend([
            {'key': 'source', 'passed': source_ok, 'reason': '历史候选记录已变化或无法核验'},
            {'key': 'unsubscribe', 'passed': not opted_out, 'reason': '旅客已退订，暂不触达'},
            {'key': 'quiet_hours', 'passed': valid_hour, 'reason': '触达时间不在08:00—22:00内'},
            {'key': 'frequency', 'passed': row['user_id'] not in sent, 'reason': '同一旅客同一情景日已模拟触达'},
            {'key': 'material', 'passed': material is not None, 'reason': '等待本名单版本的已审核素材'},
        ])
        blockers = [check['reason'] for check in checks if not check['passed']]
        items.append({'user_id': row['user_id'], 'destination': row['destination'], 'scheduled_at': scheduled,
                      'material_id': material['id'] if material else None,
                      'material_ready': material is not None, 'business_ready': business_ready(row) and source_ok,
                      'eligible': not blockers, 'action': '本地模拟航线比较' if not blockers else '暂不触达',
                      'blockers': blockers, 'checks': checks, 'real_sendable': False})
    unit_cost = campaign['settings']['unit_cost']
    eligible = sum(item['eligible'] for item in items)
    budget_ok = eligible * unit_cost <= campaign['settings']['budget'] + 1e-9
    if not budget_ok:
        for item in items:
            item['checks'].append({'key': 'campaign_budget', 'passed': False, 'reason': '合格名单费用超过活动情景预算'})
            item['blockers'].append('合格名单费用超过活动情景预算')
            item['eligible'] = False
            item['action'] = '暂不触达'
        eligible = 0
    return {'version': DECISION_VERSION, 'scope': '历史产品与模拟旅客的本地执行资格', 'items': items,
            'eligible': eligible, 'blocked': len(items) - eligible,
            'material_ready': sum(item['material_ready'] for item in items),
            'business_ready': sum(item['business_ready'] for item in items),
            'estimated_cost': round(eligible * unit_cost, 2),
            'real_sendable': False, 'real_blockers': ['尚未接入真实可售产品、渠道授权和订单状态'],
            'basis': '本地资格通过不代表真实营销许可或当前可售；不生成曝光、点击或订单。'}
