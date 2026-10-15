"""真实问卷独立证据层；原表只读，逐字段审计，不补造身份、行为或交易标签。"""
from collections import Counter
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import json
import shutil

from data_layer import BASE, RUNTIME, CST

STORE = RUNTIME / 'survey'
FEATURES = ['Q05','Q07','Q09','Q10','Q11','Q12','Q16','Q17','Q18','Q19']


def schema():
    return json.loads((BASE/'web/marketing/survey-schema.json').read_text(encoding='utf-8'))


def parse_answer(value, question):
    if value is None or value == '':return None, 'missing'
    try:
        if isinstance(value,str):value=json.loads(value.strip())
        values=value if isinstance(value,list) else [value]
        if not values:return None,'missing'
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or int(x)!=x for x in values):return None,'invalid_code'
        values=[int(x) for x in values]
        if any(x<1 or x>len(question['options']) for x in values):return None,'invalid_code'
        if len(values)!=len(set(values)):return None,'duplicate_option'
        if question['type']=='single' and len(values)!=1:return None,'single_multiple'
        if len(values)>question.get('max_choices',1):return None,'too_many'
        if len(values)>1 and set(values)&set(question.get('exclusive',[])):return None,'exclusive_conflict'
        return sorted(values),None
    except (ValueError,TypeError,OverflowError):return None,'invalid_code'


def audit(records, cutoff):
    spec=schema();questions={q['id']:q for q in spec['questions']}
    clean=[];seen=set();counts=Counter();field_issues={k:Counter() for k in questions}
    for raw in records:
        rid=str(raw.get('response_id') or '').strip();person=str(raw.get('research_id') or rid).strip()
        issues={};answers={}
        for key,q in questions.items():
            answers[key],error=parse_answer(raw.get(key),q)
            if error and (error!='missing' or q.get('required')):issues[key]=error
        # 跳题回答不作为经历痛点；原值仍留在原始工作簿中。
        if answers['Q03']==[1]:
            if raw.get('Q04') not in (None,''):issues['Q04']='skip_violation'
            answers['Q04']=None
        cities=answers['Q13'];places=answers['Q14']
        if cities and places:
            allowed={questions['Q13']['options'][x-1] for x in cities if x<=16}
            if any(questions['Q14']['option_cities'][x-1] not in allowed for x in places if x<=32):
                answers['Q14']=None;issues['Q14']='city_attraction_conflict'
        if answers['Q07']==[1] and answers['Q08'] and answers['Q08'][0] in (2,3,4,5):
            issues['party_size']='needs_confirmation'
        date=raw.get('submitted_at',raw.get('填写时间'))
        if date is None:date=raw.get('_time')
        try:
            date=date if isinstance(date,datetime) else datetime.fromisoformat(str(date))
            if date.tzinfo is None:date=date.replace(tzinfo=CST)
            stamp=date.isoformat()
            if date>cutoff:issues['time']='future_timestamp'
        except (TypeError,ValueError):stamp=None;issues['time']='invalid_timestamp'
        eligibility=answers['Q01']==[1] and answers['Q02']==[1]
        if not eligibility:issues['eligibility']='no_consent_or_adult'
        if not rid:issues['identity']='missing_response_id'
        elif rid in seen:issues['identity']='duplicate_response_id'
        seen.add(rid)
        usable=eligibility and 'identity' not in issues and 'time' not in issues
        counts['raw_rows']+=1
        if usable:counts['eligible_rows']+=1
        if usable and not issues:counts['strict_rows']+=1
        if usable and 'exclusive_conflict' in issues.values():counts['exclusive_conflict_rows']+=1
        if usable and issues:counts['rows_with_issues']+=1
        for key,error in issues.items():
            counts[error]+=1
            if key in field_issues:field_issues[key][error]+=1
        clean.append({'key':hashlib.sha256(person.encode()).hexdigest(),'submitted_at':stamp,'usable':usable,
                      'answers':answers,'issues':issues})
    usable=[r for r in clean if r['usable']]
    distributions={}
    for key,q in questions.items():
        answered=[r['answers'][key] for r in usable if r['answers'][key] is not None]
        c=Counter(x for values in answered for x in values)
        distributions[key]={'label':q['label'],'denominator':len(answered),'multi':q['type']=='multi',
            'options':[{'code':i,'label':label,'count':c[i],'share':c[i]/len(answered) if answered else None} for i,label in enumerate(q['options'],1)],
            'issues':dict(field_issues[key])}
    people=Counter(r['key'] for r in usable)
    summary={'schema_version':spec['version'],'asof':cutoff.isoformat(),'counts':dict(counts),
        'distinct_research_ids':len(people),'repeated_research_ids':sum(n>1 for n in people.values()),
        'distributions':distributions,
        'basis':'用户确认为一手收集且未经过人工整理的1000份问卷，属于自报偏好。逐题有效分母；多选占比不合计为100%。未来时间与无同意/未成年记录不进入统计及训练；冲突字段置为未知，不猜答案。',
        'longitudinal':'Q23至Q25为一次填答中的回忆自报，不是已观测行为轨迹。重复研究编号的多次有效答卷才可构成动态追踪。'}
    summary['time_basis']='原表未注明时区，按北京时间解释；统计基准固定为本批导入asof，超前时间待核对设备时钟或导出时区。'
    return clean,summary


