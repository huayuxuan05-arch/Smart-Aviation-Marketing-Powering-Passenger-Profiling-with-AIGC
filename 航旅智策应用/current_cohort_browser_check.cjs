const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{spawn}=require('node:child_process');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
let server,pid;function stop(){if(pid){try{process.kill(pid);}catch{}pid=null;}server?.kill();}process.on('exit',stop);
(async()=>{
 const base='http://127.0.0.1:8774',out=path.join(__dirname,'runtime/tmp/current-cohort-qa');fs.mkdirSync(out,{recursive:true});
 server=spawn(path.join(__dirname,'.venv/Scripts/python.exe'),['-u','decision_qa_server.py'],{cwd:__dirname,windowsHide:true,stdio:'ignore',env:{...process.env,PYTHONUTF8:'1',AEROLENS_QA_PORT:'8774',AEROLENS_TEST_CURRENT_COHORT:'1',AEROLENS_TEST_FLIGHT_FIXTURE:'1'}});
 for(let i=0;i<90;i++){try{const r=await fetch(base+'/api/health');if(r.ok){pid=(await r.json()).process_id;break;}}catch{}if(server.exitCode!==null)throw Error('QA exited');await new Promise(r=>setTimeout(r,500));}assert.ok(pid);
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[],checks=[];
 page.on('pageerror',e=>errors.push(e.message));const pass=s=>{checks.push(s);console.log('PASS '+s);};
 try{
  await page.goto(base+'/marketing/#trips');await page.locator('[data-trip-detail]').waitFor({timeout:60000});
  const settings=await page.evaluate(()=>tripSettings);assert.equal(settings.cohort,'current');assert.equal(settings.asof,'2026-10-15');assert.equal(settings.start_date,'2026-11-06');
  assert.equal(await page.locator('#trip-settings-form [name=holiday]').count(),0);assert.equal(await page.locator('[name=asof]').getAttribute('max'),'2026-10-15');pass('Marketing uses the active annual test population and current profile dates');
  assert.match(await page.locator('.trip-user-list').innerText(),/LIVE_V2_TEST_/);assert.equal(await page.locator('[data-flight-reference]').count(),0);assert.equal(await page.locator('[data-trip-day]').count(),3);pass('New test users receive complete day-by-day plans without historical fare fallback');
  await page.locator('#trip-settings-form [name=trip_budget]').fill('500');await page.locator('#trip-settings-form [type=submit]').click();
  await page.waitForFunction(()=>!tripLoading&&tripSettings.trip_budget==='500'&&tripPlan?.budget.specified_total===500);
  assert.equal(await page.evaluate(()=>tripSettings.cohort),'current');assert.equal(await page.locator('[data-trip-day]').count(),3);pass('Updating a low-budget request retains the current cohort and full itinerary');
  await page.locator('.current-flight-total').first().waitFor({state:'attached'});const choices=page.locator('.current-flight-choices');if(!await choices.evaluate(e=>e.open))await choices.locator('summary').click();assert.match(await page.locator('[data-current-flights]').innerText(),/超预算备选/);pass('Over-budget current quote options remain available with explicit budget status');
  await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);pass('Current annual itinerary page fits mobile width');
  assert.deepEqual(errors,[]);pass('No JavaScript exceptions');
  fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({fixture:'Annual real generated data with explicit QA flight fixtures; not a live provider test',passed:checks.length,checks},null,2));
 }finally{await browser.close();stop();}
})().catch(e=>{console.error(e);process.exitCode=1;stop();});
