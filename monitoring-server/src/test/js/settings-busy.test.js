const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function setup(fail=false){
 let release,calls=0;const gate=new Promise(r=>release=r),states=[];
 const ctx=vm.createContext({settingsApplying:false,dirty:new Map([['projector','on']]),site:'site',requireSelection:()=>[{id:'rail'}],rails:()=>[{id:'rail'}],setSettingsBusy:v=>states.push(v),syncPendingSettings(){},guarded:async f=>{try{await f()}catch{}},send:async()=>{calls++;await gate;if(fail)throw Error('timeout')},waitAppliedSnapshot:async()=>{},toast(){},renderLive(){}});
 vm.runInContext(source.match(/async function applyAllUpdates\(\).*$/m)[0],ctx);
 return {ctx,states,release,get calls(){return calls}};
}
test('apply stays busy while awaiting device and ignores duplicate clicks',async()=>{
 const a=setup(),pending=a.ctx.applyAllUpdates();assert.deepEqual(a.states,[true]);await a.ctx.applyAllUpdates();assert.equal(a.calls,1);
 a.release();await pending;assert.deepEqual(a.states,[true,false]);assert.equal(a.ctx.dirty.size,0);
});
test('failed application releases lock and retains pending settings',async()=>{
 const a=setup(true),pending=a.ctx.applyAllUpdates();a.release();await pending;assert.deepEqual(a.states,[true,false]);assert.equal(a.ctx.settingsApplying,false);assert.equal(a.ctx.dirty.size,1);
});
