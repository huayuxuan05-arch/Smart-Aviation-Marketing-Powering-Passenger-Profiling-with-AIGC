"""可追溯画像、历史候选排序与观察截点协议。"""
from collections import Counter, defaultdict
from datetime import datetime, timedelta
import math
import statistics
from data_layer import VERSION

METHOD = 'decay-equal-v1.0'
TYPES = {'destination':'目的地', 'scenic':'景区', 'hotel':'酒店', 'airfare':'机票价格', 'guide':'攻略'}
HOLIDAYS = [
    {'id':'newyear','name':'元旦','start':'2023-12-30','end':'2024-01-01'},
    {'id':'spring','name':'春节','start':'2024-02-10','end':'2024-02-17'},
    {'id':'qingming','name':'清明节','start':'2024-04-04','end':'2024-04-06'},
    {'id':'labor','name':'劳动节','start':'2024-05-01','end':'2024-05-05'},
    {'id':'dragon','name':'端午节','start':'2024-06-08','end':'2024-06-10'},
    {'id':'midautumn','name':'中秋节','start':'2024-09-15','end':'2024-09-17'},
    {'id':'national','name':'国庆节','start':'2024-10-01','end':'2024-10-07'}]


def cutoff(value):
    value = str(value).replace('T',' ')
    if len(value) == 10:
        value += ' 23:59:59'
    result = datetime.fromisoformat(value)
    if result.tzinfo or not datetime(2023,12,1) <= result <= datetime(2024,12,31,23,59,59):
        raise ValueError('截点须位于 2023-12-01 至 2024-12-31，北京时间且不含时区后缀')
    return result


def history(c, uid, end=None):
    sql = 'SELECT * FROM behaviors WHERE user_id=?'
    params = [uid]
    if end:
        sql += ' AND search_at_cst<=?'
        params.append(end.strftime('%Y-%m-%d %H:%M:%S'))
    return [dict(r) for r in c.execute(sql+' ORDER BY search_at_cst',params)]


def profile(c, uid, as_of, window=30, half=14, rows=None):
    t = cutoff(as_of)
    if window not in (7,30,60) or half not in (7,14,30):
        raise ValueError('窗口支持7/30/60天，半衰期支持7/14/30天')
    user = c.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
    if not user:
        raise ValueError('用户编号不存在，请从实际用户列表选择')
    rows = history(c,uid,t) if rows is None else [r for r in rows if r['search_at_cst'] <= str(t)]
    start = t-timedelta(days=window)
    scores = defaultdict(float)
    evidence = defaultdict(list)
    dest, categories, channels, hours = Counter(), Counter(), Counter(), Counter()
    favorites, budgets, records = {}, [], []
    for raw in rows:
        r = dict(raw)
        search = datetime.fromisoformat(r['search_at_cst'])
        visit = datetime.fromisoformat(r['visit_at_cst'])
        complete = visit+timedelta(seconds=r['dwell_seconds'])
        fav_at = datetime.fromisoformat(r['favorite_at_cst']) if r['favorite_at_cst'] else None
        if fav_at and fav_at<=t:
            if r['favorite_action'] in ('add','favorite','collect'):
                favorites[r['object_id']] = r['record_id']
            elif r['favorite_action'] in ('remove','unfavorite','cancel'):
                favorites.pop(r['object_id'],None)
        if search <= start:
            continue
        # 每条日过程只累计一次，搜索与浏览不重复放大证据。
        age = (t-search).total_seconds()/86400
        scores[r['destination']] += 2**(-age/half)
        evidence[r['destination']].append(r['record_id'])
        dest[r['destination']] += 1
        categories[r['object_type']] += 1
        channels[r['channel']] += 1
        hours[search.hour] += 1
        if r['price_limit_cny'] is not None:
            budgets.append({'value':r['price_limit_cny'],'record_id':r['record_id']})
        r['phase'] = '过程完成' if complete<=t else '浏览中' if visit<=t else '搜索完成'
        if visit>t:
            r.update(visit_at_cst=None,dwell_seconds=None,visit_index=None,is_repeat_visit=None)
        elif complete>t:
            r['dwell_seconds'] = max(0,int((t-visit).total_seconds()))
        if not fav_at or fav_at>t:
            r.update(favorite_action='none',favorite_at_cst=None)
        r['is_favorited'] = int(r['object_id'] in favorites)
        records.append(r)
    ranking = sorted(scores.items(),key=lambda x:(-x[1],x[0]))
    total = sum(scores.values()) or 1
    n = len(records)
    observed_start = max(datetime(2023,12,1),start)
    budget_values = [b['value'] for b in budgets]
    return {'user':dict(user),'as_of_time':str(t),'window':window,'half_life':half,
        'method':METHOD,'version':VERSION,'input_range':[str(observed_start),str(t)],
        'actual_days':min(window,math.ceil((t-datetime(2023,12,1)).total_seconds()/86400)),
        'record_count':n,'confidence':'证据较充分' if n>=14 else '证据有限' if n>=7 else '证据不足',
        'destinations':[{'name':d,'score':round(v,4),'share':round(v/total*100,1),'count':dest[d],'record_ids':evidence[d]} for d,v in ranking],
        'categories':[{'name':TYPES.get(k,k),'key':k,'count':v} for k,v in categories.most_common()],
        'channels':[{'name':k,'count':v} for k,v in channels.most_common()],
        'hours':[{'hour':h,'count':hours[h]} for h in range(24)],
        'budget':{'median':statistics.median(budget_values) if budgets else None,'min':min(budget_values) if budgets else None,'max':max(budget_values) if budgets else None,'evidence':budgets},
        'favorites':favorites,'repeat_count':sum(r['is_repeat_visit'] or 0 for r in records),
        'latest':records[-1]['search_at_cst'] if records else None,'records':list(reversed(records)),
        'strategy':{'channel':channels.most_common(1)[0][0] if channels else '待确认',
                    'hour':hours.most_common(1)[0][0] if hours else 10,
                    'theme':TYPES.get(categories.most_common(1)[0][0],'目的地') if categories else '目的地',
                    'basis':'仅依据截点前访问分布，不能证明渠道转化最优'}}


