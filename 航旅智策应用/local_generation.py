"""本地Qwen推理与受限视觉配方；只在本机运行，不调用云端API。"""
from pathlib import Path
import base64,subprocess,urllib.request,urllib.error,json,time,threading,re,html,math,socket,os
from aigc_config import ROOT,PORT,MODEL_FILE,MODEL_NAME,REVISION,RUNTIME_DIR,ALIAS
_PROC=None;_LOCK=threading.Lock()

def risk_flags(value):
 risks=[word for word in ['保证','必达','最低','余票','已预订','五星','免费','折扣','优惠','天气','酒店设施','门票','营业时间','完美','拥有','满足你的','都能'] if word in value]
 if any(word in value for word in ['JSON','提示词','事实边界','不谈事实','只谈规划','不涉具体承诺','只作了解邀请']):risks.append('文案包含生成规则或说明语')
 if re.search(r'[0-9¥￥]',value):risks.append('未提供的数值声明')
 return risks

def rpc(path,body=None,timeout=120):
 request=urllib.request.Request(f'http://127.0.0.1:{PORT}'+path,data=json.dumps(body,ensure_ascii=False).encode('utf-8') if body is not None else None,headers={'Content-Type':'application/json'})
 try:
  with urllib.request.urlopen(request,timeout=timeout) as r:return json.load(r)
 except urllib.error.HTTPError as e:
  raise ValueError('本地模型请求失败，请查看推理日志（HTTP '+str(e.code)+'）') from e

def health():
 try:
  rpc('/health',timeout=2);props=rpc('/props',timeout=2)
  return Path(props.get('model_path','')).resolve()==(ROOT/MODEL_FILE).resolve() and any(m.get('id')==ALIAS for m in rpc('/v1/models',timeout=2).get('data',[]))
 except Exception:return False

def ensure():
 global _PROC
 if health():return
 exe=ROOT/RUNTIME_DIR/'llama-server.exe';model=ROOT/MODEL_FILE
 if not exe.exists() or not model.exists():raise ValueError('本地文案模型未就绪，请运行 setup_local_aigc.py')
 if _PROC is None or _PROC.poll() is not None:
  try:
   with socket.create_connection(('127.0.0.1',PORT),timeout=1):raise ValueError('8767端口已有其他模型服务，请停止本应用旧模型或更换端口后重启')
  except OSError:pass
  log=(ROOT/'inference-qwen3.5.log').open('ab')
  cache=ROOT/'cache'/'cuda';temp=ROOT/'tmp'
  cache.mkdir(parents=True,exist_ok=True);temp.mkdir(parents=True,exist_ok=True)
  environment=os.environ.copy();environment.update({'CUDA_CACHE_PATH':str(cache),'TEMP':str(temp),'TMP':str(temp),'TMPDIR':str(temp),'HF_HOME':str(ROOT/'cache'/'huggingface')})
  args=[str(exe),'-m',str(model),'--alias',ALIAS,'--host','127.0.0.1','--port',str(PORT),'-c','8192','-np','1','-t','8','-tb','8','-ngl','99','--device','CUDA0','--flash-attn','on','--jinja','--reasoning','off','--no-ui']
  _PROC=subprocess.Popen(args,cwd=str(ROOT),env=environment,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0));log.close()
  (ROOT/'process.json').write_text(json.dumps({'pid':_PROC.pid,'exe':str(exe),'port':PORT,'model':MODEL_NAME,'model_file':str(model),'backend':'CUDA13.4 / CUDA0','context':8192,'parallel':1,'thinking':False}),encoding='utf-8')
 for _ in range(240):
  if health():return
  if _PROC.poll() is not None:raise ValueError('本地GPU模型启动失败，请查看 runtime/local_aigc/inference-qwen3.5.log')
  time.sleep(.5)
 raise ValueError('本地模型正在加载，请稍后再试')

