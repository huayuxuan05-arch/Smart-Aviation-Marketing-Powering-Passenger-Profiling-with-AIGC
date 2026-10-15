"""Live alternative routes/dates and constraint-first recommendation evaluation."""
from __future__ import annotations
import argparse
import copy
import json
import uuid
import numpy as np
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
from pathlib import Path
import independent_cohort as cohort
from independent_evaluation import flight_key,query_for_user
from price_range_evaluation import combine_observed_legs
from constraint_planner import optimize,propose_reallocation
import flight_quotes as flights
import marketing_ml as ml
from independent_evaluation import frozen_scores
from travel_planner import PLACES

ALTERNATIVE_CITIES={'北京':['西安','太原'],'深圳':['重庆','武汉'],'成都':['西安','昆明']}


def itinerary_for(selected,days,fallback=None):
    if not selected:
        if not fallback:return []
        selected=dict(destination=fallback['requested_destination'],start_date=fallback['start_date'],
            option=dict(outbound=dict(segments=[]),inbound=dict(segments=[])))
    city=selected['destination'];points=PLACES.get(city,[]);start=datetime.fromisoformat(selected['start_date'])
    result=[]
    for i in range(days):
        date=(start+timedelta(days=i)).date().isoformat()
        if i==0:
            segments=selected['option']['outbound']['segments']
            activities=[dict(activity='抵达与入住（时刻待匹配航班后确认）',flight_arrival=segments[-1]['arrival_time'] if segments else None),
                dict(activity='按抵达时刻安排周边餐饮与休息')]
        elif i==days-1:
            segments=selected['option']['inbound']['segments']
            activities=[dict(activity='退房与返程（时刻待匹配航班后确认）',flight_departure=segments[0]['departure_time'] if segments else None)]
        else:
            activities=[dict(activity=points[(i-1)%len(points)] if points else '市区游览',status='候选地点，开放预约待核验'),
                dict(activity='午餐与休息'),dict(activity=points[i%len(points)] if points else '周边漫游',status='可按体力调整')]
        result.append(dict(day=i+1,date=date,activities=activities))
    return result


def alternative_queries(users):
    queries={}
    for u in users:
        query=query_for_user(u)
        for city in ALTERNATIVE_CITIES.get(u['usual_departure_city'],[]):
            q={**query,'destinations':[city],'max_stops':1};queries[flight_key(q)]=q
        if u['usual_departure_city'] in ALTERNATIVE_CITIES:
            q={**query,'departure':(datetime.fromisoformat(query['departure'])+timedelta(days=3)).date().isoformat(),
               'return_date':(datetime.fromisoformat(query['return_date'])+timedelta(days=3)).date().isoformat(),'max_stops':1}
            queries[flight_key(q)]=q
    return queries


