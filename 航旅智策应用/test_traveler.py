"""旅客数据与推荐测试；状态数据库隔离于临时目录。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import traveler_layer as t
from data_layer import connect


class TravelerTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.mock = patch.object(t,'RUNTIME',Path(self.temp.name))
        self.mock.start()
        self.uid,_ = t.session()
        self.other,_ = t.session()
        self.c = connect()

    def tearDown(self):
        self.c.close()
        self.mock.stop()
        self.temp.cleanup()

    def test_01_identity_and_preferences(self):
        self.assertEqual(t.session(self.uid),(self.uid,False))
        p=t.save_preferences(self.uid,{**t.DEFAULT_PREFS,'themes':['海边放空'],'days':'4'})
        self.assertEqual(p['preferences']['days'],4)
        self.assertEqual(t.state(self.other)['preferences']['themes'],[])
        with self.assertRaises(ValueError):
            t.save_preferences(self.uid,{'budget':float('nan')})

    def test_02_actions_affect_ranking_and_are_reversible(self):
        t.save_preferences(self.uid,{**t.DEFAULT_PREFS,'themes':['海边放空']})
        self.assertIn('海边放空',t.discover(self.c,self.uid,{})['items'][0]['themes'])
        for _ in range(2):
            t.action(self.uid,{'kind':'favorite','destination':'三亚'})
        self.assertEqual(t.state(self.uid)['favorites'],['三亚'])
        t.action(self.uid,{'kind':'hide','destination':'三亚'})
        with t.store() as db:
            db.executemany('INSERT INTO travel_actions(traveler,kind,target,at) VALUES(?,?,?,?)',[(self.uid,'view','成都',t.now())]*201)
        self.assertNotIn('三亚',[d['name'] for d in t.discover(self.c,self.uid,{})['items']])
        t.action(self.uid,{'kind':'restore','destination':'三亚'})
        self.assertIn('三亚',[d['name'] for d in t.discover(self.c,self.uid,{})['items']])
        s=t.action(self.uid,{'kind':'clear-history'})
        self.assertEqual(s['view_count'],0)
        self.assertEqual(s['favorites'],['三亚'])
        self.assertEqual(s['preferences']['themes'],['海边放空'])

    def test_03_exact_quotes_and_explicit_date_filter(self):
        for d in t.discover(self.c,self.uid,{})['items']:
            expected=self.c.execute('SELECT MIN(机票票价) FROM flights WHERE 出发日=? AND 出发城市=? AND 到达城市=?',('2024-10-23','上海',d['name'])).fetchone()[0]
            self.assertEqual(d['price'],expected)
        future=t.search_flights(self.c,self.uid,{'destination':'成都','date':'2026-10-23'})
        self.assertEqual(future['items'],[])
        self.assertIn('2024',future['reason'])
        afternoon=t.search_flights(self.c,self.uid,{'destination':'成都','time':'下午出发'})
        self.assertTrue(all(12<=int(f['出发时间'][:2])<18 for f in afternoon['items']))

    def test_04_plan_ownership_snapshot_and_validation(self):
        flight=t.search_flights(self.c,self.uid,{'destination':'成都'})['items'][0]
        args={'destination':'成都','candidate_id':flight['candidate_id'],'date':'2024-10-23','departure':'上海','days':3}
        p=t.create_plan(self.c,self.uid,args)
        self.assertEqual(p['flight']['机票票价'],flight['机票票价'])
        with self.assertRaises(ValueError):
            t.create_plan(self.c,self.uid,{**args,'date':'2024-10-24'})
        with self.assertRaises(ValueError):
            t.update_plan(self.other,p['id'],{'note':'other user'})
        saved=t.update_plan(self.uid,p['id'],{'note':'自由安排','day_notes':['抵达','散步','返程'],'checklist':[True,False,False,False]})
        self.assertEqual(saved['itinerary'][1]['note'],'散步')
        self.assertTrue(t.state(self.uid)['plans'][0]['checklist'][0]['done'])
        t.update_plan(self.uid,p['id'],{'action':'delete'})
        self.assertEqual(t.state(self.uid)['plans'],[])


if __name__=='__main__':
    unittest.main()
