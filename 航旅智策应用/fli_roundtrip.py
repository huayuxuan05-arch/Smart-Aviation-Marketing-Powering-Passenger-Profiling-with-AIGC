"""Google's native round-trip shopping: outbound first, then selected returns."""
from datetime import date,datetime,timedelta
import asyncio,copy
from urllib.parse import urlencode
import airline_preferences as airlines
import flight_catalog


def filters(query,outbound=None):
    from adv_search_flights.search.engine import resolve_airports
    from fli.core import build_flight_segments,parse_cabin_class,parse_max_stops,parse_sort_by,parse_airlines,resolve_airport
    from fli.models import FlightSearchFilters,PassengerInfo,FlightResult,FlightLeg
    origin=[resolve_airport(a) for a in resolve_airports(query['origin'])]
    destination=[resolve_airport(a) for a in resolve_airports(query['destinations'][0])]
    start=outbound['departure_time'][:10] if outbound else query['departure']
    shift=(date.fromisoformat(start)-date.fromisoformat(query['departure'])).days
    end=(date.fromisoformat(query['return_date'])+timedelta(days=shift)).isoformat()
    segments,trip_type=build_flight_segments(origin=origin,destination=destination,departure_date=start,return_date=end,time_restrictions=None)
    if outbound:
        legs=[]
        for item in outbound['segments']:
            code=airlines.segment_code(item)
            departure=datetime.fromisoformat(item['departure_time']);arrival=datetime.fromisoformat(item['arrival_time'])
            legs.append(FlightLeg(airline=parse_airlines([code])[0],flight_number=item['flight_number'][len(code):],
                departure_airport=resolve_airport(item['origin_airport']),arrival_airport=resolve_airport(item['destination_airport']),
                departure_datetime=departure,arrival_datetime=arrival,duration=max(1,int((arrival-departure).total_seconds()/60))))
        segments[0].selected_flight=FlightResult(legs=legs,duration=sum(l.duration for l in legs),stops=len(legs)-1)
    return FlightSearchFilters(trip_type=trip_type,passenger_info=PassengerInfo(adults=query['adults']),
        flight_segments=segments,stops=parse_max_stops('ANY'),seat_type=parse_cabin_class(query['cabin_class']),
        sort_by=parse_sort_by('CHEAPEST'),show_all_results=True)


def fetch(query,outbound=None):
    import flight_quotes as quotes
    from adv_search_flights.search.engine import resolve_airports
    observation={'observed_at':quotes.now(),'cabin':query['cabin_class'],'catalog':[],
        'direction':'inbound' if outbound else 'outbound','price_basis':'native_roundtrip_total' if outbound else 'native_roundtrip_from'}
    try:
        selected=filters(query,outbound)
        parsed=quotes._google_request(selected,observation)
        origins=resolve_airports(query['destinations'][0] if outbound else query['origin'])
        destinations=resolve_airports(query['origin'] if outbound else query['destinations'][0])
        target=selected.flight_segments[1 if outbound else 0].travel_date
        catalog=[row[1] for row in parsed if row[1]['origin_airport'] in origins and row[1]['destination_airport'] in destinations
            and row[1]['departure_time'][:10]==target]
        for leg in catalog:
            leg['price_basis']=observation['price_basis']
            # The provider's single-leg purchase link loses the return date.
            leg['google_url']='https://www.google.com/travel/flights?'+urlencode({'hl':'zh-CN','curr':'CNY',
                'q':f"Flights from {query['origin']} to {query['destinations'][0]} on {selected.flight_segments[0].travel_date} returning {selected.flight_segments[1].travel_date} {query['adults']} adults economy"})
        observation['catalog']=flight_catalog.deduplicate(catalog)
    except Exception as error:observation.update(status='failed',error_code=type(error).__name__)
    return observation


