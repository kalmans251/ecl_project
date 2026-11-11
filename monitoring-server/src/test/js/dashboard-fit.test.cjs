const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/dashboard-fit.js'),'utf8');
for(const [width,height,expected] of [[2400,1350,1],[1920,1080,.8],[1536,864,.64],[3840,2160,1.6],[1280,1024,1280/2400],[800,600,.5]]){
 const stage={style:{}},canvas={style:{}},events={};
 const document={documentElement:{clientWidth:width},getElementById:id=>id==='dashboardStage'?stage:canvas};
 const window={innerHeight:height,addEventListener:(name,fn)=>events[name]=fn};
 let queued;
 vm.runInNewContext(source,{document,window,requestAnimationFrame:fn=>{queued=fn;return 1;}});
 assert.ok(Math.abs(parseFloat(stage.style.width)-2400*expected)<.01);
 assert.ok(Math.abs(parseFloat(stage.style.height)-1350*expected)<.01);
 assert.equal(canvas.style.transform,'scale('+expected+')');
 document.documentElement.clientWidth=1920;window.innerHeight=1080;events.resize();queued();
 assert.equal(canvas.style.transform,'scale(0.8)');
}
console.log('6 viewport sizes and resize: PASS');
