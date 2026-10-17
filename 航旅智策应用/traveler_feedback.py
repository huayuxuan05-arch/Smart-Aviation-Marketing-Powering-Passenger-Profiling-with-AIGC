"""Optional plan feedback: owned, versioned, fixed choices and separate sharing."""
import json
import uuid
import sqlite3

SUITABILITY=['符合需求','部分符合','不符合需求','暂无法判断']
REASONS=['价格超预算','日期不合适','航司不符合偏好','中转或耗时不合适','行程节奏不合适','暂不计划出行','其他原因']


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS personal_plan_feedback(
        id TEXT PRIMARY KEY,owner TEXT NOT NULL,plan_id TEXT NOT NULL,profile_revision INTEGER NOT NULL,
        recorded_at TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(owner,id))''')
    c.execute('CREATE INDEX IF NOT EXISTS feedback_owner_plan ON personal_plan_feedback(owner,plan_id,recorded_at)')


def submit(owner,plan_id,body):
    import personal_app as personal
    if not isinstance(body,dict):raise ValueError('评价须为对象')
    plan=personal.get_plan(owner,plan_id)
    rating=body.get('rating');suitability=body.get('suitability') or None;reasons=body.get('reasons',[])
    if rating is not None and (type(rating) is not int or not 1<=rating<=5):raise ValueError('评分请选择1至5分')
    if suitability is not None and suitability not in SUITABILITY:raise ValueError('请选择支持的符合程度')
    if not isinstance(reasons,list) or len(reasons)>len(REASONS) or any(type(r) is not str or r not in REASONS for r in reasons) or len(set(reasons))!=len(reasons):raise ValueError('请选择支持的原因')
    if rating is None and suitability is None and not reasons:raise ValueError('请至少填写一项评价，也可以直接跳过')
    share=body.get('share_feedback',False)
    if type(share) is not bool:raise ValueError('请自主选择是否匿名共享评价')
    ident=body.get('submission_id')
    try:uuid.UUID(ident)
    except (ValueError,TypeError,AttributeError):raise ValueError('评价提交编号无效，请刷新后重试') from None
    payload={'rating':rating,'suitability':suitability,'reasons':reasons,'share_feedback':share}
    with personal.db() as c:
        previous=c.execute('SELECT plan_id,payload FROM personal_plan_feedback WHERE id=? AND owner=?',(ident,owner)).fetchone()
        if previous:
            if previous['plan_id']!=plan_id or json.loads(previous['payload'])!=payload:raise ValueError('该提交编号已使用，请重新提交')
            return {'recorded':True,'duplicate':True}
        consent=personal.real_travelers.consent_view(c,owner)
        if share and not consent['enabled']:raise ValueError('匿名共享评价前，请先自主开启画像共享；也可以仅保存评价')
        try:c.execute('INSERT INTO personal_plan_feedback VALUES(?,?,?,?,?,?)',(ident,owner,plan_id,plan['profile_revision'],personal.now(),json.dumps(payload,ensure_ascii=False)))
        except sqlite3.IntegrityError:raise ValueError('评价提交编号已使用，请重新提交') from None
        if share:personal.real_travelers.record_event(c,owner,'plan_feedback',plan['destination'],{'plan_id':plan_id,'profile_revision':plan['profile_revision']})
    return {'recorded':True,'duplicate':False}


def latest(c,owner,shared_only=False):
    rows=c.execute('SELECT plan_id,profile_revision,recorded_at,payload FROM personal_plan_feedback WHERE owner=? ORDER BY recorded_at DESC,rowid DESC',(owner,)).fetchall()
    seen=set();result=[]
    for row in rows:
        if row['plan_id'] in seen:continue
        seen.add(row['plan_id']);payload=json.loads(row['payload'])
        if shared_only and not payload.get('share_feedback'):continue
        result.append({'plan_id':row['plan_id'],'profile_revision':row['profile_revision'],'recorded_at':row['recorded_at'],**payload})
    return result


def withdraw(c,owner):
    # Keep the participant's private history, revoke every previous sharing flag.
    for row in c.execute('SELECT id,payload FROM personal_plan_feedback WHERE owner=?',(owner,)).fetchall():
        value=json.loads(row['payload'])
        if value.get('share_feedback'):
            value['share_feedback']=False;c.execute('UPDATE personal_plan_feedback SET payload=? WHERE id=?',(json.dumps(value,ensure_ascii=False),row['id']))
