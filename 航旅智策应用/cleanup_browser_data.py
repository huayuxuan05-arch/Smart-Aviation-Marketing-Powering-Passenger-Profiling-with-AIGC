"""只清理浏览器验收清单明确列出且带测试标记的草稿，不处理其他草稿。"""
import json
from data_layer import RUNTIME
from aigc_layer import state_db

report=json.loads((RUNTIME/'browser-test-results.json').read_text(encoding='utf-8'))
ids=set(report.get('previous_test_draft_ids',[])+[report.get('test_draft_id')])-{None}
removed=[]
with state_db() as c:
    c.execute('BEGIN IMMEDIATE')
    for draft_id in ids:
        row=c.execute('SELECT payload FROM drafts WHERE id=?',(draft_id,)).fetchone()
        if not row:
            continue
        draft=json.loads(row[0])
        if '研究测试用草稿。' not in draft['text'] or draft['context']['user']!='SIMU_00006':
            raise RuntimeError('不符合浏览器测试标记，保留该草稿：'+draft_id)
        c.execute('DELETE FROM simulations WHERE draft_id=?',(draft_id,))
        c.execute('DELETE FROM audit WHERE draft_id=?',(draft_id,))
        c.execute('DELETE FROM drafts WHERE id=?',(draft_id,))
        removed.append(draft_id)
report['cleaned_test_draft_ids']=sorted(removed)
(RUNTIME/'browser-test-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('仅清理本轮验收明确记录的测试草稿：'+', '.join(removed))
