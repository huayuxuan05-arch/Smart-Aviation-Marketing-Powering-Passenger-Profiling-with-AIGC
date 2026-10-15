"""个人旅客入口：独立浏览器会话、自报偏好快照和个人方案，不读取模拟用户画像。"""
from datetime import datetime, timedelta
from pathlib import Path
import hashlib
import json
import math
import re
import sqlite3
import uuid

from data_layer import RUNTIME, ClosingConnection, CST
import travel_planner as planner
import survey_evidence as evidence
import flight_quotes

THEMES=['城市初访','自然与景区','舒适休闲','交通与预算','文化与攻略']
PARTIES=['独行','情侣','朋友','亲子','长者同行']
PACES=['按同行方式安排','轻松','均衡','充实']
FLEXIBILITY=['日期固定','前后1天可比较','前后3天可比较','同一假期内可比较','尚未确定']
LODGING=['综合比较','价格优先','安静休息','电梯与少走路','可取消','家庭空间','公共交通便利','少换住宿点']
FALLBACKS=['先展示差异，由我确认','只接受直飞','可比较中转与机场接驳','只保留原目的地']
OVERBUDGET=['先展示差异，由我选择','优先比较允许范围内的日期','优先降低住宿与付费体验','比较其他感兴趣的城市','缩短行程','暂缓出游']
STAGES=['制定行程','先收集灵感','暂不计划出游']
FIELDS=['origin','destination','start_date','days','party','pace','theme','trip_budget','airfare_cap','date_flexibility','lodging_priority','fallback_policy','overbudget_policy','preferred_attractions','planning_stage']


def now():return datetime.now(CST).isoformat(timespec='microseconds')


def db():
    RUNTIME.mkdir(parents=True,exist_ok=True)
    c=sqlite3.connect(RUNTIME/'personal.sqlite3',timeout=30,factory=ClosingConnection)
    c.row_factory=sqlite3.Row
    c.executescript('''CREATE TABLE IF NOT EXISTS personal_sessions(owner TEXT PRIMARY KEY,created_at TEXT,revision INTEGER DEFAULT 0,preferences TEXT);
    CREATE TABLE IF NOT EXISTS personal_preferences(id INTEGER PRIMARY KEY,owner TEXT,revision INTEGER,recorded_at TEXT,changed_fields TEXT,preferences TEXT);
    CREATE TABLE IF NOT EXISTS personal_plans(id TEXT PRIMARY KEY,owner TEXT,created_at TEXT,profile_revision INTEGER,payload TEXT);
    CREATE INDEX IF NOT EXISTS personal_plan_owner ON personal_plans(owner,created_at);''')
    c.commit();return c


def session(token=None):
    with db() as c:
        if isinstance(token,str) and re.fullmatch(r'[0-9a-f]{64}',token):
            owner=hashlib.sha256(token.encode()).hexdigest()
            if c.execute('SELECT 1 FROM personal_sessions WHERE owner=?',(owner,)).fetchone():return token,owner,False
        token=uuid.uuid4().hex+uuid.uuid4().hex
        owner=hashlib.sha256(token.encode()).hexdigest()
        c.execute('INSERT INTO personal_sessions(owner,created_at) VALUES(?,?)',(owner,now()));c.commit()
        return token,owner,True


def defaults():
    return {'origin':'北京','destination':'杭州','start_date':(datetime.now(CST).date()+timedelta(days=30)).isoformat(),
            'days':3,'party':'独行','pace':'按同行方式安排','theme':'城市初访','trip_budget':None,'airfare_cap':None,
            'date_flexibility':FLEXIBILITY[0],'lodging_priority':LODGING[0],'fallback_policy':FALLBACKS[0],
            'overbudget_policy':OVERBUDGET[0],'preferred_attractions':[],'planning_stage':STAGES[0]}


