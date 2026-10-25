/* Last P4-confirmed snapshot, never a browser-inferred people total. */
(function(root){
 const values=new Map();
 function decode(command){
  const reset=command.operation==='detection.reset';
  if(!reset&&command.operation!=='detection.count')return null;
  if(command.status!==(reset?'APPLIED':'COMPLETED'))return null;
  const result=command.result,s=result?.steps?.[0];
  if(result?.operation!==command.operation||result.device_application_confirmed!==reset||result.steps.length!==1||s?.node!==2||s.service!==9||s.command!==(reset?54:16)||s.status!==0||!/^01(?:00|01)[0-9a-f]{8}$/.test(s.data))return null;
  const count=parseInt(s.data.slice(4),16);
  if(reset&&count!==0)return null;
  return {count,source:s.data.slice(2,4)==='00'?'레이더':'CCTV',at:command.created_at};
 }
 function ingest(commands){for(const command of commands||[]){const value=decode(command);if(value&&(!values.has(command.rail_id)||values.get(command.rail_id).at<=value.at))values.set(command.rail_id,value);}}
 function get(id){return values.get(id);}
 function describe(id){const d=get(id);return d?`${d.count}회 · ${d.source} · 마지막 확인 요청 ${new Date(d.at).toLocaleString()}`:'미조회 · 카운트 조회를 누르세요';}
 root.DetectionCounts={decode,ingest,get,describe};
 if(typeof module!=='undefined')module.exports=root.DetectionCounts;
})(globalThis);
