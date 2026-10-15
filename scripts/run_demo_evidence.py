"""复现模拟案例与公平对照；不训练模型，不写用户活动库，不调用大模型。"""
from pathlib import Path
import argparse
import csv
from datetime import datetime, timedelta
import hashlib
import json
import os
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parents[1]
APP = REPO / '航旅智策应用'
sys.path.insert(0, str(APP))
os.environ['AEROLENS_GENERATION_MODE'] = 'template'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'

import numpy as np
import marketing_ml as ml
import marketing_app as app
import decision_logic as decision
from algorithm_layer import HOLIDAYS, profile
from data_layer import connect, SOURCE, SOURCE_HASHES, CST, VERSION

SEED = 20261015
METHODS = ['动态学习模型', '逻辑回归', '近30天频次', '14天时间衰减', '最近关注', '固定六月画像', '训练热门']
TEST_DATES = ['2024-10-15', '2024-11-15', '2024-12-15']
CASE_DATES = ['2024-09-23', '2024-09-26', '2024-09-30']


def digest(path):
    if not path.exists():
        return None
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(app.clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def csv_rows(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def per_user_metrics(labels, scores, k=3):
    """每名旅客一个值，无相关目的地保留NaN并单列，不计作零。"""
    order = np.argsort(-scores, axis=1, kind='stable')[:, :k]
    rel = np.take_along_axis(labels, order, axis=1)
    count = labels.sum(axis=1)
    discount = 1 / np.log2(np.arange(2, k + 2))
    ideal = np.array([discount[:min(int(v), k)].sum() for v in count])
    recall = np.divide(rel.sum(axis=1), count, out=np.full(len(count), np.nan), where=count > 0)
    ndcg = np.divide((rel * discount).sum(axis=1), ideal, out=np.full(len(count), np.nan), where=ideal > 0)
    return {'Recall@3': recall, 'NDCG@3': ndcg}


def paired_ci(first, second, repetitions):
    """同一旅客跨日期整组重采样，以有效快照数加权。"""
    first = np.atleast_2d(first)
    second = np.atleast_2d(second)
    if not np.array_equal(np.isfinite(first), np.isfinite(second)):
        raise ValueError('Paired comparisons must use identical eligible snapshots')
    sums = np.nansum(first - second, axis=0)
    counts = np.isfinite(first).sum(axis=0)
    rng = np.random.default_rng(SEED)
    values = []
    for start in range(0, repetitions, 50):
        indices = rng.integers(0, len(sums), size=(min(50, repetitions - start), len(sums)))
        numerator = sums[indices].sum(axis=1)
        denominator = counts[indices].sum(axis=1)
        values.extend((numerator / denominator).tolist())
    interval = np.quantile(values, [.025, .975])
    return {'difference': float(sums.sum() / counts.sum()),
            'ci95': [float(v) for v in interval], 'bootstrap_repetitions': repetitions,
            'resampling_unit': '旅客编号；跨日期快照整组重采样', 'seed': SEED}


def ranking_experiment(out, repetitions):
    _, users, _, destinations = ml.load_data()
    pack = ml.model_pack()
    fixed = ml.snapshot('2024-06-30')['X'][:, :, 1]
    train_frequency = np.concatenate([ml.snapshot(d)['X'][:, :, 1] for d in pack['report']['protocol']['train_dates']])
    popular = train_frequency.mean(axis=0)
    scopes = {'固定测试': TEST_DATES, '国庆专项': ['2024-09-30']}
    results, score_audit = {}, []
    for scope, dates in scopes.items():
        collected = {name: {'Recall@3': [], 'NDCG@3': []} for name in METHODS}
        per_date = []
        for date in dates:
            print('RANKING', scope, date, flush=True)
            snap = ml.snapshot(date)
            labels = ml.targets(snap['day'])['continue']
            flat = snap['X'].reshape(-1, len(ml.FEATURES))
            scores = {
                '动态学习模型': pack['models']['boost'].predict_proba(flat)[:, 1].reshape(len(users), len(destinations)),
                '逻辑回归': pack['models']['continue'].predict_proba(pack['scaler'].transform(flat))[:, 1].reshape(len(users), len(destinations)),
                '近30天频次': snap['X'][:, :, 1], '14天时间衰减': snap['X'][:, :, 3],
                '最近关注': -snap['X'][:, :, 4], '固定六月画像': fixed,
                '训练热门': np.broadcast_to(popular, (len(users), len(destinations)))}
            for name, values in scores.items():
                metrics = per_user_metrics(labels, values)
                for metric, array in metrics.items():
                    collected[name][metric].append(array)
                per_date.append({'scope': scope, 'asof': date, 'method': name,
                                 **{k: float(np.nanmean(v)) for k, v in metrics.items()},
                                 'eligible_snapshots': int((labels.sum(axis=1) > 0).sum()),
                                 'no_relevant_snapshots': int((labels.sum(axis=1) == 0).sum())})
            score_audit.append({'scope': scope, 'asof': date,
                                'feature_end': date + ' 23:59:59',
                                'label_start': (datetime.fromisoformat(date) + timedelta(days=1)).date().isoformat(),
                                'label_end': (datetime.fromisoformat(date) + timedelta(days=7)).date().isoformat()})
        metric_arrays = {name: {k: np.stack(v) for k, v in values.items()} for name, values in collected.items()}
        table = []
        for name, values in metric_arrays.items():
            array = values['Recall@3']
            table.append({'method': name, **{k: float(np.nanmean(v)) for k, v in values.items()},
                          'eligible_snapshots': int(np.isfinite(array).sum()),
                          'no_relevant_snapshots': int((~np.isfinite(array)).sum())})
        differences = []
        for baseline in METHODS[1:]:
            for metric in ['Recall@3', 'NDCG@3']:
                differences.append({'baseline': baseline, 'metric': metric,
                                    **paired_ci(metric_arrays[METHODS[0]][metric], metric_arrays[baseline][metric], repetitions)})
        csv_rows(out / ('ranking-frozen.csv' if scope == '固定测试' else 'ranking-national.csv'), table)
        csv_rows(out / ('ranking-frozen-by-date.csv' if scope == '固定测试' else 'ranking-national-by-date.csv'), per_date)
        results[scope] = {'dates': dates, 'users': len(users), 'destinations': len(destinations),
                         'metrics': table, 'paired_differences': differences,
                         'inference': '预先指定动态模型与近30天频次为主要对照；其他比较为探索性，区间未作多重比较调整'}
        if scope == '固定测试':
            aliases = dict(zip(METHODS, ['boost', 'continue', '近30天频次', '时间衰减规则', '最近一次关注', '固定画像', '训练集热门']))
            for row in table:
                saved = pack['report']['ranking'][aliases[row['method']]]
                for key, saved_key in [('Recall@3', 'recall_at_3'), ('NDCG@3', 'ndcg_at_3')]:
                    if abs(row[key] - saved[saved_key]) > 1e-7:
                        raise ValueError('Frozen test does not reproduce saved metrics: ' + row['method'])
        arrays = {f'method_{i}_{metric}': values[metric] for i, (_, values) in enumerate(metric_arrays.items()) for metric in values}
        np.savez_compressed(out / ('per-user-frozen.npz' if scope == '固定测试' else 'per-user-national.npz'), **arrays)
    return {'protocol': {'train_dates': pack['report']['protocol']['train_dates'],
                         'validation_dates': pack['report']['protocol']['validation_dates'],
                         'model_selection_labels_available_through': '2024-09-22',
                         'target': '截点后7天同目的地至少2次搜索过程；非购票概率',
                         'users_seen_during_training': True, 'candidate_count': 41,
                         'ties': '所有方法按同一目的地字典稳定排序',
                         'no_relevant_policy': '单列，不计入Recall和NDCG均值',
                         'seed': SEED, 'no_retraining': True, 'windows': score_audit}, 'results': results}


def decision_experiment(source, out, repetitions):
    print('DECISION matched-cohort ablation', flush=True)
    date = '2024-09-30'
    holiday = next(h for h in HOLIDAYS if h['id'] == 'national')
    arrays, users, _, destinations = ml.load_data()
    snap = app.trained_snapshot(date)
    orders = np.argsort(-snap['scores'], axis=1, kind='stable')
    unsub = {r[0] for r in source.execute('SELECT DISTINCT user_id FROM events WHERE feedback_type="unsubscribe" AND event_time_cst<=?', (date + ' 23:59:59',))}
    groups, days = [], set()
    for i, user in enumerate(users):
        candidates = [int(j) for j in orders[i] if snap['count'][60][i, j] > 0][:3]
        choices = []
        for j in candidates:
            if snap['scores'][i, j] < .35:
                continue
            intent = decision.trip_intent(arrays, i, j, date, holiday)
            row = {**user, 'destination': destinations[j], 'travel_date': intent['travel_date'],
                   'budget': intent['budget'], 'intent': intent, 'score': float(snap['scores'][i, j]),
                   'preference_rank': len(choices) + 1, 'flight': None}
            choices.append(row)
            days.add(row['travel_date'])
        groups.append(choices)
    quotes = {}
    for day in sorted(days):
        for f in source.execute('SELECT rowid AS source_row,* FROM flights WHERE 出发日=? ORDER BY 机票票价,rowid', (day,)):
            quotes.setdefault((day, f['出发城市'], f['到达城市']), dict(f))
    pairs = []
    for user, choices in zip(users, groups):
        for row in choices:
            f = quotes.get((row['travel_date'], row['usual_departure_city'], row['destination']))
            if f and f['机票票价'] > 0 and (row['budget'] is None or f['机票票价'] <= row['budget']):
                row['flight'] = {**f, 'candidate_id': 'FLIGHT_ROW_' + str(f['source_row'] + 1)}
        first = choices[0] if choices else None
        selected = decision.select_candidate(choices) if choices else None
        pair = {'user_id': user['user_id'], 'opted_out': user['user_id'] in unsub,
                'candidate_count': len(choices),
                'has_interest_candidate': bool(choices), 'primary_score': first['score'] if first else -1,
                'constrained_score': selected['score'] if selected else -1,
                'primary_destination': first['destination'] if first else '',
                'constrained_destination': selected['destination'] if selected else '',
                'primary_matched': bool(first and first['flight']), 'constrained_matched': bool(selected and selected['flight']),
                'primary_ready': bool(first and decision.business_ready(first)),
                'constrained_ready': bool(selected and decision.business_ready(selected)),
                'changed': bool(selected and selected['preference_rank'] > 1)}
        pair['selection_diagnostic'] = (
            '无兴趣候选' if not choices else '只有一个达标兴趣候选' if len(choices) == 1
            else '发生备选替换' if pair['changed'] else '首选已满足业务条件'
            if pair['primary_ready'] else '有备选但没有更可行候选')
        pairs.append(pair)
    eligible = [p for p in pairs if not p['opted_out']]
    common300 = sorted((p for p in eligible if p['has_interest_candidate']), key=lambda p: (-p['primary_score'], p['user_id']))[:300]
    scopes = {'未退订全量同群': eligible, '共同兴趣名单300人': common300}
    results = {}
    for scope, rows in scopes.items():
        table = []
        for prefix, name in [('primary', '只取兴趣首选'), ('constrained', '同候选内约束选择')]:
            matched = sum(p[prefix + '_matched'] for p in rows)
            ready = sum(p[prefix + '_ready'] for p in rows)
            table.append({'method': name, 'users': len(rows), 'recommended': sum(p['has_interest_candidate'] for p in rows),
                          'historical_matches': matched, 'historical_match_rate': matched / len(rows),
                          'business_ready': ready, 'business_ready_rate': ready / len(rows),
                          'deferred': len(rows) - ready, 'defer_rate': 1 - ready / len(rows),
                          'execution': '未执行 仅离线候选对照'})
        intervals = {}
        for key in ['matched', 'ready']:
            first = np.array([p['constrained_' + key] for p in rows], float)
            second = np.array([p['primary_' + key] for p in rows], float)
            intervals[key] = paired_ci(first, second, repetitions)
        results[scope] = {'metrics': table, 'paired_differences': intervals,
                         'alternative_selected': sum(p['changed'] for p in rows),
                         'diagnostics': {reason: sum(p['selection_diagnostic'] == reason for p in rows)
                                         for reason in sorted({p['selection_diagnostic'] for p in rows})},
                         'execution_note': '离线建议对照；两种方法执行前均采用同一资格门控，不实际发送不合格建议'}
    csv_rows(out / 'decision-paired-users.csv', pairs)
    # Exploratory policy analysis prompted by the zero-gain fixed cohort. It selects
    # different users from the SAME eligible pool, never by future outcomes.
    policies = [
        ('兴趣分数前300人', common300, 'primary'),
        ('先筛历史候选再选300人', sorted((p for p in eligible if p['constrained_matched']),
                                    key=lambda p: (-p['constrained_score'], p['user_id']))[:300], 'constrained'),
        ('先筛业务条件再选最多300人', sorted((p for p in eligible if p['constrained_ready']),
                                        key=lambda p: (-p['constrained_score'], p['user_id']))[:300], 'constrained')]
    labels = ml.targets(ml.day_index(date))['continue']
    user_index = {u['user_id']: i for i, u in enumerate(users)}
    policy_rows, policy_members = [], []
    for name, rows, prefix in policies:
        observed = sum(int(labels[user_index[p['user_id']], destinations.index(p[prefix + '_destination'])]) for p in rows)
        ready = sum(p[prefix + '_ready'] for p in rows)
        policy_rows.append({'policy': name, 'pool': len(eligible), 'capacity': 300,
                            'selected': len(rows), 'shortfall': 300 - len(rows),
                            'historical_matches': sum(p[prefix + '_matched'] for p in rows),
                            'business_ready': ready, 'ready_rate_in_selected': ready / len(rows),
                            'ready_per_300_capacity': ready / 300,
                            'future_continue': observed, 'future_continue_rate': observed / len(rows),
                            'nominal_selection_cost': len(rows) * .5,
                            'qualified_cost_scenario': ready * .5,
                            'execution': '仅离线策略试验 未提交新触达'})
        policy_members.extend({'policy': name, 'user_id': p['user_id'], 'destination': p[prefix + '_destination']} for p in rows)
    csv_rows(out / 'selection-policy-comparison.csv', policy_rows)
    csv_rows(out / 'selection-policy-members.csv', policy_members)
    return {'asof': date, 'holiday': '2024国庆', 'original_population': len(users),
            'opted_out_excluded': len(users) - len(eligible), 'results': results,
            'selection_policy_exploration': {'metrics': policy_rows,
                'basis': '同一9799人未退订池，同一最多300人名额和150元费用上限，日期预算规则相同；按截点前条件选择，不依据未来结果选人',
                'status': '根据共同300人零改善诊断提出的探索性策略；不是同一名单候选消融或事先预注册的确认试验',
                'capacity_note': '资格优先不足300时明确报告缺额，不补入不合格旅客；后续代理标签仅在冻结名单后评价'},
            'protocol': {'candidate_pool': '同一个模型、近期60天有依据、分数至少0.35、最多3目的地',
                         'common300_selection': '按首选分数和旅客编号冻结同一名单，不前置筛航班，不按结果选人',
                         'capacity': 300, 'unit_cost_scenario': .5, 'budget_scenario': 150,
                         'date_budget_rules': '两方法使用同一当次日期与预算证据及原始出发地',
                         'model_unchanged': True, 'not_randomized_marketing_trial': True}}


def compact_profile(source, uid, date):
    result = profile(source, uid, date, 30, 14)
    return {k: result[k] for k in ['user', 'as_of_time', 'record_count', 'destinations', 'categories', 'channels', 'budget', 'records', 'strategy']}


def cases(source, out):
    print('CASES isolated workflow', flush=True)
    audience = app.build_audience(source, {'holiday': 'national', 'asof': '2024-09-30', 'limit': 300})
    positive = next(p for p in audience['audience'] if p['user_id'] == 'SIMU_00179')
    negative = next(p for p in audience['audience'] if p['user_id'] == 'SIMU_00732')
    assert positive['business_ready'] and not negative['business_ready']
    campaign = app.save_campaign(source, {'name': '国庆模拟案例 流程验证', 'holiday': 'national', 'asof': '2024-09-30', 'limit': 300})
    campaign = app.revise_audience(campaign['id'], {'user_ids': [positive['user_id'], negative['user_id']]})
    steps = [{'step': '冻结双人名单', 'campaign_revision': campaign['revision'], 'users': campaign['audience_count']}]
    creatives = []
    for row in [positive, negative]:
        material = app.generate_creative(source, campaign['id'], {'user_id': row['user_id']})
        assert material['generation_mode'] == 'template' and not material['risk_flags'] and material['model_alias'] is None
        material = app.update_creative(campaign['id'], material['id'], {'action': 'approve', 'checks': ['facts', 'historical', 'synthetic']})
        creatives.append(material)
        (out / (row['user_id'] + '-poster.svg')).write_text(material['poster_svg'], encoding='utf-8')
    with app.db() as state:
        app.audit(state, campaign['id'], '实验脚本核验', '三项审核确认由脚本提交，仅验证审核流程，不代表独立人工质量评分')
    ready = app.get_campaign(campaign['id'])['execution']
    assert ready['eligible'] == 1
    first = app.launch(source, campaign['id'], {'confirm': True})
    assert first['last_launch']['sent'] == 1
    assert first['deliveries'][0]['user_id'] == positive['user_id']
    assert all(first['deliveries'][0][key] is None for key in ['exposure', 'click', 'payment'])
    steps.append({'step': '首次本地模拟触达', 'sent': 1, 'blocked': first['last_launch']['blocked']})
    second = app.launch(source, campaign['id'], {'confirm': True})
    assert second['last_launch']['sent'] == 0 and len(second['deliveries']) == 1
    steps.append({'step': '重复触达检查', 'sent': 0, 'blocked': second['last_launch']['blocked']})
    evaluation = app.evaluate_campaign(campaign['id'])
    followup = app.followup(source, campaign['id'], positive['user_id'])
    final = app.get_campaign(campaign['id'])
    write_json(out / 'workflow-campaign.json', final)
    dynamic = {'user_id': 'SIMU_00748', 'selection': '按截点前画像和模型首选变化筛选示例；不是总体效果证据',
               'dates': CASE_DATES, 'snapshots': []}
    arrays, users, _, dests = ml.load_data()
    index = next(i for i, u in enumerate(users) if u['user_id'] == dynamic['user_id'])
    for date in CASE_DATES:
        snap = app.trained_snapshot(date)
        j = int(np.argmax(snap['scores'][index]))
        dynamic['snapshots'].append({'date': date, 'profile': compact_profile(source, dynamic['user_id'], date),
                                     'model_top1': dests[j], 'model_score': float(snap['scores'][index, j])})
    return {'campaign_id': final['id'], 'positive': positive, 'deferred': negative,
            'steps': steps, 'readiness_before_launch': ready, 'creatives': creatives,
            'evaluation': evaluation, 'followup': followup, 'dynamic': dynamic,
            'original_selection_funnel': audience['selection_funnel'],
            'business_ready_in_original_300': audience['business_ready_count'],
            'review_basis': '脚本提交三项审核确认以验证门控；未开展独立人工内容质量评测',
            'no_real_delivery': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, default=APP / 'runtime' / 'evidence')
    parser.add_argument('--bootstrap', type=int, default=2000)
    args = parser.parse_args()
    out = args.out.resolve()
    if not out.is_relative_to(APP / 'runtime') or args.bootstrap < 1000:
        raise ValueError('Output must be inside project runtime; use at least 1000 bootstrap replicates')
    out.mkdir(parents=True, exist_ok=True)
    user_state = {p: digest(p) for p in [APP / 'runtime' / 'marketing.sqlite3', APP / 'runtime' / 'personal.sqlite3']}
    source_proof = {name: digest(SOURCE / name) for name in SOURCE_HASHES}
    if source_proof != SOURCE_HASHES:
        raise ValueError('Source fingerprints differ')
    proof = json.loads((ml.ROOT / 'artifact_manifest.json').read_text(encoding='utf-8'))
    artifact_proof = {name: digest(ml.ROOT / name) for name in proof['artifacts']}
    if any(artifact_proof[n] != proof['artifacts'][n]['sha256'] for n in artifact_proof):
        raise ValueError('Model artifact fingerprints differ')
    report = {'created_at': datetime.now(CST).isoformat(timespec='seconds'), 'source_version': VERSION,
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
              'source_sha256': source_proof, 'artifacts_sha256': artifact_proof,
              'seed': SEED, 'synthetic_behavior': True, 'generation_mode': 'template'}
    report['implementation_sha256'] = {str(p.relative_to(REPO)): digest(p) for p in [
        Path(__file__).resolve(), APP / 'marketing_ml.py', APP / 'marketing_app.py',
        APP / 'decision_logic.py', APP / 'algorithm_layer.py', APP / 'local_generation.py', APP / 'content_generation.py']}
    import sklearn
    report['environment'] = {'python': sys.version.split()[0], 'numpy': np.__version__, 'scikit_learn': sklearn.__version__}
    report['ranking'] = ranking_experiment(out, args.bootstrap)
    with connect() as source:
        report['decision'] = decision_experiment(source, out, args.bootstrap)
        with TemporaryDirectory(prefix='case_evidence_', dir=APP / 'runtime' / 'tmp') as temporary:
            original = app.RUNTIME
            try:
                app.RUNTIME = Path(temporary)
                report['cases'] = cases(source, out)
                (out / 'state').mkdir(exist_ok=True)
                shutil.copyfile(app.RUNTIME / 'marketing.sqlite3', out / 'state' / 'marketing.sqlite3')
            finally:
                app.RUNTIME = original
    report['isolation'] = {'source_files_unchanged': source_proof == {name: digest(SOURCE / name) for name in SOURCE_HASHES},
                           'model_files_unchanged': artifact_proof == {name: digest(ml.ROOT / name) for name in artifact_proof},
                           'user_activity_files_unchanged': all(digest(p) == v for p, v in user_state.items()),
                           'activity_state': 'runtime/evidence/state/marketing.sqlite3'}
    if not all(v for k, v in report['isolation'].items() if k.endswith('_unchanged')):
        raise ValueError('Input or user activity changed during evidence run; inspect provenance before publishing')
    write_json(out / 'results.json', report)
    print('EVIDENCE_COMPLETE', out, flush=True)
    print(json.dumps({scope: result['metrics'] for scope, result in report['ranking']['results'].items()}, ensure_ascii=False), flush=True)
    print(json.dumps(report['decision']['results'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
