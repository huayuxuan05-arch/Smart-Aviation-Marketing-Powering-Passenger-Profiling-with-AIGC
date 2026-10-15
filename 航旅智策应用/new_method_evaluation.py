"""Pairwise ranking and new-data boosting selected before a fresh user holdout."""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import SGDClassifier
from sklearn.preprocessing import StandardScaler
import independent_cohort as cohort
import independent_evaluation as evaluation
import marketing_ml as ml


def fit_pairwise(x,y,seed=cohort.SEED+20):
    """Within-user positive vs negative destination pairs; no user-ID feature."""
    rng=np.random.default_rng(seed);scaler=StandardScaler().fit(x.reshape(-1,x.shape[-1]))
    rows,positive=np.where(y>0);deltas=[]
    for _ in range(3):
        negative=rng.integers(x.shape[1],size=len(rows))
        valid=y[rows,negative]==0;r=rows[valid];p=positive[valid];n=negative[valid]
        deltas.append((x[r,p]-x[r,n])/scaler.scale_)
    delta=np.concatenate(deltas);pair_x=np.concatenate([delta,-delta])
    pair_y=np.concatenate([np.ones(len(delta)),np.zeros(len(delta))])
    model=SGDClassifier(loss='log_loss',alpha=.0001,max_iter=200,tol=.0001,
        fit_intercept=False,random_state=seed).fit(pair_x,pair_y)
    return dict(model=model,scaler=scaler,pair_rows=len(pair_y))


def predict_pairwise(snapshot,pack):
    x=snapshot['X'];scores=pack['model'].decision_function(x.reshape(-1,x.shape[-1])/pack['scaler'].scale_)
    return scores.reshape(x.shape[:2])


def rank_percentile(scores):
    order=np.argsort(np.argsort(scores,axis=-1,kind='stable'),axis=-1,kind='stable')
    return order/(scores.shape[-1]-1)


def scores_for(data,base,dates,original,pairwise,boost):
    ys=[];scores={}
    for s,target in cohort.snapshots(data,base,dates):
        x=s['X'];old=evaluation.frozen_scores(s,original);pair=predict_pairwise(s,pairwise)
        new=boost.predict_proba(x.reshape(-1,x.shape[-1]))[:,1].reshape(x.shape[:2])
        values={'原冻结模型':old,'成对学习排序':pair,'新数据梯度提升':new,**evaluation.rule_scores(s)}
        for weight in [.25,.5,.75]:
            values[f'排序与衰减融合{weight}']=weight*rank_percentile(pair)+(1-weight)*rank_percentile(s['X'][:,:,3])
        for name,value in values.items():scores.setdefault(name,[]).append(value)
        ys.append(target['continue'])
    y=np.stack(ys);stacked={n:np.stack(v) for n,v in scores.items()}
    metrics={n:ml.ranking_metrics(y.reshape(-1,y.shape[-1]),v.reshape(-1,y.shape[-1])) for n,v in stacked.items()}
    return y,stacked,metrics


