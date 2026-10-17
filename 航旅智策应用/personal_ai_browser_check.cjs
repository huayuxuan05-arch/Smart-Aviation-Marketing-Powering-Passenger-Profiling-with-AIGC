const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {chromium}=require(path.join(process.env.USERPROFILE,'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
(async()=>{
 const out=path.join(__dirname,'runtime/tmp/local-ai-airline-live');fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1440,height:1100}}),page=await context.newPage(),errors=[];
 page.on('pageerror',e=>errors.push(e.message));const base=process.env.AEROLENS_TEST_URL||'http://127.0.0.1:8765';
 const api=async(route,data)=>{const r=await context.request[data===undefined?'get':'post'](base+'/api/personal/'+route,data===undefined?{}:{data,timeout:240000});const v=await r.json();assert.ok(r.ok(),JSON.stringify(v));return v;};
 try{
  const auth=await api('auth/status');
  if(auth.enabled){
   if(!process.env.AEROLENS_TEST_USERNAME||!process.env.AEROLENS_TEST_PASSWORD)throw Error('Real-model check requires a dedicated unused account via AEROLENS_TEST_USERNAME / AEROLENS_TEST_PASSWORD; no account is created automatically.');
   await api('auth/login',{username:process.env.AEROLENS_TEST_USERNAME,password:process.env.AEROLENS_TEST_PASSWORD});
   const existing=await api('state');assert.equal(existing.revision,0,'Use a dedicated unused test account');assert.equal(existing.collection.enabled,false);
  }
  const b=await api('bootstrap');assert.ok(b.generation.model_enabled);assert.match(b.generation.label,/Qwen3\.5-4B/);
  await api('preferences',{preferences:{...b.preferences,origin:'上海',destination:'广州',start_date:process.env.AEROLENS_LIVE_CHECK_DATE||new Date(Date.now()+7*86400000).toISOString().slice(0,10),days:4,party:'朋友',trip_budget:2000},expected_revision:b.revision});
  await page.goto(base+'/personal/');await page.locator('[data-personal-section=assistant]>summary').click();
  await page.locator('#assistant-text').fill('我不要春秋航空，我要川航的，我想从上海去成都');
  await page.locator('#assistant-parse').click();
  await page.waitForFunction(()=>document.querySelector('#assistant-consent')||document.querySelector('#assistant-error')?.textContent||document.querySelector('.assistant-error')?.textContent,null,{timeout:240000});
  assert.equal(await page.locator('#assistant-error').innerText(),'');
  assert.equal(await page.locator('.assistant-error').count(),0);
  assert.match(await page.locator('[data-assistant-field=required_airlines]').innerText(),/四川航空/);
  assert.match(await page.locator('[data-assistant-field=excluded_airlines]').innerText(),/春秋航空/);
  await page.locator('.assistant-plan-preview>summary').click();
  assert.match(await page.locator('.assistant-plan-preview').innerText(),/每日行程/);
  assert.equal((await api('state')).plans.length,0);
  await page.locator('#assistant-draft').screenshot({path:path.join(out,'ai-draft.png')});
  console.log('PASS exact request produces a local-model draft with 3U only, excludes 9C and previews all itinerary cards before saving');
  await page.locator('#assistant-consent').check();await page.locator('#assistant-confirm').click();
  await page.locator('[data-trip-detail]').waitFor({timeout:60000});
  const state=await api('state'),p=state.latest_plan;
  assert.equal(p.origin,'上海');assert.equal(p.destination,'成都');assert.equal(p.ai_planning.content_generated,true);
  assert.equal(p.daily_itinerary.length,4);assert.equal(p.planning_evidence.simulated_users,10000);
  assert.deepEqual(p.preference_constraints.required_airlines,['3U']);assert.deepEqual(p.preference_constraints.excluded_airlines,['9C']);
  assert.equal(await page.locator('.trip-rationale').count(),0);assert.equal(await page.locator('.trip-budget thead th').count(),2);
  await page.locator('[data-personal-section=flights]>summary').click();
  await page.waitForFunction(()=>!document.querySelector('[data-live-action=refresh]').disabled,null,{timeout:180000});
  await page.waitForFunction(()=>!document.querySelector('[data-live-action=refresh]').disabled);
  const flights=await page.locator('[data-current-flights]').innerText();
  const hasQuotes=await page.locator('.current-flight-option').count()>0;if(hasQuotes)assert.match(flights,/四川航空 3U/);else assert.match(flights,/暂未返回符合航司条件|当前暂时无法核验航班/);assert.doesNotMatch(flights,/春秋航空 9C|9C\d{3,4}|TEST\d/);
  await page.locator('[data-current-flights]').screenshot({path:path.join(out,'real-sichuan-flights.png')});
  console.log('PASS flight search applies 3U only and never substitutes another carrier; quotes available: '+hasQuotes);
  await page.locator('[data-personal-section=trip-budget]>summary').click();await page.locator('[data-personal-section=trip-ai]>summary').click();assert.equal(await page.locator('.trip-ai h3').innerText(),'旅行建议');assert.ok((await page.locator('#trip-ai-summary').inputValue()).length>0);const titles=await page.locator('.personal-page .card h2,.personal-page .card h3').allTextContents();assert.ok(titles.every(t=>/^[\u4e00-\u9fff]{4}$/.test(t)),JSON.stringify(titles));
  await page.setViewportSize({width:390,height:844});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.locator('.trip-budget').screenshot({path:path.join(out,'budget-mobile.png')});
  assert.deepEqual(errors,[]);
  const report={website:base+'/personal/',model:b.generation.label,model_called:true,ai_content:p.ai_planning,route:p.origin+' → '+p.destination,required_airlines:p.preference_constraints.required_airlines,excluded_airlines:p.preference_constraints.excluded_airlines,training_source:p.planning_evidence.source,flights_text:flights,ui_removed:['定制依据','预算依据列'],quotes_available:hasQuotes,card_titles:titles,mobile:true,js_errors:errors};
  report.verification_scope=process.env.AEROLENS_TEST_ISOLATED==='1'?'isolated QA; flight source blocked':'dedicated live account';
  fs.writeFileSync(path.join(out,'verification.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({model:report.model,route:report.route,required_airlines:report.required_airlines,model_called:true,verification_scope:report.verification_scope,quotes_available:hasQuotes,passed:true}));
 }finally{await api('auth/logout',{}).catch(()=>{});await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
