"""Annual cohort isolation, future masking, frozen model compatibility and query sharing."""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
import numpy as np
import independent_cohort as cohort
import independent_evaluation as evaluation
import marketing_ml as ml


class IndependentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(dir=ml.ROOT.parent/'tmp')
        cls.root=Path(cls.tmp.name)
        cls.manifest=cohort.generate(cls.root/'test',32,'test','2026-10-16',export_behaviors=False)
        cls.data,cls.base,_=cohort.load(cls.root/'test')

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def test_full_year_distinct_user_ids_and_complete_windows(self):
        self.assertEqual(self.data[0]['dest'].shape,(365,32))
        self.assertEqual(self.manifest['behavior_rows'],365*32)
        self.assertEqual(self.manifest['original_user_overlap'],0)
        self.assertEqual(self.manifest['behavior_start'],'2025-10-16')
        self.assertEqual(self.manifest['behavior_end'],'2026-10-15')
        self.assertEqual(len({u['user_id'] for u in self.data[1]}),32)
        for day in evaluation.cutoff_dates('2026-10-16',[67,37,7]):
            y=ml.targets(ml.day_index(day,self.base),dataset=self.data)
            self.assertEqual(y['continue'].shape,(32,41))
        with self.assertRaisesRegex(ValueError,'标签窗口不完整'):
            ml.targets(358,dataset=self.data)

    def test_future_changes_do_not_modify_annual_features(self):
        day='2026-10-08';t=ml.day_index(day,self.base)
        before=ml.snapshot(day,dataset=self.data,base_date=self.base,holidays=cohort.HOLIDAYS)
        arrays={k:v.copy() for k,v in self.data[0].items()}
        for value in arrays.values():value[t+1:]=0
        after=ml.snapshot(day,dataset=(arrays,*self.data[1:]),base_date=self.base,holidays=cohort.HOLIDAYS)
        for field in ['X','cluster','channels','hours','budget','favdest']:
            np.testing.assert_array_equal(before[field],after[field])

    def test_development_users_are_distinct_and_seed_is_reproducible(self):
        cohort.generate(self.root/'validation',32,'validation','2026-10-16',seed=cohort.SEED+1,export_behaviors=False)
        other,_,_=cohort.load(self.root/'validation')
        self.assertFalse({u['user_id'] for u in self.data[1]}&{u['user_id'] for u in other[1]})
        cohort.generate(self.root/'repeat',32,'test','2026-10-16',export_behaviors=False)
        repeated,_,_=cohort.load(self.root/'repeat')
        for name in self.data[0]:np.testing.assert_array_equal(self.data[0][name],repeated[0][name])

    def test_manifest_detects_modified_cohort(self):
        directory=self.root/'tamper';cohort.generate(directory,8,'tamper','2026-10-16',export_behaviors=False)
        with (directory/'users.jsonl').open('a') as f:f.write('{}\n')
        with self.assertRaisesRegex(ValueError,'fingerprint'):
            cohort.generate(directory,8,'tamper','2026-10-16',export_behaviors=False)

    def test_original_feature_and_label_results_remain_identical(self):
        data=ml.load_data();before=ml.snapshot('2024-09-30')
        after=ml.snapshot('2024-09-30',dataset=data,base_date=ml.BASE_DATE,holidays=ml.HOLIDAYS)
        np.testing.assert_array_equal(before['X'],after['X'])
        t=ml.day_index('2024-09-30')
        for key,value in ml.targets(t).items():np.testing.assert_array_equal(value,ml.targets(t,dataset=data)[key])

    def test_user_level_metric_retains_undefined_cases(self):
        y=np.zeros((3,2,41),np.uint8);y[:,0,0]=1
        scores=np.zeros_like(y,float);scores[:,0,0]=1
        actual=evaluation.individual_ndcg(y,scores)
        self.assertEqual(actual[0],1);self.assertTrue(np.isnan(actual[1]))

    def test_live_queries_are_shared_and_keys_are_safe(self):
        users=[]
        for i in range(10000):
            origin,destination=cohort.ROUTES[i%8]
            users.append(dict(usual_departure_city=origin,requested_destination=destination,
                start_date=f'2026-10-{23+7*((i//8)%2)}',days=[3,5][(i//16)%2]))
        keys={evaluation.flight_key(evaluation.query_for_user(u)) for u in users}
        self.assertEqual(len(keys),32)
        self.assertTrue(all(len(k)==64 and k.isalnum() for k in keys))

    def test_retraining_gate_and_selection_never_depend_on_test_scores(self):
        metrics={'原冻结模型':dict(recall_at_3=.9,ndcg_at_3=.88),
                 '14天衰减':dict(recall_at_3=.901,ndcg_at_3=.882)}
        self.assertFalse(evaluation.needs_retraining(metrics))
        metrics['14天衰减']['ndcg_at_3']=.9
        self.assertTrue(evaluation.needs_retraining(metrics))
        metrics['new']=dict(recall_at_3=.8,ndcg_at_3=.99)
        self.assertEqual(evaluation.choose_method(metrics),'14天衰减')

    def test_flights_do_not_substitute_historical_or_simulated_fares(self):
        root=self.root/'flight';(root/'test').mkdir(parents=True)
        future=(datetime.now()+timedelta(days=7)).date().isoformat()
        user=dict(user_id='TEST_ONLY',usual_departure_city='北京',requested_destination='杭州',
            start_date=future,days=3,trip_budget=4000,airfare_cap=1000)
        (root/'test'/'users.jsonl').write_text(json.dumps(user),encoding='utf-8')
        with patch.object(evaluation.flights,'configured_proxy',return_value='http://127.0.0.1:1'),patch.object(evaluation.flights,'_search',side_effect=RuntimeError('offline')):
            result=evaluation.collect_flights(root)
        self.assertEqual(result['statuses'],{'failed':1});self.assertEqual(result['user_route_match_rate'],0)
        self.assertEqual(result['constraint_match_rate'],0)


if __name__=='__main__':unittest.main()
