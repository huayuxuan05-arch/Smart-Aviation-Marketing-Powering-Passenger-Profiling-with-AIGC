"""受限需求协商：提取、澄清、工具预览、本人确认；不把聊天直接写成偏好。"""
from datetime import datetime, timedelta
import json
import re
import uuid

import content_generation
import personal_app as personal
import airline_preferences as airlines

LABELS=dict(zip(personal.FIELDS,['出发地','目的地','出发日期','旅行天数','同行方式','旅行节奏','兴趣主题','每名成人全程预算上限','每名成人单程机票上限','日期弹性','住宿侧重','备选许可','超预算处理','具体景点','出游阶段','每名成人全程预算下限','每名成人单程机票预算下限']))
LABELS.update(required_airlines='仅选择的航空公司',excluded_airlines='排除的航空公司')
LABELS['travel_request']='本次旅行需求'
LABELS['flight_budget_policy']='航班预算标签'
ENUMS={'party':personal.PARTIES,'pace':personal.PACES,'theme':personal.THEMES,
       'date_flexibility':personal.FLEXIBILITY,'lodging_priority':personal.LODGING,
       'fallback_policy':personal.FALLBACKS,'overbudget_policy':personal.OVERBUDGET,'planning_stage':personal.STAGES,'flight_budget_policy':personal.FLIGHT_BUDGET_POLICIES}
