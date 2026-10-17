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
import real_travelers as real
import accounts

from http.cookies import SimpleCookie, CookieError

STATIC = BASE/'web'


class Handler(BaseHTTPRequestHandler):
    def log_message(self,format,*args):
        if '/flights/' in getattr(self,'path',''):return
        super().log_message(format,*args)
    def personal_owner(self):
        if accounts.required():
            user=accounts.resolve(self.login_token('personal'),'traveler')
            if not user:raise PermissionError('请先登录个人账号')
            return user['owner']
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except CookieError:cookie=SimpleCookie()
        token,owner,fresh=personal.session(cookie['huayi_personal'].value if 'huayi_personal' in cookie else None)
        if fresh:self.personal_cookie=f'huayi_personal={token}; Path=/api/personal/; HttpOnly; SameSite=Strict; Max-Age=2592000'
        return owner

    def login_token(self,area):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except CookieError:return None
        name='huayi_personal' if area=='personal' else 'huayi_marketing'
        return cookie[name].value if name in cookie else None

    def auth_route(self,path,body=None):
        area='personal' if path.startswith('/api/personal/') else 'mkt'
        prefix=f'/api/{area}/auth/'
        if not path.startswith(prefix):return False
        action=path.removeprefix(prefix);role='traveler' if area=='personal' else 'staff'
        token=self.login_token(area)
        if body is None and action=='status':
            user=accounts.resolve(token,role) if accounts.required() else None
            self.send_json({'enabled':accounts.required(),'authenticated':bool(user),
                'user':{k:user[k] for k in ('username','role','user_id')} if user else None})
            return True
        if not isinstance(body,dict):raise ValueError('不支持的登录操作')
        if action=='register' and area=='personal':
            # A new account gets a fresh identity; never adopt the prior browser user's profile.
            owner=accounts.create_account(body.get('username'),body.get('password'));token=accounts.issue(owner)
        elif action=='login':token=accounts.login(body,role)
        elif action=='logout':accounts.logout(token);token=''
        else:raise ValueError('不支持的登录操作')
        name='huayi_personal' if area=='personal' else 'huayi_marketing'
        self.personal_cookie=f'{name}={token}; Path=/api/{area}/; HttpOnly; SameSite=Strict; Max-Age={accounts.SESSION_SECONDS if token else 0}'
        self.send_json({'authenticated':bool(token)})
        return True

    def require_marketing_login(self,path):
        if path.startswith('/api/mkt/') and accounts.required() and not accounts.resolve(self.login_token('mkt'),'staff'):
            raise PermissionError('请登录营销管理账号')

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
            if self.auth_route(url.path):return
            self.require_marketing_login(url.path)
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
                if path=='/api/mkt/data-source':return self.send_json({'mode':real.mode()})
                if path.startswith('/api/mkt/real/'):
                    tail=path.removeprefix('/api/mkt/real/')
                    if tail=='dashboard':return self.send_json(real.dashboard(q))
                    if tail=='export':return self.send_json(real.export_case(q))
                    if tail.startswith('campaigns/'):
                        import real_marketing_workflow as workflow
                        parts=tail.split('/')
                        if len(parts)==3 and parts[2]=='observations':return self.send_json(workflow.observe(parts[1]))
                        return self.send_json(workflow.get(parts[1]))
                    if tail.startswith('forecasts/'):
                        import real_forecast
                        return self.send_json(real_forecast.evaluate(tail.split('/')[1]))
                    if tail.startswith('profiles/'):return self.send_json(real.profile(tail.split('/')[1]))
                    if tail.startswith('plans/'):return self.send_json(real.plan(tail.split('/')[1]))
                    return self.send_json({'error':'接口不存在'},404)
                if path.startswith(('/api/personal/flights/','/api/mkt/flights/')):
                    owner=self.personal_owner() if path.startswith('/api/personal/') else 'marketing'
                    tail=path.split('/flights/',1)[1]
                    if tail=='status':return self.send_json(flights.configuration())
                    if tail.startswith('queries/'):return self.send_json(flights.get(owner,tail.split('/')[1]))
                    if tail=='history':
                        plan=personal.get_plan(owner,q['plan_id']) if owner!='marketing' else real.plan(q['user_id']) if real.mode()=='real' else q
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
                    if real.mode()=='real':return self.send_json({'error':'正式营销端仅处理已同意共享的真实旅客，请使用真实客群接口'},400)
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
        except PermissionError as e:self.send_json({'error':str(e)},401)
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
            if self.auth_route(path,body):return
            self.require_marketing_login(path)
            if path.startswith(('/api/personal/flights/','/api/mkt/flights/')):
                if not isinstance(body,dict):raise ValueError('请求参数须为对象')
                owner=self.personal_owner() if path.startswith('/api/personal/') else 'marketing'
                tail=path.split('/flights/',1)[1]
                if owner!='marketing':
                    plan=personal.get_plan(owner,body['plan_id'])
                    if plan['profile_revision']!=personal.state(owner)['revision']:raise ValueError('偏好标签已更新，请按当前标签生成新方案后搜索')
                else:
                    if real.mode()=='real':plan=real.plan(body['user_id'])
                    else:
                        with connect() as c:plan=planner.make_plan(c,body['user_id'],body.get('settings',{}))
                if tail=='queries':
                    try:result=flights.submit(owner,plan,body)
                    except ValueError:
                        if owner!='marketing':real.record_search_request(owner,plan)
                        raise
                    if owner!='marketing':
                        real.record_search_request(owner,plan,result)
                        if result['status'] in ('success','empty','flights_only'):
                            real.record_flight_result(owner,result['id'],result['query'],result['status'],len(result.get('options',[])),plan['profile_revision'])
                        with personal.db() as pc:real.record_event(pc,owner,'flight_search',plan['destination'])
                    return self.send_json(result,202)
                if tail=='returns':return self.send_json(flights.query_returns(owner,plan,body))
                if tail=='preview':return self.send_json(personal.preview_flight_quote(owner,plan,body) if owner!='marketing' else flights.preview(owner,plan,body))
                if tail=='apply' and owner!='marketing':return self.send_json(personal.apply_flight_quote(owner,body),201)
                if tail=='reject' and owner!='marketing':return self.send_json(personal.reject_flight_quote(owner,plan,body))
                return self.send_json({'error':'接口不存在'},404)
            if path.startswith('/api/mkt/real/'):
                tail=path.removeprefix('/api/mkt/real/')
                if tail=='campaigns':return self.send_json(real.create_campaign(body),201)
                if tail=='analysis':return self.send_json(real.decision_summary(body))
                parts=tail.split('/')
                if len(parts)==3 and parts[0]=='campaigns':
                    import real_marketing_workflow as workflow
                    if parts[2]=='materials':return self.send_json(workflow.generate(parts[1],body))
                    if parts[2]=='review':return self.send_json(workflow.review(parts[1],body))
                    if parts[2]=='package':return self.send_json(workflow.package(parts[1],body))
                    if parts[2]=='forecast':
                        import real_forecast
                        return self.send_json(real_forecast.freeze(parts[1]),201)
                return self.send_json({'error':'接口不存在'},404)
            if path.startswith('/api/personal/'):
                if not isinstance(body,dict):raise ValueError('请求参数须为对象')
                owner=self.personal_owner()
                tail=path.removeprefix('/api/personal/')
                if tail=='collection':return self.send_json(real.set_consent(owner,body))
                if tail=='activity':return self.send_json(real.record_activity(owner,body))
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
                    if len(parts)==3 and parts[0]=='plans' and parts[2]=='feedback':
                        import traveler_feedback
                        return self.send_json(traveler_feedback.submit(owner,parts[1],body),201)
                return self.send_json({'error':'接口不存在'},404)
            if path.startswith('/api/mkt/'):
                if real.mode()=='real':return self.send_json({'error':'正式营销端仅处理真实旅客；不会使用模拟名单或发送外部营销信息'},400)
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
        except PermissionError as e:self.send_json({'error':str(e)},401)
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
    if accounts.required():accounts.ensure_admin()
    flights.recover_interrupted()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'航旅智策 本地测试版 http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
