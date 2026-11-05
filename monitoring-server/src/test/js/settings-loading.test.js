const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
const apiSource=source.slice(source.indexOf('async function api('),source.indexOf('\nconst statusBaselines'));
const applySource=source.slice(source.indexOf('async function applyAllUpdates()'),source.indexOf('\nfunction sendAudioAction'));
function network(fetch){
 let expire,cleared=0;
 const c=vm.createContext({AbortController,csrf:{header:'X-CSRF',token:'token'},fetch,
  location:{},setTimeout(fn){expire=fn;return 1;},clearTimeout(){cleared++;}});
 vm.runInContext(apiSource,c);
 return {run:code=>vm.runInContext(code,c),expire:()=>expire(),cleared:()=>cleared};
}
function aborted(signal){return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(Error('aborted')),{once:true}));}
test('stalled mutation headers time out once with uncertainty and no replay',async()=>{
 let calls=0;const a=network((path,options)=>{calls++;return aborted(options.signal);});
 const pending=a.run("api('/api/portal/commands','POST',{})");a.expire();
 await assert.rejects(pending,/적용 여부는 미확인/);
 assert.equal(calls,1);assert.equal(a.cleared(),1);
});
test('deadline covers stalled body after successful headers',async()=>{
 const a=network(async(path,options)=>{const body=aborted(options.signal);return {status:200,ok:true,headers:{get:()=>null},text:()=>body};});
 const pending=a.run("api('/api/portal/commands/a')");
 await Promise.resolve();await Promise.resolve();a.expire();
 await assert.rejects(pending,/서버 응답 시간 초과/);assert.equal(a.cleared(),1);
});
test('successful response cancels deadline and preserves result',async()=>{
 const a=network(async()=>({status:200,ok:true,headers:{get:()=>null},text:async()=>'{"status":"APPLIED"}'}));
 assert.equal((await a.run("api('/api/portal/commands/a')")).status,'APPLIED');assert.equal(a.cleared(),1);
});
function batch(options={}){
 let opened=false,calls=0,errors=[];
 const c=vm.createContext({musicBusy:false,settingsApplying:false,site:'site-a',dirty:new Map([['projector','off']]),
  toast:()=>{},setSettingsBusy(value){opened=value;},
  syncPendingSettings(){if(options.preparationFailure&&opened)throw Error('render failed');},
  requireSelection:()=>[{id:'rail-a'}],rails:()=>[{id:'rail-a'}],
  guarded:async fn=>{try{await fn();}catch(e){errors.push(e.message);}},
  send:async()=>{calls++;if(options.requestFailure)throw Error('timeout; unknown');},
  waitAppliedSnapshot:async()=>{if(options.snapshotFailure)throw Error('no fresh status');},renderLive:()=>{}});
 vm.runInContext(applySource,c);
 return {run:()=>vm.runInContext('applyAllUpdates()',c),c,opened:()=>opened,calls:()=>calls,errors};
}
test('preparation errors release loading and ownership without sending',async()=>{
 const a=batch({preparationFailure:true});await a.run();
 assert.equal(a.opened(),false);assert.equal(a.c.settingsApplying,false);assert.equal(a.calls(),0);assert.equal(a.c.dirty.size,1);
});
test('request or snapshot failure releases loading and retains pending setting',async()=>{
 for(const options of [{requestFailure:true},{snapshotFailure:true}]){
  const a=batch(options);await a.run();assert.equal(a.opened(),false);
  assert.equal(a.c.settingsApplying,false);assert.equal(a.calls(),1);assert.equal(a.c.dirty.size,1);assert.equal(a.errors.length,1);
 }
});
test('confirmed completion closes loading and clears only completed settings',async()=>{
 const a=batch();await a.run();assert.equal(a.opened(),false);assert.equal(a.c.settingsApplying,false);
 assert.equal(a.c.dirty.size,0);assert.equal(a.calls(),1);
});
