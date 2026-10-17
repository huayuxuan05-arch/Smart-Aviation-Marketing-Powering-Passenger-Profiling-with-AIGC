"""Current-population attention forecasting with sealed, disjoint people.

Never replace the released 2024 baseline or enroll synthetic people in the real
marketing workspace. Test labels are read only after validation selection is saved.
"""
from __future__ import annotations
import os
os.environ.setdefault('OMP_NUM_THREADS','8')
os.environ.setdefault('OPENBLAS_NUM_THREADS','8')
import argparse
from datetime import datetime,timedelta
from functools import lru_cache
import json
from pathlib import Path
import time
import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import average_precision_score
import independent_cohort as cohort
import marketing_ml as ml
from data_layer import RUNTIME
from select_simulated_population import population_path,verify

VERSION='demand-30000-20261017-v1'
ROOT=RUNTIME/'demand-models'
TRAIN_DAYS=(180,240,290)
VALIDATION_DAYS=(310,330,350)
TEST_DAYS=(310,330,357)
RECENT=[0,1,2,3,4,13]


def write(path,value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def split_sources(root,split):
    if split=='development':
        yield 'original-2024',ml.load_data(),ml.BASE_DATE,None
        catalog=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        for row in catalog['sources']:
            data,base,manifest=cohort.load(root/row['path'])
            yield row['path'],data,base,manifest
    else:
        data,base,manifest=cohort.load(root/split)
        yield split,data,base,manifest


def examples(root,split,days):
    for name,data,base,manifest in split_sources(root,split):
        for day in days:
            date=(base+timedelta(days=day)).date().isoformat()
            holidays=ml.HOLIDAYS if manifest is None else [h for h in cohort.HOLIDAYS if h['published']<=date]
            snap=ml.snapshot(date,dataset=data,base_date=base,holidays=holidays)
            target=ml.targets(day,dataset=data)['continue']
            print('SNAPSHOT',split,name,date,flush=True)
            yield name,snap['X'],target,data[1],date


def rules(X):
    return {'recent7':X[:,:,0],'frequency30':X[:,:,1],'decay14':X[:,:,3],
        'recent_mix':.6*X[:,:,0]+.3*X[:,:,1]+.1*X[:,:,3]}


def learned_scores(model,X,columns):
    flat=X.reshape(-1,len(ml.FEATURES))
    return model.predict_proba(flat[:,columns])[:,1].reshape(X.shape[:2])


def candidate_scores(X,models):
    result=rules(X)
    frozen=ml.model_pack();flat=X.reshape(-1,len(ml.FEATURES));key=frozen['selected']
    result['frozen2024']=frozen['models'][key].predict_proba(flat if key=='boost' else frozen['scaler'].transform(flat))[:,1].reshape(X.shape[:2])
    for name,(model,columns) in models.items():
        score=learned_scores(model,X,columns)
        for alpha in (.25,.5,.75,1.):result[f'{name}:{alpha:g}']=alpha*score+(1-alpha)*result['recent_mix']
    return result


def metrics(y,score):
    return {**ml.ranking_metrics(y,score),'pr_auc':float(average_precision_score(y.ravel(),score.ravel()))}


def individual_ndcg(y,score):
    order=np.argsort(-score,axis=1,kind='stable')[:,:3]
    discount=1/np.log2(np.arange(2,5));num=y.sum(axis=1)
    ideal=np.array([discount[:min(int(n),3)].sum() for n in num])
    return np.divide((np.take_along_axis(y,order,axis=1)*discount).sum(axis=1),ideal,
        out=np.full(len(y),np.nan),where=ideal>0)


def paired_ci(y,chosen,reference,owners):
    # Bootstrap people, not repeated snapshots or destination pairs.
    delta=individual_ndcg(y,chosen)-individual_ndcg(y,reference)
    groups={}
    for user,value in zip(owners,delta):
        if np.isfinite(value):groups.setdefault(user,[]).append(value)
    values=np.array([np.mean(v) for v in groups.values()]);rng=np.random.default_rng(20261017)
    draws=np.array([rng.choice(values,len(values),replace=True).mean() for _ in range(500)])
    return {'mean_delta':float(values.mean()),'ci95':list(map(float,np.quantile(draws,[.025,.975]))),'independent_people':len(values)}


def evaluate(root,split,days,models):
    labels=[];scores={};owners=[];scenarios=[];dates=[]
    for _,X,y,users,date in examples(root,split,days):
        labels.append(y);dates.append(date);owners.extend(u['user_id'] for u in users)
        scenarios.extend(u.get('scenario','original') for u in users)
        for key,value in candidate_scores(X,models).items():scores.setdefault(key,[]).append(value)
    return np.concatenate(labels),{k:np.concatenate(v) for k,v in scores.items()},owners,np.array(scenarios),dates


def train():
    started=time.time();root=population_path();verified=verify(root)
    target=ROOT/VERSION
    if target.exists():raise ValueError('Immutable run already exists; read its report rather than tuning on test again')
    target.mkdir(parents=True)
    xs=[];ys=[];cutoffs=[]
    for name,X,y,users,date in examples(root,'development',TRAIN_DAYS):
        xs.append(X.reshape(-1,len(ml.FEATURES)));ys.append(y.ravel());cutoffs.append({'source':name,'asof':date,'label_end':(datetime.fromisoformat(date)+timedelta(days=7)).date().isoformat()})
    X=np.concatenate(xs);y=np.concatenate(ys);del xs,ys
    models={}
    for name,columns in [('recent_hgb',RECENT),('full_hgb',list(range(len(ml.FEATURES))))]:
        print('FIT',name,X.shape,flush=True)
        model=HistGradientBoostingClassifier(max_iter=65,max_leaf_nodes=15,max_bins=64,
            learning_rate=.12,l2_regularization=10,early_stopping=False,random_state=20261017)
        model.fit(X[:,columns],y);models[name]=(model,columns)
    del X,y
    vy,vs,_,_,vdates=evaluate(root,'validation',VALIDATION_DAYS,models)
    validation={key:metrics(vy,value) for key,value in vs.items()}
    baseline_keys=['frozen2024','recent7','frequency30','decay14','recent_mix']
    best_baseline=max(baseline_keys,key=lambda k:validation[k]['ndcg_at_3'])
    floor=validation[best_baseline]['recall_at_3']-.005
    eligible=[k for k in validation if validation[k]['recall_at_3']>=floor]
    selected=max(eligible,key=lambda k:validation[k]['ndcg_at_3'])
    selection={'selected':selected,'baseline':best_baseline,'validation':validation,'validation_dates':vdates,
        'rule':'maximum validation NDCG@3 with recall no worse than best baseline minus 0.005',
        'test_used_for_selection':False,'population':verified,'training_cutoffs':cutoffs}
    write(target/'selection.json',selection)
    print('SELECTION_LOCKED',selected,flush=True)
    # No training, blending or parameter selection below this point.
    ty,ts,owners,scenarios,tdates=evaluate(root,'test',TEST_DAYS,models)
    test={key:metrics(ty,value) for key,value in ts.items()}
    ci=paired_ci(ty,ts[selected],ts[best_baseline],owners)
    baseline_ci=paired_ci(ty,ts[selected],ts['frozen2024'],owners)
    promoted=(selected not in baseline_keys and test[selected]['ndcg_at_3']>=test[best_baseline]['ndcg_at_3']
        and test[selected]['recall_at_3']>=test[best_baseline]['recall_at_3']-.005 and ci['ci95'][0]>0)
    report={**selection,'version':VERSION,'test':test,'test_dates':tdates,'paired_ndcg_vs_validation_best_baseline':ci,
        'paired_ndcg_vs_frozen2024':baseline_ci,'promoted':promoted,'training_seconds':round(time.time()-started,2),
        'trained_people':26000,'validation_people':2000,'test_people':2000,'pair_training_rows':26000*41*len(TRAIN_DAYS),
        'target':'未来7天同一目的地至少2次关注，模拟关注代理；不是购票概率',
        'scenarios':{name:{'people':len(set(u for u,s in zip(owners,scenarios) if s==name)),
            **metrics(ty[scenarios==name],ts[selected][scenarios==name])} for name in sorted(set(scenarios))},
        'boundary':['仅模拟数据；新用户独立，但与开发集共用模拟器','未观察到真实购票、满意度或营销增量',
            '2024历史回放继续使用原冻结模型，防止借用未来训练结果','本人明确条件优先；现场首次使用不伪造长期行为或需求概率'],
        'base_model_sha256':cohort.digest(ml.ROOT/'marketing_models.joblib')}
    if selected not in baseline_keys:
        name,alpha=selected.split(':');model,columns=models[name]
        joblib.dump({'model':model,'columns':columns,'alpha':float(alpha),'version':VERSION,
            'candidate_destinations':ml.load_data()[3],'feature_names':ml.FEATURES,'target':report['target']},target/'model.joblib',compress=3)
    write(target/'report.json',report)
    if promoted:
        write(ROOT/'active.json',{'version':VERSION,'root':str(target.resolve()),
            'model_sha256':cohort.digest(target/'model.joblib'),'report_sha256':cohort.digest(target/'report.json'),
            'available_from':'2026-10-17','scope':'synthetic attention reference; explicit real preferences always take precedence'})
    print('COMPLETE',json.dumps({'selected':selected,'promoted':promoted,'test':test[selected],'baseline':test[best_baseline],'frozen':test['frozen2024'],'seconds':report['training_seconds']},ensure_ascii=False),flush=True)
    return report


@lru_cache(maxsize=1)
def active_pack():
    entry=ROOT/'active.json'
    if not entry.exists():return None
    manifest=json.loads(entry.read_text(encoding='utf-8'));root=Path(manifest['root']).resolve()
    if not root.is_relative_to(ROOT.resolve()):raise ValueError('Demand model outside project')
    for name,key in [('model.joblib','model_sha256'),('report.json','report_sha256')]:
        if cohort.digest(root/name)!=manifest[key]:raise ValueError('Demand artifact fingerprint changed')
    return joblib.load(root/'model.joblib'),json.loads((root/'report.json').read_text(encoding='utf-8')),manifest


def reference():
    pack=active_pack()
    if not pack:
        path=ROOT/VERSION/'report.json'
        if not path.exists():return {'available':False,'boundary':'当前使用冻结基线；新模型尚未通过独立评估'}
        report=json.loads(path.read_text(encoding='utf-8'))
        return {'available':False,'evaluated_version':VERSION,'training_users':26000,'validation_users':2000,
            'test_users':2000,'candidate_metrics':report['test'][report['selected']],
            'baseline_metrics':report['test']['frozen2024'],'target':report['target'],
            'boundary':'候选模型未达到稳定提升门槛，继续使用冻结基线；真实用户以本人确认偏好为准'}
    model,report,manifest=pack
    return {'available':True,'version':manifest['version'],'training_users':26000,'validation_users':2000,
        'test_users':2000,'target':report['target'],'test_metrics':report['test'][report['selected']],
        'boundary':'模拟关注任务的独立用户评估；本人明确条件优先，不代表真实购票率'}


def predict(X,asof):
    pack=active_pack()
    if pack is None or asof<pack[2]['available_from']:return None
    model,_,_=pack
    if X.ndim!=3 or X.shape[2]!=len(ml.FEATURES) or not np.isfinite(X).all():raise ValueError('Demand features invalid')
    return model['alpha']*learned_scores(model['model'],X,model['columns'])+(1-model['alpha'])*rules(X)['recent_mix']


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--train',action='store_true');args=parser.parse_args()
    if args.train:train()
    else:print(json.dumps(reference(),ensure_ascii=False,indent=2))
