"""Replay timestamped current-flight batches with explicit prospective features."""
from __future__ import annotations
import argparse
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
import numpy as np
import independent_cohort as cohort
import independent_evaluation as evaluation
import flight_quotes as flights
import itinerary_ranking as itinerary
import marketing_ml as ml
from feasibility_benchmark import itinerary_for
from price_range_evaluation import band, combine_observed_legs


def run(root):
    root=Path(root).resolve(); output=root/'lambdamart-v1'; quotes=output/'quotes'
    if (output/'quote_audit.json').exists():
        print('QUOTE_BATCH_AUDIT_LOCKED',flush=True)
        return json.loads((output/'quote_audit.json').read_text(encoding='utf-8'))
    records=[]; sources=[]
    for filename in ['latest_flight_report.json','latest_alternative_flights.json']:
        latest=json.loads((quotes/filename).read_text(encoding='utf-8'))
        directory=Path(latest['path'])
        for path in sorted(directory.glob('*.json')):
            if path.name=='report.json': continue
            record=json.loads(path.read_text(encoding='utf-8'));records.append(record)
            sources.append(dict(file=str(path.relative_to(output)),sha256=cohort.digest(path),
                query_id=record['id'],status=record['status'],requested_at=record['requested_at']))
    asof=flights.now(); groups={}; leg_status=Counter(); query_status=Counter()
    for record in records:
        query_status[record['status']]+=1
        for leg in record.get('result',{}).get('leg_observations',[]): leg_status[leg.get('status','unknown')]+=1
        q=record['query']; days=(datetime.fromisoformat(q['return_date'])-datetime.fromisoformat(q['departure'])).days+1
        for option in combine_observed_legs(record,max_stops=1):
            candidate=dict(origin=q['origin'],destination=q['destinations'][0],start_date=q['departure'],
                max_stops=max(len(option['outbound']['segments'])-1,len(option['inbound']['segments'])-1),
                observed_at=record['requested_at'],query_id=record['id'],option=option)
            groups.setdefault((q['origin'],days),[]).append(candidate)
    # Cost frontier within departure/arrival time buckets: retain time diversity.
    # Dominated fares with the same city/date/stops/time buckets cannot increase coverage.
    reduced={}
    for condition, candidates in groups.items():
        buckets={}
        for c in candidates:
            def slot(leg,field):
                seg=c['option'][leg]['segments']; s=seg[0] if field=='departure_time' else seg[-1]
                return datetime.fromisoformat(s[field]).hour//6
            times=tuple(slot(leg,field) for leg in ['outbound','inbound'] for field in ['departure_time','arrival_time'])
            key=(c['destination'],c['start_date'],c['max_stops'],times)
            buckets.setdefault(key,[]).append(c)
        frontier=[]
        for candidates in buckets.values():
            candidates.sort(key=lambda c:(c['option']['outbound']['price_cny'],c['option']['inbound']['price_cny']))
            best=float('inf')
            for c in candidates:
                price=c['option']['inbound']['price_cny']
                if price<best: frontier.append(c);best=price
        reduced[condition]=frontier
    data,base,manifest=cohort.load(root/'test')
    s=ml.snapshot(manifest['behavior_end'],dataset=data,base_date=base,holidays=cohort.HOLIDAYS)
    scores=evaluation.frozen_scores(s,ml.model_pack());dindex={c:i for i,c in enumerate(data[3])}
    counts=Counter(); uncertain=0; total_rows=0; changes=Counter()
    with (output/'prospective_itinerary_features.jsonl').open('w',encoding='utf-8') as rows, (output/'traveler_plans.jsonl').open('w',encoding='utf-8') as plans:
        for j,u in enumerate(data[1]):
            p=dict(one_way_airfare=band(u['airfare_cap'],50),adult_trip_budget=band(u['trip_budget']),
                days=u['days'],destination=u['requested_destination'],start_date=u['start_date'])
            values=[]
            for c in reduced.get((u['usual_departure_city'],u['days']),[]):
                if abs((datetime.fromisoformat(c['start_date'])-datetime.fromisoformat(u['start_date'])).days)>3:continue
                values.append({**c,'interest_score':float(scores[j,dindex[c['destination']]])})
            # This batch is an auditable offline snapshot, not a purchasable offer.
            result=itinerary.rank(values,p,asof,allow_alternatives=True,offline_snapshot=True)
            state=itinerary.exploration_state(s,j);uncertain+=state['needs_preference_confirmation']
            counts[result['status']]+=1
            for candidate in result.get('alternatives',[]):
                features=itinerary.itinerary_features(candidate,p,asof)
                rows.write(json.dumps(dict(user_id=u['user_id'],is_synthetic=True,query_id=candidate['query_id'],
                    asof=asof,features=features,relevance_label=None,plan_adopted=None,
                    label_status='unobserved; do not fabricate purchase or adoption labels'),ensure_ascii=False)+'\n')
                total_rows+=1
            chosen=result.get('selected')
            if chosen:
                for key,changed in chosen['changes'].items():changes[key]+=int(changed)
                # Raw decoder payloads stay in the source batch; omit repeated raw rows here.
                chosen={**chosen,'option':{**chosen['option'],**{leg:{k:v for k,v in chosen['option'][leg].items() if k!='raw'} for leg in ['outbound','inbound']}}}
            plans.write(json.dumps(dict(user_id=u['user_id'],is_synthetic=True,original_conditions=p,
                status=result['status'],selected=chosen,accepted=False,uncertainty=state,
                daily_itinerary=itinerary_for(chosen,u['days'],fallback=u),
                requires_quote_refresh_before_use=True),ensure_ascii=False)+'\n')
    feasible=counts['original_conditions_feasible']+counts['alternative_requires_confirmation']
    report=dict(version='prospective-itinerary-features-v1',evaluated_at=asof,users=len(data[1]),
        counts=dict(counts),strict_budget_candidate_rate=feasible/len(data[1]),changes=dict(changes),
        prospective_feature_rows=total_rows,prospective_features=itinerary.FEATURES,
        query_snapshots=len(records),query_statuses=dict(query_status),leg_statuses=dict(leg_status),
        quotes_fresh_at_audit=all(flights.is_fresh(r['requested_at']) for r in records),
        empty_query_meaning='no usable roundtrip was returned in this query; not proof of no market flight',
        uncertain_users=uncertain,uncertain_users_removed_from_denominator=False,
        adoption_labels_observed=0,prices_used_as_historical_training_features=False,
        quote_change_is_not_model_gain=True,online_weights_replaced=False,
        budget_policy='unchanged predefined 80%-120% synthetic bands; strict upper bounds; no airfare reallocation',
        scope='8 representative original routes plus predefined date/city alternatives, not national inventory',
        nonflight_cost_basis='three declared scenario tiers plus 10% reserve; not merchant quotations',
        ranking_basis='production city-attention model retained because new learned model failed promotion gate',
        original_model_sha256=cohort.digest(ml.ROOT/'marketing_models.joblib'),
        sources=sources,artifacts={name:dict(sha256=cohort.digest(output/name),bytes=(output/name).stat().st_size)
            for name in ['traveler_plans.jsonl','prospective_itinerary_features.jsonl']})
    cohort.write_json(output/'quote_audit.json',report)
    print('PROSPECTIVE_QUOTE_AUDIT',json.dumps({k:v for k,v in report.items() if k not in ['sources','prospective_features']},ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);run(p.parse_args().root)
