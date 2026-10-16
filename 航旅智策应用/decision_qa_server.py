"""隔离浏览器验收服务；真实索引与模型只读，活动写入独立临时目录。"""
import json
import uuid
from pathlib import Path
from unittest.mock import patch

import marketing_app as app
import local_generation as gen
import personal_app as personal
import flight_quotes as flights
from data_layer import connect
from server import Handler, ThreadingHTTPServer


def main():
    # QA never reads or spends the real third-party key unless explicitly tested
    # through a mocked adapter in the dedicated SerpApi browser fixture.
    __import__('os').environ['AEROLENS_FLIGHT_PROVIDER']='serpapi' if __import__('os').environ.get('AEROLENS_TEST_SERPAPI_FLIGHTS')=='1' else 'fli'
    auth_cohort=__import__('os').environ.get('AEROLENS_TEST_ACCOUNT_COHORT')=='1'
    __import__('os').environ['AEROLENS_LOGIN_REQUIRED']='1' if auth_cohort else '0'
    __import__('os').environ['AEROLENS_MARKETING_DATA_MODE']='real' if __import__('os').environ.get('AEROLENS_TEST_REAL_COHORT')=='1' else 'synthetic'
    port=int(__import__('os').environ.get('AEROLENS_QA_PORT','8769'))
    qa = Path(__file__).resolve().parent / 'runtime/tmp' / ('decision-qa' if port==8769 else f'decision-qa-{port}')
    qa.mkdir(parents=True, exist_ok=True)
    app.RUNTIME = qa / ('state-' + uuid.uuid4().hex[:12])
    app.RUNTIME.mkdir()
    personal.RUNTIME = app.RUNTIME
    flights.RUNTIME = app.RUNTIME
    if auth_cohort:
        # Explicit 200-account QA cohort in isolated runtime; never production data.
        import accounts
        import real_travelers as real
        from datetime import timedelta
        accounts.create_account('qa_staff','QA-only-password-2026','staff')
        salt='1'*64;digest=accounts.password_hash('QA-only-password-2026',salt)
        with personal.db() as c:
            for i in range(200):
                owner=f'QA_OWNER_{i:03d}';ident=f'QA_TRAVEL_{i:03d}';at=personal.now()
                prefs={**personal.defaults(),'origin':'上海','destination':'成都' if i%2==0 else '杭州',
                    'start_date':(real.now().date()+timedelta(days=7+i%4)).isoformat(),'trip_budget':2000+i*20,
                    'party':['朋友','亲子','情侣'][i%3],'theme':personal.THEMES[i%5],
                    'required_airlines':[['CA'],['MU'],['3U']][i%3],'excluded_airlines':['9C']}
                c.execute('INSERT INTO personal_accounts VALUES(?,?,?,?,?,?,?)',(owner,f'case{i:03d}',salt,digest,accounts.ITERATIONS,'traveler',at))
                c.execute('INSERT INTO personal_users VALUES(?,?,?,?)',(owner,ident,at,at))
                c.execute('INSERT INTO personal_sessions VALUES(?,?,?,?)',(owner,at,1,json.dumps(prefs,ensure_ascii=False)))
                c.execute('INSERT INTO real_traveler_consent VALUES(?,?,?,?)',(owner,ident,1,at))
                real.record_preferences(c,owner,prefs,1)
                real.record_event(c,owner,'section_view',prefs['destination'],{'section':'lodging','label':'住宿安排'})
    if __import__('os').environ.get('AEROLENS_TEST_CURRENT_COHORT')=='1':
        from data_layer import RUNTIME as project_runtime
        pointer=project_runtime/'current-cohorts'/'active.json'
        destination=app.RUNTIME/'current-cohorts'/'active.json';destination.parent.mkdir()
        destination.write_bytes(pointer.read_bytes())
    # 常规浏览器验收不访问外部航班源；专项夹具也不冒充真实报价。
    if __import__('os').environ.get('AEROLENS_TEST_FLIGHT_FIXTURE')=='1':
        from test_flight_quotes import fixture_result
        flights._search=lambda query:fixture_result(query,variants=True)
        if __import__('os').environ.get('AEROLENS_TEST_LABEL_FLIGHTS')=='1':
            def labelled_fixture(query):
                result=fixture_result(query,variants=True)
                result['source']='QA explicit airline-label fixture / not live'
                for i,option in enumerate(result['options']):
                    for leg in ['outbound','inbound']:
                        for segment in option[leg]['segments']:
                            segment.update(flight_number='3U'+str(9500+i),airline='Sichuan Airlines',airline_zh='四川航空',
                                origin_airport='SHA' if leg=='outbound' else 'TFU',destination_airport='TFU' if leg=='outbound' else 'SHA')
                return result
            flights._search=labelled_fixture
    else:
        flights._search=lambda query:{'options':[],'source':'QA / no external requests'}
    if __import__('os').environ.get('AEROLENS_TEST_NATIVE_FLIGHTS')=='1':
        import fli_roundtrip
        from test_fli_roundtrip import native_fixture,returns_fixture
        flights._search=native_fixture
        fli_roundtrip.returns=returns_fixture
        fli_roundtrip.quote_selected=lambda query,outbound,inbound,catalog:{'catalog':catalog,'options':[],'partial':False}
    if __import__('os').environ.get('AEROLENS_TEST_SERPAPI_FLIGHTS')=='1':
        import flight_provider_settings
        import serpapi_quotes
        import fx_rates
        from test_serpapi_quotes import response_fixture,QA_KEY
        # Explicit QA key and response; no access to the real credential or service.
        __import__('os').environ['SERPAPI_API_KEY']=QA_KEY
        flight_provider_settings.CONFIG=app.RUNTIME/'provider-fixture.json'
        flight_provider_settings.CONFIG.write_text(json.dumps({'provider':'serpapi','currency':'JPY','country':'jp','language':'ja'}),encoding='utf-8')
        serpapi_quotes.request=response_fixture
        serpapi_quotes.SOURCE='QA SerpApi fixture / not live'
        fx_rates.snapshot=lambda:{'rates':{'CNY':'7.4993','JPY':'177.06'},'rate_date':__import__('datetime').date.today().isoformat(),'source':'QA reference-rate fixture / not live'}
        flights._search=serpapi_quotes.initial
    with connect() as source:
        campaign = app.save_campaign(source, {'name': '行程决策隔离浏览器验收', 'limit': 300})
        ready = next(row for row in campaign['audience'] if row['business_ready'])
        fixture = {'title': '从容安排本次旅程', 'text': '了解历史航线参考，按本次计划比较出行条件。',
                   'palette': 'teal', 'art': 'mountain', 'engine': '隔离浏览器验收素材',
                   'risk_flags': [], 'generation_seconds': 0, 'visual_mode': '验收用SVG',
                   'prompt': '隔离验收素材，不冒充本次模型生成'}
        with patch.object(gen, 'generate', return_value=fixture):
            material = app.generate_creative(source, campaign['id'], {'user_id': ready['user_id']})
        result = {'campaign': campaign['id'], 'user_id': ready['user_id'], 'material': material['id'],
                  'comparison': campaign['strategy_comparison'], 'business_ready': campaign['business_ready_count']}
        (qa / 'fixture.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False), flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
