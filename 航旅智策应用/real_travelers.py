"""Consented real traveler profiles, observed intent and cohort decisions.

No synthetic sessions are enrolled automatically. Raw chat and browser tokens
are never exposed to the marketing workspace. Observation time is server time.
"""
from collections import Counter
from datetime import datetime,timedelta
import copy
import json
import os
import uuid
from data_layer import CST
from airline_preferences import AIRLINES

PUBLIC_FIELDS=['origin','destination','start_date','days','party','pace','theme','planning_stage',
    'trip_budget','trip_budget_min','airfare_cap','airfare_min','required_airlines','excluded_airlines',
    'date_flexibility','lodging_priority','fallback_policy','overbudget_policy','preferred_attractions','flight_budget_policy']
ACTIVITY_SECTIONS={'page':'个人页面','assistant':'旅行需求','preferences':'旅行偏好','profile':'偏好更新','history':'历史方案',
    'plan':'旅行方案','flights':'航班搜索','daily':'每日行程','lodging':'住宿安排','budget':'费用预算',
    'backup':'调整方案','trip-ai':'旅行建议','checklist':'行前清单','dates':'日期备选','airlines':'航司标签','details':'细化需求'}
ACTIVITY_ACTIONS={'open-plan':'查看历史方案','apply-date':'比较备选日期','trip-export':'导出旅行方案',
    'trip-print':'导出打印方案','trip-ai':'生成旅行建议','preview':'比较航班预算',
    'request-draft':'提交旅行需求','feedback-draft':'提交调整需求','cancel-draft':'取消需求草稿'}


def mode():return os.environ.get('AEROLENS_MARKETING_DATA_MODE','real')
def now():return datetime.now(CST)


