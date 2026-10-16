"""Minimal local itinerary choice evidence; never interprets nonchoice as rejection.

Uses the owning personal DB transaction. No cookies, free text, passenger names,
survey identifiers or synthetic users are copied to this evidence store.
"""
import json
import math
import uuid
from datetime import datetime, timezone


def initialize(c):
    # Individual execute calls preserve an enclosing transaction (executescript would commit).
    c.execute('''CREATE TABLE IF NOT EXISTS itinerary_requests(
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, recorded_at TEXT NOT NULL,
        query_id TEXT NOT NULL, plan_id TEXT NOT NULL, profile_revision INTEGER NOT NULL,
        candidates TEXT NOT NULL, UNIQUE(owner,query_id,plan_id,profile_revision))''')
    c.execute('''CREATE TABLE IF NOT EXISTS itinerary_feedback(
        id TEXT PRIMARY KEY, owner TEXT NOT NULL, recorded_at TEXT NOT NULL,
        request_id TEXT, candidate_index INTEGER, event TEXT NOT NULL,
        detail TEXT NOT NULL, UNIQUE(owner,request_id,candidate_index,event))''')


def event(c,owner,kind,detail,request_id=None,candidate_index=None):
    if kind not in ('preview','choose','reject','modify','save_plan','delete_plan','discard_draft'):
        raise ValueError('Unsupported evidence event')
    initialize(c)
    c.execute('INSERT OR IGNORE INTO itinerary_feedback VALUES(?,?,?,?,?,?,?)',
        ('EV_'+uuid.uuid4().hex,owner,datetime.now(timezone.utc).isoformat(),request_id,candidate_index,
         kind,json.dumps(detail,ensure_ascii=False,allow_nan=False)))


def candidate_features(plan,option,adults):
    """Itinerary features use actual self-reported ceilings, not simulated bands."""
    budget=plan['budget']; cap=budget.get('one_way_airfare_cap'); total=budget.get('specified_total')
    air_min=budget.get('one_way_airfare_range',{}).get('min')
    trip_min=budget.get('trip_budget_range',{}).get('min')
    out=option['outbound']; back=option['inbound']
    def hour(leg,field):
        value=leg.get(field) or leg['segments'][0 if field=='departure_time' else -1][field]
        dt=datetime.fromisoformat(value);return dt.hour+dt.minute/60
    def duration(leg):
        start=leg.get('departure_time') or leg['segments'][0]['departure_time']
        end=leg.get('arrival_time') or leg['segments'][-1]['arrival_time']
        return (datetime.fromisoformat(end)-datetime.fromisoformat(start)).total_seconds()/60
    prices=[out['price_cny']/adults,back['price_cny']/adults]
    if not all(math.isfinite(v) and v>0 for v in prices):raise ValueError('Invalid current fare')
    constraints=plan.get('preference_constraints',{})
    recorded=datetime.now(timezone.utc)
    nonflight=[c.get('value') for c in budget.get('components',[]) if c['name'] not in ('去程航空','返程航空','机动预留')]
    estimate=round((sum(prices)+sum(nonflight))*1.1,2) if nonflight and all(v is not None for v in nonflight) else None
    stops=max(len(out['segments'])-1,len(back['segments'])-1)
    feasible=((cap is None or max(prices)<=cap) and
        (total is None or estimate is not None and estimate<=total) and
        (constraints.get('fallback_policy')!='只接受直飞' or stops==0))
    return dict(outbound_per_adult=prices[0],inbound_per_adult=prices[1],
        one_way_upper=cap,trip_upper=total,one_way_lower=air_min,trip_lower=trip_min,
        one_way_band_width=cap-air_min if cap is not None and air_min is not None else None,
        trip_band_width=total-trip_min if total is not None and trip_min is not None else None,
        budget_source='actual self-reported bounds; unfilled bounds stay missing',
        roundtrip_trip_cap_share=sum(prices)/total if total else None,
        estimated_total_per_adult=estimate,total_budget_ratio=estimate/total if total and estimate is not None else None,
        hard_constraints_satisfied=bool(feasible),
        outbound_cap_ratio=prices[0]/cap if cap else None,inbound_cap_ratio=prices[1]/cap if cap else None,
        days=plan['days'],adults=adults,
        booking_lead_days=(datetime.fromisoformat(plan['start_date']).date()-recorded.astimezone().date()).days,
        max_stops=stops,
        outbound_departure_hour=hour(out,'departure_time'),outbound_arrival_hour=hour(out,'arrival_time'),
        return_departure_hour=hour(back,'departure_time'),return_arrival_hour=hour(back,'arrival_time'),
        outbound_minutes=duration(out),return_minutes=duration(back),
        pace=plan.get('pace'),lodging_priority=constraints.get('lodging_priority'),
        date_flexibility=constraints.get('date_flexibility'),fallback_policy=constraints.get('fallback_policy'),
        merchant_hotel_price_observed=False,model_score=None)


def exposure(c,owner,plan,observation):
    initialize(c)
    candidates=[dict(index=i,features=candidate_features(plan,option,observation['query']['adults']),
        relevance=None) for i,option in enumerate(observation.get('options',[]))]
    if not candidates:raise ValueError('No quoted itinerary candidates')
    revision=plan['profile_revision']
    row=c.execute('SELECT id FROM itinerary_requests WHERE owner=? AND query_id=? AND plan_id=? AND profile_revision=?',
        (owner,observation['id'],plan['id'],revision)).fetchone()
    if row:return row[0]
    ident='REQ_'+uuid.uuid4().hex
    c.execute('INSERT INTO itinerary_requests VALUES(?,?,?,?,?,?,?)',(ident,owner,
        datetime.now(timezone.utc).isoformat(),observation['id'],plan['id'],revision,
        json.dumps(candidates,ensure_ascii=False,allow_nan=False)))
    return ident


def explicit_rejection(c,owner,request_id,index):
    """Only an explicit rejection counts; deleting a saved plan is a separate event."""
    initialize(c)
    row=c.execute('SELECT candidates FROM itinerary_requests WHERE id=? AND owner=?',(request_id,owner)).fetchone()
    if not row:raise ValueError('候选请求不存在或不属于当前浏览器')
    candidates=json.loads(row[0])
    if isinstance(index,bool) or not isinstance(index,int) or not 0<=index<len(candidates):raise ValueError('候选编号不合法')
    event(c,owner,'reject',{},request_id,index)


def labeled_groups(c):
    """Only explicitly chosen AND explicitly rejected candidates form training pairs."""
    initialize(c); result=[]
    for row in c.execute('SELECT id,owner,recorded_at,candidates FROM itinerary_requests ORDER BY recorded_at,id'):
        request_id,owner,recorded_at,candidates=row
        labels={}; conflicts=set()
        for index,kind in c.execute("SELECT candidate_index,event FROM itinerary_feedback WHERE request_id=? AND owner=? AND event IN ('choose','reject')",(request_id,owner)):
            value=int(kind=='choose')
            if index in labels and labels[index]!=value:conflicts.add(index)
            labels[index]=value
        selected=[]
        for candidate in json.loads(candidates):
            i=candidate['index']
            if i in labels and i not in conflicts and candidate['features'].get('hard_constraints_satisfied'):
                selected.append({**candidate,'relevance':labels[i]})
        if {v['relevance'] for v in selected}=={0,1}:
            result.append(dict(request_id=request_id,owner=owner,recorded_at=recorded_at,candidates=selected))
    return result
