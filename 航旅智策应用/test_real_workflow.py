"""Real workflow uses isolated consent fixtures and never sends marketing messages."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from datetime import timedelta
import json
import unittest
import personal_app as personal
import real_travelers as real
import real_marketing_workflow as workflow
import real_forecast as forecast
from data_layer import connect


class RealWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp');self.addCleanup(self.temp.cleanup)
        for p in [patch.object(personal,'RUNTIME',Path(self.temp.name)),patch.dict('os.environ',{'AEROLENS_GENERATION_MODE':'template'})]:p.start();self.addCleanup(p.stop)
        _,self.owner,_=personal.session();self.prefs={**personal.defaults(),'origin':'上海','destination':'成都','start_date':(real.now().date()+timedelta(days=14)).isoformat(),'days':4,'trip_budget':4000,'required_airlines':['3U'],'excluded_airlines':['9C'],'travel_request':'PRIVATE ORIGINAL CHAT'}
        personal.create_plan(self.source,self.owner,{'preferences':self.prefs,'expected_revision':0});real.set_consent(self.owner,{'enabled':True});self.ident=real.dashboard()['profiles'][0]['user_id']
        self.campaign=real.create_campaign({'name':'隔离真实流程验收','user_ids':[self.ident]})
    def generate(self):return workflow.generate(self.campaign['id'],{'expected_revision':1})
    def approve(self,value):return workflow.review(value['id'],{'expected_revision':value['revision'],'verdict':'approve','facts_checked':True,'consent_checked':True,'boundary_checked':True})
    def test_activity_materials_review_and_local_package_preserve_constraints_and_send_nothing(self):
        materials=self.generate();self.assertEqual(materials['status'],'素材待审核')
        self.assertEqual(materials['materials'][0]['destination'],'成都')
        with self.assertRaises(ValueError):workflow.package(materials['id'],{'expected_revision':materials['revision'],'confirmed':True})
        with self.assertRaises(ValueError):workflow.review(materials['id'],{'expected_revision':materials['revision'],'verdict':'approve'})
        approved=self.approve(materials);prepared=workflow.package(approved['id'],{'expected_revision':approved['revision'],'confirmed':True})
        self.assertEqual(prepared['sent'],0);self.assertEqual(prepared['execution_package']['status'],'未发送')
        row=prepared['execution_package']['records'][0];self.assertEqual(row['preferences']['required_airlines'],['3U']);self.assertEqual(row['preferences']['excluded_airlines'],['9C'])
        self.assertNotIn('PRIVATE ORIGINAL CHAT',json.dumps(prepared));self.assertIsNone(workflow.observe(prepared['id'])['conversion_rate'])
    def test_consent_withdrawal_hides_packets_and_invalidates_approval(self):
        approved=self.approve(self.generate());workflow.package(approved['id'],{'expected_revision':approved['revision'],'confirmed':True})
        real.set_consent(self.owner,{'enabled':False});current=workflow.get(approved['id'])
        self.assertTrue(current['stale']);self.assertEqual(current['user_ids'],[]);self.assertNotIn('execution_package',current)
        self.assertNotIn(self.ident,json.dumps(real.dashboard()['campaigns']))
    def test_changed_preferences_or_stale_revision_require_new_material_review(self):
        materials=self.generate()
        with self.assertRaises(ValueError):workflow.review(materials['id'],{'expected_revision':1,'verdict':'reject'})
        personal.save_preferences(self.source,self.owner,{'preferences':{**self.prefs,'required_airlines':['MU']},'expected_revision':1})
        self.assertTrue(workflow.get(materials['id'])['stale'])
        with self.assertRaises(ValueError):self.approve(materials)
    def test_rejection_requires_new_review_before_package(self):
        materials=self.generate();rejected=workflow.review(materials['id'],{'expected_revision':materials['revision'],'verdict':'reject'})
        self.assertFalse(rejected['review']['approved'])
        with self.assertRaises(ValueError):workflow.package(rejected['id'],{'expected_revision':rejected['revision'],'confirmed':True})
    def test_decision_cannot_confuse_event_counts_with_people_or_invent_offers(self):
        with personal.db() as c:
            for i in range(8):real.record_event(c,self.owner,'flight_request','成都',{'query_id':'QA_'+str(i),'status':'queued'})
        result=workflow.decision(real.dashboard());self.assertIn('发起过查询1人',result['summary'])
        self.assertNotIn('8人',result['summary']);self.assertNotIn('优惠',result['summary']);self.assertFalse(result['model_called'])
    def test_forecast_refuses_cold_start_and_does_not_publish_metrics_early(self):
        result=forecast.freeze(self.campaign['id']);self.assertEqual(result['predictions'],[]);self.assertEqual(result['insufficient_history_people'],1);self.assertIsNone(result['metrics'])
        self.assertEqual(workflow.get(self.campaign['id'])['forecast_id'],result['id'])
        with self.assertRaises(ValueError):forecast.evaluate('missing')
    def test_forecast_is_frozen_before_future_events_and_evaluated_after_closed_horizon(self):
        clock=real.now()
        with personal.db() as c:
            for day in range(1,8):
                at=(clock-timedelta(days=day)).isoformat();c.execute('INSERT INTO real_traveler_events(owner,at,kind,destination,payload) VALUES(?,?,?,?,?)',(self.owner,at,'destination_view','成都','{}'))
        frozen=forecast.freeze(self.campaign['id']);self.assertEqual(frozen['predictions'][0]['top3_destinations'][0],'成都');self.assertIsNone(frozen['metrics'])
        with personal.db() as c:
            for day in (1,2):c.execute('INSERT INTO real_traveler_events(owner,at,kind,destination,payload) VALUES(?,?,?,?,?)',(self.owner,(clock+timedelta(days=day)).isoformat(),'destination_view','成都','{}'))
        self.assertIsNone(forecast.evaluate(frozen['id'])['metrics'])
        with patch.object(real,'now',return_value=clock+timedelta(days=8)):
            evaluated=forecast.evaluate(frozen['id']);self.assertEqual(evaluated['metrics']['recall_at_3'],1);self.assertEqual(evaluated['predictions'],frozen['predictions'])


if __name__=='__main__':unittest.main()
