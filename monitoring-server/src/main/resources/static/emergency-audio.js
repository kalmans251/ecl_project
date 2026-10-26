/* WROOM: 16 kHz square wave, 880/660 Hz alternating every 350 ms. */
class EmergencyAudio {
 constructor(makeContext,notify=()=>{}){this.makeContext=makeContext;this.notify=notify;this.context=null;this.source=null;this.pending=new Set();this.muted=new Set();this.inCall=false;}
 async enable(){
  if(!this.context){this.context=this.makeContext();this.context.onstatechange=()=>this.render();}
  await this.context.resume();this.render();
  if(this.context.state!=='running')throw Error('브라우저에서 알림음 재생을 허용하세요.');
 }
 sync(rails,calls){
  this.pending=new Set(rails.filter(r=>r.reported?.emergency).map(r=>r.id+':'+(r.reported.emergency_at??r.seen_at??0)));
  this.muted=new Set([...this.muted].filter(id=>this.pending.has(id)));
  this.inCall=calls.some(c=>c.OWNED);this.render();
 }
 muteRail(rail){for(const id of this.pending)if(id.startsWith(rail+':'))this.muted.add(id);this.render();}
 mute(){for(const id of this.pending)this.muted.add(id);this.render();}
 render(){
  const wanted=[...this.pending].some(id=>!this.muted.has(id))&&!this.inCall;
  const enabled=this.context?.state==='running';
  if(wanted&&enabled&&!this.source){
   const buffer=this.context.createBuffer(1,11200,16000),data=buffer.getChannelData(0);let phase=0;
   for(let i=0;i<data.length;i++){data[i]=phase<8000?.12:-.12;phase=(phase+(i<5600?880:660))%16000;}
   this.source=this.context.createBufferSource();this.source.buffer=buffer;this.source.loop=true;this.source.connect(this.context.destination);this.source.start();
  }else if((!wanted||!enabled)&&this.source){this.source.stop();this.source.disconnect();this.source=null;}
  this.notify(!enabled?'비상 알림음 비활성 · 활성화 필요':this.inCall?'통화 중 · 알림음 일시정지':this.source?'비상 알림음 재생 중':this.pending.size?'현재 호출 음소거':'비상 알림음 활성');
 }
}
if(typeof module!=='undefined')module.exports={EmergencyAudio};
