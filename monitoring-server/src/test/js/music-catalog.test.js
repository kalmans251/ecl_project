const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
function app(){
 const elements={};
 const context=vm.createContext({console,setTimeout,clearTimeout,performance,crypto:require('node:crypto').webcrypto,
  Option:class {constructor(text,value){this.text=text;this.value=value;}},
  window:{addEventListener(){}},document:{addEventListener(){},getElementById(id){return elements[id]??=( {value:'',disabled:false,children:[],replaceChildren(){this.children=[];this.value='';},append(item){this.children.push(item);}});}}});
 const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8').replace(/\ninit\(\);\s*$/,'');
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
