"""当前航班查询仅保留成功观测；2024航班仅用于离线训练与评估。"""
from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
import logging
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
import airline_preferences as airlines
import flight_ranking
import flight_catalog

SOURCE = 'Google Flights / fli'
UPSTREAM_COMMIT = '7adb330fc167029e5874799e26c36c25aba019e9'
FRESH_SECONDS = 15 * 60
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='flight-quotes')
_slots = threading.BoundedSemaphore(6)
_lock = threading.Lock()
_empty_results = {}
_empty_lock = threading.Lock()
_return_slots=threading.BoundedSemaphore(2)
_return_locks=[threading.Lock() for _ in range(32)]

# Supplements omissions in the provider's Chinese carrier dictionary.
AIRLINE_NAMES_ZH = {'spring airlines': '春秋航空', '9c': '春秋航空'}


def airline_display_name(segment):
    existing = str(segment.get('airline_zh') or '').strip()
    if re.search(r'[\u3400-\u9fff]', existing):
        return existing
    code=airlines.segment_code(segment)
    if code in airlines.AIRLINES:return airlines.AIRLINES[code][0]
    for value in (segment.get('airline'), existing, segment.get('airline_code')):
        name = ' '.join(str(value or '').split()).casefold()
        if name in AIRLINE_NAMES_ZH:
            return AIRLINE_NAMES_ZH[name]
    if not segment.get('airline') and not existing:
        number = re.sub(r'\s+', '', str(segment.get('flight_number') or '')).upper()
        if re.fullmatch(r'9C\d+[A-Z]?', number):
            return '春秋航空'
    return existing or segment.get('airline')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def db():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(RUNTIME / 'flight_quotes.sqlite3', timeout=30)
    c.execute('PRAGMA secure_delete=ON')
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
    # curl on Windows requires an ASCII certificate filename. A project path
    # containing Chinese characters needs a separate, project-specific cache
    # on the same drive; copying within that path does not solve the problem.
    if os.name == 'nt' and not str(directory).isascii():
        project = Path(__file__).resolve().parent.parent
        ancestor = next(p for p in project.parents if str(p).isascii())
        project_key = hashlib.sha256(str(project).encode('utf-8')).hexdigest()[:16]
        directory = ancestor / '.huayi-chaoyang-runtime' / project_key / 'flight-certificates'
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (hashlib.sha256(contents).hexdigest() + '.pem')
    if not destination.exists():
        temporary = directory / (uuid.uuid4().hex + '.tmp')
        temporary.write_bytes(contents)
        os.replace(temporary, destination)
    return str(destination)


def configuration():
    import flight_provider_settings
    settings=flight_provider_settings.settings()
    ready = all(importlib.util.find_spec(m) is not None for m in ('adv_search_flights', 'fli'))
    try:
        configured_proxy()
        proxy = True
    except ValueError:
        proxy = False
    third_party=settings['provider']=='serpapi'
    return {'enabled': ready and proxy and (not third_party or settings['key_configured']),
            'provider':settings['provider'],'source': 'Google Flights / SerpApi' if third_party else SOURCE, 'fresh_seconds': FRESH_SECONDS,
            'setup_required':third_party and not settings['key_configured'],
            'search_version':flight_provider_settings.VERSION if third_party else flight_catalog.VERSION,'route_inventory':True,
            'automatic_refresh':not third_party,
            'historical_flights_role': 'training_and_offline_evaluation_only'}


def recover_interrupted():
    with db() as c:
        c.execute('PRAGMA secure_delete=ON')
        c.execute("DELETE FROM flight_observations WHERE status!='success'")
        for row in c.execute("SELECT id,result_json FROM flight_observations WHERE status='success'").fetchall():
            value=json.loads(row['result_json'] or '{}')
            if not value.get('options'):c.execute('DELETE FROM flight_observations WHERE id=?',(row['id'],));continue
            c.execute('UPDATE flight_observations SET result_json=?,error_code=NULL WHERE id=?',
                (json.dumps(successful_result(value),ensure_ascii=False),row['id']))
        c.commit();c.execute('VACUUM')


