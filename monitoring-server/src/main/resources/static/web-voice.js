/* PCM endpoint only. Codec2 remains in the loopback server adapter. */
class WebVoice {
 constructor(notify){this.notify=notify;this.sources=new Set();this.context=null;this.socket=null;this.stream=null;this.node=null;this.key=null;this.transmit=false;this.generation=0;}
 async prepare(){if(!this.context)this.context=new AudioContext();await this.context.resume();}
 silence(){this.transmit=false;this.node?.port.postMessage('reset');for(const source of this.sources){try{source.stop();}catch(_){}}this.sources.clear();this.at=0;}
 close(){this.generation++;this.silence();this.key=null;if(this.socket){this.socket.onclose=null;this.socket.close();this.socket=null;}if(this.node){this.node.disconnect();this.node=null;}if(this.stream){this.stream.getTracks().forEach(t=>t.stop());this.stream=null;}}
 async mic(){await this.prepare();if(this.node)return;const generation=this.generation,stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:true,noiseSuppression:true,autoGainControl:true}});if(generation!==this.generation){stream.getTracks().forEach(t=>t.stop());return;}this.stream=stream;await this.context.audioWorklet.addModule('/mic-worklet.js');if(generation!==this.generation)return;this.node=new AudioWorkletNode(this.context,'monitor-mic');this.node.port.onmessage=e=>{if(this.transmit&&this.socket?.readyState===1&&this.socket.bufferedAmount<5120)this.socket.send(e.data);};this.context.createMediaStreamSource(stream).connect(this.node);this.node.connect(this.context.destination);}
 async sync(call,enabled){
  if(!enabled||!call?.OWNED||call.STATUS!=='ACTIVE'){this.close();return;}
  const key=call.ID+':'+call.VOICE_EPOCH;if(this.key===key&&this.socket?.readyState<2)return;
  this.close();const generation=this.generation;await this.prepare();if(generation!==this.generation)return;this.key=key;
  const ws=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/operator/voice/${call.ID}`);this.socket=ws;ws.binaryType='arraybuffer';
  ws.onopen=async()=>{if(this.socket!==ws)return;if(call.DIRECTION==='CONTROL_TX'){try{await this.mic();if(generation===this.generation){this.node?.port.postMessage('reset');this.transmit=true;}}catch(e){this.notify('마이크 오류: '+e.message);this.close();}}};
  ws.onclose=()=>{if(this.socket===ws){this.close();this.notify('음성 연결 종료. 통화 상태를 확인하거나 종료하세요.');}};
  ws.onmessage=e=>{if(this.socket!==ws||call.DIRECTION!=='FIELD_TX'||!(e.data instanceof ArrayBuffer)||e.data.byteLength!==2560)return;const data=new DataView(e.data),buffer=this.context.createBuffer(1,1280,8000),samples=buffer.getChannelData(0);for(let i=0;i<1280;i++)samples[i]=data.getInt16(i*2,true)/32768;const now=this.context.currentTime;if(!this.at||this.at<now||this.at>now+.6)this.at=now+.16;const source=this.context.createBufferSource();source.buffer=buffer;source.connect(this.context.destination);source.onended=()=>this.sources.delete(source);this.sources.add(source);source.start(this.at);this.at+=.16;};
 }
}
if(typeof module!=='undefined')module.exports={WebVoice};
