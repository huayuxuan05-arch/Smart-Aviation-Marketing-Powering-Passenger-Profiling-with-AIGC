"""Serve the active, flight-verified synthetic test population in trip planning."""
from __future__ import annotations
import json
import math
import threading
from datetime import datetime,timedelta
from pathlib import Path
import marketing_ml as ml
import independent_cohort as cohort
from independent_evaluation import frozen_scores
import flight_quotes as flights
from constraint_planner import optimize
from data_layer import RUNTIME

_CACHE={};_LOCK=threading.RLock()


def metadata(runtime=None):
    path=Path(runtime or RUNTIME)/'current-cohorts'/'active.json'
    if not path.exists():return None
    active=json.loads(path.read_text(encoding='utf-8'));root=Path(active['root'])
    manifest=json.loads((root/'test'/'manifest.json').read_text(encoding='utf-8'))
    protocol=json.loads((root/'protocol.json').read_text(encoding='utf-8'))
    return dict(version=active['version'],verified_at=active['verified_at'],population=manifest['users'],
        asof=manifest['behavior_end'],asof_min=(datetime.fromisoformat(manifest['behavior_start'])+timedelta(days=30)).date().isoformat(),
        start_date=protocol['splits']['test']['contexts'][0]['query']['departure'],budget_policy='prefer')


def load(split='test'):
    if split not in ('training','validation','test'):raise ValueError('Unknown cohort split')
    active=json.loads((RUNTIME/'current-cohorts'/'active.json').read_text(encoding='utf-8'))
    with _LOCK:
        key=active['acceptance_sha256']
        if _CACHE.get('key')!=key:
            _CACHE.clear();_CACHE.update(key=key,splits={})
        if split not in _CACHE['splits']:
            root=Path(active['root']);data,base,manifest=cohort.load(root/split)
            records={}
            for path in (root/'successful-quotes').glob('*.json'):
                record=json.loads(path.read_text(encoding='utf-8'));q=record['query']
                records[(q['origin'],q['destinations'][0],q['departure'],q['return_date'])]=record
            _CACHE['splits'][split]=dict(data=data,base=base,manifest=manifest,records=records,
                lookup={u['user_id']:i for i,u in enumerate(data[1])},profiles={})
        return _CACHE['splits'][split]


def profile_for(cache,asof):
    with _LOCK:
        if asof not in cache['profiles']:
            snapshot=ml.snapshot(asof,dataset=cache['data'],base_date=cache['base'],
                holidays=[h for h in cohort.HOLIDAYS if h['published']<=asof])
            cache['profiles'][asof]=(snapshot,frozen_scores(snapshot,ml.model_pack()))
            if len(cache['profiles'])>3:
                first=next(iter(cache['profiles']))
                if first!=asof:del cache['profiles'][first]
        return cache['profiles'][asof]


