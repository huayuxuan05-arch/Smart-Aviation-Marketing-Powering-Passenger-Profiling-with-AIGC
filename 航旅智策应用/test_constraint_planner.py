import unittest
import numpy as np
from constraint_planner import optimize,propose_reallocation
from price_range_evaluation import band,classify,combine_observed_legs
from new_method_evaluation import fit_pairwise,predict_pairwise


class ConstraintTests(unittest.TestCase):
    def setUp(self):
        self.preferences=dict(one_way_airfare=dict(min=400,max=700),
            adult_trip_budget=dict(min=1200,max=1600),days=3,destination='杭州',start_date='2026-10-23')

    def candidate(self,price=300,city='杭州',day='2026-10-23',score=1):
        return dict(destination=city,start_date=day,interest_score=score,max_stops=0,
            option=dict(total_price_cny=price*2,outbound=dict(price_cny=price),inbound=dict(price_cny=price)))

    def test_cheaper_than_band_remains_feasible(self):
        result=optimize([self.candidate()],self.preferences)
        self.assertEqual(result['status'],'original_conditions_feasible')
        self.assertLessEqual(result['selected']['estimated_total'],1600)
        self.assertFalse(result['selected']['within_target_band'])
        self.assertFalse(result['accepted'])

    def test_high_interest_never_overrides_hard_budget(self):
        result=optimize([self.candidate(price=900,score=1),self.candidate(city='西安',score=.1)],
            self.preferences,allow_alternatives=True)
        self.assertEqual(result['status'],'alternative_requires_confirmation')
        self.assertEqual(result['selected']['destination'],'西安')
        self.assertTrue(result['selected']['requires_confirmation'])

    def test_alternatives_are_never_silently_accepted(self):
        candidate=self.candidate(day='2026-10-26')
        self.assertEqual(optimize([candidate],self.preferences)['status'],'no_feasible_quote')
        result=optimize([candidate],self.preferences,allow_alternatives=True)
        self.assertEqual(result['status'],'alternative_requires_confirmation')
        self.assertFalse(result['accepted'])

    def test_no_quote_does_not_produce_a_fictitious_fare(self):
        self.assertIsNone(optimize([],self.preferences)['selected'])
        result=optimize([self.candidate(price=900)],self.preferences)
        self.assertGreater(result['nearest'][0]['one_way_budget_gap'],0)
        self.assertIsNone(result['selected'])

    def test_price_interval_keeps_upper_bound_and_labels_lower_price(self):
        self.assertEqual(band(1000)['min'],800);self.assertEqual(band(1000)['max'],1200)
        options=[self.candidate(price=300)['option']]
        status,_=classify(options,dict(min=400,max=700),dict(min=1000,max=2000),600)
        self.assertEqual(status,'below_target_band')
        status,_=classify(options,dict(min=200,max=250),dict(min=1000,max=2000),600)
        self.assertEqual(status,'airfare_above_max')

    def test_observed_combinations_reject_overnight_and_discontinuous_legs(self):
        segment=dict(flight_number='TEST',departure_time='2026-10-23T10:00:00',arrival_time='2026-10-23T11:00:00',origin_airport='AAA',destination_airport='BBB')
        out=dict(origin='AAA',destination='BBB',segments=[segment],price_cny=300)
        incoming=dict(origin='BBB',destination='AAA',segments=[{**segment,'departure_time':'2026-10-25T10:00:00','arrival_time':'2026-10-25T11:00:00','origin_airport':'BBB','destination_airport':'AAA'}],price_cny=300)
        record=dict(query=dict(departure='2026-10-23',return_date='2026-10-25'),result=dict(leg_observations=[dict(date='2026-10-23',options=[out]),dict(date='2026-10-25',options=[incoming])]))
        self.assertEqual(len(combine_observed_legs(record)),1)
        segment['arrival_time']='2026-10-24T01:00:00'
        self.assertEqual(combine_observed_legs(record),[])

    def test_pairwise_ranker_learns_only_feature_differences(self):
        x=np.zeros((30,3,2),np.float32);x[:,0,0]=1;y=np.zeros((30,3),np.uint8);y[:,0]=1
        pack=fit_pairwise(x,y,seed=5);scores=predict_pairwise(dict(X=x),pack)
        self.assertTrue(np.all(scores[:,0]>scores[:,1]))
        self.assertEqual(pack['model'].n_features_in_,2)

    def test_budget_reallocation_is_explicit_and_does_not_raise_total_ceiling(self):
        preferences={**self.preferences,'adult_trip_budget':dict(min=1200,max=2000),
            'one_way_airfare':dict(min=200,max=300)}
        proposal=propose_reallocation([self.candidate(price=400)],preferences)
        self.assertTrue(proposal['requires_confirmation']);self.assertFalse(proposal['accepted'])
        self.assertEqual(proposal['original_one_way_upper'],300)
        self.assertEqual(proposal['requested_one_way_upper'],400)
        self.assertLessEqual(proposal['estimated_total'],2000)


if __name__=='__main__':unittest.main()
