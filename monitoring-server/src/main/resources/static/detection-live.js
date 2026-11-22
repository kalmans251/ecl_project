'use strict';
// Subscribe to P4 counts in both CCTV and radar mode. Never increments locally.
class DetectionCountView {
 constructor(update){
  this.update=update;this.rail=null;this.socket=null;this.retry=0;this.heartbeat=0;
  this.timer=setInterval(()=>this.tick(),250);
  document.addEventListener('visibilitychange',()=>this.tick());
  window.addEventListener('pagehide',()=>{this.rail=null;this.close();});
 }
 select(rail){if(rail===this.rail)return;this.rail=rail;this.retry=0;this.close();this.tick();}
 close(){const socket=this.socket;this.socket=null;if(socket)socket.close();}
 tick(){
  const now=performance.now();
  if(!this.rail||document.hidden){this.close();return;}
  if(!this.socket&&now>=this.retry){
   const rail=this.rail,socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/operator/detection/${encodeURIComponent(rail)}`);
   this.socket=socket;
   socket.onopen=()=>{this.heartbeat=performance.now();};
   socket.onmessage=event=>{
    if(socket!==this.socket||rail!==this.rail)return;
    try{
     const s=JSON.parse(event.data);
     if(s.type!=='detection_count'||s.rail_id!==rail||!Number.isInteger(s.count)||s.count<0||s.count>0xffffffff||![0,1].includes(s.source)||!Number.isFinite(s.observed_at))return;
     this.update(s);
    }catch{}
   };
   socket.onclose=()=>{if(socket!==this.socket)return;this.socket=null;this.retry=performance.now()+2000;};
  }
  if(this.socket?.readyState===WebSocket.OPEN&&now-this.heartbeat>=5000){this.socket.send('ping');this.heartbeat=now;}
 }
}
if(typeof module!=='undefined')module.exports=DetectionCountView;