def validate(source,raw):
    if not isinstance(raw,dict):raise ValueError('偏好参数须为对象')
    result={**defaults(),**{k:raw[k] for k in FIELDS if k in raw}}
    if result['planning_stage'] not in STAGES:raise ValueError('请选择支持的出游阶段')
    intent_only=result['planning_stage']!='制定行程'
    network=planner.network(source)
    if result['origin'] not in network.outgoing:raise ValueError('请选择有原始航线数据的出发城市')
    if result['destination'] not in planner.PLACES and result['destination']!='为我推荐':raise ValueError('请选择支持的目的地')
    if result['origin']==result['destination']:raise ValueError('目的地与出发地相同，请选择异地目的地或为我推荐')
    if intent_only and result['start_date'] in ('',None):result['start_date']=None
    else:
        try:date=datetime.strptime(result['start_date'],'%Y-%m-%d').date()
        except (ValueError,TypeError):raise ValueError('请选择有效的出发日期') from None
        if not '2024-01-01'<=date.isoformat()<='2035-12-31':raise ValueError('出发日期须位于2024年至2035年')
    if intent_only and result['days'] in ('',None):result['days']=None
    else:
        if str(result['days']) not in ('2','3','4','5','6','7','8'):raise ValueError('请选择2至8天行程')
        result['days']=int(result['days'])
    if result['party'] not in PARTIES or result['pace'] not in PACES or result['theme'] not in THEMES:raise ValueError('同行、节奏或兴趣选项不支持')
    for key,allowed in [('date_flexibility',FLEXIBILITY),('lodging_priority',LODGING),('fallback_policy',FALLBACKS),('overbudget_policy',OVERBUDGET)]:
        if result[key] not in allowed:raise ValueError('日期弹性、住宿或备选处理选项不支持')
    attractions=result['preferred_attractions']
    if not isinstance(attractions,list) or len(attractions)>3 or any(not isinstance(x,str) for x in attractions) or len(set(attractions))!=len(attractions):raise ValueError('具体景点最多选择3个，不得重复')
    allowed=attraction_options(result['destination'])
    if any(x not in allowed for x in attractions):raise ValueError('请重新选择属于当前目的地的景点')
    for key in ['trip_budget','airfare_cap']:
        if result[key] in (None,''):result[key]=None;continue
        try:value=float(result[key])
        except (ValueError,TypeError):raise ValueError('预算须为有效数值') from None
        if not math.isfinite(value) or not 100<=value<=100000:raise ValueError('预算须为100至100000元')
        result[key]=value
    return result


def attraction_options(destination):
    q=evidence.schema()['questions'][13]
    return list(dict.fromkeys(planner.PLACES.get(destination,[])+[label.split(' ',1)[1] for label,city in zip(q['options'],q['option_cities']) if city==destination]))


