"""Explicit fixtures for inventory, native totals, lazy booking and account isolation."""
import copy
import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from types import SimpleNamespace
import flight_catalog as catalog
import fli_roundtrip as native
import flight_quotes as quotes
import flight_ranking as ranking
import fx_rates
from test_flight_quotes import FlightQuoteTests,fixture_result


def native_fixture(query):
    out=fixture_result(query)['options'][0]['outbound']
    out.update(origin_airport='SHA',destination_airport='CAN',price_basis='native_roundtrip_from')
    legs=[]
    for i in range(25):
        leg=copy.deepcopy(out);code='MU' if i%2==0 else '9C'
        leg['segments'][0].update(flight_number=code+str(5600+i),airline=code,airline_zh='东方航空' if code=='MU' else '春秋航空')
        leg['price_cny']=None if i==0 else 2200+i*10
        legs.append(leg)
    return {'source':'QA native roundtrip fixture / not live','native_roundtrip':True,
        'fare_basis':'QA 往返总价夹具，不是真实报价','options':[],
        'catalog':{'outbound':catalog.deduplicate(legs),'inbound':[]},'coverage':{'partial':False}}


def returns_fixture(query,outbound):
    leg=fixture_result(query)['options'][0]['inbound'];leg.update(origin_airport='CAN',destination_airport='SHA')
    leg['segments'][0].update(flight_number='MU5636',airline='MU',airline_zh='东方航空')
    leg['price_cny']=2524.04;leg['price_basis']='native_roundtrip_total';leg['catalog_id']=catalog.catalog_id(leg)
    noquote=copy.deepcopy(leg);noquote['segments'][0]['flight_number']='MU5664';noquote.update(price_cny=None,catalog_id=catalog.catalog_id(noquote))
    back=copy.deepcopy(leg);out=copy.deepcopy(outbound);out['price_cny']=back['price_cny']=None
    option={'outbound':out,'inbound':back,'quote_kind':'native_roundtrip','total_price_cny':2524.04,
        'original_total':59593,'original_currency':'JPY','fare_conversion':{'rate_date':'QA','rate_source':'QA'}}
    return {'catalog':[leg,noquote],'options':[option],'partial':False,'observed_at':quotes.now()}


