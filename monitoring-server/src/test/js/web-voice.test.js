const {test}=require('node:test');
const assert=require('node:assert/strict');
const {WebVoice}=require('../../main/resources/static/web-voice.js');
test('superseded preparation cannot open a stale voice connection',async()=>{
 const v=new WebVoice(()=>{});let release;
 v.prepare=()=>new Promise(r=>release=r);
 const opening=v.sync({OWNED:true,STATUS:'ACTIVE',ID:'call',VOICE_EPOCH:'old'},true);
 v.close();release();await opening;assert.equal(v.socket,null);assert.equal(v.key,null);
});
test('unknown call closes media and stops microphone tracks',async()=>{
 const v=new WebVoice(()=>{});let stopped=0,closed=0;
 v.stream={getTracks:()=>[{stop:()=>stopped++}]};v.socket={close:()=>closed++};v.transmit=true;
 await v.sync({OWNED:true,STATUS:'UNKNOWN'},true);
 assert.equal(stopped,1);assert.equal(closed,1);assert.equal(v.transmit,false);
});
test('confirmed talk reuses prepared microphone and sends only after socket opens',async()=>{
 const priorLocation=global.location,priorSocket=global.WebSocket;
 let stops=0,disconnects=0,micStarts=0;
 global.location={protocol:'https:',host:'test'};
 global.WebSocket=class {constructor(){this.readyState=0;}close(){this.readyState=3;}};
 try{
  const v=new WebVoice(()=>{});v.prepare=async()=>{};
  const node={disconnect(){disconnects++;},port:{postMessage(){}}};
  v.node=node;v.stream={getTracks:()=>[{stop(){stops++;}}]};
  v.mic=async()=>{micStarts++;assert.equal(v.node,node);};
  await v.sync({OWNED:true,STATUS:'ACTIVE',ID:'c',VOICE_EPOCH:'talk',DIRECTION:'CONTROL_TX'},true);
  assert.equal(stops,0);assert.equal(disconnects,0);assert.equal(v.transmit,false);
  v.socket.readyState=1;await v.socket.onopen();assert.equal(v.transmit,true);assert.equal(micStarts,1);
  await v.sync({OWNED:true,STATUS:'ACTIVE',ID:'c',VOICE_EPOCH:'listen',DIRECTION:'FIELD_TX'},true);
  assert.equal(v.transmit,false);assert.equal(stops,1);assert.equal(disconnects,1);
 }finally{global.location=priorLocation;global.WebSocket=priorSocket;}
});
test('diagnostics distinguish capture from socket transmission and report signed PCM peak',()=>{
 const messages=[],v=new WebVoice(()=>{},s=>messages.push(s));v.context={state:'running'};
 let sends=0;v.socket={readyState:1,bufferedAmount:0,send(){sends++;}};
 const pcm=new ArrayBuffer(2560);new DataView(pcm).setInt16(0,-32768,true);
 v.pcm(pcm);assert.equal(v.captured,1);assert.equal(v.sent,0);assert.match(messages[0],/peak 32768/);
 v.transmit=true;v.pcm(pcm);assert.equal(v.sent,1);assert.equal(sends,1);
 v.socket.bufferedAmount=5120;v.pcm(pcm);assert.equal(v.captured,3);assert.equal(v.sent,1);
});
