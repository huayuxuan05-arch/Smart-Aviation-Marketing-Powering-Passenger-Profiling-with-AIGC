"""Annual new-user holdout evaluation and timestamped live flight feasibility checks."""
from __future__ import annotations
import argparse
import hashlib
import csv
import json
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
import independent_cohort as cohort
import marketing_ml as ml
import flight_quotes as flights
from data_layer import CST, RUNTIME


def cutoff_dates(anchor, offsets):
    end=datetime.fromisoformat(anchor)-timedelta(days=1)
    return [(end-timedelta(days=x)).date().isoformat() for x in offsets]


def frozen_scores(s, pack):
    x=s['X'].reshape(-1,len(ml.FEATURES));model=pack['models'][pack['selected']]
    if pack['selected']!='boost':x=pack['scaler'].transform(x)
    return model.predict_proba(x)[:,1].reshape(s['X'].shape[:2])


def rule_scores(s):
    return {'近30天频次':s['X'][:,:,1], '14天衰减':s['X'][:,:,3],
            '近7天频次':s['X'][:,:,0],
            '短期变化规则':.6*s['X'][:,:,0]+.3*s['X'][:,:,1]+.1*s['X'][:,:,3]}


def score_sets(dataset, base, cutoffs, pack, candidate=None):
    labels=[];scores={}
    for snapshot,target in cohort.snapshots(dataset,base,cutoffs):
        labels.append(target['continue'])
        values={'原冻结模型':frozen_scores(snapshot,pack),**rule_scores(snapshot)}
        if candidate is not None:
            x=snapshot['X'];values['新数据梯度提升']=candidate.predict_proba(x.reshape(-1,len(ml.FEATURES)))[:,1].reshape(x.shape[:2])
        for name,value in values.items():scores.setdefault(name,[]).append(value)
    y=np.stack(labels)
    stacked={name:np.stack(parts) for name,parts in scores.items()}
    metrics={name:ml.ranking_metrics(y.reshape(-1,y.shape[-1]),value.reshape(-1,y.shape[-1])) for name,value in stacked.items()}
    return y,stacked,metrics


def individual_ndcg(y, scores):
    order=np.argsort(-scores,axis=-1,kind='stable')[...,:3]
    rel=np.take_along_axis(y,order,axis=-1);discount=1/np.log2(np.arange(2,5))
    count=y.sum(axis=-1);ideal=np.array([discount[:min(int(n),3)].sum() for n in count.ravel()]).reshape(count.shape)
    values=np.divide((rel*discount).sum(axis=-1),ideal,out=np.full(count.shape,np.nan),where=ideal>0)
    valid=np.isfinite(values);total=np.nansum(values,axis=0);n=valid.sum(axis=0)
    return np.divide(total,n,out=np.full(n.shape,np.nan),where=n>0)


def needs_retraining(metrics):
    original=metrics['原冻结模型']
    best=max((n for n in metrics if n!='原冻结模型'),key=lambda n:metrics[n]['ndcg_at_3'])
    return (original['ndcg_at_3']+.005<metrics[best]['ndcg_at_3'] or
            original['recall_at_3']+.01<metrics[best]['recall_at_3'])


def choose_method(metrics):
    floor=metrics['原冻结模型']['recall_at_3']-.005
    allowed=[n for n in metrics if metrics[n]['recall_at_3']>=floor]
    return max(allowed,key=lambda n:metrics[n]['ndcg_at_3'])


