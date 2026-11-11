const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/dashboard-fit.js'),'utf8');
for(const [width,height] of [[2400,1350],[1920,1080],[1920,1200],[1536,864],[1366,768],[3840,2160],[3440,1440],[1280,1024],[800,600],[390,844]]){
 const stage={style:{}},canvas={style:{}},events={};
 const document={documentElement:{clientWidth:width},getElementById:id=>id==='dashboardStage'?stage:canvas};
 const window={innerHeight:height,addEventListener:(name,fn)=>events[name]=fn};
 let queued;
 vm.runInNewContext(source,{document,window,requestAnimationFrame:fn=>{queued=fn;return 1;}});
 const scale=Math.max(.5,Math.min(width/2400,height/1350));
 assert.equal(canvas.style.transform,'scale('+scale+')');
 const sw=parseFloat(stage.style.width),sh=parseFloat(stage.style.height);
 assert.ok(Math.abs(sw-Math.max(width,2400*scale))<.01);
 assert.ok(Math.abs(sh-Math.max(height,1350*scale))<.01);
 assert.ok(Math.abs(parseFloat(canvas.style.width)*scale-sw)<.01);
 assert.ok(Math.abs(parseFloat(canvas.style.height)*scale-sh)<.01);
 if(width>=1200&&height>=675){
  assert.ok(Math.abs(sw-width)<.01,'horizontal gap/overflow');
  assert.ok(Math.abs(sh-height)<.01,'vertical gap/overflow');
 }
 document.documentElement.clientWidth=1920;window.innerHeight=1200;events.resize();queued();
 assert.equal(canvas.style.width,'2400px');assert.equal(canvas.style.height,'1500px');
 assert.equal(stage.style.width,'1920px');assert.equal(stage.style.height,'1200px');
}
console.log('10 viewports, no spare edges, minimum size, and resize: PASS');
