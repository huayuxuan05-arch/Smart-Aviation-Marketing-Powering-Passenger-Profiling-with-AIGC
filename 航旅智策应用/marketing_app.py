"""业务闭环：全量洞察、活动名单、素材审核、本地触达与归因隔离。"""
from datetime import datetime,timedelta
from collections import Counter,defaultdict
from pathlib import Path
import json,math,sqlite3,uuid,threading
import numpy as np
from data_layer import RUNTIME,ClosingConnection,connect,VERSION
from algorithm_layer import HOLIDAYS,profile,flight_search
import marketing_ml as ml
import decision_logic as decision
import content_generation

_LOCK=threading.RLock();_SNAPS={}
SEGMENT_THEMES=['目的地信息','景区探索','酒店体验','机票比较','攻略准备']

def db():
 c=sqlite3.connect(RUNTIME/'marketing.sqlite3',timeout=30,factory=ClosingConnection);c.row_factory=sqlite3.Row
 c.executescript('CREATE TABLE IF NOT EXISTS campaigns(id TEXT PRIMARY KEY,payload TEXT);CREATE TABLE IF NOT EXISTS creatives(id TEXT PRIMARY KEY,campaign TEXT,payload TEXT);CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,campaign TEXT,user_id TEXT,day TEXT,payload TEXT);CREATE INDEX IF NOT EXISTS delivery_user ON deliveries(user_id,day);CREATE TABLE IF NOT EXISTS campaign_audit(id INTEGER PRIMARY KEY,campaign TEXT,action TEXT,at TEXT,detail TEXT);');c.commit();return c

def audit(c,cid,action,detail):c.execute('INSERT INTO campaign_audit(campaign,action,at,detail) VALUES(?,?,?,?)',(cid,action,datetime.now().isoformat(timespec='seconds'),detail))
def clean(x):
 if isinstance(x,dict):return {str(k):clean(v) for k,v in x.items()}
 if isinstance(x,(list,tuple)):return [clean(v) for v in x]
 if isinstance(x,np.ndarray):return clean(x.tolist())
 if isinstance(x,np.generic):return x.item()
 return x

def trained_snapshot(asof):
 with _LOCK:
  if asof in _SNAPS:return _SNAPS[asof]
  a,users,objects,dests=ml.load_data();s=ml.snapshot(asof);pack=ml.model_pack();n=len(users);k=len(dests)
  # Model selection uses validation labels through Sep 22. Earlier replay must not borrow that model.
  learned=asof>='2024-09-22'
  if learned:
   flat=s['X'].reshape(-1,len(ml.FEATURES));scaled=pack['scaler'].transform(flat)
   selected=pack['selected'];s['scores']=pack['models'][selected].predict_proba(flat if selected=='boost' else scaled)[:,1].reshape(n,k)
   s['fare']=pack['models']['fare'].predict_proba(scaled)[:,1].reshape(n,k);s['favorite']=pack['models']['favorite'].predict_proba(scaled)[:,1].reshape(n,k)
   s['clusters']=pack['cluster'].predict(pack['cluster_scaler'].transform(s['cluster']))
   cx=np.column_stack([s['channels']/30,s['hours']/30,s['cluster']]);cx=pack['channel_scaler'].transform(cx)
   s['channel_probs']=pack['channel'].predict_proba(cx);s['channel_ids']=pack['channel'].classes_[np.argmax(s['channel_probs'],axis=1)];s['time_ids']=pack['time'].predict(cx)
  else:
   s['scores']=s['X'][:,:,3];s['fare']=s['X'][:,:,10];s['favorite']=1-np.exp(-s['favdest']);s['clusters']=np.argmax(s['cluster'][:,:5],axis=1);s['channel_ids']=np.argmax(s['channels'],axis=1);s['time_ids']=np.argmax(s['hours'].reshape(n,6,4).sum(axis=2),axis=1)
  s['learned']=learned;s['model']='梯度提升 · 未来7天持续关注' if learned else '历史时间衰减回放 · 不调用未来训练模型'
  _SNAPS.clear();_SNAPS[asof]=s;return s

