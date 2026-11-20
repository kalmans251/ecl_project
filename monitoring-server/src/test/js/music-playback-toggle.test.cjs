const assert=require('node:assert/strict');
const {musicPlaybackToggle:toggle}=require('../../main/resources/static/music-status.js');
const snapshot={available:true,fresh:true,age_ms:0,fresh_ms:10000};
for(const [state,icon,operation]of [['playing','Ⅱ','music.pause'],['paused','▶','music.start'],['idle','▶','music.start']]){
 const model=toggle({...snapshot,state},true,0);
 assert.equal(model.icon,icon);assert.equal(model.operation,operation);assert.equal(model.enabled,true);
}
for(const [s,online,elapsed]of [[{...snapshot,state:'playing'},false,0],[{...snapshot,state:'playing'},true,5000],[{...snapshot,state:'unknown'},true,0],[null,true,0],[{...snapshot,state:'playing',available:false},true,0]]){
 assert.equal(toggle(s,online,elapsed).operation,null);
}
console.log('Playback toggle states: PASS');
