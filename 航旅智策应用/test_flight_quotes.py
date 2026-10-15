"""真实数据边界、失败记录、会话隔离和确认保存；报价全部为明确的测试夹具。"""
import copy
import json
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import flight_quotes as quotes
import personal_app as personal
from data_layer import CST, connect


def fixture_result(query):
    if query['adults']==9:raise TimeoutError('QA simulated provider failure')
    def leg(origin,destination,day,amount,number):
        segment={'flight_number':number,'airline':'测试航空','airline_zh':'测试航空',
                 'origin_airport':origin,'destination_airport':destination,
                 'departure_time':day+'T10:00:00','arrival_time':day+'T12:00:00'}
        return {'segments':[segment],'price_cny':amount,'departure_time':segment['departure_time'],
                'arrival_time':segment['arrival_time'],'airlines':['测试航空'],'layovers':[],'stop_count':0}
    option={'total_price_cny':1800,'outbound':leg('SHA','CAN',query['departure'],800,'TEST100'),
            'inbound':leg('CAN','SHA',query['return_date'],1000,'TEST101')}
    return {'source':'QA fixture / not live','fare_basis':'测试夹具，不是真实票价',
            'options':[option],'leg_observations':[],'upstream_commit':quotes.UPSTREAM_COMMIT}


class FlightQuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.source=connect()
    @classmethod
    def tearDownClass(cls):cls.source.close()
    def setUp(self):
        folder=Path(__file__).parent/'runtime/tmp';folder.mkdir(parents=True,exist_ok=True)
        self.temp=TemporaryDirectory(dir=folder)
        self.patches=[patch.object(quotes,'RUNTIME',Path(self.temp.name)),patch.object(personal,'RUNTIME',Path(self.temp.name)),
                      patch.dict(os.environ,{'HTTPS_PROXY':'http://127.0.0.1:7897'}),
                      patch.object(quotes,'configuration',return_value={'enabled':True}),
                      patch.object(quotes._pool,'submit',side_effect=lambda f,*a:f(*a))]
        for p in self.patches:p.start()
        _,self.owner,_=personal.session();_,self.other,_=personal.session()
        self.start=(datetime.now(CST).date()+timedelta(days=14)).isoformat()
        self.plan=personal.create_plan(self.source,self.owner,{'preferences':{**personal.defaults(),
            'origin':'上海','destination':'广州','start_date':self.start,'days':4,'trip_budget':2000}})['plan']
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()
    def quote(self):
        with patch.object(quotes,'_search',side_effect=fixture_result):
            return quotes.submit(self.owner,self.plan,{'adults':2})
    def test_personal_plan_has_no_historical_fares_or_flights(self):
        self.assertEqual(self.plan['outbound']['flights'],[])
        self.assertIsNone(self.plan['budget']['estimated_total'])
        self.assertIsNone(self.plan['budget']['components'][0]['value'])
        self.assertFalse(self.plan['bookable'])
    def test_observations_cached_and_owned(self):
        q=self.quote();self.assertEqual(q['status'],'success')
        cached=quotes.submit(self.owner,self.plan,{'adults':2})
        self.assertEqual(cached['id'],q['id'])
        with self.assertRaises(ValueError):quotes.get(self.other,q['id'])
        self.assertEqual(quotes.history(self.other,q['query'])['items'],[])
    def test_failures_and_empty_results_are_recorded_without_zero_prices(self):
        with patch.object(quotes,'_search',side_effect=TimeoutError('private endpoint')):
            failed=quotes.submit(self.owner,self.plan,{'adults':3})
        self.assertEqual(failed['status'],'failed');self.assertNotIn('error',failed)
        self.assertIsNone(quotes.history(self.owner,failed['query'])['items'][0]['minimum_total_cny'])
        with patch.object(quotes,'_search',return_value={'options':[]}):
            empty=quotes.submit(self.owner,self.plan,{'adults':4})
        self.assertEqual(empty['status'],'empty')
    def test_preview_uses_group_quote_per_adult_without_saving(self):
        q=self.quote();before=personal.get_plan(self.owner,self.plan['id'])
        preview=quotes.preview(self.owner,self.plan,{'query_id':q['id'],'option_index':0})
        self.assertEqual(preview['budget']['components'][0]['value'],400)
        self.assertEqual(preview['budget']['components'][1]['value'],500)
        self.assertEqual(preview['live_flights']['adults'],2)
        self.assertGreater(preview['budget']['difference'],0)
        self.assertEqual(len(personal.state(self.owner)['plans']),1)
        self.assertEqual(personal.get_plan(self.owner,self.plan['id']),before)
    def test_confirm_creates_new_plan_and_preserves_old_version(self):
        q=self.quote();state=personal.state(self.owner)
        body={'plan_id':self.plan['id'],'query_id':q['id'],'option_index':0,'expected_revision':state['revision']}
        with self.assertRaises(ValueError):personal.apply_flight_quote(self.owner,body)
        saved=personal.apply_flight_quote(self.owner,{**body,'confirmed':True})
        self.assertNotEqual(saved['id'],self.plan['id']);self.assertEqual(saved['parent_plan_id'],self.plan['id'])
        self.assertEqual(personal.get_plan(self.owner,self.plan['id']),self.plan)
        self.assertEqual(personal.state(self.owner)['revision'],state['revision'])
    def test_mismatched_and_expired_quotes_cannot_enter_budget(self):
        q=self.quote();body={'query_id':q['id'],'option_index':0}
        with self.assertRaises(ValueError):quotes.preview(self.owner,{**self.plan,'destination':'成都'},body)
        with self.assertRaises(ValueError):quotes.preview(self.owner,self.plan,{**body,'option_index':-1})
        with quotes.db() as c:c.execute("UPDATE flight_observations SET requested_at='2024-01-01T00:00:00+00:00' WHERE id=?",(q['id'],))
        with self.assertRaises(ValueError):quotes.preview(self.owner,self.plan,body)
    def test_expired_selected_quote_is_hidden_and_budget_becomes_incomplete(self):
        q=self.quote();p=quotes.preview(self.owner,self.plan,{'query_id':q['id'],'option_index':0})
        p['live_flights']['observed_at']='2024-01-01T00:00:00+00:00'
        public=quotes.latest_only(p)
        self.assertNotIn('live_flights',public);self.assertIsNone(public['budget']['estimated_total'])
    def test_raw_training_flights_are_not_returned_by_web_projection(self):
        old={'flight':{'航班号':'OLD100','出发日':'2024-10-01','机票票价':777},'business_ready':True}
        original=copy.deepcopy(old);public=quotes.public_payload(old)
        self.assertIsNone(public['flight']);self.assertFalse(public['business_ready']);self.assertEqual(old,original)
        self.assertEqual(quotes.public_payload([1,None,[None,2]]),[1,None,[None,2]])
    def test_proxy_is_required_and_never_guessed(self):
        with patch.dict(os.environ,{'HTTPS_PROXY':'','https_proxy':''}):
            with self.assertRaises(ValueError):quotes.configured_proxy()
        with patch.dict(os.environ,{'HTTPS_PROXY':'socks5://127.0.0.1:9999'}):
            with self.assertRaises(ValueError):quotes.configured_proxy()
    def test_current_query_cannot_target_the_training_year(self):
        with self.assertRaises(ValueError):quotes.submit(self.owner,{**self.plan,'start_date':'2024-10-01','end_date':'2024-10-04'})
    def test_ca_bundle_with_unicode_source_is_copied_without_disabling_tls(self):
        source=Path(self.temp.name)/'测试证书.pem';source.write_bytes(b'QA trust bundle')
        with patch.dict(os.environ,{'FLI_CA_BUNDLE':str(source)}):
            destination=Path(quotes.certificate_bundle())
        self.assertEqual(destination.read_bytes(),source.read_bytes())
        str(destination).encode('ascii')
    def test_restart_records_interrupted_attempt_without_deleting_it(self):
        q=self.quote()
        with quotes.db() as c:c.execute("UPDATE flight_observations SET status='running' WHERE id=?",(q['id'],))
        quotes.recover_interrupted()
        self.assertEqual(quotes.get(self.owner,q['id'])['status'],'failed')
        self.assertEqual(len(quotes.history(self.owner,q['query'])['items']),1)


if __name__=='__main__':unittest.main()