REQUIRED=['origin','destination','start_date','days','party','trip_budget']


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS personal_assistant_drafts(
        id TEXT PRIMARY KEY,owner TEXT,created_at TEXT,base_revision INTEGER,
        version INTEGER,status TEXT,payload TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS assistant_owner ON personal_assistant_drafts(owner,created_at)')


def extract_rules(text,cities):
    """只提取有明确表述的槽位；金额口径、相对日期和冲突另行追问。"""
    patch={};spans={};issues={};notes=[]
    def put(key,value,span):
        if key in patch and patch[key]!=value:
            issues[key]='检测到多个不同表述，请确认最终选择。'
        patch[key]=value;spans[key]=span
    for clause in re.split(r'[，,。；;\n]',text):
        for key,values in ENUMS.items():
            for value in values:
                pos=clause.find(value)
                if pos>=0 and not re.search(r'(?:不想|不要|不接受|不是|不选|不去|不喜欢)$',clause[:pos]):put(key,value,value)
        for city in sorted(cities,key=len,reverse=True):
            for match in re.finditer(re.escape(city),clause):
                before=clause[:match.start()];after=clause[match.end():]
                if re.search(r'(?:不去|不要去|不想去|不是|不选)$',before):continue
                if re.search(r'(?:从|出发地(?:是|改为|改成)?|出发城市(?:是|改为)?)$',before) or re.match(r'(?:出发|起飞)',after):put('origin',city,clause)
                elif re.search(r'(?:去|目的地(?:是|改为|改成)?|改去|换成|换到)$',before):put('destination',city,clause)
        if re.search(r'推荐(?:目的地|城市)|去哪(?:里)?好|为我推荐',clause):put('destination','为我推荐',clause)
        named_origin=re.search(r'(?:从([\u4e00-\u9fff]{2,8}?)(?:出发|去|起飞)|出发地(?:是|改为|改成)?([\u4e00-\u9fff]{2,8}))',clause)
        origin_text=next((s for s in named_origin.groups() if s),None) if named_origin else None
        if origin_text and not any(origin_text.startswith(city) for city in cities):
            issues['origin']='该出发地未能匹配当前航线城市，请确认支持的出发地。'
        named=re.search(r'(?:目的地(?:是|改为|改成)|改去|换到|换成|想去|去)([\u4e00-\u9fff]{2,8})',clause)
        if named and not any(named[1].startswith(city) for city in cities) and not named[1].startswith(('哪里','哪儿','旅行','旅游','玩','散步','看看')) and not re.search(r'不(?:想)?$',clause[:named.start()]):
            issues['destination']='该目的地未能匹配当前演示城市，请确认支持的目的地。'
        for match in re.finditer(r'(?<!\d)(20\d{2})[-年/](\d{1,2})[-月/](\d{1,2})日?(?!\d)',clause):
            put('start_date',f'{match[1]}-{int(match[2]):02d}-{int(match[3]):02d}',match[0])
        match=re.search(r'(?<![\d一二三四五六七八九十两])([0-9]{1,3}|[一二三四五六七八九十两]{1,3})\s*天',clause)
        if match and not re.search(r'前后\s*$|提前\s*$|推迟\s*$|延后\s*$|改期\s*$',clause[:match.start()]):
            digits={'二':2,'两':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8}
            value=int(match[1]) if match[1].isdigit() else digits.get(match[1])
            if value not in range(2,9) or re.search(r'不(?:要|想玩|玩)?$',clause[:match.start()]):issues['days']='请确认最终旅行天数；当前演示支持2至8天。'
            else:put('days',value,match[0])
        # 三类金额不互相替代：团队总额、人均全程、单程航空。
        if re.search(r'预算|机票|票价',clause):
            amounts=re.findall(r'(\d+(?:\.\d+)?)\s*(?:元|块)',clause) or re.findall(r'(?:预算|上限|不超过|最多|以内|低于)\s*(\d+(?:\.\d+)?)',clause)
            if amounts:
                flight=bool(re.search(r'机票|票价',clause));key='airfare_cap' if flight else 'trip_budget'
                per_person=bool(re.search(r'每名成人|每位成人|每人|人均',clause))
                party_total=bool(re.search(r'[二两三四五六七八九十\d]+(?:个)?人.*(?:总|一共|合计)|(?:总|一共|合计).*[二两三四五六七八九十\d]+(?:个)?人',clause))
                interval=re.search(r'(?:预算|票价|上限)(?:是|为|约|在|区间|控制在)?\s*(\d+(?:\.\d+)?)\s*(?:元|块)?\s*(?:到|至|[-~～—])\s*(\d+(?:\.\d+)?)\s*(?:元|块)?',clause)
                clear_basis=not party_total and (flight and '单程' in clause or not flight and per_person)
                if interval and clear_basis:
                    put(key,float(interval[2]),clause)
                    put('airfare_min' if flight else 'trip_budget_min',float(interval[1]),clause)
                elif len(set(amounts))>1 or party_total or (flight and '单程' not in clause) or (not flight and not per_person):
                    issues[key]='请确认每名成人的'+('单程机票上限；往返总额不能直接作单程上限。' if flight else '全程预算；多人总额不自动平摊，儿童费用需另行核实。')
                else:put(key,float(amounts[0]),clause)
            elif re.search(r'[零一二两三四五六七八九十百千万]+(?:元|块)|预算.*[一二三四五六七八九十百千万]',clause):
                issues['airfare_cap' if re.search(r'机票|票价',clause) else 'trip_budget']='请用阿拉伯数字确认每名成人的金额与口径。'
        mappings=[('pace','轻松',r'太赶|太累|少走路|轻松一点|放慢|慢一点'),
                  ('pace','充实',r'多安排|紧凑一点'),('lodging_priority','安静休息',r'住宿.*安静|酒店.*安静'),
                  ('lodging_priority','价格优先',r'酒店太贵|住宿太贵|住宿.*便宜'),
                  ('overbudget_policy','优先降低住宿与付费体验',r'酒店太贵|住宿太贵|降低住宿'),
                  ('date_flexibility','日期固定',r'日期不变|不改日期|不能改期'),
                  ('fallback_policy','只接受直飞',r'不接受中转|不要中转|只坐直飞'),
                  ('planning_stage','先收集灵感',r'先看看|还没确定|先找灵感'),
                  ('planning_stage','暂不计划出游',r'暂时不去|暂不出游')]
        for key,value,pattern in mappings:
            match=re.search(pattern,clause)
            if match and not re.search(r'(?:不想|不要|不喜欢)$',clause[:match.start()]):put(key,value,match[0])
    if re.search(r'国庆|五一|春节|中秋|端午|明天|下周|下月|明年|今年|\d{1,2}月\d{1,2}日',text) and 'start_date' not in patch:
        issues['start_date']='请确认包含年份的具体出发日期；不推定节假日或调休日。'
    carrier_patch,carrier_spans=airlines.extract(text)
    patch.update(carrier_patch);spans.update(carrier_spans)
    if not patch:notes.append('尚未识别到明确条件，请补充信息或使用左侧表单。')
    return patch,spans,issues,notes


def question(key,message,cities):
    options=ENUMS.get(key)
    if key=='origin':options=sorted(cities)
    if key=='destination':options=['为我推荐',*sorted(personal.planner.PLACES)]
    return {'field':key,'label':LABELS[key],'message':message,'options':options,
            'type':'select' if options else 'date' if key=='start_date' else 'number',
            'optional':key in ('trip_budget','airfare_cap','trip_budget_min','airfare_min')}


def build_view(source,payload):
    cities=personal.planner.network(source).outgoing
    prefs={**payload['baseline'],**payload['patch']}
    for key in airlines.FIELDS:prefs.setdefault(key,[])
    # An explicit new carrier choice replaces contradictory inherited restrictions.
    if 'required_airlines' in payload['patch'] and 'excluded_airlines' not in payload['patch']:
        prefs['excluded_airlines']=[c for c in prefs['excluded_airlines'] if c not in prefs['required_airlines']]
    if 'excluded_airlines' in payload['patch'] and 'required_airlines' not in payload['patch']:
        prefs['required_airlines']=[c for c in prefs['required_airlines'] if c not in prefs['excluded_airlines']]
    issues=dict(payload['issues'])
    # 新会话没有确认过的日期、天数、客群等不采用界面初始值。
    for key in REQUIRED:
        if key in ('start_date','days') and prefs['planning_stage']!='制定行程':
            if payload['base_revision']==0 and key not in payload['patch']:prefs[key]=None
            issues.pop(key,None);continue
        if payload['base_revision']==0 and key not in payload['patch']:
            issues.setdefault(key,'请确认'+LABELS[key]+('，也可以选择尚未确定。' if key=='trip_budget' else '。'))
        elif key in ('start_date','days') and prefs.get(key) is None and prefs['planning_stage']=='制定行程':
            issues.setdefault(key,'生成方案前请确认'+LABELS[key]+'。')
    if 'destination' in payload['patch'] and prefs['destination']!=payload['baseline']['destination'] and 'preferred_attractions' not in payload['patch']:
        prefs['preferred_attractions']=[]
    checked=None;plan=None;error=None
    if not issues and not payload['patch']:error='未识别到可调整字段，请补充明确条件或使用表单。'
    elif not issues:
        try:
            checked=personal.validate(source,prefs)
            if checked['planning_stage']=='制定行程':
                cache_key=json.dumps(checked,ensure_ascii=False,sort_keys=True)
                if payload.get('preview_key')==cache_key:plan=payload['preview_plan']
                else:
                    plan=personal.generate_content(personal.make_plan(source,checked),checked)
                    payload['preview_key']=cache_key;payload['preview_plan']=plan
        except ValueError as e:error=str(e)
    changes=[{'field':key,'label':LABELS[key],'before':payload['baseline'].get(key),'after':prefs[key],
              'evidence':payload['spans'].get(key,'目的地改变后清空原景点' if key=='preferred_attractions' else '首次仅保存意向，未确定条件保留为空')}
             for key in personal.FIELDS if key in LABELS and (prefs.get(key)!=payload['baseline'].get(key) or (payload['base_revision']==0 and key in payload['patch']))]
    baseline_plan=payload.get('baseline_plan')
    def metrics(p):
        if not p:return None
        return {'destination':p['destination'],'days':p['days'],'pace':p['pace'],
                'estimated_total':p['budget']['estimated_total'],'budget_difference':p['budget']['difference'],
                'outbound_reference':p['outbound']['reference_fare'],'return_available':bool(p['return_route']),
                'checks':p['checklist'][:4]}
    before=metrics(baseline_plan);after=metrics(plan)
    delta=round(after['estimated_total']-before['estimated_total'],2) if before and after and before['estimated_total'] is not None and after['estimated_total'] is not None else None
    view={**{k:payload[k] for k in ['id','version','base_revision','created_at','kind','engine','notes','status']},
          'changes':changes,'questions':[question(k,v,cities) for k,v in issues.items()],
          'inherited':[LABELS[k] for k in personal.FIELDS if k in LABELS and k not in payload['patch']] if payload['base_revision'] else [],
            'defaults_applied':[{'label':LABELS[k],'value':prefs[k]} for k in personal.FIELDS if k in LABELS and k not in payload['patch'] and k not in REQUIRED] if payload['base_revision']==0 else [],
          'can_confirm':not issues and error is None,'error':error,'preferences':checked,
          'comparison':{'before':before,'after':after,'estimated_delta':delta},
          'preview':plan,'basis':'非机票费用按每名成人估算；航班由本次联网查询后加入预算。'}
    return view


def load(c,owner,draft_id):
    row=c.execute('SELECT payload,status FROM personal_assistant_drafts WHERE id=? AND owner=?',(draft_id,owner)).fetchone()
    if not row:raise ValueError('需求草稿不存在或不属于当前浏览器')
    payload=json.loads(row['payload']);payload['status']=row['status']
    return payload


def active(payload,state,body):
    if payload['status']!='pending':raise ValueError('需求草稿已处理，请创建新的草稿')
    if datetime.fromisoformat(payload['created_at'])+timedelta(hours=24)<datetime.fromisoformat(personal.now()):raise ValueError('需求草稿已过期，请重新解析')
    if state['revision']!=payload['base_revision']:raise ValueError('偏好已在另一个页面更新，请重新解析')
    if type(body.get('version')) is not int or body['version']!=payload['version']:raise ValueError('草稿已更新，请重新查看后确认')


def create(source,owner,body):
    text=body.get('text');kind=body.get('kind','request')
    if not isinstance(text,str) or not 1<=len(text.strip())<=2000:raise ValueError('请填写1至2000字的旅行需求')
    if kind not in ('request','feedback'):raise ValueError('不支持的需求类型')
    state=personal.state(owner)
    if type(body.get('expected_revision')) is not int or body['expected_revision']!=state['revision']:raise ValueError('偏好已在另一个页面更新，请刷新后重试')
    baseline_plan=None
    if kind=='feedback':
        baseline_plan=personal.get_plan(owner,body.get('plan_id',''))
        if baseline_plan['profile_revision']!=state['revision']:raise ValueError('该历史方案与当前偏好版本不同，请先生成当前版本方案')
    cities=personal.planner.network(source).outgoing
    patch,spans,issues,notes=extract_rules(text,set(cities)|set(personal.planner.PLACES))
    engine={'mode':'rules','label':'本地规则解析 · 大模型未接入','model_called':False}
    if content_generation.configuration()['model_enabled']:
        import local_generation
        suggestions=local_generation.extract_preferences(text,sorted(cities),sorted(personal.planner.PLACES),ENUMS)
        for item in suggestions['items']:
            key,value,span=item['field'],item['value'],item['evidence']
            if key in patch or key in issues:continue
            # 数字、日期、城市只接受程序可独立重现的提取，不允许模型编造。
            if key not in ENUMS or key in ('flight_budget_policy','fallback_policy','date_flexibility'):
                verified,_,ambiguities,_=extract_rules(span,set(cities)|set(personal.planner.PLACES))
                if key in ambiguities or key not in verified or verified[key]!=value:continue
            patch[key]=value;spans[key]=span
        for key in suggestions.get('unverified_fields',[]):
            if key in LABELS and key not in patch and key not in issues:
                issues[key]='请确认'+LABELS[key]+'；这项需求还需要你明确一下。'
        engine={'mode':'local-model','label':suggestions['engine'],'model_called':True}
        patch['travel_request']=text;spans['travel_request']=text
        if patch:notes=[]
    payload={'id':'DRAFT_'+uuid.uuid4().hex,'version':1,'base_revision':state['revision'],'created_at':personal.now(),
             'status':'pending','kind':kind,'text':text,'baseline':state['preferences'],'baseline_plan':baseline_plan,
             'patch':patch,'spans':spans,'issues':issues,'notes':notes,'engine':engine}
    view=build_view(source,payload)
    with personal.db() as c:
        initialize(c)
        c.execute('INSERT INTO personal_assistant_drafts VALUES(?,?,?,?,?,?,?)',(payload['id'],owner,payload['created_at'],payload['base_revision'],1,'pending',json.dumps(payload,ensure_ascii=False)))
        c.commit()
    return view


def clarify(source,owner,draft_id,body):
    with personal.db() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE');payload=load(c,owner,draft_id)
        row=c.execute('SELECT revision FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
        active(payload,{'revision':row[0]},body)
        view=build_view(source,payload);answers=body.get('answers')
        if not isinstance(answers,dict) or not answers or set(answers)-{q['field'] for q in view['questions']}:raise ValueError('请仅回答草稿中的待确认问题')
        for key,value in answers.items():
            if key in ('trip_budget','airfare_cap','trip_budget_min','airfare_min') and value in ('',None):value=None
            elif key=='days':
                if str(value) not in ('2','3','4','5','6','7','8'):raise ValueError('请选择2至8天')
                value=int(value)
            elif key in ('trip_budget','airfare_cap','trip_budget_min','airfare_min'):
                if isinstance(value,bool):raise ValueError('预算须为有效数值')
                try:value=float(value)
                except (ValueError,TypeError):raise ValueError('预算须为有效数值') from None
            elif not isinstance(value,str) or not value.strip():raise ValueError('请填写'+LABELS[key])
            allowed=next(q['options'] for q in view['questions'] if q['field']==key)
            if allowed and value not in allowed:raise ValueError('请选择支持的'+LABELS[key])
            payload['patch'][key]=value;payload['spans'][key]='本人澄清选择';payload['issues'].pop(key,None)
        payload['version']+=1;view=build_view(source,payload)
        c.execute('UPDATE personal_assistant_drafts SET version=?,payload=? WHERE id=? AND owner=?',(payload['version'],json.dumps(payload,ensure_ascii=False),draft_id,owner));c.commit()
    return view


def confirm(source,owner,draft_id,body):
    if body.get('confirmed') is not True:raise ValueError('请先确认逐项调整及费用口径')
    with personal.db() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE');payload=load(c,owner,draft_id)
        row=c.execute('SELECT revision FROM personal_sessions WHERE owner=?',(owner,)).fetchone()
        active(payload,{'revision':row[0]},body)
        view=build_view(source,payload)
        if not view['can_confirm']:raise ValueError(view['error'] or '请先回答所有待确认问题')
        prefs=view['preferences'];revision=personal.record_preferences(c,owner,prefs,payload['base_revision'])
        result={'preferences':prefs,'revision':revision,'draft_id':draft_id}
        if view['preview']:
            plan=view['preview'];plan.update({'id':'PERSONAL_'+uuid.uuid4().hex,'created_at':personal.now(),'profile_revision':revision,
                'assistant_provenance':{'draft_id':draft_id,'kind':payload['kind'],'engine':payload['engine'],'confirmed':True}})
            c.execute('INSERT INTO personal_plans VALUES(?,?,?,?,?)',(plan['id'],owner,plan['created_at'],revision,json.dumps(plan,ensure_ascii=False)));result['plan']=plan
            personal.choice_evidence.event(c,owner,'save_plan',{'plan_id':plan['id'],'profile_revision':revision,'booking':False,'source':'assistant_confirmation'})
            personal.real_travelers.record_event(c,owner,'plan_saved',plan['destination'],{'revision':revision})
        payload['status']='confirmed';payload['confirmed_at']=personal.now();payload['confirmed_revision']=revision
        c.execute('UPDATE personal_assistant_drafts SET status=?,payload=? WHERE id=? AND owner=?',('confirmed',json.dumps(payload,ensure_ascii=False),draft_id,owner));c.commit()
    return result


def cancel(owner,draft_id,body):
    with personal.db() as c:
        initialize(c);c.execute('BEGIN IMMEDIATE');payload=load(c,owner,draft_id)
        if payload['status']!='pending':raise ValueError('需求草稿已处理')
        if body.get('version')!=payload['version']:raise ValueError('草稿已更新，请重新查看')
        c.execute('UPDATE personal_assistant_drafts SET status=? WHERE id=? AND owner=?',('cancelled',draft_id,owner));c.commit()
        personal.choice_evidence.event(c,owner,'discard_draft',{'draft_id':draft_id,'rejection_label':False});c.commit()
    return {'status':'cancelled'}
