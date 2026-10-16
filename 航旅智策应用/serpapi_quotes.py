"""SerpApi Google Flights adapter. Public schedules/quotes only, no user identity."""
from datetime import date,datetime,timedelta
from urllib.parse import urlencode
from urllib.error import HTTPError,URLError
import copy,hashlib,json,math,re,sqlite3,ssl,threading,time,urllib.request
from contextlib import closing
import airline_preferences as airlines
import flight_catalog as catalog
import flight_provider_settings as config
import fx_rates

SOURCE='Google Flights / SerpApi'
ENDPOINT='https://serpapi.com/search.json'
_locks=[threading.Lock() for _ in range(32)]
_memory_lock=threading.Lock()
_cache={}
_tokens={}
_quota_lock=threading.Lock()


def _reserve(settings):
    """Conservative local caps, including attempted calls; never auto-buy credits."""
    import flight_quotes as quotes
    now=datetime.now(quotes.CST);hour=now.strftime('%Y-%m-%dT%H');month=now.strftime('%Y-%m')
    with _quota_lock:
        target=quotes.RUNTIME/'flight-provider'/'usage.sqlite3';target.parent.mkdir(parents=True,exist_ok=True)
        with closing(sqlite3.connect(target,timeout=10)) as connection,connection:
            connection.execute('CREATE TABLE IF NOT EXISTS usage(bucket TEXT PRIMARY KEY,count INTEGER NOT NULL)')
            connection.execute('BEGIN IMMEDIATE')
            for bucket,cap in [(hour,settings['hourly_limit']),(month,settings['monthly_limit'])]:
                row=connection.execute('SELECT count FROM usage WHERE bucket=?',(bucket,)).fetchone()
                if row and row[0]>=cap:raise ValueError('第三方航班查询已达到本机设置的额度，请稍后查询或联系管理员')
            for bucket in (hour,month):
                connection.execute('INSERT INTO usage VALUES(?,1) ON CONFLICT(bucket) DO UPDATE SET count=count+1',(bucket,))


def request(params):
    import flight_quotes as quotes
    settings=config.settings();key=config.api_key()
    fingerprint=hashlib.sha256(key.encode()).hexdigest()
    encoded=json.dumps(params,sort_keys=True,separators=(',',':'))
    cache_key=(str(quotes.RUNTIME),fingerprint,encoded)
    lock=_locks[int(hashlib.sha256(encoded.encode()).hexdigest(),16)%len(_locks)]
    with lock:
        with _memory_lock:
            old=_cache.get(cache_key)
            if old and time.monotonic()-old[0]<60:return copy.deepcopy(old[1])
        # Validate the required proxy/TLS configuration before spending local quota.
        proxy=quotes.configured_proxy();context=ssl.create_default_context(cafile=quotes.certificate_bundle())
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({'http':proxy,'https':proxy}),urllib.request.HTTPSHandler(context=context))
        _reserve(settings)
        url=ENDPOINT+'?'+urlencode({**params,'api_key':key,'output':'json'})
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'HuayiChaoyang-FlightSearch/1.0','Accept':'application/json'})
            with opener.open(req,timeout=50) as response:raw=response.read(4000001)
            if len(raw)>4000000:raise ValueError('第三方航班结果过大，请缩小查询范围')
            data=json.loads(raw)
        except HTTPError as error:
            if error.code in (401,403):message='第三方航班密钥或账号权限需要检查'
            elif error.code==429:message='第三方航班服务额度或频率已达上限'
            else:message='第三方航班服务暂时不可用，请稍后再试'
            raise ValueError(message) from None
        except (URLError,TimeoutError,OSError,json.JSONDecodeError):
            # urllib exception URLs may contain the key; never relay or log them.
            raise ValueError('第三方航班服务暂时无法连接，请稍后再试') from None
        if not isinstance(data,dict) or data.get('error') or data.get('search_metadata',{}).get('status') not in ('Success',):
            raise ValueError('第三方航班服务未完成查询，请检查账号额度或稍后重试')
        with _memory_lock:
            for item in list(_cache):
                if time.monotonic()-_cache[item][0]>=60:del _cache[item]
            if len(_cache)>=128:del _cache[next(iter(_cache))]
            _cache[cache_key]=(time.monotonic(),copy.deepcopy(data))
        return data


def base(query):
    locale=query['provider_locale']
    return {'engine':'google_flights','type':1,'adults':query['adults'],'children':0,'infants_in_seat':0,'infants_on_lap':0,
        'travel_class':{'ECONOMY':1,'PREMIUM_ECONOMY':2,'BUSINESS':3,'FIRST':4}[query['cabin_class']],
        'currency':locale['currency'],'gl':locale['country'],'hl':locale['language'],
        'deep_search':'true','show_hidden':'true','no_cache':'true'}


