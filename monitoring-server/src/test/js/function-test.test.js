const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
function app(){const elements={};const element=()=>({value:'',textContent:'',disabled:false,children:[],dataset:{},setAttribute(){},replaceChildren(){this.children=[];this.value='';},append(...v){this.children.push(...v);}});
const context=vm.createContext({module:{exports:{}},performance,crypto:require('node:crypto').webcrypto,setTimeout,AbortSignal,location:{},Option:class{constructor(t,v){this.text=t;this.value=v;}},document:{getElementById(id){return elements[id]??=element();},createElement:element,querySelectorAll(){return [];}}});
for(const f of ['music-status.js','detection-count.js','function-test.js'])vm.runInContext(fs.readFileSync(path.join(__dirname,'../../main/resources/static',f),'utf8'),context);
const run=s=>vm.runInContext(s,context);run(`view={role:'OPERATOR',rails:[{id:'a',name:'A',online:true},{id:'b',name:'B',online:true}]};selected=new Set(['a']);`);return {run,context,elements};}
test('viewer and offline selection cannot submit',async()=>{const a=app();a.run(`view.role='VIEWER'`);await assert.rejects(a.run(`send('power','on')`),/권한/);a.run(`view.role='OPERATOR';view.rails[0].online=false`);await assert.rejects(a.run(`send('power','on')`),/연결/);});
test('multi rail partial failure is shown without resend',async()=>{const a=app(),posted=[];a.context.capture=x=>posted.push(x);a.run(`selected.add('b');api=async(p,m,d)=>{if(m==='POST'){capture(d);return [{id:'1',rail_id:'a',status:'SENT'},{id:'2',rail_id:'b',status:'SENT'}];}return p.endsWith('1')?{id:'1',rail_id:'a',status:'APPLIED'}:{id:'2',rail_id:'b',status:'UNKNOWN'};};`);await assert.rejects(a.run(`send('volume','10')`),/B: UNKNOWN/);assert.equal(posted.length,1);assert.equal(posted[0].rail_ids.length,2);assert.equal(a.run('busy'),false);assert.equal(a.elements.results.children.length,2);});
test('busy blocks another request and request keeps original rail',async()=>{const a=app();let release;const gate=new Promise(r=>release=r);a.context.gate=gate;a.run(`api=async(p,m)=>{await gate;return [{id:'1',rail_id:'a',status:'APPLIED'}];}`);const request=a.run(`send('led','basic')`);await assert.rejects(a.run(`send('led','off')`),/이전 명령/);release();await request;assert.equal(a.run('busy'),false);});
test('music play uses catalog identity and rejects empty selection',async()=>{const a=app(),sent=[];a.context.capture=x=>sent.push(x);a.run(`page={catalog_version:123,group:'20',tracks:[{index:2}]};$('track').value='2';api=async(p,m,d)=>{capture(d);return [{id:'1',rail_id:'a',status:'APPLIED'}];};refresh=async()=>{};`);await a.run('play()');assert.equal(sent[0].value,'123:20:2');assert.equal(sent[0].operation,'music.play');a.run(`$('track').value=''`);await assert.rejects(a.run('play()'),/선택/);});
test('seek rejects stale state and sends playback ID with milliseconds',async()=>{const a=app(),sent=[];a.context.capture=x=>sent.push(x);a.run(`view.rails[0].music_status={available:true,fresh:true,fresh_ms:10000,age_ms:0,seekable:true,state:'playing',duration_ms:90000,playback_id:42};$('seconds').value='10';`);await assert.rejects(a.run('seek()'),/최신/);a.run(`received=performance.now();api=async(p,m,d)=>{capture(d);return [{id:'1',rail_id:'a',status:'APPLIED'}];};refresh=async()=>{};`);await a.run('seek()');assert.equal(sent[0].value,'42:10000');});
test('failed state refresh disables controls and clears catalog',async()=>{const a=app();a.run(`site='s';page={tracks:[]};api=async()=>{throw Error('offline');};`);await assert.rejects(a.run('refresh()'),/offline/);assert.equal(a.run('writable()'),false);assert.equal(a.run('page'),null);});
test('hangup bypasses broken browser audio and refreshes failed call state',async()=>{
 const a=app();a.run(`webVoice={pause(){},close(){},prepare(){throw Error('audio unavailable');}};send=async(op)=>{if(op!=='call.end')throw Error('wrong op');throw Error('unconfirmed');};refresh=async()=>{globalThis.refreshed=true;};`);
 await assert.rejects(a.run(`callControl('call.end')`),/unconfirmed/);assert.equal(a.context.refreshed,true);
});
test('unknown owned call keeps hangup enabled',()=>{
 const a=app();a.run(`view.calls=[{RAIL_ID:'a',OWNED:true,STATUS:'UNKNOWN'}];renderCall();`);
 assert.equal(a.elements.callEnd.disabled,false);assert.equal(a.elements.pttOn.disabled,true);
});
test('microphone preparation excludes poll media sync and duplicate controls',async()=>{
 const a=app();let release;const gate=new Promise(r=>release=r);let syncs=0,posts=0;
 a.context.gate=gate;a.context.sync=()=>syncs++;a.context.post=()=>posts++;
 a.run(`site='s';view.calls=[{RAIL_ID:'a',OWNED:true,STATUS:'ACTIVE',DIRECTION:'FIELD_TX'}];
 webVoice={pause(){},close(){},prepare:async()=>{},mic:()=>gate,sync};
 api=async(p,m)=>{if(m==='POST'){post();return [{id:'cmd',status:'APPLIED'}];}return {...view,calls:[{RAIL_ID:'a',OWNED:true,STATUS:'ACTIVE',DIRECTION:'CONTROL_TX'}]};};`);
 const pending=a.run(`callControl('ptt.on')`);await new Promise(r=>setImmediate(r));
 await a.run('refresh()');assert.equal(syncs,0);assert.equal(a.run('writable()'),false);
 await assert.rejects(a.run(`callControl('ptt.off')`),/기다려/);
 await assert.rejects(a.run(`send('led','off')`));
 release();await pending;assert.equal(posts,1);assert.equal(syncs,1);assert.equal(a.run('callChanging'),false);
});
test('failed microphone preparation releases transition and restores listening without PTT',async()=>{
 const a=app();let syncs=0;a.context.sync=()=>syncs++;
 a.run(`webVoice={pause(){},close(){},prepare:async()=>{},mic:async()=>{throw Error('permission denied');},sync};refresh=async()=>{};send=async()=>{throw Error('must not send');};`);
 await assert.rejects(a.run(`callControl('ptt.on')`),/permission denied/);
 assert.equal(a.run('callChanging'),false);assert.equal(syncs,1);
});
