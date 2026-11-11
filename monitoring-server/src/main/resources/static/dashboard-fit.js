'use strict';
(() => {
 const WIDTH=2400,HEIGHT=1350,MIN_SCALE=0.5;
 const stage=document.getElementById('dashboardStage');
 const canvas=document.getElementById('dashboardCanvas');
 if(!stage||!canvas)return;
 let frame=0;
 function fit(){
  frame=0;
  // CSS viewport dimensions also change when browser zoom changes.
  // Use the layout viewport: pinch zoom must retain native pan/zoom behavior.
  const width=document.documentElement.clientWidth;
  const height=window.innerHeight;
  if(width<=0||height<=0)return;
  const scale=Math.max(MIN_SCALE,Math.min(width/WIDTH,height/HEIGHT));
  stage.style.width=(WIDTH*scale)+'px';
  stage.style.height=(HEIGHT*scale)+'px';
  canvas.style.transform='scale('+scale+')';
 }
 function schedule(){if(!frame)frame=requestAnimationFrame(fit);}
 fit();
 window.addEventListener('resize',schedule,{passive:true});
 window.addEventListener('pageshow',schedule);
})();
