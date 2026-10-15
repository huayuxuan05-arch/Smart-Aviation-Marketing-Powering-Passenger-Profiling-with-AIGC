"""Independent synthetic annual cohorts. No original person or model score is copied."""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
import numpy as np
import marketing_ml as ml
from data_layer import CST, connect

VERSION = 'annual-independent-v1'
SEED = 20261016
SCENARIOS = ['稳定关注', '逐步迁移', '临近出游变化', '预算变化', '广泛探索', '多目的地比较']
ROUTES = [('北京','杭州'),('上海','成都'),('广州','西安'),('深圳','厦门'),
          ('成都','三亚'),('北京','重庆'),('广州','上海'),('上海','北京')]
HOLIDAY_SOURCE = 'https://www.beijing.gov.cn/cs/gncs/zcwj/202603/t20260327_4568275.html'
HOLIDAYS = [dict(id=i,name=n,start=s,end=e,published='2025-11-04') for i,n,s,e in [
    ('2026-newyear','元旦','2026-01-01','2026-01-03'),
    ('2026-spring','春节','2026-02-15','2026-02-23'),
    ('2026-qingming','清明节','2026-04-04','2026-04-06'),
    ('2026-labor','劳动节','2026-05-01','2026-05-05'),
    ('2026-dragon','端午节','2026-06-19','2026-06-21'),
    ('2026-midautumn','中秋节','2026-09-25','2026-09-27'),
    ('2026-national','国庆节','2026-10-01','2026-10-07')]]


def digest(path):
    with Path(path).open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')


