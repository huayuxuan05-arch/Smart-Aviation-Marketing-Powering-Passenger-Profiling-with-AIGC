import json
import base64
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch,Mock
import flight_quotes as quotes


class TransportTests(unittest.TestCase):
    def flight_row(self,number,price,currency='CNY'):
        leg=[None]*32
        for i,v in {3:'SHA',6:'CAN',8:[10,0],10:[12,0],11:120,20:[2026,11,1],21:[2026,11,1],22:['MU',number]}.items():leg[i]=v
        detail=[None]*23;detail[0]='MU';detail[1]=['东方航空'];detail[2]=[leg];detail[9]=120
        token=base64.urlsafe_b64encode(b'\x1a\x05\x1a\x03'+currency.encode()).decode()
        row=[detail,[[price],token] if price is not None else None]+[None]*7
        row[8]='QA-private-booking-token'
        return row

    def wire(self,chunks):
        body=b")]}'\n\n"
        for chunk in chunks:
            payload=json.dumps([['wrb.fr',None,json.dumps(chunk,ensure_ascii=False)]],ensure_ascii=False).encode('utf-8')+b'\n'
            body+=str(len(payload)+1).encode()+b'\n'+payload
        return body

    def test_all_wire_chunks_unpriced_flights_and_foreign_quotes_survive_without_tokens(self):
        first=self.flight_row('5635',None);second=self.flight_row('5636',59593,'JPY')
        body=self.wire([[[[first]]],[[[first,second]]]])
        fake=SimpleNamespace(BASE_URL='https://example.invalid/test',client=SimpleNamespace(post=Mock(return_value=self.response(body))))
        with (patch('fli.search.SearchFlights',return_value=fake),
              patch.object(quotes,'configured_proxy',return_value='http://127.0.0.1:1'),
              patch('fx_rates.convert',return_value={'amount_cny':2524.04,'original_currency':'JPY','original_amount':59593})):
            observed={'observed_at':quotes.now()};rows=quotes._google_request(SimpleNamespace(encode=lambda:'QA filters'),observed)
        self.assertEqual(observed['response_chunks'],2);self.assertEqual(observed['raw_flight_rows'],3)
        self.assertEqual(len(rows),2);self.assertEqual(rows[0][1]['segments'][0]['flight_number'],'MU5635')
        self.assertIsNone(rows[0][1]['price_cny']);self.assertEqual(rows[1][1]['price_cny'],2524.04)
        self.assertEqual(rows[1][1]['original_currency'],'JPY')
        self.assertNotIn('QA-private-booking-token',json.dumps(observed))
        self.assertEqual(rows[1][2].raw,{})

    def response(self,body):
        return SimpleNamespace(status_code=200,headers={'content-type':'application/json; charset=utf-8'},
            content=body,raise_for_status=lambda:None)

    def invoke(self,body,decoded,filters=None):
        observed=[];response=self.response(body)
        post=Mock(return_value=response)
        fake=SimpleNamespace(BASE_URL='https://example.invalid/test',client=SimpleNamespace(post=post))
        with (patch('fli.search.SearchFlights',return_value=fake),
              patch('fli.search._wire.iter_wrb_chunks',return_value=[decoded] if decoded is not None else []) as parser,
              patch.object(quotes,'configured_proxy',return_value='http://127.0.0.1:1')):
            try:quotes._search_leg('SHA','CAN',date(2026,11,1),1,'ECONOMY',observed,filters)
            except RuntimeError:pass
            parser.assert_called_once_with(body)
        self.last_post=post.call_args.kwargs
        return observed[0]

    def test_airline_constraints_are_sent_to_source_not_only_postfiltered(self):
        self.invoke(b'test wire',[],{'required_airlines':['3U'],'excluded_airlines':['9C']})
        self.assertIn('3U',self.last_post['data']);self.assertIn('9C',self.last_post['data'])
        self.assertEqual(self.last_post['proxy'],'http://127.0.0.1:1')
        self.assertTrue(self.last_post['verify'])

    def test_http_200_rpc_error_is_not_a_valid_empty_flight_result(self):
        body=b")]}'\n\n"+json.dumps([['wrb.fr',None,None,None,None,[13,None,[]]]]).encode()
        row=self.invoke(body,None)
        self.assertEqual(row['status'],'failed');self.assertEqual(row['error_stage'],'upstream_rpc')
        self.assertEqual(row['upstream_rpc_code'],13);self.assertEqual(row['response_meta']['http_status'],200)
        self.assertNotIn('raw_response',row);self.assertEqual(row['options'],[])
        self.assertEqual(quotes.result_status({'options':[],'query_quality':{'incomplete':True}}),'failed')

    def test_valid_empty_payload_stays_distinct_from_rpc_failure(self):
        row=self.invoke(b'test wire bytes',[])
        self.assertEqual(row['status'],'empty');self.assertNotIn('error_stage',row)
        self.assertEqual(quotes.result_status({'options':[],'query_quality':{'incomplete':False}}),'empty')

    def test_http_200_malformed_payload_is_classified_as_decode_error(self):
        row=self.invoke(b'<invalid>test</invalid>',None)
        self.assertEqual(row['status'],'failed');self.assertEqual(row['error_stage'],'wire_decode')


if __name__=='__main__':unittest.main()
