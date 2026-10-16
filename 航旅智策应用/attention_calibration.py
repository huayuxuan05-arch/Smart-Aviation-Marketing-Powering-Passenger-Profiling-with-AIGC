"""Fixed sigmoid calibration for a defined attention event, never booking odds."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss,log_loss
import marketing_ml as ml
import independent_cohort as cohort
import independent_evaluation as evaluation


def logit(p):
    p=np.clip(p,1e-6,1-1e-6)
    return np.log(p/(1-p)).reshape(-1,1)


def ece(y,p):
    result=0
    for lo,hi in zip(np.linspace(0,1,11)[:-1],np.linspace(0,1,11)[1:]):
        mask=(p>=lo)&(p<hi if hi<1 else p<=hi)
        if mask.any():result+=float(mask.mean()*abs(y[mask].mean()-p[mask].mean()))
    return result


def run(root,anchor):
    root=Path(root);output=root/'lambdamart-v1'/'attention-calibration-v1';output.mkdir(exist_ok=True)
    if (output/'report.json').exists():return json.loads((output/'report.json').read_text(encoding='utf-8'))
    protocol=dict(event='future 7 days same city >=2 searches',source='synthetic attention only',
        model='frozen production attention classifier, fixed sigmoid on clipped logit',
        calibration_users=2000,validation_used_for_fitting=True,
        calibration_dates=evaluation.cutoff_dates(anchor,[90,60,30]),
        fresh_assessment_users=2000,fresh_seed=cohort.SEED+90,assessment_dates=evaluation.cutoff_dates(anchor,[67,37,7]),
        metrics=['Brier','log loss','10 equal-width bins ECE'],
        interpretation='not probability of booking, adopting or responding to marketing',online_scores_changed=False,
        original_sha256=cohort.digest(ml.ROOT/'marketing_models.joblib'))
    cohort.write_json(output/'protocol.json',protocol)
    data,base,_=cohort.load(root/'validation');ys=[];ps=[];original=ml.model_pack()
    for s,t in cohort.snapshots(data,base,protocol['calibration_dates']):
        ys.append(t['continue']);ps.append(evaluation.frozen_scores(s,original))
    model=LogisticRegression(C=1e6,max_iter=200).fit(logit(np.stack(ps)),np.stack(ys).ravel())
    joblib.dump(model,output/'sigmoid.joblib');del data,ys,ps
    cohort.generate(output/'assessment',2000,'calibration_assessment_v1',anchor,seed=protocol['fresh_seed'],export_behaviors=False)
    data,base,manifest=cohort.load(output/'assessment');ys=[];ps=[]
    for split in ['training','validation','test','confirmation']:
        old={json.loads(line)['user_id'] for line in (root/split/'users.jsonl').read_text(encoding='utf-8').splitlines()}
        if old&{u['user_id'] for u in data[1]}:raise ValueError('Calibration assessment overlaps previous users')
    for s,t in cohort.snapshots(data,base,protocol['assessment_dates']):
        ys.append(t['continue']);ps.append(evaluation.frozen_scores(s,original))
    y=np.stack(ys);p=np.stack(ps);cal=model.predict_proba(logit(p))[:,1].reshape(p.shape)
    scores={}
    for name,values in [('uncalibrated',p),('sigmoid',cal)]:
        scores[name]=dict(brier=float(brier_score_loss(y.ravel(),values.ravel())),
            log_loss=float(log_loss(y.ravel(),values.ravel())),ece_10_bins=ece(y,values))
    user_delta=((p-y)**2-(cal-y)**2).mean(axis=(0,2));rng=np.random.default_rng(cohort.SEED+91)
    ci=list(map(float,np.quantile([rng.choice(user_delta,len(user_delta),replace=True).mean() for _ in range(1000)],[.025,.975])))
    report=dict(protocol=protocol,metrics=scores,positive_rate=float(y.mean()),candidate_events=int(y.size),
        paired_user_brier_improvement=float(user_delta.mean()),ci95=ci,
        monotonic_rank_preserved=bool(model.coef_[0,0]>0),online_scores_changed=False,
        assessment_manifest=manifest,calibrator_sha256=cohort.digest(output/'sigmoid.joblib'),
        original_unchanged=cohort.digest(ml.ROOT/'marketing_models.joblib')==protocol['original_sha256'])
    cohort.write_json(output/'report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('--anchor',default='2026-10-16');a=p.parse_args()
    r=run(a.root,a.anchor);print(json.dumps({k:v for k,v in r.items() if k not in ['assessment_manifest','protocol']},ensure_ascii=False))
