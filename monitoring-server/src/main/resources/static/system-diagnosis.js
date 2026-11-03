'use strict';
let systemDiagnosisRunning=false,systemDiagnosisStop=false;
async function diagnosisRequest(path,method='GET',data){
 const headers={};if(method!=='GET'){headers[csrf.header]=csrf.token;headers['Content-Type']='application/json';}
 const response=await fetch(path,{method,headers,body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(10000)});
 if(!response.ok){let reason;try{reason=(await response.json()).message;}catch(_){}throw Error(reason||'서버 요청 실패 ('+response.status+')');}
 return response.json();
}
// Minimum presentation time only; device latency is measured before this wait.
async function diagnosisLoading(started,minimumMs){
 let remaining=Math.max(0,minimumMs-(performance.now()-started));
 while(remaining>0&&!systemDiagnosisStop){
  const slice=Math.min(100,remaining);
  await new Promise(resolve=>setTimeout(resolve,slice));remaining-=slice;
 }
 return !systemDiagnosisStop;
}
function diagnosisRow(label){
 const row=document.createElement('li'),title=document.createElement('strong'),detail=document.createElement('span');
 title.textContent=label;detail.textContent='대기';row.dataset.state='waiting';row.append(title,detail);$('systemDiagnosisResults').append(row);
 return (state,message)=>{row.dataset.state=state;detail.textContent=message;};
}
function stopSystemDiagnosis(){systemDiagnosisStop=true;$('systemDiagnosisStop').disabled=true;text('systemDiagnosisSummary','중단 요청됨 · 진행 중인 조회 결과는 처리 내역에서 확인할 수 있습니다.');}
async function startSystemDiagnosis(){
 if(systemDiagnosisRunning)return;
 try{
  const targets=requireSelection().map(r=>({...r})),targetSite=site;
  if(settingsApplying||controlBusy||pttChanging||emergencyAccepting||musicBusy)throw Error('진행 중인 제어가 끝난 뒤 진단하세요.');
  systemDiagnosisRunning=true;systemDiagnosisStop=false;controlBusy=true;
  const dialog=$('systemDiagnosisDialog');$('systemDiagnosisResults').replaceChildren();
  text('systemDiagnosisTarget',targets.map(r=>r.name).join(' / '));
  text('systemDiagnosisSummary','서버 연결과 장치 응답을 순서대로 확인합니다.');
  $('systemDiagnosisClose').disabled=true;$('systemDiagnosisStop').disabled=false;dialog.showModal();
  let passed=0,failed=0,skipped=0;
  const server=diagnosisRow('모니터링 서버 연결');server('running','최신 상태 조회 중…');
  let snapshot;const serverStarted=performance.now();
  try{snapshot=await diagnosisRequest('/api/portal/sites/'+encodeURIComponent(targetSite)+'/state');
   if(!await diagnosisLoading(serverStarted,800)){server('skip','진단 중단');return;}
   server('pass','서버 응답 수신');passed++;}
  catch(e){server('fail',e.message);throw Error('서버 상태를 조회하지 못해 장치 진단을 중단했습니다. 로그인·서버·네트워크를 확인하세요.');}
  for(const target of targets){
   if(systemDiagnosisStop)break;
   const gateway=diagnosisRow(target.name+' · Pi'),gatewayStarted=performance.now();
   gateway('running','게이트웨이 연결 상태 확인 중…');
   if(!await diagnosisLoading(gatewayStarted,1000)){gateway('skip','진단 중단');break;}
   const rail=snapshot.rails.find(r=>r.id===target.id);
   if(!rail?.online){gateway('fail','Pi 오프라인 또는 접근 대상 없음 · Pi 실행/인터넷/게이트웨이 연결을 확인하세요.');failed++;skipped+=3;continue;}
   gateway('pass','서버와 Pi 연결 확인');passed++;
   if(snapshot.calls.some(c=>c.GATEWAY_ID===target.gateway_id||snapshot.rails.some(r=>r.id===c.RAIL_ID&&r.gateway_id===target.gateway_id))||rail.reported?.emergency){gateway('skip','통화 또는 비상 처리 중 · 장치 조회 생략');skipped+=3;continue;}
   for(const [node,label]of [['p4','P4 · PLC 응답'],['wroom','WROOM · 중계 응답'],['s3','S3 · 중계 응답']]){
    if(systemDiagnosisStop)break;
    const report=diagnosisRow(target.name+' · '+label),started=performance.now();report('running','조회 요청 · 응답 대기…');
    let submitted=false;
    try{
     let rows=await diagnosisRequest('/api/portal/commands','POST',{request_id:crypto.randomUUID(),rail_ids:[target.id],operation:'query',value:node});
     submitted=true;
     if(rows.length!==1||rows[0].rail_id!==target.id)throw Error('진단 응답 대상 불일치');
     let result=rows[0];const deadline=performance.now()+65000;
     while(['QUEUED','SENT','RECEIVED'].includes(result.status)){
      if(systemDiagnosisStop)throw Error('중단됨 · 이미 요청한 조회는 서버에서 완료될 수 있습니다.');
      if(performance.now()>=deadline)throw Error('응답 대기 시간 초과 · 처리 내역을 확인하세요.');
      await new Promise(resolve=>setTimeout(resolve,400));
      result=await diagnosisRequest('/api/portal/commands/'+encodeURIComponent(result.id));
     }
     const responseMs=Math.round(performance.now()-started);
     const step=result.result?.steps?.[0],expected={p4:2,wroom:3,s3:4}[node];
     if(!['COMPLETED','APPLIED'].includes(result.status)||step?.node!==expected||step?.status!==0){
      report('fail',(result.detail||result.status)+' · '+(node==='p4'?'Pi↔PLC↔P4 구간을 확인하세요.':'P4 조회 결과와 함께 '+node.toUpperCase()+' 전원·중계 링크를 확인하세요.'));failed++;continue;
     }
     report('running','응답 수신 · 결과 확인 중…');
     if(!await diagnosisLoading(started,1500)){report('skip','응답 수신 후 진단 중단');break;}
     report('pass',responseMs+' ms · 장치 응답 확인 · 데이터 '+step.data);passed++;
    }catch(e){
     report('fail',e.message);failed++;
     // A lost HTTP response can leave a command pending; do not queue another test.
     if(submitted||e.name==='TimeoutError'||e.name==='TypeError'){systemDiagnosisStop=true;break;}
    }
   }
  }
  text('systemDiagnosisSummary',`${systemDiagnosisStop?'진단 중단':'진단 완료'} · 정상 ${passed} / 실패 ${failed} / 생략 ${skipped}. 응답 실패만으로 전원·배선·CRC 중 원인을 확정할 수 없습니다.`);
 }catch(e){
  if(systemDiagnosisRunning)text('systemDiagnosisSummary',e.message);else toast(e.message);
 }finally{
  if(systemDiagnosisRunning){systemDiagnosisRunning=false;controlBusy=false;$('systemDiagnosisClose').disabled=false;$('systemDiagnosisStop').disabled=true;}
 }
}
