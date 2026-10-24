/* PCM endpoint only. Codec2 remains in the loopback server adapter. */
class WebVoice {
 constructor(notify,diagnostic=()=>{}){this.notify=notify;this.diagnostic=diagnostic;this.captured=0;this.sent=0;this.sources=new Set();this.context=null;this.socket=null;this.stream=null;this.node=null;this.key=null;this.transmit=false;this.generation=0;}
 report(message){this.diagnostic(message);}
 pcm(data){
  this.captured++;let peak=0;const view=new DataView(data);for(let i=0;i+1<data.byteLength;i+=2)peak=Math.max(peak,Math.abs(view.getInt16(i,true)));
  if(this.transmit&&this.socket?.readyState===1&&this.socket.bufferedAmount<5120){this.socket.send(data);this.sent++;}
  if(this.captured===1||this.captured%25===0)this.report(`마이크 PCM ${this.captured} · 웹 전송 ${this.sent} · peak ${peak} · 오디오 ${this.context?.state} · WS ${this.socket?.readyState??'없음'}`);
 }
 async prepare(){if(!this.context)this.context=new AudioContext();await this.context.resume();}
 silence(){this.transmit=false;this.node?.port.postMessage('reset');for(const source of this.sources){try{source.stop();}catch(_){}}this.sources.clear();this.at=0;}
 close(keepMic=false){this.generation++;this.silence();this.key=null;if(this.socket){this.socket.onclose=null;this.socket.close();this.socket=null;}if(!keepMic&&this.node){this.node.disconnect();this.node=null;}if(!keepMic&&this.stream){this.stream.getTracks().forEach(t=>t.stop());this.stream=null;}}
 async mic(){await this.prepare();if(this.node)return;const generation=this.generation,stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}this.stream=stream;this.report('마이크 권한 확보 · 오디오 처리기 준비 중');await this.context.audioWorklet.addModule('/mic-worklet.js');if(generation!==this.generation)return;this.node=new AudioWorkletNode(this.context,'monitor-mic');this.node.onprocessorerror=()=>this.report('마이크 오디오 처리기 오류');this.node.port.onmessage=e=>this.pcm(e.data);this.report('마이크 준비 완료 · 방향 전환 대기');this.context.createMediaStreamSource(stream).connect(this.node);this.node.connect(this.context.destination);}
 async sync(call,enabled){
  if(!enabled||!call?.OWNED||call.STATUS!=='ACTIVE'){this.close();return;}
  const key=call.ID+':'+call.VOICE_EPOCH;if(this.key===key&&this.socket?.readyState<2)return;
  this.close(call.DIRECTION==='CONTROL_TX');const generation=this.generation;await this.prepare();if(generation!==this.generation)return;this.key=key;
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/operator/voice/${call.ID}`);this.socket=ws;this.captured=0;this.sent=0;this.report('음성 WebSocket 연결 중 · '+call.DIRECTION);ws.binaryType='arraybuffer';
  ws.onopen=async()=>{if(this.socket!==ws)return;this.report('음성 WebSocket 연결 완료 · '+call.DIRECTION);if(call.DIRECTION==='CONTROL_TX'){try{await this.mic();if(generation===this.generation){this.node?.port.postMessage('reset');this.transmit=true;this.report('말하기 연결 완료 · 마이크 PCM 대기');}}catch(e){this.report('마이크 오류: '+e.name+' · '+e.message);this.notify('마이크 오류: '+e.message);this.close();}}};
  ws.onerror=()=>{if(this.socket===ws)this.report('음성 WebSocket 오류 · Network의 연결 상태 확인 필요');};
  ws.onclose=e=>{if(this.socket===ws){const detail=`음성 연결 종료 · code ${e.code} · ${e.reason||'사유 없음'} · PCM ${this.captured} / 전송 ${this.sent}`;this.close();this.report(detail);this.notify(detail);}};
  ws.onmessage=e=>{if(this.socket!==ws||call.DIRECTION!=='FIELD_TX'||!(e.data instanceof ArrayBuffer)||e.data.byteLength!==2560)return;const data=new DataView(e.data),buffer=this.context.createBuffer(1,1280,8000),samples=buffer.getChannelData(0);for(let i=0;i<1280;i++)samples[i]=data.getInt16(i*2,true)/32768;const now=this.context.currentTime;if(!this.at||this.at<now||this.at>now+.6)this.at=now+.16;const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.context.destination);source.onended=()=>this.sources.delete(source);this.sources.add(source);source.start(this.at);this.at+=.16;};
 }
}
if(typeof module!=='undefined')module.exports={WebVoice};
