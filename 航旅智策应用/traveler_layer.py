"""旅客端：匿名本机会话、明确偏好、可解释推荐与持久化旅行清单。"""
from datetime import datetime
from collections import Counter
import json
import math
import sqlite3
import uuid
from data_layer import RUNTIME, ClosingConnection, CST
from algorithm_layer import flight_search

THEMES = ['自然山海','海边放空','城市漫游','美食寻味','人文探索','亲子时光']
CATALOG = [
    ('成都','把节奏慢下来','一段留给自己、也留给好味道的城市假期。',['美食寻味','城市漫游','亲子时光'],'city','CHENGDU','慢一点，刚刚好'),
    ('三亚','把日常交给海风','向海出发，把旅行的空白留给自己。',['海边放空','自然山海','亲子时光'],'coast','SANYA','下一站，去看海'),
    ('大理','山与水之间的留白','选一段不赶路的时光，重新感受旅途。',['自然山海','人文探索'],'mountain','DALI','有风，也有自由'),
    ('北京','换个角度看城市','让一次新的出发，连接你喜欢的城市故事。',['人文探索','城市漫游','亲子时光'],'heritage','BEIJING','在城市里发现故事'),
    ('厦门','给自己一段海岸时光','不必排满日程，沿着自己的心情走。',['海边放空','城市漫游','美食寻味'],'coast','XIAMEN','沿着海岸慢慢走'),
    ('西安','走进另一段时光','为好奇心留出时间，为旅程留一点想象。',['人文探索','美食寻味'],'heritage','XIAN','好奇心，就是方向'),
    ('重庆','城市的另一种节奏','出发去感受一座城市，也发现新的自己。',['城市漫游','美食寻味'],'city','CHONGQING','让城市带来灵感'),
    ('杭州','把旅行过得从容一点','为自然和日常之间，留出一段轻松的假期。',['自然山海','城市漫游'],'mountain','HANGZHOU','走走停停，都是风景'),
    ('青岛','一场关于海的约定','在城市与海的交界，寻找喜欢的旅行节奏。',['海边放空','城市漫游'],'coast','QINGDAO','风从海上来'),
    ('丽江','找一处心里的远方','留一段散步的时间，把新的故事带回来。',['自然山海','人文探索'],'mountain','LIJIANG','远方，自有答案'),
    ('长沙','让好心情先出发','好奇地走进一座城市，把喜欢的瞬间收进旅程。',['美食寻味','城市漫游'],'city','CHANGSHA','跟着好心情出发'),
    ('广州','把城市当作旅行灵感','带着自己的口味与步调，发现新的旅行选择。',['美食寻味','城市漫游','亲子时光'],'city','GUANGZHOU','新的风景，也有熟悉的温度'),
    ('昆明','从容出发，轻松抵达','给假期一点弹性，让旅行回到舒服的节奏。',['自然山海','亲子时光'],'mountain','KUNMING','旅行，可以很轻松'),
    ('上海','在熟悉之外发现灵感','为城市漫步留出时间，也给自己一些新的可能。',['城市漫游','美食寻味'],'city','SHANGHAI','随心，漫游城市'),
    ('张家界','去自然里找一个答案','把视线放远，把行程放慢。',['自然山海','亲子时光'],'mountain','ZHANGJIAJIE','向山野出发'),
    ('桂林','为山水留一点时间','不赶着打卡，让每一站都有自己的节奏。',['自然山海','亲子时光'],'mountain','GUILIN','把风景留给旅程'),
]
DESTINATIONS = {d[0]:{'name':d[0],'headline':d[1],'description':d[2],'themes':d[3],'art':d[4],'english':d[5],'caption':d[6]} for d in CATALOG}
DEFAULT_PREFS = {'departure':'上海','date':'2024-10-23','budget':1800,'party':'一个人','days':3,'themes':[],'time':'不限时段'}


