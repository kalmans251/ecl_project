/* Current device position, with bounded display-only interpolation. */
'use strict';
function musicDisplay(snapshot, online, elapsedMs) {
 const s=snapshot||{}, elapsed=Math.max(0,elapsedMs), age=(s.age_ms||0)+elapsed;
 const fresh=!!(online && s.available && s.fresh && elapsed<5000 && age<s.fresh_ms);
 const duration=Number.isFinite(s.duration_ms)&&s.duration_ms>0?s.duration_ms:null;
 const advance=fresh && s.state==='playing'?age:0;
 return {fresh, filename:s.filename||'곡 정보 없음', state:s.state||'unknown',
   durationMs:duration,playbackId:s.playback_id,seekable:!!s.seekable,
   positionMs:s.available?Math.min(duration??Infinity,Math.max(0,(s.position_ms||0)+advance)):null};
}
if(typeof module!=='undefined')module.exports={musicDisplay};