def make_plan(source,prefs):
    if prefs.get('planning_stage','制定行程')!='制定行程':raise ValueError('当前仅保存出游意向；确认日期和天数并选择制定行程后，再生成方案')
    start=prefs['start_date'];end=(datetime.strptime(start,'%Y-%m-%d').date()+timedelta(days=prefs['days']-1)).isoformat()
    routes=planner.network(source);origin=prefs['origin']
    choices={
        '城市初访':['上海','北京','成都','杭州','西安','厦门'],
        '自然与景区':['三亚','昆明','桂林','厦门','杭州','青岛'],
        '舒适休闲':['杭州','厦门','三亚','苏州','成都','海口'],
        '交通与预算':['成都','西安','武汉','长沙','南京','重庆'],
        '文化与攻略':['西安','北京','苏州','南京','杭州','成都']}[prefs['theme']] if prefs['destination']=='为我推荐' else [prefs['destination']]
    candidates=[]
    for destination in choices:
        if destination==origin or destination=='苏州' and origin in ('上海','南京'):continue
        def pending(day,gateway):
            return {'flights':[],'gateway':gateway,'destination':gateway,'target_date':day,
                    'kind':'当前航班','status':'','exact_date':False,'ground_transfer':None,
                    'reference_fare':0,'date_gap':0}
        candidates.append((destination,pending(start,destination),pending(end,origin)))
    if not candidates:raise ValueError('当前条件缺少航线网络参考，请调整目的地；不会改写历史航班日期')
    prior=evidence.destination_prior()
    def cost_order(candidate):
        d,o,b=candidate;cap=prefs['airfare_cap'];total=prefs['trip_budget']
        # 下界是情景比较，不是实时报价；先保往返与用户约束，再用样本先验打破并列。
        floor=(o['reference_fare']+(b['reference_fare'] if b else 0)+(prefs['days']-1)*120+prefs['days']*160+200)*1.1
        direct=len(o['flights'])==1 and not o['ground_transfer'] and b is not None and len(b['flights'])==1 and not b['ground_transfer']
        return (-prior.get(d,0),choices.index(d))
    if prefs['destination']=='为我推荐':candidates.sort(key=cost_order)
    destination,outbound,back=candidates[0]
    pace=prefs['pace'] if prefs['pace']!='按同行方式安排' else ('轻松' if prefs['party'] in ('亲子','长者同行') or prefs['theme']=='舒适休闲' else '均衡')
    cap=prefs['airfare_cap'];excess=max(0,outbound['reference_fare']-cap) if cap is not None else None
    intent={'budget':cap,'budget_basis':'当前旅客主动填写的单程机票上限' if cap is not None else '本次单程机票上限未填写','date_basis':'当前旅客主动选择的日期','travel_date':start,'profile_source':'self_report'}
    summary={'user_id':'我的旅行','audience':'personal','origin':origin,'destination':destination,'requested_destination':prefs['destination'],
             'start_date':start,'end_date':end,'days':prefs['days'],'party':prefs['party'],'theme':prefs['theme'],'pace':pace,
             'date_basis':'按你选择的出发日期规划','selection_reason':'按你当前选择的目的地安排' if prefs['destination']!='为我推荐' else '按你选择的兴趣主题提出目的地建议，可随时调整',
             'budget_excess':excess,'bookable':False,'profile_source':'self_report','plan_version':'personal-survey-constraints-v2'}
    priorities=[f'你选择了{prefs["theme"]}主题，计划从{origin}出发，旅行{prefs["days"]}天。',f'按{prefs["party"]}的同行方式，采用{pace}节奏。',
                '将逐项情景费用与你本次填写的全程预算对照，超预算明确提示，并按你选择的方式提出调整。' if prefs['trip_budget'] is not None else '你尚未填写全程预算，先提供逐项估算供比较。']
    alternatives=[{'destination':d,'target_date':start,'reference_fare':o['reference_fare'],'kind':o['kind'],'status':o['status']} for d,o,b in candidates[1:]]
    if prefs['destination']=='为我推荐' and prior:
        priorities.append('先比较往返参考完整性、直飞要求与所填预算，再以本批有效问卷的城市关注率打破同等条件并列；样本热度不代表你的购票概率。')
    priorities.extend([f'日期弹性：{prefs["date_flexibility"]}；备选许可：{prefs["fallback_policy"]}。原日期与目的地的调整均需你确认。',
                       f'住宿侧重：{prefs["lodging_priority"]}；超预算处理：{prefs["overbudget_policy"]}。'])
    plan=planner.compose_plan(summary,intent,outbound,back,THEMES.index(prefs['theme']),{'days':prefs['days'],'trip_budget':prefs['trip_budget'],'preferred_attractions':prefs['preferred_attractions'],'adjust_lodging':prefs['overbudget_policy']=='优先降低住宿与付费体验'},priorities,alternatives)
    plan['preference_constraints']={k:prefs[k] for k in FIELDS[9:]}
    span={'前后1天可比较':1,'前后3天可比较':3}.get(prefs['date_flexibility'],0)
    plan['date_comparisons']=[{'start_date':(datetime.strptime(start,'%Y-%m-%d').date()+timedelta(days=offset)).isoformat(),
        'advice':f'在你允许的日期范围内{abs(offset)}天；仅供改期比较，实际航班与报价需重查，确认生成后才保存。'} for offset in (-span,span) if '2024-01-01'<=(datetime.strptime(start,'%Y-%m-%d').date()+timedelta(days=offset)).isoformat()<='2035-12-31'] if span else []
    if prefs['date_flexibility']=='同一假期内可比较':plan['checklist'].insert(0,'尚未确认假期实际日期范围，请核实后选择比较日期，不自动推定调休。')
    plan['recommendation_model']={'version':'survey-constrained-ranking-v2','survey_prior_used':prefs['destination']=='为我推荐' and bool(prior),'shadow_classifier_used':False,'criteria':['往返参考完整性','主动直飞要求','机票预算与全程情景费用下界','有效问卷城市关注率仅作并列参考']}
    if prefs['preferred_attractions']:
        plan['personalization'].append('你选择的具体景点：'+'、'.join(prefs['preferred_attractions'])+'；优先作为行程候选，开放预约仍需核验。')
        scheduled=' '.join(b['activity'] for d in plan['daily_itinerary'] for b in d['blocks'])
        unscheduled=[x for x in prefs['preferred_attractions'] if x not in scheduled]
        if unscheduled:plan['checklist'].insert(0,'受行程天数限制，以下所选地点尚未排入：'+'、'.join(unscheduled)+'；可增加天数或替换活动。')
    if prefs['lodging_priority']!='综合比较':plan['lodging']['type']=prefs['lodging_priority']+'优先；'+plan['lodging']['type']
    plan['checklist'].insert(0,'按你的日期弹性与备选许可比较差异，确认后再调整方案。')
    if prefs['fallback_policy']=='只接受直飞' and (len(outbound['flights'])>1 or outbound['ground_transfer'] or not back or len(back['flights'])>1 or back['ground_transfer']):
        warning='当前历史参考不满足往返仅直飞要求，尚待补充；不可视为你已接受中转或接驳。'
        plan['checklist'].insert(0,warning);plan['personalization'].insert(0,warning)
    if prefs['trip_budget'] is not None and plan['budget']['difference'] is not None and plan['budget']['difference']>0:
        plan['backup_options'].insert(0,{'name':'按你选择的方式处理超预算','advice':f'情景估算超出全程预算{plan["budget"]["difference"]:.0f}元。你选择：{prefs["overbudget_policy"]}；先核实报价并确认调整，不自动提高预算或更换日期、城市。'})
    else:plan['backup_options'].insert(0,{'name':'预算变化时的处理顺序','advice':f'你选择：{prefs["overbudget_policy"]}。出现费用差异时先说明，再由你确认。'})
    plan['basis']='依据当前旅客主动填写的偏好生成，不套用模拟旅客画像。航班引用2024年历史样本，非机票费用为情景估算，需按实际出行日核验。'
    plan['budget']['basis']='按每名成人估算，未采集同行人数；全程预算与单程机票上限分开，历史票价和情景费用不等于实时报价。'
    return flight_quotes.latest_only(plan)


