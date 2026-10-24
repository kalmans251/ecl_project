const {test}=require('node:test'),assert=require('node:assert/strict');
const {WebVoice}=require('../../main/resources/static/web-voice.js');
const epochs=['11111111-1111-4111-8111-111111111111','22222222-2222-4222-8222-222222222222','33333333-3333-4333-8333-333333333333'];
const call=(i,direction='FIELD_TX')=>({OWNED:true,STATUS:'ACTIVE',ID:'call',VOICE_EPOCH:epochs[i],DIRECTION:direction});
function setup(){
 const sockets=[];global.location={protocol:'https:',host:'test'};
 global.WebSocket=class{constructor(){this.readyState=0;this.bufferedAmount=0;this.sent=[];this.closed=0;sockets.push(this);}send(data){this.sent.push(data);}close(){this.closed++;this.readyState=3;}};
 const v=new WebVoice(()=>{});v.prepare=async()=>{};v.mic=async()=>{v.node={port:{postMessage(){}},disconnect(){}};};
 return {v,sockets};
}
async function ready(v,ws,i,direction){await v.message(ws,JSON.stringify({type:'ready',epoch:epochs[i],direction}));}
test('one socket survives listening talking and listening; old PCM is dropped',async()=>{
 const {v,sockets}=setup();await v.sync(call(0),true);const ws=v.socket;ws.readyState=1;ws.onopen();await ready(v,ws,0,'FIELD_TX');
 v.pause();assert.equal(v.transmit,false);await v.sync({...call(0),STATUS:'SWITCHING'},true);assert.equal(ws.closed,0);
 await v.sync(call(1,'CONTROL_TX'),true);assert.equal(v.transmit,false);await ready(v,ws,0,'FIELD_TX');assert.equal(v.ready,false);
 await ready(v,ws,1,'CONTROL_TX');assert.equal(v.transmit,true);
 v.pcm(new ArrayBuffer(2560),epochs[0]);assert.equal(v.sent,0);
 v.pcm(new ArrayBuffer(2560),epochs[1]);assert.equal(v.sent,1);assert.equal(ws.sent.at(-1).byteLength,2596);
 v.pause();await v.sync(call(2),true);await ready(v,ws,2,'FIELD_TX');assert.equal(v.transmit,false);assert.equal(v.node,null);
 assert.equal(sockets.length,1);assert.equal(ws.closed,0);v.close();assert.equal(ws.closed,1);
});
test('switch while socket is connecting binds only latest epoch on open',async()=>{
 const {v,sockets}=setup();await v.sync(call(0),true);await v.sync(call(1,'CONTROL_TX'),true);assert.equal(sockets.length,1);
 v.socket.readyState=1;v.socket.onopen();assert.equal(JSON.parse(v.socket.sent[0]).epoch,epochs[1]);
});
test('unknown state stops microphone and closes transport',async()=>{
 const {v}=setup();await v.sync(call(0),true);const ws=v.socket;let stopped=0;v.stream={getTracks:()=>[{stop(){stopped++;}}]};
 await v.sync({...call(0),STATUS:'UNKNOWN'},true);assert.equal(ws.closed,1);assert.equal(stopped,1);assert.equal(v.transmit,false);
});
test('superseded audio preparation cannot create a socket',async()=>{
 const {v,sockets}=setup();let release;v.prepare=()=>new Promise(r=>release=r);const pending=v.sync(call(0),true);v.close();release();await pending;assert.equal(sockets.length,0);
});
test('delayed ready cannot enable microphone after pause',async()=>{
 const {v}=setup();await v.sync(call(1,'CONTROL_TX'),true);v.socket.readyState=1;let release;v.mic=()=>new Promise(r=>release=r);
 const pending=ready(v,v.socket,1,'CONTROL_TX');v.pause();release();await pending;assert.equal(v.transmit,false);
});
test('old downlink epoch is rejected before scheduling playback',async()=>{
 const {v}=setup();await v.sync(call(2),true);v.ready=true;
 const packet=new Uint8Array(2596);for(let i=0;i<36;i++)packet[i]=epochs[0].charCodeAt(i);
 await v.message(v.socket,packet.buffer);assert.equal(v.sources.size,0);
});
test('diagnostics distinguish capture from actual send and signed peak',async()=>{
 const {v}=setup(),messages=[];v.diagnostic=s=>messages.push(s);await v.sync(call(1,'CONTROL_TX'),true);v.socket.readyState=1;await ready(v,v.socket,1,'CONTROL_TX');
 const pcm=new ArrayBuffer(2560);new DataView(pcm).setInt16(0,-32768,true);v.socket.bufferedAmount=6000;v.pcm(pcm,epochs[1]);assert.equal(v.sent,0);assert.match(messages.at(-1),/peak 32768/);
 v.socket.bufferedAmount=0;v.pcm(pcm,epochs[1]);assert.equal(v.sent,1);
});
test('worklet drops partial old samples and tags only the newly confirmed epoch',()=>{
 const fs=require('node:fs'),vm=require('node:vm');let Processor;const sent=[];
 const context=vm.createContext({AudioWorkletProcessor:class{constructor(){this.port={postMessage:m=>sent.push(m)};}},sampleRate:8000,registerProcessor:(name,type)=>{Processor=type;}});
 vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../../main/resources/static/mic-worklet.js'),'utf8'),context);
 const processor=new Processor();processor.port.onmessage({data:{epoch:epochs[0]}});processor.process([[new Float32Array(100).fill(.8)]]);
 processor.port.onmessage({data:{epoch:null}});processor.process([[new Float32Array(1280).fill(.8)]]);assert.equal(sent.length,0);
 processor.port.onmessage({data:{epoch:epochs[1]}});processor.process([[new Float32Array(1280).fill(.1)]]);
 assert.equal(sent.length,1);assert.equal(sent[0].epoch,epochs[1]);assert.equal(new DataView(sent[0].data).getInt16(0,true),3277);
});
