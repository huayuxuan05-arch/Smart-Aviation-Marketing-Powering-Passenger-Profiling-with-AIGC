import copy
import unittest
from datetime import datetime,timedelta
from test_flight_quotes import fixture_result
import flight_ranking


class FlightRankingTests(unittest.TestCase):
    def query(self):return {'departure':'2026-11-15','return_date':'2026-11-18','adults':2,
        'required_airlines':['3U'],'excluded_airlines':['9C'],'trip_budget':2500,'airfare_cap':1000,
        'nonflight_total':1000,'budget_policy':'预算优先'}
    def option(self,shift=0,total=1800,carrier='3U'):
        q=self.query();o=fixture_result(q)['options'][0];o['total_price_cny']=total
        for leg in ['outbound','inbound']:
            o[leg]['price_cny']=total/2
            for key in ['departure_time','arrival_time']:o[leg][key]=(datetime.fromisoformat(o[leg][key])+timedelta(days=shift)).isoformat()
            for s in o[leg]['segments']:
                s['flight_number']=carrier+'1234'
                for key in ['departure_time','arrival_time']:s[key]=(datetime.fromisoformat(s[key])+timedelta(days=shift)).isoformat()
        return o
    def test_airline_priority_never_replaced_by_cheaper_carrier(self):
        result=flight_ranking.rank([self.option(total=900,carrier='9C'),self.option(total=2400)],self.query())
        self.assertEqual(len(result),1);self.assertEqual(result[0]['total_price_cny'],2400)
    def test_date_priority_precedes_cheaper_flexible_date_then_price(self):
        options=[self.option(shift=1,total=1200),self.option(total=2400),self.option(total=2200)]
        result=flight_ranking.rank(options,self.query())
        self.assertEqual([o['total_price_cny'] for o in result],[2200,2400,1200])
        self.assertEqual([o['recommendation_rank'] for o in result],[1,2,3])
    def test_user_strict_budget_tag_is_enforced(self):
        q={**self.query(),'budget_policy':'只看预算内'}
        result=flight_ranking.rank([self.option(total=8000),self.option(shift=1,total=1200)],q)
        self.assertEqual(len(result),1);self.assertEqual(result[0]['total_price_cny'],1200)


if __name__=='__main__':unittest.main()