def run(root,anchor):
    root=Path(root);output=root/'new-method-v1';output.mkdir(exist_ok=True)
    if (output/'report.json').exists():
        print('CONFIRMATION_RESULT_LOCKED',flush=True);return
    cohort.generate(root/'training',6000,'training',anchor,seed=cohort.SEED+2,export_behaviors=False)
    cohort.generate(root/'confirmation',10000,'confirmation',anchor,seed=cohort.SEED+3,export_behaviors=False)
    protocol=dict(method='constraint-first recommendation + preference ranking',
        training_users=6000,validation_users=2000,fresh_confirmation_users=10000,
        training_dates=evaluation.cutoff_dates(anchor,[270,240,210,180,150,120]),
        validation_dates=evaluation.cutoff_dates(anchor,[90,60,30]),
        confirmation_dates=evaluation.cutoff_dates(anchor,[67,37,7]),
        candidates=['pairwise SGD ranking','new-data gradient boosting','three fixed rank-decay blends','frozen model','four rules'],
        choose='validation NDCG@3 maximum subject to Recall@3 no worse than original by 0.005',
        promotion='confirmation NDCG delta >=0.005 and paired 95% CI lower bound >0',
        old_test_reused_for_tuning=False,frozen_model_sha256=cohort.digest(ml.ROOT/'marketing_models.joblib'),
        confirmation_manifest_sha256=cohort.digest(root/'confirmation'/'manifest.json'),
        note='feasibility is evaluated separately; interest ranking cannot make an over-budget flight feasible')
    cohort.write_json(output/'protocol.json',protocol)
    data,base,_=cohort.load(root/'training');xs=[];ys=[]
    for s,t in cohort.snapshots(data,base,protocol['training_dates']):xs.append(s['X']);ys.append(t['continue'])
    x=np.concatenate(xs);y=np.concatenate(ys)
    started=time.monotonic();print('PAIRWISE_TRAIN',x.shape,flush=True)
    pairwise=fit_pairwise(x,y);joblib.dump(pairwise,output/'pairwise_ranker.joblib',compress=3)
    print('BOOST_TRAIN',flush=True)
    boost=HistGradientBoostingClassifier(max_iter=50,max_leaf_nodes=15,max_bins=64,
        learning_rate=.1,l2_regularization=3,early_stopping=False,random_state=cohort.SEED+20).fit(x.reshape(-1,x.shape[-1]),y.ravel())
    joblib.dump(boost,output/'boost_model.joblib',compress=3)
    seconds=round(time.monotonic()-started,2);del x,y,xs,ys,data
    original=ml.model_pack();validation,base,_=cohort.load(root/'validation')
    _,_,vm=scores_for(validation,base,protocol['validation_dates'],original,pairwise,boost)
    selected=evaluation.choose_method(vm)
    cohort.write_json(output/'selection_before_confirmation.json',dict(selected=selected,validation=vm,training_seconds=seconds,
        pairwise_pairs=pairwise['pair_rows'],protocol_sha256=cohort.digest(output/'protocol.json')))
    print('NEW_VALIDATION',json.dumps(vm,ensure_ascii=False),'selected',selected,flush=True)
    confirmation,base,manifest=cohort.load(root/'confirmation')
    ids={u['user_id'] for u in confirmation[1]}
    for split in ['test','training','validation']:
        other={json.loads(line)['user_id'] for line in (root/split/'users.jsonl').read_text(encoding='utf-8').splitlines()}
        if ids&other:raise ValueError('Confirmation cohort overlaps previous users')
    y,scores,metrics=scores_for(confirmation,base,protocol['confirmation_dates'],original,pairwise,boost)
    delta=evaluation.individual_ndcg(y,scores[selected])-evaluation.individual_ndcg(y,scores['原冻结模型'])
    rng=np.random.default_rng(cohort.SEED+40);samples=[float(np.nanmean(delta[rng.integers(len(delta),size=len(delta))])) for _ in range(500)]
    ci=list(map(float,np.quantile(samples,[.025,.975])));mean=float(np.nanmean(delta))
    groups=np.array([u['scenario'] for u in confirmation[1]]);subgroups={}
    for group in cohort.SCENARIOS:
        mask=groups==group;gy=y[:,mask]
        subgroups[group]={name:ml.ranking_metrics(gy.reshape(-1,gy.shape[-1]),scores[name][:,mask].reshape(-1,gy.shape[-1])) for name in {selected,'原冻结模型'}}
    report=dict(protocol=protocol,selected_method=selected,validation=vm,confirmation=metrics,
        paired_ndcg_delta=mean,paired_ndcg_delta_95pct=ci,subgroups=subgroups,
        promotion_gate_passed=mean>=.005 and ci[0]>0,training_seconds=seconds,
        original_artifact_unchanged=cohort.digest(ml.ROOT/'marketing_models.joblib')==protocol['frozen_model_sha256'],
        recommendation='versioned new-cohort method only; keep 2024 replay model and test labels unchanged')
    cohort.write_json(output/'report.json',report)
    print('NEW_CONFIRMATION',json.dumps(metrics,ensure_ascii=False),'selected',selected,'delta',mean,'CI',ci,'promote',report['promotion_gate_passed'],flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path);parser.add_argument('--anchor',default='2026-10-16')
    args=parser.parse_args();run(args.root,args.anchor)