def segment_names():
 pack=ml.model_pack();centers=pack['cluster'].cluster_centers_;return {i:SEGMENT_THEMES[int(np.argmax(row[:5]))]+'客群 · '+str(i+1) for i,row in enumerate(centers)}

def settings(raw=None):
 raw=raw or {};holiday=next((h for h in HOLIDAYS if h['id']==raw.get('holiday','national')),None)
 if not holiday:raise ValueError('请选择数据中的2024假期')
 asof=raw.get('asof') or max('2023-12-31',(datetime.fromisoformat(holiday['start'])-timedelta(days=1)).strftime('%Y-%m-%d'))
 if asof<'2023-12-31' or asof>'2024-12-24':raise ValueError('画像日期须位于2023-12-31至2024-12-24，保留完整7天标签窗口')
 if asof>=holiday['end']:raise ValueError('洞察日期须早于假期结束')
 result={'holiday':holiday['id'],'holiday_name':holiday['name'],'asof':asof,'province':raw.get('province',''),'destination':raw.get('destination',''),'segment':str(raw.get('segment','')),'min_score':float(raw.get('min_score',.35)),'limit':int(raw.get('limit',300)),'budget':float(raw.get('budget',1000)),'unit_cost':float(raw.get('unit_cost',.5)),'require_flight':str(raw.get('require_flight',True)).lower() in ('true','1')}
 if not all(math.isfinite(result[k]) for k in ['min_score','budget','unit_cost']):raise ValueError('请填写有效条件')
 if not 0<=result['min_score']<=1 or not 1<=result['limit']<=5000 or not 0<=result['budget']<=1000000 or not .01<=result['unit_cost']<=100:raise ValueError('分数需0—1、人数1—5000、预算0—100万元、单次费用0.01—100元')
 return result

