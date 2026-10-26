const {test}=require('node:test');const assert=require('node:assert/strict');
const RadarView=require('../../main/resources/static/radar-view.js');
test('selection isolation, disconnect, visibility and stale clearing',()=>{
 const old={setInterval:global.setInterval,document:global.document,window:global.window,WebSocket:global.WebSocket,location:global.location};
 try{
  global.setInterval=()=>1;global.document={hidden:false,addEventListener(){}};global.window={addEventListener(){}};global.location={protocol:'https:',host:'example.test'};
  const sockets=[];global.WebSocket=class{static OPEN=1;constructor(url){this.url=url;this.readyState=1;sockets.push(this);}close(){this.closed=true;}send(){}};
  let points,label;const view=new RadarView(p=>points=p,s=>label=s);
  view.select('rail-a');const first=sockets[0];assert.match(first.url,/rail-a$/);
  const msg=(id)=>({data:JSON.stringify({type:'radar',rail_id:id,fresh:true,available:true,detail:true,count:1,source:2,targets:[{x:1,y:2}],expires_in_ms:1000})});
  first.onmessage(msg('rail-a'));assert.equal(points.length,1);
  view.select('rail-b');assert.equal(first.closed,true);first.onmessage(msg('rail-a'));assert.deepEqual(points,[]);
  sockets[1].onmessage(msg('rail-b'));assert.equal(points.length,1);
  view.deadline=performance.now()-1;view.tick();assert.deepEqual(points,[]);assert.match(label,/미확인/);
  document.hidden=true;view.tick();assert.equal(sockets[1].closed,true);
  document.hidden=false;view.tick();assert.equal(sockets.length,3);
  view.select(null);assert.equal(sockets[2].closed,true);
 }finally{Object.assign(global,old);}
});
