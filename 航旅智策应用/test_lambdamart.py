import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
import numpy as np
import independent_cohort as cohort
import marketing_ml as ml
import lambdamart_evaluation as ranking
import itinerary_ranking as itinerary


class RankingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=ml.ROOT.parent/'tmp')
        cohort.generate(Path(cls.tmp.name),24,'rank_unit','2026-10-16',export_behaviors=False)
        cls.data,cls.base,_=cohort.load(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_future_events_cannot_change_extended_features(self):
        day='2026-08-01';t=ml.day_index(day,self.base)
        s=ml.snapshot(day,dataset=self.data,base_date=self.base,holidays=[])
        expected=ranking.extend_features(s,self.data)
        arrays={k:v.copy() for k,v in self.data[0].items()}
        for v in arrays.values():v[t+1:]=0
        changed=(arrays,*self.data[1:])
        actual=ranking.extend_features(ml.snapshot(day,dataset=changed,base_date=self.base,holidays=[]),changed)
        np.testing.assert_array_equal(expected,actual)
        self.assertEqual(expected.shape,(24,41,len(ranking.FEATURES)))

    def test_qid_keeps_whole_passenger_lists_together(self):
        x=np.zeros((4,41,36),np.float32);y=np.zeros((4,41),np.uint8)
        flat,labels,qid=ranking.grouped_rows(x,y)
        self.assertEqual(flat.shape,(164,36))
        np.testing.assert_array_equal(np.bincount(qid),[41]*4)
        with self.assertRaises(ValueError):ranking.grouped_rows(x,y[:3])
        x[0,0,0]=np.nan
        with self.assertRaises(ValueError):ranking.grouped_rows(x,y)

    def test_disjoint_guard_rejects_reused_holdout_ids(self):
        ranking.assert_disjoint(['old'],['new'])
        with self.assertRaises(ValueError):ranking.assert_disjoint(['old'],['old'])

    def test_ranker_learns_group_relevance_without_identifiers(self):
        try:from xgboost import XGBRanker
        except ImportError:self.skipTest('Optional offline xgboost not installed')
        x=np.zeros((40,3,2),np.float32);y=np.zeros((40,3),np.uint8)
        for i in range(40):x[i,i%3,0]=1;y[i,i%3]=1
        flat,labels,qid=ranking.grouped_rows(x,y)
        model=XGBRanker(n_estimators=12,max_depth=2,n_jobs=2,objective='rank:ndcg').fit(flat,labels,qid=qid)
        scores=model.predict(flat).reshape(y.shape)
        np.testing.assert_array_equal(scores.argmax(axis=1),y.argmax(axis=1))

    def test_uncertainty_reads_behavior_not_scenario(self):
        x=np.zeros((2,41,23),np.float32);x[0,:,1]=1/41;x[1,3,1]=1
        self.assertTrue(itinerary.exploration_state(dict(X=x),0)['needs_preference_confirmation'])
        self.assertFalse(itinerary.exploration_state(dict(X=x),1)['needs_preference_confirmation'])


class ItineraryTests(unittest.TestCase):
    def setUp(self):
        self.asof='2026-10-16T10:00:00+08:00'
        self.p=dict(one_way_airfare=dict(min=400,max=700),adult_trip_budget=dict(min=1200,max=1600),
            days=3,destination='杭州',start_date='2026-10-23')

    def candidate(self,price=300,observed='2026-10-16T09:59:00+08:00'):
        def leg(day):return dict(price_cny=price,segments=[dict(departure_time=day+'T10:00:00',arrival_time=day+'T12:00:00')])
        return dict(destination='杭州',start_date='2026-10-23',max_stops=0,interest_score=1,
            observed_at=observed,option=dict(outbound=leg('2026-10-23'),inbound=leg('2026-10-25')))

    def test_current_features_keep_intervals_and_quote_clock(self):
        f=itinerary.itinerary_features(self.candidate(),self.p,self.asof)
        self.assertEqual(f['booking_lead_days'],7);self.assertEqual(f['airfare_band_width'],300)
        self.assertEqual(f['quote_age_minutes'],1);self.assertEqual(f['outbound_minutes'],120)

    def test_future_quote_is_rejected_even_in_offline_mode(self):
        result=itinerary.rank([self.candidate(observed='2026-10-16T10:01:00+08:00')],self.p,self.asof,offline_snapshot=True)
        self.assertIsNone(result['selected']);self.assertEqual(result['rejected'],dict(invalid_quote=1))

    def test_stale_quote_never_silently_becomes_live_offer(self):
        c=self.candidate(observed='2026-10-16T09:30:00+08:00')
        self.assertIsNone(itinerary.rank([c],self.p,self.asof)['selected'])
        offline=itinerary.rank([c],self.p,self.asof,offline_snapshot=True)
        self.assertIsNotNone(offline['selected']);self.assertTrue(offline['requires_quote_refresh_before_use'])

    def test_huge_score_cannot_override_budget(self):
        c=self.candidate(price=900);c['interest_score']=1e6
        self.assertIsNone(itinerary.rank([c],self.p,self.asof)['selected'])

    def test_date_shift_outside_permission_is_rejected(self):
        c=self.candidate();c['start_date']='2026-10-30'
        result=itinerary.rank([c],self.p,self.asof,allow_alternatives=True)
        self.assertIsNone(result['selected']);self.assertEqual(result['rejected']['date_outside_permission'],1)

    def test_wrong_return_day_cannot_enter_itinerary_ranking(self):
        c=self.candidate();c['option']['inbound']['segments'][0].update(
            departure_time='2026-10-24T10:00:00',arrival_time='2026-10-24T12:00:00')
        result=itinerary.rank([c],self.p,self.asof)
        self.assertIsNone(result['selected']);self.assertEqual(result['rejected']['invalid_quote'],1)


if __name__=='__main__':unittest.main()
