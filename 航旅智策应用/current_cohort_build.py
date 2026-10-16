"""Build annual cohorts conditioned on successful current flight queries only.

User policy: unsuccessful queries, responses and logs are not retained. All
active users must join a fresh successful roundtrip quote at activation time.
This is a curated test population, never a claim of unconditional coverage.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timedelta
from pathlib import Path
import independent_cohort as cohort
import flight_quotes as flights
from data_layer import CST,RUNTIME

ROUTES=[('武汉','上海'),('杭州','西安'),('西安','厦门'),('重庆','广州'),('南京','成都'),('长沙','北京')]


def quote(query):
    """No failed data is written or printed, including provider diagnostics."""
    for _ in range(3):
        started=flights.now()
        try:
            result=flights._search(query)
            if flights.result_status(result)=='success':
                return dict(id='LIVE_'+uuid.uuid4().hex,query=query,
                    query_key=hashlib.sha256(flights.query_key(query).encode()).hexdigest(),
                    requested_at=started,finished_at=flights.now(),status='success',result=flights.successful_result(result))
        except Exception:pass
    return None


def contexts_for(records,departure):
    return [dict(query=r['query'],query_key=r['query_key']) for r in records if r['query']['departure']==departure]


def build(directory,anchor,counts=(10000,2000,10000),export_behaviors=True):
    directory=Path(directory).resolve();directory.mkdir(parents=True,exist_ok=True)
    if (directory/'acceptance.json').exists():raise ValueError('Use a new immutable cohort version')
    base=datetime.fromisoformat(anchor).date();departures=[(base+timedelta(days=x)).isoformat() for x in [7,14,21]]
    query_directory=directory/'successful-quotes';query_directory.mkdir(exist_ok=True)
    queries=[]
    for origin,destination in ROUTES:
        for departure in departures:
            for days in [3,5]:
                end=(datetime.fromisoformat(departure)+timedelta(days=days-1)).date().isoformat()
                queries.append(flights.query_for(dict(origin=origin,destination=destination,start_date=departure,end_date=end),dict(adults=1,max_stops=1)))
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(quote,q) for q in queries]):
            record=future.result()
            if record:
                records.append(record);cohort.write_json(query_directory/(record['query_key']+'.json'),record)
                print('VERIFIED_CURRENT_ROUNDTRIP_CONTEXTS',len(records),flush=True)
    contexts={name:contexts_for(records,date) for name,date in zip(['training','validation','test'],departures)}
    if any(len(v)<2 for v in contexts.values()):
        raise ValueError('Insufficient verified conditions; no active dataset is published')
    protocol=dict(version='current-queryable-cohorts-v2',anchor=anchor,
        population='synthetic users conditioned on successful current flight searches',
        admission='fresh complete roundtrip quote; budget is a soft preference',
        flight_prices_backfilled_into_past_behavior=False,retention='successful queries only; no failed logs or responses',
        splits={name:dict(users=count,seed=cohort.SEED+100+i,contexts=contexts[name])
            for i,(name,count) in enumerate(zip(contexts,counts))},
        split_independence='distinct user IDs, seeds and departure-date query groups',
        interpretation='100% queryable at acceptance is a sampling condition, not recommendation accuracy or real-population coverage')
    cohort.write_json(directory/'protocol.json',protocol)
    for i,(name,count) in enumerate(zip(contexts,counts)):
        cohort.generate(directory/name,count,'live_v2_'+name,anchor,seed=cohort.SEED+100+i,
            export_behaviors=export_behaviors,flight_contexts=contexts[name])
        print('ANNUAL_COHORT_READY',name,count,count*365,flush=True)
    # Refresh every shared query after annual generation, then require freshness.
    current={r['query_key']:r for r in records}
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(quote,r['query']) for r in records]):
            record=future.result()
            if record:
                current[record['query_key']]=record;cohort.write_json(query_directory/(record['query_key']+'.json'),record)
    if not all(flights.is_fresh(r['requested_at']) for r in current.values()):
        raise ValueError('At least one admitted condition has no fresh successful quote; activation refused')
    return activate(directory,protocol,current)


def refresh(directory):
    """Refresh successful observations without changing user IDs or behavior labels."""
    directory=Path(directory).resolve()
    protocol=json.loads((directory/'protocol.json').read_text(encoding='utf-8'))
    current={}
    records=[json.loads(p.read_text(encoding='utf-8')) for p in (directory/'successful-quotes').glob('*.json')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(quote,r['query']) for r in records]):
            record=future.result()
            if record:
                current[record['query_key']]=record
                cohort.write_json(directory/'successful-quotes'/(record['query_key']+'.json'),record)
                print('CURRENT_QUOTES_REFRESHED',len(current),flush=True)
    # Never reuse a previous successful response as evidence of a new query.
    return activate(directory,protocol,current)


def activate(directory,protocol,current):
    directory=Path(directory);all_ids=set();used_queries=set();splits={}
    for name,spec in protocol['splits'].items():
        users=[json.loads(line) for line in (directory/name/'users.jsonl').read_text(encoding='utf-8').splitlines()]
        manifest=json.loads((directory/name/'manifest.json').read_text(encoding='utf-8'))
        if len(users)!=spec['users'] or manifest['behavior_days']!=365:raise ValueError('Population or annual window mismatch')
        for filename,artifact in manifest['files'].items():
            if cohort.digest(directory/name/filename)!=artifact['sha256']:raise ValueError('Cohort fingerprint mismatch')
        ids={u['user_id'] for u in users}
        if all_ids&ids:raise ValueError('User leakage between active splits')
        all_ids|=ids
        keys={u['current_flight_query_key'] for u in users}
        if used_queries&keys:raise ValueError('Flight condition leakage between active splits')
        used_queries|=keys
        for u in users:
            if u['current_flight_query_key'] not in current:raise ValueError('A user has no newly verified quote')
            r=current[u['current_flight_query_key']];q=r['query']
            if r['status']!='success' or not r['result'].get('options') or not flights.is_fresh(r['requested_at']):
                raise ValueError('A user has no current complete roundtrip quote')
            if (u['usual_departure_city'],u['requested_destination'],u['start_date'])!=(q['origin'],q['destinations'][0],q['departure']):
                raise ValueError('User and quote condition mismatch')
            if u['days']!=(datetime.fromisoformat(q['return_date'])-datetime.fromisoformat(q['departure'])).days+1:
                raise ValueError('Trip duration mismatch')
            if q['adults']!=1 or q['max_stops']!=u['allowed_max_stops']:raise ValueError('Party or stop constraint mismatch')
        splits[name]=dict(users=len(users),users_with_verified_current_quotes=len(users),
            verified_query_conditions=len(keys),behavior_days=365,behavior_rows=len(users)*365,
            manifest_sha256=cohort.digest(directory/name/'manifest.json'),queryable_rate_at_acceptance=1.0)
    acceptance=dict(version=protocol['version'],verified_at=flights.now(),splits=splits,
        query_snapshots=len(used_queries),all_admitted_quotes_fresh=True,
        unsuccessful_query_details_retained=False,conditioned_sampling=True,
        meaning='Every active synthetic user joins a fresh successful observed quote; not permanent availability or 100% budget compliance',
        sources={key:dict(quote_id=current[key]['id'],observed_at=current[key]['requested_at'],
            sha256=cohort.digest(directory/'successful-quotes'/(key+'.json'))) for key in used_queries})
    cohort.write_json(directory/'acceptance.json',acceptance)
    active=dict(version=protocol['version'],root=str(directory.resolve()),verified_at=acceptance['verified_at'],
        acceptance_sha256=cohort.digest(directory/'acceptance.json'),budget_policy='prefer')
    active_path=RUNTIME/'current-cohorts'/'active.json';active_path.parent.mkdir(parents=True,exist_ok=True)
    cohort.write_json(active_path,active)
    print('CURRENT_COHORTS_ACTIVATED',json.dumps(splits,ensure_ascii=False),flush=True)
    return acceptance


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path)
    p.add_argument('--anchor',default=datetime.now(CST).date().isoformat());p.add_argument('--refresh',action='store_true');args=p.parse_args()
    if args.refresh:refresh(args.directory)
    else:build(args.directory,args.anchor)
