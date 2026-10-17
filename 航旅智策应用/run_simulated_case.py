"""Replay 10,000 explicitly synthetic participants in an isolated website case.

Never writes to the formal personal database, calls a paid flight provider, or
attributes the replay to real participants. Not a concurrent load test.
"""
from pathlib import Path
from datetime import datetime, timedelta
from collections import Counter
from unittest.mock import patch
import argparse
import hashlib
import json
import os
import random
import re
import time
import uuid

import personal_app as personal
import real_travelers as real
import real_marketing_workflow as workflow
import real_forecast as forecast
import marketing_ml as ml
import flight_quotes as flights
import content_generation
from data_layer import RUNTIME, CST, connect

ROOT = RUNTIME / 'simulation-case-20261017'
SEED = 20261017
ASOF = datetime(2024, 9, 24, 23, 59, tzinfo=CST)
ACTION_CLOCK = ASOF - timedelta(hours=1)
LABEL = '10,000名模拟用户网站回放'
BOUNDARY = '全部为模拟数据；串行后端业务回放及代表性浏览器验收，不是实际到访、万人并发、真实授权、实时报价、满意度或营销增量证据。'


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def activate():
    ROOT.mkdir(parents=True, exist_ok=True)
    personal.RUNTIME = ROOT
    flights.RUNTIME = ROOT
    os.environ['AEROLENS_GENERATION_MODE'] = 'template'