def generate(destination,holiday,theme,tone='轻松亲切',variant=1):
 with _LOCK:
  ensure();schema={'type':'object','properties':{'title':{'type':'string'},'text':{'type':'string'},'palette':{'type':'string','enum':['indigo','teal','sunset']},'art':{'type':'string','enum':['mountain','coast','city']}},'required':['title','text','palette','art'],'additionalProperties':False}
  instruction=f'为航空旅游营销活动创作可直接展示给旅客的中文邀请。活动：{holiday}；旅行方向：{destination}；内容兴趣：{theme}；语气：{tone}。第{variant}版。标题十二至二十字，正文四十至六十字。围绕旅行期待、自己的出行节奏和提前规划展开，最后自然邀请查看航线参考。'
  instruction+=' 仅有以上信息，景点、酒店、天气、价格、优惠、库存和服务详情均未提供，不得补写；不得暗示已预订、真实可售或掌握旅客隐私。不使用完美、保证、最低等绝对承诺。标题与正文直接面向旅客，不复述任务要求，不解释事实边界，不谈规则或承诺限制。'
  instruction+=' 仅输出JSON，四个字符串字段：title是标题，text是正文，palette只能为indigo、teal、sunset之一，art只能为mountain、coast、city之一。'
  body={'model':ALIAS,'messages':[{'role':'system','content':'遵循给定事实边界。输出JSON且不添加解释。'},{'role':'user','content':instruction}],'max_tokens':500,'temperature':.7,'top_p':.8,'top_k':20,'min_p':0,'presence_penalty':1.5,'repeat_penalty':1.0,'seed':20261012+variant,'response_format':{'type':'json_schema','json_schema':{'name':'marketing_creative','strict':True,'schema':schema}},'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':'none','stream':False}
  started=time.time()
  result=rpc('/v1/chat/completions',body);choice=result['choices'][0]
  if result.get('model')!=ALIAS:raise ValueError('推理服务返回了其他模型，已拒绝保存')
  if choice.get('finish_reason')!='stop':raise ValueError('模型输出未完整结束，请重新生成')
  raw=choice['message'].get('content') or ''
  try:parsed=json.loads(raw)
  except (ValueError,TypeError) as e:raise ValueError('模型未返回有效JSON，请重新生成') from e
  if set(parsed)!={'title','text','palette','art'} or not all(isinstance(v,str) for v in parsed.values()):raise ValueError('模型返回字段不完整，请重新生成')
  title=parsed['title'].strip();text=parsed['text'].strip()
  if not 1<=len(title)<=40 or not 1<=len(text)<=400 or parsed['palette'] not in ['indigo','teal','sunset'] or parsed['art'] not in ['mountain','coast','city']:raise ValueError('模型输出超出素材范围，请重新生成')
  risks=risk_flags(title+text)
  return {'title':title,'text':text,'palette':parsed['palette'],'art':parsed['art'],'engine':MODEL_NAME+' / 本地GPU生成（CUDA）','generation_seconds':round(time.time()-started,2),'prompt':instruction,'risk_flags':risks,'visual_mode':'语言模型选择配色与抽象主题，本地SVG合成；非扩散文生图，非景点实拍','model_revision':REVISION,'model_alias':result['model'],'thinking':False,'context':8192,'quantizer':'Unsloth','usage':result.get('usage',{}),'timings':result.get('timings',{})}

def explain_trip(plan):
 """在既有结构化规划上生成可编辑说明，不让模型改写航班、日期或费用。"""
 with _LOCK:
  ensure()
  schema={'type':'object','properties':{'summary':{'type':'string'},'reasons':{'type':'array','items':{'type':'string'},'minItems':2,'maxItems':4},'practical_tips':{'type':'array','items':{'type':'string'},'minItems':3,'maxItems':5}},'required':['summary','reasons','practical_tips'],'additionalProperties':False}
  facts={k:plan[k] for k in ['origin','destination','days','party','theme','pace','date_basis','personalization','checklist']}
  facts['activities']=[{'day':x['day'],'activities':[b['activity'] for b in x['blocks']]} for x in plan['daily_itinerary']]
  if plan.get('preference_constraints'):
   facts['preference_constraints']=plan['preference_constraints']
   facts['lodging_conditions']=plan['lodging']
   facts['priority_rule']='本次明确选择优先；样本城市关注率只作并列参考，不得描述成该旅客个人意愿。日期、目的地、预算及备选调整均须旅客确认。'
  instruction='根据以下旅行方案，为旅客写中文个性化说明。summary解释旅行节奏和主题，reasons解释为何适合该同行方式和兴趣，practical_tips提供具体可操作的行前准备。只使用给定地点与条件，不修改或增补景点、酒店、航班、时刻、价格、优惠、天气、库存或已预订状态。不得将其他日期的历史航线说成指定日期可售。建议写成待旅客确认的草稿。不要出现保证、已预订、余票充足、最低价这几个词，即使是否定或提醒也不要使用；用建议、可选、需核实表达，不作健康、舒适或出行结果承诺。summary不超过220字，每条理由和建议不超过100字。只输出JSON。\n'+json.dumps(facts,ensure_ascii=False)
  body={'model':ALIAS,'messages':[{'role':'system','content':'你是旅行规划编辑，只解释已给定的结构化方案，不编造旅行事实。'},{'role':'user','content':instruction}],'max_tokens':1100,'temperature':.3,'top_p':.8,'seed':20261014,'response_format':{'type':'json_schema','json_schema':{'name':'trip_explanation','strict':True,'schema':schema}},'chat_template_kwargs':{'enable_thinking':False},'reasoning_effort':'none','stream':False}
  started=time.time();result=rpc('/v1/chat/completions',body);choice=result['choices'][0]
  if result.get('model')!=ALIAS:raise ValueError('推理服务返回了其他模型，已拒绝保存')
  if choice.get('finish_reason')!='stop':raise ValueError('旅行说明输出未完整结束，请重试')
  try:parsed=json.loads(choice['message'].get('content') or '')
  except (ValueError,TypeError) as e:raise ValueError('旅行说明未返回有效JSON') from e
  if not isinstance(parsed,dict) or set(parsed)!={'summary','reasons','practical_tips'}:raise ValueError('旅行说明字段不完整')
  if not isinstance(parsed['summary'],str) or not 1<=len(parsed['summary'])<=500:raise ValueError('旅行说明长度异常')
  for key,minimum,maximum in [('reasons',2,4),('practical_tips',3,5)]:
   if not isinstance(parsed[key],list) or not minimum<=len(parsed[key])<=maximum or any(not isinstance(v,str) or not 1<=len(v)<=250 for v in parsed[key]):raise ValueError('旅行说明条目异常')
  combined=parsed['summary']+''.join(parsed['reasons']+parsed['practical_tips'])
  if any(word in combined for word in ['保证','已预订','余票充足','最低价']):raise ValueError('旅行说明含无依据承诺，请重新生成')
  return {**parsed,'engine':MODEL_NAME+' / 本地GPU旅行说明','model_alias':ALIAS,'model_revision':REVISION,'generation_seconds':round(time.time()-started,2),'usage':result.get('usage',{}),'prompt':instruction,'status':'待人工核验的可编辑建议'}


