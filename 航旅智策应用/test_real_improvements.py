"""Meaningful isolation, evidence and consent checks using fixture-only queries."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import json
import uuid
import unittest
import personal_app as personal
import real_travelers as real
import traveler_feedback as feedback
import case_study
import flight_quotes as flights
from data_layer import connect


class RealImprovementsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp');self.addCleanup(self.temp.cleanup)
        self.patches=[patch.object(personal,'RUNTIME',Path(self.temp.name)),patch.object(flights,'RUNTIME',Path(self.temp.name)),patch.dict('os.environ',{'AEROLENS_GENERATION_MODE':'template'})]
        for p in self.patches:p.start();self.addCleanup(p.stop)
        _,self.owner,_=personal.session();_,self.other,_=personal.session()
        self.prefs={**personal.defaults(),'origin':'上海','destination':'成都','start_date':'2026-11-15','days':4,'trip_budget':4000}
        self.plan=personal.create_plan(self.source,self.owner,{'preferences':self.prefs,'expected_revision':0})['plan']
    def share(self):real.set_consent(self.owner,{'enabled':True})
    def review(self,**changes):return {'submission_id':str(uuid.uuid4()),'rating':4,'suitability':'部分符合','reasons':['价格超预算'],'share_feedback':False,**changes}
    def test_unknown_interest_has_no_automatic_cluster_and_legacy_data_is_not_rewritten(self):
        self.assertEqual(personal.state(self.owner)['preferences']['theme'],'')
        self.assertIsNone(__import__('planning_evidence').guidance(self.prefs)['matched_training_segment'])
        with personal.db() as c:
            legacy={**self.prefs,'theme':'城市初访'};legacy.pop('theme_source',None)
            c.execute('UPDATE personal_sessions SET preferences=? WHERE owner=?',(json.dumps(legacy),self.owner))
        self.assertEqual(personal.state(self.owner)['preferences']['theme'],'')
        with personal.db() as c:self.assertEqual(json.loads(c.execute('SELECT preferences FROM personal_sessions WHERE owner=?',(self.owner,)).fetchone()[0])['theme'],'城市初访')
        self.share();self.assertEqual(real.dashboard()['profile_dimensions']['theme'],{'未填写':1})
    def test_active_theme_choice_is_shared_as_explicit(self):
        personal.save_preferences(self.source,self.owner,{'preferences':{**self.prefs,'theme':'自然与景区'},'expected_revision':1})
        self.share();self.assertEqual(real.dashboard()['profile_dimensions']['theme'],{'自然与景区':1})
    def test_feedback_is_private_by_default_and_retries_do_not_duplicate(self):
        self.share();body=self.review();feedback.submit(self.owner,self.plan['id'],body);feedback.submit(self.owner,self.plan['id'],body)
        self.assertEqual(real.dashboard()['case_evidence']['feedback']['respondents'],0)
        self.assertEqual(len(personal.state(self.owner)['plan_feedback']),1)
        with personal.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM personal_plan_feedback').fetchone()[0],1)
    def test_feedback_requires_owned_plan_and_real_optional_fields(self):
        with self.assertRaises(ValueError):feedback.submit(self.other,self.plan['id'],self.review())
        for changes in ({'rating':True},{'rating':0},{'rating':None,'suitability':None,'reasons':[]},{'reasons':[{}]}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):feedback.submit(self.owner,self.plan['id'],self.review(**changes))
        with self.assertRaises(ValueError):feedback.submit(self.owner,self.plan['id'],self.review(share_feedback=True))
    def test_feedback_sharing_is_separate_and_withdrawal_does_not_reenroll_old_ratings(self):
        self.share();feedback.submit(self.owner,self.plan['id'],self.review(share_feedback=True,raw_chat='must not be stored'))
        data=real.dashboard();self.assertEqual(data['case_evidence']['feedback']['mean_rating'],4)
        self.assertNotIn('must not be stored',json.dumps(real.export_case()))
        real.set_consent(self.owner,{'enabled':False});self.assertEqual(real.dashboard()['population'],0)
        self.share();self.assertEqual(real.dashboard()['case_evidence']['feedback']['respondents'],0)
        self.assertEqual(personal.state(self.owner)['plan_feedback'][0]['rating'],4)
    def test_failures_and_empty_results_remain_distinct_and_never_count_as_rejection(self):
        self.share();query={'destinations':['成都'],'departure':self.plan['start_date'],'return_date':self.plan['end_date'],'provider':'serpapi'}
        for status in ['timeout','failed','empty','flights_only','success']:
            real.record_flight_result(self.owner,'Q_'+status,query,status,0 if status!='success' else 2,1)
        evidence=real.dashboard()['case_evidence'];self.assertEqual(evidence['people']['query_failed'],1)
        self.assertEqual(evidence['people']['confirmed_empty'],1);self.assertEqual(evidence['people']['unpriced_inventory'],1)
        self.assertEqual(evidence['people']['flight_rejected'],0)
        observations=real.export_case()['records'][0]['observations']
        timeout=next(e for e in observations if e.get('result',{}).get('status')=='timeout')
        self.assertIsNone(timeout['result']['option_count']);self.assertEqual(timeout['result']['source'],'Google Flights / SerpApi')
    def test_native_inventory_can_later_transition_to_priced_results_without_duplicate_events(self):
        self.share();query={'destinations':['成都'],'departure':self.plan['start_date'],'return_date':self.plan['end_date']}
        for status in ['flights_only','success','success']:real.record_flight_result(self.owner,'Q_NATIVE',query,status,2 if status=='success' else 0,1)
        counts=real.dashboard()['case_evidence']['query_status_events'];self.assertEqual(counts,{'flights_only':1,'success':1})
    def test_request_reuse_is_recorded_without_reusing_private_quote_payloads(self):
        self.share();result={'id':'Q_CACHE','status':'success','cache_hit':True,'reused_inflight':False,'secret':'not retained'}
        real.record_search_request(self.owner,self.plan,result);real.record_search_request(self.owner,self.plan,result)
        data=real.export_case();self.assertEqual(data['case_evidence']['new_request_events']['cache_hit'],2)
        self.assertEqual(data['case_evidence']['people']['search_requested'],1);self.assertNotIn('not retained',json.dumps(data))
    def test_fixed_cohort_does_not_adopt_later_users_and_fresh_consent_is_required(self):
        self.share();ident=real.dashboard()['profiles'][0]['user_id'];root=Path(self.temp.name)/'case-studies/fixed-200';root.mkdir(parents=True)
        (root/'cohort.json').write_text(json.dumps({'label':'固定样本','frozen_at':'2026-10-17','public_user_ids':[ident]}),encoding='utf-8')
        personal.save_preferences(self.source,self.other,{'preferences':self.prefs,'expected_revision':0});real.set_consent(self.other,{'enabled':True})
        self.assertEqual(real.dashboard()['population'],2)
        result=real.export_case({'cohort':'fixed-200'});self.assertEqual(result['population'],1);self.assertEqual(result['records'][0]['user_id'],ident)
        real.set_consent(self.owner,{'enabled':False});result=real.export_case({'cohort':'fixed-200'})
        self.assertEqual(result['population'],0);self.assertEqual(result['cohort']['registered_accounts'],1)
        with self.assertRaises(ValueError):real.export_case({'cohort':'../../personal.sqlite3'})


if __name__=='__main__':unittest.main()