def build():
    activate()
    if (ROOT / 'personal.sqlite3').exists():
        raise SystemExit('Existing simulation retained. Use --serve to open it; do not append another population.')
    started = time.perf_counter()
    rng = random.Random(SEED)
    a, users, objects, cities = ml.load_data()
    assert len(users) == 10000 and all(u['is_synthetic'] for u in users)
    snapshot_day = ml.day_index(ASOF.date().isoformat())
    ids = {u['user_id']: 'SIM_SITE_' + hashlib.sha256(u['user_id'].encode()).hexdigest()[:12].upper() for u in users}
    assumptions = {'seed': SEED, 'population': 10000, 'virtual_asof': ASOF.isoformat(),
        'source': 'Original DAILY_SYN_2024_V2_SUBSET_10K users and 2024 synthetic daily behavior',
        'origin': 'unchanged usual_departure_city from original user row',
        'consent_probability': .82, 'planning_probability': .72, 'inspiration_probability': .20,
        'explicit_theme_probability': .82, 'save_plan_given_planning_probability': .80,
        'query_button_given_saved_probability': .55,
        'website_actions': 'Seeded scenario assumptions, not estimated human behavior',
        'flight_queries': 'Disabled in batch replay; attempted requests recorded unavailable, no quotes fabricated',
        'personal_generation': 'Template business path for batch replay; no claim of 10000 Qwen calls',
        'marketing_generation': 'Actual local Qwen call if --local-model is provided, otherwise clearly labelled rules',
        'review': 'Automated replay of the three-check approval path, not an independent human quality evaluation',
        'future_labels': 'Original synthetic observations after frozen asof; not website campaign outcomes',
        'boundary': BOUNDARY}
    dump(ROOT / 'protocol.json', assumptions)
    records = []
    at = ACTION_CLOCK.isoformat()
    with personal.db() as c:
        for i, u in enumerate(users):
            owner = 'SIM_OWNER_' + str(i).zfill(5)
            c.execute('INSERT INTO personal_users VALUES(?,?,?,?)', (owner, ids[u['user_id']], at, at))
            c.execute('INSERT INTO personal_sessions VALUES(?,?,?,?)', (owner, at, 0, None))
            records.append((i, u, owner))
    counts = Counter(total=10000)
    errors = Counter()
    phase_clock=[ACTION_CLOCK]
    with patch.object(real, 'now', side_effect=lambda:phase_clock[0]), patch.object(personal, 'now', return_value=at), connect() as source:
        # These are actual application functions and constraints, not a table of
        # made-up completion totals. Each virtual participant executes its path.
        for i, u, owner in records:
            origin = u['usual_departure_city']
            recent = Counter(cities[int(a['dest'][d, i])] for d in range(snapshot_day-6, snapshot_day+1))
            candidates = sorted((city for city in cities if city != origin), key=lambda city: (-recent[city], city))
            destination = candidates[0]
            stage_draw = rng.random()
            stage = '制定行程' if stage_draw < .72 else '先收集灵感' if stage_draw < .92 else '暂不计划出游'
            explicit = rng.random() < .82
            prefs = {**personal.defaults(), 'origin': origin, 'destination': destination,
                'start_date': '2024-10-01', 'days': 3 + rng.randrange(3),
                'party': u['travel_party'] if u['travel_party'] in personal.PARTIES else personal.PARTIES[i % 5],
                'theme': personal.THEMES[int(a['type'][snapshot_day, i])] if explicit else '',
                'theme_source': 'explicit' if explicit else 'unfilled', 'planning_stage': stage,
                'trip_budget': rng.choice([2000, 3000, 4000, 5000, 6000, 8000]),
                'airfare_cap': rng.choice([800, 1200, 1600, 2000]),
                'required_airlines': rng.choice([[], [], ['CA'], ['MU'], ['CZ']]),
                'excluded_airlines': [], 'travel_request': ''}
            shared = rng.random() < .82
            try:
                if shared:
                    real.set_consent(owner, {'enabled': True})
                    counts['shared'] += 1
                personal.save_preferences(source, owner, {'preferences': prefs, 'expected_revision': 0})
                counts['preferences_saved'] += 1
                if stage == '制定行程' and rng.random() < .80:
                    personal.create_plan(source, owner, {'preferences': prefs, 'expected_revision': 1})
                    counts['plans_saved'] += 1
                    if rng.random() < .55:
                        plan = {'id': 'SIM_REQUEST_' + str(i), 'profile_revision': 1, 'destination': destination}
                        real.record_search_request(owner, plan, None)
                        counts['query_button_attempts'] += 1
                if shared:
                    # Replay the original synthetic timeline with original dates.
                    with personal.db() as c:
                        c.executemany('INSERT INTO real_traveler_events(owner,at,kind,destination,payload) VALUES(?,?,?,?,?)',
                            [(owner, (ml.BASE_DATE + timedelta(days=d, hours=10)).replace(tzinfo=CST).isoformat(),
                              'destination_view', cities[int(a['dest'][d, i])],
                              json.dumps({'source': 'synthetic_original_behavior_replay', 'is_synthetic': True}))
                             for d in range(snapshot_day-29, snapshot_day+1)])
            except ValueError as e:
                errors[str(e)] += 1
                counts['business_path_errors'] += 1
            if (i+1) % 500 == 0:
                print(json.dumps({'completed': i+1, 'seconds': round(time.perf_counter()-started, 1)}, ensure_ascii=False), flush=True)
        phase_clock[0]=ASOF
        dashboard = real.dashboard()
        decision=workflow.decision(dashboard)
        dump(ROOT / 'initial-dashboard.json', dashboard)
        eligible = [p for p in dashboard['profiles'] if p['has_saved_plan'] and p['intent_stage'] == '明确计划']
        destinations = Counter(p['destination'] for p in eligible)
        campaigns = []
        frozen = []
        if ARGS.local_model:
            os.environ['AEROLENS_GENERATION_MODE'] = 'local-model'
            os.environ['AEROLENS_LOCAL_MODEL_PROFILE'] = str(RUNTIME / 'local_aigc/active_model.json')
        for city, n in destinations.most_common(3):
            selected = [p['user_id'] for p in eligible if p['destination'] == city][:5000]
            campaign = real.create_campaign({'name': '模拟案例：' + city + '行程准备', 'user_ids': selected})
            campaign = workflow.generate(campaign['id'], {'expected_revision': campaign.get('revision', 1)})
            campaign = workflow.review(campaign['id'], {'expected_revision': campaign['revision'], 'verdict': 'approve',
                'facts_checked': True, 'consent_checked': True, 'boundary_checked': True})
            campaign = workflow.package(campaign['id'], {'expected_revision': campaign['revision'], 'confirmed': True})
            campaigns.append({'destination': city, 'members': len(selected), 'campaign': campaign,
                'observation': workflow.observe(campaign['id'])})
            frozen.append(forecast.freeze(campaign['id']))
            print('CAMPAIGN_READY', city, len(selected), flush=True)
        # Only after freeze, append the next 7 days from the original synthetic
        # dataset. The virtual clock advances; wall-clock seven days did not pass.
        with personal.db() as c:
            shared_owners={r['owner'] for r in real.rows(c)}
            for i, u, owner in records:
                if owner not in shared_owners: continue
                c.executemany('INSERT INTO real_traveler_events(owner,at,kind,destination,payload) VALUES(?,?,?,?,?)',
                    [(owner, (ml.BASE_DATE + timedelta(days=d, hours=10)).replace(tzinfo=CST).isoformat(),
                      'destination_view', cities[int(a['dest'][d, i])],
                      json.dumps({'source': 'synthetic_original_future_replay', 'is_synthetic': True}))
                     for d in range(snapshot_day+1, snapshot_day+8)])
        with patch.object(real, 'now', return_value=ASOF + timedelta(days=8)):
            evaluated = [forecast.evaluate(f['id']) for f in frozen]
        summary = {'label': LABEL, 'is_synthetic': True, 'protocol': assumptions, 'executed_paths': dict(counts),
            'errors': dict(errors), 'dashboard_population': dashboard['population'],
            'case_evidence': dashboard['case_evidence'], 'intent_groups': dashboard['intent_groups'],'decision':decision,
            'theme_groups': dashboard['theme_groups'], 'top_destinations': destinations.most_common(10),
            'campaigns': campaigns, 'frozen_forecasts': frozen, 'evaluated_forecasts': evaluated,
            'external_messages_sent': 0, 'priced_flights_fabricated': 0, 'ratings_fabricated': 0,
            'seconds': round(time.perf_counter()-started, 2), 'boundary': BOUNDARY}
        dump(ROOT / 'summary.json', summary)
        assert counts['total']==10000 and counts['preferences_saved']==10000
        # Business rejection is an observed case result, not grounds to erase
        # or regenerate a participant until the exercise looks perfect.
        assert counts['business_path_errors']==sum(errors.values())
        assert all(x['campaign']['sent']==0 for x in campaigns)
        print(json.dumps({k:v for k,v in summary.items() if k in ('label','executed_paths','errors','seconds')}, ensure_ascii=False), flush=True)


