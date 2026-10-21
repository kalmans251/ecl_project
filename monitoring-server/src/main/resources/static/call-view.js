/* Pure call presentation policy, shared by portal and Node regression tests. */
function callView(call, rail, calls, role) {
 const online=!!rail?.online, operator=role!=='VIEWER';
 const owned=!!call?.OWNED;
 const ready=online && owned && call.STATUS==='ACTIVE';
 const occupied=!!rail && calls.some(c=>c.GATEWAY_ID===rail.gateway_id);
 const labels={PENDING:'연결 준비 중',SWITCHING:'통화 방향 전환 중',ENDING:'종료 확인 중',UNKNOWN:'통화 상태 확인 실패'};
 const errors={GATEWAY_OFFLINE:'Pi 연결 또는 상태 수신 끊김',WROOM_TIMEOUT:'WROOM 응답 시간 초과',S3_TIMEOUT:'S3 응답 시간 초과',WROOM_FAILED:'WROOM 음성 출력 상태 이상',S3_FAILED:'S3 마이크 상태 이상'};
 return {label:call?(labels[call.STATUS]||(call.DIRECTION==='CONTROL_TX'?'말하는 중':'듣는 중')):'통화 없음',
   detail:call?(errors[call.DETAIL]||(call.STATUS==='UNKNOWN'?'음성 중단 · 종료 재시도로 상태를 정리하세요.':owned?'내 통화':'다른 운영자의 통화')):'',
   start:operator && online && !occupied,
   end:operator && online && owned && !['PENDING','SWITCHING','ENDING'].includes(call.STATUS),
   ptt:operator && ready,
   retry:call?.STATUS==='UNKNOWN'};
}
if(typeof module!=='undefined')module.exports={callView};
