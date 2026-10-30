const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
test('location editor has sized map styling and click/drag update GPS inputs',async()=>{
 const nodes=[],events={},classes=new Set();let task,marker,invalidations=0;
 function node(tag){const n={tag,value:'',children:[],isConnected:true,classList:{add(v){if(tag==='form')classes.add(v)}},append(...v){this.children.push(...v)},insertBefore(v){this.children.push(v)},replaceChildren(){this.children=[]},setAttribute(){},addEventListener(){},style:{}};nodes.push(n);return n;}
 const body=node('div'),previewMap={setView(){return this},on(k,f){events[k]=f;return this},invalidateSize(){invalidations++},remove(){}};
 const L={map:()=>previewMap,tileLayer:()=>({addTo(){}}),marker:(p,options)=>{const handlers={};marker={p,handlers,icon:options.icon,setIcon(icon){this.icon=icon},dragging:{disable(){},enable(){}},addTo(){return this},on(k,f){handlers[k]=f},setLatLng(p){this.p=p},getLatLng(){return {lat:this.p[0],lng:this.p[1]}}};return marker;}};
 const ctx=vm.createContext({railMapIcon:(r,highlight)=>({number:r.number,highlight}),me:{user:{ADMIN:true}},site:'site',view:{rails:[{id:'rail',name:'난간 1',number:1,latitude:37,longitude:127}]},selected:new Set(['rail']),document:{createElement:node},dialog:()=>body,guarded:f=>task=f(),window:{L},L,$:()=>({addEventListener(){}}),requestAnimationFrame:f=>f(),AbortSignal});
 vm.runInContext(source.slice(source.indexOf('function openRailLocation(){')),ctx);ctx.openRailLocation();await task;
 assert.ok(classes.has('rail-location-editor'));assert.ok(invalidations>0);assert.equal(marker.icon.number,1);assert.equal(marker.icon.highlight,true);
 const inputs=nodes.filter(n=>n.tag==='input'),lat=inputs[1],lng=inputs[2];
 events.click({latlng:{lat:37.123456,lng:127.654321}});
 assert.equal(lat.value,'37.123456');assert.equal(lng.value,'127.654321');
 marker.p=[36.5,128.2];marker.handlers.dragend();
 assert.equal(lat.value,'36.500000');assert.equal(lng.value,'128.200000');
});
