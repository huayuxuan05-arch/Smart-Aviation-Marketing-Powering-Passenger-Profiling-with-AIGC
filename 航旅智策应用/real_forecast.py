"""Freeze attention forecasts before outcomes exist. No purchase probabilities."""
from collections import defaultdict
from datetime import datetime,timedelta
import json
import uuid


def initialize(c):c.execute('CREATE TABLE IF NOT EXISTS real_forecast_snapshots(id TEXT PRIMARY KEY,campaign_id TEXT,created_at TEXT,payload TEXT)')


def freeze(campaign_id):
    import personal_app as personal
    import real_marketing_workflow as workflow
    import real_travelers as real
    campaign=workflow.get(campaign_id);profiles=workflow._profiles(campaign);clock=real.now();predictions=[];insufficient=0
    for p in profiles:
        observed=[e for e in p['observations'] if e['destination'] and e['kind'] in ('destination_view','flight_search','flight_request','flight_selected','plan_saved') and datetime.fromisoformat(e['at'])<=clock]
        unique={(e['at'][:10],e['destination']) for e in observed}
        if len({day for day,_ in unique})<7:insufficient+=1;continue
        scores=defaultdict(float)
        for day,city in unique:
            age=(clock.date()-datetime.fromisoformat(day).date()).days;scores[city]+=2**(-age/14)
        top=sorted(scores,key=lambda city:(-scores[city],city))[:3]
        predictions.append({'user_id':p['user_id'],'top3_destinations':top,'history_active_days':len({day for day,_ in unique})})
    value={'id':'FORECAST_'+uuid.uuid4().hex,'campaign_id':campaign_id,'asof':clock.isoformat(),'horizon_end':(clock+timedelta(days=7)).isoformat(),
        'method':'14天衰减关注规则基线','target':'未来7天至少在2个不同日期关注同一目的地；不是购票预测',
        'predictions':predictions,'insufficient_history_people':insufficient,'registered_members_at_snapshot':len(profiles),
        'boundary':'至少7个活跃日期才给参考排序，原始航司、日期与预算不修改。当前结果先封存，7天窗口结束后才评价。'}
    with personal.db() as c:
        initialize(c)
        active={r['public_id'] for r in real.rows(c)}
        if any(p['user_id'] not in active for p in profiles):raise ValueError('授权已改变，请刷新后保存预测')
        c.execute('INSERT INTO real_forecast_snapshots VALUES(?,?,?,?)',(value['id'],campaign_id,value['asof'],json.dumps(value,ensure_ascii=False)))
    return evaluate(value['id'])


def evaluate(ident):
    import personal_app as personal
    import real_marketing_workflow as workflow
    import real_travelers as real
    with personal.db() as c:
        initialize(c);row=c.execute('SELECT payload FROM real_forecast_snapshots WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('预测快照不存在')
    value=json.loads(row[0]);campaign=workflow.get(value['campaign_id']);ids=set(campaign['user_ids'])
    lookback=max(30,(real.now()-datetime.fromisoformat(value['asof'])).days+8)
    with personal.db() as c:profiles=[real.public_profile(c,r,lookback) for r in real.rows(c) if r['public_id'] in ids]
    active={p['user_id']:p for p in profiles}
    value['predictions']=[p for p in value['predictions'] if p['user_id'] in active]
    value['currently_shared_members']=len(active);value['metrics']=None
    value['insufficient_history_people']=max(0,len(active)-len(value['predictions']))
    if real.now().isoformat()<value['horizon_end']:
        value['status']='等待完整7天观察窗口' if value['predictions'] else '历史不足，暂不给预测排序'
        return value
    hits=[];no_relevant=0
    for prediction in value['predictions']:
        p=active[prediction['user_id']]
        dates=defaultdict(set)
        for e in p['observations']:
            if e['destination'] and e['kind'] in ('destination_view','flight_search','flight_request','flight_selected','plan_saved') and value['asof']<e['at']<=value['horizon_end']:dates[e['destination']].add(e['at'][:10])
        actual={city for city,days in dates.items() if len(days)>=2}
        if actual:hits.append(len(actual & set(prediction['top3_destinations']))/len(actual))
        else:no_relevant+=1
    value['status']='观察窗口已结束';value['metrics']={'recall_at_3':sum(hits)/len(hits) if hits else None,'eligible_people':len(hits),'no_relevant_people':no_relevant}
    return value
