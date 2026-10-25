const {test}=require('node:test'),assert=require('node:assert/strict');
const {fit,label}=require('../src/main/resources/static/camera-overlay.js');
test('contain geometry preserves letterbox offsets',()=>{
 const rect=fit(1000,1000,1920,1080);for(const [k,v] of Object.entries({x:0,y:218.75,w:1000,h:562.5}))assert.ok(Math.abs(rect[k]-v)<1e-9);
 assert.deepEqual(fit(1000,500,500,1000),{x:375,y:0,w:250,h:500});
});
test('estimated and unresolved ages are distinct per track',()=>{
 assert.equal(label({id:'2',state:'estimated',age:28.4}),'#2 추정 28세');
 assert.equal(label({id:'3',state:'pending',age:null}),'#3 나이 분석 중');
 assert.equal(label({id:'3',state:'unknown',age:null}),'#3 나이 미확정');
});

test('stale metadata and paused video never leave boxes on screen',async()=>{
 const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
 let clock=0,draws=0,nextFrame;const timers=[];
 const ctx={clearRect(){draws=0;},strokeRect(){draws++;},measureText(){return {width:40};},fillRect(){},fillText(){}};
 const context={performance:{now:()=>clock},document:{hidden:false},AbortController,
  requestAnimationFrame:f=>nextFrame=f,setTimeout:f=>{timers.push(f);return timers.length;},clearTimeout(){},
  fetch:async()=>({ok:true,json:async()=>({fresh:true,age_ms:0,people:[{id:'1',box:[.1,.1,.5,.8],age:28,state:'estimated'}]})})};
 vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../src/main/resources/static/camera-overlay.js'),'utf8'),context);
 const video={clientWidth:640,clientHeight:360,videoWidth:640,videoHeight:360,currentTime:1,paused:false,readyState:4};
 const canvas={width:640,height:360,getContext:()=>ctx},status={};
 const viewer=context.CameraOverlay.attach('cctv01',video,canvas,status,{checked:true});
 await new Promise(resolve=>setImmediate(resolve));nextFrame();assert.equal(draws,1);
 video.paused=true;nextFrame();assert.equal(draws,0);
 video.paused=false;video.currentTime=2;clock=1100;nextFrame();assert.equal(draws,0);
 viewer.stop();assert.equal(draws,0);
});
