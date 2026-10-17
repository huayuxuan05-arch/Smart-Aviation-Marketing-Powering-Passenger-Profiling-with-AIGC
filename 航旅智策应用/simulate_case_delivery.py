"""Local-only synthetic delivery and response replay. No network adapters."""
from collections import Counter
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import random
import sqlite3

from run_simulated_case import ROOT, ASOF, activate
import real_marketing_workflow as workflow
import real_travelers as real

SEED=20261018
KINDS=('queued','sent','delivered','read','clicked','plan_viewed','delivery_failed')
PROTOCOL={'is_synthetic':True,'seed':SEED,'channel':'本机模拟收件箱',
 'assumed_delivery_probability':.94,'assumed_read_given_delivered_probability':.68,
 'assumed_click_given_read_probability':.28,'assumed_plan_view_given_click_probability':.45,
 'basis':'人为场景参数，仅检验队列、状态与统计展示，不是从真实人群估计。',
 'isolation':'另库存储模拟触达与反馈，不写入正式库，也不进入原模拟未来关注标签。',
 'external_messages_sent':0,'orders_generated':0,'ratings_generated':0}


def run():
 activate();rng=random.Random(SEED)
 summary=json.loads((ROOT/'summary.json').read_text(encoding='utf-8'))
 with patch.object(real,'now',return_value=ASOF):
  campaigns=[workflow.get(item['campaign']['id']) for item in summary['campaigns']]
 assert all(not c['stale'] and c['review']['approved'] and c['execution_package']['sent']==0 for c in campaigns)
 package_hash=hashlib.sha256(json.dumps([c['execution_package'] for c in campaigns],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 target=ROOT/'simulation_delivery.sqlite3'
 with sqlite3.connect(target) as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS simulation_metadata(key TEXT PRIMARY KEY,value TEXT);
  CREATE TABLE IF NOT EXISTS simulation_messages(id TEXT PRIMARY KEY,campaign TEXT,user_id TEXT,material_id TEXT,content TEXT,is_synthetic INTEGER CHECK(is_synthetic=1),UNIQUE(campaign,user_id));
  CREATE TABLE IF NOT EXISTS simulation_touch_events(id TEXT PRIMARY KEY,message_id TEXT,at TEXT,kind TEXT,is_synthetic INTEGER CHECK(is_synthetic=1),FOREIGN KEY(message_id) REFERENCES simulation_messages(id));''')
  c.execute('PRAGMA foreign_keys=ON')
  previous=c.execute("SELECT value FROM simulation_metadata WHERE key='package_sha256'").fetchone()
  if previous:
   if previous[0]!=package_hash:raise ValueError('模拟执行包版本已改变，不能沿用原回放结果')
  else:
   c.execute('INSERT INTO simulation_metadata VALUES(?,?)',('package_sha256',package_hash))
   c.execute('INSERT INTO simulation_metadata VALUES(?,?)',('protocol',json.dumps(PROTOCOL,ensure_ascii=False)))
   for campaign in campaigns:
    package=campaign['execution_package'];materials={m['id']:m for m in package['materials']}
    for i,row in enumerate(package['records']):
     assert row['user_id'].startswith('SIM_SITE_')
     material=materials[row['material_id']]
     assert row['destination']==material['destination']
     ident='SIM_MESSAGE_'+hashlib.sha256((campaign['id']+row['user_id']).encode()).hexdigest()[:20]
     content='【本地模拟消息，不实际发送】'+material['title']+'\n'+material['text']
     c.execute('INSERT INTO simulation_messages VALUES(?,?,?,?,?,1)',(ident,campaign['id'],row['user_id'],material['id'],content))
     queue_time=ASOF+timedelta(minutes=1,seconds=i)
     events=[('queued',queue_time),('sent',queue_time+timedelta(seconds=1))]
     if rng.random()<.94:
      delivered=queue_time+timedelta(seconds=2+rng.randrange(5));events.append(('delivered',delivered))
      if rng.random()<.68:
       read=delivered+timedelta(hours=1+rng.randrange(72));events.append(('read',read))
       if rng.random()<.28:
        clicked=read+timedelta(minutes=1+rng.randrange(180));events.append(('clicked',clicked))
        if rng.random()<.45:events.append(('plan_viewed',clicked+timedelta(seconds=10+rng.randrange(120))))
     else:events.append(('delivery_failed',queue_time+timedelta(seconds=10)))
     for kind,at in events:
      c.execute('INSERT INTO simulation_touch_events VALUES(?,?,?,?,1)',(ident+'_'+kind,ident,at.isoformat(),kind))
  rows=[dict(zip(('message_id','campaign','user_id','at','kind'),r)) for r in c.execute('''SELECT e.message_id,m.campaign,m.user_id,e.at,e.kind FROM simulation_touch_events e JOIN simulation_messages m ON m.id=e.message_id ORDER BY e.at,e.id''')]
 totals=Counter(r['kind'] for r in rows)
 by_campaign=[]
 for campaign in campaigns:
  counts=Counter(r['kind'] for r in rows if r['campaign']==campaign['id'])
  counts={key:counts[key] for key in KINDS}
  assert counts['queued']==counts['sent']==len(campaign['execution_package']['records'])
  assert counts['sent']==counts['delivered']+counts['delivery_failed']
  assert counts['plan_viewed']<=counts['clicked']<=counts['read']<=counts['delivered']
  by_campaign.append({'id':campaign['id'],'name':campaign['name'],'counts':counts})
 frames=[{'at':ASOF.isoformat(),'counts':dict.fromkeys(KINDS,0)}];progress=Counter()
 for index,row in enumerate(rows):
  progress[row['kind']]+=1
  if (index+1)%max(1,len(rows)//40)==0 or index+1==len(rows):frames.append({'at':row['at'],'counts':{key:progress[key] for key in KINDS}})
 report={'protocol':PROTOCOL,'package_sha256':package_hash,'is_synthetic':True,'counts':{key:totals[key] for key in KINDS},
  'campaigns':by_campaign,'click_rate':{'value':totals['clicked']/totals['delivered'] if totals['delivered'] else None,
    'numerator':totals['clicked'],'denominator':totals['delivered'],'unit':'模拟点击人数 / 模拟送达人数'},
  'replay_frames':frames,'sample_events':rows[:16],
  'boundary':'全部为合成反馈，场景参数直接决定分布；不是外部渠道回执或真实点击，不代表营销有效、购买转化或收入。'}
 assert report['counts']['sent']==419
 summary['simulated_delivery']=report
 (ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 (ROOT/'simulated-delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 public=Path(__file__).resolve().parent.parent/'experiments/results/simulated-site-case-2026-10-17/delivery.json'
 public.write_text(json.dumps({k:v for k,v in report.items() if k not in ('sample_events','replay_frames')},ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'is_synthetic':True,'counts':report['counts'],'external_messages_sent':0},ensure_ascii=False))


if __name__=='__main__':run()
