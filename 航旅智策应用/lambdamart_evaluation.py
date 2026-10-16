"""Versioned user-grouped ranking experiment; never overwrites production weights.

Previously inspected synthetic holdouts may be reused for development with their
role disclosed. A fresh, sealed cohort is scored only after validation selection.
Current flight quotes are evaluated separately, never joined to past cutoffs.
"""
from __future__ import annotations
import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import numpy as np
import independent_cohort as cohort
import independent_evaluation as evaluation
import marketing_ml as ml

EXTRA_FEATURES = ['近1天关注', '近3天关注', '近14天关注', '近90天关注',
                  '3天衰减关注', '7天衰减关注', '28天衰减关注',
                  '7天关注熵', '30天关注熵', '7天主次差距', '30天主次差距',
                  '7天与30天分布变化', '7天预算相对30天变化']
FEATURES = ml.FEATURES + EXTRA_FEATURES
TRIALS = {
    'LambdaMART浅树': dict(max_depth=3, n_estimators=100, lambdarank_pair_method='topk'),
    'LambdaMART深树': dict(max_depth=5, n_estimators=160, lambdarank_pair_method='topk'),
    'LambdaMART随机配对': dict(max_depth=4, n_estimators=140, lambdarank_pair_method='mean'),
}


def extend_features(s, dataset):
    """Only completed pre-cutoff observations; no ID, scenario or future quote."""
    a, users, _, dests = dataset
    t = s['day']; n = len(users); k = len(dests); ids = np.arange(n)
    counts = {w: np.zeros((n, k), np.float32) for w in [1, 3, 14, 90]}
    decays = {w: np.zeros((n, k), np.float32) for w in [3, 7, 28]}
    length = min(90, t + 1)
    for age in range(length):
        d = a['dest'][t - age]
        for w, values in counts.items():
            if age < w: values[ids, d] += 1
        for w, values in decays.items(): values[ids, d] += 2 ** (-age / w)
    extra = [counts[w] / min(w, length) for w in counts]
    extra += [v / sum(2 ** (-i / w) for i in range(length)) for w, v in decays.items()]
    p7, p30 = s['X'][:, :, 0], s['X'][:, :, 1]
    def tile(v): return np.broadcast_to(v[:, None], (n, k))
    def entropy(p): return -(p * np.log(np.maximum(p, 1e-10))).sum(axis=1) / np.log(k)
    def margin(p):
        top = np.sort(p, axis=1)[:, -2:]
        return top[:, 1] - top[:, 0]
    extra += [tile(entropy(p7)), tile(entropy(p30)), tile(margin(p7)), tile(margin(p30)),
              tile(np.abs(p7 - p30).sum(axis=1) / 2)]
    recent = a['budget'][max(0, t-6):t+1]
    valid = np.isfinite(recent)
    b7 = np.divide(np.nansum(recent, axis=0), valid.sum(axis=0),
                   out=np.zeros(n, np.float32), where=valid.sum(axis=0)>0)
    delta = np.where((s['budget_n']>0) & (valid.sum(axis=0)>0),
                     (b7 - s['budget']) / np.maximum(s['budget'], 100), 0)
    extra += [tile(delta)]
    return np.concatenate([s['X'], np.stack(extra, axis=-1)], axis=-1).astype(np.float32)


def grouped_rows(x, y):
    """One complete destination list per passenger/cutoff; monotonically sorted qid."""
    if x.ndim != 3 or y.shape != x.shape[:2] or x.shape[1] < 2:
        raise ValueError('Expected complete user-by-destination lists')
    if not np.isfinite(x).all() or not np.isin(y, [0, 1]).all():
        raise ValueError('Nonfinite features or invalid relevance label')
    return x.reshape(-1, x.shape[-1]), y.ravel(), np.repeat(np.arange(len(x)), x.shape[1])


def subset(data, limit, seed):
    a, users, objects, dests = data
    indices = np.sort(np.random.default_rng(seed).choice(len(users), min(limit, len(users)), replace=False))
    return ({key: value[:, indices] for key, value in a.items()},
            [users[i] for i in indices], objects, dests)


def assert_disjoint(*groups):
    seen = set()
    for ids in groups:
        ids = set(ids)
        if seen & ids: raise ValueError('User overlap across development/validation/holdout')
        seen.update(ids)


def metrics(y, scores):
    return {name: ml.ranking_metrics(y.reshape(-1, y.shape[-1]), v.reshape(-1, y.shape[-1]))
            for name, v in scores.items()}