def shopping_params(query):
    from adv_search_flights.data.airports import resolve_airports
    return {**base(query),'departure_id':','.join(resolve_airports(query['origin'])),
        'arrival_id':','.join(resolve_airports(query['destinations'][0])),
        'outbound_date':query['departure'],'return_date':query['return_date'],'stops':0,'sort_by':2}


def _convert(amount,currency):
    if isinstance(amount,bool) or not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<=0:return None
    try:return fx_rates.convert(amount,currency)
    except Exception:return None


def normalize(row,currency,observed_at,basis):
    import flight_quotes as quotes
    flights=row.get('flights')
    if not isinstance(flights,list) or not flights:raise ValueError('缺少完整航段')
    segments=[]
    for flight in flights:
        number=re.sub(r'\s+','',str(flight.get('flight_number',''))).upper()
        if not re.fullmatch(r'[A-Z0-9]{2}\d{1,4}[A-Z]?',number):raise ValueError('航班号无效')
        origin=flight['departure_airport'];destination=flight['arrival_airport']
        if not all(re.fullmatch('[A-Z]{3}',item['id']) for item in (origin,destination)):raise ValueError('机场代码无效')
        departure=datetime.fromisoformat(origin['time']);arrival=datetime.fromisoformat(destination['time'])
        if departure.year<datetime.now(quotes.CST).year-1:raise ValueError('非当前航班')
        segment={'flight_number':number,'airline_code':number[:2],'airline':str(flight.get('airline') or number[:2]),
            'origin_airport':origin['id'],'destination_airport':destination['id'],
            'departure_time':departure.isoformat(timespec='seconds'),'arrival_time':arrival.isoformat(timespec='seconds')}
        segment['airline_zh']=quotes.airline_display_name(segment)
        if segments and segments[-1]['destination_airport']!=segment['origin_airport']:raise ValueError('航段不连续')
        segments.append(segment)
    conversion=_convert(row.get('price'),currency)
    leg={'segments':segments,'origin_airport':segments[0]['origin_airport'],'destination_airport':segments[-1]['destination_airport'],
        'departure_time':segments[0]['departure_time'],'arrival_time':segments[-1]['arrival_time'],
        'price_cny':conversion['amount_cny'] if conversion else None,'original_price':row.get('price'),'original_currency':currency,
        'conversion':conversion,'price_basis':basis,'quote_status':'priced' if conversion else 'unresolved','source':SOURCE,
        'airlines':list(dict.fromkeys(s['airline'] for s in segments)),'stop_count':len(segments)-1,
        'layovers':[{'airport':v['id'],'minutes':v['duration']} for v in row.get('layovers',[])],
        'observed_at':observed_at}
    leg['catalog_id']=catalog.catalog_id(leg)
    return leg


def _context(query):
    # Only public itinerary facts key the cache; identities/preferences are excluded.
    import flight_quotes as quotes
    return (str(quotes.RUNTIME),hashlib.sha256(config.api_key().encode()).hexdigest(),json.dumps(shopping_params(query),sort_keys=True))


def _remember(query,leg,token,outbound=None):
    if not isinstance(token,str) or not token or len(token)>20000:return
    key=(_context(query),catalog.identity(leg),catalog.identity(outbound) if outbound else None)
    with _memory_lock:
        for item in list(_tokens):
            if time.monotonic()-_tokens[item][0]>=900:del _tokens[item]
        if len(_tokens)>=4096:del _tokens[next(iter(_tokens))]
        _tokens[key]=(time.monotonic(),token)


def fetch(query,outbound=None):
    import flight_quotes as quotes
    from adv_search_flights.data.airports import resolve_airports
    changed=copy.deepcopy(query)
    if outbound:
        offset=(date.fromisoformat(outbound['departure_time'][:10])-date.fromisoformat(query['departure'])).days
        changed.update(departure=outbound['departure_time'][:10],return_date=(date.fromisoformat(query['return_date'])+timedelta(days=offset)).isoformat())
    params=shopping_params(changed)
    if outbound:
        key=(_context(changed),catalog.identity(outbound),None)
        with _memory_lock:entry=_tokens.get(key)
        if not entry or time.monotonic()-entry[0]>=900:
            fetch(changed)
            with _memory_lock:entry=_tokens.get(key)
        if not entry:raise ValueError('第三方接口未提供该去程的返程查询信息，请刷新或选择其他航班')
        params['departure_token']=entry[1]
    data=request(params);observed=quotes.now();rows=[];failures=0
    currency=data.get('search_parameters',{}).get('currency') or changed['provider_locale']['currency']
    origins=resolve_airports(changed['destinations'][0] if outbound else changed['origin'])
    destinations=resolve_airports(changed['origin'] if outbound else changed['destinations'][0])
    target=changed['return_date'] if outbound else changed['departure']
    for row in [*data.get('best_flights',[]),*data.get('other_flights',[])]:
        try:
            leg=normalize(row,currency,observed,'native_roundtrip_total' if outbound else 'native_roundtrip_from')
            if leg['origin_airport'] not in origins or leg['destination_airport'] not in destinations or leg['departure_time'][:10]!=target:raise ValueError('航班不属于本次行程')
            leg['google_url']='https://www.google.com/travel/flights?'+urlencode({'hl':'zh-CN','curr':'CNY',
                'q':f"Flights from {changed['origin']} to {changed['destinations'][0]} on {changed['departure']} returning {changed['return_date']} {query['adults']} adults economy"})
            rows.append(leg)
            if not outbound:_remember(changed,leg,row.get('departure_token'))
        except (ValueError,TypeError,KeyError,AttributeError):failures+=1
    return {'catalog':catalog.deduplicate(rows),'observed_at':observed,'partial':bool(failures),'source':SOURCE}