def make_plan(source,user_id,raw=None,compact=False):
    import travel_planner as planner
    raw=raw or {}
    split=next((s for s in ('training','validation','test') if str(user_id).startswith('LIVE_V2_'+s.upper()+'_')),None)
    if split is None:raise ValueError('当前旅客不存在')
    cache=load(split)
    if user_id not in cache['lookup']:raise ValueError('当前旅客不存在')
    index=cache['lookup'][user_id];u=cache['data'][1][index]
    asof=raw.get('asof') or cache['manifest']['behavior_end']
    if not cache['manifest']['behavior_start']<=asof<=cache['manifest']['behavior_end']:
        raise ValueError('画像日期超出当前年度行为数据范围')
    snapshot,scores=profile_for(cache,asof)
    days=int(raw.get('days') or u['days'])
    if days not in (2,3,4,5,6,7,8):raise ValueError('请选择2至8天行程')
    start=raw.get('start_date') or u['start_date'];end=(datetime.fromisoformat(start)+timedelta(days=days-1)).date().isoformat()
    total=float(raw['trip_budget']) if raw.get('trip_budget') not in (None,'') else u['trip_budget']
    if not math.isfinite(total) or not 100<=total<=100000:raise ValueError('预算金额不合法')
    origin=u['usual_departure_city'];city=u['requested_destination'];j=cache['data'][3].index(city)
    theme=int(np_argmax(snapshot['X'][index,j,7:12]));themes=['城市初访','自然与景区','舒适休闲','交通与预算','文化与攻略']
    party=u['travel_party'];pace=raw.get('pace','跟随画像')
    if pace=='跟随画像':pace='轻松' if party in ('亲子','长者同行') else '均衡'
    if pace not in ('轻松','均衡','充实'):raise ValueError('旅行节奏不支持')
    record=cache['records'].get((origin,city,start,end));candidates=[]
    if record and flights.is_fresh(record['requested_at']):
        for option in record['result']['options']:
            candidates.append(dict(destination=city,start_date=start,origin=origin,option=option,
                max_stops=max(len(option[leg]['segments'])-1 for leg in ['outbound','inbound']),
                query_id=record['id'],observed_at=record['requested_at'],interest_score=float(scores[index,j])))
    preferences=dict(one_way_airfare={'min':0,'max':u['airfare_cap']},adult_trip_budget={'min':0,'max':total},days=days,destination=city,start_date=start)
    recommendation=optimize(candidates,preferences,allow_alternatives=True,budget_policy='prefer');selected=recommendation.get('selected')
    summary=dict(user_id=user_id,origin=origin,destination=city,requested_destination=city,start_date=start,end_date=end,
        days=days,party=party,theme=themes[theme],pace=pace,score=round(float(scores[index,j]),4),
        flight_kind='当前航班' if selected else '航班待匹配',flight_date_exact=bool(selected),flight_reference_fare=None,
        flight_numbers=[],route_available=bool(selected),has_return_reference=bool(selected),
        date_basis='本次模拟旅客明确的旅行日期',selection_reason='保留本次出行城市；按近期行为定制主题、节奏与备选费用',
        budget_excess=selected['one_way_budget_gap'] if selected else None,asof=asof,bookable=False,
        plan_version='current-queryable-budget-preferred-v2',allowed_max_stops=u['allowed_max_stops'],is_synthetic=True)
    if compact:return summary
    def pending(day):return dict(flights=[],gateway=city,destination=city,target_date=day,kind='当前航班',status='',exact_date=False,ground_transfer=None,reference_fare=0,date_gap=0)
    plan=planner.compose_plan(summary,{'budget':u['airfare_cap'],'budget_basis':'模拟旅客原预算偏好'},pending(start),pending(end),theme,
        {'days':days,'trip_budget':total,'adjust_lodging':False},
        ['当前旅客为独立生成的模拟样本。','预算内优先，无预算内方案时保留带报价的备选。'],[])
    plan=flights.latest_only(plan)
    plan['recommendation_policy']='budget-preferred-v1'
    plan['budget']['trip_budget_range']={'min':None,'max':total,'source':'synthetic'}
    plan['budget']['one_way_airfare_range']={'min':None,'max':u['airfare_cap'],'source':'synthetic'}
    plan['budget']['basis']='机票采用本次联网报价；住宿、餐饮和活动按每名成人情景估算。'
    if selected:
        values={'去程航空':selected['option']['outbound']['price_cny'],'返程航空':selected['option']['inbound']['price_cny'],
            '住宿':selected['lodging_nightly_scenario']*(days-1),'餐饮':selected['food_daily_scenario']*days,
            '市内交通':50*days,'景点与体验预留':selected['activity_scenario'],'机动预留':selected['reserve']}
        for component in plan['budget']['components']:
            component.update(value=values[component['name']],basis='本次联网航班报价' if component['name'] in ('去程航空','返程航空') else '旅游费用情景估算')
        plan['budget'].update(estimated_total=selected['estimated_total'],difference=selected['estimated_total']-total)
        plan['live_flights']=dict(query_id=record['id'],observed_at=record['requested_at'],adults=1,option=selected['option'],source=record['result']['source'],fare_basis=record['result']['fare_basis'])
        plan['budget_status']='within_budget' if selected['one_way_budget_gap']==0 and selected['total_budget_gap']==0 else 'over_budget'
        plan['daily_itinerary'][0]['blocks'][0]['detail']='去程抵达：'+selected['option']['outbound']['arrival_time']
        plan['daily_itinerary'][-1]['blocks'][-1]['detail']='返程起飞：'+selected['option']['inbound']['departure_time']
    else:plan['budget_status']='awaiting_quote'
    return plan


def np_argmax(values):
    return max(range(len(values)),key=lambda i:values[i])


def list_plans(source,raw=None):
    raw=raw or {};cache=load();users=cache['data'][1];query=str(raw.get('q','')).strip().lower()
    matched=[u for u in users if not query or any(query in str(u.get(k,'')).lower() for k in ['user_id','residence_city','usual_departure_city','travel_party'])]
    page=max(1,int(raw.get('page',1)));size=min(50,max(1,int(raw.get('page_size',20))))
    items=[make_plan(source,u['user_id'],raw,compact=True) for u in matched[(page-1)*size:page*size]]
    settings={**raw,'cohort':'current','asof':raw.get('asof') or cache['manifest']['behavior_end'],'days':int(raw.get('days') or 3)}
    return dict(population=len(users),total=len(matched),page=page,page_size=size,items=items,settings=settings,
        coverage=dict(population=len(users),planned=len(users),preferred_destination_retained=len(users)),
        coverage_scope='每名旅客保留旅行方案；预算内与超预算推荐分别标记')