def successful_result(result):
    """Retain usable quotations only; failed attempts and diagnostics are discarded."""
    value=copy.deepcopy(result)
    value['leg_observations']=[o for o in value.get('leg_observations',[])
        if o.get('status')=='success' and o.get('options')]
    value.pop('query_quality',None)
    return value


def query_for(plan, body=None):
    import flight_provider_settings
    settings=flight_provider_settings.settings()
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
    constraints=plan.get('preference_constraints',{})
    filters={key:airlines.normalize(constraints.get(key,[])) for key in airlines.FIELDS}
    filters.update(date_flex_days={'前后1天可比较':1,'前后3天可比较':3}.get(constraints.get('date_flexibility'),0),
        budget_policy=constraints.get('flight_budget_policy','预算优先'),
        airfare_cap=plan.get('budget',{}).get('one_way_airfare_cap'),trip_budget=plan.get('budget',{}).get('specified_total'),
        nonflight_total=sum(c['value'] or 0 for c in plan.get('budget',{}).get('components',[]) if c['name'] not in ('去程航空','返程航空','往返航空','机动预留')))
    provider={}
    if settings['provider']=='serpapi':
        provider={'provider':'serpapi','provider_locale':{k:settings[k] for k in ('currency','country','language')},'search_version':flight_provider_settings.VERSION}
    return {**filters,'origin': str(plan['origin']), 'destinations': [str(plan['destination'])],
            'departure': str(plan['start_date']), 'return_date': str(plan['end_date']),
            'adults': adults, 'max_stops': stops, 'max_layover_hours': 6,
            'currency': 'CNY', 'cabin_class': 'ECONOMY','search_version':flight_catalog.VERSION,**provider}


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
        with _empty_lock:
            cached=_empty_results.get((str(RUNTIME),owner,query_id))
            if cached and is_fresh(cached['requested_at']):return copy.deepcopy(cached)
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
    return {'items': items, 'source': 'Google Flights / SerpApi' if query.get('provider')=='serpapi' else SOURCE, 'basis': '本机采集后形成的报价记录，不补造采集前的价格'}


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
        if not (body or {}).get('refresh'):
            with _empty_lock:
                existing=next((v for (root,account,_),v in reversed(list(_empty_results.items())) if root==str(RUNTIME) and account==owner
                    and is_fresh(v['requested_at']) and query_key(v['query'])==key),None)
                if existing:return {**copy.deepcopy(existing),'cache_hit':True,'reused_inflight':False}
        with db() as c:
            existing = c.execute('''SELECT id,requested_at,status FROM flight_observations
                WHERE owner=? AND query_key=? ORDER BY requested_at DESC,rowid DESC LIMIT 1''', (owner, key)).fetchone()
            if existing and is_fresh(existing['requested_at']) and (existing['status'] in ('queued', 'running') or
                    existing['status']=='success' and not (body or {}).get('refresh')):
                return {**get(owner, existing['id']),'cache_hit':existing['status']=='success','reused_inflight':existing['status'] in ('queued','running')}
            if not _slots.acquire(blocking=False):
                raise ValueError('航班匹配任务繁忙，请稍后再试')
            ident = 'QUOTE_' + uuid.uuid4().hex
            c.execute('INSERT INTO flight_observations VALUES(?,?,?,?,?,?,?,?,?)',
                      (ident, owner, key, now(), None, 'queued', json.dumps(query, ensure_ascii=False), None, None))
        try:
            _pool.submit(_run, owner, ident, query, plan.get('profile_revision'))
        except Exception:
            _slots.release()
            with db() as c:c.execute('DELETE FROM flight_observations WHERE id=?',(ident,))
            raise
    return {**get(owner, ident),'cache_hit':False,'reused_inflight':False}


