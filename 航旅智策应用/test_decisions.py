"""用可控行程验证预算隔离、备选目的地和执行时重查；所有写入隔离。"""
import copy
import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import numpy as np
import decision_logic as decision
import marketing_app as app
import marketing_ml as ml


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.runtime = patch.object(app, 'RUNTIME', Path(self.temp.name))
        self.runtime.start()
        self.source = sqlite3.connect(':memory:')
        self.source.row_factory = sqlite3.Row
        self.source.executescript('''
            CREATE TABLE events(user_id TEXT,feedback_type TEXT,event_time_cst TEXT);
            CREATE TABLE flights(出发日 TEXT,出发城市 TEXT,到达城市 TEXT,机票票价 REAL,航班号 TEXT,出发时间 TEXT);
            INSERT INTO flights VALUES('2024-10-04','原始城市','乙城',800,'MU_TEST','10:00');
        ''')
        self.connection = patch.object(app, 'connect', return_value=self.source)
        self.connection.start()
        self.asof = '2024-09-30'
        self.t = ml.day_index(self.asof)
        shape = (397, 1)
        self.arrays = {key: np.zeros(shape, dtype=dtype) for key, dtype in
                       [('dest', 'int16'), ('type', 'uint8'), ('budget', 'float32'), ('travel', 'int16')]}
        self.arrays['budget'].fill(np.nan)
        self.arrays['travel'].fill(-1)
        self.record(self.t - 1, 0, '2024-10-03', 900)
        self.record(self.t - 2, 1, '2024-10-04', 1000)
        self.holiday = next(h for h in app.HOLIDAYS if h['id'] == 'national')
        self.snapshot = {'scores': np.array([[.9, .8]]), 'fare': np.array([[.4, .3]]),
                         'favorite': np.array([[.2, .1]]), 'clusters': np.array([0]),
                         'cluster': np.zeros((1, 12)), 'channel_ids': np.array([0]),
                         'time_ids': np.array([2]), 'hours': np.ones((1, 24)),
                         'X': np.zeros((1, 2, 23)), 'count': {60: np.array([[29, 1]])},
                         'favdest': np.zeros((1, 2)), 'learned': False, 'model': '隔离历史规则', 'day': self.t}
        self.users = [{'user_id': 'TEST_TRIP', 'usual_departure_city': '原始城市', 'residence_province': '测试省'}]
        self.data = patch.object(ml, 'load_data', return_value=(self.arrays, self.users, [], ['甲城', '乙城']))
        self.snap = patch.object(app, 'trained_snapshot', return_value=self.snapshot)
        self.data.start()
        self.snap.start()

    def tearDown(self):
        self.snap.stop()
        self.data.stop()
        self.connection.stop()
        self.source.close()
        self.runtime.stop()
        self.temp.cleanup()

    def record(self, day, destination, travel=None, budget=None):
        self.arrays['dest'][day, 0] = destination
        self.arrays['type'][day, 0] = 3 if budget is not None else 0
        self.arrays['travel'][day, 0] = ml.day_index(travel) if travel else -1
        self.arrays['budget'][day, 0] = budget if budget is not None else np.nan

    def intent(self, destination=1):
        return decision.trip_intent(self.arrays, 0, destination, self.asof, self.holiday)

    def campaign(self, approved=True):
        campaign = app.save_campaign(self.source, {'holiday': 'national', 'limit': 10})
        if approved:
            material = {'id': 'TEST_MATERIAL', 'campaign': campaign['id'], 'destination': '乙城',
                        'theme': campaign['audience'][0]['theme'], 'campaign_revision': 1,
                        'revision': 1, 'status': '已审核', 'review': {'revision': 1},
                        'title': '从容出行', 'text': '了解航线参考。', 'channel': '跟随旅客策略'}
            with app.db() as state:
                state.execute('INSERT INTO creatives VALUES(?,?,?)', (material['id'], campaign['id'], json.dumps(material)))
        return app.get_campaign(campaign['id'])

    def test_budget_only_matches_destination_and_current_plan(self):
        self.record(self.t, 0, '2024-10-04', 200)
        self.assertEqual(self.intent()['budget'], 1000)
        self.assertEqual(self.intent()['budget_evidence'], 1)

    def test_other_date_budget_is_reference_not_a_hard_limit(self):
        self.record(self.t, 1, '2024-10-05')
        intent = self.intent()
        self.assertEqual(intent['travel_date'], '2024-10-05')
        self.assertIsNone(intent['budget'])
        self.assertEqual(intent['budget_reference'], 1000)
        self.assertEqual(intent['budget_status'], 'reference')

    def test_latest_matching_budget_supersedes_earlier_query(self):
        self.record(self.t, 1, '2024-10-04', 1500)
        intent = self.intent()
        self.assertEqual(intent['budget'], 1500)
        self.assertEqual(intent['budget_evidence'], 2)

    def test_latest_plan_outside_holiday_does_not_resurrect_old_plan(self):
        self.record(self.t, 1, '2024-10-20', 1800)
        self.assertEqual(self.intent()['plan_status'], 'outside_holiday')
        self.assertEqual(self.intent()['travel_date'], '2024-10-20')
        self.assertIsNone(self.intent()['budget'])

    def test_future_rows_cannot_change_trip_intent(self):
        before = self.intent()
        self.record(self.t + 1, 1, '2024-10-06', 200)
        self.assertEqual(before, self.intent())

    def test_no_plan_keeps_scenario_separate_and_budget_unknown(self):
        self.record(self.t - 2, 1, budget=700)
        intent = self.intent()
        self.assertEqual(intent['plan_status'], 'unknown')
        self.assertEqual(intent['date_basis'], '营销假期情景假设')
        self.assertIsNone(intent['budget'])
        self.assertEqual(intent['budget_reference'], 700)

    def test_feasible_second_preference_recovers_match_without_origin_change(self):
        result = app.build_audience(self.source)
        row = result['audience'][0]
        self.assertEqual(row['destination'], '乙城')
        self.assertEqual(row['preference_rank'], 2)
        self.assertEqual(row['usual_departure_city'], '原始城市')
        self.assertEqual(row['travel_date'], '2024-10-04')
        self.assertTrue(row['business_ready'])
        self.assertEqual(result['strategy_comparison']['primary_matched'], 0)
        self.assertEqual(result['strategy_comparison']['recovered_matches'], 1)

    def test_explicit_destination_filter_is_never_relaxed(self):
        result = app.build_audience(self.source, {'destination': '甲城', 'require_flight': False})
        self.assertEqual(result['audience'][0]['destination'], '甲城')
        self.assertIsNone(result['audience'][0]['flight'])
        self.assertFalse(result['audience'][0]['business_ready'])

    def test_below_threshold_or_unobserved_alternative_is_not_used(self):
        result = app.build_audience(self.source, {'min_score': .85, 'require_flight': False})
        self.assertEqual(result['audience'][0]['destination'], '甲城')
        self.snapshot['count'][60][0, 1] = 0
        self.assertEqual(app.build_audience(self.source, {'require_flight': False})['audience'][0]['destination'], '甲城')

    def test_default_product_filter_reports_shortfall_without_inventing_candidates(self):
        self.assertTrue(app.settings()['require_flight'])
        self.source.execute('DELETE FROM flights')
        result = app.build_audience(self.source, {'limit': 10})
        self.assertEqual(result['audience_count'], 0)
        self.assertEqual(result['selection_funnel']['shortfall'], 10)
        self.assertIsNone(result['candidate_coverage']['rate'])
        self.assertFalse(result['candidate_coverage']['meets_target'])

    def test_material_ready_does_not_bypass_unknown_budget(self):
        campaign = self.campaign()
        with app.db() as state:
            row = json.loads(state.execute('SELECT payload FROM campaigns WHERE id=?', (campaign['id'],)).fetchone()[0])
            row['audience'][0]['budget'] = None
            row['audience'][0]['intent']['budget'] = None
            row['audience'][0]['intent']['budget_status'] = 'unknown'
            state.execute('UPDATE campaigns SET payload=? WHERE id=?', (json.dumps(row), campaign['id']))
        check = app.get_campaign(campaign['id'])['execution']
        self.assertEqual(check['material_ready'], 1)
        self.assertEqual(check['eligible'], 0)
        result = app.launch(self.source, campaign['id'], {'confirm': True})
        self.assertEqual(result['last_launch']['sent'], 0)
        self.assertFalse(result['deliveries'])
        self.assertIn('预算', result['last_launch']['blocked'][0]['reason'])

    def test_unsubscribe_after_preview_is_checked_at_execution(self):
        campaign = self.campaign()
        self.assertEqual(campaign['execution']['eligible'], 1)
        self.source.execute("INSERT INTO events VALUES('TEST_TRIP','unsubscribe','2024-10-01 07:00:00')")
        result = app.launch(self.source, campaign['id'], {'confirm': True})
        self.assertEqual(result['last_launch']['sent'], 0)
        self.assertIn('已退订', result['last_launch']['blocked'][0]['reason'])

    def test_later_unsubscribe_does_not_leak_into_earlier_execution(self):
        campaign = self.campaign()
        self.source.execute("INSERT INTO events VALUES('TEST_TRIP','unsubscribe','2024-10-01 23:00:00')")
        result = app.launch(self.source, campaign['id'], {'confirm': True})
        self.assertEqual(result['last_launch']['sent'], 1)
        self.assertFalse(result['execution']['real_sendable'])

    def test_product_change_after_preview_blocks_execution(self):
        campaign = self.campaign()
        self.source.execute('UPDATE flights SET 机票票价=1200')
        result = app.launch(self.source, campaign['id'], {'confirm': True})
        self.assertEqual(result['last_launch']['sent'], 0)
        self.assertIn('记录已变化', result['last_launch']['blocked'][0]['reason'])

    def test_repeat_execution_writes_no_duplicate_and_keeps_response_unknown(self):
        campaign = self.campaign()
        first = app.launch(self.source, campaign['id'], {'confirm': True})
        second = app.launch(self.source, campaign['id'], {'confirm': True})
        self.assertEqual(first['last_launch']['sent'], 1)
        self.assertEqual(second['last_launch']['sent'], 0)
        self.assertEqual(len(second['deliveries']), 1)
        self.assertIsNone(second['deliveries'][0]['payment'])
        self.assertIsNone(second['deliveries'][0]['click'])

    def test_legacy_campaign_preserved_but_not_executable(self):
        campaign = self.campaign()
        with app.db() as state:
            stored = json.loads(state.execute('SELECT payload FROM campaigns WHERE id=?', (campaign['id'],)).fetchone()[0])
            stored['audience'][0].pop('intent')
            state.execute('UPDATE campaigns SET payload=? WHERE id=?', (json.dumps(stored), campaign['id']))
        loaded = app.get_campaign(campaign['id'])
        self.assertEqual(loaded['audience_count'], 1)
        self.assertEqual(loaded['execution']['eligible'], 0)
        self.assertIn('旧版', loaded['execution']['items'][0]['blockers'][0])


if __name__ == '__main__':
    unittest.main()
