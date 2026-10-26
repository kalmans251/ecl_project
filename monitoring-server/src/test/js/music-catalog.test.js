const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function app(){
 const elements={};
 const context=vm.createContext({console,setTimeout,clearTimeout,setInterval:()=>1,performance,crypto:require('node:crypto').webcrypto,
  Option:class {constructor(text,value){this.text=text;this.value=value;}},
  window:{addEventListener(){}},document:{addEventListener(){},getElementById(id){return elements[id]??=( {value:'',disabled:false,children:[],replaceChildren(){this.children=[];this.value='';},append(item){this.children.push(item);}});}}});
 const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8').replace(/^init\(\);$/m,'');
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../main/resources/static/radar-view.js'),'utf8'),context);
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../main/resources/static/detection-count.js'),'utf8'),context);
 vm.runInContext(source,context);
 const run=code=>vm.runInContext(code,context);
 run(`view={role:'OPERATOR',rails:[{id:'rail-a',name:'A',online:true},{id:'rail-b',name:'B',online:true}]};selected=new Set(['rail-a']);renderMusicCatalog();`);
 return {run,elements,context};
}
test('changing selected railing invalidates old catalog and disables playback',()=>{
 const a=app();a.run(`musicPage={catalog_version:5,group:'default',offset:0,total:1,tracks:[{index:0,filename:'a.mp3'}]};fillMusicTracks();$('piTrackSelect').value='0';renderMusicCatalog();`);
 assert.equal(a.elements.musicTrackPlay.disabled,false);
 a.run(`selected=new Set(['rail-b']);renderMusicCatalog();`);
 assert.equal(a.run('musicPage'),null);assert.equal(a.elements.musicTrackPlay.disabled,true);
 a.run(`view.role='VIEWER';renderMusicCatalog();`);assert.equal(a.elements.musicListLoad.disabled,true);
});
test('selected playback sends exact displayed catalog version and waits for confirmed result',async()=>{
 const a=app(),posted=[];a.context.capture=data=>posted.push(data);
 a.run(`musicPage={catalog_version:5,group:'20',offset:0,total:1,tracks:[{index:0,filename:'a.mp3'}]};fillMusicTracks();$('piTrackSelect').value='0';
 api=async(path,method,data)=>{if(method==='POST'){capture(data);return [{id:'request'}];}return {status:'APPLIED',result:{filename:'a.mp3'}};};poll=async()=>{};toast=()=>{};`);
 await a.run('playSelectedMusic()');
 assert.equal(posted[0].operation,'music.play');assert.equal(posted[0].value,'5:20:0');assert.equal(posted[0].rail_ids[0],'rail-a');
});
test('unknown playback clears catalog without automatic retry',async()=>{
 const a=app();let calls=0;a.context.count=()=>calls++;
 a.run(`musicPage={catalog_version:5,group:'default',offset:0,total:1,tracks:[{index:0,filename:'a.mp3'}]};fillMusicTracks();$('piTrackSelect').value='0';
 api=async(path,method)=>{if(method==='POST'){count();return [{id:'request'}];}return {status:'UNKNOWN'};};`);
 await assert.rejects(a.run('playSelectedMusic()'),/UNKNOWN/);assert.equal(calls,1);assert.equal(a.run('musicPage'),null);
});
test('general control waits for each railing and reports partial failure without replay',async()=>{
 const a=app(),posted=[];a.context.capture=x=>posted.push(x);
 a.run(`selected=new Set(['rail-a','rail-b']);poll=async()=>{};toast=()=>{};
 api=async(path,method,data)=>{if(method==='POST'){capture(data);return [{id:'a',status:'SENT'},{id:'b',status:'SENT'}];}
 return path.endsWith('/a')?{id:'a',rail_id:'rail-a',status:'APPLIED'}:{id:'b',rail_id:'rail-b',status:'UNKNOWN'};};`);
 await assert.rejects(a.run(`send('power','ac')`),/B: UNKNOWN/);
 assert.equal(posted.length,1);assert.equal(a.run('controlBusy'),false);
});
test('policy-only completion remains distinct and blocks duplicate control while pending',async()=>{
 const a=app();a.run(`poll=async()=>{};toast=()=>{};controlBusy=true;`);
 await assert.rejects(a.run(`send('music.start')`),/이전 제어/);
 a.run(`controlBusy=false;api=async(path,method)=>method==='POST'?[{id:'a',status:'SENT'}]:{id:'a',rail_id:'rail-a',status:'COMPLETED',detail:'P4 policy confirmed'};`);
 const results=await a.run(`send('music.start')`);
 assert.equal(results[0].status,'COMPLETED');
});
test('batch settings stop when selection changes while confirmation is pending',async()=>{
 const a=app();let sent=0;a.context.count=()=>sent++;
 a.run(`site='site-a';dirty=new Map([['led','basic'],['volume','20']]);guarded=async f=>f();toast=()=>{};
 send=async()=>{count();selected=new Set(['rail-b']);return [];};`);
 await assert.rejects(a.run('applyAllUpdates()'),/선택이 변경/);assert.equal(sent,1);
});
test('emergency accept prepares audio and opens it only after one confirmed request',async()=>{
 const a=app(),steps=[];a.context.capture=x=>steps.push(x);
 a.run(`modalRail='rail-b';guarded=async f=>f();renderSelection=()=>{};
 ensureAudio=async()=>capture('audio');voiceClient=()=>({prepare:async()=>capture('prepare')});
 send=async op=>capture(op);openVoice=async()=>capture('voice');dismissEmergencyModal=()=>capture('dismiss');`);
 await a.run('acceptEmergencyCallFromModal()');
 assert.deepEqual(steps,['audio','prepare','call.accept','voice','dismiss']);
 assert.equal(a.run('[...selected][0]'),'rail-b');
 steps.length=0;a.run(`send=async op=>{capture(op);throw Error('unconfirmed');};`);
 await assert.rejects(a.run('acceptEmergencyCallFromModal()'),/unconfirmed/);
 assert.deepEqual(steps,['audio','prepare','call.accept']);
});
