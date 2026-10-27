const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function app(advance){
 let now=0,calls=0;
 const c=vm.createContext({site:'s',stateFetchFailed:false,view:{rails:[{id:'r',online:true,seen_at:10}]},performance:{now:()=>now},renewStatusDemand:async()=>{},setTimeout:fn=>{now+=1000;fn();}});
 c.poll=async()=>{calls++;if(advance&&calls===3)c.view.rails[0].seen_at=11;};
 vm.runInContext(source.slice(source.indexOf('async function waitAppliedSnapshot('),source.indexOf('async function applyAllUpdates(')),c);
 return {c,calls:()=>calls};
}
test('old snapshots cannot complete apply confirmation; newer response can',async()=>{
 const a=app(true);await vm.runInContext("waitAppliedSnapshot(['r'],'s')",a.c);assert.equal(a.calls(),3);
});
test('missing post-apply response raises error rather than clearing pending selection',async()=>{
 const a=app(false);await assert.rejects(vm.runInContext("waitAppliedSnapshot(['r'],'s')",a.c),/선택값을 유지/);
 assert.ok(source.includes('await waitAppliedSnapshot(targets,targetSite);if(dirty.get(op)===value)dirty.delete(op);renderLive();'));
});