def serve():
    activate()
    import server
    from http.server import ThreadingHTTPServer
    os.environ['AEROLENS_LOGIN_REQUIRED']='0'
    os.environ['AEROLENS_MARKETING_DATA_MODE']='real'
    os.environ['AEROLENS_GENERATION_MODE']='local-model'
    os.environ['AEROLENS_LOCAL_MODEL_PROFILE']=str(RUNTIME/'local_aigc/active_model.json')
    real.now=lambda:ASOF
    personal.now=lambda:ASOF.isoformat()
    original_profile=real.public_profile
    def profile(*args,**kwargs):
        value=original_profile(*args,**kwargs)
        value['source']='synthetic_site_replay'
        return value
    real.public_profile=profile
    original_dashboard=real.dashboard
    def dashboard(*args,**kwargs):
        value=original_dashboard(*args,**kwargs)
        value.update(is_synthetic=True,scope=BOUNDARY,algorithm='模拟历史回放；本人条件校验；非真实参与者',
            simulation_label=LABEL)
        return value
    real.dashboard=dashboard
    original_send=server.Handler.send_json
    flight_file=ROOT/'simulation-flights.json'
    simulated_flights=json.loads(flight_file.read_text(encoding='utf-8')) if flight_file.exists() else {'records':{}}
    class SimulationHandler(server.Handler):
        def send_json(self,data,status=200):
            if isinstance(data,dict):
                data={**data,'is_synthetic':True,'simulation_label':LABEL,'simulation_boundary':BOUNDARY}
                if data.get('mode')=='real':data['mode']='simulation'
                if data.get('data_mode')=='real':data['data_mode']='simulation'
                if 'data_mode' in data:data['scope']=BOUNDARY
            return original_send(self,data,status)
        def do_GET(self):
            if self.path.split('?')[0]=='/api/simulation-case':
                value=json.loads((ROOT/'summary.json').read_text(encoding='utf-8'))
                item=value['campaigns'][0]
                return self.send_json({'is_synthetic':True,'campaign_members':item['members'],
                    'campaign':workflow.get(item['campaign']['id']),'observation':item['observation'],
                    'forecast':value['evaluated_forecasts'][0],
                    'example':item['campaign']['execution_package']['records'][0],
                    'case_evidence':value['case_evidence'],'decision':value['decision'],
                    'delivery':value.get('simulated_delivery'),'flight_summary':value.get('simulated_flights'),
                    'example_flights':simulated_flights['records'].get(item['campaign']['execution_package']['records'][0]['user_id'])})
            if self.path.split('?')[0].startswith('/api/simulation-flights/'):
                ident=self.path.split('?')[0].rsplit('/',1)[-1]
                record=simulated_flights['records'].get(ident)
                return self.send_json(record if record else {'error':'该模拟旅客尚未保存方案'},200 if record else 404)
            if self.path.split('?')[0] in ('/case-study','/case-study/'):
                target=server.STATIC/'marketing/simulation-guide.html'
                if not target.is_file():return self.send_json({'error':'案例说明尚在准备'},404)
                payload=target.read_bytes();self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path.split('?')[0].startswith('/case-images/'):
                name=self.path.split('?')[0].removeprefix('/case-images/')
                if not re.fullmatch(r'(trips|overview|insights|audience|routes|creative|delivery|evaluation)(?:-detail)?\.png',name):return self.send_json({'error':'截图不存在'},404)
                target=ROOT/'images'/name
                if not target.is_file():return self.send_json({'error':'截图尚在准备'},404)
                payload=target.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path in ('/marketing','/marketing/','/marketing/index.html'):
                raw=(server.STATIC/'marketing/index.html').read_text(encoding='utf-8')
                banner='<div role="note" style="position:fixed;top:0;left:0;right:0;z-index:10000;background:#8b3900;color:white;text-align:center;font:14px sans-serif;padding:9px">全流程模拟案例 · 10,000名虚拟旅客 · 本地模拟通道 · 画像截点2024-09-24</div>'
                raw=re.sub(r'(<body\b[^>]*>)',r'\1'+banner,raw,count=1)
                raw=raw.replace('</head>','<link rel="stylesheet" href="/marketing/simulation-visuals.css"><style>.topbar{top:36px}#sidebar{padding-top:45px}.main-shell{padding-top:36px}.simulation-step{border-left:4px solid #a65a16!important}.simulation-step-head{display:flex;justify-content:space-between;gap:15px;color:#8b3900;font-size:13px}.simulation-step h2{margin-top:12px}.simulation-next{display:inline-block;margin-top:12px;text-decoration:none}@media(max-width:600px){.topbar{top:55px}.main-shell{padding-top:65px}.simulation-step-head{flex-wrap:wrap}}</style></head>')
                raw=raw.replace('</body>','<script src="/marketing/simulation-case.js"></script><script src="/marketing/simulation-visuals.js"></script><script>document.title="模拟案例｜航旅智策";</script></body>')
                payload=raw.encode()
                self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path.split('?')[0] in ('/marketing/real-users.js','/marketing/app.js'):
                source=(server.STATIC/self.path.split('?')[0].lstrip('/')).read_text(encoding='utf-8')
                source=source.replace('真实','模拟').replace('实时航班','仿真航班').replace("data_mode==='real'","data_mode==='simulation'").replace("data_mode!=='real'","data_mode!=='simulation'").replace("data_mode:'real'","data_mode:'simulation'").replace("source.mode==='real'","source.mode==='simulation'")
                payload=source.encode()
                self.send_response(200);self.send_header('Content-Type','application/javascript; charset=utf-8');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload);return
            if self.path.startswith('/api/mkt/real/forecasts/'):
                # The picture stays at the frozen asof; the result panel opens
                # the separately evaluated synthetic future window explicitly.
                ident=self.path.split('?')[0].rsplit('/',1)[-1]
                value=json.loads((ROOT/'summary.json').read_text(encoding='utf-8'))
                result=next((f for f in value['evaluated_forecasts'] if f['id']==ident),None)
                if result is None:return self.send_json({'error':'模拟快照不存在'},404)
                return self.send_json({**result,'simulation_evaluation_at':(ASOF+timedelta(days=8)).isoformat()})
            return super().do_GET()
        def do_POST(self):
            # Keep the report case immutable when browsing. Model/material writes
            # were already exercised through the application functions above.
            return self.send_json({'error':'模拟案例为只读回放，请在正式站点操作自己的数据'},400)
    print('SIMULATION_SITE http://127.0.0.1:'+str(ARGS.port)+'/marketing/',flush=True)
    ThreadingHTTPServer(('127.0.0.1',ARGS.port),SimulationHandler).serve_forever()


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--serve',action='store_true')
    parser.add_argument('--local-model',action='store_true')
    parser.add_argument('--port',type=int,default=8766)
    ARGS=parser.parse_args()
    serve() if ARGS.serve else build()