def _run(owner, ident, query, profile_revision=None):
    try:
        with db() as c:
            c.execute("UPDATE flight_observations SET status='running' WHERE id=?", (ident,))
        # Quote history stores usable quotations only. Consented status counters
        # are separate and never contain failed quote payloads or error text.
        result = _search(query)
        result['options']=flight_ranking.rank(result.get('options',[]),query)
        status = result_status(result)
        with db() as c:
            if status!='success':c.execute('DELETE FROM flight_observations WHERE id=?',(ident,))
            else:c.execute('UPDATE flight_observations SET status=?,finished_at=?,result_json=? WHERE id=?',
                      (status, now(), json.dumps(successful_result(result), ensure_ascii=False), ident))
        if status in ('empty','flights_only'):
            # Inventory without a priced pair is not persisted as fare history.
            with _empty_lock:
                for key in list(_empty_results):
                    if not is_fresh(_empty_results[key]['requested_at']):del _empty_results[key]
                if len(_empty_results)>=512:del _empty_results[next(iter(_empty_results))]
                _empty_results[(str(RUNTIME),owner,ident)]={'id':ident,'status':status,'requested_at':now(),
                    'finished_at':now(),'fresh':True,'query':copy.deepcopy(query),'options':[],'source':result.get('source',SOURCE),
                    **{k:copy.deepcopy(result[k]) for k in ('catalog','coverage','fare_basis','native_roundtrip') if k in result}}
        if status in ('success','empty','flights_only','failed'):
            try:
                from real_travelers import record_flight_result
                record_flight_result(owner,ident,query,status,len(result['options']),profile_revision)
            except Exception:
                logging.getLogger(__name__).error('Could not save consented flight outcome')
    except Exception as error:
        with db() as c:
            c.execute('DELETE FROM flight_observations WHERE id=?',(ident,))
        try:
            from real_travelers import record_flight_result
            record_flight_result(owner,ident,query,'timeout' if isinstance(error,TimeoutError) else 'error',None,profile_revision)
        except Exception:logging.getLogger(__name__).error('Could not save consented flight outcome')
    finally:
        _slots.release()


def result_status(result):
    if result.get('options'):return 'success'
    if any(result.get('catalog',{}).get(k) for k in ('outbound','inbound')):return 'flights_only'
    return 'failed' if result.get('query_quality',{}).get('incomplete') else 'empty'


def query_returns(owner,plan,body):
    # Serialize updates of one observation while allowing independent users to shop.
    lock=_return_locks[int(hashlib.sha256((owner+str(body.get('query_id'))).encode()).hexdigest(),16)%len(_return_locks)]
    with lock:return _query_returns(owner,plan,body)


