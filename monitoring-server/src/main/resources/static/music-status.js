/* Current device position, with bounded display-only interpolation. */
'use strict';
function musicDisplay(snapshot, online, elapsedMs) {
 const s=snapshot||{}, elapsed=Math.max(0,elapsedMs), age=(s.age_ms||0)+elapsed;
 const fresh=!!(online && s.available && s.fresh && elapsed<5000 && age<s.fresh_ms);
 const advance=fresh && s.state==='playing'?age:0;
 return {fresh, filename:s.filename||'곡 정보 없음', state:s.state||'unknown',
   positionMs:s.available?Math.max(0,(s.position_ms||0)+advance):null};
}
if(typeof module!=='undefined')module.exports={musicDisplay};
