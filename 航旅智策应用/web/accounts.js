'use strict';
async function ensureSiteLogin(area){
 const prefix='/api/'+area+'/auth/';
 const response=await fetch(prefix+'status'),state=await response.json();
 if(!response.ok)throw Error(state.error||'暂时无法读取登录状态');
 if(!state.enabled){document.body.dataset.loginState='ready';return true;}
 if(state.authenticated){
  document.body.dataset.loginState='ready';
  const slot=document.createElement('div');slot.className='account-session';
  const name=document.createElement('span');name.textContent=state.user.username;
  const logout=document.createElement('button');logout.type='button';logout.className='secondary small';logout.textContent='退出登录';logout.dataset.accountLogout='';
  logout.addEventListener('click',async()=>{logout.disabled=true;try{const responses=await Promise.all(['personal','mkt'].map(a=>fetch('/api/'+a+'/auth/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})));if(responses.some(r=>!r.ok))throw Error('退出未完成，请重试');sessionStorage.clear();location.reload();}catch{logout.disabled=false;logout.textContent='重试退出';}});
  slot.append(name,logout);document.querySelector(area==='personal'?'.personal-header nav':'.top-actions').append(slot);
  return true;
 }
 document.body.dataset.loginState='required';
 const host=document.createElement('section');host.className='account-gate card';host.setAttribute('aria-labelledby','account-heading');
 host.innerHTML=`<span class="account-kicker">${area==='personal'?'个人旅行空间':'营销工作空间'}</span><h2 id="account-heading">${area==='personal'?'登录账号':'管理登录'}</h2><p>${area==='personal'?'登录后继续查看你的旅行偏好、方案和动态记录。每位参与者请使用自己的账号。':'请使用管理账号查看已同意共享的用户画像。'}</p>${area==='personal'?'<div class="account-tabs" role="group" aria-label="账号操作"><button type="button" data-account-mode="login" aria-pressed="true">登录</button><button type="button" data-account-mode="register" aria-pressed="false">注册账号</button></div>':''}<form id="account-form"><label class="field"><span>账号</span><input name="username" autocomplete="username" minlength="3" maxlength="32" required placeholder="输入你的账号" ${area==='mkt'?'value="marketing_admin"':''}></label><label class="field"><span>密码</span><div class="account-password-input"><input name="password" type="password" autocomplete="current-password" maxlength="128" required><button type="button" class="secondary small" data-password-toggle aria-pressed="false" aria-label="显示密码">显示密码</button></div></label><label class="field" data-password-confirm hidden><span>确认密码</span><input name="confirm" type="password" autocomplete="new-password" maxlength="128"></label><p class="account-error" role="alert"></p><button type="submit" class="primary">登录个人账号</button></form><small>${area==='personal'?'注册时使用3至32位账号和至少8位密码。画像共享由你登录后自主选择。':'管理账号由本站维护人员提供。'}</small>`;
 document.querySelector(area==='personal'?'.personal-layout':'#app').before(host);
 host.querySelector('[data-password-toggle]').addEventListener('click',e=>{const input=host.querySelector('[name=password]'),visible=input.type==='password';input.type=visible?'text':'password';e.currentTarget.textContent=visible?'隐藏密码':'显示密码';e.currentTarget.setAttribute('aria-pressed',String(visible));e.currentTarget.setAttribute('aria-label',visible?'隐藏密码':'显示密码');});
 let mode='login';const form=host.querySelector('form'),submit=form.querySelector('[type=submit]');submit.textContent=area==='personal'?'登录个人账号':'登录管理账号';
 host.addEventListener('click',e=>{const b=e.target.closest('[data-account-mode]');if(!b)return;mode=b.dataset.accountMode;host.querySelectorAll('[data-account-mode]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));host.querySelector('#account-heading').textContent=mode==='register'?'注册账号':'登录账号';form.querySelector('[data-password-confirm]').hidden=mode!=='register';form.elements.confirm.required=mode==='register';form.elements.password.autocomplete=mode==='register'?'new-password':'current-password';form.elements.password.minLength=mode==='register'?8:1;submit.textContent=mode==='register'?'注册并进入':'登录个人账号';form.querySelector('.account-error').textContent='';});
 form.addEventListener('submit',async e=>{e.preventDefault();if(submit.disabled)return;const error=form.querySelector('.account-error');error.textContent='';if(mode==='register'&&form.elements.password.value!==form.elements.confirm.value){error.textContent='两次输入的密码不一致';return;}submit.disabled=true;try{const r=await fetch(prefix+mode,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:form.elements.username.value,password:form.elements.password.value})}),value=await r.json();if(!r.ok)throw Error(value.error||'登录未完成');sessionStorage.clear();location.reload();}catch(e){error.textContent=e.message;submit.disabled=false;}});
 return false;
}