def _query_returns(owner,plan,body):
    observation=get(owner,body['query_id'])
    if not observation['fresh'] or not observation.get('native_roundtrip'):raise ValueError('请刷新航班后选择去程')
    query=observation['query']
    if query.get('provider')=='serpapi':import serpapi_quotes as adapter
    else:import fli_roundtrip as adapter
    if query_key(query)!=query_key(query_for(plan,query)):raise ValueError('查询与当前行程条件不同，请刷新')
    outbound=next((leg for leg in observation['catalog']['outbound'] if leg['catalog_id']==body.get('outbound_id')),None)
    if outbound is None:raise ValueError('请选择本次查询返回的去程航班')
    inbound=None
    if body.get('inbound_id'):
        if observation.get('selected_outbound_id')!=outbound['catalog_id']:raise ValueError('请先选择对应去程')
        inbound=next((leg for leg in observation['catalog']['inbound'] if leg['catalog_id']==body['inbound_id']),None)
        if inbound is None:raise ValueError('请选择当前去程对应的返程航班')
    if not _return_slots.acquire(blocking=False):raise ValueError('返程查询繁忙，请稍后重试')
    try:value=adapter.quote_selected(query,outbound,inbound,observation['catalog']['inbound']) if inbound else adapter.returns(query,outbound)
    finally:_return_slots.release()
    # Apply personal constraints only to selectable quotes, not the route inventory.
    valid=flight_ranking.rank(value['options'],query)
    for option in valid:
        index=next((i for i,o in enumerate(observation['options']) if flight_catalog.identity(o['outbound'])==flight_catalog.identity(option['outbound'])
            and flight_catalog.identity(o['inbound'])==flight_catalog.identity(option['inbound']) and o['total_price_cny']==option['total_price_cny']),None)
        if index is None:index=len(observation['options']);observation['options'].append(option)
        for leg in value['catalog']:
            if flight_catalog.identity(leg)==flight_catalog.identity(option['inbound']):leg['option_index']=index
    observation.update(finished_at=now(),status='success' if observation['options'] else 'flights_only')
    observation['catalog']['inbound']=value['catalog'];observation['selected_outbound_id']=outbound['catalog_id']
    observation['coverage']['partial']=observation['coverage'].get('partial',False) or value['partial']
    if observation['options']:
        payload={k:v for k,v in observation.items() if k not in ('id','status','requested_at','finished_at','fresh','query')}
        with db() as c:
            c.execute('INSERT INTO flight_observations VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,finished_at=excluded.finished_at,result_json=excluded.result_json',
                (observation['id'],owner,query_key(query),observation['requested_at'],now(),'success',json.dumps(query,ensure_ascii=False),json.dumps(payload,ensure_ascii=False),None))
        if owner!='marketing':
            from real_travelers import record_flight_result
            record_flight_result(owner,observation['id'],query,'success',len(observation['options']),plan.get('profile_revision'))
    with _empty_lock:_empty_results[(str(RUNTIME),owner,observation['id'])]=copy.deepcopy(observation)
    return {'observation':observation,'returns':value['catalog'],'outbound_id':outbound['catalog_id'],'partial':value['partial']}


def _search(query):
    if query.get('provider')=='serpapi':
        import serpapi_quotes
        return serpapi_quotes.initial(query)
    if query.get('search_version')==flight_catalog.VERSION:
        import fli_roundtrip
        return fli_roundtrip.initial(query)
    # Query the route before applying personal airline/price restrictions.
    for name in ['adv_search_flights','fli']:
        logger=logging.getLogger(name)
        for handler in logger.handlers[:]:handler.close();logger.removeHandler(handler)
        logger.addHandler(logging.NullHandler());logger.propagate=False
    from adv_search_flights.search.engine import resolve_airports
    origins=resolve_airports(query['origin'])
    destinations=list(dict.fromkeys(a for city in query['destinations'] for a in resolve_airports(city)))
    specs=set()
    for offset in range(-query.get('date_flex_days',0),query.get('date_flex_days',0)+1):
        start=date.fromisoformat(query['departure'])+timedelta(days=offset)
        end=date.fromisoformat(query['return_date'])+timedelta(days=offset)
        if start<datetime.now(CST).date():continue
        for origin in origins:
            for destination in destinations:
                if origin!=destination:
                    specs.add(('outbound',origin,destination,start))
                    specs.add(('inbound',destination,origin,end))
    observations=[]
    async def run():
        gate=asyncio.Semaphore(2)
        async def leg(spec):
            direction,origin,destination,day=spec;local=[]
            async with gate:
                try:
                    await asyncio.to_thread(_search_leg,origin,destination,day,query['adults'],query['cabin_class'],local,{'required_airlines':[],'excluded_airlines':[]})
                except RuntimeError:pass
            for observation in local:observation['direction']=direction
            return local
        rows=await asyncio.gather(*(leg(spec) for spec in sorted(specs)))
        return [item for row in rows for item in row]
    observations=asyncio.run(run())
    catalog={direction:flight_catalog.deduplicate([leg for observation in observations if observation['direction']==direction
        for leg in observation.get('catalog',[])]) for direction in ('outbound','inbound')}
    options=flight_catalog.combine(catalog,query)
    failures=[o for o in observations if o.get('status')=='failed' or o.get('parse_failures')]
    coverage={**flight_catalog.summary(catalog),'source':SOURCE,'scope':'google_returned_route_inventory',
        'expected_airport_queries':len(specs),'completed_airport_queries':len(observations),
        'partial':bool(failures) or len(observations)<len(specs),
        'combination_policy':'cheapest_compatible_pair_for_each_eligible_priced_leg',
        'airports':{'origin':origins,'destination':destinations},'search_version':flight_catalog.VERSION}
    return {'source':SOURCE,'options':options,'catalog':catalog,'coverage':coverage,'leg_observations':observations,
        'ranking_order':flight_ranking.ORDER,'query_quality':{'leg_attempts':len(observations),
            'failed_leg_attempts':len(failures),'incomplete':coverage['partial']},'upstream_commit':UPSTREAM_COMMIT,
        'fare_basis':'所选成人数的两张单程查询价之和；外币按最近可用参考汇率换算人民币，最终税费、行李、退改与可售性以预订页为准'}


