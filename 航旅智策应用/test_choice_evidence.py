import json
import os
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timedelta
from unittest.mock import patch
import personal_app as personal
import travel_choice_evidence as evidence
import choice_ranker_training as training
import flight_quotes as quotes
from test_flight_quotes import fixture_result
from data_layer import connect,CST


class ChoiceEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=personal.RUNTIME/'tmp');self.root=Path(self.tmp.name)
        self.patches=[patch.object(personal,'RUNTIME',self.root),patch.object(quotes,'RUNTIME',self.root),
            patch.dict(os.environ,{'HTTPS_PROXY':'http://127.0.0.1:7897'}),
            patch.object(quotes,'configuration',return_value={'enabled':True}),
            patch.object(quotes._pool,'submit',side_effect=lambda fn,*a:fn(*a)),
            patch.object(quotes,'_search',side_effect=lambda q:fixture_result(q,variants=True))]
        for p in self.patches:p.start()
        _,self.owner,_=personal.session();_,self.other,_=personal.session()
        self.plan=personal.create_plan(self.source,self.owner,{'preferences':{**personal.defaults(),
            'origin':'上海','destination':'广州','start_date':(datetime.now(CST).date()+timedelta(days=14)).isoformat(),
            'days':4,'trip_budget':4000,'airfare_cap':1000}})['plan']
        self.q=quotes.submit(self.owner,self.plan,{'adults':2})
        self.body=dict(plan_id=self.plan['id'],query_id=self.q['id'],option_index=0,confirmed=True,expected_revision=1)
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()
    def groups(self):
        with personal.db() as c:return evidence.labeled_groups(c)

    def test_preview_is_not_a_choice_and_nonchoice_is_not_negative(self):
        personal.preview_flight_quote(self.owner,self.plan,self.body)
        self.assertEqual(self.groups(),[])
        personal.apply_flight_quote(self.owner,self.body)
        self.assertEqual(self.groups(),[])
        with personal.db() as c:
            candidates=json.loads(c.execute('SELECT candidates FROM itinerary_requests').fetchone()[0])
        self.assertTrue(all(c['relevance'] is None for c in candidates))
        self.assertEqual(candidates[0]['features']['one_way_upper'],1000)
        self.assertIsNone(candidates[0]['features']['one_way_lower'])
        self.assertEqual(candidates[0]['features']['outbound_per_adult'],400)

    def test_only_explicit_choose_reject_form_group_and_events_are_idempotent(self):
        for _ in range(2):personal.reject_flight_quote(self.owner,self.plan,{**self.body,'option_index':2})
        personal.apply_flight_quote(self.owner,self.body)
        groups=self.groups();self.assertEqual(len(groups),1)
        self.assertEqual([c['relevance'] for c in groups[0]['candidates']],[1,0])
        with personal.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM itinerary_feedback WHERE event='reject'").fetchone()[0],1)

    def test_foreign_or_unconfirmed_request_cannot_add_labels(self):
        for owner,body in [(self.other,self.body),(self.owner,{**self.body,'confirmed':False})]:
            with self.assertRaises(ValueError):personal.reject_flight_quote(owner,self.plan,body)
        with personal.db() as c:self.assertEqual(c.execute('SELECT COUNT(*) FROM itinerary_requests').fetchone()[0],0)

    def test_conflicting_judgements_are_excluded_not_overwritten(self):
        personal.reject_flight_quote(self.owner,self.plan,self.body)
        personal.apply_flight_quote(self.owner,self.body)
        self.assertEqual(self.groups(),[])

    def test_delete_is_not_rejection_and_readiness_never_fabricates_labels(self):
        personal.delete_plan(self.owner,self.plan['id'],{'confirmed':True})
        with personal.db() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM itinerary_feedback WHERE event='reject'").fetchone()[0],0)
            report=training.run(c,self.root/'readiness')
        self.assertFalse(report['training_performed']);self.assertEqual(report['observed_paired_requests'],0)

    def test_stale_revision_rolls_back_choice_and_plan_together(self):
        before=len(personal.state(self.owner)['plans'])
        with self.assertRaises(ValueError):personal.apply_flight_quote(self.owner,{**self.body,'expected_revision':0})
        self.assertEqual(len(personal.state(self.owner)['plans']),before)
        with personal.db() as c:self.assertEqual(c.execute("SELECT COUNT(*) FROM itinerary_feedback WHERE event='choose'").fetchone()[0],0)

    def test_budget_preference_and_actual_hard_constraints_are_separate(self):
        plan={**self.plan,'budget':{**self.plan['budget'],'one_way_airfare_cap':100}}
        f=evidence.candidate_features(plan,self.q['options'][0],2)
        self.assertTrue(f['hard_constraints_satisfied']);self.assertFalse(f['within_budget'])
        self.assertGreater(f['outbound_cap_ratio'],1)
    def test_explicit_interval_width_uses_actual_user_bounds(self):
        plan={**self.plan,'budget':{**self.plan['budget'],
            'trip_budget_range':{'min':2000,'max':4000},'one_way_airfare_range':{'min':300,'max':1000}}}
        f=evidence.candidate_features(plan,self.q['options'][0],2)
        self.assertEqual(f['trip_band_width'],2000);self.assertEqual(f['one_way_band_width'],700)
        self.assertEqual(f['one_way_lower'],300)

    def test_real_choice_split_excludes_late_development_events(self):
        groups=[dict(owner=str(i),recorded_at=f'2026-10-{i+1:02}T10:00:00',candidates=[]) for i in range(10)]
        groups.append(dict(owner='0',recorded_at='2026-10-20T10:00:00',candidates=[]))
        parts=training.split_groups(groups)
        self.assertEqual(list(map(len,parts)),[6,2,2])
        self.assertFalse(set(g['owner'] for g in parts[0])&set(g['owner'] for g in parts[2]))
        self.assertEqual(training.encoded({'trip_upper':None,'model_score':.9}),{'trip_upper__missing':1})


if __name__=='__main__':unittest.main()
