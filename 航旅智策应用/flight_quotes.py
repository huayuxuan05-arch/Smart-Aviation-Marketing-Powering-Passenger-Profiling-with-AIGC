"""当前航班查询和只追加的观测记录；2024航班仅用于离线训练与评估。"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import math
import os
import re
import sqlite3
import threading
import time
import uuid
import hashlib
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlsplit

from data_layer import RUNTIME, CST

SOURCE = 'Google Flights / fli'
UPSTREAM_COMMIT = '7adb330fc167029e5874799e26c36c25aba019e9'
FRESH_SECONDS = 15 * 60
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='flight-quotes')
_slots = threading.BoundedSemaphore(6)
_lock = threading.Lock()


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def db():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(RUNTIME / 'flight_quotes.sqlite3', timeout=30)
    c.row_factory = sqlite3.Row
    try:
        c.execute('''CREATE TABLE IF NOT EXISTS flight_observations(
            id TEXT PRIMARY KEY,owner TEXT NOT NULL,query_key TEXT NOT NULL,
            requested_at TEXT NOT NULL,finished_at TEXT,status TEXT NOT NULL,
            query_json TEXT NOT NULL,result_json TEXT,error_code TEXT)''')
        c.execute('CREATE INDEX IF NOT EXISTS flight_query_owner ON flight_observations(owner,query_key,requested_at DESC)')
        yield c
        c.commit()
    finally:
        c.close()


def configured_proxy():
    value = os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy')
    if not value:
        raise ValueError('HTTPS代理未配置')
    parsed = urlsplit(value)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname:
        raise ValueError('需要已配置的HTTP或HTTPS代理端点')
    return value


def certificate_bundle():
    """Windows curl无法读取中文CA路径时，复制同一可信证书到项目ASCII路径。"""
    import certifi
    source = Path(os.environ.get('FLI_CA_BUNDLE') or os.environ.get('CURL_CA_BUNDLE') or
                  os.environ.get('REQUESTS_CA_BUNDLE') or certifi.where())
    contents = source.read_bytes()
    directory = Path(__file__).resolve().parent.parent / 'runtime' / 'flight-certificates'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (hashlib.sha256(contents).hexdigest() + '.pem')
    if not destination.exists():
        temporary = directory / (uuid.uuid4().hex + '.tmp')
        temporary.write_bytes(contents)
        os.replace(temporary, destination)
    return str(destination)


def configuration():
    ready = all(importlib.util.find_spec(m) is not None for m in ('adv_search_flights', 'fli'))
    try:
        configured_proxy()
        proxy = True
    except ValueError:
        proxy = False
    return {'enabled': ready and proxy, 'source': SOURCE, 'fresh_seconds': FRESH_SECONDS,
            'historical_flights_role': 'training_and_offline_evaluation_only'}


def recover_interrupted():
    with db() as c:
        c.execute("UPDATE flight_observations SET status='failed',finished_at=?,error_code='ServerRestart' WHERE status IN ('queued','running')",(now(),))


def query_for(plan, body=None):
    body = body or {}
    try:
        adults = int(body.get('adults', 1))
        stops = int(body.get('max_stops', 0))
    except (ValueError, TypeError):
        raise ValueError('人数或中转条件不合法') from None
    if not 1 <= adults <= 9 or stops not in (0, 1):
        raise ValueError('支持1至9名成人及最多一次中转')
    if plan.get('preference_constraints', {}).get('fallback_policy') == '只接受直飞':
        stops = 0
    return {'origin': str(plan['origin']), 'destinations': [str(plan['destination'])],
            'departure': str(plan['start_date']), 'return_date': str(plan['end_date']),
            'adults': adults, 'max_stops': stops, 'max_layover_hours': 6,
            'currency': 'CNY', 'cabin_class': 'ECONOMY', 'limit': 12}


def query_key(query):
    return json.dumps(query, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def is_fresh(value):
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(value)).total_seconds()
        return 0 <= age < FRESH_SECONDS
    except (ValueError, TypeError):
        return False


def get(owner, query_id):
    with db() as c:
        row = c.execute('SELECT * FROM flight_observations WHERE id=? AND owner=?', (query_id, owner)).fetchone()
    if row is None:
        raise ValueError('没有找到当前会话的航班查询')
    result = json.loads(row['result_json']) if row['result_json'] else {}
    return {'id': row['id'], 'status': row['status'], 'requested_at': row['requested_at'],
            'finished_at': row['finished_at'], 'fresh': is_fresh(row['requested_at']),
            'query': json.loads(row['query_json']), **result}


def history(owner, query):
    with db() as c:
        rows = c.execute('''SELECT id,requested_at,finished_at,status,result_json
            FROM flight_observations WHERE owner=? AND query_key=?
            ORDER BY requested_at DESC,rowid DESC LIMIT 60''', (owner, query_key(query))).fetchall()
    items = []
    for row in rows:
        payload = json.loads(row['result_json']) if row['result_json'] else {}
        options = payload.get('options', [])
        items.append({'id': row['id'], 'observed_at': row['requested_at'], 'status': row['status'],
                      'minimum_total_cny': min((o['total_price_cny'] for o in options), default=None)})
    return {'items': items, 'source': SOURCE, 'basis': '本机采集后形成的报价记录，不补造采集前的价格'}


def submit(owner, plan, body=None):
    query = query_for(plan, body)
    departure, returning = date.fromisoformat(query['departure']), date.fromisoformat(query['return_date'])
    today = datetime.now(CST).date()
    if not today <= departure <= returning <= today + timedelta(days=330):
        raise ValueError('请选择未来330天内有效的往返日期')
    configured_proxy()
    if not configuration()['enabled']:
        raise ValueError('航班查询依赖未就绪')
    key = query_key(query)
    with _lock:
        with db() as c:
            existing = c.execute('''SELECT id,requested_at,status FROM flight_observations
                WHERE owner=? AND query_key=? ORDER BY requested_at DESC,rowid DESC LIMIT 1''', (owner, key)).fetchone()
            if existing and is_fresh(existing['requested_at']) and (existing['status'] in ('queued', 'running') or
                    existing['status']=='success' and not (body or {}).get('refresh')):
                return get(owner, existing['id'])
            if not _slots.acquire(blocking=False):
                raise ValueError('航班匹配任务繁忙，请稍后再试')
            ident = 'QUOTE_' + uuid.uuid4().hex
            c.execute('INSERT INTO flight_observations VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident, owner, key, now(), None, 'queued', json.dumps(query, ensure_ascii=False), None, None))
        try:
            _pool.submit(_run, owner, ident, query)
        except Exception:
            _slots.release()
            raise
    return get(owner, ident)


def _run(owner, ident, query):
    try:
        with db() as c:
            c.execute("UPDATE flight_observations SET status='running' WHERE id=?", (ident,))
        # 每次尝试都留下记录；错误详情不向网页或日志输出代理凭证。
        result = _search(query)
        status = 'success' if result['options'] else 'empty'
        with db() as c:
            c.execute('UPDATE flight_observations SET status=?,finished_at=?,result_json=? WHERE id=?',
                      (status, now(), json.dumps(result, ensure_ascii=False), ident))
    except Exception as exc:
        with db() as c:
            c.execute("UPDATE flight_observations SET status='failed',finished_at=?,error_code=? WHERE id=?",
                      (now(), type(exc).__name__, ident))
    finally:
        _slots.release()


def _search(query):
    os.environ['ADV_SEARCH_FLIGHTS_LOG_DIR'] = str(RUNTIME / 'flight-logs')
    from adv_search_flights.control.rate_limit import DataCallController
    from adv_search_flights.domain.models import SearchRequest
    from adv_search_flights.providers.fli import FliProvider
    from adv_search_flights.search.engine import FlightSearchEngine
    observations = []

    class ProxyProvider(FliProvider):
        async def search_one_way(self, origin, destination, departure_date, adults, currency,
                                 max_stops, max_layover_minutes, cabin_class='ECONOMY'):
            return await asyncio.to_thread(_search_leg, origin, destination, departure_date,
                                           adults, cabin_class, observations)

    request = SearchRequest(**query, provider='fli', output_format='json')
    response = asyncio.run(FlightSearchEngine(ProxyProvider(), controller=DataCallController(
        cooldown_seconds=3, retry_delays=(3,)), max_concurrency=1).search(request))
    options = []
    for item in response.rendered or []:
        if not math.isfinite(float(item['total_price_cny'])) or item['total_price_cny'] <= 0:
            continue
        # 两张单程票组合只在往返时序确实可行时进入页面。
        arrival = datetime.fromisoformat(item['outbound']['arrival_time'])
        returning = datetime.fromisoformat(item['inbound']['departure_time'])
        if arrival.tzinfo is None:
            arrival = arrival.replace(tzinfo=CST)
        if returning.tzinfo is None:
            returning = returning.replace(tzinfo=CST)
        if arrival >= returning:
            continue
        if item['outbound']['arrival_time'][:10] != query['departure'] or item['inbound']['arrival_time'][:10] != query['return_date']:
            continue
        options.append(item)
    return {'source': SOURCE, 'options': options, 'leg_observations': observations,
            'upstream_commit': UPSTREAM_COMMIT, 'fare_basis': '所选成人数的两张单程查询价之和；税费、行李、退改和最终可售性以预订页为准'}


def _search_leg(origin, destination, departure_date, adults, cabin_class, observations):
    # 复用 Farello 的解码与标准化；请求明确传入用户代理，不执行其自动直连诊断。
    from fli.core import build_flight_segments, parse_cabin_class, parse_max_stops, parse_sort_by, resolve_airport
    from fli.models import FlightSearchFilters, PassengerInfo
    from fli.search import SearchFlights
    from fli.search._decoders import parse_flight_row
    from fli.search._urls import with_locale_params
    from fli.search._wire import parse_first_wrb_payload
    from adv_search_flights.providers.fli import _iter_flight_rows, _option_from_fli_flight
    observed_at = now()
    entry = {'origin': origin, 'destination': destination, 'date': departure_date.isoformat(),
             'adults': adults, 'observed_at': observed_at, 'currency': 'CNY', 'options': []}
    observations.append(entry)
    try:
        segments, trip_type = build_flight_segments(origin=resolve_airport(origin), destination=resolve_airport(destination),
            departure_date=departure_date.isoformat(), return_date=None, time_restrictions=None)
        filters = FlightSearchFilters(trip_type=trip_type, passenger_info=PassengerInfo(adults=adults),
            flight_segments=segments, stops=parse_max_stops('ANY'), seat_type=parse_cabin_class(cabin_class),
            sort_by=parse_sort_by('CHEAPEST'), show_all_results=True)
        client = SearchFlights()
        response = client.client.post(url=with_locale_params(client.BASE_URL, 'CNY', 'zh-CN', 'CN'),
            data=f'f.req={filters.encode()}', impersonate='chrome', allow_redirects=True,
            timeout=12, proxy=configured_proxy(), verify=certificate_bundle())
        response.raise_for_status()
        inner = parse_first_wrb_payload(response.text)
        if not isinstance(inner, list):
            raise ValueError('Flight source returned no usable payload')
        options = []
        for raw in _iter_flight_rows(inner):
            try:
                flight = parse_flight_row(raw)
                # 不把外币估算冒充人民币原始报价。
                if str(getattr(flight, 'currency', '') or '').upper() != 'CNY':
                    continue
                option = _option_from_fli_flight(flight, origin, destination, departure_date, raw, cabin_class=cabin_class)
                if option.price_cny is not None and option.price_cny > 0 and option.segments:
                    options.append(option)
            except (ValueError, TypeError, IndexError, AttributeError):
                continue
        entry.update(status='success' if options else 'empty', options=[o.model_dump(mode='json') for o in options], finished_at=now())
        return options
    except Exception as exc:
        entry.update(status='failed', error_code=type(exc).__name__, finished_at=now())
        raise RuntimeError(type(exc).__name__) from None


def latest_only(plan):
    """Web投影不改写原始数据或已保存的旧版本；历史票价不进入网页预算。"""
    p = copy.deepcopy(plan)
    live = p.get('live_flights')
    if live and is_fresh(live.get('observed_at')):
        return p
    p.pop('live_flights', None)
    p.pop('ai_explanation', None)
    p['flight_numbers'] = []
    p['flight_reference_fare'] = None
    p['flight_date_exact'] = False
    p['budget_excess'] = None
    for name, day in [('outbound', p['start_date']), ('return_route', p['end_date'])]:
        p[name] = {'flights': [], 'target_date': day, 'kind': '当前航班', 'status': '',
                   'exact_date': False, 'reference_fare': None, 'ground_transfer': None}
    for component in p['budget']['components']:
        if component['name'] in ('去程航空', '返程航空'):
            component.update(value=None, basis='按本次日期和人数查询')
        if component['name'] == '住宿':
            nightly = 240 if p['theme']=='交通与预算' else 360 if p['theme']=='舒适休闲' else 300
            component.update(value=(p['days']-1)*nightly, basis=f'每晚每名成人{nightly}元的情景估算，非商户报价')
    costs = [c['value'] for c in p['budget']['components'] if c['name'] != '机动预留' and c['value'] is not None]
    for component in p['budget']['components']:
        if component['name'] == '机动预留':
            component['value'] = round(sum(costs) * .1)
    p['budget'].update(estimated_total=None, difference=None,
        basis='按每名成人测算；航班采用本次查询价，住宿、餐饮和活动为情景估算。')
    p['basis'] = '画像使用历史数据训练。当前航班单独联网查询；住宿、餐饮和活动费用为情景估算。'
    p['personalization'] = [s for s in p['personalization'] if not re.search('历史航班|历史航线|历史参考|两段航线', s)]
    p['checklist'] = [s for s in p['checklist'] if not re.search('历史|两段航线', s)]
    p['backup_options'] = [o for o in p.get('backup_options', []) if o['name']!='按你选择的方式处理超预算']
    policy=p.get('preference_constraints',{}).get('overbudget_policy')
    if policy and not any(o['name']=='预算处理方式' for o in p['backup_options']):
        p['backup_options'].insert(0,{'name':'预算处理方式','advice':f'你选择：{policy}。费用变化先比较，再由你确认。'})
    for alternative in p.get('alternatives', []):
        alternative.update(reference_fare=None, kind='', status='按所选日期比较')
    p['bookable'] = False
    return p


def public_payload(value):
    """历史数据保持可复现，但不作为Web可选航班或报价输出。"""
    if isinstance(value, list):
        pairs=[(v,public_payload(v)) for v in value]
        return [item for original,item in pairs if not (isinstance(original,dict) and item is None)]
    if not isinstance(value, dict):
        return value
    if 'daily_itinerary' in value and 'budget' in value and 'outbound' in value:
        return latest_only(value)
    if '航班号' in value and '出发日' in value:
        return None
    if 'source' in value and ('01_航班信息.xlsx' in str(value['source']) or '历史航班' in str(value['source'])):
        return None
    result = {k: public_payload(v) for k, v in value.items()}
    if 'flight' in value and result.get('flight') is None:
        result.update(business_ready=False,flight_reason='',primary_flight_matched=False,
                      defer_reasons=['按本次出行条件确认航班'])
    if 'flight_matched' in result:
        result.update(flight_matched=False,business_ready=False)
    if 'flight_reference_fare' in result:
        result.update(flight_reference_fare=None, flight_numbers=[], flight_date_exact=False)
    for name in ('text', 'basis'):
        if isinstance(result.get(name), str):
            result[name] = '\n'.join(line for line in result[name].splitlines()
                if not re.search('历史表记录|历史参考价格|该历史报价|匹配历史航班', line))
    return result


def preview(owner, plan, body):
    observation = get(owner, body['query_id'])
    if observation['status'] != 'success' or not observation['fresh']:
        raise ValueError('请重新匹配当前航班后选择')
    q = observation['query']
    if query_key(q) != query_key(query_for(plan, q)):
        raise ValueError('报价与当前行程的日期、城市或人数不一致')
    try:
        index = int(body['option_index'])
        if index < 0:
            raise ValueError()
        option = observation['options'][index]
    except (ValueError, TypeError, IndexError):
        raise ValueError('请选择当前报价中的航班组合') from None
    p = latest_only(plan)
    adults = q['adults']
    p['live_flights'] = {'query_id': observation['id'], 'observed_at': observation['requested_at'],
                         'adults': adults, 'option': option, 'source': observation.get('source',SOURCE),
                         'fare_basis': observation['fare_basis']}
    for component in p['budget']['components']:
        direction = {'去程航空': 'outbound', '返程航空': 'inbound'}.get(component['name'])
        if direction:
            component.update(value=round(option[direction]['price_cny'] / adults, 2),
                basis=f'{adults}名成人查询价均摊；{SOURCE}，{observation["requested_at"]}')
    subtotal = sum(c['value'] or 0 for c in p['budget']['components'] if c['name'] != '机动预留')
    reserve = round(subtotal * .1)
    for component in p['budget']['components']:
        if component['name'] == '机动预留':
            component['value'] = reserve
    estimate = round(subtotal + reserve, 2)
    specified = p['budget']['specified_total']
    p['budget'].update(estimated_total=estimate, difference=round(estimate-specified, 2) if specified is not None else None)
    cap = p['budget'].get('one_way_airfare_cap')
    p['budget_excess'] = max(0, round(option['outbound']['price_cny']/adults-cap, 2)) if cap is not None else None
    p.pop('ai_explanation', None)
    p['checklist'].insert(0, '按已选航班时刻调整首尾日活动，并在预订页确认税费、行李、退改和价格。')
    p['daily_itinerary'][0]['blocks'][0]['detail'] = '本次去程：' + option['outbound']['departure_time'] + ' 至 ' + option['outbound']['arrival_time'] + '；以预订及航司通知为准。'
    p['basis'] = '航班使用本次联网查询结果；非机票费用为情景估算，不代表商户报价。原始训练数据保留在离线数据层。'
    p['bookable'] = False
    return p