def features(row):
    return {f'{key}:{v}':1.0 for key in FEATURES for v in row['answers'].get(key) or [0]}


def train(rows):
    """按研究编号分组且按时间后推留出；不使用目标Q13、景点Q14和回忆城市Q23-25作为特征。"""
    import numpy as np
    from sklearn.feature_extraction import DictVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import make_pipeline
    import joblib
    eligible=[r for r in rows if r['usable'] and r['answers']['Q13'] and all(x<=16 for x in r['answers']['Q13'])
              and all(r['answers'][k] is not None for k in FEATURES)]
    grouped={}
    for r in eligible:grouped.setdefault(r['key'],[]).append(r)
    groups=sorted(grouped,key=lambda k:max(r['submitted_at'] for r in grouped[k]))
    report={'target':'Q13明确选择的16个城市，多选无排序；不是购票/转化标签','features':FEATURES,
            'excluded_features':['Q13','Q14','Q23','Q24','Q25'],'eligible_training_rows':len(eligible),
            'split':'按研究编号分组，以该组最晚提交时间排序；最早60%训练，中间20%验证，最新20%测试。各期编号不重叠。',
            'seed':20261015,'gate':'验证和测试Recall@3均高于训练集全局热门基线至少0.01，且测试集按研究编号配对自助法95%差值区间下界大于0；线上字段完备后才可启用。',
            'promoted':False}
    if len(groups)<80:report['reason']='有效独立编号不足80，不训练';return report,None
    # 每个编号只取最新一次合格测量，避免同一人多波答卷重复加权。
    grouped={k:[max(v,key=lambda r:r['submitted_at'])] for k,v in grouped.items()}
    a=int(len(groups)*.6);b=int(len(groups)*.8)
    parts=[[r for k in ids for r in grouped[k]] for ids in (groups[:a],groups[a:b],groups[b:])]
    def target(rs):
        y=np.zeros((len(rs),16),dtype=int)
        for i,r in enumerate(rs):y[i,np.array(r['answers']['Q13'])-1]=1
        return y
    x=[list(map(features,p)) for p in parts];y=list(map(target,parts));pop=y[0].mean(axis=0)
    def recall(scores,truth):
        top=np.argsort(-scores,axis=1,kind='stable')[:,:3]
        return float(np.mean([truth[i,top[i]].sum()/truth[i].sum() for i in range(len(truth))]))
    candidates=[]
    for strength in (.05,.2,1.0):
        model=make_pipeline(DictVectorizer(),OneVsRestClassifier(LogisticRegression(C=strength,max_iter=1000,random_state=20261015)))
        model.fit(x[0],y[0]);score=recall(model.predict_proba(x[1]),y[1]);candidates.append((score,strength,model))
    val,strength,model=max(candidates,key=lambda x:x[0])
    test=recall(model.predict_proba(x[2]),y[2])
    baseline_val=recall(np.tile(pop,(len(y[1]),1)),y[1]);baseline_test=recall(np.tile(pop,(len(y[2]),1)),y[2])
    prediction=np.argsort(-model.predict_proba(x[2]),axis=1,kind='stable')[:,:3];base_top=np.argsort(-pop,kind='stable')[:3]
    differences={}
    for i,r in enumerate(parts[2]):
        differences.setdefault(r['key'],[]).append(float((y[2][i,prediction[i]].sum()-y[2][i,base_top].sum())/y[2][i].sum()))
    group_diff=np.array([np.mean(v) for v in differences.values()]);rng=np.random.default_rng(20261015)
    boot=np.mean(rng.choice(group_diff,size=(2000,len(group_diff)),replace=True),axis=1);low,high=map(float,np.quantile(boot,[.025,.975]))
    gate_passed=val>=baseline_val+.01 and test>=baseline_test+.01 and low>0
    report.update({'train_rows':len(parts[0]),'validation_rows':len(parts[1]),'test_rows':len(parts[2]),'selected_C':strength,
        'validation_recall_at_3':val,'test_recall_at_3':test,'baseline_validation_recall_at_3':baseline_val,
        'baseline_test_recall_at_3':baseline_test,'validation_trials':[{'C':c,'recall_at_3':s} for s,c,m in candidates],
        'train_until':max(r['submitted_at'] for r in parts[0]),'test_from':min(r['submitted_at'] for r in parts[2]),
        'test_recall_gain_95ci':[low,high],'gate_passed':gate_passed,'promoted':False})
    report['reason']='离线通过门槛，但个人入口尚未采集全部模型字段，暂保留影子模型；线上只采用透明样本先验及用户约束' if gate_passed else '未通过完整门槛，保持影子模型；线上只采用透明样本先验及用户约束，不覆盖旅客主动偏好'
    STORE.mkdir(parents=True,exist_ok=True);joblib.dump(model,STORE/'preference_shadow.joblib')
    return report,model


