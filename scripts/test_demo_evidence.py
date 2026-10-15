"""核验对照统计口径，尤其是无相关标签、稳定并列与旅客整组权重。"""
import unittest
import numpy as np
from scripts.run_demo_evidence import per_user_metrics, paired_ci


class EvidenceStatisticsTests(unittest.TestCase):
    def test_ranking_known_order_ties_and_missing_relevance(self):
        y = np.array([[1, 0, 0, 1], [0, 0, 0, 0], [0, 1, 0, 0]])
        scores = np.array([[.9, .8, .7, .1], [.1, .2, .3, .4], [1, 1, 1, 1]])
        result = per_user_metrics(y, scores)
        self.assertEqual(result['Recall@3'][0], .5)
        self.assertTrue(np.isnan(result['Recall@3'][1]))
        self.assertEqual(result['Recall@3'][2], 1)
        self.assertAlmostEqual(result['NDCG@3'][0], 1 / (1 + 1 / np.log2(3)))
        self.assertAlmostEqual(result['NDCG@3'][2], 1 / np.log2(3))

    def test_cluster_bootstrap_weights_actual_valid_snapshots(self):
        first = np.array([[1., np.nan], [0., 0.]])
        second = np.array([[0., np.nan], [0., 0.]])
        result = paired_ci(first, second, 1000)
        self.assertAlmostEqual(result['difference'], 1 / 3)
        self.assertEqual(result, paired_ci(first, second, 1000))
        self.assertEqual(result['ci95'], [0., .5])

    def test_unpaired_missing_labels_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'identical eligible'):
            paired_ci(np.array([1., np.nan]), np.array([0., 1.]), 1000)


if __name__ == '__main__':
    unittest.main()