class NativeFlowTests(FlightQuoteTests):
    # Reuse isolated DB/account setup, without repeating the parent test methods.
    def quote(self):
        with patch.object(quotes,'_search',side_effect=native_fixture):return quotes.submit(self.owner,self.plan,{'adults':2})

    def test_inventory_is_complete_before_preferences_and_not_price_history(self):
        self.plan['preference_constraints'].update(required_airlines=['MU'],excluded_airlines=['9C'])
        q=self.quote();self.assertEqual(q['status'],'flights_only');self.assertEqual(len(q['catalog']['outbound']),25)
        self.assertEqual(quotes.history(self.owner,q['query'])['items'],[])
        with self.assertRaises(ValueError):quotes.get(self.other,q['id'])

    def test_native_total_is_not_split_or_added_twice_and_saved_choice_is_valid(self):
        self.plan['budget']['one_way_airfare_cap']=None
        q=self.quote();out=q['catalog']['outbound'][0]
        with patch.object(native,'returns',side_effect=returns_fixture):
            result=quotes.query_returns(self.owner,self.plan,{'query_id':q['id'],'outbound_id':out['catalog_id']})
        self.assertEqual(result['returns'][0]['option_index'],0);self.assertNotIn('option_index',result['returns'][1])
        option=result['observation']['options'][0]
        self.assertIsNone(option['outbound']['price_cny']);self.assertIsNone(option['inbound']['price_cny'])
        self.assertEqual(option['total_price_cny'],2524.04)
        preview=personal_preview=self._personal_preview(q['id'])
        amounts=[c for c in preview['budget']['components'] if c['name'] in ('去程航空','返程航空','往返航空')]
        self.assertEqual(amounts,[{'name':'往返航空','value':1262.02,'basis':'Google所选航班往返总价按成人数均摊；未提供单程拆价'}])
        self.assertEqual(personal_preview['candidate_constraints']['one_way_budget_gap'],None)
        from travel_choice_evidence import candidate_features
        features=candidate_features(self.plan,option,2)
        self.assertIsNone(features['outbound_per_adult'])
        self.assertEqual(features['roundtrip_trip_cap_share'],1262.02/2000)

    def _personal_preview(self,ident):
        import personal_app
        return personal_app.preview_flight_quote(self.owner,self.plan,{'query_id':ident,'option_index':0})

    def test_wrong_outbound_or_foreign_query_cannot_resolve_returns(self):
        q=self.quote();body={'query_id':q['id'],'outbound_id':'forged'}
        with self.assertRaises(ValueError):quotes.query_returns(self.owner,self.plan,body)
        body['outbound_id']=q['catalog']['outbound'][0]['catalog_id']
        with self.assertRaises(ValueError):quotes.query_returns(self.other,self.plan,body)
        modified=copy.deepcopy(self.plan);modified['preference_constraints']['required_airlines']=['CA']
        with self.assertRaises(ValueError):quotes.query_returns(self.owner,modified,body)

    def test_unknown_one_way_cap_cannot_be_asserted_as_within_strict_budget(self):
        q=self.quote();o=returns_fixture(q['query'],q['catalog']['outbound'][0])['options'][0]
        query={**q['query'],'budget_policy':'只看预算内','airfare_cap':1500,'trip_budget':100000}
        self.assertEqual(ranking.rank([o],query),[])
        query.update(budget_policy='预算优先');self.assertEqual(len(ranking.rank([o],query)),1)
        query.update(max_stops=0);o['inbound']['segments'].append(copy.deepcopy(o['inbound']['segments'][0]))
        self.assertEqual(ranking.rank([o],query),[])

    def test_new_outbound_appends_choices_without_relabeling_previous_exposure(self):
        import personal_app
        import travel_choice_evidence
        q=self.quote();legs=q['catalog']['outbound']
        with patch.object(native,'returns',side_effect=returns_fixture):
            quotes.query_returns(self.owner,self.plan,{'query_id':q['id'],'outbound_id':legs[0]['catalog_id']})
            first=personal_app.preview_flight_quote(self.owner,self.plan,{'query_id':q['id'],'option_index':0})
            result=quotes.query_returns(self.owner,self.plan,{'query_id':q['id'],'outbound_id':legs[1]['catalog_id']})
            second=personal_app.preview_flight_quote(self.owner,self.plan,{'query_id':q['id'],'option_index':1})
        self.assertEqual(first['choice_request_id'],second['choice_request_id'])
        self.assertEqual(result['returns'][0]['option_index'],1)
        self.assertEqual(len(result['observation']['options']),2)
        with personal_app.db() as c:
            travel_choice_evidence.explicit_rejection(c,self.owner,second['choice_request_id'],1)
            count=__import__('json').loads(c.execute('SELECT candidates FROM itinerary_requests WHERE id=?',(second['choice_request_id'],)).fetchone()[0])
        self.assertEqual([candidate['index'] for candidate in count],[0,1])

    def test_native_filters_group_both_shanghai_airports_and_keep_roundtrip_dates(self):
        q=quotes.query_for(self.plan,{'adults':2});f=native.filters(q)
        self.assertEqual(len(f.flight_segments),2);self.assertTrue(f.show_all_results)
        self.assertEqual(f.passenger_info.adults,2)
        self.assertEqual(f.flight_segments[1].travel_date,self.plan['end_date'])
        names={a[0].name for a in f.flight_segments[0].departure_airport}
        self.assertEqual(names,{'SHA','PVG'})
        out=native_fixture(q)['catalog']['outbound'][0];f=native.filters(q,out)
        self.assertEqual(f.flight_segments[0].selected_flight.legs[0].flight_number,out['segments'][0]['flight_number'][2:])

    def test_booking_pair_uses_returned_token_and_proxy_without_persisting_tokens(self):
        q=quotes.query_for(self.plan);out=native_fixture(q)['catalog']['outbound'][0]
        ret=returns_fixture(q,out)['catalog'][1];filters=native.filters(q,out)
        fake_return=filters.flight_segments[0].selected_flight.model_copy(update={'booking_token':'QA-private-token'})
        response=SimpleNamespace(content=b'QA wire',raise_for_status=lambda:None)
        post=__import__('unittest.mock',fromlist=['Mock']).Mock(return_value=response)
        client=SimpleNamespace(BOOKING_URL='https://example.invalid/booking',client=SimpleNamespace(post=post),_encode_booking_payload=lambda token,f:'QA encoded')
        with (patch.object(quotes,'_google_request',return_value=[(fake_return,ret,None)]),
              patch('fli.search.SearchFlights',return_value=client),patch('fli.search._wire.iter_wrb_chunks',return_value=[[]]),
              patch('fli.search._decoders.parse_booking_chunk',return_value=[SimpleNamespace(price=59593,currency='JPY')]),
              patch.object(fx_rates,'convert',return_value={'amount_cny':2524.04,'original_amount':59593,'original_currency':'JPY'})):
            value=native.quote_selected(q,out,ret,[ret])
        self.assertEqual(value['options'][0]['total_price_cny'],2524.04)
        self.assertEqual(post.call_args.kwargs['proxy'],'http://127.0.0.1:7897');self.assertTrue(post.call_args.kwargs['verify'])
        self.assertNotIn('QA-private-token',str(value))


# Parent methods exercise the legacy fixture through their own quote(), which this
# subclass intentionally replaces. Keep only new native-flow tests in this class.
for _name in list(FlightQuoteTests.__dict__):
    if _name.startswith('test_') and _name not in NativeFlowTests.__dict__:setattr(NativeFlowTests,_name,None)


class FxTests(unittest.TestCase):
    def test_decimal_cross_rate_and_bad_amounts(self):
        data={'rates':{'CNY':'7.7919','JPY':'183.968'},'rate_date':datetime.now(fx_rates.CST).date().isoformat(),'source':fx_rates.SOURCE}
        with patch.object(fx_rates,'snapshot',return_value=data):
            value=fx_rates.convert(59593,'JPY');self.assertEqual(value['amount_cny'],2524.04)
            self.assertEqual(value['rate_source'],fx_rates.SOURCE)
            with self.assertRaises(ValueError):fx_rates.convert(100,'XYZ')
        self.assertEqual(fx_rates.convert(99.999,'CNY')['amount_cny'],100)
        for amount in (0,-1,'NaN','Infinity',None):
            with self.assertRaises(ValueError):fx_rates.convert(amount,'CNY')

    def test_stale_future_negative_rate_data_are_rejected(self):
        today=datetime.now(fx_rates.CST).date()
        for shift in (-8,1):
            with self.assertRaises(ValueError):fx_rates.validate({'rate_date':(today+timedelta(days=shift)).isoformat(),'rates':{'CNY':'7'}})
        for rate in ('NaN','-2','0'):
            with self.assertRaises(ValueError):fx_rates.validate({'rate_date':today.isoformat(),'rates':{'CNY':rate}})


if __name__=='__main__':unittest.main()