def public_summary():
    path=STORE/'summary.json'
    if not path.exists():return {'available':False,'basis':'尚未导入问卷证据'}
    return {'available':True,**json.loads(path.read_text(encoding='utf-8'))}


def destination_prior():
    """样本先验只用于无明确城市时打破同等条件并列，不是个人画像或购买概率。"""
    summary=public_summary()
    if not summary['available']:return {}
    return {v['label']:v['share'] for v in summary['distributions']['Q13']['options'][:16]}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('workbook',type=Path);parser.add_argument('--asof');parser.add_argument('--source-note',default='用户提供的一手问卷');args=parser.parse_args()
    import openpyxl
    path=args.workbook.resolve();book=openpyxl.load_workbook(path,read_only=True,data_only=True)
    expected=[f'Q{x:02}' for x in range(1,31)]
    sheet=None;it=None;headers=None
    for candidate in book:
        stream=candidate.values
        for _ in range(6):
            h=list(next(stream,[]))
            if 'response_id' in h and all(k in h for k in expected):sheet=candidate;it=stream;headers=h;break
        if sheet is not None:break
    if sheet is None:raise ValueError('未找到含Q01至Q30及response_id表头的数据页')
    if any(headers.count(k)!=1 for k in expected) or 'response_id' not in headers or 'research_id' not in headers:
        raise ValueError('工作簿必须包含唯一Q01至Q30及答卷/研究编号列')
    records=[]
    for values in it:
        if not any(v is not None for v in values):continue
        raw=dict(zip(headers,values));raw['_time']=raw.get('submitted_at',raw.get('填写时间',values[2]));records.append(raw)
    book.close();cutoff=datetime.fromisoformat(args.asof) if args.asof else datetime.now(CST)
    if cutoff.tzinfo is None:cutoff=cutoff.replace(tzinfo=CST)
    rows,summary=audit(records,cutoff)
    summary['source']={'filename':path.name,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sheet':sheet.title,'rows':len(records),'note':args.source_note}
    previous=STORE/'summary.json'
    if previous.exists():
        old=json.loads(previous.read_text(encoding='utf-8'));old_hash=old['source']['sha256']
        if old_hash!=summary['source']['sha256']:
            history=STORE/'batches'/old_hash[:16];history.mkdir(parents=True,exist_ok=True)
            for name in ['summary.json','responses.private.json','workbook.private.json','preference_shadow.joblib']:
                if (STORE/name).exists():shutil.copy2(STORE/name,history/name)
            old_report=BASE.parent/'问卷资料/问卷证据分析与方案更新.html'
            if old_report.exists():shutil.copy2(old_report,history/'analysis.html')
            old_book=BASE.parent/'问卷资料/outputs/survey-20261015/华翼朝阳_问卷整理与核对.xlsx'
            if old_book.exists():shutil.copy2(old_book,history/'review.xlsx')
    summary['basis']='用户确认为一手收集的问卷。本批来源说明：'+args.source_note+'。逐题有效分母；多选占比不合计为100%。未来时间与无同意/未成年记录不进入统计及训练；冲突字段置为未知，不猜答案。'
    summary['model'],_=train(rows)
    STORE.mkdir(parents=True,exist_ok=True)
    (STORE/'responses.private.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    (STORE/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    (STORE/'workbook.private.json').write_text(json.dumps({'records':records,'rows':rows,'summary':summary,'schema':schema()},ensure_ascii=False,default=str),encoding='utf-8')
    # 聚合报告可审阅，绝不输出个体研究编号或逐人答案。
    out=BASE.parent/'问卷资料/问卷证据分析与方案更新.html'
    import html
    lines=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>华翼朝阳 · 问卷证据与方案更新</title><style>body{max-width:1080px;margin:40px auto;padding:20px;font:15px/1.8 Microsoft YaHei;color:#233253}h1,h2{color:#172d75}table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border-bottom:1px solid #ddd;text-align:left;padding:9px}pre{white-space:pre-wrap;background:#f5f6fc;padding:18px}.note{background:#f2effc;padding:20px}</style>',
        '<h1>华翼朝阳：问卷证据与方案更新</h1>',f'<p>审计时间 {html.escape(summary["asof"])} · 原表SHA256 {summary["source"]["sha256"]}</p>',
        f'<p class="note">{html.escape(summary["basis"])}</p>',f'<pre>{html.escape(json.dumps(summary["counts"],ensure_ascii=False,indent=2))}</pre>',
        '<h2>推荐模型验证</h2>',f'<pre>{html.escape(json.dumps(summary["model"],ensure_ascii=False,indent=2))}</pre>',
        '<h2>需求发现及实施策略</h2>']
    d=summary['distributions']
    for text in [f'4至5天行程为{d["Q17"]["options"][2]["count"]}/{d["Q17"]["denominator"]}（{d["Q17"]["options"][2]["share"]:.1%}）；个人入口扩展为2至8天，保留每一天抵达、活动与返程安排。',
        f'天数未定{d["Q17"]["options"][5]["count"]}/{d["Q17"]["denominator"]}，预算未定{d["Q18"]["options"][5]["count"]}/{d["Q18"]["denominator"]}，Q13不计划出游{d["Q13"]["options"][18]["count"]}/{d["Q13"]["denominator"]}；增加先收集灵感、暂不计划出游的意向保存方式，允许日期、天数、预算留空，不强制生成行程或把未定当作确定需求。',
        f'每名成人2000至6000元预算合计{d["Q18"]["options"][1]["count"]+d["Q18"]["options"][2]["count"]}/{d["Q18"]["denominator"]}；保留区间原义，绝不用区间中点代替个人上限。网页由旅客明确填写上限，逐项展示历史参考和费用情景。',
        f'希望展示推荐理由为{d["Q28"]["options"][6]["count"]}/{d["Q28"]["denominator"]}，预约清单为{d["Q28"]["options"][4]["count"]}/{d["Q28"]["denominator"]}，可编辑方案为{d["Q28"]["options"][7]["count"]}/{d["Q28"]["denominator"]}；优先建设依据、预约、备选与可更新的详细行程。',
        f'超预算优先调日期为{d["Q22"]["options"][0]["count"]}/{d["Q22"]["denominator"]}，降低住宿及付费体验为{d["Q22"]["options"][1]["count"]}/{d["Q22"]["denominator"]}；分别采集处理顺序及日期许可，确认前不改变城市或日期。',
        f'Q29未看过Demo者为{d["Q29"]["options"][5]["count"]}/{d["Q29"]["denominator"]}，不纳入满意度分母。问卷有效独立编号{summary["distinct_research_ids"]}个，重复编号{summary["repeated_research_ids"]}个；本批不能验证动态画像更新效果。',
        '优先采用本次明确选择；仅在“为我推荐”中以问卷城市热度作同条件并列参考。往返航线完整性与用户预算约束优先，超预算明确提示。具体景点、住宿条件、日期弹性、备选许可与超预算处理进入偏好版本、逐日规划及本地AI说明。营销端独立展示问卷证据，不将其混入万人模拟客群或营销授权。']:
        lines.append('<p>'+html.escape(text)+'</p>')
    lines += [
        f'<p>{html.escape(summary["longitudinal"])}</p>',
        '<h2>后续更新</h2><p>请核对互斥项冲突、独行与人数冲突、填写时间及招募渠道。只回访Q30同意者，Q30不等于营销授权。假期前30/14/7天与出游后约7天按同一研究编号重复测量；明确区分年份、假期与实际出发日期，不把回忆关注当行为日志。新增答卷重新执行同一审计及分组后推验证，通过门槛才升级预测模型。报告仅描述本样本，不推断全国旅客分布或真实成交提升。</p>']
    for k,d in summary['distributions'].items():
        lines.append(f'<h2>{k} {html.escape(d["label"])}</h2><p>有效分母 {d["denominator"]}；字段问题 {html.escape(json.dumps(d["issues"],ensure_ascii=False))}</p><table><tr><th>选项</th><th>人数</th><th>占本题有效答卷</th></tr>')
        for v in sorted(d['options'],key=lambda x:-x['count']):lines.append(f'<tr><td>{html.escape(v["label"])}</td><td>{v["count"]}</td><td>{v["share"]:.1%}</td></tr>' if v['share'] is not None else '')
        lines.append('</table>')
    out.write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({'counts':summary['counts'],'distinct_research_ids':summary['distinct_research_ids'],'model':summary['model'],'report':str(out)},ensure_ascii=False))


if __name__=='__main__':main()
