"""事实约束模板适配器及带版本的人工审核，不宣称外部大模型/RAG接入。"""
from datetime import datetime
from pathlib import Path
import hashlib
import json
import sqlite3
import uuid
from algorithm_layer import profile, flight_search
from data_layer import RUNTIME, VERSION, ClosingConnection, CST


def state_db():
    RUNTIME.mkdir(exist_ok=True)
    c = sqlite3.connect(RUNTIME/'application.sqlite3',timeout=30,factory=ClosingConnection)
    c.row_factory = sqlite3.Row
    c.execute('CREATE TABLE IF NOT EXISTS drafts (id TEXT PRIMARY KEY, payload TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, draft_id TEXT, action TEXT, detail TEXT, at TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS simulations (id TEXT PRIMARY KEY, user_id TEXT, research_day TEXT, draft_id TEXT, payload TEXT)')
    c.commit()
    return c


def context_hash(context):
    return hashlib.sha256(json.dumps(context,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def log(c, draft_id, action, detail):
    c.execute('INSERT INTO audit(draft_id,action,detail,at) VALUES(?,?,?,?)',(draft_id,action,detail,datetime.now(CST).isoformat(timespec='seconds')))


def generate(c, body):
    context = body['context']
    p = profile(c,context['user'],context['asof'],int(context['window']),int(context['half']))
    if not p['record_count']:
        raise ValueError('当前截点没有画像证据，无法生成个性化草稿')
    destination = body.get('destination') or p['destinations'][0]['name']
    dest = next((d for d in p['destinations'] if d['name']==destination),None)
    if not dest:
        raise ValueError('所选目的地不在当前窗口证据中，请先确认画像')
    template = c.execute('SELECT * FROM templates WHERE destination=? AND creative_group=?',(destination,p['user']['creative_group'])).fetchone()
    facts = [{'id':rid,'type':'模拟行为','source':'02_用户行为.xlsx / 每日行为分表','text':f'截点前对{destination}的搜索过程'} for rid in dest['record_ids'][-3:]]
    if template:
        facts.append({'id':template['campaign_id'],'type':'模拟素材模板','source':'03_营销反馈.xlsx / 模拟素材','text':template['template_text']})
    theme = body.get('theme','目的地')
    if theme not in ('目的地','价格比较','行程攻略','景区酒店'):
        raise ValueError('未知内容主题')
    hour = int(body.get('hour',p['strategy']['hour']))
    if not 0<=hour<=23:
        raise ValueError('触达时段应为0—23时')
    channel = body.get('channel') or p['strategy']['channel']
    if channel not in ('百度','携程','同程','小红书','B站','飞猪'):
        raise ValueError('不支持的模拟渠道')
    title = f'{destination}，你的下一段旅程灵感'
    text = f'你近期关注了{destination}的旅行信息。我们为你整理了一份{theme}主题参考，方便继续比较和规划。'
    candidate = body.get('candidate')
    if candidate:
        try:
            row_id = int(candidate.removeprefix('FLIGHT_ROW_'))-1
        except (ValueError,AttributeError):
            raise ValueError('候选编号格式不正确')
        f = c.execute('SELECT rowid AS source_row,* FROM flights WHERE rowid=?',(row_id,)).fetchone()
        if not f or f['到达城市']!=destination:
            raise ValueError('航班候选不存在或目的地与画像不符')
        f = dict(f)
        text += f' 历史表留存了{f["出发日"]}从{f["出发城市"]}出发的{f["航班号"]}，起飞时间{f["出发时间"]}，历史参考票价¥{f["机票票价"]:,.0f}。该价格不代表当前可售报价，库存和税费未知。'
        facts.append({'id':candidate,'type':'第三方历史航班','source':f'01_航班信息.xlsx / 航班明细 / 第{row_id+1}行','text':f'{f["出发日"]} {f["出发城市"]}→{destination} {f["航班号"]} ¥{f["机票票价"]}'})
    else:
        text += ' 尚未确认航班与计划出行日，可先补充出发地、日期及预算。'
    text += ' 本内容为研究测试草稿，不含真实酒店景区承诺。'
    draft = {'id':'DRAFT_'+uuid.uuid4().hex[:12],'title':title,'text':text,'status':'待审核','revision':1,
        'context':context,'context_hash':context_hash(context),'facts':facts,'destination':destination,'theme':theme,
        'channel':channel,'hour':hour,
        'quiet_start':22,'quiet_end':8,'max_per_day':1,'opted_out':False,
        'mode':'事实约束模板生成 / 未接入LLM、公开攻略RAG和视觉模型','prompt_version':'fact-template-v1',
        'created_at':datetime.now(CST).isoformat(timespec='seconds'),'version':VERSION,'candidate':candidate}
    with state_db() as state:
        state.execute('INSERT INTO drafts VALUES(?,?)',(draft['id'],json.dumps(draft,ensure_ascii=False)))
        log(state,draft['id'],'生成','事实约束草稿 v1')
    return draft


def drafts():
    with state_db() as c:
        return [json.loads(r['payload']) for r in c.execute('SELECT * FROM drafts ORDER BY rowid DESC LIMIT 100')]


def audit():
    with state_db() as c:
        return [dict(r) for r in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 100')]


def update(draft_id, body):
    action = body['action']
    with state_db() as c:
        c.execute('BEGIN IMMEDIATE')
        row = c.execute('SELECT payload FROM drafts WHERE id=?',(draft_id,)).fetchone()
        if not row:
            raise ValueError('草稿不存在')
        d = json.loads(row[0])
        if action in ('approve','simulate') and context_hash(body['context'])!=d['context_hash']:
            raise ValueError('画像输入已变更，请根据新截点重新生成并审核')
        if action == 'edit':
            for key in ('title','text','channel','hour','quiet_start','quiet_end','max_per_day','opted_out'):
                if key in body:
                    d[key] = body[key]
            for key in ('hour','quiet_start','quiet_end'):
                d[key] = int(d[key])
                if not 0<=d[key]<=23:
                    raise ValueError('时段应为0—23时')
            d['max_per_day'] = int(d['max_per_day'])
            if not 1<=d['max_per_day']<=3:
                raise ValueError('每日频次应为1—3')
            if not d['title'].strip() or not d['text'].strip():
                raise ValueError('标题及文案不能为空')
            d['status'] = '待审核'
            d['revision'] += 1
            d.pop('review',None)
        elif action == 'approve':
            checks = body.get('checks',[])
            if set(checks)!=set(['facts','historical','synthetic']):
                raise ValueError('请逐项核对事实、历史价格和模拟属性后审核')
            d['status'] = '已审核'
            d['review'] = {'reviewer':'本机研究员','at':datetime.now(CST).isoformat(timespec='seconds'),'revision':d['revision'],'checks':checks}
        elif action == 'simulate':
            if d['status']!='已审核' or d.get('review',{}).get('revision')!=d['revision']:
                raise ValueError('当前版本须先完成人工审核')
            h,qs,qe = d['hour'],d['quiet_start'],d['quiet_end']
            quiet = (h>=qs or h<qe) if qs>qe else qs<=h<qe
            if quiet:
                raise ValueError('建议触达时间处于安静时段，请修改时间并重新审核')
            if d['opted_out']:
                raise ValueError('已标记退订，模拟触达被阻止')
            # 研究日按画像截点，不拿实际今天与历史研究日期混用。
            simday = d['context']['asof'][:10]
            count = c.execute('SELECT COUNT(*) FROM simulations WHERE user_id=? AND research_day=?',(d['context']['user'],simday)).fetchone()[0]
            if count>=d['max_per_day']:
                raise ValueError('同一用户同一研究日已达到模拟频次上限')
            d['status'] = '完成'
            d['simulation'] = {'id':'LOCAL_'+uuid.uuid4().hex[:10],'date':simday,'status':'模拟触达完成','events':['审核通过','安静时段检查通过','频次检查通过','生成本地模拟发送记录'],'limitation':'未真实发送；未生成曝光、点击或订单；不关联既有营销反馈'}
            c.execute('INSERT INTO simulations VALUES(?,?,?,?,?)',(d['simulation']['id'],d['context']['user'],simday,d['id'],json.dumps(d['simulation'],ensure_ascii=False)))
        elif action == 'stop':
            d['status'] = '停止'
        else:
            raise ValueError('不支持的草稿操作')
        c.execute('UPDATE drafts SET payload=? WHERE id=?',(json.dumps(d,ensure_ascii=False),draft_id))
        log(c,draft_id,action,'版本 '+str(d['revision'])+' / '+d['status'])
        return d
