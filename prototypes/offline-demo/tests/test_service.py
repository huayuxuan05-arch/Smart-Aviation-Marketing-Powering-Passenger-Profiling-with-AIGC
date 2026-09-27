import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from app.data import synthetic_passengers
from app.service import Service


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.service = Service()
        self.addCleanup(self.service.db.close)
        self.pid = 'SYN-0002'

    def test_workflow_requires_review_and_prevents_duplicate_simulation(self):
        c = self.service.create_campaign(self.pid)
        with self.assertRaises(ValueError):
            self.service.transition(c['id'], 'simulate')
        self.service.transition(c['id'], 'approve')
        done = self.service.transition(c['id'], 'simulate')
        self.assertEqual(done['result']['real_messages_sent'], 0)
        with self.assertRaises(ValueError):
            self.service.transition(c['id'], 'simulate')
        self.assertEqual([a['action'] for a in self.service.audit()], ['simulate','approve','draft_created'])

    def test_revoked_consent_is_checked_again_at_simulation(self):
        c = self.service.create_campaign(self.pid)
        self.service.transition(c['id'], 'approve')
        self.service.passengers[1]['consent'] = False
        with self.assertRaisesRegex(ValueError, '复核失败'):
            self.service.transition(c['id'], 'simulate')

    def test_frequency_persists_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / 'demo.db')
            first = Service(path)
            c = first.create_campaign(self.pid)
            first.transition(c['id'], 'approve')
            first.transition(c['id'], 'simulate')
            first.db.close()
            second = Service(path)
            try:
                with self.assertRaisesRegex(ValueError, '频控'):
                    second.create_campaign(self.pid)
            finally:
                second.db.close()

    def test_parallel_campaigns_cannot_bypass_frequency(self):
        ids = [self.service.create_campaign(self.pid)['id'] for _ in range(2)]
        for cid in ids:
            self.service.transition(cid, 'approve')
        def run(cid):
            try:
                self.service.transition(cid, 'simulate')
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sum(pool.map(run, ids)), 1)

    def test_empty_and_all_ineligible_experiment_has_no_division_error(self):
        for passengers in [[], [{**p, 'consent':False} for p in synthetic_passengers()]]:
            service = Service(passengers=passengers)
            try:
                self.assertIsNone(service.simulated_experiment()['absolute_lift'])
            finally:
                service.db.close()

    def test_synthetic_experiment_is_reproducible_and_explicit(self):
        result = self.service.simulated_experiment()
        self.assertEqual(result, self.service.simulated_experiment())
        self.assertEqual(result['data_source'], 'synthetic')
        self.assertEqual(sum(g['assigned'] for g in result['groups'].values()), self.service.overview()['eligible'])
