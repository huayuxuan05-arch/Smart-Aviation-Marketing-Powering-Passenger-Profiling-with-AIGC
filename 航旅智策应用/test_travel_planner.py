"""旅行规划不能通过删旅客、改航班日期或隐藏超预算来获得覆盖。"""
import sqlite3
import unittest
from unittest.mock import patch
from data_layer import connect
import travel_planner as planner
import local_generation as gen
from aigc_config import ALIAS
import json


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.db.row_factory=sqlite3.Row
        self.db.executescript('''CREATE TABLE flights(出发城市 TEXT,到达城市 TEXT,出发日 TEXT,机票票价 REAL,航班号 TEXT);
        INSERT INTO flights VALUES('甲','上海','2024-10-01',400,'TEST1'),('上海','乙','2024-10-03',300,'TEST2');''')
        self.network=planner.FlightNetwork(self.db)
    def tearDown(self):self.db.close()
    def test_other_date_remains_reference(self):
        route=self.network.route('甲','上海','2024-10-06')
        self.assertFalse(route['exact_date']);self.assertFalse(route['bookable'])
        self.assertEqual(route['flights'][0]['出发日'],'2024-10-01')
        self.assertEqual(route['target_date'],'2024-10-06')
    def test_two_legs_do_not_claim_connection(self):
        route=self.network.route('甲','乙','2024-10-01')
        self.assertEqual(len(route['flights']),2);self.assertFalse(route['exact_date'])
        self.assertIn('尚未核验',route['status']);self.assertEqual(route['reference_fare'],700)
    def test_suzhou_has_real_gateway(self):
        route=self.network.route('甲','苏州','2024-10-01')
        self.assertEqual(route['gateway'],'上海');self.assertIn('苏州',route['ground_transfer'])
        self.assertEqual(route['flights'][0]['到达城市'],'上海')
    def test_no_route_stays_missing(self):self.assertIsNone(self.network.route('乙','甲','2024-10-01'))


class FullPopulationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=connect();cls.config,cls.ctx=planner.context();cls.uid=cls.ctx[1][0]['user_id']
        cls.plan=planner.make_plan(cls.source,cls.uid)
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def test_all_travelers_have_outbound_return_and_plan(self):
        audit=planner.full_population_audit(self.source)
        self.assertEqual(audit['population'],10000);self.assertEqual(audit['planned'],10000)
        self.assertEqual(audit['with_flight_reference'],10000);self.assertEqual(audit['with_return_reference'],10000)
        self.assertEqual(audit['failed'],0);self.assertLess(audit['exact_date_direct'],audit['population'])
    def test_each_quoted_record_matches_source(self):
        for route in [self.plan['outbound'],self.plan['return_route']]:
            for flight in route['flights']:
                raw=self.source.execute('SELECT * FROM flights WHERE rowid=?',(flight['source_row'],)).fetchone()
                for key in ['出发日','出发城市','到达城市','航班号','机票票价']:self.assertEqual(flight[key],raw[key])
    def test_days_and_lodging_are_complete(self):
        plan=planner.make_plan(self.source,self.uid,{'days':7})
        self.assertEqual(len(plan['daily_itinerary']),7);self.assertEqual(plan['lodging']['nights'],6)
        self.assertTrue(all(len(day['blocks'])==4 for day in plan['daily_itinerary']))
        self.assertEqual(plan['daily_itinerary'][-1]['date'],plan['end_date'])
    def test_explicit_budget_changes_assumptions_and_discloses_excess(self):
        low=planner.make_plan(self.source,self.uid,{'trip_budget':100})
        high=planner.make_plan(self.source,self.uid,{'trip_budget':10000})
        self.assertGreater(low['budget']['difference'],0)
        self.assertLess(low['budget']['components'][2]['value'],high['budget']['components'][2]['value'])
        self.assertIn('情景',low['budget']['components'][2]['basis'])
    def test_new_date_does_not_reuse_old_airfare_cap(self):
        plan=planner.make_plan(self.source,self.uid,{'start_date':'2024-12-29'})
        self.assertEqual(plan['start_date'],'2024-12-29');self.assertIsNone(plan['budget']['one_way_airfare_cap'])
    def test_parent_and_senior_pace_and_different_plans(self):
        users=self.ctx[1]
        for party in ['亲子','长者同行']:
            user=next(u for u in users if u['travel_party']==party)
            plan=planner.make_plan(self.source,user['user_id'])
            self.assertEqual(plan['pace'],'轻松');self.assertIn('少换',plan['lodging']['type'])
        different=next(u for u in users if u['usual_departure_city']!=self.plan['origin'])
        plan=planner.make_plan(self.source,different['user_id'])
        self.assertNotEqual(plan['origin'],self.plan['origin'])
    def test_unknown_user_and_invalid_options(self):
        with self.assertRaisesRegex(ValueError,'旅客不存在'):planner.make_plan(self.source,'MISSING')
        for config in [{'days':2},{'trip_budget':'nan'},{'start_date':'2024-09-01'},{'pace':'不存在'}]:
            with self.assertRaises(ValueError):planner.options(config)
    def test_paginated_search_does_not_change_audited_population(self):
        result=planner.list_plans(self.source,{'q':self.uid,'page_size':1})
        self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['user_id'],self.uid)
        self.assertEqual(result['coverage']['population'],10000)
    def test_ai_editor_uses_existing_activities_and_keeps_structure(self):
        value={'summary':'按照现有主题安排轻松行程。','reasons':['保留休息。','围绕已有兴趣。'],'practical_tips':['核对预约。','确认航班。','调整交通。']}
        response={'model':ALIAS,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}
        with patch.object(gen,'ensure'),patch.object(gen,'rpc',return_value=response) as request:
            result=gen.explain_trip(self.plan)
        self.assertEqual(result['model_alias'],ALIAS)
        self.assertIn(self.plan['daily_itinerary'][0]['blocks'][2]['activity'],request.call_args.args[1]['messages'][1]['content'])
        self.assertNotIn('outbound',result)
        response['choices'][0]['message']['content']=json.dumps({**value,'summary':'保证最低价已预订'})
        with patch.object(gen,'ensure'),patch.object(gen,'rpc',return_value=response),self.assertRaisesRegex(ValueError,'无依据承诺'):gen.explain_trip(self.plan)


if __name__=='__main__':unittest.main()
