const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function app({seen=10,baseline=10,advance=true,projector=true}={}){
 let now=0,calls=0;
 const c=vm.createContext({site:'s',stateFetchFailed:false,statusBaselines:new Map([['r',{seen:baseline}]]),view:{rails:[{id:'r',online:true,seen_at:seen,reported:{projector}}]},performance:{now:()=>now},renewStatusDemand:async()=>{},setTimeout:fn=>{now+=1000;fn();}});
 c.poll=async()=>{calls++;if(advance&&calls===3)c.view.rails[0].seen_at=11;};
 const start=source.indexOf('async function waitAppliedSnapshot('),end=source.indexOf('function setSettingsBusy(',start);
 vm.runInContext(source.slice(start,end),c);return {c,calls:()=>calls};
}
test('post-command snapshot already received is reused without another 5-second poll',async()=>{const a=app({seen:11,advance:false});await a.c.waitAppliedSnapshot(['r'],'s','projector','on');assert.equal(a.calls(),1);});
test('old snapshots cannot complete apply confirmation; newer matching response can',async()=>{const a=app();await a.c.waitAppliedSnapshot(['r'],'s','projector','on');assert.equal(a.calls(),3);});
test('new actual response completes immediately even if device policy differs from request',async()=>{const a=app({seen:11,advance:false,projector:false});await a.c.waitAppliedSnapshot(['r'],'s');assert.equal(a.calls(),1);assert.equal(a.c.view.rails[0].reported.projector,false);});
test('missing post-apply response preserves pending selection',async()=>{const a=app({advance:false});await assert.rejects(a.c.waitAppliedSnapshot(['r'],'s','projector','on'),/선택값을 유지/);assert.ok(source.includes('await waitAppliedSnapshot(targets,targetSite);if(dirty.get(op)===value)dirty.delete(op);'));});
