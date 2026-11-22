const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function app(){
 const els=new Map();function el(id){if(!els.has(id))els.set(id,{hidden:false,disabled:false,textContent:'',replaceChildren(){},append(){},classList:{toggle(){}},style:{}});return els.get(id);}
 const c=vm.createContext({crypto:{randomUUID:()=> 'test'},structuredClone,document:{getElementById:el,addEventListener(){},createElement:()=>({append(){}}),querySelectorAll:()=>[]},window:{addEventListener(){}},RadarView:class{},setTimeout:()=>0,clearTimeout(){},performance:{now:()=>0}});
 vm.runInContext(source.replace(/^init\(\);$/m,''),c);
 vm.runInContext(`site='s';view={rails:[{id:'r',online:true,reported:{power:'ac',sleep:false,detection:'radar',music_mode:'sequential'},music_status:{fresh:true,volume:20}}]};selected=new Set(['r']);let rendered=0;renderLive=()=>{rendered++};send=()=>{throw Error('Cancellation must not send commands')};`,c);
 return {run:s=>vm.runInContext(s,c),el};
}
test('returning sleep, detection, power, volume and music mode to their starting values clears the drawer',()=>{
 for(const [op,start,end]of [['sleep','off','on'],['detection','radar','cctv'],['power','ac','battery'],['volume','20','80'],['music.mode','sequential','shuffle']]){
  const a=app();a.run(`mark('${op}','${end}')`);assert.equal(a.el('pendingSettingsBar').hidden,false);a.run(`mark('${op}','${start}')`);assert.equal(a.run('dirty.size'),0);assert.equal(a.el('pendingSettingsBar').hidden,true);
 }
});
test('mixed or unknown original device states retain the change instead of pretending they match',()=>{
 const a=app();a.run(`view.rails.push({id:'r2',reported:{sleep:true}});selected.add('r2');mark('sleep','off')`);assert.equal(a.run('dirty.size'),1);
 a.run(`dirty.clear();view.rails[0].reported={};selected=new Set(['r']);mark('sleep','off')`);assert.equal(a.run('dirty.size'),1);
});
test('cancel clears edits, restores projector and LED preferences, and does not send a command',()=>{
 const a=app();a.run(`projectorChoices.set('r',false);toggleDeviceState('projector',true);rememberLedDraft();ledPreference().values[0]=2;ledPreference().tab=2;dirty.set('led.basic_pattern','2');mark('volume','60');cancelPendingSettings()`);
 assert.equal(a.run('dirty.size'),0);assert.equal(a.el('pendingSettingsBar').hidden,true);assert.equal(a.run("projectorChoices.get('r')"),false);assert.equal(a.run('ledPreference().values[0]'),9);assert.equal(a.run('ledPreference().tab'),0);assert.equal(a.run('rendered'),1);
});
test('projector selection uses logical choice rather than physical sleep relay and supports undo by clicking',()=>{
 const a=app();a.run(`view.rails[0].reported.projector=false;projectorChoices.set('r',true);toggleDeviceState('projector',false)`);assert.equal(a.run('dirty.size'),1);a.run(`toggleDeviceState('projector',true)`);assert.equal(a.run('dirty.size'),0);
});
test('cancel is blocked during application and cannot undo an already applied projector change',()=>{
 const a=app();a.run(`projectorChoices.set('r',true);toggleDeviceState('projector',false);settingsApplying=true;syncPendingSettings();cancelPendingSettings()`);assert.equal(a.run('dirty.size'),1);assert.equal(a.el('btnCancelSettings').disabled,true);
 a.run(`settingsApplying=false;dirty.delete('projector');syncPendingSettings();mark('volume','70');cancelPendingSettings()`);assert.equal(a.run("projectorChoices.get('r')"),false);
});
test('changing selection clears draft restoration data',()=>{
 const a=app();a.run(`toggleDeviceState('projector',false);rememberLedDraft();dirty.set('led','music');dirty.clear();syncPendingSettings()`);assert.equal(a.run('projectorDraftBefore'),null);assert.equal(a.run('ledDraftBefore'),null);assert.equal(a.run('pendingOriginals.size'),0);
});
test('LED pattern returned to the observed pattern removes the pending change',()=>{
 const a=app();a.run(`view.rails[0].seen_at=1;Object.assign(view.rails[0].reported,{led:'basic',led_basic_pattern:0});ledPreference().values[0]=0;setSubModeUI(2)`);assert.equal(a.run('dirty.size'),1);a.run('setSubModeUI(0)');assert.equal(a.run('dirty.size'),0);assert.equal(a.el('pendingSettingsBar').hidden,true);
});
test('reset defaults can also be cancelled with the previous LED and projector choices restored',()=>{
 const a=app();a.run(`projectorChoices.set('r',true);ledPreference().values[0]=4;ledPreference().tab=1;resetAllConfigurations();cancelPendingSettings()`);assert.equal(a.run('dirty.size'),0);assert.equal(a.run('ledPreference().values[0]'),4);assert.equal(a.run('ledPreference().tab'),1);assert.equal(a.run("projectorChoices.get('r')"),true);
});
