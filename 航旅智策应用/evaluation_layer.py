"""冻结规则在完整未来窗口下的描述性评价，不推断真实购票。"""
from collections import Counter
from datetime import timedelta
import math
from algorithm_layer import cutoff, history, profile, METHOD
from data_layer import VERSION


def evaluate(c, as_of='2024-10-01', horizon=7, sample=100, window=30, half=14):
    t = cutoff(as_of)
    horizon, sample = int(horizon),int(sample)
    if horizon not in (7,14) or not 10<=sample<=500:
        raise ValueError('未来窗口支持7/14天，用户数支持10—500')
    end = t+timedelta(days=horizon)
    if t.month<10 or end>cutoff('2024-12-31'):
        raise ValueError('测试截点须位于2024年10—12月，且未来窗口须完整留在年内')
    users = [r[0] for r in c.execute('SELECT user_id FROM users ORDER BY user_id LIMIT ?',(sample,))]
    results = {k:{'recall':0.,'ndcg':0.,'hit':0} for k in ['最近一次关注','窗口历史频次','动态时间衰减','固定六月画像']}
    failures = []
    zero = 0
    for uid in users:
        rows = history(c,uid,end)
        old = [r for r in rows if r['search_at_cst']<=str(t)]
        future = {r['destination'] for r in rows if str(t)<r['search_at_cst']<=str(end)}
        if not future:
            zero += 1
            continue
        p = profile(c,uid,str(t),window,half,old)
        fixed = profile(c,uid,'2024-06-30',window,half,old)
        freq = Counter(r['destination'] for r in old if r['search_at_cst']>str(t-timedelta(days=window)))
        predictions = {
            '最近一次关注':list(dict.fromkeys(r['destination'] for r in reversed(old)))[:3],
            '窗口历史频次':[k for k,v in sorted(freq.items(),key=lambda kv:(-kv[1],kv[0]))[:3]],
            '动态时间衰减':[d['name'] for d in p['destinations'][:3]],
            '固定六月画像':[d['name'] for d in fixed['destinations'][:3]]}
        for method, pred in predictions.items():
            hits = len(set(pred)&future)
            dcg = sum(1/math.log2(i+2) for i,d in enumerate(pred) if d in future)
            ideal = sum(1/math.log2(i+2) for i in range(min(3,len(future))))
            results[method]['recall'] += hits/len(future)
            results[method]['ndcg'] += dcg/ideal
            results[method]['hit'] += int(hits>0)
        if not set(predictions['动态时间衰减'])&future and len(failures)<10:
            failures.append({'user_id':uid,'predicted':predictions['动态时间衰减'],'future':sorted(future)})
    n = len(users)-zero
    metrics = [{'method':k,'recall_at_3':round(v['recall']/n,4) if n else None,'ndcg_at_3':round(v['ndcg']/n,4) if n else None,'hit_users':v['hit'],'denominator':n} for k,v in results.items()]
    return {'metrics':metrics,'sample':len(users),'zero_relevance':zero,'as_of_time':str(t),'future_end':str(end),'horizon':horizon,
        'window':window,'half_life':half,'method_version':METHOD,'data_version':VERSION,'failures':failures,
        'protocol':'test-proxy-v1；用户按ID升序确定性取前N名；相同41个目的地集合；未来窗口至少搜索一次为二元相关；逐用户宏平均；所有方法取Top3。最近一次基线按最近关注顺序取三个不同目的地。',
        'split':{'warmup':'2023-12','train':'2024-01—06','validation':'2024-07—09','test':'2024-10—12'},
        'limitation':'规则预先声明，尚未进行训练或调参；页面修改参数属于探索比较。模拟代理标签，非真实购票；该确定性子样本不代表总体，无因果结论。'}


def marketing(c,uid,as_of):
    t = str(cutoff(as_of))
    params = [t]
    clause = 'event_time_cst<=?'
    if uid:
        clause += ' AND user_id=?'
        params.append(uid)
    counts = {r[0]:r[1] for r in c.execute('SELECT feedback_type,COUNT(DISTINCT push_id) FROM events WHERE '+clause+' GROUP BY feedback_type',params)}
    effective = c.execute('SELECT COUNT(DISTINCT push_id) FROM events WHERE '+clause+' AND feedback_type="exposure" AND measure_value>=2000',params).fetchone()[0]
    send,exposure,click,pay,refund = [counts.get(k,0) for k in ('send','exposure','click','mock_paid','mock_refund')]
    counts['effective_exposure'] = effective
    def ratio(num,den):
        return {'numerator':num,'denominator':den,'value':round(num/den*100,2) if den else None}
    order_sql = 'SELECT * FROM orders WHERE created_at_cst<=?'
    if uid:
        order_sql += ' AND user_id=?'
    orders = [dict(r) for r in c.execute(order_sql,params)]
    # 按截至当时的支付/退款时刻重建金额和状态，不读取未来状态。
    for o in orders:
        paid = bool(o['paid_at_cst'] and o['paid_at_cst']<=t)
        refunded = bool(o['refunded_at_cst'] and o['refunded_at_cst']<=t)
        o['mock_paid_cny'] = o['mock_paid_cny'] if paid else 0
        o['mock_refund_cny'] = o['mock_refund_cny'] if refunded else 0
        cancelled = c.execute('SELECT 1 FROM events WHERE push_id=? AND feedback_type="mock_cancel" AND event_time_cst<=? LIMIT 1',(o['push_id'],t)).fetchone()
        o['status'] = 'mock_refunded' if refunded else 'mock_paid' if paid else 'mock_cancelled' if cancelled else 'mock_created'
        if not paid:
            o['paid_at_cst'] = None
        if not refunded:
            o['refunded_at_cst'] = None
    pushes = [dict(r) for r in c.execute('SELECT * FROM pushes WHERE sent_at_cst<=?'+(' AND user_id=?' if uid else '')+' ORDER BY sent_at_cst DESC LIMIT 30',params)]
    for p in pushes:
        p['events'] = [dict(e) for e in c.execute('SELECT * FROM events WHERE push_id=? AND event_time_cst<=? ORDER BY event_time_cst,feedback_id',(p['push_id'],t))]
    return {'counts':counts,'as_of_time':t,'scope':uid or '全部10000名模拟用户','pushes':pushes,'orders':orders,
        'net_mock_paid':round(sum(o['mock_paid_cny']-o['mock_refund_cny'] for o in orders),2),
        'rates':{'effective_ctr':ratio(click,effective),'all_exposure_ctr':ratio(click,exposure),'click_to_paid':ratio(pay,click),'send_to_paid':ratio(pay,send),'refund_rate':ratio(refund,pay),'unsubscribe_rate':ratio(counts.get('unsubscribe',0),send)},
        'limitation':'基础模拟情景；事件按push_id去重；截至截点回放尚未统一成熟观察窗口，不作策略因果比较；模拟订单未关联真实航班。'}