def initial(query):
    import flight_quotes as quotes
    rows=[];partial=False;completed=0
    # Sequential flexible dates avoid bursting through the free plan's limits.
    for offset in sorted(range(-query.get('date_flex_days',0),query.get('date_flex_days',0)+1),key=lambda n:(abs(n),n)):
        start=date.fromisoformat(query['departure'])+timedelta(days=offset)
        if start<datetime.now(quotes.CST).date():continue
        changed={**query,'departure':start.isoformat(),'return_date':(date.fromisoformat(query['return_date'])+timedelta(days=offset)).isoformat()}
        try:
            value=fetch(changed);rows.extend(value['catalog']);partial=partial or value['partial'];completed+=1
        except ValueError:
            if not rows:raise
            partial=True;break
    inventory={'outbound':catalog.deduplicate(rows),'inbound':[]}
    return {'source':SOURCE,'options':[],'native_roundtrip':True,'catalog':inventory,
        'coverage':{**catalog.summary(inventory),'partial':partial,'scope':'serpapi_google_flights_returned_inventory',
            'completed_date_queries':completed,'search_version':config.VERSION},'query_quality':{'incomplete':partial},
        'fare_basis':'Google Flights经SerpApi返回的所选成人数往返总价；人民币显示，未拆分单程金额。最终价格、行李及退改条件以预订页为准。'}


def _option(outbound,inbound):
    out=copy.deepcopy(outbound);back=copy.deepcopy(inbound);out['price_cny']=back['price_cny']=None
    return {'outbound':out,'inbound':back,'total_price_cny':inbound['price_cny'],'quote_kind':'native_roundtrip',
        'fare_conversion':copy.deepcopy(inbound.get('conversion')),'original_total':inbound.get('original_price'),
        'original_currency':inbound.get('original_currency')}


def returns(query,outbound):
    value=fetch(query,outbound)
    return {**value,'options':[_option(outbound,leg) for leg in value['catalog'] if leg['price_cny'] is not None and catalog.compatible(outbound,leg,query)]}


def quote_selected(query,outbound,inbound,inventory):
    import flight_quotes as quotes
    def pinned(leg):return [{'flight_number':s['flight_number'],'departure_id':s['origin_airport'],
        'arrival_id':s['destination_airport'],'date':s['departure_time'][:10]} for s in leg['segments']]
    selected={'outbound':pinned(outbound),'return':pinned(inbound)}
    data=request({**base(query),'selected_flights_json':json.dumps(selected,separators=(',',':'))})
    currency=data.get('search_parameters',{}).get('currency') or query['provider_locale']['currency']
    actual=data.get('selected_flights',[])
    if len(actual)!=2 or any(catalog.identity(normalize(raw,currency,quotes.now(),'native_roundtrip_total'))!=catalog.identity(leg)
        for raw,leg in zip(actual,(outbound,inbound))):raise ValueError('第三方报价与所选往返航班不一致，请重新查询')
    candidates=[]
    for offer in data.get('booking_options',[]):
        together=offer.get('together',{})
        conversion=_convert(together.get('price'),currency)
        if conversion:candidates.append(conversion)
    value={'catalog':copy.deepcopy(inventory),'options':[],'partial':False,'observed_at':quotes.now(),'source':SOURCE}
    if not candidates:return value
    conversion=min(candidates,key=lambda c:c['amount_cny'])
    leg=next(l for l in value['catalog'] if l['catalog_id']==inbound['catalog_id'])
    # A refreshed booking amount invalidates an earlier choice index for this row.
    leg.pop('option_index',None)
    leg.update(price_cny=conversion['amount_cny'],original_price=conversion['original_amount'],original_currency=conversion['original_currency'],
        conversion=conversion,quote_status='priced',price_basis='native_roundtrip_total',observed_at=value['observed_at'])
    value['options']=[_option(outbound,leg)]
    return value
