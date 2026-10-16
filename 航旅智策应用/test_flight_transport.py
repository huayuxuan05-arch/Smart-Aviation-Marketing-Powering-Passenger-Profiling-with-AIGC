import json
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import flight_quotes as quotes


class TransportTests(unittest.TestCase):
    def response(self,body):
        return SimpleNamespace(status_code=200,headers={'content-type':'application/json; charset=utf-8'},
            content=body,raise_for_status=lambda:None)

    def invoke(self,body,decoded):
        observed=[];response=self.response(body)
        fake=SimpleNamespace(BASE_URL='https://example.invalid/test',client=SimpleNamespace(post=lambda **kwargs:response))
        with (patch('fli.search.SearchFlights',return_value=fake),
              patch('fli.search._wire.parse_first_wrb_payload',return_value=decoded) as parser,
              patch.object(quotes,'configured_proxy',return_value='http://127.0.0.1:1')):
            try:quotes._search_leg('SHA','CAN',date(2026,11,1),1,'ECONOMY',observed)
            except RuntimeError:pass
            parser.assert_called_once_with(body)
        return observed[0]

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
