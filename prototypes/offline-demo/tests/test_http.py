import json
import threading
import unittest
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

from app.server import handler_for
from app.service import Service


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = Service()
        cls.server = ThreadingHTTPServer(('127.0.0.1',0), handler_for(cls.service))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.service.db.close()

    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        try:
            connection.request(method,path,body=body,headers=headers or {})
            response = connection.getresponse()
            return response.status, response.read(), dict(response.getheaders())
        finally:
            connection.close()

    def test_home_and_profiles(self):
        code, body, headers = self.request('GET','/')
        self.assertEqual(code,200)
        self.assertIn('航旅智绘',body.decode())
        self.assertIn('Content-Security-Policy',headers)
        code, body, _ = self.request('GET','/api/profiles')
        self.assertEqual(code,200)
        self.assertEqual(len(json.loads(body)),120)

    def test_path_traversal_is_not_served(self):
        code, _, _ = self.request('GET','/../app/server.py')
        self.assertEqual(code,404)

    def test_bad_json_and_cross_origin_requests_rejected(self):
        for body in ['[1]', '{bad', '{"passenger_id": null}']:
            code, _, _ = self.request('POST','/api/campaigns',body,{'Content-Type':'application/json'})
            self.assertEqual(code,400)
        code, _, _ = self.request('POST','/api/campaigns','{}',{'Content-Type':'application/json','Origin':'https://example.com'})
        self.assertEqual(code,403)

    def test_full_workflow_over_http(self):
        code, body, _ = self.request('POST','/api/campaigns',json.dumps({'passenger_id':'SYN-0002'}),{'Content-Type':'application/json'})
        self.assertEqual(code,201)
        cid = json.loads(body)['id']
        for action in ['approve','simulate']:
            code, _, _ = self.request('POST',f'/api/campaigns/{cid}/{action}','{}',{'Content-Type':'application/json'})
            self.assertEqual(code,200)
