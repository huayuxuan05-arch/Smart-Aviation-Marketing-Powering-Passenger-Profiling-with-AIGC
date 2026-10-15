"""个人入口的会话隔离、自报偏好更新与原始航班引用。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from data_layer import connect
import personal_app as app
import local_generation as gen
import marketing_ml as ml


class PersonalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        folder=Path(__file__).parent/'runtime/tmp';folder.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=folder)
        self.runtime=patch.object(app,'RUNTIME',Path(self.temp.name));self.runtime.start()
        self.token,self.owner,_=app.session()
        self.other_token,self.other,_=app.session()
        self.prefs={**app.defaults(),'origin':'北京','destination':'杭州','start_date':'2026-11-15','days':4,'party':'亲子','trip_budget':4000,'airfare_cap':1000}
    def tearDown(self):self.runtime.stop();self.temp.cleanup()
    def create(self,owner=None,**changes):return app.create_plan(self.source,owner or self.owner,{'preferences':{**self.prefs,**changes}})
    def test_unknown_tokens_create_new_owned_sessions(self):
        self.assertEqual(app.session(self.token),(self.token,self.owner,False))
        token,owner,fresh=app.session('0'*64)
        self.assertTrue(fresh);self.assertNotEqual(token,'0'*64);self.assertNotEqual(owner,self.owner)
    def test_personal_plan_does_not_read_simulated_profiles(self):
        with patch.object(ml,'load_data',side_effect=AssertionError('Personal planning must not load simulated user profiles')):
            plan=self.create()['plan']
        self.assertEqual(plan['audience'],'personal');self.assertEqual(plan['profile_source'],'self_report')
        self.assertEqual(plan['user_id'],'我的旅行');self.assertNotIn('SIMU_',str(plan))
        self.assertEqual(plan['destination'],'杭州');self.assertEqual(plan['days'],4);self.assertEqual(plan['pace'],'轻松')
    def test_quotes_keep_source_dates_and_prices(self):
        plan=self.create()['plan']
        self.assertEqual(plan['start_date'],'2026-11-15');self.assertFalse(plan['bookable'])
        for route in [plan['outbound'],plan['return_route']]:
            self.assertEqual(route['target_date'],plan['start_date'] if route is plan['outbound'] else plan['end_date'])
            for flight in route['flights']:
                row=self.source.execute('SELECT * FROM flights WHERE rowid=?',(flight['source_row'],)).fetchone()
                self.assertEqual(flight['出发日'],row['出发日']);self.assertEqual(flight['机票票价'],row['机票票价'])
    def test_states_and_plan_access_are_isolated(self):
        plan=self.create()['plan'];self.assertEqual(len(app.state(self.owner)['plans']),1)
        self.assertEqual(app.state(self.other)['revision'],0);self.assertEqual(app.state(self.other)['plans'],[])
        with self.assertRaisesRegex(ValueError,'不属于'):app.get_plan(self.other,plan['id'])
        self.assertEqual(app.get_plan(self.owner,plan['id'])['destination'],'杭州')
    def test_preference_snapshots_do_not_rewrite_old_plans(self):
        first=self.create()['plan'];second=self.create(destination='西安',days=5)['plan']
        state=app.state(self.owner);self.assertEqual(state['revision'],2);self.assertEqual(len(state['profile_history']),2)
        self.assertIn('destination',state['profile_history'][0]['changed_fields'])
        self.assertEqual(app.get_plan(self.owner,first['id'])['destination'],'杭州')
        self.assertEqual(app.get_plan(self.owner,second['id'])['destination'],'西安')
    def test_same_preferences_do_not_create_false_updates(self):
        self.create();self.create();self.assertEqual(app.state(self.owner)['revision'],1)
        self.assertEqual(len(app.state(self.owner)['plans']),2)
    def test_stale_tab_cannot_overwrite_current_preferences(self):
        self.create()
        with self.assertRaisesRegex(ValueError,'另一个页面'):
            app.create_plan(self.source,self.owner,{'preferences':{**self.prefs,'destination':'西安'},'expected_revision':0})
        state=app.state(self.owner);self.assertEqual(state['preferences']['destination'],'杭州');self.assertEqual(len(state['plans']),1)
    def test_save_only_and_overbudget_disclosure(self):
        saved=app.save_preferences(self.source,self.owner,{'preferences':self.prefs,'expected_revision':0})
        self.assertEqual(saved['revision'],1);self.assertEqual(app.state(self.owner)['plans'],[])
        plan=self.create(trip_budget=100)['plan'];self.assertIsNone(plan['budget']['difference'])
        self.assertIsNone(plan['budget']['estimated_total'])
        self.assertEqual(plan['budget']['specified_total'],100)
    def test_invalid_preferences_do_not_silently_relax(self):
        for changes in [{'origin':'未知城市'},{'destination':'未知景点'},{'destination':'北京'},{'trip_budget':'nan'},{'days':1},{'days':3.5},{'start_date':'bad'},{'theme':'随便编造'}]:
            with self.assertRaises(ValueError):app.validate(self.source,{**self.prefs,**changes})
        self.assertEqual(app.state(self.owner)['revision'],0)
    def test_ai_explanation_requires_ownership_before_inference(self):
        plan=self.create()['plan']
        with patch.object(gen,'explain_trip') as generate:
            with self.assertRaisesRegex(ValueError,'不属于'):app.explain(self.other,plan['id'])
            generate.assert_not_called()
        value={'summary':'按现有计划调整节奏','reasons':['自报主题','亲子同行'],'practical_tips':['核对航班','确认预约','保留午休'],'status':'测试用隔离输出'}
        with patch.object(gen,'explain_trip',return_value=value):result=app.explain(self.owner,plan['id'])
        self.assertEqual(result['ai_explanation'],value);self.assertEqual(app.get_plan(self.owner,plan['id'])['ai_explanation'],value)


if __name__=='__main__':unittest.main()