def flight_search(c, departure, destination, day, budget=None, sort='price'):
    datetime.strptime(day,'%Y-%m-%d')
    if not '2024-01-01'<=day<='2024-12-31':
        raise ValueError('历史航班仅覆盖2024年')
    if sort not in ('price','time'):
        raise ValueError('排序仅支持历史价格或起飞时间')
    if budget is not None and (not math.isfinite(float(budget)) or float(budget)<=0):
        raise ValueError('预算应为正数，未知预算请留空')
    # 仅允许数据中原城市名精确匹配；景区邻近机场映射留待人工核验。
    known = c.execute('SELECT 1 FROM flights WHERE 到达城市=? LIMIT 1',(destination,)).fetchone()
    if not known:
        return {'items':[],'total':0,'reason':'目的地尚无经核对的城市/机场映射。请选择历史表原有到达城市。','mapping':'未确定'}
    query = ' FROM flights WHERE 出发日=? AND 出发城市=? AND 到达城市=?'
    params = [day,departure,destination]
    all_count = c.execute('SELECT COUNT(*)'+query,params).fetchone()[0]
    if budget is not None:
        query += ' AND 机票票价<=?'
        params.append(float(budget))
    total = c.execute('SELECT COUNT(*)'+query,params).fetchone()[0]
    items = []
    order = '机票票价,出发时间,rowid' if sort=='price' else '出发时间,机票票价,rowid'
    for raw in c.execute('SELECT rowid AS source_row,*'+query+' ORDER BY '+order+' LIMIT 100',params):
        r = dict(raw)
        r['candidate_id'] = f'FLIGHT_ROW_{r["source_row"]+1}'
        r['source'] = '01_航班信息.xlsx / 航班明细 / Excel第'+str(r['source_row']+1)+'行'
        r['delay_imputed'] = r['平均误点时间'] in (1,2,3,4,5)
        r['delay_provenance'] = '随机填补（当前文件版本规则）' if r['delay_imputed'] else '来源匹配，统计口径未知'
        r['reason'] = '日期与城市对精确匹配；'+('按历史价格升序' if sort=='price' else '按起飞时间升序')
        r['duplicate_versions'] = c.execute('SELECT COUNT(*) FROM flights WHERE 出发日=? AND 出发城市=? AND 到达城市=? AND 航空公司=? AND 航班号=? AND 出发机场=? AND 出发时间=?',(day,departure,destination,r['航空公司'],r['航班号'],r['出发机场'],r['出发时间'])).fetchone()[0]
        items.append(r)
    reason = None if items else ('同日城市对有历史记录，但均超出预算。未自动放宽条件。' if all_count else '当前日期与城市对没有历史记录。可手动更改日期或城市。')
    return {'items':items,'total':total,'before_budget':all_count,'reason':reason,'mapping':'历史城市名精确匹配，无邻近机场替换',
            'constraints':{'departure':departure,'destination':destination,'date':day,'budget':budget,'sort':sort},
            'limitations':'历史参考；未知库存、采价时间及税费；缺少跨午夜到达日期，不计算准确航程；候选多版本原样保留。'}
