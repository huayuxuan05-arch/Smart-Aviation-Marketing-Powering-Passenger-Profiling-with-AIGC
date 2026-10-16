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
    def test_deletion_requires_confirmation_and_session_ownership(self):
        plan=self.create()['plan']
        for owner,body in [(self.owner,{}),(self.owner,{'confirmed':False}),(self.other,{'confirmed':True})]:
            with self.subTest(owner=owner,body=body):
                with self.assertRaises(ValueError):app.delete_plan(owner,plan['id'],body)
                self.assertEqual(app.get_plan(self.owner,plan['id']),plan)
    def test_delete_one_plan_preserves_other_plans_preferences_and_versions(self):
        first=self.create()['plan'];second=self.create(destination='西安')['plan'];other=self.create(self.other)['plan']
        before=app.state(self.owner)
        after=app.delete_plan(self.owner,second['id'],{'confirmed':True})
        self.assertEqual([p['id'] for p in after['plans']],[first['id']])
        self.assertEqual(after['latest_plan']['id'],first['id'])
        for key in ('preferences','revision','profile_history'):self.assertEqual(after[key],before[key])
        self.assertEqual(app.get_plan(self.other,other['id']),other)
        with self.assertRaises(ValueError):app.get_plan(self.owner,second['id'])
        with self.assertRaises(ValueError):app.delete_plan(self.owner,second['id'],{'confirmed':True})
        empty=app.delete_plan(self.owner,first['id'],{'confirmed':True})
        self.assertEqual(empty['plans'],[]);self.assertIsNone(empty['latest_plan'])
        self.assertEqual(empty['preferences'],before['preferences'])
    def test_inflight_ai_cannot_return_a_deleted_plan_as_saved(self):
        plan=self.create()['plan']
        def delete_during_inference(_):
            app.delete_plan(self.owner,plan['id'],{'confirmed':True})
            return {'summary':'已删除方案的延迟输出'}
        with patch.object(gen,'explain_trip',side_effect=delete_during_inference):
            with self.assertRaisesRegex(ValueError,'已删除'):app.explain(self.owner,plan['id'])
        self.assertEqual(app.state(self.owner)['plans'],[])
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
    def test_real_budget_interval_preserves_bounds_and_history(self):
        first=self.create(trip_budget_min=2000,trip_budget=4000,airfare_min=400,airfare_cap=1000)['plan']
        self.assertEqual(first['budget']['trip_budget_range'],{'min':2000,'max':4000,'source':'self_report'})
        self.assertEqual(first['budget']['one_way_airfare_range'],{'min':400,'max':1000,'source':'self_report'})
        self.create(trip_budget_min=2500,trip_budget=5000)
        self.assertEqual(app.get_plan(self.owner,first['id'])['budget']['trip_budget_range']['min'],2000)
        with self.assertRaisesRegex(ValueError,'下限'):self.create(trip_budget_min=5000,trip_budget=4000)
    def test_missing_interval_bound_is_not_filled_by_a_simulated_value(self):
        first=self.create()['plan']
        self.assertIsNone(first['budget']['trip_budget_range']['min'])
        self.assertIsNone(first['budget']['one_way_airfare_range']['min'])
    def test_ai_explanation_requires_ownership_before_inference(self):
        plan=self.create()['plan']
        with patch.object(gen,'explain_trip') as generate:
            with self.assertRaisesRegex(ValueError,'不属于'):app.explain(self.other,plan['id'])
            generate.assert_not_called()
        value={'summary':'按现有计划调整节奏','reasons':['自报主题','亲子同行'],'practical_tips':['核对航班','确认预约','保留午休'],'status':'测试用隔离输出'}
        with patch.object(gen,'explain_trip',return_value=value):result=app.explain(self.owner,plan['id'])
        self.assertEqual(result['ai_explanation'],value);self.assertEqual(app.get_plan(self.owner,plan['id'])['ai_explanation'],value)


if __name__=='__main__':unittest.main()
