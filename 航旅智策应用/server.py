"""应用层：本机旅客网站、独立研究工作台与HTTP接口。"""
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit,parse_qs
from pathlib import Path
import argparse
import json
import mimetypes
import sqlite3
import traceback
from collections import Counter
from data_layer import BASE, DB, connect, build
from algorithm_layer import profile, flight_search, HOLIDAYS
from evaluation_layer import evaluate,marketing
import aigc_layer as aigc
import traveler_layer as travel
import marketing_app as mkt
from http.cookies import SimpleCookie, CookieError

STATIC = BASE/'web'


class Handler(BaseHTTPRequestHandler):
    def traveler_id(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get('Cookie',''))
        except CookieError:
            cookie = SimpleCookie()
        token, fresh = travel.session(cookie['aerolens_traveler'].value if 'aerolens_traveler' in cookie else None)
        if fresh:
            self.travel_cookie = f'aerolens_traveler={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=2592000'
        return token

    def send_json(self, data, status=200):
        raw = json.dumps(data,ensure_ascii=False,allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store')
        if getattr(self,'travel_cookie',None):
            self.send_header('Set-Cookie',self.travel_cookie)
        self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self.travel_cookie = None
        url = urlsplit(self.path)
        q = {k:v[0] for k,v in parse_qs(url.query,keep_blank_values=True).items()}
        try:
            if not url.path.startswith('/api/'):
                rel = url.path.lstrip('/') or 'index.html'
                if rel in ('research','research/'):
                    rel = 'research/index.html'
                if rel in ('traveler','traveler/'):
                    rel = 'traveler/index.html'
                if rel in ('marketing','marketing/') or rel == 'index.html':
                    rel = 'marketing/index.html'
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
                if path.startswith('/api/mkt/'):
                    tail = path.removeprefix('/api/mkt/')
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
                if path.startswith('/api/travel/'):
                    uid = self.traveler_id()
                    if path == '/api/travel/bootstrap':
                        cities = [r[0] for r in c.execute('SELECT DISTINCT 出发城市 FROM flights ORDER BY 出发城市')]
                        return self.send_json({'state':travel.state(uid),'themes':travel.THEMES,'catalog':list(travel.DESTINATIONS.values()),'cities':cities})
                    if path == '/api/travel/state':
                        return self.send_json(travel.state(uid))
                    if path == '/api/travel/discover':
                        return self.send_json(travel.discover(c,uid,q))
                    if path == '/api/travel/flights':
                        return self.send_json(travel.search_flights(c,uid,q))
                    return self.send_json({'error':'接口不存在'},404)
                if path == '/api/health':
                    return self.send_json({'application':'aerolens','status':'ok','database':DB.exists(),'host':'127.0.0.1'})
                if path == '/api/meta':
                    manifest = json.loads(c.execute('SELECT value FROM metadata WHERE key="manifest"').fetchone()[0])
                    cities = [r[0] for r in c.execute('SELECT DISTINCT 出发城市 FROM flights ORDER BY 出发城市')]
                    destinations = [r[0] for r in c.execute('SELECT DISTINCT destination FROM objects ORDER BY destination')]
                    return self.send_json({'manifest':manifest,'holidays':HOLIDAYS,'cities':cities,'destinations':destinations,'default_user':c.execute('SELECT user_id FROM users ORDER BY user_id LIMIT 1').fetchone()[0]})
                if path == '/api/users':
                    term = q.get('q','').strip()
                    items = [dict(r) for r in c.execute('SELECT * FROM users WHERE user_id LIKE ? OR residence_city LIKE ? ORDER BY user_id LIMIT 100',('%'+term+'%','%'+term+'%'))]
                    return self.send_json({'items':items})
                if path == '/api/profile':
                    return self.send_json(profile(c,q['user'],q['asof'],int(q.get('window',30)),int(q.get('half',14))))
                if path == '/api/segments':
                    groups = Counter()
                    samples = []
                    for u in c.execute('SELECT user_id FROM users ORDER BY user_id LIMIT 100').fetchall():
                        p = profile(c,u[0],q['asof'],int(q.get('window',30)),int(q.get('half',14)))
                        cats = p['categories']
                        label = '证据不足' if p['record_count']<7 else '多类并重' if len(cats)>1 and cats[0]['count']==cats[1]['count'] else cats[0]['name']+'关注型'
                        groups[label] +=1
                        samples.append({'user_id':u[0],'group':label,'destination':p['destinations'][0]['name'] if p['destinations'] else None,'record_count':p['record_count']})
                    return self.send_json({'groups':[{'name':k,'count':v} for k,v in groups.most_common()],'sample':100,'samples':samples,'as_of_time':q['asof'],'protocol':'按实际用户ID升序取前100名；窗口内类别频次最高者分组，并列单列，少于7条过程标记证据不足；规则分群，未训练聚类模型；不代表全部旅客分布。'})
                if path == '/api/compare':
                    return self.send_json({'before':profile(c,q['user'],q['before'],int(q.get('window',30)),int(q.get('half',14))),'after':profile(c,q['user'],q['asof'],int(q.get('window',30)),int(q.get('half',14)))})
                if path == '/api/flights':
                    return self.send_json(flight_search(c,q['departure'],q['destination'],q['date'],float(q['budget']) if q.get('budget') else None,q.get('sort','price')))
                if path == '/api/marketing':
                    return self.send_json(marketing(c,q.get('user') if q.get('scope')=='user' else None,q['asof']))
                if path == '/api/evaluation':
                    return self.send_json(evaluate(c,q.get('asof','2024-10-01'),int(q.get('horizon',7)),int(q.get('sample',100)),int(q.get('window',30)),int(q.get('half',14))))
                if path == '/api/drafts':
                    return self.send_json({'items':aigc.drafts(),'audit':aigc.audit()})
                return self.send_json({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError) as e:
            self.send_json({'error':str(e)},400)
        except Exception:
            traceback.print_exc()
            self.send_json({'error':'服务处理失败，请查看 runtime/server.log'},500)

    def do_POST(self):
        self.travel_cookie = None
        try:
            origin = self.headers.get('Origin')
            if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
                return self.send_json({'error':'只允许本机同源操作'},403)
            size = int(self.headers.get('Content-Length','0'))
            if size>100000 or size<=0:
                raise ValueError('请求大小不合法')
            body = json.loads(self.rfile.read(size))
            path = urlsplit(self.path).path
            if path.startswith('/api/mkt/'):
                tail = path.removeprefix('/api/mkt/')
                with connect() as c:
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
            if path.startswith('/api/travel/'):
                uid = self.traveler_id()
                if path == '/api/travel/preferences':
                    return self.send_json(travel.save_preferences(uid,body))
                if path == '/api/travel/action':
                    return self.send_json(travel.action(uid,body))
                if path == '/api/travel/plans':
                    with connect() as c:
                        return self.send_json(travel.create_plan(c,uid,body),201)
                if path.startswith('/api/travel/plans/'):
                    return self.send_json(travel.update_plan(uid,path.rsplit('/',1)[-1],body))
                return self.send_json({'error':'接口不存在'},404)
            if path == '/api/drafts':
                with connect() as c:
                    return self.send_json(aigc.generate(c,body),201)
            if path.startswith('/api/drafts/'):
                return self.send_json(aigc.update(path.rsplit('/',1)[-1],body))
            return self.send_json({'error':'接口不存在'},404)
        except (ValueError,KeyError,TypeError) as e:
            self.send_json({'error':str(e)},400)
        except Exception:
            traceback.print_exc()
            self.send_json({'error':'操作失败，请查看本机服务日志'},500)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port',type=int,default=8765)
    args = parser.parse_args()
    build()
    aigc.state_db().close()
    server = ThreadingHTTPServer(('127.0.0.1',args.port),Handler)
    print(f'航旅智策 本地测试版 http://127.0.0.1:{args.port}',flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