def initial(query):
    import flight_quotes as quotes
    from adv_search_flights.search.engine import resolve_airports
    async def search():
        gate=asyncio.Semaphore(2)
        async def day(offset):
            changed={**query,'departure':(date.fromisoformat(query['departure'])+timedelta(days=offset)).isoformat(),
                'return_date':(date.fromisoformat(query['return_date'])+timedelta(days=offset)).isoformat()}
            if date.fromisoformat(changed['departure'])<datetime.now(quotes.CST).date():return None
            async with gate:return await asyncio.to_thread(fetch,changed)
        return [r for r in await asyncio.gather(*(day(o) for o in range(-query.get('date_flex_days',0),query.get('date_flex_days',0)+1))) if r]
    observed=asyncio.run(search())
    catalog={'outbound':flight_catalog.deduplicate([leg for row in observed for leg in row['catalog']]),'inbound':[]}
    partial=any(row.get('status')=='failed' or row.get('parse_failures') for row in observed)
    return {'source':quotes.SOURCE,'options':[],'native_roundtrip':True,'catalog':catalog,'leg_observations':observed,
        'coverage':{**flight_catalog.summary(catalog),'partial':partial,'scope':'google_returned_roundtrip_inventory',
            'airports':{'origin':resolve_airports(query['origin']),'destination':resolve_airports(query['destinations'][0])},
            'completed_airport_queries':len(observed),'search_version':flight_catalog.VERSION},
        'query_quality':{'incomplete':partial},
        'fare_basis':'Google返回的所选成人数往返总价；按实际报价币种换算人民币，未拆分单程金额。最终价格及可售性以预订页为准。'}


def returns(query,outbound):
    row=fetch(query,outbound);options=[];catalog=row['catalog']
    for leg in catalog:
        if leg.get('price_cny') is None or not flight_catalog.compatible(outbound,leg,query):continue
        out=copy.deepcopy(outbound);back=copy.deepcopy(leg);out['price_cny']=back['price_cny']=None
        options.append({'outbound':out,'inbound':back,'total_price_cny':leg['price_cny'],
            'quote_kind':'native_roundtrip','fare_conversion':copy.deepcopy(leg.get('conversion')),
            'original_total':leg.get('original_price'),'original_currency':leg.get('original_currency')})
    return {'catalog':catalog,'options':options,'partial':row.get('status')=='failed' or bool(row.get('parse_failures')),
        'observed_at':row['observed_at']}


def quote_selected(query,outbound,inbound,catalog):
    """Resolve a single pair using Google's returned booking token in memory only."""
    import flight_quotes as quotes
    import fx_rates
    from fli.search import SearchFlights
    from fli.search._urls import with_locale_params
    from fli.search._wire import iter_wrb_chunks
    from fli.search._decoders import parse_booking_chunk
    selected=filters(query,outbound)
    observed={'observed_at':quotes.now(),'cabin':query['cabin_class']}
    rows=quotes._google_request(selected,observed)
    found=next((row for row in rows if flight_catalog.identity(row[1])==flight_catalog.identity(inbound)),None)
    if found is None:raise ValueError('当前返程结果已变化，请重新选择去程')
    returning=found[0];client=SearchFlights()
    if not returning.booking_token:raise ValueError('当前接口未返回该组合的报价凭据，请到 Google 核验')
    selected.flight_segments[1].selected_flight=returning
    encoded=client._encode_booking_payload(returning.booking_token,selected)
    response=client.client.post(url=with_locale_params(client.BOOKING_URL,'CNY','zh-CN','CN'),
        data='f.req='+encoded,impersonate='chrome',allow_redirects=True,timeout=15,
        proxy=quotes.configured_proxy(),verify=quotes.certificate_bundle())
    response.raise_for_status()
    offers=[offer for chunk in iter_wrb_chunks(response.content) for offer in parse_booking_chunk(chunk)]
    amounts=[]
    for offer in offers:
        try:amounts.append(fx_rates.convert(offer.price,offer.currency))
        except (ValueError,TypeError,AttributeError):continue
    result={'catalog':copy.deepcopy(catalog),'options':[],'partial':False,'observed_at':observed['observed_at']}
    if not amounts:return result
    conversion=min(amounts,key=lambda v:v['amount_cny'])
    leg=next(l for l in result['catalog'] if l['catalog_id']==inbound['catalog_id'])
    leg.update(price_cny=conversion['amount_cny'],price_basis='native_roundtrip_total',quote_status='priced',
        original_price=conversion['original_amount'],original_currency=conversion['original_currency'],conversion=conversion)
    out=copy.deepcopy(outbound);back=copy.deepcopy(leg);out['price_cny']=back['price_cny']=None
    result['options']=[{'outbound':out,'inbound':back,'total_price_cny':leg['price_cny'],
        'quote_kind':'native_roundtrip','fare_conversion':conversion,'original_total':leg['original_price'],
        'original_currency':leg['original_currency']}]
    return result
