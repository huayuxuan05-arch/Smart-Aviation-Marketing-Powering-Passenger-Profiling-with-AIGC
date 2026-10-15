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
    port=int(__import__('os').environ.get('AEROLENS_QA_PORT','8769'))
    qa = Path(__file__).resolve().parent / 'runtime/tmp' / ('decision-qa' if port==8769 else f'decision-qa-{port}')
    qa.mkdir(parents=True, exist_ok=True)
    app.RUNTIME = qa / ('state-' + uuid.uuid4().hex[:12])
    app.RUNTIME.mkdir()
    personal.RUNTIME = app.RUNTIME
    flights.RUNTIME = app.RUNTIME
    # 常规浏览器验收不访问外部航班源；专项夹具也不冒充真实报价。
    if __import__('os').environ.get('AEROLENS_TEST_FLIGHT_FIXTURE')=='1':
        from test_flight_quotes import fixture_result
        flights._search=fixture_result
    else:
        flights._search=lambda query:{'options':[],'source':'QA / no external requests'}
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
