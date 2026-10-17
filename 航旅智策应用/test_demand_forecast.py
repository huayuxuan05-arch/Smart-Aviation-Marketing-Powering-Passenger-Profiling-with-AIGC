"""Leakage, promotion and temporal-use checks against retained actual artifacts."""
from datetime import timedelta
import json
import unittest
from unittest.mock import patch
import numpy as np
import demand_forecast as forecast
import independent_cohort as cohort
import marketing_ml as ml
from select_simulated_population import population_path


class DemandForecastTests(unittest.TestCase):
    def test_future_behavior_changes_labels_but_not_observed_features(self):
        data,base,_=cohort.load(population_path()/'validation')
        arrays={k:v[:,:12].copy() for k,v in data[0].items()}
        sample=(arrays,data[1][:12],data[2],data[3]);day=330
        date=(base+timedelta(days=day)).date().isoformat()
        before=ml.snapshot(date,dataset=sample,base_date=base,holidays=[])['X']
        old=ml.targets(day,dataset=sample)['continue']
        arrays['dest'][day+1:]=40;arrays['dwell'][day+1:]=999999
        arrays['action'][day+1:]=1;arrays['budget'][day+1:]=999999
        after=ml.snapshot(date,dataset=sample,base_date=base,holidays=[])['X']
        np.testing.assert_array_equal(before,after)
        self.assertFalse(np.array_equal(old,ml.targets(day,dataset=sample)['continue']))

    def test_evaluation_does_not_promote_uncertain_candidate(self):
        path=forecast.ROOT/forecast.VERSION
        report=json.loads((path/'report.json').read_text(encoding='utf-8'))
        selection=json.loads((path/'selection.json').read_text(encoding='utf-8'))
        self.assertEqual(report['selected'],selection['selected'])
        self.assertFalse(selection['test_used_for_selection'])
        self.assertEqual(report['base_model_sha256'],cohort.digest(ml.ROOT/'marketing_models.joblib'))
        self.assertEqual(report['population']['owner_overlap'],0)
        self.assertLess(max(forecast.TRAIN_DAYS)+7,min(forecast.VALIDATION_DAYS))
        if report['paired_ndcg_vs_validation_best_baseline']['ci95'][0]<=0:
            self.assertFalse(report['promoted'])
        reference=forecast.reference()
        if not report['promoted']:self.assertFalse(reference['available'])

    def test_new_model_cannot_score_historical_replay(self):
        # A future-trained model must not be used for 2024 holiday replay.
        with patch.object(forecast,'active_pack',return_value=({}, {}, {'available_from':'2026-10-17'})):
            self.assertIsNone(forecast.predict(np.zeros((1,41,23)),'2024-09-30'))

    def test_bootstrap_counts_people_instead_of_repeated_snapshots(self):
        y=np.array([[1,0,0,0]]*6);good=y.astype(float);bad=1-good
        result=forecast.paired_ci(y,good,bad,['a','b','c','a','b','c'])
        self.assertEqual(result['independent_people'],3)
        self.assertGreater(result['ci95'][0],0)


if __name__=='__main__':unittest.main()
