"""应用层：本地航空智慧营销网站与HTTP接口。"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
import argparse
import json
import mimetypes
import os
import traceback
from data_layer import BASE, DB, connect, build
from algorithm_layer import profile
from evaluation_layer import marketing
import marketing_app as mkt
import travel_planner as planner
import personal_app as personal
import personal_assistant as assistant
import flight_quotes as flights

from http.cookies import SimpleCookie, CookieError

STATIC = BASE/'web'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if '/flights/' in getattr(self,'path',''):return
        super().log_message(format,*args)
    def personal_owner(self):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except CookieError:cookie=SimpleCookie()
        token,owner,fresh=personal.session(cookie['huayi_personal'].value if 'huayi_personal' in cookie else None)
        if fresh:self.personal_cookie=f'huayi_personal={token}; Path=/api/personal/; HttpOnly; SameSite=Strict; Max-Age=2592000'
        return owner

    def send_json(self, data, status=200):
        data = flights.public_payload(data)
        raw = json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        if getattr(self,'personal_cookie',None):self.send_header('Set-Cookie',self.personal_cookie)
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.personal_cookie=None
        url = urlsplit(self.path)
        q = {k:v[0] for k,v in parse_qs(url.query,keep_blank_values=True).items()}
        try:
            if not url.path.startswith('/api/'):
                rel = url.path.lstrip('/') or 'index.html'
                if rel in ('personal','personal/'):
                    rel = 'personal/index.html'
                if rel in ('marketing','marketing/'):
                    rel = 'marketing/index.html'
                if rel == 'index.html':
                    rel = 'portal/index.html'
                target = (STATIC/rel).resolve()
                if not target.is_relative_to(STATIC.resolve()) or not target.is_file():
                    return self.send_json({'error':'文件不存在'},404)
                raw = target.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type',mimetypes.guess_type(str(target))[0] or 'application/octet-stream')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-cache')
                self.end_headers()
                self.wfile.write(raw)
                return
            with connect() as c:
                path = url.path
                if path.startswith(('/api/personal/flights/','/api/mkt/flights/')):
                    owner=self.personal_owner() if path.startswith('/api/personal/') else 'marketing'
                    tail=path.split('/flights/',1)[1]
                    if tail=='status':return self.send_json(flights.configuration())
                    if tail.startswith('queries/'):return self.send_json(flights.get(owner,tail.split('/')[1]))
                    if tail=='history':
                        plan=personal.get_plan(owner,q['plan_id']) if owner!='marketing' else q
                        return self.send_json(flights.history(owner,flights.query_for(plan,q)))
                    return self.send_json({'error':'接口不存在'},404)
                if path.startswith('/api/personal/'):
                    owner=self.personal_owner()
                    tail=path.removeprefix('/api/personal/')
                    if tail=='bootstrap':return self.send_json(personal.bootstrap(c,owner))
                    if tail=='state':return self.send_json(personal.state(owner))
                    parts=tail.split('/')
                    if len(parts)==2 and parts[0]=='plans':return self.send_json(personal.get_plan(owner,parts[1]))
                    return self.send_json({'error':'接口不存在'},404)
                if path.startswith('/api/mkt/'):
                    tail = path.removeprefix('/api/mkt/')
                    if tail == 'travel-plans':
                        return self.send_json(planner.list_plans(c,q))
                    if tail.startswith('travel-plans/'):
                        return self.send_json(planner.make_plan(c,tail.split('/')[1],q))
                    if tail == 'meta':
                        return self.send_json(mkt.metadata(c))
                    if tail == 'insights':
                        return self.send_json(mkt.build_audience(c,q))
                    if tail == 'campaigns':
                        return self.send_json({'items':mkt.campaign_list(q.get('deleted')=='true')})
                    parts = tail.split('/')
                    if parts[0]=='campaigns' and len(parts)>=2:
                        cid = parts[1]
                        if len(parts)==2:
                            return self.send_json(mkt.get_campaign(cid))
                        if parts[2]=='traveler':
                            return self.send_json(mkt.user_detail(c,cid,q['user']))
                        if parts[2]=='followup':
                            return self.send_json(mkt.followup(c,cid,q['user']))
                    if tail=='historical':
                        return self.send_json(marketing(c,None,'2024-12-31'))
                    return self.send_json({'error':'接口不存在'},404)
                if path == '/api/health':
                    return self.send_json({'application':'aerolens','status':'ok','database':DB.exists(),'host':'127.0.0.1','process_id':os.getpid(),'generation':mkt.content_generation.configuration()})
                return self.send_json({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError) as e:
            self.send_json({'error':str(e)},400)
        except Exception:
            if '/flights/' not in self.path:traceback.print_exc()
            self.send_json({'error':'服务处理失败，请查看 runtime/server.log'},500)

    def do_POST(self):
        self.personal_cookie=None
        try:
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
                return self.send_json({'error':'只允许本机同源操作'},403)
            size = int(self.headers.get('Content-Length','0'))
            if size>100000 or size<=0:
                raise ValueError('请求大小不合法')
            body = json.loads(self.rfile.read(size))
            path = urlsplit(self.path).path
            if path.startswith(('/api/personal/flights/','/api/mkt/flights/')):
                if not isinstance(body,dict):raise ValueError('请求参数须为对象')
                owner=self.personal_owner() if path.startswith('/api/personal/') else 'marketing'
                tail=path.split('/flights/',1)[1]
                if owner!='marketing':plan=personal.get_plan(owner,body['plan_id'])
                else:
                    with connect() as c:plan=planner.make_plan(c,body['user_id'],body.get('settings',{}))
                if tail=='queries':return self.send_json(flights.submit(owner,plan,body),202)
                if tail=='preview':return self.send_json(personal.preview_flight_quote(owner,plan,body) if owner!='marketing' else flights.preview(owner,plan,body))
                if tail=='apply' and owner!='marketing':return self.send_json(personal.apply_flight_quote(owner,body),201)
                if tail=='reject' and owner!='marketing':return self.send_json(personal.reject_flight_quote(owner,plan,body))
                return self.send_json({'error':'接口不存在'},404)
            if path.startswith('/api/personal/'):
                if not isinstance(body,dict):raise ValueError('请求参数须为对象')
                owner=self.personal_owner()
                tail=path.removeprefix('/api/personal/')
                with connect() as c:
                    if tail=='preferences':return self.send_json(personal.save_preferences(c,owner,body))
                    if tail=='plans':return self.send_json(personal.create_plan(c,owner,body),201)
                    if tail=='feedback/reject':return self.send_json(personal.reject_candidate(owner,body))
                    if tail=='assistant/drafts':return self.send_json(assistant.create(c,owner,body),201)
                    parts=tail.split('/')
                    if len(parts)==4 and parts[:2]==['assistant','drafts']:
                        if parts[3]=='clarify':return self.send_json(assistant.clarify(c,owner,parts[2],body))
                        if parts[3]=='confirm':return self.send_json(assistant.confirm(c,owner,parts[2],body))
                        if parts[3]=='cancel':return self.send_json(assistant.cancel(owner,parts[2],body))
                    if len(parts)==3 and parts[0]=='plans' and parts[2]=='explain':return self.send_json(personal.explain(owner,parts[1]))
                    if len(parts)==3 and parts[0]=='plans' and parts[2]=='delete':return self.send_json(personal.delete_plan(owner,parts[1],body))
                return self.send_json({'error':'接口不存在'},404)
            if path.startswith('/api/mkt/'):
                tail = path.removeprefix('/api/mkt/')
                with connect() as c:
                    if tail.startswith('travel-plans/'):
                        parts=tail.split('/')
                        plan=planner.make_plan(c,parts[1],body)
                        if len(parts)==3 and parts[2]=='explain':
                            import local_generation
                            plan['ai_explanation']=local_generation.explain_trip(plan)
                        return self.send_json(plan)
                    if tail == 'insights':
                        return self.send_json(mkt.build_audience(c,body))
                    if tail == 'traveler':
                        preview = mkt.build_audience(c,body)
                        row = next((r for r in preview['audience'] if r['user_id']==body.get('user_id')),None)
                        if not row:
                            raise ValueError('该旅客不在当前预览名单中')
                        from datetime import datetime,timedelta
                        asof = preview['settings']['asof']
                        return self.send_json({'decision':row,'profile':profile(c,row['user_id'],asof,30,14),'previous':profile(c,row['user_id'],(datetime.fromisoformat(asof)-timedelta(days=30)).strftime('%Y-%m-%d'),30,14),'asof':asof,'model':preview['model']})
                    if tail == 'campaigns':
                        return self.send_json(mkt.save_campaign(c,body),201)
                    parts = tail.split('/')
                    if parts[0]=='campaigns' and len(parts)>=3:
                        cid = parts[1]
                        if parts[2] in ('delete','restore'):
                            return self.send_json(mkt.change_campaign_visibility(cid,body,parts[2]=='delete'))
                        if parts[2]=='creatives':
                            if len(parts)==3:
                                return self.send_json(mkt.generate_creative(c,cid,body),201)
                            return self.send_json(mkt.update_creative(cid,parts[3],body))
                        if parts[2]=='audience':
                            return self.send_json(mkt.revise_audience(cid,body))
                        if parts[2]=='launch':
                            return self.send_json(mkt.launch(c,cid,body))
                        if parts[2]=='evaluate':
                            return self.send_json(mkt.evaluate_campaign(cid))
                return self.send_json({'error':'接口不存在'},404)
            return self.send_json({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError) as e:
            self.send_json({'error':str(e)},400)
        except Exception:
            if '/flights/' not in self.path:traceback.print_exc()
            self.send_json({'error':'操作失败，请查看本机服务日志'},500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    build()
    flights.recover_interrupted()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'航旅智策 本地测试版 http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
