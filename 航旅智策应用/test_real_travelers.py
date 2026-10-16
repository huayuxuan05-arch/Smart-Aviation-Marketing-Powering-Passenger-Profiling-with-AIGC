"""Consented real data stays separate from QA/synthetic users and training data."""
import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import personal_app as personal
import real_travelers as real
from data_layer import connect


class RealTravelerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.temp=TemporaryDirectory(dir=Path(__file__).parent/'runtime/tmp')
        self.runtime=patch.object(personal,'RUNTIME',Path(self.temp.name));self.runtime.start()
        self.addCleanup(self.temp.cleanup);self.addCleanup(self.runtime.stop)
        _,self.first,_=personal.session();_,self.second,_=personal.session()
        self.prefs={**personal.defaults(),'origin':'上海','destination':'成都','start_date':(real.now().date()+timedelta(days=7)).isoformat(),'days':4,'trip_budget':2000,'required_airlines':['3U'],'excluded_airlines':['9C'],'travel_request':'private unshared raw chat'}
    def save(self,owner,**changes):
        current=personal.state(owner)
        return personal.save_preferences(self.source,owner,{'preferences':{**self.prefs,**changes},'expected_revision':current['revision']})
    def test_existing_and_qa_sessions_are_not_automatically_real_profiles(self):
        self.save(self.first)
        self.assertEqual(real.dashboard()['population'],0)
        self.assertEqual(real.dashboard()['hotspots'],[])
        self.assertFalse(personal.state(self.first)['collection']['enabled'])
    def test_explicit_consent_records_only_sanitized_preferences_and_real_changes(self):
        self.save(self.first);real.set_consent(self.first,{'enabled':True})
        data=real.dashboard();self.assertEqual(data['population'],1)
        self.assertEqual(data['hotspots'][0]['destination'],'成都')
        profile=real.profile(data['profiles'][0]['user_id'])
        self.assertNotIn('travel_request',profile['preferences'])
        self.assertNotIn('private unshared raw chat',json.dumps(profile))
        self.assertNotIn(self.first,json.dumps(data))
        self.save(self.first,destination='杭州')
        profile=real.profile(data['profiles'][0]['user_id'])
        self.assertEqual(profile['destination'],'杭州');self.assertEqual(len(profile['profile_history']),2)
    def test_popularity_counts_distinct_users_not_refreshes(self):
        for owner in (self.first,self.second):self.save(owner);real.set_consent(owner,{'enabled':True})
        with personal.db() as c:
            for _ in range(10):real.record_event(c,self.first,'flight_search','成都')
        data=real.dashboard();h=data['hotspots'][0]
        self.assertEqual(h['users'],2);self.assertEqual(h['users_last_7d'],2)
        self.assertEqual(sum(p['events_30d'].get('flight_search',0) for p in data['profiles']),1)
        self.assertIsNone(data['real_conversion_rate'])
    def test_withdrawal_removes_data_and_saved_campaign_members_immediately(self):
        self.save(self.first);real.set_consent(self.first,{'enabled':True})
        ident=real.dashboard()['profiles'][0]['user_id']
        real.create_campaign({'name':'真实需求跟进','user_ids':[ident]})
        real.set_consent(self.first,{'enabled':False})
        data=real.dashboard();self.assertEqual(data['population'],0);self.assertEqual(data['campaigns'][0]['user_ids'],[])
        with self.assertRaises(ValueError):real.profile(ident)
        with self.assertRaises(ValueError):real.create_campaign({'name':'旧名单','user_ids':[ident]})
        with personal.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM real_traveler_events').fetchone()[0],0)
        self.assertEqual(personal.state(self.first)['preferences']['destination'],'成都')
    def test_real_plan_export_requires_current_sharing_and_redacts_raw_request(self):
        with patch.dict('os.environ',{'AEROLENS_GENERATION_MODE':'template'}):personal.create_plan(self.source,self.first,{'preferences':self.prefs,'expected_revision':0})
        real.set_consent(self.first,{'enabled':True});ident=real.dashboard()['profiles'][0]['user_id']
        plan=real.plan(ident)
        self.assertEqual(plan['user_id'],ident);self.assertEqual(plan['audience'],'marketing')
        self.assertNotIn('travel_request',plan['preference_constraints'])
        real.set_consent(self.first,{'enabled':False})
        with self.assertRaises(ValueError):real.plan(ident)
    def test_invalid_or_unknown_consent_cannot_share_profiles(self):
        with self.assertRaises(ValueError):real.set_consent(self.first,{'enabled':'true'})
        self.assertEqual(real.dashboard()['population'],0)
        self.assertEqual(real.dashboard()['data_mode'],'real')
    def test_all_carrier_preferences_survive_empty_results_and_old_revisions_do_not_match(self):
        self.save(self.first,required_airlines=['CA','MU']);real.set_consent(self.first,{'enabled':True})
        revision=personal.state(self.first)['revision']
        query={'destinations':['成都'],'departure':self.prefs['start_date'],'return_date':self.prefs['start_date'],'required_airlines':['CA','MU'],'excluded_airlines':['9C']}
        real.record_flight_result(self.first,'QA_EMPTY',query,'empty',0,revision)
        real.record_flight_result(self.first,'QA_EMPTY',query,'empty',0,revision)
        data=real.dashboard();self.assertEqual(data['unmatched_users'],1)
        self.assertEqual({a['code']:a['unmatched_users'] for a in data['airline_preferences'] if a['preferred_users']},{'CA':1,'MU':1})
        self.assertEqual(data['profiles'][0]['preferences']['required_airlines'],['CA','MU'])
        self.assertEqual(data['profiles'][0]['events_30d']['flight_search_result'],1)
        self.save(self.first,required_airlines=['HU'])
        self.assertEqual(real.dashboard()['unmatched_users'],0)
        real.record_flight_result(self.first,'QA_FAILED',query,'failed',0,revision)
        self.assertEqual(real.dashboard()['profiles'][0]['events_30d']['flight_search_result'],1)
    def test_site_activity_is_allowlisted_consented_throttled_and_exported(self):
        self.save(self.first)
        body={'kind':'section_view','section':'lodging','raw_text':'must never be retained'}
        real.record_activity(self.first,body);self.assertEqual(real.dashboard()['population'],0)
        real.set_consent(self.first,{'enabled':True})
        for _ in range(3):real.record_activity(self.first,body)
        real.record_activity(self.first,{'kind':'section_view','section':'budget'})
        real.record_activity(self.first,{'kind':'workspace_action','action':'preview'})
        real.record_activity(self.first,{'kind':'destination_view','destination':'杭州'})
        with self.assertRaises(ValueError):real.record_activity(self.first,{'kind':'section_view','section':'external_browser'})
        data=real.dashboard();self.assertEqual(data['behavior_groups']['住宿安排'],1)
        self.assertEqual(data['behavior_groups']['费用预算'],1)
        export=real.export_case();self.assertEqual(len(export['records']),1)
        self.assertNotIn('raw_text',json.dumps(export));self.assertNotIn('private unshared raw chat',json.dumps(export))
        real.set_consent(self.first,{'enabled':False});self.assertEqual(real.export_case()['records'],[])


if __name__=='__main__':unittest.main()
