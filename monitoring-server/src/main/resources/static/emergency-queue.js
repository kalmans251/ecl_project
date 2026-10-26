class EmergencyQueue {
 constructor(){this.known=new Map();this.site=null;}
 rows(site,rails,calls,incidents){
  if(Array.isArray(incidents))return incidents.map(e=>{
   const rail=rails.find(r=>r.id===e.rail_id);if(!rail)return null;
   const attempt=[...(e.attempts||[])].reverse().find(a=>!a.ENDED_AT&&!a.NOT_STARTED_AT);
   const call=attempt?(calls.find(c=>c.ID===attempt.CALL_ID)||{STATUS:attempt.CALL_STATUS||'UNKNOWN',OWNER_NAME:attempt.OWNER_NAME}):null;
   return {incidentId:e.id,rail,call,at:e.started_at,active:e.cleared_at==null,status:call?({ACTIVE:'통화 중',PENDING:'연결 중',SWITCHING:'음성 방향 전환 중',ENDING:'종료 확인 중'}[call.STATUS]||'상태 미확정 · 종료 확인 필요'):'수락 대기'};
  }).filter(Boolean);

  if(this.site!==site){this.known.clear();this.site=site;}
  const result=[];
  for(const rail of rails){
   const call=calls.find(c=>c.RAIL_ID===rail.id),active=rail.reported?.emergency===true;
   if(active)this.known.set(rail.id,rail.reported.emergency_at??rail.seen_at??null);
   if(!active&&!call)this.known.delete(rail.id);
   if(!active&&!this.known.has(rail.id))continue;
   result.push({rail,call,at:this.known.get(rail.id),active,
    status:call?({ACTIVE:'통화 중',STARTING:'연결 중',SWITCHING:'음성 방향 전환 중',ENDING:'종료 확인 중',UNKNOWN:'상태 미확정 · 종료 확인 필요'}[call.STATUS]||'통화 처리 중'):'수락 대기'});
  }
  const ids=new Set(rails.map(r=>r.id));for(const id of this.known.keys())if(!ids.has(id))this.known.delete(id);
  return result.sort((a,b)=>(a.at??Infinity)-(b.at??Infinity)||a.rail.id.localeCompare(b.rail.id));
 }
}
if(typeof module!=='undefined')module.exports={EmergencyQueue};
