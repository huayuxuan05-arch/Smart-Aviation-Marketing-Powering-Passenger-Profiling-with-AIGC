"""真实数据特征隔离与营销闭环测试；活动状态仅写入临时目录。"""
import copy,json,unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import datetime,timedelta
import numpy as np
import marketing_ml as ml
import marketing_app as app
import local_generation as gen
from data_layer import connect,SOURCE_HASHES

class FeatureTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):cls.data=ml.load_data();cls.pack=ml.model_pack()

 def test_full_population_and_real_trained_artifacts(self):
  a,users,objects,dests=self.data
  self.assertEqual(len(users),10000);self.assertEqual(a['dest'].shape,(397,10000));self.assertEqual(len(dests),41)
  self.assertEqual(len({u['user_id'] for u in users}),10000)
  self.assertEqual(self.pack['models']['boost'].n_features_in_,23)
  self.assertEqual(self.pack['cluster'].n_clusters,5)
  self.assertEqual(self.pack['report']['source_sha256'],SOURCE_HASHES)
  self.assertEqual(self.pack['report']['protocol']['train_pair_rows'],2460000)
  import hashlib
  manifest=json.loads((ml.ROOT/'artifact_manifest.json').read_text(encoding='utf-8'))
  with (ml.ROOT/'marketing_models.joblib').open('rb') as stream:self.assertEqual(hashlib.file_digest(stream,'sha256').hexdigest(),manifest['artifacts']['marketing_models.joblib']['sha256'])

 def test_features_ignore_all_future_rows(self):
  a,users,objects,dests=self.data;t=ml.day_index('2024-09-30');before=ml.snapshot('2024-09-30')
  changed={k:v.copy() for k,v in a.items()}
  for k in changed:changed[k][t+1:]=0
  with patch.object(ml,'_CACHE',(changed,users,objects,dests)):after=ml.snapshot('2024-09-30')
  for key in ['X','cluster','channels','hours','budget','favdest']:np.testing.assert_array_equal(before[key],after[key])

 def test_unfinished_visit_and_future_favorite_are_masked(self):
  a,users,objects,dests=self.data;t=ml.day_index('2024-09-30');end=(t+1)*86400-1
  changed=dict(a)
  for k in ['visit','repeat','dwell','action','favtime']:changed[k]=a[k].copy()
  changed['visit'][t,0]=end+100;changed['repeat'][t,0]=1;changed['dwell'][t,0]=300
  changed['action'][t,0]=1;changed['favtime'][t,0]=end+200
  with patch.object(ml,'_CACHE',(changed,users,objects,dests)):future=ml.snapshot('2024-09-30')
  changed['repeat'][t,0]=0;changed['dwell'][t,0]=0;changed['action'][t,0]=0
  with patch.object(ml,'_CACHE',(changed,users,objects,dests)):absent=ml.snapshot('2024-09-30')
  np.testing.assert_array_equal(future['X'],absent['X']);np.testing.assert_array_equal(future['cluster'],absent['cluster'])

 def test_split_label_windows_are_disjoint_and_complete(self):
  p=self.pack['report']['protocol']
  last_train=max(p['train_dates']);last_val=max(p['validation_dates'])
  self.assertLess(datetime.fromisoformat(last_train)+timedelta(days=7),datetime.fromisoformat(min(p['validation_dates'])))
  self.assertLess(datetime.fromisoformat(last_val)+timedelta(days=7),datetime.fromisoformat(min(p['test_dates'])))
  self.assertEqual(ml.targets(ml.day_index('2024-12-24'))['continue'].shape,(10000,41))
  with self.assertRaises(ValueError):ml.targets(ml.day_index('2024-12-25'))

class BusinessTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  with connect() as c:cls.insight=app.build_audience(c,{'holiday':'national','limit':30})
 def setUp(self):
  self.temp=TemporaryDirectory();self.patch=patch.object(app,'RUNTIME',Path(self.temp.name));self.patch.start();self.c=connect()
 def tearDown(self):self.c.close();self.patch.stop();self.temp.cleanup()
 def campaign(self):
  with patch.object(app,'build_audience',return_value=copy.deepcopy(self.insight)):return app.save_campaign(self.c,{'name':'隔离单元验收'})
 def creative(self,p):
  output={'title':'给假期留一点期待','text':'按自己的节奏安排旅程，先了解航线参考，再决定想去的方向。','palette':'teal','art':'mountain','engine':'隔离测试生成器','risk_flags':[]}
  with patch.object(gen,'generate',return_value=output):return app.generate_creative(self.c,p['id'],{'user_id':p['audience'][0]['user_id']})
 def approve(self,p,m):return app.update_creative(p['id'],m['id'],{'action':'approve','checks':['facts','historical','synthetic']})

 def test_unsubscribed_users_and_exact_historical_constraints(self):
  blocked={r[0] for r in self.c.execute('SELECT DISTINCT user_id FROM events WHERE feedback_type="unsubscribe" AND event_time_cst<=?',('2024-09-30 23:59:59',))}
  for r in self.insight['audience']:
   self.assertNotIn(r['user_id'],blocked);self.assertTrue(8<=r['hour']<22)
   if r['flight']:
    f=r['flight'];self.assertEqual((f['出发日'],f['出发城市'],f['到达城市']),(r['travel_date'],r['usual_departure_city'],r['destination']))
    if r['budget'] is not None:self.assertLessEqual(f['机票票价'],r['budget'])

 def test_early_holiday_replay_does_not_borrow_future_model(self):
  early=app.trained_snapshot('2024-04-03');self.assertFalse(early['learned'])
  np.testing.assert_array_equal(early['scores'],early['X'][:,:,3])
  self.assertTrue(app.trained_snapshot('2024-09-30')['learned'])

 def test_review_risks_edits_and_audience_revision(self):
  p=self.campaign();m=self.creative(p)
  with self.assertRaises(ValueError):app.launch(self.c,p['id'],{'confirm':True})
  with self.assertRaises(ValueError):app.update_creative(p['id'],m['id'],{'action':'approve','checks':['facts']})
  m=self.approve(p,m);self.assertEqual(m['status'],'已审核')
  m=app.update_creative(p['id'],m['id'],{'action':'edit','text':'保证最低价格100元，拥有完美假期'})
  self.assertEqual(m['status'],'待审核');self.assertNotIn('review',m)
  self.assertIn('未提供的数值声明',m['risk_flags'])
  with self.assertRaises(ValueError):self.approve(p,m)
  app.update_creative(p['id'],m['id'],{'action':'edit','text':'按自己的节奏安排旅程。'});self.approve(p,m)
  revised=app.revise_audience(p['id'],{'user_ids':[p['audience'][0]['user_id']]})
  self.assertEqual(revised['audience_count'],1);self.assertEqual(sum(x['count'] for x in revised['channels']),1)
  self.assertFalse(app.delivery_plan(revised)[0])

 def test_cross_campaign_frequency_and_no_fabricated_response(self):
  p=self.campaign();m=self.creative(p);self.approve(p,m)
  result=app.launch(self.c,p['id'],{'confirm':True});self.assertGreater(len(result['deliveries']),0)
  for d in result['deliveries']:
   self.assertIsNone(d['click']);self.assertIsNone(d['payment']);self.assertIsNone(d['exposure'])
   self.assertTrue(8<=int(d['scheduled_at'][11:13])<22)
  second=self.campaign();self.approve(second,self.creative(second))
  result2=app.launch(self.c,second['id'],{'confirm':True});self.assertEqual(result2['last_launch']['sent'],0)
  self.assertEqual(len(result2['last_launch']['blocked']),len(result['deliveries']))

 def test_delete_restore_preserves_records_and_global_frequency(self):
  p=self.campaign();other=self.campaign();m=self.creative(p);self.approve(p,m)
  sent=app.launch(self.c,p['id'],{'confirm':True})['deliveries']
  with self.assertRaises(ValueError):app.change_campaign_visibility(p['id'],{},True)
  app.change_campaign_visibility(p['id'],{'confirm':True},True)
  self.assertEqual([r['id'] for r in app.campaign_list()],[other['id']])
  self.assertEqual([r['id'] for r in app.campaign_list(True)],[p['id']])
  with self.assertRaises(ValueError):app.get_campaign(p['id'])
  with self.assertRaises(ValueError):app.launch(self.c,p['id'],{'confirm':True})
  self.approve(other,self.creative(other))
  self.assertEqual(app.launch(self.c,other['id'],{'confirm':True})['last_launch']['sent'],0)
  app.change_campaign_visibility(p['id'],{'confirm':True},False)
  restored=app.get_campaign(p['id']);self.assertEqual(restored['deliveries'],sent)
  self.assertEqual(restored['creatives'][0]['id'],m['id']);self.assertFalse(app.campaign_list(True))
  self.assertIn('恢复活动',[r['action'] for r in restored['audit']])

 def test_pending_creative_delete_requires_confirmation_and_keeps_other_data(self):
  p=self.campaign();m=self.creative(p);other=self.creative(p)
  with self.assertRaises(ValueError):app.update_creative(p['id'],m['id'],{'action':'delete'})
  app.update_creative(p['id'],m['id'],{'action':'delete','confirm':True})
  current=app.get_campaign(p['id'])
  self.assertEqual([x['id'] for x in current['creatives']],[other['id']])
  self.assertEqual(current['audience'],p['audience'])
  self.assertIn('删除待审核素材',[x['action'] for x in current['audit']])
  with app.db() as c:
   archived=json.loads(c.execute('SELECT payload FROM creatives WHERE id=?',(m['id'],)).fetchone()[0])
  self.assertIn('deleted_at',archived)
  with self.assertRaises(ValueError):self.approve(p,m)
  with self.assertRaises(ValueError):app.update_creative(p['id'],m['id'],{'action':'edit','text':'新的文案'})
  self.assertFalse(app.delivery_plan(current)[0])

 def test_creative_delete_rejects_approved_and_other_campaign_material(self):
  p=self.campaign();other=self.campaign();m=self.approve(p,self.creative(p))
  with self.assertRaises(ValueError):app.update_creative(p['id'],m['id'],{'action':'delete','confirm':True})
  with self.assertRaises(ValueError):app.update_creative(other['id'],m['id'],{'action':'delete','confirm':True})
  self.assertEqual(app.get_campaign(p['id'])['creatives'][0]['status'],'已审核')

 def test_stale_pending_creative_can_be_deleted(self):
  p=self.campaign();m=self.creative(p)
  app.revise_audience(p['id'],{'user_ids':[p['audience'][-1]['user_id']]})
  app.update_creative(p['id'],m['id'],{'action':'delete','confirm':True})
  self.assertFalse(app.get_campaign(p['id'])['creatives'])

 def test_future_evaluation_is_separate_and_does_not_rewrite_audience(self):
  p=self.campaign();before=app.get_campaign(p['id'])['audience'];report=app.evaluate_campaign(p['id'])
  self.assertEqual(report['window'],['2024-09-30','2024-10-07']);self.assertEqual(report['users'],30)
  self.assertEqual(app.get_campaign(p['id'])['audience'],before)
  self.assertIn('不能',report['attribution'])

 def test_poster_keeps_long_title_and_escapes_markup(self):
  import xml.etree.ElementTree as ET
  m={'title':'旅程由自己的节奏来决定先了解航线参考再考虑出发让假期更从容自在','palette':'indigo','art':'city','theme':'<景区>','holiday_name':'国庆'}
  svg=gen.poster(m,self.insight['audience'][0]);root=ET.fromstring(svg);labels=[''.join(x.itertext()) for x in root.iter() if x.tag.endswith('text')]
  self.assertIn(m['title'],''.join(labels));self.assertIn('&lt;景区&gt;',svg)

if __name__=='__main__':unittest.main()