def poster(creative,row):
 logo_data=base64.b64encode((Path(__file__).resolve().parent/'web/assets/huayi-chaoyang-logo.png').read_bytes()).decode('ascii')
 e=lambda x:html.escape(str(x),quote=True);palettes={'indigo':('#101c48','#8274e9','#b7abff'),'teal':('#073d43','#29b49a','#b1e8c8'),'sunset':('#4a233e','#e99d73','#f7dfb4')};bg,mid,light=palettes.get(creative.get('palette'),palettes['indigo']);art=creative.get('art','mountain');scene=''
 if art=='mountain':scene=f'<path d="M0 820L160 600L270 710L430 440L600 670L720 530L900 780V1120H0Z" fill="{mid}"/><path d="M0 900L250 710L440 900L660 660L900 900V1200H0Z" fill="{light}" opacity=".55"/>'
 elif art=='coast':scene=f'<path d="M0 720Q230 570 450 720T900 700V1200H0Z" fill="{mid}"/><path d="M0 850Q230 690 450 840T900 820V1200H0Z" fill="{light}" opacity=".65"/><path d="M500 1200Q600 850 900 850V1200Z" fill="#ebd6b0"/>'
 else:scene=f'<g fill="{mid}"><path d="M0 1000V740H95V1000M120 1000V660H230V1000M260 1000V720H360V1000M390 1000V550H460V1000M490 1000V680H620V1000M650 1000V770H760V1000M790 1000V640H900V1000"/></g><path d="M0 1080Q300 880 900 1060V1200H0Z" fill="{light}" opacity=".55"/>'
 title=creative['title'];line_count=max(1,min(3,math.ceil(len(title)/13)));width=math.ceil(len(title)/line_count);lines=[title[i:i+width] for i in range(0,len(title),width)];font_size=min(58,math.floor(760/width))
 return f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="1200" viewBox="0 0 900 1200"><rect width="900" height="1200" fill="{bg}"/><circle cx="760" cy="190" r="150" fill="{mid}" opacity=".25"/><circle cx="740" cy="570" r="80" fill="{light}" opacity=".8"/>{scene}<image x="55" y="30" width="72" height="72" href="data:image/png;base64,{logo_data}"/><g fill="white" font-family="Microsoft YaHei, sans-serif"><text x="145" y="85" font-size="26" letter-spacing="4">华翼朝阳</text><text x="65" y="170" font-size="20" fill="{light}">{e(creative["holiday_name"])} · {e(creative["theme"])}主题</text>{"".join(f"<text x=\"65\" y=\"{270+i*76}\" font-size=\"{font_size}\" font-weight=\"600\">{e(line)}</text>" for i,line in enumerate(lines))}<text x="65" y="540" font-size="26">{e(row["usual_departure_city"])} → {e(row["destination"])}</text><text x="65" y="590" font-size="20">{e(row["travel_date"])} · {e(row["date_basis"])}</text><rect x="65" y="1005" width="290" height="65" rx="32" fill="white"/><text x="103" y="1048" font-size="24" fill="{bg}">了解旅游航线参考 ↗</text><text x="65" y="1130" font-size="16">本地营销演示 · 历史航班参考 · 非真实预订</text><text x="65" y="1160" font-size="14" opacity=".7">AI主题与配色 / 矢量合成插画，非目的地实拍</text></g></svg>'