def upstream_rpc_error(body):
    """Read only numeric RPC error codes, never persist service tokens or raw bodies."""
    for line in body.splitlines():
        if not line.lstrip().startswith(b'[['):continue
        try:outer=json.loads(line)
        except (ValueError,UnicodeDecodeError):continue
        if not isinstance(outer,list):continue
        for row in outer:
            if (isinstance(row,list) and len(row)>5 and row[0]=='wrb.fr' and row[2] is None
                and isinstance(row[5],list) and row[5] and type(row[5][0]) is int):
                return row[5][0]
    return None


def _google_rows(body):
    from fli.search._wire import iter_wrb_chunks
    from adv_search_flights.providers.fli import _iter_flight_rows
    chunks=[c for c in iter_wrb_chunks(body) if isinstance(c,list)]
    if not chunks:raise ValueError('Flight source returned no usable payload')
    rows=[]
    for chunk in chunks:
        for row in _iter_flight_rows(chunk):
            # Ignore metadata/ad rows, but retain valid flight schedules with no price block.
            try:
                legs=row[0][2]
                if not isinstance(legs,list) or not legs:continue
                if not all(isinstance(l,list) and len(l)>22 and isinstance(l[22],list) and len(l[22])>=2 for l in legs):continue
            except (IndexError,TypeError):continue
            rows.append(row)
    return chunks,rows


def _google_request(filters,observation):
    from fli.search import SearchFlights
    from fli.search._urls import with_locale_params
    from fli.search._decoders import parse_flight_row
    from adv_search_flights.providers.fli import _option_from_fli_flight
    from adv_search_flights.output.renderers import _one_way_payload,_purchase_link
    import fx_rates
    client=SearchFlights()
    response=client.client.post(url=with_locale_params(client.BASE_URL,'CNY','zh-CN','CN'),
        data='f.req='+filters.encode(),impersonate='chrome',allow_redirects=True,
        timeout=15,proxy=configured_proxy(),verify=certificate_bundle())
    observation['response_meta']={'http_status':response.status_code,'bytes':len(response.content)}
    response.raise_for_status()
    code=upstream_rpc_error(response.content)
    try:chunks,rows=_google_rows(response.content)
    except ValueError:
        if code is not None:observation['upstream_rpc_code']=code
        raise
    observation.update(response_chunks=len(chunks),raw_flight_rows=len(rows),parse_failures=0)
    found={}
    for row in rows:
        try:
            try:flight=parse_flight_row(row)
            except ValueError:
                clean=copy.deepcopy(row)
                while len(clean)<2:clean.append(None)
                clean[1]=[[],None]
                flight=parse_flight_row(clean)
            first=flight.legs[0];last=flight.legs[-1]
            if len(flight.legs)!=len(row[0][2]):raise ValueError('Incomplete flight segments')
            original_price=flight.price;original_currency=flight.currency;conversion=None
            if original_price is not None and original_currency:
                try:conversion=fx_rates.convert(original_price,original_currency)
                except Exception:pass
            decoded=flight.model_copy(update={'price':round(conversion['amount_cny']) if conversion else None,'currency':'CNY' if conversion else None})
            option=_option_from_fli_flight(decoded,first.departure_airport.name,last.arrival_airport.name,
                first.departure_datetime.date(),[],cabin_class=observation.get('cabin','ECONOMY'))
            if len(option.segments)!=len(flight.legs):raise ValueError('Incomplete normalized segments')
            option.raw={}
            leg=_one_way_payload(option);leg['price_cny']=conversion['amount_cny'] if conversion else None
            leg.update(catalog_id=flight_catalog.catalog_id(leg),source=SOURCE,observed_at=observation['observed_at'],
                original_price=original_price,original_currency=original_currency,conversion=conversion,
                quote_status='priced' if conversion else 'unresolved',google_url=_purchase_link(option)['url'])
            for segment in leg['segments']:segment['airline_zh']=airline_display_name(segment)
            key=flight_catalog.identity(leg);previous=found.get(key)
            if previous is None or leg['price_cny'] is not None and (previous[1]['price_cny'] is None or leg['price_cny']<previous[1]['price_cny']):found[key]=(flight,leg,option)
        except (ValueError,TypeError,IndexError,KeyError,AttributeError):observation['parse_failures']+=1
    observation.update(catalog=[row[1] for row in found.values()],status='success' if found else 'empty',finished_at=now())
    if rows and not found:raise ValueError('All flight rows failed to decode')
    return list(found.values())


