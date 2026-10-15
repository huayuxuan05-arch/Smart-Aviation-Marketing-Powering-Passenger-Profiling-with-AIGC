const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE||path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const out=path.join(__dirname,'runtime/tmp/flight-qa');fs.mkdirSync(out,{recursive:true});
let server,servingPid;function stop(){if(servingPid){try{process.kill(servingPid);}catch{}servingPid=null;}server?.kill();}process.on('exit',stop);
(async()=>{
 const base='http://127.0.0.1:8771';try{await fetch(base+'/api/health');throw Error('QA port is occupied');}catch(e){if(e.message.includes('occupied'))throw e;}
 server=spawn(path.join(__dirname,'.venv/Scripts/python.exe'),['-u','decision_qa_server.py'],{cwd:__dirname,windowsHide:true,stdio:'ignore',env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1',AEROLENS_QA_PORT:'8771',AEROLENS_TEST_FLIGHT_FIXTURE:'1'}});
 for(let i=0;i<90;i++){try{const r=await fetch(base+'/api/health');if(r.ok){servingPid=(await r.json()).process_id;break;}}catch{}if(server.exitCode!==null)throw Error('QA server exited');await new Promise(r=>setTimeout(r,500));}assert.ok(servingPid);
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),checks=[],errors=[];
 page.on('pageerror',e=>errors.push(e.message));const pass=s=>{checks.push(s);console.log('PASS '+s);};
 try{
  await page.goto(base+'/personal/');await page.locator('[name=origin]').waitFor();
  await page.locator('[name=origin]').selectOption('上海');await page.locator('[name=destination]').selectOption('广州');await page.locator('[name=start_date]').fill('2026-10-20');await page.locator('[name=days]').selectOption('4');await page.locator('[name=party]').selectOption('朋友');await page.locator('[name=trip_budget]').fill('2000');
  await page.locator('#personal-preferences [type=submit]').click();await page.locator('.current-flight-option').first().waitFor({timeout:60000});
  assert.equal(await page.locator('[data-flight-reference]').count(),0);assert.ok(!(await page.locator('#personal-result').innerText()).includes('历史参考'));pass('Existing itinerary automatically matches current flights without displaying training flights');
  const first=(await (await context.request.get(base+'/api/personal/state')).json()).latest_plan;
  await page.locator('[data-flight-adults]').selectOption('2');await page.waitForFunction(()=>document.querySelector('.current-flight-total')?.textContent.includes('2名成人'));
  await page.locator('[data-live-action=preview]').first().click();await page.locator('[data-flight-confirm]').waitFor();assert.equal(await page.locator('[data-live-action=apply]').isDisabled(),true);
  assert.equal((await (await context.request.get(base+'/api/personal/state')).json()).plans.length,1);pass('Two-adult quotation previews per-adult budget without changing the saved plan');
  await page.locator('[data-flight-confirm]').check();await page.locator('[data-live-action=apply]').click();await page.locator('.current-flight-selected').waitFor();
  const state=await (await context.request.get(base+'/api/personal/state')).json();assert.equal(state.plans.length,2);assert.notEqual(state.latest_plan.id,first.id);assert.equal(state.latest_plan.live_flights.adults,2);assert.equal(state.latest_plan.budget.components[0].value,400);assert.equal(state.latest_plan.budget.components[1].value,500);assert.equal((await (await context.request.get(base+'/api/personal/plans/'+first.id)).json()).live_flights,undefined);pass('Confirmation saves a new version with current airfare and preserves the original');
  const other=await browser.newContext();assert.equal((await other.request.get(base+'/api/personal/flights/queries/'+state.latest_plan.live_flights.query_id)).status(),400);await other.close();pass('Another browser session cannot read private quote observations');
  await page.reload();await page.locator('.current-flight-selected').waitFor();assert.equal(await page.locator('[data-current-flights]').count(),1);pass('Reload retains the selected current quote in the existing flight area');
  await page.waitForFunction(()=>!document.querySelector('[data-live-action=refresh]').disabled);await page.locator('[data-current-flights]').screenshot({path:path.join(out,'flight-area.png')});await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);await page.screenshot({path:path.join(out,'personal-mobile.png'),fullPage:true});pass('Current flight controls, options and budget fit a mobile screen');
  await page.locator('[data-flight-adults]').selectOption('9');await page.waitForFunction(()=>!document.querySelector('[data-live-action=refresh]').disabled);assert.doesNotMatch(await page.locator('body').innerText(),/尚未查询|查询失败|报价过期/);assert.equal(await page.locator('.current-flight-total').count(),0);pass('A simulated source failure adds no error-state card or historical-price fallback');
  await page.setViewportSize({width:1440,height:1000});await page.goto(base+'/marketing/#trips');await page.locator('[data-trip-detail]').waitFor({timeout:60000});await page.locator('.current-flight-option').first().waitFor();assert.equal(await page.locator('[data-flight-reference]').count(),0);await page.screenshot({path:path.join(out,'marketing-desktop.png'),fullPage:true});pass('Marketing itinerary uses the same current-flight component without adding navigation or pages');
  assert.deepEqual(errors,[]);pass('No browser JavaScript errors');
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({fixture:'Explicit QA flight data, not live prices',passed:checks.length,checks},null,2));
 }finally{await browser.close();stop();}
})().catch(e=>{console.error(e);process.exitCode=1;stop();});
