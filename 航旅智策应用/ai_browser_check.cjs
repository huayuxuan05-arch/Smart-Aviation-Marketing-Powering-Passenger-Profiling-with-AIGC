// Explicit real local-Qwen check; all sessions and plans use isolated QA state.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const out=path.join(__dirname,'runtime/tmp/ai-qa');fs.mkdirSync(out,{recursive:true});
let server,servingPid;function stop(){if(servingPid){try{process.kill(servingPid);}catch{}servingPid=null;}server?.kill();}process.on('exit',stop);
(async()=>{
 assert.equal(process.env.AEROLENS_TEST_LOCAL_AI,'1','Set AEROLENS_TEST_LOCAL_AI=1 to explicitly test the actual local model.');
 const base='http://127.0.0.1:8772';try{await fetch(base+'/api/health');throw Error('QA port is occupied');}catch(e){if(e.message.includes('occupied'))throw e;}
 server=spawn(path.join(__dirname,'.venv/Scripts/python.exe'),['-u','decision_qa_server.py'],{cwd:__dirname,windowsHide:true,stdio:'ignore',env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1',AEROLENS_QA_PORT:'8772',AEROLENS_GENERATION_MODE:'local-model'}});
 for(let i=0;i<90;i++){try{const r=await fetch(base+'/api/health');if(r.ok){servingPid=(await r.json()).process_id;break;}}catch{}if(server.exitCode!==null)throw Error('QA server exited');await new Promise(r=>setTimeout(r,500));}assert.ok(servingPid);
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));const pass=s=>{checks.push(s);console.log('PASS '+s);};
 try{
  await page.goto(base+'/personal/');await page.locator('[name=origin]').waitFor();
  await page.locator('[name=origin]').selectOption('上海');await page.locator('[name=destination]').selectOption('杭州');await page.locator('[name=start_date]').fill('2026-11-15');await page.locator('[name=days]').selectOption('4');await page.locator('[name=party]').selectOption('亲子');await page.locator('[name=trip_budget]').fill('4000');
  await page.locator('#personal-preferences [type=submit]').click();await page.locator('[data-trip-detail]').waitFor({timeout:60000});
  assert.equal(await page.locator('[data-action=trip-ai]').isEnabled(),true);assert.equal(await page.locator('.current-flight-selected').count(),0);pass('Local-model mode enables AI advice before any flight quotation is selected');
  const responsePromise=page.waitForResponse(r=>r.url().endsWith('/explain'),{timeout:180000});
  await page.locator('[data-action=trip-ai]').click();const response=await responsePromise,result=await response.json();assert.equal(response.status(),200,JSON.stringify(result));assert.match(result.ai_explanation.engine,/本地GPU/);assert.ok(result.ai_explanation.context_sha256);
  await page.locator('#trip-ai-summary').waitFor();const summary=await page.locator('#trip-ai-summary').inputValue();assert.ok(summary.length>0);assert.equal(summary,result.ai_explanation.summary);pass('Actual Qwen output reaches the API and the visible advice field without a selected flight');
  await page.reload();await page.locator('#trip-ai-summary').waitFor();assert.equal(await page.locator('#trip-ai-summary').inputValue(),summary);
  const state=await (await context.request.get(base+'/api/personal/state')).json();assert.equal(state.latest_plan.ai_explanation.summary,summary);assert.equal(state.latest_plan.budget.estimated_total,null);pass('Saved AI advice survives reload while unselected airfare remains incomplete');
  const downloadPromise=page.waitForEvent('download');await page.locator('[data-action=trip-export]').click();const download=await downloadPromise;const target=path.join(out,'plan.json');await download.saveAs(target);assert.equal(JSON.parse(fs.readFileSync(target,'utf8')).ai_explanation.summary,summary);pass('Export retains the same locally generated advice');
  await page.locator('#trip-ai-summary').screenshot({path:path.join(out,'ai-summary.png')});await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);assert.deepEqual(errors,[]);pass('AI advice fits mobile without JavaScript errors');
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({model:result.ai_explanation.model_alias,passed:checks.length,checks},null,2));
 }finally{await browser.close();stop();}
})().catch(e=>{console.error(e);process.exitCode=1;stop();});