def score(data, base, cutoffs, models, original):
    ys = []; values = {}
    for s, target in cohort.snapshots(data, base, cutoffs):
        x = extend_features(s, data)
        current = {'原冻结模型': evaluation.frozen_scores(s, original), **evaluation.rule_scores(s)}
        for name, model in models.items():
            current[name] = model.predict(x.reshape(-1, x.shape[-1])).reshape(x.shape[:2])
        for name, value in current.items(): values.setdefault(name, []).append(value)
        ys.append(target['continue'])
    y = np.stack(ys); scores = {n: np.stack(v) for n, v in values.items()}
    return y, scores, metrics(y, scores)


def paired_delta(y, scores, baseline, seed=cohort.SEED+80):
    delta = evaluation.individual_ndcg(y, scores) - evaluation.individual_ndcg(y, baseline)
    rng = np.random.default_rng(seed)
    bootstrap = [float(np.nanmean(delta[rng.integers(len(delta), size=len(delta))])) for _ in range(1000)]
    return dict(mean=float(np.nanmean(delta)), ci95=list(map(float, np.quantile(bootstrap, [.025, .975]))))


def run(root, anchor):
    import xgboost as xgb
    root = Path(root); output = root/'lambdamart-v1'; output.mkdir(exist_ok=True)
    report_path = output/'report.json'
    if report_path.exists():
        print('SEALED_HOLDOUT_RESULT_EXISTS', flush=True)
        return json.loads(report_path.read_text(encoding='utf-8'))
    if (output/'selection_before_holdout.json').exists():
        raise ValueError('Interrupted sealed run: resume evaluation explicitly; never silently retrain')
    protocol = dict(version='lambdamart-v1', anchor=anchor, features=FEATURES,
        target='future seven days same-city >=2 searches; synthetic attention, not plan adoption',
        development_sources=['original 2024 first-half cutoffs, 10000 users',
            'training, test and confirmation cohorts: seeded 4000 users each'],
        previous_test_role='test and confirmation were already inspected; explicitly reused for development',
        new_training_dates=evaluation.cutoff_dates(anchor, [240, 180, 120]),
        original_training_dates=['2024-02-15','2024-04-15','2024-06-15'],
        validation_dates=evaluation.cutoff_dates(anchor, [90, 60, 30]), validation_users=2000,
        fresh_holdout=dict(split='lambda_holdout_v1', users=10000, seed=cohort.SEED+50,
                           dates=evaluation.cutoff_dates(anchor, [67, 37, 7])),
        trials=TRIALS, objective='rank:ndcg', qid='passenger x cutoff, all 41 cities',
        selection='validation NDCG@3 maximum; Recall floor original minus 0.005',
        promotion='selected learned model: NDCG improvement >=0.005 and CI lower >0 against BOTH frozen model and validation-selected rule; Recall no worse than frozen by 0.005',
        quote_temporal_policy='current quotes only in prospective feasibility/features; never backfilled into past training snapshots',
        original_model_sha256=cohort.digest(ml.ROOT/'marketing_models.joblib'), xgboost=xgb.__version__,
        runtime='CPU 6 threads; preserve local Qwen GPU; no paid model')
    cohort.write_json(output/'protocol.json', protocol)
    xs=[]; ys=[]; train_ids=[]; provenance=[]
    for index, split in enumerate(['original', 'training', 'test', 'confirmation']):
        if split=='original':
            data=ml.load_data(); base=ml.BASE_DATE; dates=protocol['original_training_dates']
            source_hash=cohort.digest(ml.ROOT/'behavior_arrays.npz')
        else:
            data, base, manifest=cohort.load(root/split)
            data=subset(data, 4000, cohort.SEED+60+index); dates=protocol['new_training_dates']
            source_hash=cohort.digest(root/split/'manifest.json')
        train_ids.extend(u['user_id'] for u in data[1])
        provenance.append(dict(source=split, users=len(data[1]), cutoffs=dates, sha256=source_hash))
        for date in dates:
            holidays=([h for h in cohort.HOLIDAYS if h['published']<=date] if split!='original' else ml.HOLIDAYS)
            s=ml.snapshot(date, dataset=data, base_date=base, holidays=holidays)
            xs.append(extend_features(s, data)); ys.append(ml.targets(s['day'],dataset=data)['continue'])
            print('RANKING_FEATURES', split, date, len(data[1]), flush=True)
        del data
    x=np.concatenate(xs); y=np.concatenate(ys); del xs,ys
    flat, labels, qid=grouped_rows(x,y)
    cohort.write_json(output/'training_provenance.json', dict(sources=provenance, users=len(set(train_ids)),
        query_groups=len(x), pair_rows=len(flat), feature_count=len(FEATURES)))
    models={}; seconds={}
    for name, params in TRIALS.items():
        print('LAMBDAMART_TRAIN', name, flat.shape, flush=True); start=time.monotonic()
        model=xgb.XGBRanker(objective='rank:ndcg', eval_metric='ndcg@3', tree_method='hist',
            device='cpu', n_jobs=6, learning_rate=.08, max_bin=64, reg_lambda=5,
            subsample=1, colsample_bytree=1, random_state=cohort.SEED+70,
            lambdarank_num_pair_per_sample=5, **params)
        model.fit(flat,labels,qid=qid)
        filename=f'ranker_{len(models)}.ubj'; model.save_model(output/filename)
        models[name]=model; seconds[name]=round(time.monotonic()-start,2)
        print('LAMBDAMART_TRAINED', name, seconds[name], flush=True)
    del x,y,flat,labels,qid
    validation,base,_=cohort.load(root/'validation')
    validation_ids={u['user_id'] for u in validation[1]}
    assert_disjoint(train_ids, validation_ids)
    _,_,vm=score(validation,base,protocol['validation_dates'],models,ml.model_pack()); del validation
    selected=evaluation.choose_method(vm)
    rule=max(evaluation.rule_scores({'X':np.zeros((1,41,len(ml.FEATURES)))}), key=lambda n:vm[n]['ndcg_at_3'])
    selection=dict(selected=selected, strongest_validation_rule=rule, validation=vm,
        training_seconds=seconds, protocol_sha256=cohort.digest(output/'protocol.json'),
        artifacts={f'ranker_{i}.ubj':cohort.digest(output/f'ranker_{i}.ubj') for i in range(len(models))})
    cohort.write_json(output/'selection_before_holdout.json', selection)
    print('VALIDATION_SELECTED', selected, json.dumps(vm,ensure_ascii=False), flush=True)
    holdout=protocol['fresh_holdout']; directory=output/'holdout'
    cohort.generate(directory,holdout['users'],holdout['split'],anchor,seed=holdout['seed'],export_behaviors=False)
    data,base,manifest=cohort.load(directory)
    # Check the entire old cohorts, including previously unselected development users.
    all_old=set(train_ids)|validation_ids
    for split in ['training','test','confirmation']:
        all_old.update(json.loads(line)['user_id'] for line in (root/split/'users.jsonl').read_text(encoding='utf-8').splitlines())
    assert_disjoint(all_old, [u['user_id'] for u in data[1]])
    ty,ts,tm=score(data,base,holdout['dates'],models,ml.model_pack())
    old_delta=paired_delta(ty,ts[selected],ts['原冻结模型'])
    rule_delta=paired_delta(ty,ts[selected],ts[rule])
    promoted=(selected in models and all(d['mean']>=.005 and d['ci95'][0]>0 for d in [old_delta,rule_delta])
              and tm[selected]['recall_at_3']>=tm['原冻结模型']['recall_at_3']-.005)
    groups=np.array([u['scenario'] for u in data[1]])
    subgroups={}
    for group in cohort.SCENARIOS:
        mask=groups==group
        subgroups[group]=metrics(ty[:,mask],{n:ts[n][:,mask] for n in {selected,rule,'原冻结模型'}})
    report=dict(protocol=protocol,selection=selection,holdout_manifest=manifest,holdout=tm,
        selected_method=selected,delta_against_original=old_delta,delta_against_best_rule=rule_delta,
        subgroups=subgroups,promotion_gate_passed=bool(promoted),online_weights_replaced=False,
        original_artifact_unchanged=cohort.digest(ml.ROOT/'marketing_models.joblib')==protocol['original_model_sha256'],
        limitation='Dense one-event/day synthetic generator. Exploration is random. No real booking/adoption ground truth; no fare forecasting claim.')
    cohort.write_json(report_path,report)
    print('LAMBDAMART_HOLDOUT',json.dumps(tm,ensure_ascii=False),'selected',selected,'promote',promoted,flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('root',type=Path)
    parser.add_argument('--anchor',default='2026-10-16')
    args=parser.parse_args();run(args.root,args.anchor)