def build_audience(c,raw=None):
 cfg=settings(raw);h=next(h for h in HOLIDAYS if h['id']==cfg['holiday']);s=trained_snapshot(cfg['asof']);a,users,objects,dests=ml.load_data();n=len(users);names=segment_names() if s['learned'] else {i:SEGMENT_THEMES[i]+'客群 · 历史规则' for i in range(5)}
 if cfg['destination']:
  if cfg['destination'] not in dests:raise ValueError('目的地不在41个行为目的地中')
 ordered=np.argsort(-s['scores'],axis=1,kind='stable')
 unsub={r[0] for r in c.execute('SELECT DISTINCT user_id FROM events WHERE feedback_type="unsubscribe" AND event_time_cst<=?',(cfg['asof']+' 23:59:59',))}
 candidate_sets=[];date_set=set()
 for i,u in enumerate(users):
  if cfg['province'] and u['residence_province']!=cfg['province']:continue
  if cfg['segment'] and str(s['clusters'][i])!=cfg['segment']:continue
  candidates=[dests.index(cfg['destination'])] if cfg['destination'] else [int(j) for j in ordered[i] if s['count'][60][i,j]>0][:3]
  candidates=[j for j in candidates if s['scores'][i,j]>=cfg['min_score']]
  if not candidates:continue
  time_bucket=int(s['time_ids'][i]);valid_hours=[h for h in range(8,22) if h//4==time_bucket]
  hour=max(valid_hours,key=lambda h:s['hours'][i,h]) if valid_hours else max(range(8,22),key=lambda h:s['hours'][i,h])
  choices=[]
  for rank,j in enumerate(candidates,1):
   intent=decision.trip_intent(a,i,j,cfg['asof'],h)
   r={**u,'destination':dests[j],'score':round(float(s['scores'][i,j]),4),'fare_score':round(float(s['fare'][i,j]),4),'favorite_score':round(float(s['favorite'][i,j]),4),'segment':int(s['clusters'][i]),'segment_name':names[int(s['clusters'][i])],'channel':ml.CHANNELS[int(s['channel_ids'][i])],'hour':int(hour),'travel_date':intent['travel_date'],'date_basis':intent['date_basis'],'budget':intent['budget'],'budget_evidence':intent['budget_evidence'],'intent':intent,'preference_rank':rank,'unsubscribed':u['user_id'] in unsub,'theme':SEGMENT_THEMES[int(np.argmax(s['cluster'][i,:5]))],'recent_share':round(float(s['X'][i,j,0]),3),'long_share':round(float(s['X'][i,j,2]),3),'favorites':int(s['favdest'][i,j])}
   choices.append(r);date_set.add(r['travel_date'])
  candidate_sets.append(choices)
 quotes={}
 for day in date_set:
  for f in c.execute('SELECT rowid AS source_row,* FROM flights WHERE 出发日=? ORDER BY 机票票价,rowid',(day,)):
   key=(day,f['出发城市'],f['到达城市'])
   if key not in quotes:quotes[key]=dict(f)
 rows=[]
 for choices in candidate_sets:
  for r in choices:
   f=quotes.get((r['travel_date'],r['usual_departure_city'],r['destination']));r['flight']=None
   if f and f['机票票价']>0 and (r['budget'] is None or f['机票票价']<=r['budget']):r['flight']={**f,'candidate_id':'FLIGHT_ROW_'+str(f['source_row']+1)}
   r['flight_reason']='城市、日期与已确认预算满足历史条件' if r['flight'] and r['budget'] is not None else '有历史候选，日期或本次预算仍需确认' if r['flight'] else '当前日期、城市或明确预算无匹配历史候选'
  r=decision.select_candidate(choices)
  r['primary_destination']=choices[0]['destination'];r['primary_flight_matched']=bool(choices[0]['flight'])
  r['selection_reason']='保留关注首选目的地' if r['preference_rank']==1 else f"首选{choices[0]['destination']}执行条件不足，选用第{r['preference_rank']}偏好{r['destination']}，保持原始出发地及各自计划条件"
  r['alternatives']=[{'destination':x['destination'],'score':x['score'],'preference_rank':x['preference_rank'],'travel_date':x['travel_date'],'budget':x['budget'],'budget_status':x['intent']['budget_status'],'plan_status':x['intent']['plan_status'],'flight_matched':bool(x['flight']),'business_ready':decision.business_ready(x),'reason':x['flight_reason']} for x in choices]
  r['business_ready']=decision.business_ready(r);r['defer_reasons']=[x['reason'] for x in decision.business_checks(r) if not x['passed']]
  r['suggested_action']='航线比较 · 待核验执行资格' if r['business_ready'] else '暂不触达 · 先确认条件'
  rows.append(r)
 interest_qualified=len(rows);product_qualified=sum(bool(r['flight']) for r in rows)
 if cfg['require_flight']:rows=[r for r in rows if r['flight']]
 rows.sort(key=lambda r:(r['unsubscribed'],-r['score'],r['user_id']))
 pool=len(rows);cap=min(cfg['limit'],int(cfg['budget']/cfg['unit_cost']));eligible=[r for r in rows if not r['unsubscribed']];audience=eligible[:cap]
 hotspots=Counter(r['destination'] for r in rows);regions=Counter(r['residence_province'] for r in rows);segments=Counter(r['segment_name'] for r in rows);channels=Counter(r['channel'] for r in audience);matched=sum(bool(r['flight']) for r in audience)
 comparison={'scope':'当前冻结名单，同一兴趣候选和当次约束；非随机营销实验','users':len(audience),'primary_matched':sum(r['primary_flight_matched'] for r in audience),'selected_matched':matched,'recovered_matches':sum(bool(r['flight']) and not r['primary_flight_matched'] for r in audience),'alternative_selected':sum(r['preference_rank']>1 for r in audience)}
 funnel={'interest_qualified':interest_qualified,'product_qualified':product_qualified,'eligible_before_cap':len(eligible),'selected':len(audience),'requested':cfg['limit'],'budget_capacity':cap,'shortfall':max(0,cap-len(audience)),'mode':'先筛历史产品，再按兴趣选名单' if cfg['require_flight'] else '全部兴趣探索，允许缺少产品候选'}
 coverage={'matched':matched,'users':len(audience),'rate':matched/len(audience) if audience else None,'target':.9,'meets_target':bool(audience) and matched/len(audience)>=.9,'scope':'最终名单中的历史候选覆盖，不代表当前可售或已确认行程'}
 return clean({'settings':cfg,'holiday':h,'model':s['model'],'learned':s['learned'],'population':n,'potential':pool,'unsubscribe_blocked':sum(r['unsubscribed'] for r in rows),'audience':audience,'audience_count':len(audience),'eligible_before_cap':len(eligible),'matched_flights':matched,'business_ready_count':sum(r['business_ready'] for r in audience),'decision_version':decision.DECISION_VERSION,'strategy_comparison':comparison,'selection_funnel':funnel,'candidate_coverage':coverage,'estimated_cost':round(len(audience)*cfg['unit_cost'],2),'hotspots':[{'name':k,'count':v} for k,v in hotspots.most_common(12)],'regions':[{'name':k,'count':v} for k,v in regions.most_common(12)],'segments':[{'name':name,'id':i,'count':sum(r['segment']==i for r in rows)} for i,name in names.items()],'channels':[{'name':k,'count':v} for k,v in channels.most_common()],'basis':'未来7天关注代理；营销名单默认先筛选历史产品候选再截取人数；本次明确预算才作硬约束；访问习惯不代表可触达或最优转化。','source_version':VERSION})

def metadata(c):
 import current_population
 generation=content_generation.configuration()
 report=ml.model_pack()['report'];users=[dict(r) for r in c.execute('SELECT * FROM users')]
 return {'holidays':HOLIDAYS,'provinces':sorted({u['residence_province'] for u in users}),'departures':sorted({u['usual_departure_city'] for u in users}),'destinations':report['protocol']['candidate_destinations'],'segments':[{'id':i,'name':name} for i,name in segment_names().items()],'defaults':settings(),'report':report,'source_version':VERSION,'llm':generation['label'],'generation':generation,'campaigns':campaign_list(),'current_dataset':current_population.metadata(RUNTIME)}

def campaign_list(deleted=False):
 with db() as c:
  condition='IS NOT NULL' if deleted else 'IS NULL'
  return [{k:p[k] for k in ['id','name','status','created_at','revision','settings','audience_count']} for p in [json.loads(r[0]) for r in c.execute(f"SELECT payload FROM campaigns WHERE json_extract(payload,'$.deleted_at') {condition} ORDER BY rowid DESC LIMIT 30")]]

def change_campaign_visibility(cid,body,deleted):
 if body.get('confirm') is not True:raise ValueError('请确认活动操作')
 with db() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()
  if not row:raise ValueError('活动不存在')
  p=json.loads(row[0]);was_deleted=bool(p.get('deleted_at'))
  if deleted:p['deleted_at']=datetime.now().isoformat(timespec='seconds')
  else:p.pop('deleted_at',None)
  if was_deleted!=deleted:
   c.execute('UPDATE campaigns SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),cid))
   audit(c,cid,'删除活动' if deleted else '恢复活动','保留名单、素材和本地触达账本')
 return {'id':cid,'deleted':deleted}

def get_campaign(cid):
 with db() as c:
  row=c.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()
  if not row:raise ValueError('活动不存在')
  p=json.loads(row[0])
  if p.get('deleted_at'):raise ValueError('活动已删除，请先从已删除活动中恢复')
  p['creatives']=[json.loads(r[0]) for r in c.execute("SELECT payload FROM creatives WHERE campaign=? AND json_extract(payload,'$.deleted_at') IS NULL ORDER BY rowid DESC",(cid,))];p['deliveries']=[json.loads(r[0]) for r in c.execute('SELECT payload FROM deliveries WHERE campaign=?',(cid,))];p['audit']=[dict(r) for r in c.execute('SELECT * FROM campaign_audit WHERE campaign=? ORDER BY id DESC',(cid,))]
  with connect() as source:p['execution']=decision.execution_readiness(p,source,c)
  return p

def save_campaign(c,body):
 insight=build_audience(c,body);p={**insight,'id':'MKT_'+uuid.uuid4().hex[:10],'name':str(body.get('name') or insight['holiday']['name']+'旅游航线营销')[:80],'revision':1,'status':'名单就绪','created_at':datetime.now().isoformat(timespec='seconds')}
 with db() as state:
  state.execute('INSERT INTO campaigns VALUES(?,?)',(p['id'],json.dumps(p,ensure_ascii=False)));audit(state,p['id'],'创建活动',f"全量{p['population']}人洞察，冻结{p['audience_count']}人名单；来源{VERSION}")
 return get_campaign(p['id'])

def user_detail(c,cid,uid):
 campaign=get_campaign(cid);r=next((r for r in campaign['audience'] if r['user_id']==uid),None)
 if not r:raise ValueError('该旅客不在活动名单中')
 asof=campaign['settings']['asof'];p=profile(c,uid,asof,30,14);old=profile(c,uid,(datetime.fromisoformat(asof)-timedelta(days=30)).strftime('%Y-%m-%d'),30,14)
 return {'decision':r,'profile':p,'previous':old,'asof':asof,'model':campaign['model'],'trace':{'behavior_file':'02_用户行为.xlsx','model_version':'holiday-ml-v1','source_version':VERSION,'label':'未来7天持续关注，非购票概率'}}

def _get_row(p,uid):
 r=next((r for r in p['audience'] if r['user_id']==uid),None)
 if not r:raise ValueError('该旅客不在活动名单内')
 return r

def compose(creative,row):
 text=creative['text']+f"\n{row['usual_departure_city']} → {row['destination']}，参考出发日期 {row['travel_date']}（{row['date_basis']}）。"
 if row['flight']:
  f=row['flight'];text+=f"\n历史表记录：{f['航班号']}，{f['出发时间']} 起飞，历史参考价格 ¥{f['机票票价']:,.0f}。该历史报价不代表当前可售价格，库存与税费未知。"
 else:text+='\n当前条件暂无匹配历史航班，建议先确认出发地、日期及预算。'
 if row.get('intent'):text+='\n预算依据：'+row['intent']['budget_basis']+'。'
 return text+'\n本地模拟营销内容，仅供旅游航线规划参考，不提供真实预订。'

def generate_creative(c,cid,body):
 import local_generation as gen
 p=get_campaign(cid);r=_get_row(p,body['user_id']);tone=body.get('tone','轻松亲切')
 if tone not in ['轻松亲切','简洁直接','温暖陪伴']:raise ValueError('请选择支持的语气')
 old=p['creatives'];variant=1+len(old)
 output=gen.generate(r['destination'],p['holiday']['name'],r['theme'],tone,variant)
 material={**output,'id':'CRE_'+uuid.uuid4().hex[:10],'campaign':cid,'campaign_revision':p['revision'],'user_id':r['user_id'],'destination':r['destination'],'theme':r['theme'],'holiday_name':p['holiday']['name'],'channel':body.get('channel','跟随旅客策略'),'status':'待审核','revision':1,'created_at':datetime.now().isoformat(timespec='seconds'),'tone':tone}
 if material['channel'] not in ml.CHANNELS+['跟随旅客策略']:raise ValueError('渠道不支持')
 material['facts']=[{'id':x['record_id'],'source':'02_用户行为.xlsx / 每日行为分表','text':f"{x['search_at_cst']} {x['query_text']}"} for x in [dict(x) for x in c.execute('SELECT record_id,search_at_cst,query_text FROM behaviors WHERE user_id=? AND destination=? AND search_at_cst<=? ORDER BY search_at_cst DESC LIMIT 3',(r['user_id'],r['destination'],p['settings']['asof']+' 23:59:59'))]]
 template=c.execute('SELECT * FROM templates WHERE destination=? LIMIT 1',(r['destination'],)).fetchone()
 if template:material['facts'].append({'id':template['campaign_id'],'source':'03_营销反馈.xlsx / 模拟素材','text':template['template_text']})
 if r['flight']:material['facts'].append({'id':r['flight']['candidate_id'],'source':'01_航班信息.xlsx / 历史航班','text':f"{r['travel_date']} {r['usual_departure_city']}→{r['destination']} {r['flight']['航班号']} ¥{r['flight']['机票票价']}"})
 material['composed_text']=compose(material,r);material['poster_svg']=gen.poster(material,r)
 material['coverage']=sum(x['destination']==r['destination'] and x['theme']==r['theme'] for x in p['audience'])
 with db() as state:
  state.execute('INSERT INTO creatives VALUES(?,?,?)',(material['id'],cid,json.dumps(material,ensure_ascii=False)));audit(state,cid,'生成创意',f"{material['engine']}，{r['destination']} / {r['theme']} / 素材{material['id']}")
 return material

def update_creative(cid,creative_id,body):
 import local_generation as gen
 p=get_campaign(cid)
 with db() as c:
  c.execute('BEGIN IMMEDIATE');row=c.execute('SELECT payload FROM creatives WHERE id=? AND campaign=?',(creative_id,cid)).fetchone()
  if not row:raise ValueError('素材不存在')
  m=json.loads(row[0])
  if m.get('deleted_at'):raise ValueError('素材已删除')
  action=body.get('action')
  if action=='delete':
   if body.get('confirm') is not True:raise ValueError('请确认删除这条待审核素材')
   if m['status']!='待审核':raise ValueError('仅可删除待审核素材')
   m['deleted_at']=datetime.now().isoformat(timespec='seconds')
   c.execute('UPDATE creatives SET payload=? WHERE id=? AND campaign=?',(json.dumps(m,ensure_ascii=False),creative_id,cid))
   audit(c,cid,'删除待审核素材',creative_id+' / '+m['destination']+' / '+m['theme'])
   return {'id':creative_id,'deleted':True}
  r=_get_row(p,m['user_id'])
  if m['campaign_revision']!=p['revision']:raise ValueError('活动名单已变更，请生成新版本素材')
  if action=='edit':
   for key in ['title','text','palette','art']:
    if key in body:m[key]=str(body[key])
   if not 1<=len(m['title'])<=40 or not 1<=len(m['text'])<=500:raise ValueError('标题1—40字，文案1—500字')
   if m['palette'] not in ['indigo','teal','sunset'] or m['art'] not in ['mountain','coast','city']:raise ValueError('配色或插画类型不支持')
   m['revision']+=1;m['status']='待审核';m.pop('review',None)
   m['risk_flags']=gen.risk_flags(m['title']+m['text'])
  elif action=='approve':
   if m['risk_flags']:raise ValueError('存在无证据承诺，请先修改文案后重新审核')
   if set(body.get('checks',[]))!={'facts','historical','synthetic'}:raise ValueError('请确认事实、历史价格和模拟属性三项核验')
   m['status']='已审核';m['review']={'revision':m['revision'],'at':datetime.now().isoformat(timespec='seconds'),'checks':body['checks']}
  else:raise ValueError('操作不支持')
  m['composed_text']=compose(m,r);m['poster_svg']=gen.poster(m,r);c.execute('UPDATE creatives SET payload=? WHERE id=?',(json.dumps(m,ensure_ascii=False),creative_id));audit(c,cid,'素材'+action,creative_id+' v'+str(m['revision']))
 return m

def revise_audience(cid,body):
 p=get_campaign(cid);requested=body.get('user_ids')
 if not isinstance(requested,list) or not requested:raise ValueError('至少保留一名已选旅客')
 valid={r['user_id'] for r in p['audience']}
 if any(uid not in valid for uid in requested):raise ValueError('只能从当前已冻结名单中选择')
 p['audience']=[r for r in p['audience'] if r['user_id'] in set(requested)];p['audience_count']=len(p['audience']);p['matched_flights']=sum(bool(r['flight']) for r in p['audience']);p['estimated_cost']=round(p['audience_count']*p['settings']['unit_cost'],2);p['revision']+=1;p['status']='名单就绪'
 p['channels']=[{'name':k,'count':v} for k,v in Counter(r['channel'] for r in p['audience']).most_common()]
 p['business_ready_count']=sum(decision.business_ready(r) for r in p['audience'])
 if p.get('candidate_coverage'):p['candidate_coverage'].update(matched=p['matched_flights'],users=p['audience_count'],rate=p['matched_flights']/p['audience_count'],meets_target=p['matched_flights']/p['audience_count']>=p['candidate_coverage']['target'])
 if p.get('selection_funnel'):p['selection_funnel'].update(selected=p['audience_count'],shortfall=max(0,p['selection_funnel']['budget_capacity']-p['audience_count']))
 if p.get('strategy_comparison'):
  p['strategy_comparison'].update(users=p['audience_count'],primary_matched=sum(bool(r.get('primary_flight_matched')) for r in p['audience']),selected_matched=p['matched_flights'],recovered_matches=sum(bool(r['flight']) and not r.get('primary_flight_matched') for r in p['audience']),alternative_selected=sum(r.get('preference_rank',1)>1 for r in p['audience']))
 for key in ['creatives','deliveries','audit','evaluation','last_launch','execution']:p.pop(key,None)
 with db() as c:c.execute('UPDATE campaigns SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),cid));audit(c,cid,'更新名单','版本'+str(p['revision'])+'；旧素材审批失效')
 return get_campaign(cid)

def delivery_plan(p):
 approved=decision.approved_materials(p)
 ready=[];waiting=[]
 for r in p['audience']:
  m=approved.get((r['destination'],r['theme']))
  if m:ready.append((r,m))
  else:waiting.append(r['user_id'])
 return ready,waiting

def launch(c,cid,body):
 p=get_campaign(cid)
 if body.get('confirm') is not True:raise ValueError('请确认仅在本机模拟触达')
 ready,waiting=delivery_plan(p)
 if not ready:raise ValueError('还没有可覆盖名单的已审核素材')
 day=(datetime.fromisoformat(p['settings']['asof'])+timedelta(days=1)).strftime('%Y-%m-%d');sent=[];blocked=[]
 with db() as state:
  state.execute('BEGIN IMMEDIATE')
  current=json.loads(state.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()[0])
  if current.get('deleted_at'):raise ValueError('活动已删除，不能继续触达')
  if current['revision']!=p['revision']:raise ValueError('活动名单刚刚变更，请刷新并重新核对触达计划')
  # Readiness is recomputed inside the same write transaction as the frequency ledger.
  p['creatives']=[json.loads(row[0]) for row in state.execute("SELECT payload FROM creatives WHERE campaign=? AND json_extract(payload,'$.deleted_at') IS NULL ORDER BY rowid DESC",(cid,))]
  readiness=decision.execution_readiness(p,c,state);qualification={item['user_id']:item for item in readiness['items']}
  ready,waiting=delivery_plan(p)
  for r in p['audience']:
   item=qualification[r['user_id']]
   if not item['eligible']:blocked.append({'user_id':r['user_id'],'reason':'；'.join(item['blockers']),'checks':item['checks']})
  for r,m in ready:
   if not qualification[r['user_id']]['eligible']:continue
   latest=json.loads(state.execute('SELECT payload FROM creatives WHERE id=?',(m['id'],)).fetchone()[0])
   if latest['status']!='已审核' or latest['revision']!=m['revision'] or latest.get('review',{}).get('revision')!=m['revision']:raise ValueError('素材刚刚修改，请重新审核后执行')
   if r['unsubscribed'] or not 8<=r['hour']<22:blocked.append({'user_id':r['user_id'],'reason':'退订或安静时段'});continue
   if state.execute('SELECT 1 FROM deliveries WHERE user_id=? AND day=?',(r['user_id'],day)).fetchone():blocked.append({'user_id':r['user_id'],'reason':'同一旅客同一情景日已模拟触达，频次上限1次'});continue
   record={'id':'LOCAL_'+uuid.uuid4().hex[:12],'campaign':cid,'campaign_revision':p['revision'],'user_id':r['user_id'],'destination':r['destination'],'channel':r['channel'] if m['channel']=='跟随旅客策略' else m['channel'],'scheduled_at':f'{day} {r["hour"]:02}:00:00','creative':m['id'],'creative_revision':m['revision'],'title':m['title'],'text':compose(m,r),'status':'本地模拟触达完成','is_synthetic':True,'exposure':None,'click':None,'payment':None,'source_version':VERSION,'estimated_cost':p['settings']['unit_cost']}
   state.execute('INSERT INTO deliveries VALUES(?,?,?,?,?)',(record['id'],cid,r['user_id'],day,json.dumps(record,ensure_ascii=False)));sent.append(record)
  p['status']='本地触达完成' if sent else '暂不触达';p['last_launch']={'sent':len(sent),'waiting_for_material':len(waiting),'blocked':blocked,'at':datetime.now().isoformat(timespec='seconds'),'qualification_version':decision.DECISION_VERSION}
  for key in ['creatives','deliveries','audit','execution']:p.pop(key,None)
  state.execute('UPDATE campaigns SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),cid));audit(state,cid,'本地模拟触达',f'新增{len(sent)}条；待素材{len(waiting)}人；频控等阻止{len(blocked)}人。未生成曝光、点击或订单。')
 return get_campaign(cid)

def evaluate_campaign(cid):
 p=get_campaign(cid);a,users,objects,dests=ml.load_data();uidx={u['user_id']:i for i,u in enumerate(users)};t=ml.day_index(p['settings']['asof']);labels=ml.targets(t);s=trained_snapshot(p['settings']['asof']);delivered={d['user_id'] for d in p['deliveries'] if d['campaign_revision']==p['revision']};rows=[r for r in p['audience'] if r['user_id'] in delivered] or p['audience'];counts=Counter();baseline=0
 for r in rows:
  i=uidx[r['user_id']];j=dests.index(r['destination'])
  for key in labels:counts[key]+=int(labels[key][i,j])
  baseline+=int(labels['continue'][i,int(np.argmax(s['X'][i,:,1]))])
 end=(datetime.fromisoformat(p['settings']['asof'])+timedelta(days=7)).strftime('%Y-%m-%d')
 evaluation={'scope':'当前版本已模拟触达名单' if delivered else '当前名单离线回测（尚未触达）','users':len(rows),'window':[p['settings']['asof'],end],'outcomes':dict(counts),'baseline_continue':baseline,'campaign_revision':p['revision'],'label':'未来7天行为代理标签；来源02_用户行为.xlsx，截点后记录仅用于此处评估','attribution':'不能将后续关注解释为触达造成；没有新活动的真实曝光、点击、支付或退款','feedback_update':{'asof':end,'available':True,'description':'后续行为到达后可查看更新画像；不倒填原预测特征'}}
 p['evaluation']=evaluation
 for key in ['creatives','deliveries','audit','execution']:p.pop(key,None)
 with db() as c:c.execute('UPDATE campaigns SET payload=? WHERE id=?',(json.dumps(p,ensure_ascii=False),cid));audit(c,cid,'未来窗口复盘',f'{len(rows)}人，7天完整窗口至{end}，不归因新触达')
 return evaluation

def followup(c,cid,uid):
 p=get_campaign(cid);r=_get_row(p,uid);end=(datetime.fromisoformat(p['settings']['asof'])+timedelta(days=7)).strftime('%Y-%m-%d');return {'before':profile(c,uid,p['settings']['asof'],30,14),'after':profile(c,uid,end,30,14),'asof':end,'note':'离线回放后续已观察行为；新快照未用于之前的预测或名单筛选。'}
