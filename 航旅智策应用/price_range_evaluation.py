"""Versioned budget-band scenarios; original holdout labels and quotes stay immutable."""
from __future__ import annotations
import argparse
import json
import math
from collections import Counter
from datetime import datetime
from pathlib import Path
import numpy as np
import independent_cohort as cohort
import flight_quotes as flights
from independent_evaluation import flight_key, query_for_user


def band(center,step=100):
    return dict(min=max(100,math.floor(center*.8/step)*step),
                max=math.ceil(center*1.2/step)*step,currency='CNY',
                semantics='target band; lower prices allowed, upper bound hard')


def classify(options,airfare,total,nonflight):
    affordable=[o for o in options if o['outbound']['price_cny']<=airfare['max'] and
        o['inbound']['price_cny']<=airfare['max'] and o['total_price_cny']+nonflight<=total['max']]
    preferred=[o for o in affordable if o['outbound']['price_cny']>=airfare['min'] and
        o['inbound']['price_cny']>=airfare['min'] and o['total_price_cny']+nonflight>=total['min']]
    if preferred:return 'within_target_band',min(preferred,key=lambda o:o['total_price_cny'])
    if affordable:return 'below_target_band',min(affordable,key=lambda o:o['total_price_cny'])
    if not options:return 'no_quote',None
    if not any(o['outbound']['price_cny']<=airfare['max'] and o['inbound']['price_cny']<=airfare['max'] for o in options):return 'airfare_above_max',None
    return 'trip_total_above_max',None


def combine_observed_legs(record,max_stops=1):
    """Recombine actual observed quotes, respecting same-day arrival and layovers."""
    query=record['query'];out=[];back=[]
    def valid(option,day):
        segments=option.get('segments',[])
        if not segments or len(segments)>max_stops+1 or not option.get('price_cny'):return False
        if not math.isfinite(option['price_cny']) or option['price_cny']<=0:return False
        if segments[0]['departure_time'][:10]!=day or segments[-1]['arrival_time'][:10]!=day:return False
        for segment in segments:
            if datetime.fromisoformat(segment['arrival_time'])<=datetime.fromisoformat(segment['departure_time']):return False
        for a,b in zip(segments,segments[1:]):
            duration=(datetime.fromisoformat(b['departure_time'])-datetime.fromisoformat(a['arrival_time'])).total_seconds()/60
            if a['destination_airport']!=b['origin_airport'] or not 30<=duration<=360:return False
        return True
    for observed in record.get('result',{}).get('leg_observations',[]):
        for option in observed.get('options',[]):
            if observed['date']==query['departure'] and valid(option,query['departure']):out.append(option)
            if observed['date']==query['return_date'] and valid(option,query['return_date']):back.append(option)
    pairs=[];seen=set()
    for o in out:
        for b in back:
            if o['origin']!=b['destination'] or o['destination']!=b['origin']:continue
            if datetime.fromisoformat(o['segments'][-1]['arrival_time'])>=datetime.fromisoformat(b['segments'][0]['departure_time']):continue
            key=tuple((s['flight_number'],s['departure_time']) for leg in [o,b] for s in leg['segments'])
            if key in seen:continue
            seen.add(key);pairs.append(dict(outbound=o,inbound=b,total_price_cny=o['price_cny']+b['price_cny']))
    return sorted(pairs,key=lambda o:o['total_price_cny'])


def run(root):
    root=Path(root);data,base,manifest=cohort.load(root/'test');users=data[1]
    latest=json.loads((root/'latest_flight_report.json').read_text(encoding='utf-8'))
    source=Path(latest['path']);destination=root/'budget-range-v1';destination.mkdir(exist_ok=True)
    records={}
    for path in source.glob('*.json'):
        if path.name=='report.json':continue
        record=json.loads(path.read_text(encoding='utf-8'));records[record['query_key']]=record
    profiles=[dict(user_id=u['user_id'],is_synthetic=True,
        one_way_airfare=band(u['airfare_cap'],50),adult_trip_budget=band(u['trip_budget']),
        simulated_range_source='80%-120% around original synthetic scenario center; not a real user response') for u in users]
    with (destination/'budget_ranges.jsonl').open('w',encoding='utf-8') as f:
        for p in profiles:f.write(json.dumps(p,ensure_ascii=False)+'\n')
    budget=data[0]['budget'];np.savez_compressed(destination/'annual_budget_ranges.npz',
        budget_min=np.where(np.isfinite(budget),np.maximum(100,np.floor(budget*.8/50)*50),np.nan),
        budget_max=np.where(np.isfinite(budget),np.ceil(budget*1.2/50)*50,np.nan))
    protocol=dict(version='budget-range-v1',original_test_manifest_sha256=cohort.digest(root/'test'/'manifest.json'),
        budget_profiles_sha256=cohort.digest(destination/'budget_ranges.jsonl'),
        annual_budget_ranges_sha256=cohort.digest(destination/'annual_budget_ranges.npz'),
        flight_source=str(source),flight_source_sha256=cohort.digest(source/'report.json'),
        policy='fixed original assumptions versus budget bands; upper bounds increase by predefined 20%, not learned from holdout outcomes',
        transfer_policy='one-stop alternatives are scenario comparisons requiring confirmation, not automatic acceptance',
        lower_bound='preferred spend, not a minimum that excludes cheaper options',
        evaluation_scope='budget policy comparison, not an improvement in demand prediction accuracy')
    cohort.write_json(destination/'protocol_before_scoring.json',protocol)
    alternatives={key:combine_observed_legs(r) for key,r in records.items()}
    scenarios={name:Counter() for name in ['fixed_direct','range_direct','range_one_stop_option']}
    rows=[];cache={}
    for u,p in zip(users,profiles):
        key=flight_key(query_for_user(u));record=records[key]
        direct=record.get('result',{}).get('options',[])
        nonflight=(u['days']-1)*260+u['days']*160+200
        tests=[('fixed_direct',direct,dict(min=0,max=u['airfare_cap']),dict(min=0,max=u['trip_budget'])),
               ('range_direct',direct,p['one_way_airfare'],p['adult_trip_budget']),
               ('range_one_stop_option',alternatives[key],p['one_way_airfare'],p['adult_trip_budget'])]
        row=dict(user_id=u['user_id'],observed_at=record['requested_at'],query_id=record['id'],is_synthetic=True)
        for name,options,air,total in tests:
            cachekey=(key,name,air['min'],air['max'],total['min'],total['max'],nonflight)
            if cachekey not in cache:cache[cachekey]=classify(options,air,total,nonflight)
            status,best=cache[cachekey];scenarios[name][status]+=1
            row[name]=dict(status=status,minimum_airfare_cny=best['total_price_cny'] if best else None)
        rows.append(row)
    result={}
    for name,counts in scenarios.items():
        feasible=counts['within_target_band']+counts['below_target_band']
        result[name]=dict(users=len(users),counts=dict(counts),feasible=feasible,match_rate=feasible/len(users))
    report=dict(protocol=protocol,scenarios=result,evaluated_at=flights.now(),
        quotes_fresh_at_evaluation=all(flights.is_fresh(r['requested_at']) for r in records.values()),
        warning='Snapshot comparison only; quote freshness must be rechecked before travel. One-stop availability is conditional, not accepted user demand.')
    cohort.write_json(destination/'report.json',report)
    with (destination/'traveler_results.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print('PRICE_RANGE_RESULT',json.dumps(result,ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);run(parser.parse_args().root)
