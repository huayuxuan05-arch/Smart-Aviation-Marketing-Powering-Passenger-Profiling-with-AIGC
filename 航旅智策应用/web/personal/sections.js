'use strict';
const personalSectionState=new Map();
function rememberPersonalSection(details){
 if(!details.isConnected)return;
 personalSectionState.set(details.dataset.personalSection,details.open);
}
function personalSection(container,key){
 if(!container||container.querySelector(':scope > details.personal-disclosure'))return;
 const heading=container.querySelector(':scope > .assistant-heading,:scope > .trip-day-heading,:scope > .row,:scope > h2,:scope > h3');
 if(!heading)return;
 const details=document.createElement('details'),summary=document.createElement('summary'),body=document.createElement('div');
 details.className='personal-disclosure';details.dataset.personalSection=key;
 details.open=personalSectionState.get(key)===true;
 body.className='personal-disclosure-body';summary.append(heading);
 while(container.firstChild)body.append(container.firstChild);
 details.append(summary,body);container.append(details);
 details.addEventListener('toggle',()=>rememberPersonalSection(details));
 summary.addEventListener('click',()=>queueMicrotask(()=>rememberPersonalSection(details)));
}
function compactPersonalNotes(){
 compactApplicationUI();
 document.querySelectorAll('.personal-page .assistant-intro,.personal-page .personal-small,.personal-page .personal-reference,.personal-page .trip-basis,.personal-page .card-sub,.personal-page .assistant-note,.personal-page .assistant-changes small,.personal-page .assistant-question small,.personal-page .assistant-draft-head>span,.personal-page section.trip-subsection>small').forEach(e=>e.remove());
}
function updatePersonalDisclosures(){
 compactPersonalNotes();
 personalSection(document.querySelector('.assistant-card'),'assistant');
 personalSection(document.querySelector('#personal-preferences')?.closest('.card'),'preferences');
 personalSection(document.querySelector('.personal-history'),'history');
 personalSection(document.querySelector('.personal-profile'),'profile');
 personalSection(document.querySelector('[data-current-flights]'),'flights');
 for(const section of document.querySelectorAll('[data-trip-detail]>section.trip-subsection')){
  const title=section.querySelector(':scope > h3,:scope > .row>h3')?.textContent||'';
  const key=title.includes('预算')?'trip-budget':title==='AI旅行建议'?'trip-ai':'trip-'+title;
  personalSection(section,key);
 }
 for(const day of document.querySelectorAll('[data-trip-day]')){
  const number=day.querySelector('.trip-day-heading>span')?.textContent||'';
  personalSection(day,'day-'+number);
 }
 personalSection(document.querySelector('.personal-date-comparisons'),'dates');
}
