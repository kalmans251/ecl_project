/* Latest-frame metadata; intentionally independent of the WHEP connection. */
(function(root){
 function fit(width,height,vw,vh){
  const scale=Math.min(width/vw,height/vh);
  return {x:(width-vw*scale)/2,y:(height-vh*scale)/2,w:vw*scale,h:vh*scale};
 }
 function label(p){
  if(p.state==='estimated'&&Number.isFinite(p.age))return '#'+p.id+' 추정 '+Math.round(p.age)+'세';
  return '#'+p.id+' '+({pending:'나이 분석 중',unknown:'나이 미확정',disabled:'연령 분석 꺼짐',unavailable:'연령 분석 불가'})[p.state];
 }
 function attach(camera,video,canvas,status,toggle){
  const ctx=canvas.getContext('2d');let stopped=false,data=null,received=0,requestCost=0,lastTime=-1,lastProgress=0,abort;
  function clear(){ctx.clearRect(0,0,canvas.width,canvas.height);}
  function render(){
   if(stopped)return;
   const now=performance.now(),width=video.clientWidth,height=video.clientHeight;
   if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
   clear();
   if(video.currentTime!==lastTime){lastTime=video.currentTime;lastProgress=now;}
   const fresh=data?.fresh&&data.age_ms+requestCost+now-received<=1000;
   if(toggle.checked&&fresh&&!video.paused&&video.readyState>=2&&now-lastProgress<500&&video.videoWidth&&video.videoHeight){
    const rect=fit(width,height,video.videoWidth,video.videoHeight);
    ctx.font='bold 15px sans-serif';ctx.lineWidth=2;ctx.strokeStyle='#39ff88';
    for(const p of data.people){
     const [l,t,r,b]=p.box,x=rect.x+l*rect.w,y=rect.y+t*rect.h,w=(r-l)*rect.w,h=(b-t)*rect.h;
     ctx.strokeRect(x,y,w,h);
     const text=label(p),tw=Math.min(width,ctx.measureText(text).width+12),tx=Math.max(0,Math.min(x,width-tw)),ty=Math.max(0,y-24);
     ctx.fillStyle='rgba(0,0,0,.8)';ctx.fillRect(tx,ty,tw,24);ctx.fillStyle='#fff';ctx.fillText(text,tx+6,ty+17);
    }
   }
   status.textContent=!toggle.checked?'분석 표시 꺼짐':!fresh?'분석 결과 대기 / 오래된 결과 숨김':'실시간 분석 · 최대 20명 · 영상과 시차가 있을 수 있음';
   requestAnimationFrame(render);
  }
  async function poll(){
   while(!stopped){
    if(!document.hidden){
     abort=new AbortController();const timer=setTimeout(()=>abort.abort(),800),start=performance.now();
     try{
      const r=await fetch('/api/portal/cctv/'+encodeURIComponent(camera)+'/overlay',{cache:'no-store',signal:abort.signal});
      if(!r.ok)throw Error('overlay unavailable');
      const next=await r.json();
      if(!stopped){data=next;received=performance.now();requestCost=received-start;}
     }catch(e){data=null;}finally{clearTimeout(timer);}
    }else data=null;
    await new Promise(resolve=>setTimeout(resolve,200));
   }
  }
  render();poll();
  return {clear(){data=null;clear();},stop(){stopped=true;abort?.abort();data=null;clear();}};
 }
 root.CameraOverlay={fit,label,attach};
 if(typeof module!=='undefined')module.exports=root.CameraOverlay;
})(globalThis);
