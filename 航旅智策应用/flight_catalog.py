"""Complete returned route inventory, separate from priced recommendation pairs."""
from datetime import date,datetime
import copy,hashlib,json,math
import airline_preferences as airlines
import flight_ranking

VERSION='google-route-catalog-v2'


def identity(leg):
    return tuple(tuple(str(s.get(k,'')) for k in ('flight_number','origin_airport','destination_airport','departure_time','arrival_time')) for s in leg.get('segments',[]))


def catalog_id(leg):return 'LEG_'+hashlib.sha256(json.dumps(identity(leg)).encode()).hexdigest()[:20]


def deduplicate(legs):
    found={}
    for leg in legs:
        key=identity(leg)
        if not key:continue
        price=leg.get('price_cny')
        if price is not None and (not math.isfinite(float(price)) or price<=0):price=None
        old=found.get(key)
        if old is None or price is not None and (old.get('price_cny') is None or price<old['price_cny']):
            found[key]={**copy.deepcopy(leg),'price_cny':price,'catalog_id':catalog_id(leg)}
    return sorted(found.values(),key=lambda v:(v['departure_time'],v.get('price_cny') is None,v.get('price_cny') or 0))


def valid_leg(leg,query):
    if not airlines.matches_leg(leg,query):return False
    if len(leg['segments'])-1>query['max_stops']:return False
    if any(l.get('minutes',0)>query.get('max_layover_hours',6)*60 for l in leg.get('layovers',[])):return False
    return leg.get('price_cny') is not None


def compatible(outbound,inbound,query):
    offset=(date.fromisoformat(outbound['departure_time'][:10])-date.fromisoformat(query['departure'])).days
    back_offset=(date.fromisoformat(inbound['departure_time'][:10])-date.fromisoformat(query['return_date'])).days
    return abs(offset)<=query.get('date_flex_days',0) and offset==back_offset and outbound['arrival_time']<inbound['departure_time']


def combine(catalog,query):
    """Cover every eligible priced leg with its cheapest compatible counterpart.

    This avoids materializing the potentially huge Cartesian product. All source
    flights remain in the inventory, including those without a recovered quote.
    """
    out=sorted((l for l in catalog['outbound'] if valid_leg(l,query)),key=lambda l:l['price_cny'])
    back=sorted((l for l in catalog['inbound'] if valid_leg(l,query)),key=lambda l:l['price_cny'])
    pairs={}
    def add(a,b):
        key=(a['catalog_id'],b['catalog_id'])
        pairs[key]={'outbound':a,'inbound':b,'total_price_cny':round(a['price_cny']+b['price_cny'],2)}
    for a in out:
        b=next((b for b in back if compatible(a,b,query)),None)
        if b:add(a,b)
    for b in back:
        a=next((a for a in out if compatible(a,b,query)),None)
        if a:add(a,b)
    return flight_ranking.rank(list(pairs.values()),query)


def summary(catalog):
    legs=[*catalog['outbound'],*catalog['inbound']]
    return {'outbound_count':len(catalog['outbound']),'inbound_count':len(catalog['inbound']),
        'priced_count':sum(l['price_cny'] is not None for l in legs),
        'price_unresolved_count':sum(l['price_cny'] is None for l in legs),
        'airlines':sorted({airlines.segment_code(s) or s.get('airline','') for l in legs for s in l['segments']})}
