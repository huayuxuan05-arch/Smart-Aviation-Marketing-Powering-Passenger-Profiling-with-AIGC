"""Ordered priorities: airline, date, declared budgets/fare, stops, duration."""
from datetime import datetime
import airline_preferences as airlines

ORDER=['航空公司','起飞日期','预算符合情况与票价','中转次数','总耗时']


def rank(options,query):
    adults=query['adults'];cap=query.get('airfare_cap');total=query.get('trip_budget')
    def key(o):
        airline_penalty=0 if airlines.matches_option(o,query) else 1
        shift=abs((datetime.fromisoformat(o['outbound']['departure_time']).date()-datetime.fromisoformat(query['departure']).date()).days)
        per_leg_known=all(o[l].get('price_cny') is not None for l in ['outbound','inbound'])
        air_gap=max(0,max(o[l]['price_cny']/adults for l in ['outbound','inbound'])-cap) if cap is not None and per_leg_known else 0
        estimate=(o['total_price_cny']/adults+query.get('nonflight_total',0))*1.1
        total_gap=max(0,estimate-total) if total is not None else 0
        stops=sum(max(0,len(o[l]['segments'])-1) for l in ['outbound','inbound'])
        duration=sum((datetime.fromisoformat(o[l]['arrival_time'])-datetime.fromisoformat(o[l]['departure_time'])).total_seconds() for l in ['outbound','inbound'])
        return airline_penalty,shift,bool(air_gap or total_gap),air_gap+total_gap,o['total_price_cny'],stops,duration
    selected=sorted((o for o in options if airlines.matches_option(o,query) and
        all(len(o[l]['segments'])-1<=query.get('max_stops',1) and
            all(v.get('minutes',0)<=query.get('max_layover_hours',6)*60 for v in o[l].get('layovers',[]))
            for l in ['outbound','inbound']) and
        (query.get('budget_policy')!='只看预算内' or not key(o)[2] and
         (cap is None or all(o[l].get('price_cny') is not None for l in ['outbound','inbound'])))),key=key)
    for index,o in enumerate(selected):
        o['recommendation_rank']=index+1;o['date_deviation_days']=key(o)[1]
    return selected
