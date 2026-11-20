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
function musicPlaybackToggle(snapshot,online,elapsedMs){
 const d=musicDisplay(snapshot,online,elapsedMs);
 const known=d.fresh && ['playing','paused','idle'].includes(d.state);
 return {enabled:known,icon:known&&d.state==='playing'?'Ⅱ':'▶',
   label:known?(d.state==='playing'?'일시정지':'재생'):'재생 상태 확인 중',
   operation:known?(d.state==='playing'?'music.pause':'music.start'):null};
}
if(typeof module!=='undefined')module.exports={musicDisplay,musicPlaybackToggle};
