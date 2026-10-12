"""评估层：原始模拟营销反馈的截点回放；活动评估在marketing_app.py。"""
from algorithm_layer import cutoff


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
