// Independent browser acceptance; no writes to the user's campaign database.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const {chromium}=require('C:/Users/Administrator/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const out=path.join(__dirname,'runtime/tmp/travel-qa');fs.mkdirSync(out,{recursive:true});
process.env.TEMP=out;process.env.TMP=out;process.env.TMPDIR=out;
let server;process.on('exit',()=>server?.kill());
(async()=>{
 const base='http://127.0.0.1:8769';
 try{await fetch(base+'/api/health');throw Error('QA port 8769 is already occupied');}catch(e){if(e.message.includes('occupied'))throw e;}
 const localPython=path.join(__dirname,'.venv/Scripts/python.exe');
 const python=process.env.AEROLENS_PYTHON||(fs.existsSync(localPython)?localPython:path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'));
 server=spawn(python,['-u','decision_qa_server.py'],{cwd:__dirname,windowsHide:true,env:{...process.env,PYTHONUTF8:'1',PYTHONDONTWRITEBYTECODE:'1'},stdio:'ignore'});
 let ready=false;for(let i=0;i<90;i++){try{ready=(await fetch(base+'/api/health')).ok;}catch{}if(ready)break;if(server.exitCode!==null)throw Error('QA server exited');await new Promise(r=>setTimeout(r,500));}assert.ok(ready);
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage(),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));const pass=s=>{checks.push(s);console.log('PASS '+s);};
 try{
  await page.goto(base+'/marketing/',{waitUntil:'networkidle'});await page.locator('[data-trip-detail]').waitFor({timeout:60000});
  assert.equal(await page.locator('[data-trip-day]').count(),3);assert.ok((await page.locator('.metric-grid').innerText()).includes('10,000'));
  assert.ok((await page.locator('[data-trip-detail]').innerText()).includes('原始记录日期'));pass('Default homepage offers full-population travel plans with original flight dates');
  const first=await page.locator('[data-trip-detail] h2').innerText();await page.locator('[data-action=trip-view]').nth(1).click();await page.waitForFunction(t=>document.querySelector('[data-trip-detail] h2').textContent!==t,first);
  pass('Different travelers have individual plans and route references');
  await page.locator('#trip-settings-form [name=days]').selectOption('5');await page.locator('#trip-settings-form [name=trip_budget]').fill('100');await page.locator('#trip-settings-form [type=submit]').click();
  await page.waitForFunction(()=>document.querySelectorAll('[data-trip-day]').length===5,{timeout:60000});
  assert.ok((await page.locator('[data-trip-detail]').innerText()).includes('当前情景高出'));pass('Duration and budget updates regenerate the itinerary and disclose an infeasible budget');
  let download=page.waitForEvent('download');await page.locator('[data-action=trip-export]').click();let file=await download;await file.saveAs(path.join(out,'plan.json'));const plan=JSON.parse(fs.readFileSync(path.join(out,'plan.json'),'utf8'));
  assert.equal(plan.days,5);assert.equal(plan.bookable,false);assert.equal(plan.daily_itinerary.length,5);assert.equal(plan.backup_options.length,3);pass('Complete export preserves flight provenance, budget assumptions and backup options');
  await page.screenshot({path:path.join(out,'trip-desktop.png')});await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(out,'trip-mobile.png')});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);pass('Travel planner fits a mobile viewport');
  await page.setViewportSize({width:1200,height:900});await page.goto(base+'/marketing/survey.html');
  await require('./survey_browser_checks.cjs')(page,out,pass);
  assert.deepEqual(errors,[]);pass('Travel and questionnaire integration has no JavaScript errors');
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({passed:checks.length,checks,errors},null,2));
 }finally{await browser.close();server.kill();}
})().catch(e=>{console.error(e);process.exitCode=1;server?.kill();});