def evaluate(root, anchor):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    if (root/'evaluation_report.json').exists():
        print('LOCKED_REPORT_EXISTS: reuse result; do not retune on held-out users',flush=True)
        return json.loads((root/'evaluation_report.json').read_text(encoding='utf-8'))
    cohort.generate(root/'test',10000,'test',anchor,export_behaviors=True)
    cohort.generate(root/'validation',2000,'validation',anchor,seed=cohort.SEED+1,export_behaviors=False)
    protocol=dict(version='annual-new-user-eval-v1',anchor=anchor,seed=cohort.SEED,
        training_cutoffs=cutoff_dates(anchor,[270,240,210,180,150,120]),
        validation_cutoffs=cutoff_dates(anchor,[90,60,30]),test_cutoffs=cutoff_dates(anchor,[67,37,7]),
        horizon_days=7,features=ml.FEATURES,test_users=10000,test_rows=3650000,
        outcome='future 7-day repeated destination attention, not bookings',
        selection='validation users only; final test evaluated once after selection',
        retrain_trigger='original validation NDCG@3 trails best rule by >0.005, or Recall@3 by >0.01',
        replacement='best validation NDCG@3 with Recall@3 no worse than original by 0.005',
        uncertainty='paired bootstrap of users; each user retains all 3 snapshots',
        synthetic_limit='generated retrospective behavior is not actual year-long observation',
        flights='independent current feasibility checks, never a feature or future-attention label',
        original_model_sha256=cohort.digest(ml.ROOT/'marketing_models.joblib'),
        frozen_test_manifest_sha256=cohort.digest(root/'test'/'manifest.json'))
    cohort.write_json(root/'protocol.json',protocol)
    pack=ml.model_pack();validation,base,vm=cohort.load(root/'validation')
    vy,vs,metrics=score_sets(validation,base,protocol['validation_cutoffs'],pack)
    weak=needs_retraining(metrics)
    candidate=None;train_info={'performed':False}
    print('VALIDATION',json.dumps(metrics,ensure_ascii=False),'retrain',weak,flush=True)
    if weak:
        cohort.generate(root/'training',6000,'training',anchor,seed=cohort.SEED+2,export_behaviors=False)
        training,tbase,tm=cohort.load(root/'training');xs=[];ys=[]
        for snap,target in cohort.snapshots(training,tbase,protocol['training_cutoffs']):
            xs.append(snap['X'].reshape(-1,len(ml.FEATURES)));ys.append(target['continue'].ravel())
        x=np.concatenate(xs);y=np.concatenate(ys)
        print('RETRAIN',x.shape,flush=True);started=time.monotonic()
        candidate=HistGradientBoostingClassifier(max_iter=50,max_leaf_nodes=15,max_bins=64,
            learning_rate=.1,l2_regularization=3,early_stopping=False,random_state=cohort.SEED).fit(x,y)
        joblib.dump(candidate,root/'candidate_model.joblib',compress=3)
        train_info=dict(performed=True,users=6000,pair_rows=len(x),seconds=round(time.monotonic()-started,2),
            sha256=cohort.digest(root/'candidate_model.joblib'),test_users_used=0)
        vy,vs,metrics=score_sets(validation,base,protocol['validation_cutoffs'],pack,candidate)
        del x,y,xs,ys,training
    chosen=choose_method(metrics)
    selection=dict(method=chosen,validation=metrics,retraining=train_info,
        frozen_protocol_sha256=cohort.digest(root/'protocol.json'),test_access='not yet scored')
    cohort.write_json(root/'selection_before_test.json',selection)
    del vy,vs,validation
    test,base,manifest=cohort.load(root/'test')
    test_ids={u['user_id'] for u in test[1]}
    for split in ['validation','training']:
        if (root/split/'users.jsonl').exists():
            others={json.loads(line)['user_id'] for line in (root/split/'users.jsonl').read_text(encoding='utf-8').splitlines()}
            if test_ids&others:raise ValueError('Held-out and development users overlap')
    y,scores,test_metrics=score_sets(test,base,protocol['test_cutoffs'],pack,candidate)
    user_delta=individual_ndcg(y,scores[chosen])-individual_ndcg(y,scores['原冻结模型'])
    rng=np.random.default_rng(cohort.SEED+30);samples=[]
    for _ in range(500):samples.append(float(np.nanmean(user_delta[rng.integers(0,len(user_delta),len(user_delta))])))
    groups=np.array([u['scenario'] for u in test[1]])
    by_group={}
    for group in cohort.SCENARIOS:
        mask=groups==group;gy=y[:,mask]
        by_group[group]={name:ml.ranking_metrics(gy.reshape(-1,gy.shape[-1]),value[:,mask].reshape(-1,gy.shape[-1])) for name,value in scores.items() if name in {chosen,'原冻结模型'}}
    permutation=rng.permutation(len(test[1]));control=ml.ranking_metrics(y[:,permutation].reshape(-1,y.shape[-1]),scores[chosen].reshape(-1,y.shape[-1]))
    report=dict(protocol=protocol,cohort=manifest,selection=selection,test=test_metrics,
        selected_method=chosen,paired_ndcg_delta=float(np.nanmean(user_delta)),
        paired_ndcg_delta_95pct=list(map(float,np.quantile(samples,[.025,.975]))),
        subgroups=by_group,shuffled_user_negative_control=control,
        old_model_unchanged=cohort.digest(ml.ROOT/'marketing_models.joblib')==protocol['original_model_sha256'],
        result_scope='independent synthetic new users; not real behavior, sales, conversion or ROI',
        deployment='original 2024 replay model preserved; recommended method versioned for new-cohort evaluation')
    cohort.write_json(root/'evaluation_report.json',report)
    print('TEST_RESULT',json.dumps(test_metrics,ensure_ascii=False),'chosen',chosen,flush=True)
    with (root/'predictions.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['user_id','asof','method','rank','destination','score','is_synthetic'])
        for z,cutoff in enumerate(protocol['test_cutoffs']):
            order=np.argsort(-scores[chosen][z],axis=1,kind='stable')[:,:3]
            for j,u in enumerate(test[1]):
                for rank,d in enumerate(order[j],1):writer.writerow([u['user_id'],cutoff,chosen,rank,test[3][d],float(scores[chosen][z,j,d]),1])
    return report


def query_for_user(user):
    return flights.query_for(dict(origin=user['usual_departure_city'],destination=user['requested_destination'],
        start_date=user['start_date'],end_date=(datetime.fromisoformat(user['start_date'])+timedelta(days=user['days']-1)).date().isoformat()),dict(adults=1,max_stops=0))


def flight_key(query):
    return hashlib.sha256(flights.query_key(query).encode('utf-8')).hexdigest()


def export_profiles(root):
    """Monthly behavior-derived portraits, separate from immutable test labels."""
    root=Path(root);data,base,manifest=cohort.load(root/'test')
    cutoffs=[(base+timedelta(days=d)).date().isoformat() for d in range(59,365,30)]
    if manifest['behavior_end'] not in cutoffs:cutoffs.append(manifest['behavior_end'])
    with (root/'profile_snapshots.jsonl').open('w',encoding='utf-8') as stream:
        for cutoff in cutoffs:
            snapshot=ml.snapshot(cutoff,dataset=data,base_date=base,
                holidays=[h for h in cohort.HOLIDAYS if h['published']<=cutoff])
            order=np.argsort(-snapshot['X'][:,:,3],axis=1,kind='stable')[:,:3]
            for j,user in enumerate(data[1]):
                row=dict(user_id=user['user_id'],asof=cutoff,is_synthetic=True,
                    destination_attention=[dict(destination=data[3][d],
                        share_7d=float(snapshot['X'][j,d,0]),share_30d=float(snapshot['X'][j,d,1]),
                        share_60d=float(snapshot['X'][j,d,2]),decayed_share=float(snapshot['X'][j,d,3]),
                        favorite_objects=int(snapshot['favdest'][j,d])) for d in order[j]],
                    airfare_budget_mean=float(snapshot['budget'][j]) if snapshot['budget_n'][j]>0 else None,
                    budget_evidence_count=int(snapshot['budget_n'][j]),
                    favorite_channel=ml.CHANNELS[int(snapshot['channels'][j].argmax())],
                    broad_exploration=bool(snapshot['X'][j,:,1].max()<.2))
                stream.write(json.dumps(row,ensure_ascii=False)+'\n')
    cohort.write_json(root/'profile_manifest.json',dict(users=len(data[1]),cutoffs=cutoffs,
        rows=len(data[1])*len(cutoffs),source_sha256=cohort.digest(root/'test'/'manifest.json'),
        artifact_sha256=cohort.digest(root/'profile_snapshots.jsonl'),
        note='Observed synthetic events only; no hidden generator preferences or model labels in profiles'))
    print('PROFILE_SNAPSHOTS_READY',len(data[1])*len(cutoffs),flush=True)


def collect_flights(root):
    """Append dated snapshots; query sharing never masquerades as independent evidence."""
    root=Path(root);users=[json.loads(line) for line in (root/'test'/'users.jsonl').read_text(encoding='utf-8').splitlines()]
    unique={flight_key(query_for_user(u)):query_for_user(u) for u in users}
    today=datetime.now(CST).date()
    if any(datetime.fromisoformat(q['departure']).date()<today for q in unique.values()):
        raise ValueError('This cohort travel dates have passed; create a new cohort instead of rewriting its dates')
    flights.configured_proxy()
    run=root/'live-flights'/datetime.now(CST).strftime('%Y%m%dT%H%M%S')
    run.mkdir(parents=True,exist_ok=False);results={}
    def one(key,query):
        started=flights.now()
        try:
            result=flights._search(query)
            if flights.result_status(result)!='success':return key,None
            return key,dict(id='EVAL_'+uuid.uuid4().hex,query_key=key,requested_at=started,
                finished_at=flights.now(),status='success',query=query,result=flights.successful_result(result))
        except Exception:return key,None
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=[pool.submit(one,key,query) for key,query in unique.items()]
        for future in as_completed(pending):
            key,value=future.result()
            if not value:continue
            results[key]=value;cohort.write_json(run/(key+'.json'),value)
            print('LIVE_FLIGHT',len(results),len(unique),value['status'],value['query']['origin'],value['query']['destinations'],flush=True)
    counts=Counter();rows=[]
    for user in users:
        record=results.get(flight_key(query_for_user(user)))
        if not record:continue
        options=record['result']['options']
        cap=user['airfare_cap'];budget=user['trip_budget']
        # Conservative non-ticket scenario cost, not merchant quotes or supervised truth.
        nonflight=(user['days']-1)*260+user['days']*160+200
        qualifying=[o for o in options if o['outbound']['price_cny']<=cap and o['inbound']['price_cny']<=cap and o['total_price_cny']+nonflight<=budget]
        counts['users']+=1;counts['query_success_users']+=bool(options);counts['within_constraints_users']+=bool(qualifying)
        row=dict(user_id=user['user_id'],query_id=record['id'],query_key=record['query_key'],
            requested_at=record['requested_at'],status=record['status'],option_count=len(options),
            qualifying_options=len(qualifying),nonflight_scenario_cny=nonflight,
            minimum_airfare_cny=min((o['total_price_cny'] for o in options),default=None),is_synthetic_user=True)
        rows.append(row)
    with (run/'traveler_results.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    report=dict(collected_at=flights.now(),unique_queries=len(unique),statuses=dict(Counter(r['status'] for r in results.values())),
        **counts,source=flights.SOURCE,upstream_commit=flights.UPSTREAM_COMMIT,
        user_route_match_rate=counts['query_success_users']/len(users),
        constraint_match_rate=counts['within_constraints_users']/len(users),
        scope='8 representative routes, two dates, two lengths; not national-market coverage',
        evidence='observed current query results, no historical fare fallback; prices expire, not guaranteed bookings',
        scenario_costs='non-ticket fees simulated; budgets and users synthetic; not training labels')
    cohort.write_json(run/'report.json',report)
    cohort.write_json(root/'latest_flight_report.json',dict(report=report,path=str(run.resolve())))
    print('LIVE_FLIGHTS_COMPLETE',json.dumps(report,ensure_ascii=False),flush=True)
    return report


def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['evaluate','flights','profiles','all'])
    parser.add_argument('--anchor',default=datetime.now(CST).date().isoformat())
    parser.add_argument('--root',type=Path)
    args=parser.parse_args();root=args.root or RUNTIME/'independent-evaluation'/f'annual-{args.anchor}-v1'
    if args.command in ('evaluate','all'):evaluate(root,args.anchor)
    if args.command in ('profiles','all'):export_profiles(root)
    if args.command in ('flights','all'):collect_flights(root)


if __name__=='__main__':main()