def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS real_traveler_consent(
        owner TEXT PRIMARY KEY,public_id TEXT UNIQUE,enabled INTEGER,updated_at TEXT);
        CREATE TABLE IF NOT EXISTS real_profile_snapshots(
        id INTEGER PRIMARY KEY,owner TEXT,at TEXT,revision INTEGER,preferences TEXT);
        CREATE TABLE IF NOT EXISTS real_traveler_events(
        id INTEGER PRIMARY KEY,owner TEXT,at TEXT,kind TEXT,destination TEXT,payload TEXT);
        CREATE INDEX IF NOT EXISTS real_events_owner ON real_traveler_events(owner,at);
        CREATE INDEX IF NOT EXISTS real_snapshots_owner ON real_profile_snapshots(owner,at);
        CREATE TABLE IF NOT EXISTS real_marketing_campaigns(id TEXT PRIMARY KEY,payload TEXT);''')


def consent_view(c,owner):
    row=c.execute('SELECT enabled,updated_at FROM real_traveler_consent WHERE owner=?',(owner,)).fetchone()
    return {'enabled':bool(row and row['enabled']),'updated_at':row['updated_at'] if row else None,
        'scope':'匿名共享主动旅行偏好、已保存方案、本站模块浏览和操作记录，用于客群分析；不共享原始聊天、输入过程或站外记录。'}


def record_preferences(c,owner,prefs,revision):
    row=c.execute('SELECT enabled FROM real_traveler_consent WHERE owner=?',(owner,)).fetchone()
    if not row or not row['enabled']:return
    safe={k:copy.deepcopy(prefs.get(k)) for k in PUBLIC_FIELDS}
    c.execute('INSERT INTO real_profile_snapshots(owner,at,revision,preferences) VALUES(?,?,?,?)',
        (owner,now().isoformat(),revision,json.dumps(safe,ensure_ascii=False)))
    record_event(c,owner,'preferences_confirmed',safe.get('destination'),{'revision':revision})


def record_event(c,owner,kind,destination=None,payload=None):
    row=c.execute('SELECT enabled FROM real_traveler_consent WHERE owner=?',(owner,)).fetchone()
    if not row or not row['enabled'] or kind not in ('preferences_confirmed','plan_saved','plan_deleted','flight_search','flight_selected','flight_rejected','destination_view','flight_search_result','section_view','workspace_action'):
        return
    destination=destination if destination and destination!='为我推荐' else None
    current=now()
    if kind in ('flight_search','destination_view','section_view','workspace_action'):
        recent=c.execute("SELECT at FROM real_traveler_events WHERE owner=? AND kind=? AND destination IS ? AND json_extract(payload,'$.section') IS ? AND json_extract(payload,'$.action') IS ? ORDER BY id DESC LIMIT 1",
            (owner,kind,destination,(payload or {}).get('section'),(payload or {}).get('action'))).fetchone()
        if recent and (current-datetime.fromisoformat(recent['at'])).total_seconds()<60:return
    # Payloads are created by server tools, never arbitrary client JSON.
    c.execute('INSERT INTO real_traveler_events(owner,at,kind,destination,payload) VALUES(?,?,?,?,?)',
        (owner,current.isoformat(),kind,destination,json.dumps(payload or {},ensure_ascii=False)))


def record_activity(owner,body):
    """Allowlisted, consented site interactions; no arbitrary text or URL tracking."""
    import personal_app as personal
    import travel_planner as planner
    if not isinstance(body,dict):raise ValueError('操作记录须为对象')
    kind=body.get('kind');payload={}
    if kind=='section_view' and body.get('section') in ACTIVITY_SECTIONS:payload={'section':body['section'],'label':ACTIVITY_SECTIONS[body['section']]}
    elif kind=='workspace_action' and body.get('action') in ACTIVITY_ACTIONS:payload={'action':body['action'],'label':ACTIVITY_ACTIONS[body['action']]}
    elif kind=='destination_view' and body.get('destination') in planner.PLACES:pass
    else:raise ValueError('不支持的本站操作记录')
    with personal.db() as c:
        prefs=c.execute('SELECT preferences FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
        destination=body['destination'] if kind=='destination_view' else json.loads(prefs['preferences'] or '{}').get('destination')
        record_event(c,owner,kind,destination,payload)
    return {'accepted':True}


def record_flight_result(owner,query_id,query,status,option_count,profile_revision=None):
    """Only source-confirmed outcomes; never store failed calls as zero availability."""
    import personal_app as personal
    if owner=='marketing' or status not in ('success','empty'):return
    with personal.db() as c:
        # Do not duplicate a completed query. Consent is checked again at completion.
        if c.execute("SELECT 1 FROM real_traveler_events WHERE owner=? AND kind='flight_search_result' AND json_extract(payload,'$.query_id')=?",(owner,query_id)).fetchone():return
        record_event(c,owner,'flight_search_result',query['destinations'][0],{
            'query_id':query_id,'status':status,'option_count':option_count,'profile_revision':profile_revision,
            'required_airlines':query.get('required_airlines',[]),'excluded_airlines':query.get('excluded_airlines',[]),
            'departure':query['departure'],'return_date':query['return_date'],
            'adults':query.get('adults'),'max_stops':query.get('max_stops'),
            'source':'Google Flights / fli','interpretation':'该数据源在查询条件下未返回报价，不代表航司没有执飞' if status=='empty' else '已返回符合条件的报价'})


def set_consent(owner,body):
    import personal_app as personal
    if type(body.get('enabled')) is not bool:raise ValueError('请明确选择是否共享匿名旅行画像')
    with personal.db() as c:
        row=c.execute('SELECT public_id,enabled FROM real_traveler_consent WHERE owner=?',(owner,)).fetchone()
        ident=row['public_id'] if row else c.execute('SELECT user_id FROM personal_users WHERE owner=?',(owner,)).fetchone()['user_id']
        enabled=body['enabled']
        c.execute('INSERT INTO real_traveler_consent VALUES(?,?,?,?) ON CONFLICT(owner) DO UPDATE SET enabled=excluded.enabled,updated_at=excluded.updated_at',
            (owner,ident,int(enabled),now().isoformat()))
        if not enabled:
            c.execute('DELETE FROM real_traveler_events WHERE owner=?',(owner,))
            c.execute('DELETE FROM real_profile_snapshots WHERE owner=?',(owner,))
        elif not row or not row['enabled']:
            current=c.execute('SELECT preferences,revision FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
            if current['preferences']:record_preferences(c,owner,json.loads(current['preferences']),current['revision'])
        return consent_view(c,owner)


def rows(c):
    return c.execute('''SELECT r.owner,r.public_id,s.revision,s.preferences,r.updated_at,u.created_at,u.last_seen_at,
        CASE WHEN a.owner IS NULL THEN 'browser_session' ELSE 'account' END AS identity_kind
        FROM real_traveler_consent r JOIN personal_sessions s ON s.owner=r.owner
        JOIN personal_users u ON u.owner=s.owner LEFT JOIN personal_accounts a ON a.owner=s.owner
        WHERE r.enabled=1 ORDER BY u.created_at DESC''').fetchall()


def public_profile(c,row,window=30):
    prefs=json.loads(row['preferences'] or '{}');clock=now();cutoff=(clock-timedelta(days=window)).isoformat()
    events=[dict(e) for e in c.execute('SELECT at,kind,destination,payload FROM real_traveler_events WHERE owner=? AND at>=? AND at<=? ORDER BY id',
        (row['owner'],cutoff,clock.isoformat()))]
    for event in events:
        payload=json.loads(event.pop('payload'))
        if event['kind']=='flight_search_result':
            event['result']={k:payload.get(k) for k in ('status','option_count','profile_revision','required_airlines','excluded_airlines','departure','return_date','adults','max_stops','source','interpretation')}
        elif event['kind'] in ('section_view','workspace_action'):event['activity']={k:payload[k] for k in ('section','action','label') if k in payload}
    planned=c.execute('SELECT payload FROM personal_plans WHERE owner=? ORDER BY created_at DESC LIMIT 1',(row['owner'],)).fetchone()
    latest=json.loads(planned[0]) if planned else None
    destination=(latest['destination'] if latest and latest.get('profile_revision')==row['revision'] else prefs.get('destination'))
    stage=prefs.get('planning_stage','尚未表达');date=prefs.get('start_date')
    if stage=='暂不计划出游':intent='暂缓出游';next_action='尊重暂缓选择，不安排旅游触达'
    elif destination in (None,'为我推荐') or not date:intent='探索灵感';next_action='先确认目的地与日期'
    elif date<clock.date().isoformat():intent='计划待更新';next_action='核对是否仍有新的出行计划'
    elif any(e['kind']=='flight_selected' and e['destination']==destination for e in events):intent='已比较航班';next_action='核对航班可售性、行李与最终费用'
    elif stage=='制定行程':intent='明确计划';next_action='按本人航司、日期与预算匹配当前航班'
    else:intent='探索灵感';next_action='在本人允许范围内比较目的地'
    counts=Counter(e['kind'] for e in events)
    matching_results=[e['result'] for e in events if e['kind']=='flight_search_result' and e['destination']==destination
        and e['result']['departure']==date and e['result']['required_airlines']==prefs.get('required_airlines',[])
        and e['result']['profile_revision']==row['revision']
        and e['result']['excluded_airlines']==prefs.get('excluded_airlines',[])]
    search_result=matching_results[-1] if matching_results else None
    if search_result and search_result['status']=='empty' and intent not in ('暂缓出游','计划待更新'):
        next_action='保留本人航司偏好，核验其他合规报价渠道；不自动改推其他航司'
    snapshots=[{'at':s['at'],'revision':s['revision'],'preferences':json.loads(s['preferences'])} for s in
        c.execute('SELECT at,revision,preferences FROM real_profile_snapshots WHERE owner=? AND at>=? AND at<=? ORDER BY id DESC',(row['owner'],cutoff,clock.isoformat()))]
    known={k:prefs.get(k) for k in PUBLIC_FIELDS}
    return {'user_id':row['public_id'],'origin':prefs.get('origin'),'destination':destination,
        'start_date':date,'days':prefs.get('days'),'party':prefs.get('party'),'theme':prefs.get('theme'),
        'intent_stage':intent,'next_action':next_action,'preferences':known,'revision':row['revision'],
        'events_30d':dict(counts),'observations':events,'profile_history':snapshots,
        'identity_kind':row['identity_kind'],'created_at':row['created_at'],'last_seen_at':row['last_seen_at'],'flight_search_result':search_result,
        'last_active_at':events[-1]['at'] if events else row['updated_at'],
        'has_saved_plan':bool(latest and latest.get('profile_revision')==row['revision']),'source':'consented_personal_workspace','booking_probability':None}


def dashboard(raw=None):
    import personal_app as personal
    import content_generation
    raw=raw or {};window=int(raw.get('window_days',30))
    if window not in (7,30,90):raise ValueError('请选择7天、30天或90天窗口')
    clock=now();cutoff=clock-timedelta(days=window)
    with personal.db() as c:
        profiles=[public_profile(c,row,window) for row in rows(c)]
        active_ids={p['user_id'] for p in profiles}
        campaigns=[json.loads(r[0]) for r in c.execute('SELECT payload FROM real_marketing_campaigns ORDER BY rowid DESC')]
    popularity={};seven=clock-timedelta(days=7);prior=clock-timedelta(days=14)
    for p in profiles:
        for e in p['observations']:
            city=e['destination']
            if not city or not cutoff<=datetime.fromisoformat(e['at'])<=clock:continue
            item=popularity.setdefault(city,{'users':set(),'recent':set(),'previous':set(),'events':0})
            item['users'].add(p['user_id']);item['events']+=1
            if datetime.fromisoformat(e['at'])>=seven:item['recent'].add(p['user_id'])
            elif datetime.fromisoformat(e['at'])>=prior:item['previous'].add(p['user_id'])
    hotspots=[{'destination':city,'users':len(v['users']),'events':v['events'],'users_last_7d':len(v['recent']),
        'users_previous_7d':len(v['previous']),'change_users_7d':len(v['recent'])-len(v['previous'])} for city,v in popularity.items()]
    hotspots.sort(key=lambda h:(-h['users'],-h['users_last_7d'],h['destination']))
    for campaign in campaigns:campaign['user_ids']=[i for i in campaign['user_ids'] if i in active_ids]
    compact_profiles=[{k:v for k,v in p.items() if k not in ('observations','profile_history')} for p in profiles]
    airline_counts={}
    for p in profiles:
        for field,bucket in [('required_airlines','preferred_users'),('excluded_airlines','excluded_users')]:
            for code in set(p['preferences'].get(field) or []):
                item=airline_counts.setdefault(code,{'code':code,'name':AIRLINES.get(code,(code,))[0],
                    'preferred_users':0,'excluded_users':0,'unmatched_users':0})
                item[bucket]+=1
                if field=='required_airlines' and p['flight_search_result'] and p['flight_search_result']['status']=='empty':item['unmatched_users']+=1
    airline_preferences=sorted(airline_counts.values(),key=lambda v:(-v['preferred_users'],-v['excluded_users'],v['code']))
    return {'data_mode':'real','generation':content_generation.configuration(),'updated_at':clock.isoformat(),'window_days':window,'window_start':cutoff.isoformat(),
        'population':len(profiles),'profiles':compact_profiles,'hotspots':hotspots,'campaigns':campaigns,
        'airline_preferences':airline_preferences,'airline_names':{k:v[0] for k,v in AIRLINES.items()},
        'unmatched_users':sum(bool(p['flight_search_result'] and p['flight_search_result']['status']=='empty') for p in profiles),
        'active_users':sum(bool(p['observations']) for p in profiles),
        'profile_dimensions':{field:dict(Counter(str(p['preferences'].get(field) or '尚未表达') for p in profiles))
            for field in ('theme','party','pace','lodging_priority','date_flexibility','planning_stage','fallback_policy','overbudget_policy','origin','days')},
        'budget_groups':dict(Counter('未填写' if p['preferences'].get('trip_budget') is None else
            '2000元以下' if p['preferences']['trip_budget']<2000 else '2000—4000元' if p['preferences']['trip_budget']<=4000 else
            '4000—6000元' if p['preferences']['trip_budget']<=6000 else '6000元以上' for p in profiles)),
        'behavior_groups':dict(Counter(e.get('activity',{}).get('label') or {
            'preferences_confirmed':'确认偏好','plan_saved':'保存方案','plan_deleted':'删除方案','flight_search':'查询航班','flight_search_result':'航班查询结果',
            'flight_selected':'选择航班','flight_rejected':'排除航班','destination_view':'浏览目的地'}.get(e['kind'],e['kind'])
            for p in profiles for e in p['observations'])),
        'intent_groups':dict(Counter(p['intent_stage'] for p in profiles)),
        'theme_groups':dict(Counter(p['theme'] or '尚未表达' for p in profiles)),
        'observed_events':sum(sum(p['events_30d'].values()) for p in profiles),
        'scope':'已同意匿名共享的本站用户；账号按固定编号去重，旧匿名会话单独标记，不代表全网热度或实名人数',
        'algorithm':'本人明确意向优先；真实事件时间窗与去重热度；训练集提供内容先验，测试集仅核验',
        'real_conversion_rate':None}


def profile(ident):
    import personal_app as personal
    with personal.db() as c:
        row=next((r for r in rows(c) if r['public_id']==ident),None)
        if row is None:raise ValueError('旅客不存在或已停止共享')
        return public_profile(c,row)


def export_case(raw=None):
    """Fresh consent check; anonymized case observations for the chosen window."""
    import personal_app as personal
    data=dashboard(raw)
    with personal.db() as c:records=[public_profile(c,row,data['window_days']) for row in rows(c)]
    return {'exported_at':now().isoformat(),'window_days':data['window_days'],'population':len(records),
        'unit':'按固定账号编号去重；旧匿名浏览器会话单独标记，非实名人数','scope':data['scope'],'records':records}


def plan(ident):
    import personal_app as personal
    with personal.db() as c:
        row=c.execute('SELECT r.owner,s.revision FROM real_traveler_consent r JOIN personal_sessions s ON s.owner=r.owner WHERE r.public_id=? AND r.enabled=1',(ident,)).fetchone()
        if not row:raise ValueError('旅客不存在或已停止共享')
        latest=c.execute('SELECT payload FROM personal_plans WHERE owner=? AND profile_revision=? ORDER BY created_at DESC LIMIT 1',(row['owner'],row['revision'])).fetchone()
    if not latest:raise ValueError('该旅客尚未保存旅行方案')
    value=json.loads(latest[0]);value.update(audience='marketing',user_id=ident)
    value.pop('assistant_provenance',None)
    value.get('preference_constraints',{}).pop('travel_request',None)
    value.get('ai_explanation',{}).pop('prompt',None)
    return value


def create_campaign(body):
    import personal_app as personal
    ids=body.get('user_ids');name=body.get('name','')
    if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('请填写80字以内的活动名称')
    available={p['user_id']:p for p in dashboard()['profiles']}
    if not isinstance(ids,list) or not ids or len(ids)>5000 or any(i not in available for i in ids):raise ValueError('请选择当前仍同意共享的真实旅客')
    value={'id':'REAL_CAMPAIGN_'+uuid.uuid4().hex,'name':name.strip(),'user_ids':sorted(set(ids)),
        'created_at':now().isoformat(),'status':'待审核','source':'real_profiles','sent':0}
    with personal.db() as c:c.execute('INSERT INTO real_marketing_campaigns VALUES(?,?)',(value['id'],json.dumps(value,ensure_ascii=False)))
    return value


def decision_summary(body):
    import local_generation as model
    from personal_plan_generation import validate
    data=dashboard(body)
    if not data['population']:raise ValueError('尚无已同意共享的真实旅客，请先收集真实需求')
    text={'type':'string','minLength':1,'maxLength':400}
    spec={'type':'object','properties':{'summary':text,'actions':{'type':'array','items':text,'minItems':2,'maxItems':5}},'required':['summary','actions'],'additionalProperties':False}
    facts={k:data[k] for k in ['updated_at','window_days','population','hotspots','intent_groups','profile_dimensions','budget_groups','behavior_groups','airline_preferences','unmatched_users','scope']}
    prompt='整理真实旅客客群的决策草稿。仅使用以下聚合事实，不新增人数、价格、转化率或全网热门结论。按明确意向、近期趋势、主题提出服务与活动建议，不执行发送。数据不足如实说明，不用模拟样本补齐。summary概述，actions列可执行的下一步。\n'+json.dumps(facts,ensure_ascii=False)
    with model._LOCK:
        model.ensure();response=model.rpc('/v1/chat/completions',{'model':model.ALIAS,
            'messages':[{'role':'system','content':'你是旅客需求分析助手，只整理给定事实。'},{'role':'user','content':prompt}],
            'max_tokens':1000,'temperature':0.1,'response_format':{'type':'json_schema','json_schema':{'name':'real_cohort_decision','strict':True,'schema':spec}},
            'chat_template_kwargs':{'enable_thinking':False},'stream':False},timeout=120)
    choice=response.get('choices',[{}])[0]
    if response.get('model')!=model.ALIAS or choice.get('finish_reason')!='stop':raise ValueError('客群建议未完整返回，请重试')
    value=json.loads(choice['message']['content']);validate(value,spec)
    if not {p['user_id'] for p in data['profiles']}<={p['user_id'] for p in dashboard()['profiles']}:
        raise ValueError('共享客群已发生变化，请刷新后重新整理建议')
    return {**value,'updated_at':data['updated_at'],'population':data['population'],'model':model.MODEL_NAME,'status':'待营销人员审核'}