def record_preferences(c,owner,prefs,expected_revision=None):
    row=c.execute('SELECT revision,preferences FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
    if not row:raise ValueError('个人会话已失效，请刷新页面')
    if expected_revision is not None and expected_revision!=row['revision']:raise ValueError('偏好已在另一个页面更新，请刷新后重试')
    previous=json.loads(row['preferences']) if row['preferences'] else {}
    changed=[key for key in FIELDS if previous.get(key)!=prefs[key]]
    revision=row['revision']
    if changed:
        revision+=1
        c.execute('UPDATE personal_sessions SET revision=?,preferences=? WHERE owner=?',(revision,json.dumps(prefs,ensure_ascii=False),owner))
        c.execute('INSERT INTO personal_preferences(owner,revision,recorded_at,changed_fields,preferences) VALUES(?,?,?,?,?)',(owner,revision,now(),json.dumps(changed),json.dumps(prefs,ensure_ascii=False)))
    return revision


def save_preferences(source,owner,body):
    prefs=validate(source,body.get('preferences',{}))
    with db() as c:
        c.execute('BEGIN IMMEDIATE');revision=record_preferences(c,owner,prefs,body.get('expected_revision'));c.commit()
    return {'preferences':prefs,'revision':revision}


def create_plan(source,owner,body):
    prefs=validate(source,body.get('preferences',{}));plan=make_plan(source,prefs)
    with db() as c:
        c.execute('BEGIN IMMEDIATE');revision=record_preferences(c,owner,prefs,body.get('expected_revision'))
        plan.update({'id':'PERSONAL_'+uuid.uuid4().hex,'created_at':now(),'profile_revision':revision})
        c.execute('INSERT INTO personal_plans VALUES(?,?,?,?,?)',(plan['id'],owner,plan['created_at'],revision,json.dumps(plan,ensure_ascii=False)));c.commit()
    return {'plan':plan,'preferences':prefs,'revision':revision}


def get_plan(owner,plan_id):
    with db() as c:row=c.execute('SELECT payload FROM personal_plans WHERE id=? AND owner=?',(plan_id,owner)).fetchone()
    if not row:raise ValueError('方案不存在或不属于当前浏览器')
    return json.loads(row[0])


def apply_flight_quote(owner,body):
    import flight_quotes
    if body.get('confirmed') is not True:raise ValueError('请确认报价与预算后保存')
    original=get_plan(owner,body['plan_id'])
    plan=flight_quotes.preview(owner,original,body)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        current=c.execute('SELECT revision FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
        if not current or body.get('expected_revision')!=current['revision']:
            raise ValueError('偏好已在另一个页面更新，请刷新后重试')
        plan.update(id='PERSONAL_'+uuid.uuid4().hex,created_at=now(),parent_plan_id=original['id'])
        c.execute('INSERT INTO personal_plans VALUES(?,?,?,?,?)',(plan['id'],owner,plan['created_at'],plan['profile_revision'],json.dumps(plan,ensure_ascii=False)))
    return plan


def explain(owner,plan_id):
    import local_generation
    plan=get_plan(owner,plan_id);plan['ai_explanation']=local_generation.explain_trip(plan)
    with db() as c:
        c.execute('UPDATE personal_plans SET payload=? WHERE id=? AND owner=?',(json.dumps(plan,ensure_ascii=False),plan_id,owner));c.commit()
    return plan


def state(owner):
    with db() as c:
        row=c.execute('SELECT revision,preferences FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
        plans=[json.loads(r[0]) for r in c.execute('SELECT payload FROM personal_plans WHERE owner=? ORDER BY created_at DESC LIMIT 20',(owner,))]
        history=[{'revision':r['revision'],'recorded_at':r['recorded_at'],'changed_fields':json.loads(r['changed_fields'])} for r in c.execute('SELECT revision,recorded_at,changed_fields FROM personal_preferences WHERE owner=? ORDER BY revision DESC LIMIT 10',(owner,))]
    return {'preferences':{**defaults(),**(json.loads(row['preferences']) if row['preferences'] else {})},'revision':row['revision'],
            'plans':[{'id':p['id'],'origin':p['origin'],'destination':p['destination'],'days':p['days'],'start_date':p['start_date'],'created_at':p['created_at'],'profile_revision':p['profile_revision']} for p in plans],
            'latest_plan':plans[0] if plans else None,'profile_history':history}


def bootstrap(source,owner):
    import content_generation
    network=planner.network(source)
    return {**state(owner),'cities':sorted(network.outgoing),'destinations':sorted(planner.PLACES),'themes':THEMES,'parties':PARTIES,'paces':PACES,
            'date_flexibilities':FLEXIBILITY,'lodging_priorities':LODGING,'fallback_policies':FALLBACKS,'overbudget_policies':OVERBUDGET,
            'attractions':{d:attraction_options(d) for d in planner.PLACES},'planning_stages':STAGES,'generation':content_generation.configuration()}
