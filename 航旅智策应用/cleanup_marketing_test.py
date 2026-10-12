"""只清理浏览器验收报告明确列出的活动；不会按名称批量删除。"""
import json,sys
from pathlib import Path
import marketing_app as app

def cleanup(cid):
 with app.db() as c:
  row=c.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()
  if not row:return
  p=json.loads(row[0])
  if p['name']!='闭环验收_国庆营销':raise ValueError('不是指定验收活动，拒绝清理')
  for table in ['deliveries','creatives','campaign_audit']:
   c.execute(f'DELETE FROM {table} WHERE campaign=?',(cid,))
  c.execute('DELETE FROM campaigns WHERE id=?',(cid,))

if __name__=='__main__':
 ids=sys.argv[1:]
 if not ids:
  report=Path(__file__).parent/'runtime'/'marketing-browser-results.json'
  if report.exists():ids=[json.loads(report.read_text(encoding='utf-8')).get('test_campaign_id')]
 for cid in filter(None,ids):cleanup(cid)
