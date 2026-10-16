"""Isolated third-party fixtures: never call the real service or use its key."""
import copy,json,os,ssl,unittest
from datetime import datetime,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch,Mock
from urllib.error import HTTPError
import flight_quotes as quotes
import flight_provider_settings as config
import serpapi_quotes as provider
import personal_app as personal
import fx_rates
from data_layer import connect,CST

QA_KEY='qa_serpapi_fixture_key_'+'a'*40


def raw_leg(day,number='MU5635',origin='SHA',destination='XMN',price=59593,hour=10):
    return {'flights':[{'flight_number':number[:2]+' '+number[2:],'airline':'QA airline',
        'departure_airport':{'id':origin,'time':day+f' {hour:02d}:00'},
        'arrival_airport':{'id':destination,'time':day+f' {hour+2:02d}:00'},'duration':120}],
        'total_duration':120,'type':'Round trip','price':price,'departure_token':'QA_PRIVATE_TOKEN_'+number}


def response_fixture(params):
    common={'search_metadata':{'status':'Success'},'search_parameters':{'currency':params['currency']}}
    if params.get('selected_flights_json'):
        chosen=json.loads(params['selected_flights_json']);rows=[]
        for label in ('outbound','return'):
            segment=chosen[label][0]
            rows.append(raw_leg(segment['date'],segment['flight_number'],segment['departure_id'],segment['arrival_id'],hour=10 if label=='outbound' else 15 if segment['flight_number']=='MU5664' else 11))
        return {**common,'selected_flights':rows,'booking_options':[{'together':{'price':59593,'book_with':'QA supplier','booking_request':{'post_data':'QA_PRIVATE_POST'}}}]}
    if params.get('departure_token'):
        return {**common,'best_flights':[raw_leg(params['return_date'],'MU5636','XMN','SHA',hour=11)],
            'other_flights':[raw_leg(params['return_date'],'MU5664','XMN','SHA',None,hour=15)]}
    return {**common,'best_flights':[raw_leg(params['outbound_date'])],
        'other_flights':[raw_leg(params['outbound_date'],('9C' if i%2 else 'MU')+str(5700+i),price=None if i==0 else 60000+i) for i in range(24)]}


