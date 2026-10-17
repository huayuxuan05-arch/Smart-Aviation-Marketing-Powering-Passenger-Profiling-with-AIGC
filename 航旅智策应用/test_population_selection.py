"""Population limits and selection must not depend on unseen future behavior."""
import unittest
import numpy as np
from select_simulated_population import allocation, stratum


class PopulationSelectionTests(unittest.TestCase):
    def test_proportional_selection_keeps_exact_count_and_capacities(self):
        sizes={'large':10000,'small':2000,'tiny':3,'empty':0}
        for count in (0,1,17,1600,sum(sizes.values())):
            with self.subTest(count=count):
                result=allocation(sizes,count)
                self.assertEqual(sum(result.values()),count)
                self.assertTrue(all(0<=result[k]<=sizes[k] for k in sizes))
                for key in sizes:
                    self.assertLess(abs(result[key]-count*sizes[key]/sum(sizes.values())),1)
                self.assertEqual(result,allocation(dict(reversed(list(sizes.items()))),count))
        with self.assertRaises(ValueError):allocation(sizes,20000)

    def test_future_dwell_model_scores_and_future_outcomes_do_not_change_selection(self):
        user=dict(usual_departure_city='上海',age_band='25-34',travel_party='亲子')
        observed=np.ones(365)*100
        changed=observed.copy();changed[30:]=99999
        a=stratum('batch',user,observed)
        b=stratum('batch',{**user,'model_score':1,'future_purchase':True,'scenario':'changed'},changed)
        self.assertEqual(a,b)
        self.assertNotEqual(a,stratum('batch',{**user,'usual_departure_city':'武汉'},observed))


if __name__=='__main__':unittest.main()
