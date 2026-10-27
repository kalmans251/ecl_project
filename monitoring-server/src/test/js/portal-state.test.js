const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function app(){
 const elements={},buttons=[true,false].map(value=>element(`toggleDeviceState('projector', ${value})`));
 function element(onclick=''){const classes=new Set();return {value:'',textContent:'',classList:{toggle(k,on){on?classes.add(k):classes.delete(k)},remove(k){classes.delete(k)},contains(k){return classes.has(k)}},getAttribute(){return onclick}};}
 const c=vm.createContext({elements,buttons,dirty:new Map(),$:id=>elements[id]??=element(),document:{querySelectorAll:q=>q.startsWith('[onclick')?buttons:[]},text:(id,v)=>(elements[id]??=element()).textContent=v,updateVolUI(){},toggleSleepStateUI(){},switchCategoryTabUI(){},switchDisplayView(){}});
 vm.runInContext(source.slice(source.indexOf('function syncReportedControls'),source.indexOf('function mark(')),c);
 return {c,elements,buttons,run:s=>vm.runInContext(s,c)};
}
test('fresh observations update projector selection and actual display in both directions',()=>{const a=app();a.run('syncReportedControls({projector:true});renderProjector({projector:true})');assert.equal(a.buttons[0].classList.contains('active'),true);assert.equal(a.elements.projectorLogoWrapper.classList.contains('spinning'),true);a.run('syncReportedControls({projector:false});renderProjector({projector:false})');assert.equal(a.buttons[1].classList.contains('active'),true);assert.equal(a.elements.projectorLogoWrapper.classList.contains('spinning'),false);assert.match(a.elements.projectorStateText.textContent,/OFF/);});
test('pending edits survive polling while actual indicator follows device',()=>{const a=app();a.c.dirty.set('projector','on');a.buttons[0].classList.toggle('active',true);a.run('syncReportedControls({projector:false});renderProjector({projector:false})');assert.equal(a.buttons[0].classList.contains('active'),true);assert.match(a.elements.projectorStateText.textContent,/OFF/);a.c.dirty.clear();a.run('syncReportedControls({projector:false})');assert.equal(a.buttons[1].classList.contains('active'),true);});
test('missing or stale observations never display confirmed OFF or retain prior selection',()=>{const a=app();a.run('syncReportedControls({projector:true});syncReportedControls({});renderProjector({})');assert.equal(a.buttons.some(b=>b.classList.contains('active')),false);assert.equal(a.elements.projectorStateText.textContent,'상태 미확인');});
test('poll render synchronizes controls with freshness-gated observations',()=>{assert.match(source,/s=fresh\?r.reported:\{\}/);assert.ok(source.includes('renderProjector(r?.reported||{},fresh)'));});

test('stale ON keeps symbol bright and rotating with explicit last-observation label',()=>{const a=app();a.run('renderProjector({projector:true},false)');assert.equal(a.elements.projectorLogoWrapper.classList.contains('spinning'),true);assert.equal(a.elements.projectorLogoWrapper.classList.contains('power-off'),false);assert.match(a.elements.projectorStateText.textContent,/마지막 확인값/);});
test('rail switch with no observation uses neutral symbol instead of previous ON or confirmed OFF',()=>{const a=app();a.run('renderProjector({projector:true},false);renderProjector({},false)');const c=a.elements.projectorLogoWrapper.classList;assert.equal(c.contains('spinning'),false);assert.equal(c.contains('power-off'),false);assert.equal(c.contains('power-unknown'),true);});
test('fresh OFF stops stale ON and removes stale label',()=>{const a=app();a.run('renderProjector({projector:true},false);renderProjector({projector:false},true)');const c=a.elements.projectorLogoWrapper.classList;assert.equal(c.contains('spinning'),false);assert.equal(c.contains('power-off'),true);assert.doesNotMatch(a.elements.projectorStateText.textContent,/마지막 확인값/);});

test('controls use selected rail reported values independently of freshness gating',()=>{
 assert.ok(source.includes('syncReportedControls(r?.reported||{})'));
 assert.ok(!source.includes('syncReportedControls(s);renderProjector'));
 assert.ok(source.includes('최신 상태 미확인 · 마지막 수신값'));
});
test('repeated snapshots retain settings, new snapshots update them, edits remain pending',()=>{
 const a=app();a.c.sleepValues=[];a.c.ledValues=[];a.c.detectionValues=[];
 a.run('toggleSleepStateUI=(v)=>sleepValues.push(v);switchCategoryTabUI=(v)=>ledValues.push(v);switchDisplayView=(v)=>detectionValues.push(v)');
 a.run(`const state={projector:true,sleep:true,led:'music',music_mode:'shuffle',detection:'cctv'};syncReportedControls(state);syncReportedControls(state)`);
 assert.equal(a.buttons[0].classList.contains('active'),true);
 assert.equal(a.elements.piPlayMode.value,1);assert.deepEqual([...a.c.sleepValues],[true,true]);
 a.c.dirty.set('sleep','on');a.c.dirty.set('projector','on');
 a.run(`syncReportedControls({projector:false,sleep:false,led:'basic',music_mode:'sequential',detection:'radar'})`);
 assert.equal(a.buttons[0].classList.contains('active'),true);assert.equal(a.c.sleepValues.length,2);
 assert.equal(a.elements.piPlayMode.value,0);assert.equal(a.c.ledValues.at(-1),'basic');
 a.c.dirty.clear();a.run('syncReportedControls({projector:false,sleep:false})');
 assert.equal(a.buttons[1].classList.contains('active'),true);assert.equal(a.c.sleepValues.at(-1),false);
});

test('elapsed wall time does not expire received state; connection and new-response checks remain',()=>{
 const c=vm.createContext({statusBaselines:new Map(),stateFetchFailed:false,performance:{now:()=>20000}});
 vm.runInContext(source.slice(source.indexOf('function statusCheck('),source.indexOf('let emergencyAudio;')),c);
 c.r={id:'rail1',online:true,seen_at:1};
 assert.equal(vm.runInContext('statusCheck(r).fresh',c),true);
 c.r.online=false;assert.equal(vm.runInContext('statusCheck(r).fresh',c),false);
 c.r.online=true;c.stateFetchFailed=true;assert.equal(vm.runInContext('statusCheck(r).fresh',c),false);
 c.stateFetchFailed=false;c.statusBaselines.set('rail1',{seen:1,at:0});
 assert.equal(vm.runInContext('statusCheck(r).fresh',c),false);
 c.r.seen_at=2;assert.equal(vm.runInContext('statusCheck(r).fresh',c),true);
 c.r.seen_at=null;assert.equal(vm.runInContext('statusCheck(r).fresh',c),false);
});
