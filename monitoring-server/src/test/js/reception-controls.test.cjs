const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
function app(){
 const elements=new Map();const toggles={};
 function el(id){if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,value:'',style:{},classList:{toggle(){}},replaceChildren(){},append(){},open:false,showModal(){this.open=true},close(){this.open=false}});return elements.get(id)}
 for(const type of ['alarmBell','radar'])toggles[type]=[true,false].map(enabled=>({dataset:{enabled:String(enabled)},disabled:false,active:false,classList:{toggle(_,value){this.owner.active=value}},setAttribute(key,value){this[key]=value}}));
 for(const list of Object.values(toggles))for(const button of list)button.classList.owner=button;
 const document={getElementById:el,addEventListener(){},createElement:()=>({append(){}}),querySelectorAll:s=>toggles[s.match(/data-device-toggle="([^"]+)"/)?.[1]]||[]};
 const context=vm.createContext({document,window:{addEventListener(){}},crypto:{randomUUID:()=> 'test'},structuredClone,RadarView:class{},setTimeout:()=>0,clearTimeout(){},performance:{now:()=>0}});
 vm.runInContext(source.replace(/^init\(\);$/m,''),context);
 const run=s=>vm.runInContext(s,context);
 run(`site='s';view={role:'OPERATOR',calls:[],rails:[{id:'r',name:'난간 1',online:true,reported:{alarm_enabled:true,sensor_enabled:true}}]};selected=new Set(['r']);const sent=[];let confirmValues=true;renderLive=()=>syncReceptionControls();waitAppliedSnapshot=async()=>{};send=async(op,value,targets)=>{sent.push({op,value,targets});if(confirmValues)view.rails[0].reported[op==='alarm'?'alarm_enabled':'sensor_enabled']=value==='on';};syncReceptionControls();`);
 return {run,el,toggles};
}
test('both enabled reception controls stage their own operation and show pending choices',()=>{
 const a=app();assert.equal(a.toggles.alarmBell[0].disabled,false);assert.equal(a.toggles.radar[0].active,true);
 a.run("toggleDeviceState('alarmBell',false);toggleDeviceState('radar',false)");assert.equal(a.run("dirty.get('alarm')"),'off');assert.equal(a.run("dirty.get('sensor')"),'off');assert.equal(a.toggles.alarmBell[1].active,true);assert.equal(a.run('sent.length'),0);
});
test('original selection and cancel restore the confirmed reception state',()=>{
 const a=app();a.run("toggleDeviceState('alarmBell',false);toggleDeviceState('alarmBell',true)");assert.equal(a.run('dirty.size'),0);
 a.run("toggleDeviceState('radar',false);cancelPendingSettings()");assert.equal(a.run('dirty.size'),0);assert.equal(a.toggles.radar[0].active,true);assert.equal(a.run('sent.length'),0);
});
test('VIEWER, offline, no selection, call, emergency and in-flight requests cannot stage changes',()=>{
 for(const setup of ["view.role='VIEWER'","view.rails[0].online=false","selected.clear()","view.calls=[{RAIL_ID:'r'}]","view.rails[0].reported.emergency=true","settingsApplying=true","controlBusy=true"]){
  const a=app();a.run(setup+";syncReceptionControls();toggleDeviceState('radar',false)");assert.equal(a.toggles.radar[0].disabled,true);assert.equal(a.run('dirty.size'),0);
 }
});
test('mixed and unknown states stay neutral while online operators can request explicit values',()=>{
 const a=app();a.run("view.rails.push({id:'r2',online:true,reported:{alarm_enabled:false}});selected.add('r2');syncReceptionControls()");assert.equal(a.toggles.alarmBell.some(b=>b.active),false);assert.equal(a.toggles.alarmBell[0].disabled,false);
 a.run("toggleDeviceState('alarmBell',true)");assert.equal(a.run("dirty.get('alarm')"),'on');
});
test('apply sends both commands and clears only after confirmed state matches',async()=>{
 const a=app();a.run("toggleDeviceState('alarmBell',false);toggleDeviceState('radar',false)");await a.run('applyAllUpdates()');assert.equal(a.run('sent.map(s=>s.op).join()'),'alarm,sensor');assert.equal(a.run('dirty.size'),0);assert.equal(a.run('view.rails[0].reported.sensor_enabled'),false);
});
test('mismatched or missing P4 readback keeps the edit and never claims completion',async()=>{
 for(const unknown of [false,true]){const a=app();a.run("toggleDeviceState('alarmBell',false);confirmValues=false");if(unknown)a.run('delete view.rails[0].reported.alarm_enabled');await a.run('applyAllUpdates()');assert.equal(a.run("dirty.get('alarm')"),'off');assert.equal(a.run('settingsApplying'),false);assert.equal(a.run('sent.length'),1);assert.match(a.el('pendingSettingsResult').textContent,unknown?/확인하지 못/:/다릅니다/);}
});