class ThirdPartyTests(unittest.TestCase):
    def setUp(self):
        folder=Path(__file__).parent/'runtime/tmp';folder.mkdir(parents=True,exist_ok=True)
        self.tmp=TemporaryDirectory(dir=folder);self.root=Path(self.tmp.name)
        self.patches=[patch.object(config,'CONFIG',self.root/'config.json'),patch.object(quotes,'RUNTIME',self.root),
            patch.object(personal,'RUNTIME',self.root),patch.dict(os.environ,{'AEROLENS_FLIGHT_PROVIDER':'serpapi','SERPAPI_API_KEY':QA_KEY}),
            patch.object(fx_rates,'snapshot',return_value={'rates':{'CNY':'7.4993','JPY':'177.06'},'rate_date':datetime.now(CST).date().isoformat(),'source':fx_rates.SOURCE})]
        for p in self.patches:p.start()
        config.CONFIG.write_text(json.dumps({'provider':'serpapi','currency':'JPY','country':'jp','language':'ja'}),encoding='utf-8')
        self.query={'origin':'上海','destinations':['厦门'],'departure':'2026-12-30','return_date':'2027-01-03','adults':1,
            'cabin_class':'ECONOMY','max_stops':0,'max_layover_hours':6,'date_flex_days':0,'provider':'serpapi',
            'provider_locale':{'currency':'JPY','country':'jp','language':'ja'},'required_airlines':[],'excluded_airlines':[]}
    def tearDown(self):
        for p in reversed(self.patches):p.stop()
        self.tmp.cleanup()

    def test_params_match_google_region_expand_airports_and_request_fresh_hidden_results(self):
        params=provider.shopping_params(self.query)
        self.assertEqual(params['departure_id'],'PVG,SHA');self.assertEqual(params['arrival_id'],'XMN')
        self.assertEqual(params['currency'],'JPY');self.assertEqual(params['gl'],'jp');self.assertEqual(params['hl'],'ja')
        for key in ('no_cache','show_hidden','deep_search'):self.assertEqual(params[key],'true')
        self.assertEqual(params['type'],1);self.assertEqual(params['stops'],0)
        self.assertNotIn('api_key',params);self.assertNotIn('include_airlines',params)

    def test_inventory_returns_and_booking_preserve_all_rows_and_actual_roundtrip_amount(self):
        with patch.object(provider,'request',side_effect=response_fixture):
            first=provider.initial(self.query)
            out=next(v for v in first['catalog']['outbound'] if v['segments'][0]['flight_number']=='MU5635')
            back=provider.returns(self.query,out)
            value=provider.quote_selected(self.query,out,back['catalog'][1],back['catalog'])
        self.assertEqual(len(first['catalog']['outbound']),25);self.assertEqual(out['price_cny'],2524.04)
        self.assertEqual(len(back['catalog']),2);self.assertEqual(len(back['options']),1)
        self.assertEqual(back['options'][0]['total_price_cny'],2524.04)
        self.assertIsNone(back['options'][0]['outbound']['price_cny']);self.assertIsNone(back['options'][0]['inbound']['price_cny'])
        self.assertEqual(value['options'][0]['total_price_cny'],2524.04)
        public=json.dumps({'first':first,'back':back,'booking':value})
        self.assertNotIn(QA_KEY,public);self.assertNotIn('QA_PRIVATE',public)

    def test_selected_flights_mismatch_or_partial_vendor_prices_cannot_become_total(self):
        with patch.object(provider,'request',side_effect=response_fixture):
            first=provider.initial(self.query);out=next(l for l in first['catalog']['outbound'] if l['segments'][0]['flight_number']=='MU5635')
            back=provider.returns(self.query,out)
        def wrong(params):
            data=response_fixture(params);data['selected_flights'][1]['flights'][0]['flight_number']='MU 9999';return data
        with patch.object(provider,'request',side_effect=wrong):
            with self.assertRaisesRegex(ValueError,'不一致'):provider.quote_selected(self.query,out,back['catalog'][1],back['catalog'])
        def partial(params):
            data=response_fixture(params);data['booking_options']=[{'departing':{'price':100},'returning':{'price':None}}];return data
        with patch.object(provider,'request',side_effect=partial):
            result=provider.quote_selected(self.query,out,back['catalog'][1],back['catalog'])
        self.assertEqual(result['options'],[])

    def test_proxy_tls_no_cache_and_short_duplicate_cache(self):
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self,limit):return json.dumps(response_fixture(provider.shopping_params(self.query))).encode()
        response=Response();response.query=self.query
        opener=Mock();opener.open.return_value=response
        with patch('urllib.request.build_opener',return_value=opener) as build,patch.object(provider,'_reserve') as reserve:
            first=provider.request(provider.shopping_params(self.query));second=provider.request(provider.shopping_params(self.query))
        self.assertEqual(first,second);self.assertEqual(opener.open.call_count,1);reserve.assert_called_once()
        proxy_handler,tls_handler=build.call_args.args
        self.assertEqual(proxy_handler.proxies,{'http':quotes.configured_proxy(),'https':quotes.configured_proxy()})
        self.assertEqual(tls_handler._context.verify_mode,ssl.CERT_REQUIRED)
        self.assertIn('no_cache=true',opener.open.call_args.args[0].full_url)

    def test_private_error_messages_are_never_echoed_and_no_key_never_calls_service(self):
        opener=Mock();opener.open.side_effect=HTTPError('https://example.invalid/?api_key='+QA_KEY,401,QA_KEY,None,None)
        with patch('urllib.request.build_opener',return_value=opener):
            with self.assertRaises(ValueError) as caught:provider.request(provider.shopping_params(self.query))
        self.assertNotIn(QA_KEY,str(caught.exception));self.assertNotIn('api_key',str(caught.exception))
        with patch.dict(os.environ,{'SERPAPI_API_KEY':''}),patch('urllib.request.build_opener') as build:
            with self.assertRaisesRegex(ValueError,'配置'):provider.request(provider.shopping_params(self.query))
            build.assert_not_called()

    def test_local_usage_caps_reserve_before_calls_and_do_not_auto_increase(self):
        settings={**config.settings(),'hourly_limit':2,'monthly_limit':2}
        provider._reserve(settings);provider._reserve(settings)
        with self.assertRaisesRegex(ValueError,'额度'):provider._reserve(settings)

    @unittest.skipUnless(os.name=='nt','Windows DPAPI only')
    def test_key_is_encrypted_on_disk_and_public_configuration_contains_no_secret(self):
        config.save_key(QA_KEY)
        self.assertNotIn(QA_KEY,config.CONFIG.read_text(encoding='utf-8'))
        with patch.dict(os.environ,{'SERPAPI_API_KEY':''}):self.assertEqual(config.api_key(),QA_KEY)
        self.assertNotIn(QA_KEY,json.dumps(quotes.configuration()))

    def test_backend_switch_ownership_native_budget_and_booking_choice_indices(self):
        with connect() as source:
            _,owner,_=personal.session();_,other,_=personal.session()
            plan=personal.create_plan(source,owner,{'preferences':{**personal.defaults(),'origin':'上海','destination':'厦门',
                'start_date':'2026-12-30','days':5,'trip_budget':6000,'airfare_cap':None}})['plan']
        with patch.object(provider,'request',side_effect=response_fixture),patch.object(quotes._pool,'submit',side_effect=lambda f,*a:f(*a)):
            observation=quotes.submit(owner,plan)
            self.assertEqual(observation['query']['provider'],'serpapi')
            self.assertEqual(observation['source'],provider.SOURCE)
            out=next(l for l in observation['catalog']['outbound'] if l['segments'][0]['flight_number']=='MU5635')
            body={'query_id':observation['id'],'outbound_id':out['catalog_id']}
            with self.assertRaises(ValueError):quotes.query_returns(other,plan,body)
            result=quotes.query_returns(owner,plan,body)
            self.assertEqual(result['returns'][0]['option_index'],0)
            priced=quotes.query_returns(owner,plan,{**body,'inbound_id':result['returns'][1]['catalog_id']})
            self.assertEqual(priced['returns'][1]['option_index'],1)
            preview=personal.preview_flight_quote(owner,plan,{'query_id':observation['id'],'option_index':1})
            self.assertEqual(preview['budget']['components'][0]['name'],'往返航空');self.assertEqual(preview['budget']['components'][0]['value'],2524.04)
            self.assertEqual(len(personal.state(owner)['plans']),1)
            same=quotes.submit(owner,plan);self.assertEqual(same['id'],observation['id'])


if __name__=='__main__':unittest.main()