def store():
    RUNTIME.mkdir(exist_ok=True)
    c = sqlite3.connect(RUNTIME/'traveler.sqlite3',factory=ClosingConnection,timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS travelers (id TEXT PRIMARY KEY, preferences TEXT NOT NULL, created_at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS travel_actions (id INTEGER PRIMARY KEY, traveler TEXT, kind TEXT, target TEXT, at TEXT)')
    c.execute('CREATE INDEX IF NOT EXISTS travel_actions_user ON travel_actions(traveler,at)')
    c.execute('CREATE TABLE IF NOT EXISTS travel_favorites (traveler TEXT, destination TEXT, at TEXT, PRIMARY KEY(traveler,destination))')
    c.execute('CREATE TABLE IF NOT EXISTS travel_plans (id TEXT PRIMARY KEY, traveler TEXT, payload TEXT)')
    c.commit()
    return c


def now():
    return datetime.now(CST).isoformat(timespec='seconds')


def session(existing=None):
    with store() as c:
        if existing and c.execute('SELECT 1 FROM travelers WHERE id=?',(existing,)).fetchone():
            return existing,False
        token = uuid.uuid4().hex
        c.execute('INSERT INTO travelers VALUES (?,?,?)',(token,json.dumps(DEFAULT_PREFS,ensure_ascii=False),now()))
        return token,True


def validate_preferences(raw):
    p = {**DEFAULT_PREFS,**{k:v for k,v in raw.items() if k in DEFAULT_PREFS}}
    if not isinstance(p['departure'],str) or not 1<=len(p['departure'])<=20:
        raise ValueError('请选择出发城市')
    datetime.strptime(p['date'],'%Y-%m-%d')
    p['budget'] = float(p['budget'])
    if not math.isfinite(p['budget']) or not 100<=p['budget']<=20000:
        raise ValueError('单程预算请填写100—20000元')
    p['days'] = int(p['days'])
    if not 1<=p['days']<=14:
        raise ValueError('旅行天数请填写1—14天')
    if p['party'] not in ('一个人','两个人','朋友同行','亲子出游','长者同行'):
        raise ValueError('请选择同行方式')
    if p['time'] not in ('不限时段','上午出发','下午出发','晚间出发'):
        raise ValueError('请选择起飞时段偏好')
    if not isinstance(p['themes'],list) or any(t not in THEMES for t in p['themes']):
        raise ValueError('请选择支持的旅行兴趣')
    p['themes'] = list(dict.fromkeys(p['themes']))
    return p


def state(uid):
    with store() as c:
        row = c.execute('SELECT preferences FROM travelers WHERE id=?',(uid,)).fetchone()
        prefs = json.loads(row[0])
        favorites = [r[0] for r in c.execute('SELECT destination FROM travel_favorites WHERE traveler=? ORDER BY at DESC',(uid,))]
        actions = [dict(r) for r in c.execute('SELECT kind,target,at FROM travel_actions WHERE traveler=? ORDER BY id DESC LIMIT 200',(uid,))]
        plans = [json.loads(r[0]) for r in c.execute('SELECT payload FROM travel_plans WHERE traveler=? ORDER BY rowid DESC',(uid,))]
        hidden = {r[0] for r in c.execute('SELECT DISTINCT target FROM travel_actions WHERE traveler=? AND kind="hide"',(uid,))}
    scores = Counter()
    viewed = Counter()
    for a in actions:
        if a['kind']=='view':
            viewed[a['target']] += 1
            age = max(0,(datetime.now(CST)-datetime.fromisoformat(a['at'])).total_seconds()/86400)
            for theme in DESTINATIONS.get(a['target'],{}).get('themes',[]):
                scores[theme] += 2**(-age/14)
    for d in favorites:
        for theme in DESTINATIONS.get(d,{}).get('themes',[]):
            scores[theme] += 3
    return {'preferences':prefs,'favorites':favorites,'plans':plans,'recent':[{'name':d,'count':n} for d,n in viewed.most_common(6)],
            'learned_themes':[{'name':k,'score':round(v,2)} for k,v in scores.most_common()], 'hidden':sorted(hidden),
            'view_count':sum(viewed.values()),'history':actions[:30], 'mode':'local-guest'}


def save_preferences(uid,raw):
    prefs = validate_preferences(raw)
    with store() as c:
        c.execute('UPDATE travelers SET preferences=? WHERE id=?',(json.dumps(prefs,ensure_ascii=False),uid))
    return state(uid)


def action(uid,body):
    kind = body.get('kind')
    target = body.get('destination')
    if kind not in ('view','favorite','unfavorite','hide','restore','clear-history'):
        raise ValueError('暂不支持该操作')
    if kind!='clear-history' and target not in DESTINATIONS:
        raise ValueError('这个目的地暂不在灵感列表中')
    with store() as c:
        c.execute('BEGIN IMMEDIATE')
        if kind=='favorite':
            c.execute('INSERT OR REPLACE INTO travel_favorites VALUES(?,?,?)',(uid,target,now()))
        elif kind=='unfavorite':
            c.execute('DELETE FROM travel_favorites WHERE traveler=? AND destination=?',(uid,target))
        elif kind=='restore':
            c.execute('DELETE FROM travel_actions WHERE traveler=? AND kind="hide" AND target=?',(uid,target))
        elif kind=='clear-history':
            c.execute('DELETE FROM travel_actions WHERE traveler=? AND kind="view"',(uid,))
        if kind not in ('restore','clear-history'):
            c.execute('INSERT INTO travel_actions(traveler,kind,target,at) VALUES(?,?,?,?)',(uid,kind,target,now()))
    return state(uid)


def discover(c,uid,query):
    s = state(uid)
    p = s['preferences']
    departure = query.get('departure') or p['departure']
    day = query.get('date') or p['date']
    datetime.strptime(day,'%Y-%m-%d')
    theme = query.get('theme','全部灵感')
    if theme not in THEMES+['全部灵感','适合我','预算友好']:
        raise ValueError('未知兴趣分类')
    budget = float(query.get('budget') or p['budget'])
    if not math.isfinite(budget) or budget<=0:
        raise ValueError('请输入有效预算')
    quotes = {r['到达城市']:{'price':r['price'],'count':r['count']} for r in c.execute('SELECT 到达城市,MIN(机票票价) AS price,COUNT(*) AS count FROM flights WHERE 出发城市=? AND 出发日=? GROUP BY 到达城市',(departure,day))}
    learned = {t['name']:t['score'] for t in s['learned_themes']}
    items = []
    for name,d in DESTINATIONS.items():
        if name==departure or name in s['hidden']:
            continue
        if theme in THEMES and theme not in d['themes']:
            continue
        quote = quotes.get(name)
        if theme=='预算友好' and (not quote or quote['price']>budget):
            continue
        overlap = [t for t in p['themes'] if t in d['themes']]
        inferred = [t for t in d['themes'] if learned.get(t,0)>0]
        score = len(overlap)*5+sum(min(learned.get(t,0),10)*.35 for t in d['themes'])
        if quote:
            score += 2
            if quote['price']<=budget:
                score += 2
        reason = '符合你选择的'+ '、'.join(overlap[:2]) if overlap else '你最近关注了'+inferred[0]+'主题' if inferred else '给下一次出发一点灵感'
        items.append({**d,'price':quote['price'] if quote else None,'candidate_count':quote['count'] if quote else 0,
            'in_budget':bool(quote and quote['price']<=budget),'favorite':name in s['favorites'],'reason':reason,'score':round(score,3),
            'departure':departure,'date':day,'price_label':'历史单程参考' if quote else '当前条件暂无历史报价'})
    items.sort(key=lambda d:(-d['score'], d['price'] if d['price'] is not None else 999999))
    return {'items':items,'departure':departure,'date':day,'budget':budget,'theme':theme,'historical':True,
            'learned_from':'仅使用你在本网站主动填写的偏好、浏览和收藏，不套用模拟用户身份。'}


def search_flights(c,uid,q):
    p = state(uid)['preferences']
    departure = q.get('departure') or p['departure']
    destination = q.get('destination','')
    day = q.get('date') or p['date']
    datetime.strptime(day,'%Y-%m-%d')
    if not destination:
        raise ValueError('先选择一个想去的目的地吧')
    if not '2024-01-01'<=day<='2024-12-31':
        return {'items':[],'total':0,'reason':'当前体验版使用2024年历史航班，所选日期暂无可查询记录。可手动切换至2024年历史参考日期。','historical':True}
    sort = q.get('sort','price')
    budget = float(q['budget']) if q.get('budget') else None
    result = flight_search(c,departure,destination,day,budget,sort)
    period = q.get('time','不限时段')
    if period not in ('不限时段','上午出发','下午出发','晚间出发'):
        raise ValueError('不支持的起飞时段')
    ranges = {'上午出发':(0,12),'下午出发':(12,18),'晚间出发':(18,24)}
    if period in ranges:
        lo,hi = ranges[period]
        result['items'] = [r for r in result['items'] if lo<=int(r['出发时间'][:2])<hi]
    result['displayed'] = len(result['items'])
    result['time_filter'] = period
    if period!='不限时段':
        result['filter_note'] = '时段筛选作用于价格/起飞时间排序后的前100条历史候选。'
    result['historical'] = True
    return result


def create_plan(c,uid,body):
    s = state(uid)
    p = s['preferences']
    destination = body.get('destination')
    if not isinstance(destination,str) or not c.execute('SELECT 1 FROM flights WHERE 到达城市=? LIMIT 1',(destination,)).fetchone():
        raise ValueError('请选择历史航班中的到达城市')
    day = body.get('date') or p['date']
    datetime.strptime(day,'%Y-%m-%d')
    days = int(body.get('days',p['days']))
    if not 1<=days<=14:
        raise ValueError('旅行天数需为1—14天')
    flight = None
    if body.get('candidate_id'):
        try:
            rowid = int(body['candidate_id'].removeprefix('FLIGHT_ROW_'))-1
        except (ValueError,AttributeError):
            raise ValueError('航班参考编号不正确')
        raw = c.execute('SELECT rowid AS source_row,* FROM flights WHERE rowid=?',(rowid,)).fetchone()
        departure = body.get('departure') or p['departure']
        if not raw or raw['到达城市']!=destination or raw['出发日']!=day or raw['出发城市']!=departure:
            raise ValueError('航班日期或城市已变化，请重新选择')
        flight = dict(raw)
        flight['candidate_id'] = body['candidate_id']
    city_themes = DESTINATIONS.get(destination,{'themes':['城市漫游']})['themes']
    style = next((t for t in p['themes'] if t in city_themes),city_themes[0])
    activities = {'自然山海':'留出一段自然散步和自由探索的时间','海边放空':'安排一段海边主题的自由时光，具体地点自行确认','城市漫游':'选择你感兴趣的城市区域，按自己的节奏走走','美食寻味':'留出一顿慢慢享用的餐食，餐厅与营业信息出发前确认','人文探索':'安排一段人文主题探索，具体场馆与预约信息自行确认','亲子时光':'给同行家人留出休息和自由活动的时间'}
    itinerary = [{'day':i+1,'title':'轻松抵达' if i==0 else '从容返程' if i==days-1 else '随心探索',
        'text':('确认交通与入住安排，给自己留出休息时间。' if i==0 else '检查随身物品与返程安排，留足交通时间。' if i==days-1 else activities[style]),'note':''} for i in range(days)]
    plan = {'id':'TRIP_'+uuid.uuid4().hex[:12],'destination':destination,'departure':body.get('departure') or p['departure'],
        'date':day,'days':days,'party':p['party'],'theme':style,'title':f'{destination} · {days}天慢旅行','itinerary':itinerary,
        'flight':flight,'created_at':now(),'note':'','status':'计划中','checklist':[{'label':x,'done':False} for x in ['确认出发日期与交通','核对住宿与预约','查看天气和行李要求','安排返程交通']],
        'generation':'偏好约束的基础行程模板；具体商户、开放时间、天气与实时票价需另行确认。','source':'航班来自01_航班信息.xlsx历史记录，未提供真实预订或付款。'}
    with store() as db:
        db.execute('INSERT INTO travel_plans VALUES(?,?,?)',(plan['id'],uid,json.dumps(plan,ensure_ascii=False)))
    return plan


def update_plan(uid,plan_id,body):
    with store() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT payload FROM travel_plans WHERE id=? AND traveler=?',(plan_id,uid)).fetchone()
        if not row:
            raise ValueError('这份旅行计划不存在')
        if body.get('action')=='delete':
            c.execute('DELETE FROM travel_plans WHERE id=? AND traveler=?',(plan_id,uid))
            return {'deleted':True}
        p = json.loads(row[0])
        if 'note' in body:
            if not isinstance(body['note'],str) or len(body['note'])>5000:
                raise ValueError('备注请控制在5000字以内')
            p['note'] = body['note']
        if 'checklist' in body:
            flags = body['checklist']
            if not isinstance(flags,list) or len(flags)!=len(p['checklist']) or any(type(v)!=bool for v in flags):
                raise ValueError('清单格式不正确')
            for item,flag in zip(p['checklist'],flags):
                item['done'] = flag
        if 'status' in body:
            if body['status'] not in ('计划中','已归档'):
                raise ValueError('不支持该旅行状态')
            p['status'] = body['status']
        if 'day_notes' in body:
            notes = body['day_notes']
            if not isinstance(notes,list) or len(notes)!=p['days'] or any(not isinstance(n,str) or len(n)>1000 for n in notes):
                raise ValueError('每日备注格式不正确')
            for day,note in zip(p['itinerary'],notes):
                day['note'] = note
        p['updated_at'] = now()
        c.execute('UPDATE travel_plans SET payload=? WHERE id=? AND traveler=?',(json.dumps(p,ensure_ascii=False),plan_id,uid))
    return p
