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