def generate(directory, count, split, anchor, seed=SEED, export_behaviors=True):
    """365 daily episodes per person; simulated outcomes are never model outputs."""
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True)
    manifest_path=directory/'manifest.json'
    if manifest_path.exists():
        m=json.loads(manifest_path.read_text(encoding='utf-8'))
        if (m['users'],m['split'],m['anchor'],m['seed'])!=(count,split,anchor,seed):
            raise ValueError('Existing cohort has different immutable generation settings')
        for name,spec in m['files'].items():
            if digest(directory/name)!=spec['sha256']:raise ValueError('Cohort fingerprint mismatch')
        return m
    end=datetime.fromisoformat(anchor)-timedelta(days=1);start=end-timedelta(days=364)
    rng=np.random.default_rng(seed)
    with connect() as c:
        objects=[dict(r) for r in c.execute('SELECT * FROM objects ORDER BY object_id')]
        old_ids={r[0] for r in c.execute('SELECT user_id FROM users')}
        marginals={key:list(c.execute(f'SELECT {key},COUNT(*) FROM users GROUP BY {key} ORDER BY {key}'))
                   for key in ['travel_party','age_band']}
    destinations=sorted({o['destination'] for o in objects});k=len(destinations)
    if destinations!=ml.model_pack()['report']['protocol']['candidate_destinations']:
        raise ValueError('Frozen model destination order differs')
    def sample(key):
        rows=marginals[key];weights=np.array([r[1] for r in rows],float)
        return rng.choice([r[0] for r in rows],count,p=weights/weights.sum())
    parties,ages=sample('travel_party'),sample('age_band')
    route_ids=np.arange(count)%len(ROUTES);rng.shuffle(route_ids)
    groups=np.arange(count)%len(SCENARIOS);rng.shuffle(groups)
    provinces={'北京':'北京','上海':'上海','广州':'广东','深圳':'广东','成都':'四川'}
    users=[]
    for j in range(count):
        origin,destination=ROUTES[route_ids[j]]
        departure=(datetime.fromisoformat(anchor)+timedelta(days=7+7*((j//8)%2))).date().isoformat()
        days=[3,5][(j//16)%2]
        users.append(dict(user_id=f'{split.upper()}_{anchor.replace("-","")}_{j+1:05}',
            residence_province=provinces[origin],residence_city=origin,usual_departure_city=origin,
            age_band=str(ages[j]),travel_party=str(parties[j]),creative_group='AB'[j%2],
            is_synthetic=1,simulation_version=VERSION,scenario=SCENARIOS[groups[j]],
            requested_destination=destination,start_date=departure,days=days,
            trip_budget=int(rng.choice([2500,4000,6000,9000])),
            airfare_cap=int(rng.choice([600,1000,1600,2400]))))
    if old_ids&{u['user_id'] for u in users}:raise ValueError('Original and new IDs overlap')
    shape=(365,count)
    a={name:np.zeros(shape,dtype=dtype) for name,dtype in [
        ('dest','int16'),('type','uint8'),('channel','uint8'),('hour','uint8'),
        ('dwell','float32'),('repeat','uint8'),('action','int8'),('obj','int16'),
        ('budget','float32'),('travel','int16'),('favtime','int32'),('visit','int32')]}
    a['budget'].fill(np.nan);a['travel'].fill(-1);a['favtime'].fill(-1)
    primary=np.array([destinations.index(u['requested_destination']) for u in users])
    secondary=(primary+rng.integers(1,k,count))%k
    shifts=rng.integers(90,310,count);shifts[groups==2]=rng.integers(275,352,(groups==2).sum())
    channel=rng.integers(0,len(ml.CHANNELS),count);hour=rng.choice([9,13,18,21],count)
    base_budget=rng.choice([500,800,1200,1800,2500],count)
    favorites=np.zeros((count,len(objects)),bool)
    object_map=np.zeros((k,5),np.int16)
    for d,city in enumerate(destinations):
        for t,kind in enumerate(ml.TYPES):
            object_map[d,t]=next(i for i,o in enumerate(objects) if o['destination']==city and o['object_type']==kind)
    for z in range(365):
        day=start+timedelta(days=z);phase=np.clip((z-shifts+14)/28,0,1)
        active=np.where(((groups==1)|(groups==2))&(rng.random(count)<phase),secondary,primary)
        choice=rng.random(count);d=np.where(choice<.66,active,np.where(choice<.86,secondary,rng.integers(k,size=count)))
        explore=groups==4;d[explore]=rng.integers(k,size=explore.sum())
        multi=groups==5;d[multi]=np.where(rng.random(multi.sum())<.5,primary[multi],secondary[multi])
        typ=rng.choice(5,count,p=[.27,.23,.14,.22,.14]);a['dest'][z]=d;a['type'][z]=typ
        a['channel'][z]=np.where(rng.random(count)<.8,channel,rng.integers(6,size=count))
        a['hour'][z]=np.clip(hour+rng.integers(-2,3,count),0,23)
        a['visit'][z]=z*86400+a['hour'][z].astype(np.int32)*3600+rng.integers(0,3300,count)
        a['dwell'][z]=rng.integers(10,601,count);a['repeat'][z]=rng.random(count)<.45
        a['obj'][z]=object_map[d,typ]
        actions=rng.choice([-1,0,1],count,p=[.025,.9,.075]);a['action'][z]=actions
        a['favtime'][z]=np.where(actions!=0,a['visit'][z]+a['dwell'][z].astype(np.int32)+5,-1)
        favorites[np.arange(count),a['obj'][z]]=np.where(actions!=0,actions>0,favorites[np.arange(count),a['obj'][z]])
        airfare=typ==3;money=base_budget*np.where((groups==3)&(z>shifts),.6,1)
        a['budget'][z,airfare]=np.maximum(100,money[airfare]+rng.integers(-100,101,airfare.sum()))
        planned=(rng.random(count)<.32)|airfare
        a['travel'][z,planned]=z+rng.choice([7,14,30,60],planned.sum())
        for h in HOLIDAYS:
            gap=(datetime.fromisoformat(h['start'])-day).days
            if h['published']<=day.date().isoformat() and 0<gap<=30:
                selected=planned&(rng.random(count)<.5)
                a['travel'][z,selected]=ml.day_index(h['start'],start)+rng.integers(0,(datetime.fromisoformat(h['end'])-datetime.fromisoformat(h['start'])).days+1,selected.sum())
    users_path=directory/'users.jsonl'
    with users_path.open('w',encoding='utf-8') as f:
        for u in users:f.write(json.dumps(u,ensure_ascii=False)+'\n')
    np.savez_compressed(directory/'behavior_arrays.npz',**a)
    names=['users.jsonl','behavior_arrays.npz']
    if export_behaviors:
        print('EXPORT_ANNUAL_BEHAVIORS',count*365,flush=True)
        with gzip.open(directory/'behaviors.csv.gz','wt',encoding='utf-8',newline='',compresslevel=4) as f:
            writer=csv.writer(f)
            writer.writerow(['record_id','user_id','behavior_date','search_at_cst','visit_at_cst','object_id','destination','object_type','channel','dwell_seconds','is_repeat_visit','favorite_action','favorite_at_cst','price_limit_cny','travel_date','is_synthetic','simulation_version'])
            for z in range(365):
                day=(start+timedelta(days=z)).date().isoformat()
                rows=[]
                for j,u in enumerate(users):
                    visited=start+timedelta(seconds=int(a['visit'][z,j]))
                    fav=start+timedelta(seconds=int(a['favtime'][z,j])) if a['favtime'][z,j]>=0 else None
                    travel=start+timedelta(days=int(a['travel'][z,j])) if a['travel'][z,j]>=0 else None
                    rows.append([f'{split}_{z:03}_{j:05}',u['user_id'],day,
                        (visited-timedelta(seconds=5)).isoformat(' '),visited.isoformat(' '),objects[a['obj'][z,j]]['object_id'],
                        destinations[a['dest'][z,j]],ml.TYPES[a['type'][z,j]],ml.CHANNELS[a['channel'][z,j]],
                        int(a['dwell'][z,j]),int(a['repeat'][z,j]),{-1:'remove',0:'none',1:'add'}[int(a['action'][z,j])],
                        fav.isoformat(' ') if fav else '',float(a['budget'][z,j]) if np.isfinite(a['budget'][z,j]) else '',
                        travel.date().isoformat() if travel else '',1,VERSION])
                writer.writerows(rows)
                if z%60==0:print('EXPORT_DAY',z,flush=True)
        names.append('behaviors.csv.gz')
    m=dict(version=VERSION,seed=seed,split=split,anchor=anchor,users=count,behavior_days=365,
        behavior_rows=count*365,behavior_start=start.date().isoformat(),behavior_end=end.date().isoformat(),
        candidate_destinations=destinations,scenarios=dict(Counter(u['scenario'] for u in users)),
        original_user_overlap=0,source='independently simulated; no copied original behavior rows',
        holiday_source=HOLIDAY_SOURCE,route_scope=[list(r) for r in ROUTES],
        flight_scope='8 representative domestic routes × 2 departure dates × 2 trip lengths; shared queries, not 10000 independent flight observations',
        original_model_sha256=digest(ml.ROOT/'marketing_models.joblib'),
        files={name:dict(sha256=digest(directory/name),bytes=(directory/name).stat().st_size) for name in names})
    write_json(manifest_path,m);return m


def load(directory):
    directory=Path(directory);m=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    users=[json.loads(line) for line in (directory/'users.jsonl').read_text(encoding='utf-8').splitlines()]
    with connect() as c:objects=[dict(r) for r in c.execute('SELECT * FROM objects ORDER BY object_id')]
    arrays=dict(np.load(directory/'behavior_arrays.npz',allow_pickle=False))
    return (arrays,users,objects,m['candidate_destinations']),datetime.fromisoformat(m['behavior_start']),m


def snapshots(dataset,base,cutoffs):
    for day in cutoffs:
        calendar=[h for h in HOLIDAYS if h['published']<=day]
        s=ml.snapshot(day,dataset=dataset,base_date=base,holidays=calendar)
        yield s,ml.targets(s['day'],dataset=dataset)