def collect(root):
    root=Path(root);users=list(map(json.loads,(root/'test'/'users.jsonl').read_text(encoding='utf-8').splitlines()))
    queries=alternative_queries(users);flights.configured_proxy()
    from data_layer import CST
    if any(datetime.fromisoformat(q['departure']).date()<datetime.now(CST).date() for q in queries.values()):
        raise ValueError('Alternative travel dates have passed; generate a new cohort version')
    run=root/'alternative-flights'/datetime.now().strftime('%Y%m%dT%H%M%S');run.mkdir(parents=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        def one(key,q):
            value=dict(id='ALT_'+uuid.uuid4().hex,query_key=key,query=q,requested_at=flights.now())
            try:
                result=flights._search(q);value.update(result=result,status='success' if result['options'] else 'empty')
            except Exception as exc:value.update(status='failed',error_code=type(exc).__name__)
            value['finished_at']=flights.now();return key,value
        pending=[pool.submit(one,key,q) for key,q in queries.items()];counts=Counter()
        for future in as_completed(pending):
            key,value=future.result();cohort.write_json(run/(key+'.json'),value);counts[value['status']]+=1
            print('ALTERNATIVE_QUOTE',sum(counts.values()),len(queries),value['status'],value['query']['origin'],value['query']['destinations'],value['query']['departure'],flush=True)
    cohort.write_json(root/'latest_alternative_flights.json',dict(path=str(run.resolve()),unique_queries=len(queries),statuses=dict(counts),collected_at=flights.now()))
    print('ALTERNATIVE_COLLECTION_COMPLETE',dict(counts),flush=True)


def evaluate(root):
    root=Path(root);users=list(map(json.loads,(root/'test'/'users.jsonl').read_text(encoding='utf-8').splitlines()))
    ranges={p['user_id']:p for p in map(json.loads,(root/'budget-range-v1'/'budget_ranges.jsonl').read_text(encoding='utf-8').splitlines())}
    records=[]
    for name in ['latest_flight_report.json','latest_alternative_flights.json']:
        latest=json.loads((root/name).read_text(encoding='utf-8'))
        for path in Path(latest['path']).glob('*.json'):
            if path.name!='report.json':records.append(json.loads(path.read_text(encoding='utf-8')))
    by_condition={}
    for record in records:
        q=record['query'];days=(datetime.fromisoformat(q['return_date'])-datetime.fromisoformat(q['departure'])).days+1
        # Expanded alternatives use only actual collected leg quotes.
        options=combine_observed_legs(record,max_stops=1)
        for option in options:
            candidate=dict(origin=q['origin'],destination=q['destinations'][0],start_date=q['departure'],
                max_stops=max(len(option['outbound']['segments'])-1,len(option['inbound']['segments'])-1),
                option=option,query_id=record['id'],observed_at=record['requested_at'],interest_score=0)
            by_condition.setdefault((q['origin'],days),[]).append(candidate)
    # Pareto prune by leg prices for each date/city/stops; both upper bounds stay hard.
    reduced={}
    for key,values in by_condition.items():
        groups={}
        for v in values:groups.setdefault((v['destination'],v['start_date'],v['max_stops']),[]).append(v)
        kept=[]
        for group in groups.values():
            group.sort(key=lambda v:(v['option']['outbound']['price_cny'],v['option']['inbound']['price_cny']))
            best=float('inf')
            for v in group:
                incoming=v['option']['inbound']['price_cny']
                if incoming<best:kept.append(v);best=incoming
        reduced[key]=kept
    data,base,manifest=cohort.load(root/'test')
    snapshot=ml.snapshot(manifest['behavior_end'],dataset=data,base_date=base,holidays=cohort.HOLIDAYS)
    demand=frozen_scores(snapshot,ml.model_pack())
    minimum=demand.min(axis=1,keepdims=True);maximum=demand.max(axis=1,keepdims=True)
    demand=(demand-minimum)/np.maximum(maximum-minimum,1e-8)
    city_index={city:i for i,city in enumerate(data[3])}
    output=root/'constraint-first-v1';output.mkdir(exist_ok=True);counts=Counter();rows=[]
    with (output/'traveler_plans.jsonl').open('w',encoding='utf-8') as f:
        for j,u in enumerate(users):
            pr={**ranges[u['user_id']],'days':u['days'],'destination':u['requested_destination'],'start_date':u['start_date']}
            candidates=[]
            for original in reduced.get((u['usual_departure_city'],u['days']),[]):
                gap=abs((datetime.fromisoformat(original['start_date'])-datetime.fromisoformat(u['start_date'])).days)
                if gap>3:continue
                candidate={**original,'interest_score':float(demand[j,city_index[original['destination']]])}
                candidate['option']={**candidate['option'],**{leg:{k:v for k,v in candidate['option'][leg].items() if k!='raw'} for leg in ['outbound','inbound']}}
                candidates.append(candidate)
            result=optimize(candidates,pr,allow_alternatives=True);counts[result['status']]+=1
            reallocation=propose_reallocation(candidates,pr) if not result.get('selected') else None
            if reallocation:counts['additional_budget_reallocation_proposals']+=1
            # Explicitly pending: changing travel preferences is never a silent acceptance.
            value=dict(user_id=u['user_id'],is_synthetic=True,original_conditions=pr,
                budget_reallocation_proposal=reallocation,
                daily_itinerary=itinerary_for(result.get('selected') or reallocation,u['days'],fallback=u),**result)
            f.write(json.dumps(value,ensure_ascii=False)+'\n')
            selected=result.get('selected')
            rows.append(dict(user_id=u['user_id'],status=result['status'],destination=selected['destination'] if selected else None,
                date=selected['start_date'] if selected else None,estimated_total=selected['estimated_total'] if selected else None))
    feasible=counts['original_conditions_feasible']+counts['alternative_requires_confirmation']
    report=dict(users=len(users),method='constraint-first exact cost scenarios and observed flight Pareto frontier',
        counts=dict(counts),candidate_solution_rate=feasible/len(users),
        original_conditions_rate=counts['original_conditions_feasible']/len(users),
        alternative_proposal_rate=counts['alternative_requires_confirmation']/len(users),
        additional_reallocation_proposal_rate=counts['additional_budget_reallocation_proposals']/len(users),
        any_candidate_proposal_rate=(feasible+counts['additional_budget_reallocation_proposals'])/len(users),
        unique_query_snapshots=len(records),strict_budget_upper_bounds_relaxed=False,
        reallocation_proposals_change_airfare_band=True,reallocation_proposals_raise_total_upper=False,
        changed_preferences_accepted=False,date_flexibility_days=3,
        quote_scope='actual snapshots for specified representative routes; not whole-market flight inventory',
        nonflight='three explicit scenario cost tiers plus 10% reserve; not merchant quotations',
        preference_scores='per-user dynamic features as of latest complete synthetic behavior day; frozen model unchanged',
        interpretation='candidate solutions with date/city/stop/cost changes require user confirmation; not bookings or conversion')
    cohort.write_json(output/'report.json',report)
    with (output/'summary.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print('CONSTRAINT_FIRST_RESULT',json.dumps(report,ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['collect','evaluate','all']);p.add_argument('root',type=Path)
    args=p.parse_args()
    if args.command in ('collect','all'):collect(args.root)
    if args.command in ('evaluate','all'):evaluate(args.root)
