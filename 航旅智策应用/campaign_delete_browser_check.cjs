const taskBaseUrl=process.env.AEROLENS_TEST_URL || 'http://127.0.0.1:8765';
const taskBrowserTemp=require('node:path').join(__dirname,'runtime','browser-temp');require('node:fs').mkdirSync(taskBrowserTemp,{recursive:true});process.env.TEMP=taskBrowserTemp;process.env.TMP=taskBrowserTemp;process.env.TMPDIR=taskBrowserTemp;
const {chromium}=require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const {execFileSync}=require('node:child_process');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();const ids=[];const errors=[];const checks=[];
 page.on('pageerror',e=>errors.push(e.message));
 const base=(taskBaseUrl+'/api/mkt/');
 const check=t=>{checks.push(t);console.log('PASS '+t)};
 const entry=id=>page.locator(`[data-campaign-id="${id}"]`);
 try{
  for(const name of ['删除验收_活动甲','删除验收_活动乙']){
   const response=await context.request.post(base+'campaigns',{data:{name,holiday:'national',limit:1}});
   assert.equal(response.status(),201);ids.push((await response.json()).id);
  }
  await page.goto((taskBaseUrl+'/'),{waitUntil:'networkidle'});
  await page.locator('[data-action=campaign-list]').click();
  await entry(ids[0]).locator('[data-action=load-campaign]').click();
  await page.waitForFunction(()=>document.querySelector('#context-name').textContent==='删除验收_活动甲');
  await page.locator('[data-action=campaign-list]').click();
  await entry(ids[1]).locator('[data-action=delete-campaign]').click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  await entry(ids[1]).waitFor();check('Cancel keeps the campaign intact');
  await entry(ids[1]).locator('[data-action=delete-campaign]').click();
  await page.locator('[data-action=confirm-delete-campaign]').click();
  await page.getByRole('heading',{name:'每一次营销，都有完整记录。',exact:true}).waitFor();
  await entry(ids[1]).waitFor({state:'detached'});
  assert.equal(await page.locator('#context-name').innerText(),'删除验收_活动甲');
  check('Deleting another campaign keeps the current activity open');
  await entry(ids[0]).locator('[data-action=delete-campaign]').click();
  await page.locator('[data-action=confirm-delete-campaign]').click();
  await page.waitForFunction(()=>sessionStorage.getItem('aerolens_campaign')===null);
  await page.getByRole('heading',{name:'每一次营销，都有完整记录。',exact:true}).waitFor();
  await entry(ids[0]).waitFor({state:'detached'});
  assert.equal(await page.evaluate(()=>sessionStorage.getItem('aerolens_campaign')),null);
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.locator('#context-status').innerText(),'未保存方案');
  const denied=await context.request.post(base+`campaigns/${ids[0]}/launch`,{data:{confirm:true}});
  assert.equal(denied.status(),400);check('Deleting current activity clears refresh state and blocks execution');
  await page.locator('[data-action=campaign-list]').click();
  await page.locator('[data-action=deleted-campaign-list]').click();
  await entry(ids[0]).waitFor();await entry(ids[1]).waitFor();
  await entry(ids[0]).locator('[data-action=restore-campaign]').click();
  await entry(ids[0]).waitFor({state:'detached'});
  await page.getByRole('button',{name:'返回我的活动',exact:true}).click();
  await entry(ids[0]).waitFor();assert.equal(await entry(ids[1]).count(),0);
  await entry(ids[0]).locator('[data-action=load-campaign]').click();
  await page.waitForFunction(()=>document.querySelector('#context-name').textContent==='删除验收_活动甲');
  check('Deleted list restores the original campaign and leaves other deletions untouched');
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-action=campaign-list]').click();
  await entry(ids[0]).locator('[data-action=delete-campaign]').waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(__dirname,'runtime','campaign-delete-mobile.png')});
  assert.deepEqual(errors,[]);check('Delete button fits mobile layout without browser errors');
  fs.writeFileSync(path.join(__dirname,'runtime','campaign-delete-browser-results.json'),JSON.stringify({status:'passed',checks,test_ids:ids},null,2));
 }finally{
  await browser.close();
  const python=(process.env.PYTHON || 'python');
  execFileSync(python,['-c',`import sys,json,marketing_app as a
with a.db() as c:
 for cid in json.loads(sys.argv[1]):
  row=c.execute('SELECT payload FROM campaigns WHERE id=?',(cid,)).fetchone()
  if not row:continue
  assert json.loads(row[0])['name'] in ['删除验收_活动甲','删除验收_活动乙']
  for table in ['creatives','deliveries','campaign_audit']:c.execute('DELETE FROM '+table+' WHERE campaign=?',(cid,))
  c.execute('DELETE FROM campaigns WHERE id=?',(cid,))`,JSON.stringify(ids)],{cwd:__dirname});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
