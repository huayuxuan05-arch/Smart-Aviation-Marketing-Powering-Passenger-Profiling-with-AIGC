"""Read training-derived priors and frozen test evidence, never train on test rows."""
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def learned_reference():
    import numpy as np
    import marketing_ml as ml
    report=json.loads((ml.ROOT/'training_report.json').read_text(encoding='utf-8'))
    protocol=report['protocol']; cutoff=max(protocol['train_dates'])
    if set(protocol['train_dates']) & set(protocol['test_dates']):raise ValueError('训练与测试截点不可重叠')
    arrays,_,_,destinations=ml.load_data()
    last=ml.day_index(cutoff)
    counts=np.bincount(arrays['dest'][max(0,last-29):last+1].ravel(),minlength=len(destinations))
    prior={city:round(float(count/counts.sum()),6) for city,count in zip(destinations,counts)}
    return {'source':'DAILY_SYN_2024_V2_SUBSET_10K','simulated_users':report['users'],
        'training_cutoff':cutoff,'training_dates':protocol['train_dates'],'test_dates':protocol['test_dates'],
        'selected_model':report['selected'],'test_ranking_metrics':report['ranking'][report['selected']],
        'trained_segments':report['segments'],'destination_training_prior':prior,
        'source_sha256':report['source_sha256'],
        'boundary':'模拟行为关注代理；同一用户跨时间段评估，不代表新用户泛化、购票概率或航司选择偏好。测试仅用于核验，不用于形成先验。'}


def guidance(preferences):
    learned=learned_reference()
    focus={'城市初访':'目的地信息','自然与景区':'景区关注','舒适休闲':'酒店关注','交通与预算':'机票查询','文化与攻略':'攻略准备'}[preferences['theme']]
    segment=max(learned['trained_segments'],key=lambda s:s['center'][focus])
    interests=sorted(((k,segment['center'][k]) for k in ['目的地信息','景区关注','酒店关注','机票查询','攻略准备']),key=lambda p:-p[1])
    return {**{k:v for k,v in learned.items() if k not in ('trained_segments','destination_training_prior')},
        'matched_training_segment':segment['id'],'match_basis':'按本人主动选择主题匹配训练聚类中心，未读取或伪造个人行为',
        'training_content_priorities':interests,
        'rules':['本人明确城市、日期、航司和直飞条件先执行','先比较全程与单程预算，再在允许范围内比较方案',
                 '训练聚类中心仅指导内容侧重；未指定目的地时训练期城市先验仅作次级建议',
                 '测试指标只说明模拟关注任务效果；不改变当前航班事实、不据此扩大预算']}
