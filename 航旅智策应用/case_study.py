"""Anonymous current-consent evidence with immutable local cohort membership."""
from collections import Counter
import json
import re


def cohorts(runtime):
    root=runtime/'case-studies'
    result=[]
    if root.exists():
        for path in sorted(root.glob('*/cohort.json')):
            if not re.fullmatch('[a-z0-9-]{1,64}',path.parent.name):continue
            value=json.loads(path.read_text(encoding='utf-8'))
            result.append({'id':path.parent.name,'label':value['label'],'registered_accounts':len(set(value['public_user_ids']))})
    return result


def select(runtime,profiles,key):
    if not key:return profiles,None
    if not isinstance(key,str) or not re.fullmatch('[a-z0-9-]{1,64}',key):raise ValueError('案例样本编号无效')
    path=runtime/'case-studies'/key/'cohort.json'
    if not path.is_file():raise ValueError('案例样本不存在')
    value=json.loads(path.read_text(encoding='utf-8'));ids=set(value['public_user_ids'])
    selected=[p for p in profiles if p['user_id'] in ids]
    return selected,{'id':key,'label':value['label'],'registered_accounts':len(ids),'currently_shared_accounts':len(selected),
        'membership_frozen_at':value['frozen_at'],'identity_basis':'参与者来源由组织者确认；按固定账号编号去重'}


def evidence(profiles):
    users=Counter();statuses=Counter();feedback=[];ratings=[];reasons=Counter();suitability=Counter();requests=Counter()
    for p in profiles:
        events=p['observations'];kinds={e['kind'] for e in events}
        users['saved_plan']+=bool(p['has_saved_plan'])
        users['search_requested']+=bool(kinds & {'flight_search','flight_request','flight_query_unavailable'})
        users['flight_previewed']+='flight_previewed' in kinds
        users['flight_selected']+='flight_selected' in kinds
        users['flight_rejected']+='flight_rejected' in kinds
        outcomes=[e['result'] for e in events if e['kind']=='flight_search_result']
        users['priced_result']+=any(o['status']=='success' for o in outcomes)
        users['unpriced_inventory']+=any(o['status']=='flights_only' for o in outcomes)
        users['confirmed_empty']+=any(o['status']=='empty' for o in outcomes)
        users['query_failed']+=any(o['status'] in ('failed','timeout','error') for o in outcomes)
        users['unavailable_request']+='flight_query_unavailable' in kinds
        for e in events:
            if e['kind']=='flight_request':
                requests['total']+=1;requests['cache_hit']+=bool(e.get('flight_activity',{}).get('cache_hit'))
                requests['reused_inflight']+=bool(e.get('flight_activity',{}).get('reused_inflight'))
            elif e['kind']=='flight_query_unavailable':requests['unavailable']+=1
        statuses.update(o['status'] for o in outcomes)
        latest=max(p.get('feedback',[]),key=lambda f:f['recorded_at'],default=None)
        if latest:
            feedback.append(latest)
            if latest['rating'] is not None:ratings.append(latest['rating'])
            if latest['suitability']:suitability[latest['suitability']]+=1
            reasons.update(latest['reasons'])
    for key in ('saved_plan','search_requested','flight_previewed','flight_selected','flight_rejected','priced_result','unpriced_inventory','confirmed_empty','query_failed','unavailable_request'):users.setdefault(key,0)
    explicit=sum(p['preferences'].get('theme_source') in ('explicit','historical_explicit') for p in profiles)
    return {'population':len(profiles),'people':dict(users),'query_status_events':dict(statuses),'new_request_events':dict(requests),
        'interest_quality':{'explicit_people':explicit,'unfilled_or_unverified_people':len(profiles)-explicit},
        'feedback':{'respondents':len(feedback),'rating_respondents':len(ratings),'mean_rating':sum(ratings)/len(ratings) if ratings else None,
            'suitability':dict(suitability),'nonadoption_reasons':dict(reasons)},
        'boundary':'人数按当前仍共享的固定用户编号去重；各步骤可交叉，不能相加。失败不代表无航班；未操作不代表拒绝；选择保存不代表购票。历史缺失记录不补造，评价仅计另外同意共享且在当前窗口内的每人最新一份。'}
