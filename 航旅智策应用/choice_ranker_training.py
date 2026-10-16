"""Train an itinerary LambdaMART only when sufficient explicit real labels exist."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import numpy as np
from sklearn.feature_extraction import DictVectorizer
import joblib
import independent_cohort as cohort
import travel_choice_evidence as evidence


def encoded(features):
    result={}
    for name,value in features.items():
        # Evidence provenance and observation flags are not preference predictors.
        if name in ('budget_source','merchant_hotel_price_observed','model_score','hard_constraints_satisfied'):continue
        if value is None: result[name+'__missing']=1
        elif isinstance(value,(float,int)): result[name]=value
        else: result[name]=str(value)
    return result


def split_groups(groups):
    """Distinct owners and forward-only event windows; late development events dropped."""
    first={}
    for g in groups:first[g['owner']]=min(first.get(g['owner'],g['recorded_at']),g['recorded_at'])
    owners=sorted(first,key=lambda o:(first[o],o));n=len(owners);a=int(n*.6);b=int(n*.8)
    if not 0<a<b<n:raise ValueError('Insufficient independent owners')
    limits=[first[owners[a]],first[owners[b]]]
    assignments={o:0 if i<a else 1 if i<b else 2 for i,o in enumerate(owners)}
    parts=[[],[],[]]
    for g in groups:
        z=assignments[g['owner']]
        if z<2 and g['recorded_at']>=limits[z]:continue
        parts[z].append(g)
    return parts


def dataset(groups,vectorizer,fit=False):
    rows=[];labels=[];qid=[]
    for i,g in enumerate(groups):
        for c in g['candidates']:
            rows.append(encoded(c['features']));labels.append(c['relevance']);qid.append(i)
    x=vectorizer.fit_transform(rows) if fit else vectorizer.transform(rows)
    return x,np.array(labels,np.uint8),np.array(qid)


def ndcg(labels,scores,qid):
    values=[]
    for q in np.unique(qid):
        y=labels[qid==q];p=scores[qid==q];order=np.argsort(-p,kind='stable')[:3]
        d=1/np.log2(np.arange(2,len(order)+2))
        ideal=(np.sort(y)[::-1][:len(order)]*d).sum()
        if ideal:values.append(float((y[order]*d).sum()/ideal))
    return float(np.mean(values)) if values else None


def run(connection,output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/'selection_before_test.json').exists() or (output/'report.json').exists():
        raise ValueError('Evaluation version is sealed; choose a new output directory')
    groups=evidence.labeled_groups(connection); owners={g['owner'] for g in groups}
    protocol=dict(version='explicit-choice-lambdamart-v1',unit='passenger request x exposed itinerary',
        labels='1 explicitly chosen and saved; 0 explicitly rejected; nonchoice unlabelled; conflict excluded',
        source='local personal interactions, prospective only; no synthetic or questionnaire adoption labels',
        minimum_owners=50,minimum_paired_requests=100,split='browser-owner-disjoint 60/20/20, forward event windows',
        independence_limit='browser owners are not verified distinct people; cross-device linkage is not established',
        select='validation NDCG@3; compare simple fare-ratio baseline',
        promotion='test delta >=0.02, owner bootstrap CI lower >0; never auto-deploy',
        observed_paired_requests=len(groups),observed_owners=len(owners))
    cohort.write_json(output/'protocol.json',protocol)
    if len(owners)<50 or len(groups)<100:
        report=dict(status='insufficient_explicit_labels',training_performed=False,online_weights_replaced=False,
            observed_paired_requests=len(groups),observed_owners=len(owners),required_owners=50,required_paired_requests=100)
        cohort.write_json(output/'readiness.json',report);return report
    parts=split_groups(groups)
    if min(len({g['owner'] for g in p}) for p in parts)<10:
        raise ValueError('Forward split has too few independent owners')
    import xgboost as xgb
    vectorizer=DictVectorizer(sparse=True)
    x,y,qid=dataset(parts[0],vectorizer,True);vx,vy,vqid=dataset(parts[1],vectorizer)
    models=[];trials=[]
    for depth in [2,3,4]:
        model=xgb.XGBRanker(objective='rank:ndcg',tree_method='hist',n_jobs=4,n_estimators=80,
            max_depth=depth,learning_rate=.05,reg_lambda=10,random_state=20261016,
            lambdarank_pair_method='mean',lambdarank_num_pair_per_sample=3).fit(x,y,qid=qid)
        trials.append(dict(depth=depth,validation_ndcg=ndcg(vy,model.predict(vx),vqid)));models.append(model)
    selected=int(np.argmax([r['validation_ndcg'] for r in trials]))
    cohort.write_json(output/'selection_before_test.json',dict(trials=trials,selected=selected,features=list(vectorizer.get_feature_names_out())))
    model=models[selected];model.save_model(output/'itinerary_ranker.ubj');joblib.dump(vectorizer,output/'vectorizer.joblib')
    tx,ty,tqid=dataset(parts[2],vectorizer);pred=model.predict(tx)
    baseline=[]
    for g in parts[2]:
        baseline.extend(-c['features'].get('roundtrip_trip_cap_share',0) if c['features'].get('roundtrip_trip_cap_share') is not None else 0 for c in g['candidates'])
    baseline=np.array(baseline)
    # Paired bootstrap at owner level, rather than treating repeated requests as independent.
    deltas={}
    for i,g in enumerate(parts[2]):
        mask=tqid==i
        delta=ndcg(ty[mask],pred[mask],tqid[mask])-ndcg(ty[mask],baseline[mask],tqid[mask])
        deltas.setdefault(g['owner'],[]).append(delta)
    values=np.array([np.mean(v) for v in deltas.values()]);rng=np.random.default_rng(20261016)
    ci=list(map(float,np.quantile([np.mean(rng.choice(values,len(values),replace=True)) for _ in range(1000)],[.025,.975])))
    report=dict(status='evaluated',test_ndcg=ndcg(ty,pred,tqid),baseline_ndcg=ndcg(ty,baseline,tqid),
        paired_owner_delta=float(values.mean()),ci95=ci,promotion_gate_passed=bool(values.mean()>=.02 and ci[0]>0),
        online_weights_replaced=False,split_requests=[len(p) for p in parts],
        independence_limit=protocol['independence_limit'],
        artifacts={n:cohort.digest(output/n) for n in ['itinerary_ranker.ubj','vectorizer.joblib']})
    cohort.write_json(output/'report.json',report);return report


if __name__=='__main__':
    import personal_app
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);args=p.parse_args()
    with personal_app.db() as c:print(json.dumps(run(c,args.output),ensure_ascii=False))
