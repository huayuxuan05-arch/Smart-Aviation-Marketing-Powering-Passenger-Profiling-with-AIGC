"""Real-consent campaign workflow. Execution packages never send messages."""
from collections import Counter
import hashlib
import json
import uuid
import content_generation


def fingerprint(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def choose(options,prompt):
    """The model prioritizes verified choices; factual prose is rendered by code."""
    if not content_generation.configuration()['model_enabled']:return list(options)[:3],{'model_called':False,'model':'本地规则'}
    import local_generation as model
    from personal_plan_generation import validate
    spec={'type':'object','properties':{'ids':{'type':'array','items':{'type':'string','enum':list(options)},'minItems':1,'maxItems':min(5,len(options))}},'required':['ids'],'additionalProperties':False}
    with model._LOCK:
        model.ensure();response=model.rpc('/v1/chat/completions',{'model':model.ALIAS,'messages':[{'role':'system','content':'只从提供的已核验选项编号中选择优先项，不编造数字、优惠、客群偏好或外部事实。'},{'role':'user','content':prompt+'\n'+json.dumps(options,ensure_ascii=False)}],
            'max_tokens':250,'temperature':.1,'response_format':{'type':'json_schema','json_schema':{'name':'verified_priorities','strict':True,'schema':spec}},'chat_template_kwargs':{'enable_thinking':False},'stream':False},timeout=120)
    choice=response.get('choices',[{}])[0]
    if response.get('model')!=model.ALIAS or choice.get('finish_reason')!='stop':raise ValueError('模型未完整返回，请重试')
    value=json.loads(choice['message']['content']);validate(value,spec)
    return list(dict.fromkeys(value['ids'])),{'model_called':True,'model':model.MODEL_NAME,'revision':model.REVISION}


def decision(data):
    e=data['case_evidence'];p=e['people'];q=e['interest_quality']
    facts={'population':f"当前仍同意共享的客群为{data['population']}个账号。",'intent':f"当前偏好版本已保存方案{p['saved_plan']}人；发起过查询{p['search_requested']}人，返回过有效报价{p['priced_result']}人，选择并保存航班{p['flight_selected']}人。",
        'interest':f"兴趣主动表达{q['explicit_people']}人，未填写或历史待确认{q['unfilled_or_unverified_people']}人。",'feedback':f"另行同意共享评价{e['feedback']['respondents']}人；实际评分{e['feedback']['rating_respondents']}人。"}
    actions={'confirm_interest':'邀请愿意补充的旅客自行确认兴趣；未填写者保持未知，不按默认主题归类。',
        'verify_flights':'对明确计划的旅客按其指定或排除航司、日期和预算核验当前报价；失败与空结果分别处理。',
        'review_plan':'保留旅客确认条件，整理住宿、节奏和行程安排供本人比较，不自动修改方案。',
        'optional_feedback':'邀请自愿填写方案评价，并分别统计实际评价人数和评分人数。',
        'follow_up':'在用户许可范围内观察后续本站行为；未操作不作为拒绝，不将选择保存解释为订单。'}
    selected,engine=choose(actions,'结合以下事实选择最多5项服务准备优先级：'+json.dumps(facts,ensure_ascii=False))
    return {'summary':' '.join(facts.values()),'actions':[actions[k] for k in selected],
        'facts':facts,'evidence_policy':'模型只选择优先级，人数与事实文本由程序从当前客群填入。',**engine,
        'population':data['population'],'updated_at':data['updated_at'],'status':'待营销人员审核'}


def _read(ident):
    import personal_app as personal
    with personal.db() as c:row=c.execute('SELECT payload FROM real_marketing_campaigns WHERE id=?',(ident,)).fetchone()
    if not row:raise ValueError('活动不存在')
    return json.loads(row[0])


def _profiles(value):
    import real_travelers as real
    import personal_app as personal
    ids=set(value['user_ids'])
    with personal.db() as c:return [real.public_profile(c,r) for r in real.rows(c) if r['public_id'] in ids]


def _signature(profiles):
    return fingerprint(sorted([{'user_id':p['user_id'],'revision':p['revision'],'preferences':p['preferences']} for p in profiles],key=lambda p:p['user_id']))


def get(ident):
    import personal_app as personal
    value=_read(ident);profiles=_profiles(value);value['user_ids']=[p['user_id'] for p in profiles]
    value.setdefault('revision',1);value.setdefault('materials',[]);value.setdefault('audit',[])
    value['stale']=bool(value.get('audience_fingerprint') and value['audience_fingerprint']!=_signature(profiles))
    if value['stale']:value['status']='客群已变化，需重新制作审核';value.pop('execution_package',None)
    with personal.db() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='real_forecast_snapshots'").fetchone()
        snapshots=[dict(r) for r in c.execute('SELECT id,created_at FROM real_forecast_snapshots WHERE campaign_id=? ORDER BY created_at DESC,rowid DESC LIMIT 30',(ident,))] if exists else []
    value['forecast_snapshots']=snapshots;value['forecast_id']=snapshots[0]['id'] if snapshots else None
    return value


def _save(value,expected,action):
    import personal_app as personal
    import real_travelers as real
    with personal.db() as c:
        c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM real_marketing_campaigns WHERE id=?',(value['id'],)).fetchone()
        current=json.loads(row[0])
        if current.get('revision',1)!=expected:raise ValueError('活动版本已更新，请刷新后操作')
        # Recheck consent and preference versions in the same database transaction.
        active=[real.public_profile(c,r) for r in real.rows(c) if r['public_id'] in set(value['user_ids'])]
        if value.get('audience_fingerprint')!=_signature(active):raise ValueError('客群授权或偏好已变化，请刷新并重新制作')
        value['revision']=expected+1;value.setdefault('audit',[]).append({'at':real.now().isoformat(),'action':action,'revision':value['revision'],'actor_role':'staff'})
        c.execute('UPDATE real_marketing_campaigns SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),value['id']))
    return get(value['id'])


def generate(ident,body):
    import real_travelers as real
    value=_read(ident);expected=value.get('revision',1)
    if body.get('expected_revision')!=expected:raise ValueError('活动版本已更新，请刷新后操作')
    profiles=_profiles(value)
    if not profiles:raise ValueError('活动中没有当前仍共享的旅客')
    destinations=Counter(p['destination'] for p in profiles if p['destination'] and p['destination']!='为我推荐')
    if not destinations:raise ValueError('请先由旅客确认目的地')
    materials=[]
    for city,count in sorted(destinations.items()):
        variants={'compare':{'title':f'{city}旅行方案比较','text':f'围绕你已确认的{city}出行意向，比较行程、住宿和交通安排。航司、日期与预算以你的选择为准，当前报价需另行核验。'},
            'plan':{'title':f'一起整理{city}行程','text':f'查看{city}旅行方案，按同行方式与已确认条件核对安排。任何调整先展示差异，再由你决定；本内容不代表已预订。'},
            'prepare':{'title':f'{city}行前准备','text':f'从你已保存的{city}方案出发，核对日期、航司要求与费用口径，补充需要确认的事项。价格与可售性以实际查询结果为准。'}}
        selected,engine=choose(variants,'为已主动确认该目的地的客群选择一份旅行服务文案；不要增加事实。')
        content=variants[selected[0]];materials.append({'id':'MATERIAL_'+uuid.uuid4().hex,'destination':city,'audience_count':count,**content,**engine,'created_at':real.now().isoformat(),'status':'待审核','facts':'仅引用本人已确认目的地，不含价格、折扣或可售承诺'})
    value.update(user_ids=[p['user_id'] for p in profiles],materials=materials,audience_fingerprint=_signature(profiles),status='素材待审核',review=None)
    value.pop('execution_package',None)
    return _save(value,expected,'generate_materials')


def review(ident,body):
    import real_travelers as real
    value=get(ident);expected=value['revision']
    if body.get('expected_revision')!=expected or value['stale']:raise ValueError('活动或客群已更新，请重新制作审核')
    if not value['materials']:raise ValueError('请先制作素材')
    verdict=body.get('verdict')
    if verdict not in ('approve','reject'):raise ValueError('请选择审核通过或退回')
    if verdict=='approve' and not all(body.get(k) is True for k in ('facts_checked','consent_checked','boundary_checked')):raise ValueError('请逐项核对事实、授权及使用边界')
    approved=verdict=='approve'
    for material in value['materials']:material['status']='已审核' if approved else '已退回'
    value['review']={'approved':approved,'at':real.now().isoformat(),'materials_sha256':fingerprint(value['materials']),'audience_fingerprint':value['audience_fingerprint'],
        'checks':{k:body.get(k) is True for k in ('facts_checked','consent_checked','boundary_checked')}}
    value['status']='审核通过' if approved else '已退回，待重新制作';value.pop('execution_package',None)
    return _save(value,expected,'approve' if approved else 'reject')


def package(ident,body):
    import real_travelers as real
    value=get(ident);expected=value['revision'];review=value.get('review') or {}
    if body.get('expected_revision')!=expected or value['stale'] or not review.get('approved'):raise ValueError('请先完成当前版本审核')
    if body.get('confirmed') is not True:raise ValueError('请确认仅生成本地执行包，不发送消息')
    if review.get('materials_sha256')!=fingerprint(value['materials']):raise ValueError('素材已改变，请重新审核')
    profiles=_profiles(value);materials={m['destination']:m for m in value['materials']};ready=[];blocked=[]
    for p in profiles:
        if p['intent_stage'] in ('暂缓出游','计划待更新') or not p['start_date'] or not p['has_saved_plan'] or p['destination'] not in materials:
            blocked.append({'user_id':p['user_id'],'reason':'当前计划、方案或目的地尚待本人确认'});continue
        ready.append({'user_id':p['user_id'],'destination':p['destination'],'preferences':p['preferences'],'material_id':materials[p['destination']]['id']})
    if not ready:raise ValueError('当前没有满足本人计划条件的执行包成员，请先确认需求')
    value['execution_package']={'created_at':real.now().isoformat(),'status':'未发送','channel':'尚未接入外部发送渠道','sent':0,'records':ready,'blocked':blocked,
        'materials':value['materials'],'boundary':'匿名本地执行准备包；不得当作曝光、点击、订单或营销收益证据。本人匿名画像共享不等于外部营销联系授权。'}
    value['status']='执行包已准备';value['sent']=0
    return _save(value,expected,'prepare_local_package')


def observe(ident):
    value=get(ident);profiles=_profiles(value);since=(value.get('execution_package') or {}).get('created_at',value['created_at']);people=Counter()
    for p in profiles:
        kinds={e['kind'] for e in p['observations'] if e['at']>=since}
        for kind in ('flight_search','flight_search_result','flight_selected','plan_saved','plan_feedback'):people[kind]+=kind in kinds
    for kind in ('flight_search','flight_search_result','flight_selected','plan_saved','plan_feedback'):people.setdefault(kind,0)
    return {'campaign_id':ident,'since':since,'currently_shared_members':len(profiles),'observed_people':dict(people),'sent':0,'conversion_rate':None,
        'boundary':'只观察活动准备后的本站行为；未发送外部消息，没有对照组，不能将自然变化归因于活动或推算转化收益。'}