def _search_leg(origin,destination,departure_date,adults,cabin_class,observations,airline_filters=None):
    from fli.core import build_flight_segments,parse_airlines,parse_cabin_class,parse_max_stops,parse_sort_by,resolve_airport
    from fli.models import FlightSearchFilters,PassengerInfo
    entry={'origin':origin,'destination':destination,'date':departure_date.isoformat(),'adults':adults,
        'observed_at':now(),'currency':'CNY','cabin':cabin_class,'options':[],'catalog':[]}
    observations.append(entry)
    try:
        segments,trip_type=build_flight_segments(origin=resolve_airport(origin),destination=resolve_airport(destination),
            departure_date=departure_date.isoformat(),return_date=None,time_restrictions=None)
        filters=FlightSearchFilters(trip_type=trip_type,passenger_info=PassengerInfo(adults=adults),flight_segments=segments,
            stops=parse_max_stops('ANY'),seat_type=parse_cabin_class(cabin_class),
            airlines=parse_airlines((airline_filters or {}).get('required_airlines')),
            airlines_exclude=parse_airlines((airline_filters or {}).get('excluded_airlines')),
            sort_by=parse_sort_by('CHEAPEST'),show_all_results=True)
        parsed=_google_request(filters,entry)
        matching=[row for row in parsed if airlines.matches_leg(row[1],airline_filters or {})]
        entry['catalog']=[row[1] for row in matching]
        options=[row[2] for row in matching if row[1]['price_cny'] is not None]
        entry['options']=[{k:v for k,v in option.model_dump(mode='json').items() if k!='raw'} for option in options]
        return options
    except Exception as exc:
        entry.update(status='failed',error_code=type(exc).__name__,error_stage='upstream_rpc' if entry.get('upstream_rpc_code') is not None else 'wire_decode',finished_at=now())
        raise RuntimeError(type(exc).__name__) from None


def retain_current_explanation(plan):
    if plan.get('ai_explanation'):
        from local_generation import explanation_matches_plan
        if not explanation_matches_plan(plan):
            plan.pop('ai_explanation', None)
    return plan


