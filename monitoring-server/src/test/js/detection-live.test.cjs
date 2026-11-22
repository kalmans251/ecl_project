const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const counts=require('../../main/resources/static/detection-count.js');
const ViewSource=fs.readFileSync(path.join(__dirname,'../../main/resources/static/detection-live.js'),'utf8');
function app(){let now=0;const sockets=[],messages=[];const document={hidden:false,addEventListener(){}};class Socket{static OPEN=1;constructor(url){this.url=url;this.readyState=1;sockets.push(this)}close(){this.onclose?.()}send(data){this.sent=data}}
const c=vm.createContext({document,window:{addEventListener(){}},performance:{now:()=>now},location:{protocol:'https:',host:'example.test'},WebSocket:Socket,setInterval(){},module:{exports:{}},update:s=>messages.push(s)});vm.runInContext(ViewSource,c);vm.runInContext('const view=new DetectionCountView(update)',c);return {run:s=>vm.runInContext(s,c),sockets,messages,document,advance:ms=>now+=ms};}
test('count socket isolates selection, reconnects and stops for hidden pages',()=>{
 const a=app();a.run("view.select('one')");const old=a.sockets[0];assert.match(old.url,/\/ws\/operator\/detection\/one$/);
 const message=(rail,count=4)=>({data:JSON.stringify({type:'detection_count',rail_id:rail,source:1,count,observed_at:1000})});old.onmessage(message('one'));assert.equal(a.messages.length,1);
 old.onmessage(message('two'));old.onmessage(message('one',-1));assert.equal(a.messages.length,1);
 a.run("view.select('two')");old.onmessage(message('one'));assert.equal(a.messages.length,1);
 a.sockets[1].onmessage(message('two',0));assert.equal(a.messages[1].count,0);
 a.document.hidden=true;a.run('view.tick()');assert.equal(a.run('view.socket'),null);
 a.document.hidden=false;a.run('view.tick()');assert.equal(a.sockets.length,3);
 a.sockets[2].onclose();a.run('view.tick()');assert.equal(a.sockets.length,3);a.advance(2000);a.run('view.tick()');assert.equal(a.sockets.length,4);
});
test('live count cannot be overwritten by older status, supports resets and stays separate from general telemetry',()=>{
 const rail={id:'live-test',seen_at:1000,reported:{detection_count:2}};
 assert.equal(counts.ingestLive({type:'detection_count',rail_id:rail.id,count:8,source:0,observed_at:2000}),true);
 assert.equal(counts.latest(rail).count,8);assert.equal(rail.reported.detection_count,2);assert.equal(rail.seen_at,1000);
 assert.equal(counts.ingestLive({type:'detection_count',rail_id:rail.id,count:7,source:0,observed_at:1500}),false);
 counts.ingestLive({type:'detection_count',rail_id:rail.id,count:0,source:1,observed_at:3000});assert.equal(counts.latest(rail).count,0);
 assert.equal(counts.latest({...rail,id:'other'}).count,2);
 assert.equal(counts.ingestLive({type:'detection_count',rail_id:rail.id,count:0x100000000,source:1,observed_at:4000}),false);
 assert.equal(counts.latest({...rail,seen_at:4000,reported:{detection_count:3}}).count,3);
});
