(async()=>{
 const el=id=>document.getElementById(id),csrf=await (await fetch('/api/auth/csrf')).json();
 const camera=()=>{const s=el('camera').value;if(!/^[A-Za-z0-9_-]{1,80}$/.test(s))throw Error('카메라 ID 확인');return s;};
 const tokens=()=>({control_token:el('control').value,publish_token:el('publish').value,analysis_token:el('analysis').value});
 async function request(path,method='GET',data){const r=await fetch(path,{method,headers:{'Content-Type':'application/json',[csrf.header]:csrf.token},body:data===undefined?undefined:JSON.stringify(data)});if(!r.ok)throw Error('요청 실패 '+r.status);const text=await r.text();el('status').textContent=text?JSON.stringify(JSON.parse(text),null,2):'적용됨';}
 const action=(id,f)=>el(id).onclick=async()=>{try{await f();}catch(e){el('status').textContent=e.message;}};
 action('generate',()=>{for(const id of ['control','publish','analysis'])el(id).value=btoa(String.fromCharCode(...crypto.getRandomValues(new Uint8Array(32)))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');el('status').textContent='새 토큰 생성 완료. 등록 후 설정용 토큰을 복사하세요.';});
 action('provision',()=>request('/api/portal/admin/cctv/'+camera(),'PUT',tokens()));
 action('copy',()=>navigator.clipboard.writeText(JSON.stringify(tokens(),null,2)));
 action('enable',()=>request('/api/portal/cctv/'+camera()+'/enabled','PUT',{enabled:true}));
 action('disable',()=>request('/api/portal/cctv/'+camera()+'/enabled','PUT',{enabled:false}));
 const labels={SENT:'Pi 응답 대기',RECEIVED:'Pi 수신',PLC_SENT:'난간 전달 처리 완료',FAILED:'처리 실패 · 적용 여부 미확인',UNKNOWN:'결과 불명확',BUSY:'장치 사용 중',EXPIRED:'유효시간 만료',NOT_RECEIVED:'연령 결과 미수신'};
 const clear=()=>{for(const id of ['age-group','age-time','enter-delivery','age-delivery'])el(id).textContent='—';};
 let reading=false;
 async function refreshAge(){
  if(reading)return;reading=true;
  try{
   const selected=camera(),r=await fetch('/api/portal/cctv/'+selected,{cache:'no-store',signal:AbortSignal.timeout(5000)});
   if(!r.ok)throw Error('상태 조회 실패 '+r.status);
   const state=await r.json();if(camera()!==selected)return;
   el('status').textContent=JSON.stringify(state,null,2);
   const age=state.analysis_state?.age;
   el('age-health').textContent=!state.analysis?'CCTV 분석 비활성':!state.analysis_fresh?'분석 상태 오래됨 · 최근 기록만 표시':age==='ready'?'연령 모델 준비 완료':age==='disabled'?'연령 분석 꺼짐':'연령 모델 사용 불가 / 준비 중';
   const d=state.latest_detection;clear();if(!d?.observed_at)return;
   el('age-group').textContent=({'10':'10대','20':'20대','30':'30대','40':'40대',keep:'기존 선택 유지 (연령 미확정)',pending:'연령 결과 미수신'})[d.age_group]||'알 수 없음';
   el('age-time').textContent=new Date(d.observed_at).toLocaleString()+' / #'+d.event_seq;
   el('enter-delivery').textContent=labels[d.enter_status]||'알 수 없음';
   el('age-delivery').textContent=labels[d.age_status]||'알 수 없음';
  }catch(e){clear();el('age-health').textContent=e.message;}finally{reading=false;}
 }
 action('refresh',refreshAge);
 el('camera').addEventListener('input',()=>{clear();el('age-health').textContent='카메라 변경 · 조회 대기';});
 await refreshAge();
 setInterval(()=>{if(!document.hidden)refreshAge();},2000);
 action('watch',()=>{el('view').src='/camera-view.html?camera='+encodeURIComponent(camera());});
 action('stop',()=>{el('view').src='about:blank';});
})();
