"""Append a bounded, route/date-diverse current fare batch without fake users."""
import argparse
import json
import uuid
from pathlib import Path
from datetime import datetime,timedelta
from concurrent.futures import ThreadPoolExecutor,as_completed
from collections import Counter
import flight_quotes as flights
import independent_cohort as cohort
from data_layer import CST

ROUTES=[('武汉','上海'),('杭州','西安'),('西安','厦门'),('重庆','广州'),('南京','成都'),('长沙','北京')]


def collect(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    if (output/'protocol.json').exists():raise ValueError('Use a new immutable batch directory')
    today=datetime.now(CST).date();queries=[]
    for origin,destination in ROUTES:
        for lead in [21,28]:
            for days in [3,5]:
                start=today+timedelta(days=lead)
                queries.append(flights.query_for(dict(origin=origin,destination=destination,
                    start_date=start.isoformat(),end_date=(start+timedelta(days=days-1)).isoformat()),
                    dict(adults=1,max_stops=1)))
    cohort.write_json(output/'protocol.json',dict(version='expanded-current-quotes-v1',queries=queries,
        batch_size=len(queries),users=0,source='current online observations, no fabricated individual independence',
        purpose='route/date coverage and prospective fare features; not historical model inputs',
        retention='successful quotations only; no unsuccessful responses or diagnostics'))
    flights.configured_proxy();counts=Counter()
    def one(i,q):
        value=dict(id='EXP_'+uuid.uuid4().hex,query=q,requested_at=flights.now())
        try:
            result=flights._search(q)
            if flights.result_status(result)!='success':return i,None
            value.update(result=flights.successful_result(result),status='success')
        except Exception:return i,None
        value['finished_at']=flights.now();return i,value
    with ThreadPoolExecutor(max_workers=2) as pool:
        for future in as_completed([pool.submit(one,i,q) for i,q in enumerate(queries)]):
            i,value=future.result()
            if not value:continue
            counts['success']+=1
            cohort.write_json(output/f'query_{i:03}.json',value)
            print('EXPANDED_QUOTES',sum(counts.values()),len(queries),value['status'],flush=True)
    report=dict(query_snapshots=len(queries),statuses=dict(counts),routes=[list(r) for r in ROUTES],
        departure_dates=sorted({q['departure'] for q in queries}),days=[3,5],collected_at=flights.now(),
        unique_queries=len({flights.query_key(q) for q in queries}),users=0,
        artifacts={p.name:dict(sha256=cohort.digest(p),bytes=p.stat().st_size) for p in output.glob('query_*.json')})
    cohort.write_json(output/'report.json',report);return report


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);print(json.dumps(collect(p.parse_args().output),ensure_ascii=False))