def latest_only(plan):
    """Web投影不改写原始数据或已保存的旧版本；历史票价不进入网页预算。"""
    p = copy.deepcopy(plan)
    live = p.get('live_flights')
    if live and is_fresh(live.get('observed_at')) and airlines.matches_option(live['option'],p.get('preference_constraints',{})):
        p['live_flights'] = public_payload(live)
        return retain_current_explanation(p)
    p.pop('live_flights', None)
    p['flight_numbers'] = []
    p['flight_reference_fare'] = None
    p['flight_date_exact'] = False
    p['budget_excess'] = None
    for name, day in [('outbound', p['start_date']), ('return_route', p['end_date'])]:
        p[name] = {'flights': [], 'target_date': day, 'kind': '当前航班', 'status': '',
                   'exact_date': False, 'reference_fare': None, 'ground_transfer': None}
    for component in p['budget']['components']:
        if component['name'] in ('去程航空', '返程航空','往返航空'):
            component.update(value=None, basis='按本次日期和人数查询')
        if component['name'] == '住宿' and not p.get('ai_planning',{}).get('content_generated'):
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
    return retain_current_explanation(p)


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
    if 'flight_number' in value:
        name = airline_display_name(value)
        if name:
            result['airline_zh'] = name
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
    if not airlines.matches_option(option,plan.get('preference_constraints',{})):
        raise ValueError('该航班不符合你指定或排除的航空公司要求')
    if any(len(option[l]['segments'])-1>q['max_stops'] or
        any(v.get('minutes',0)>q['max_layover_hours']*60 for v in option[l].get('layovers',[])) for l in ('outbound','inbound')):
        raise ValueError('该航班超出已选择的中转条件')
    if not flight_catalog.compatible(option['outbound'],option['inbound'],q):
        raise ValueError('往返航班日期不符合本次行程')
    if q.get('budget_policy')=='只看预算内' and not flight_ranking.rank([copy.deepcopy(option)],q):
        raise ValueError('该航班超出你选择的预算范围，请调整标签后重新搜索')
    p = latest_only(plan)
    actual_start=option['outbound']['departure_time'][:10];actual_end=option['inbound']['departure_time'][:10]
    shift=(date.fromisoformat(actual_start)-date.fromisoformat(plan['start_date'])).days
    if abs(shift)>q.get('date_flex_days',0):raise ValueError('报价日期超出已确认的日期弹性')
    if shift:
        p.update(start_date=actual_start,end_date=actual_end)
        for day in p['daily_itinerary']:day['date']=(date.fromisoformat(actual_start)+timedelta(days=day['day']-1)).isoformat()
        p['date_basis']='在本人允许的日期范围内比较并确认的航班日期'
    adults = q['adults']
    p['live_flights'] = {'query_id': observation['id'], 'observed_at': observation['requested_at'],
                         'adults': adults, 'option': option, 'source': observation.get('source',SOURCE),
                         'fare_basis': observation['fare_basis']}
    native=option.get('quote_kind')=='native_roundtrip'
    if native:
        p['budget']['components']=[c for c in p['budget']['components'] if c['name'] not in ('去程航空','返程航空','往返航空')]
        p['budget']['components'].insert(0,{'name':'往返航空','value':round(option['total_price_cny']/adults,2),
            'basis':'Google所选航班往返总价按成人数均摊；未提供单程拆价'})
    for component in p['budget']['components']:
        direction = {'去程航空': 'outbound', '返程航空': 'inbound'}.get(component['name'])
        if direction and not native:
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
    p['budget_excess'] = max(0, round(option['outbound']['price_cny']/adults-cap, 2)) if cap is not None and not native else None
    if native and cap is not None:p['checklist'].insert(0,'已选报价为往返总价，单程预算上限尚需核验，不按总价平分推定。')
    p.pop('ai_explanation', None)
    p['checklist'].insert(0, '按已选航班时刻调整首尾日活动，并在预订页确认税费、行李、退改和价格。')
    p['daily_itinerary'][0]['blocks'][0]['detail'] = '本次去程：' + option['outbound']['departure_time'] + ' 至 ' + option['outbound']['arrival_time'] + '；以预订及航司通知为准。'
    if p.get('ai_planning',{}).get('content_generated'):
        from personal_plan_generation import align_flights
        align_flights(p)
    p['basis'] = '航班使用本次联网查询结果；非机票费用为情景估算，不代表商户报价。原始训练数据保留在离线数据层。'
    p['bookable'] = False
    return p
