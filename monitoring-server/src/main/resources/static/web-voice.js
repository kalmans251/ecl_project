/* One authenticated socket per call; every PCM packet carries its confirmed epoch. */
class WebVoice {
 constructor(notify,diagnostic=()=>{}){Object.assign(this,{notify,diagnostic,captured:0,sent:0,context:null,socket:null,stream:null,node:null,input:null,callId:null,epoch:null,direction:null,ready:false,transmit:false,generation:0,sources:new Set()});}
 report(message){this.diagnostic(message);}
 async prepare(){if(!this.context)this.context=new AudioContext();await this.context.resume();}
 silence(){this.transmit=false;this.ready=false;this.node?.port.postMessage({epoch:null});for(const source of this.sources){try{source.stop();}catch(_){}}this.sources.clear();this.at=0;}
 pause(){this.generation++;this.silence();this.epoch=null;this.direction=null;}
 stopMic(){this.input?.disconnect();this.input=null;this.node?.disconnect();this.node=null;this.stream?.getTracks().forEach(t=>t.stop());this.stream=null;}
 close(){this.generation++;this.pause();this.callId=null;const ws=this.socket;this.socket=null;if(ws){ws.onclose=null;ws.close();}this.stopMic();}
 async mic(){
  await this.prepare();if(this.node)return;const generation=this.generation;
  const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
  if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}
  this.stream=stream;this.report('마이크 권한 확보 · 오디오 처리기 준비 중');
  try{await this.context.audioWorklet.addModule('/mic-worklet.js');}catch(e){if(this.stream===stream)this.stopMic();throw e;}
  if(generation!==this.generation)return;
  this.node=new AudioWorkletNode(this.context,'monitor-mic');
  this.node.onprocessorerror=()=>{this.silence();this.report('마이크 오디오 처리기 오류');};
  this.node.port.onmessage=e=>this.pcm(e.data.data,e.data.epoch);
  this.input=this.context.createMediaStreamSource(stream);this.input.connect(this.node);this.node.connect(this.context.destination);
  this.report('마이크 준비 완료 · 방향 확인 대기');
 }
 pcm(data,epoch){
  if(!(data instanceof ArrayBuffer)||data.byteLength!==2560||!epoch||epoch!==this.epoch||!this.ready)return;
  this.captured++;let peak=0;const view=new DataView(data);for(let i=0;i<data.byteLength;i+=2)peak=Math.max(peak,Math.abs(view.getInt16(i,true)));
  if(this.transmit&&this.socket?.readyState===1&&this.socket.bufferedAmount<5192){
   const packet=new Uint8Array(2596);for(let i=0;i<36;i++)packet[i]=epoch.charCodeAt(i);packet.set(new Uint8Array(data),36);this.socket.send(packet.buffer);this.sent++;
  }
  if(this.captured===1||this.captured%25===0)this.report(`마이크 PCM ${this.captured} · 웹 전송 ${this.sent} · peak ${peak} · 오디오 ${this.context?.state} · WS ${this.socket?.readyState??'없음'}`);
 }
 bind(){if(this.socket?.readyState===1&&this.epoch)this.socket.send(JSON.stringify({type:'bind',epoch:this.epoch,direction:this.direction}));}
 async message(ws,data){
  if(this.socket!==ws)return;
  if(typeof data==='string'){
   let ack;try{ack=JSON.parse(data);}catch(_){return;}
   if(ack.type!=='ready'||ack.epoch!==this.epoch||ack.direction!==this.direction)return;
   const epoch=this.epoch,generation=this.generation;
   try{
    if(this.direction==='CONTROL_TX')await this.mic();
    if(this.socket!==ws||epoch!==this.epoch||generation!==this.generation)return;
    this.ready=true;this.transmit=this.direction==='CONTROL_TX';this.node?.port.postMessage({epoch:this.transmit?epoch:null});
    this.report(this.transmit?'말하기 연결 완료 · 마이크 PCM 대기':'듣기 연결 완료');
   }catch(e){this.pause();this.stopMic();this.report('마이크 오류: '+e.name+' · '+e.message);this.notify('마이크 오류: '+e.message);}
   return;
  }
  if(!this.ready||this.direction!=='FIELD_TX'||!(data instanceof ArrayBuffer)||data.byteLength!==2596)return;
  if(String.fromCharCode(...new Uint8Array(data,0,36))!==this.epoch)return;
  const pcm=new DataView(data,36),buffer=this.context.createBuffer(1,1280,8000),samples=buffer.getChannelData(0);
  for(let i=0;i<1280;i++)samples[i]=pcm.getInt16(i*2,true)/32768;
  const now=this.context.currentTime;if(!this.at||this.at<now||this.at>now+.6)this.at=now+.16;
  const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.context.destination);source.onended=()=>this.sources.delete(source);this.sources.add(source);source.start(this.at);this.at+=.16;
 }
 async sync(call,enabled){
  if(!enabled||!call?.OWNED){this.close();return;}
  if(['SWITCHING','ENDING'].includes(call.STATUS)){this.pause();return;}
  if(call.STATUS!=='ACTIVE'){this.close();return;}
  if(this.callId&&this.callId!==call.ID)this.close();
  if(this.epoch===call.VOICE_EPOCH&&this.direction===call.DIRECTION&&this.socket?.readyState<2)return;
  this.pause();this.callId=call.ID;this.epoch=call.VOICE_EPOCH;this.direction=call.DIRECTION;
  if(this.direction!=='CONTROL_TX')this.stopMic();
  const generation=this.generation,epoch=this.epoch;await this.prepare();
  if(generation!==this.generation||epoch!==this.epoch)return;
  if(this.socket?.readyState<2){this.bind();return;}
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/operator/voice/${call.ID}`);
  this.socket=ws;ws.binaryType='arraybuffer';this.captured=0;this.sent=0;this.report('음성 WebSocket 연결 중');
  ws.onopen=()=>{if(this.socket===ws)this.bind();};
  ws.onmessage=e=>this.message(ws,e.data);
  ws.onerror=()=>{if(this.socket===ws)this.report('음성 WebSocket 오류 · Network 확인 필요');};
  ws.onclose=e=>{if(this.socket===ws){const detail=`음성 연결 종료 · code ${e.code} · ${e.reason||'사유 없음'} · PCM ${this.captured} / 전송 ${this.sent}`;this.close();this.report(detail);this.notify(detail);}};
 }
}
if(typeof module!=='undefined')module.exports={WebVoice};
