'use strict';
// One selected rail per view. Server fans one gateway poll out to all viewers.
class RadarView {
  constructor(draw, status) {
    this.draw=draw;this.status=status;this.rail=null;this.socket=null;this.deadline=0;this.retry=0;
    this.points=[];this.label='좌표 대기';this.heartbeat=0;
    this.timer=setInterval(()=>this.tick(),250);
    document.addEventListener('visibilitychange',()=>this.tick());
    window.addEventListener('pagehide',()=>{this.rail=null;this.close();});
  }
  select(rail) {
    if(rail===this.rail)return;
    this.rail=rail;this.retry=0;this.close();this.tick();
  }
  close() {
    const socket=this.socket;this.socket=null;if(socket)socket.close();
    this.points=[];this.deadline=0;this.draw([]);
  }
  tick() {
    const now=performance.now();
    if(!this.rail || document.hidden){if(this.socket)this.close();this.status(this.rail?'화면 비활성 · 조회 중단':'난간 하나를 선택하세요');return;}
    if(!this.socket && now>=this.retry) {
      const rail=this.rail,socket=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/ws/operator/radar/${encodeURIComponent(rail)}`);
      this.socket=socket;this.label='좌표 연결 중';this.status(this.label);
      socket.onopen=()=>{this.heartbeat=performance.now();};
      socket.onmessage=event=>{
        if(socket!==this.socket || rail!==this.rail)return;
        try{
          const s=JSON.parse(event.data);if(s.type!=='radar'||s.rail_id!==rail)return;
          const valid=s.fresh===true && s.available===true;
          const targets=valid && s.detail===true && Array.isArray(s.targets)?s.targets:[];
          this.points=targets;this.deadline=performance.now()+Math.min(2500,Math.max(0,s.expires_in_ms||0));
          this.label=valid?`레이더 ${s.source} · ${s.count}명${s.count>0&&!s.detail?' · 좌표 요청 중':''}`:
            s.reason==='call_or_emergency'?'통화·비상 중 · 좌표 조회 일시 중단':'좌표 미수신 / 센서 상태 확인 중';
          this.draw(targets);this.status(this.label);
        }catch{this.points=[];this.deadline=0;this.draw([]);}
      };
      socket.onclose=()=>{if(socket!==this.socket)return;this.socket=null;this.retry=performance.now()+2000;this.deadline=0;this.points=[];this.draw([]);this.status('좌표 연결 끊김 · 재연결 대기');};
    }
    if(this.socket?.readyState===WebSocket.OPEN && now-this.heartbeat>=5000){this.socket.send('ping');this.heartbeat=now;}
    if(this.deadline && now>this.deadline){this.deadline=0;this.points=[];this.draw([]);this.status('좌표 갱신 지연 · 현재 위치 미확인');}
  }
}
if(typeof module!=='undefined')module.exports=RadarView;
