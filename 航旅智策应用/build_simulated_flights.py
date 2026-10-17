"""Detailed, labelled historical/synthetic flight examples for isolated case only."""
from collections import Counter,defaultdict
from datetime import datetime,timedelta
from pathlib import Path
import hashlib,json,random,sqlite3
from data_layer import connect,CST
from airline_preferences import AIRLINES
from run_simulated_case import ROOT
from travel_planner import GATEWAYS

SEED=20261019
PROTOCOL={'is_synthetic':True,'seed':SEED,'unit':'每名成人、单程人民币',
 'historical':'有相同日期、城市及航司的原表直飞记录时引用原始字段，并标注2024历史样本。',
 'synthetic':'缺少原表记录时，按固定场景种子合成SIM-编号、时刻及票价，机场名称仅作场景地点。',
 'constraints':'保留航司及日期，价格和全程预算不满足者明确标注待调整，不提高原预算。',
 'boundary':'仿真供给用于展示字段、约束与费用流程，不是联网报价，不证明现实班期、库存、匹配率或可售性。'}


def run():
 with connect() as c:
  airports=defaultdict(Counter);historical=defaultdict(list)
  for row in c.execute('SELECT * FROM flights'):
   f=dict(row);airports[f['出发城市']][f['出发机场']]+=1;airports[f['到达城市']][f['到达机场']]+=1
   if '2024-10-01'<=f['出发日']<='2024-10-05':historical[(f['出发城市'],f['到达城市'],f['出发日'])].append(f)
 def airport(city):return airports[city].most_common(1)[0][0] if airports[city] else '场景机场（未核验）'
 def leg(origin,destination,day,prefs):
  gateway=next((g for g in GATEWAYS.get(destination,[destination]) if g!=origin),destination)
  required=prefs.get('required_airlines') or [];excluded=set(prefs.get('excluded_airlines') or [])
  allowed=lambda f:(not required or f['航班号'][:2] in required) and f['航班号'][:2] not in excluded
  found=sorted([f for f in historical[(origin,gateway,day)] if allowed(f)],key=lambda f:float(f['机票票价']))
  if found:
   f=found[0]
   departure=datetime.fromisoformat(day+'T'+f['出发时间'][:5]);arrival=datetime.fromisoformat(day+'T'+f['到达时间'][:5])
   if arrival<departure:arrival+=timedelta(days=1)
   result={'flight_number':f['航班号'],'airline_code':f['航班号'][:2],'airline':f['航空公司'],
    'origin':origin,'destination':gateway,'origin_airport':f['出发机场'],'destination_airport':f['到达机场'],
    'departure':departure.strftime('%Y-%m-%d %H:%M'),'arrival':arrival.strftime('%Y-%m-%d %H:%M'),'aircraft':f['机型'],
    'price_cny':float(f['机票票价']),'source_kind':'historical','source_label':'2024历史样本',
    'fare_basis':'原表票面参考；税费、行李和退改未核验'}
  else:
   key=f'{SEED}|{origin}|{gateway}|{day}|{required}|{sorted(excluded)}';seed=int(hashlib.sha256(key.encode()).hexdigest()[:16],16);rng=random.Random(seed)
   codes=required or [code for code in ('CA','MU','CZ','HU','3U') if code not in excluded]
   code=codes[rng.randrange(len(codes))]
   dep=datetime.fromisoformat(day).replace(hour=7+rng.randrange(9),minute=rng.choice([0,10,15,20,30,40,45,50]))
   arrival=dep+timedelta(minutes=90+rng.randrange(151))
   result={'flight_number':'SIM-'+code+str(1000+seed%9000),'airline_code':code,'airline':AIRLINES[code][0],
    'origin':origin,'destination':gateway,'origin_airport':airport(origin),'destination_airport':airport(gateway),
    'departure':dep.strftime('%Y-%m-%d %H:%M'),'arrival':arrival.strftime('%Y-%m-%d %H:%M'),
    'aircraft':'仿真客机','price_cny':float(rng.randrange(450,1701,10)),
    'source_kind':'synthetic_scenario','source_label':'仿真合成航班与票价',
    'fare_basis':'仅为场景价格，不是航司报价；行李和退改未设定'}
  cap=prefs.get('airfare_cap');result['within_airfare_cap']=cap is None or result['price_cny']<=cap
  result['airfare_cap']=cap;result['stops']=0;result['requested_destination']=destination
  result['ground_transfer']=f'{gateway}机场至{destination}的地面接驳另作仿真估算' if gateway!=destination else None
  assert not required or result['airline_code'] in required
  assert result['airline_code'] not in excluded and result['departure'].startswith(day)
  return result
 counts=Counter();records={}
 with sqlite3.connect(ROOT/'personal.sqlite3') as c:
  for user_id,payload in c.execute('SELECT u.user_id,p.payload FROM personal_plans p JOIN personal_users u ON u.owner=p.owner ORDER BY p.created_at,p.id'):
   plan=json.loads(payload);prefs={**plan['preference_constraints'],'origin':plan['origin'],'destination':plan['destination'],'airfare_cap':plan['budget']['one_way_airfare_cap']}
   out=leg(plan['origin'],plan['destination'],plan['start_date'],prefs)
   # A destination gateway remains explicit; do not invent a Suzhou airport.
   ret=leg(out['destination'],plan['origin'],plan['end_date'],prefs)
   parts=[{'name':'去程机票','value':out['price_cny']},{'name':'返程机票','value':ret['price_cny']}]
   parts.extend({'name':p['name'],'value':p['value']} for p in plan['budget']['components'] if p['value'] is not None and p['name']!='机动预留')
   if out['ground_transfer']:parts.append({'name':'地面接驳（仿真）','value':160})
   reserve=round(sum(p['value'] for p in parts)*.1);parts.append({'name':'机动预留（仿真）','value':reserve})
   total=round(sum(p['value'] for p in parts),2);limit=plan['budget']['specified_total']
   value={'is_synthetic':True,'user_id':user_id,'plan_id':plan['id'],'outbound':out,'inbound':ret,
    'airfare_total':out['price_cny']+ret['price_cny'],'budget_components':parts,'estimated_total':total,
    'specified_total':limit,'budget_difference':total-limit if limit is not None else None,
    'within_airfare_caps':out['within_airfare_cap'] and ret['within_airfare_cap'],
    'source_note':PROTOCOL['boundary']}
   records[user_id]=value;counts['plans']+=1
   counts['historical_legs']+=sum(f['source_kind']=='historical' for f in (out,ret))
   counts['synthetic_legs']+=sum(f['source_kind']=='synthetic_scenario' for f in (out,ret))
   counts['within_airfare_caps']+=value['within_airfare_caps']
   counts['over_total_budget']+=limit is not None and total>limit
 assert len(records)==5829
 (ROOT/'simulation-flights.json').write_text(json.dumps({'protocol':PROTOCOL,'counts':dict(counts),'records':records},ensure_ascii=False),encoding='utf-8')
 summary=json.loads((ROOT/'summary.json').read_text(encoding='utf-8'));summary['simulated_flights']={'protocol':PROTOCOL,'counts':dict(counts)}
 (ROOT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
 target=Path(__file__).resolve().parent.parent/'experiments/results/simulated-site-case-2026-10-17/flights.json'
 target.write_text(json.dumps(summary['simulated_flights'],ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(dict(counts)))


if __name__=='__main__':run()
