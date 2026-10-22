const {test}=require('node:test');
const assert=require('node:assert/strict');
const {musicDisplay}=require('../../main/resources/static/music-status.js');
const snapshot={available:true,fresh:true,state:'playing',filename:'a.mp3',position_ms:10000,age_ms:1000,fresh_ms:10000};
test('advances only fresh playing samples',()=>{
 assert.equal(musicDisplay(snapshot,true,1000).positionMs,12000);
 assert.equal(musicDisplay({...snapshot,state:'paused'},true,1000).positionMs,10000);
 for(const [s,online,elapsed] of [[snapshot,false,1000],[snapshot,true,5000],[{...snapshot,age_ms:9500},true,1000],[{...snapshot,fresh:false},true,1000]]){
  const result=musicDisplay(s,online,elapsed);assert.equal(result.fresh,false);assert.equal(result.positionMs,10000);
 }
});
test('track change uses device position and unavailable does not invent progress',()=>{
 assert.equal(musicDisplay({...snapshot,filename:'b.mp3',position_ms:0,age_ms:0},true,0).positionMs,0);
 assert.equal(musicDisplay({available:false},true,0).positionMs,null);
 assert.equal(musicDisplay(null,false,0).fresh,false);
});
