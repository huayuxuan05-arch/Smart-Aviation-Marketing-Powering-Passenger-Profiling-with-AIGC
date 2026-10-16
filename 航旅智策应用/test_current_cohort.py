"""Successful-only retention and admission checks, independent of provider uptime."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import flight_quotes as flights
import independent_cohort as cohort
import current_cohort_build as builder


class CurrentCohortTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=flights.RUNTIME/'tmp');self.root=Path(self.tmp.name)
        self.query=flights.query_for(dict(origin='武汉',destination='上海',start_date='2026-11-06',end_date='2026-11-08'),dict(max_stops=1))
        self.key='query-key';self.context=[dict(query=self.query,query_key=self.key)]
        self.manifest=cohort.generate(self.root/'test',8,'live_v2_test','2026-10-16',export_behaviors=False,flight_contexts=self.context)
        self.protocol=dict(version='test',splits=dict(test=dict(users=8,contexts=self.context)))
        self.records={self.key:dict(id='test-observation',query=self.query,status='success',requested_at=flights.now(),result=dict(options=[{'fixture':True}]))}
        (self.root/'successful-quotes').mkdir()
        cohort.write_json(self.root/'successful-quotes'/(self.key+'.json'),self.records[self.key])
    def tearDown(self):self.tmp.cleanup()
    def test_geometry_admission_and_annual_behavior(self):
        data,_,_=cohort.load(self.root/'test')
        self.assertEqual(data[0]['dest'].shape,(365,8))
        self.assertTrue(all((u['usual_departure_city'],u['requested_destination'],u['start_date'],u['days'])==('武汉','上海','2026-11-06',3) for u in data[1]))
        with patch.object(builder,'RUNTIME',self.root/'runtime'):
            result=builder.activate(self.root,self.protocol,self.records)
        self.assertEqual(result['splits']['test']['users_with_verified_current_quotes'],8)
        self.assertTrue(result['conditioned_sampling'])
    def test_stale_quote_refuses_activation(self):
        self.records[self.key]['requested_at']='2024-01-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'current complete'):
            builder.activate(self.root,self.protocol,self.records)
        self.assertFalse((self.root/'acceptance.json').exists())
    def test_refresh_missing_quote_cannot_reuse_prior_snapshot(self):
        with self.assertRaisesRegex(ValueError,'newly verified'):
            builder.activate(self.root,self.protocol,{})
    def test_modified_behavior_refuses_activation(self):
        with (self.root/'test'/'behavior_arrays.npz').open('ab') as f:f.write(b'tamper')
        with self.assertRaisesRegex(ValueError,'fingerprint'):builder.activate(self.root,self.protocol,self.records)
    def test_source_failure_writes_no_query_data(self):
        with patch.object(flights,'_search',side_effect=RuntimeError('provider unavailable')):
            self.assertIsNone(builder.quote(self.query))
    def test_nested_failed_attempts_are_discarded(self):
        value=dict(options=[{'usable':True}],query_quality={'failed':1},leg_observations=[
            dict(status='failed',error_code='diagnostic'),dict(status='empty',options=[]),dict(status='success',options=[{'price':100}])])
        clean=flights.successful_result(value)
        self.assertEqual(len(clean['leg_observations']),1);self.assertNotIn('query_quality',clean)
        self.assertEqual(len(value['leg_observations']),3)


if __name__=='__main__':unittest.main()
