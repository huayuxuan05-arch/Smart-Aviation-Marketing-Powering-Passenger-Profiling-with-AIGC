const path=require('node:path'),fs=require('node:fs');
const temp=path.join(__dirname,'runtime','browser-temp');fs.mkdirSync(temp,{recursive:true});
process.env.TEMP=temp;process.env.TMP=temp;process.env.TMPDIR=temp;process.env.PYTHONDONTWRITEBYTECODE='1';
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert=require('node:assert/strict'),{execFileSync}=require('node:child_process');
(async()=>{
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage();
 const base='http://127.0.0.1:8765/api/mkt/',errors=[],checks=[];let cid;
 page.on('pageerror',e=>errors.push(e.message));
 const pass=t=>{checks.push(t);console.log('PASS '+t)};
 try{
  const created=await context.request.post(base+'campaigns',{data:{name:'素材删除专项验收',holiday:'national',limit:30}});
  assert.equal(created.status(),201);const campaign=await created.json();cid=campaign.id;
  const user=campaign.audience.find(x=>x.theme==='目的地信息')||campaign.audience[0],materials=[];
  for(let i=0;i<2;i++){
   const response=await context.request.post(base+`campaigns/${cid}/creatives`,{data:{user_id:user.user_id},timeout:150000});
   assert.equal(response.status(),201);materials.push(await response.json());
  }
  await page.goto('http://127.0.0.1:8765/',{waitUntil:'networkidle'});
  await page.locator('[data-action=campaign-list]').click();
  await page.locator(`[data-campaign-id="${cid}"] [data-action=load-campaign]`).click();
  await page.waitForFunction(()=>document.querySelector('#context-name').textContent==='素材删除专项验收');
  await page.goto('http://127.0.0.1:8765/#creative',{waitUntil:'networkidle'});
  await page.locator(`[data-action=choose-creative][data-id="${materials[0].id}"]`).click();
  await page.locator('[data-action=delete-creative]').click();
  await page.getByRole('button',{name:'取消',exact:true}).click();
  assert.equal(await page.locator('[data-action=choose-creative]').count(),2);pass('Cancel preserves the selected pending material');
  await page.locator('[data-action=delete-creative]').click();
  await page.locator('[data-action=confirm-delete-creative]').click();
  await page.locator(`[data-action=choose-creative][data-id="${materials[0].id}"]`).waitFor({state:'detached'});
  await page.locator(`[data-action=choose-creative][data-id="${materials[1].id}"]`).waitFor();
  assert.equal(await page.locator('#context-name').innerText(),'素材删除专项验收');
  const denied=await context.request.post(base+`campaigns/${cid}/creatives/${materials[0].id}`,{data:{action:'approve',checks:['facts','historical','synthetic']}});
  assert.equal(denied.status(),400);pass('Deletion removes only the selected material and prevents later approval');
  await page.reload({waitUntil:'networkidle'});
  assert.equal(await page.locator('[data-action=choose-creative]').count(),1);pass('Deletion persists after refresh');
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-action=delete-creative]').click();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
  await page.screenshot({path:path.join(__dirname,'runtime','creative-delete-mobile.png')});
  await page.locator('[data-action=confirm-delete-creative]').click();
  await page.getByText('第一条创意，从理解旅客开始',{exact:true}).waitFor();
  assert.equal(await page.locator('[data-action=choose-creative]').count(),0);pass('Deleting the last material returns to an empty studio on mobile');
  const current=await (await context.request.get(base+'campaigns/'+cid)).json();
  assert.deepEqual(current.audience,campaign.audience);assert.equal(current.creatives.length,0);assert.equal(current.deliveries.length,0);
  assert.deepEqual(errors,[]);pass('Audience remains intact and browser reports no errors');
  fs.writeFileSync(path.join(__dirname,'runtime','creative-delete-browser-results.json'),JSON.stringify({status:'passed',checks,test_campaign:cid},null,2));
 }finally{
  await browser.close();
  if(cid)execFileSync(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'),['-c',`import sys,json,marketing_app as a
with a.db() as c:
 row=c.execute('SELECT payload FROM campaigns WHERE id=?',(sys.argv[1],)).fetchone()
 assert row and json.loads(row[0])['name']=='素材删除专项验收'
 for table in ['creatives','deliveries','campaign_audit']:c.execute('DELETE FROM '+table+' WHERE campaign=?',(sys.argv[1],))
 c.execute('DELETE FROM campaigns WHERE id=?',(sys.argv[1],))`,cid],{cwd:__dirname});
 }
})().catch(e=>{console.error(e);process.exitCode=1});
