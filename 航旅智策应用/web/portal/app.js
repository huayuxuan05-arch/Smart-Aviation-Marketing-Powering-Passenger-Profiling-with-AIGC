'use strict';
// Existing saved links keep their staff workspace destination.
if(location.hash==='#survey')location.replace('/marketing/#trips');
if(['trips','overview','insights','audience','routes','creative','delivery','evaluation'].includes(location.hash.slice(1)))location.replace('/marketing/'+location.hash);
