'use strict';
const statusViewId=crypto.randomUUID();
async function renewStatusDemand(){if(!site)return;await api('/api/portal/status-demand','POST',{view:statusViewId,rails:document.hidden?[]:[...selected]});}
let csrf, me, site, view, selected=new Set(), dirty=new Map(), isSleepMode=false, currentCategory=0, map, markers=new Map(), activeCall, audioContext, toastTimer, polling=false, stateFetchFailed=false, lastEmergency=new Set(), modalRail, pttPressed=false;
let musicReceivedAt=0, musicPage=null, musicBusy=false, musicSelectionKey=null, musicSeekEditing=false, musicSeekKey=null;
const $=id=>document.getElementById(id);
const text=(id,value)=>{$(id).textContent=value;};
const newId=()=>crypto.randomUUID();
function toast(message){text('portalToast',message);$('portalToast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('portalToast').hidden=true,8000);}
async function api(path,method='GET',data){
 const headers={};if(method!=='GET'){headers[csrf.header]=csrf.token;if(data!==undefined)headers['Content-Type']='application/json';}
 const response=await fetch(path,{method,headers,body:data===undefined?undefined:JSON.stringify(data)});
 if(response.status===401){location.href='/login.html';throw Error('로그인이 필요합니다.');}
 if(!response.ok){let reason;try{reason=(await response.json()).message;}catch(_){}throw Error(reason||({403:'이 현장에 대한 제어 권한이 없습니다.',409:'장치 연결 또는 통화 점유 상태를 확인하세요.',503:'외부 서비스가 설정되지 않았습니다.'}[response.status]||`요청 실패 (${response.status})`));}
 return response.status===204 || response.headers.get('content-length')==='0'?null:response.text().then(t=>t?JSON.parse(t):null);
}
const statusBaselines=new Map();
function awaitStatus(ids,reason='selection'){for(const id of ids){const r=view?.rails.find(r=>r.id===id);statusBaselines.set(id,{seen:r?.seen_at??0,at:performance.now(),reason});}}
function statusCheck(r){
 if(!r)return {fresh:false,waiting:false};
 const baseline=statusBaselines.get(r.id),advanced=!baseline||(r.seen_at??0)>baseline.seen;
 return {fresh:!stateFetchFailed&&r.online&&!!r.seen_at&&advanced,
 waiting:!stateFetchFailed&&r.online&&!advanced,
 applying:!stateFetchFailed&&r.online&&!advanced&&baseline?.reason==='apply'};
}
function displayedStatus(r,check){return r&&(check.fresh||check.waiting)?r.reported||{}:{};}
let emergencyAudio;
function alarmAudio(){return emergencyAudio??=new EmergencyAudio(()=>new (window.AudioContext||window.webkitAudioContext)(),message=>text('emergencyAudioState',message));}
function enableEmergencyAudio(){return guarded(()=>alarmAudio().enable());}
function muteEmergencyAudio(){alarmAudio().mute();}
let emergencyQueue;
function renderEmergencyQueue(){
 if(typeof EmergencyQueue==='undefined')return;
 const rows=(emergencyQueue??=new EmergencyQueue()).rows(site,view?.rails||[],view?.calls||[],view?.incidents);
 text('emergencyQueueTitle',`비상 호출 ${rows.length}건${stateFetchFailed?' · 서버 연결 실패, 마지막 확인 정보':''}`);
 const root=$('emergencyQueue');root.replaceChildren();
 if(!rows.length){root.textContent=stateFetchFailed?'현재 호출 상태 확인 불가':'현재 현장에 수신된 미처리 호출 없음';return;}
 for(const row of rows){
  const line=document.createElement('div');line.style.cssText='display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 0;border-top:1px solid #555';
  const label=document.createElement('span');label.textContent=`${row.rail.name} · ${row.at?new Date(row.at).toLocaleString('ko-KR'):'발생 시각 미확인'} · ${row.status} · 담당 ${row.call?.OWNER_NAME||'미배정'}${row.rail.online?'':' · Pi 연결 끊김'}`;line.append(label);
  const button=(label,disabled,action)=>{const b=document.createElement('button');b.textContent=label;b.disabled=disabled;b.onclick=action;line.append(b);};
  const busy=emergencyAccepting||controlBusy||pttChanging||musicBusy;
  button('해당 난간 보기',busy||!!activeCall&&!selected.has(row.rail.id),()=>{if(!selected.has(row.rail.id)||selected.size!==1)choose(row.rail.id);});
  button('통화 수락',busy||stateFetchFailed||!row.active||!row.rail.online||!!row.call||view.role==='VIEWER'||view.calls.some(c=>c.OWNED),()=>{modalRail=row.rail.id;acceptEmergencyCallFromModal();});
  if(row.incidentId && row.call && ['UNKNOWN','ENDING'].includes(row.call.STATUS))button('종료 확인 재시도',busy||stateFetchFailed||!row.rail.online||view.role==='VIEWER',()=>recoverEmergencyIncident(row.incidentId,row.rail.name));
  button('이 호출 알림음 끄기',false,()=>alarmAudio().muteRail(row.rail.id));
  root.append(line);
 }
}
function recoverEmergencyIncident(id,name){return guarded(async()=>{
 if(controlBusy||emergencyAccepting||pttChanging)throw Error('현재 요청 처리가 끝난 뒤 다시 시도하세요.');
 if(!confirm(`${name}의 미확정 통화에 종료 명령을 다시 보내 실제 종료 응답을 확인할까요? 비상 상태를 강제로 해제하지는 않습니다.`))return;
 controlBusy=true;
 try{
  const rows=await api(`/api/portal/incidents/${encodeURIComponent(id)}/recover`,'POST',{request_id:newId()});
  toast('종료 확인 복구 요청 · 장치 응답 대기');
  const results=await waitControlResults(rows);await poll();
  if(results.some(r=>r.status!=='APPLIED'))throw Error('종료가 확인되지 않았습니다. 미확정 기록을 유지합니다. 통신과 장치 로그를 확인하세요.');
  toast('장치 통화 종료 확인 완료 · 현장 비상 해제 여부는 별도로 확인합니다.');
 }finally{controlBusy=false;}
});}
function showEmergencyHistory(){return guarded(async()=>{
 const requested=site,rows=await api(`/api/portal/sites/${requested}/incidents?history=true`);if(site!==requested)return;
 const body=dialog('완료된 비상 사건 · 최근 100건');
 const time=value=>value?new Date(value).toLocaleString('ko-KR'):'미확인';
 for(const item of rows){const section=document.createElement('section'),title=document.createElement('h3');
 title.textContent=`${view.rails.find(r=>r.id===item.rail_id)?.name||item.rail_id} · 사건 ${item.id}`;section.append(title);
 const info=document.createElement('p');info.textContent=`발생 ${time(item.started_at)} · 현장 해제 ${time(item.cleared_at)}`;section.append(info);
 for(const a of item.attempts){const line=document.createElement('p');line.textContent=`담당 ${a.OWNER_NAME||'미확인'} · 수락 요청 ${time(a.REQUESTED_AT)} · 연결 확인 ${time(a.CONNECTED_AT)} · 종료 확인 ${time(a.ENDED_AT)}${a.NOT_STARTED_AT?' · 실행 전 거부':''}`;section.append(line);}body.append(section);}
 if(!rows.length)body.textContent='완료된 비상 사건이 없습니다.';
});}
function rails(){return (view?.rails||[]).filter(r=>selected.has(r.id));}
function requireSelection(single=false){const items=rails();if(!items.length || (single&&items.length!==1))throw Error(single?'난간 하나를 선택하세요.':'난간을 선택하세요.');if(view.role==='VIEWER')throw Error('조회 계정은 제어할 수 없습니다.');return items;}
let controlBusy=false,pttChanging=false,emergencyAccepting=false,emergencyModalOpen=false;
async function waitControlResults(rows){
 const deadline=performance.now()+65000;
 let latest=rows;
 while(performance.now()<deadline){
  latest=await Promise.all(latest.map(r=>['QUEUED','SENT','RECEIVED'].includes(r.status)?api(`/api/portal/commands/${r.id}`):r));
  if(latest.every(r=>!['QUEUED','SENT','RECEIVED'].includes(r.status)))return latest;
  await new Promise(resolve=>setTimeout(resolve,400));
 }
 throw Error('확인 대기 시간 초과 · 적용 여부 불명. 처리 내역을 확인하세요. 자동 재전송하지 않습니다.');
}
async function send(operation,value,ids){
 if(emergencyAccepting && operation!=='call.accept')throw Error('비상통화 수락 처리 중입니다.');
 const items=requireSelection(operation.startsWith('call.')||operation.startsWith('ptt.'));
 const general=!operation.startsWith('call.')&&!operation.startsWith('ptt.')&&operation!=='emergency.ack';
 if(general&&controlBusy)throw Error('이전 제어의 장치 응답을 기다리고 있습니다.');
 if(general)controlBusy=true;
 try{
  const rows=await api('/api/portal/commands','POST',{request_id:newId(),rail_ids:ids||items.map(r=>r.id),operation,value:value??null});
  toast(`${operation}: 요청 접수 · 장치 응답 대기`);
  if(operation==='emergency.ack'){await poll();return rows;}
  const results=await waitControlResults(rows);DetectionCounts.ingest(results);awaitStatus(results.filter(r=>['APPLIED','COMPLETED'].includes(r.status)).map(r=>r.rail_id),'apply');await poll();
  const label=r=>view.rails.find(x=>x.id===r.rail_id)?.name||r.rail_id;
  const failed=results.filter(r=>!['APPLIED','COMPLETED'].includes(r.status));
  if(failed.length)throw Error(failed.map(r=>`${label(r)}: ${r.status}`).join(' / ')+' · 처리 내역 확인 필요, 자동 재전송 없음');
  toast(results.map(r=>`${label(r)}: ${r.status==='APPLIED'?'장치 적용 확인':r.detail||'응답 확인'}`).join(' / '));
  return results;
 }finally{if(general)controlBusy=false;}
}
async function guarded(action){try{await action();}catch(error){toast(error.message);}}
function choose(id){if(emergencyAccepting)return toast('비상통화 수락 처리 중입니다.');if(activeCall && !selected.has(id)){toast('통화 종료 후 난간을 변경하세요.');return;}selected=selected.has(id)?new Set():new Set([id]);dirty.clear();syncPendingSettings();awaitStatus(selected);renewStatusDemand().catch(()=>{});renderSelection();}
function selectAllDevices(){if(emergencyAccepting)return toast('비상통화 수락 처리 중입니다.');if(activeCall)return toast('통화 종료 후 선택을 변경하세요.');selected=new Set(view.rails.map(r=>r.id));dirty.clear();syncPendingSettings();awaitStatus(selected);renewStatusDemand().catch(()=>{});renderSelection();}
function renderSelection(){
 const grid=$('idBadgeGrid');grid.replaceChildren();for(const r of view.rails){const b=document.createElement('button');b.type='button';b.className=(selected.has(r.id)?'selected ':'')+(r.online?'':'offline');b.textContent=`${r.name} · ${r.gateway_id}/${r.number}`;b.title=r.online?'게이트웨이 연결됨':'게이트웨이 오프라인';b.onclick=()=>choose(r.id);grid.append(b);}
 text('selectedDeviceTag',rails().length?rails().map(r=>r.name).join(', '):'난간 선택');$('inputTotalDevices').value=view.rails.length;
 if(rails().length===1){const r=rails()[0];$('inputLat').value=r.latitude??'';$('inputLng').value=r.longitude??'';$('inputAddress').value=r.address??'';}
 renderLive();renderMap();
}
// Keep unsent edits separate from confirmed device observations.
function syncReportedControls(s){
 if(!dirty.has('volume')&&s.volume!==undefined){$('piVolume').value=s.volume;updateVolUI(s.volume,false);}
 if(!dirty.has('power'))document.querySelectorAll('input[name="pwrSupplyMode"]').forEach(i=>i.checked=i.value===({ac:'2',battery:'1'}[s.power]));
 if(!dirty.has('sleep')){
  if(typeof s.sleep==='boolean')toggleSleepStateUI(s.sleep,false);
  else { $('btnModeWakeup').className='pwr-state-btn';$('btnModeSleep').className='pwr-state-btn'; }
 }
 if(!dirty.has('led')&&!dirty.has('weather')){
  if(['basic','weather','music'].includes(s.led))switchCategoryTabUI(s.led,{basic:0,weather:1,music:2}[s.led],false);
  else document.querySelectorAll('.category-tab-btn').forEach(b=>b.classList.remove('active'));
  document.querySelectorAll('input[name="ledGroup1"]').forEach(i=>i.checked=i.value===({clear:'0',rain:'1',snow:'2'}[s.weather]));
 }
 if(!dirty.has('music.mode'))$('piPlayMode').value=({sequential:0,shuffle:1,age:2}[s.music_mode])??'';
 if(!dirty.has('detection')&&s.detection)switchDisplayView(s.detection,false);
 if(!dirty.has('projector'))document.querySelectorAll('[onclick^="toggleDeviceState(\'projector\'"]').forEach(b=>b.classList.toggle('active',typeof s.projector==='boolean'&&b.getAttribute('onclick').includes(String(s.projector))));
}
function renderProjector(s,fresh=true){
 const known=typeof s.projector==='boolean',on=known&&s.projector;
 const logo=$('projectorLogoWrapper');
 // A delayed observation is not an OFF event. Use only this rail's reported value.
 logo.classList.toggle('spinning',on);
 logo.classList.toggle('power-off',known&&!on);
 logo.classList.toggle('power-unknown',!known);
 const label=known?`${on?'ON · 릴레이 켜짐':'OFF · 릴레이 꺼짐'}${fresh?'':' · 마지막 확인값 / 최신 상태 미확인'}`:'상태 미확인';
 text('projectorStateText',label);logo.title=label;
}

function syncPendingSettings(){const bar=$('pendingSettingsBar');if(!bar)return;bar.hidden=!dirty.size;text('pendingSettingsMessage',`변경한 설정 ${dirty.size}개 · 전체 적용을 눌러 반영하세요.`);}
function mark(operation,value){dirty.set(operation,value);syncPendingSettings();toast('옵션 변경됨 · 전체 적용을 눌러 요청하세요.');}
function toggleSleepStateUI(value,edit=true){isSleepMode=value;$('btnModeWakeup').className=value?'pwr-state-btn':'pwr-state-btn active-normal';$('btnModeSleep').className=value?'pwr-state-btn active-sleep':'pwr-state-btn';if(edit)mark('sleep',value?'on':'off');}
function switchCategoryTabUI(name,code,edit=true){currentCategory=code;document.querySelectorAll('.category-tab-btn').forEach((b,i)=>b.classList.toggle('active',i===code));['Basic','Weather','Music'].forEach((n,i)=>$('tabContent'+n).style.display=i===code?'flex':'none');if(edit){if(code===1)mark('weather',['clear','rain','snow'][Number(document.querySelector('input[name="ledGroup1"]:checked')?.value||0)]);else mark('led',name);}}
function setSubModeUI(value){if(currentCategory===1)mark('weather',['clear','rain','snow'][value]);else mark(currentCategory===0?'led.basic_pattern':'led.music_pattern',String(value));}
function updateVolUI(value,edit=true){text('volDisplay',value+'%');if(edit){dirty.set('volume',String(value));syncPendingSettings();}}
function updateAudioPlayMode(value){mark('music.mode',['sequential','shuffle','age'][Number(value)]);}
function resetMusicCatalog(){musicPage=null;fillMusicTracks();renderMusicCatalog();}
function fillMusicTracks(){
 const select=$('piTrackSelect');select.replaceChildren();
 select.append(new Option(musicPage?.tracks.length?'곡을 선택하세요':'목록 미조회 또는 빈 폴더',''));
 for(const track of musicPage?.tracks||[])select.append(new Option(`${track.index+1}. ${track.filename}`,String(track.index)));
}
function renderMusicCatalog(){
 const items=rails(),r=items.length===1?items[0]:null,key=r?.id||null;
 if(key!==musicSelectionKey){musicSelectionKey=key;musicPage=null;fillMusicTracks();}
 const enabled=!!r?.online && view?.role!=='VIEWER' && !musicBusy;
 $('musicListLoad').disabled=!enabled;$('piMusicGroup').disabled=!enabled;
 $('piTrackSelect').disabled=!enabled||!musicPage;
 $('musicTrackPlay').disabled=!enabled||!musicPage||$('piTrackSelect').value==='';
 $('musicPagePrev').disabled=!enabled||!musicPage||musicPage.offset===0;
 $('musicPageNext').disabled=!enabled||!musicPage||musicPage.offset+8>=musicPage.total;
 text('musicPageInfo',musicBusy?'장치 응답 확인 중…':musicPage?`${musicPage.total}곡 · ${musicPage.total?musicPage.offset+1:0}–${Math.min(musicPage.offset+8,musicPage.total)}`:'목록 미조회');
}
async function musicRequest(r,operation,value){
 const rows=await api('/api/portal/commands','POST',{request_id:newId(),rail_ids:[r.id],operation,value});
 const id=rows[0].id,until=performance.now()+50000;
 while(performance.now()<until){
  const result=await api(`/api/portal/commands/${id}`);
  if(['COMPLETED','APPLIED'].includes(result.status))return result.result;
  if(!['QUEUED','SENT','RECEIVED'].includes(result.status))throw Error(`${r.name}: ${result.status} · 목록/장치 상태를 확인하세요. 자동 재시도하지 않습니다.`);
  await new Promise(resolve=>setTimeout(resolve,500));
 }
 throw Error('응답 대기 종료 · 처리 내역을 확인하세요. 자동 재시도하지 않습니다.');
}
async function loadMusicPage(offset=0){
 const r=requireSelection(true)[0],group=$('piMusicGroup').value;
 if(musicBusy)return;musicBusy=true;musicPage=null;fillMusicTracks();renderMusicCatalog();
 try {
  const result=await musicRequest(r,'music.list',`${group}:${offset}`);
  if(rails().length===1 && rails()[0].id===r.id && $('piMusicGroup').value===group){musicPage=result;fillMusicTracks();}
 } finally {musicBusy=false;renderMusicCatalog();}
}
async function playSelectedMusic(){
 const r=requireSelection(true)[0],index=$('piTrackSelect').value;
 if(musicBusy||!musicPage||index===''||!musicPage.tracks.some(t=>String(t.index)===index))throw Error('목록을 조회하고 곡을 선택하세요.');
 const value=`${musicPage.catalog_version}:${musicPage.group}:${index}`;
 musicBusy=true;renderMusicCatalog();
 try {const result=await musicRequest(r,'music.play',value);toast(`${r.name}: ${result.filename} · ${result.state==='paused'?'선택곡 준비 완료 · 재생 대기':'장치 재생 시작 확인'}`);await poll();}
 catch(e){musicPage=null;fillMusicTracks();throw e;}
 finally {musicBusy=false;renderMusicCatalog();}
}
function toggleDeviceState(type,value){if(type!=='projector')return toast('현재 펌웨어에서 해당 ON/OFF 명령을 지원하지 않습니다.');mark('projector',value?'on':'off');document.querySelectorAll('[onclick^="toggleDeviceState(\'projector\'"]').forEach(b=>b.classList.toggle('active',b.getAttribute('onclick').includes(String(value))));}
function switchDisplayView(mode,edit=true){$('mediaDisplayCard').classList.toggle('cctv-only',mode==='cctv');$('viewRadarContainer').style.display=mode==='radar'?'flex':'none';$('viewCctvContainer').style.display=mode==='cctv'?'flex':'none';$('btnSwitchRadar').classList.toggle('active',mode==='radar');$('btnSwitchCctv').classList.toggle('active',mode==='cctv');text('mediaDisplayTitle',mode==='radar'?'출입인원 CHECK (레이더)':'CCTV 모니터링');const r=rails()[0];const path=mode==='cctv'&&r?.stream_path?r.stream_path:'about:blank';if($('cctvMainIframe').getAttribute('src')!==path)$('cctvMainIframe').src=path;if(edit)mark('detection',mode);radarView.select(mode==='radar'&&rails().length===1?rails()[0].id:null);}
async function waitAppliedSnapshot(targets,targetSite){
 const baseline=new Map(targets.map(id=>[id,view?.rails.find(r=>r.id===id)?.seen_at??0]));
 const deadline=performance.now()+20000;
 await renewStatusDemand();
 while(performance.now()<deadline){
  if(site!==targetSite)throw Error('현장이 변경되어 상태 확인을 중단했습니다.');
  await poll();
  if(!stateFetchFailed&&targets.every(id=>{const r=view?.rails.find(r=>r.id===id);return r?.online&&(r.seen_at??0)>baseline.get(id);}))return;
  await new Promise(resolve=>setTimeout(resolve,250));
 }
 throw Error('명령 처리 후 새 상태 응답을 확인하지 못했습니다. 선택값을 유지합니다. 처리 내역을 확인하세요.');
}
async function applyAllUpdates(){await guarded(async()=>{const targets=requireSelection().map(r=>r.id),targetSite=site;if(!dirty.size)return toast('변경한 옵션이 없습니다.');const entries=[...dirty];for(const [op,value]of entries){if(site!==targetSite||JSON.stringify(rails().map(r=>r.id))!==JSON.stringify(targets))throw Error('선택이 변경되어 후속 설정을 중단했습니다. 처리 내역을 확인하세요.');await send(op,value,targets);toast('적용 후 실제 장치 상태 확인 중…');await waitAppliedSnapshot(targets,targetSite);if(dirty.get(op)===value)dirty.delete(op);syncPendingSettings();renderLive();}toast('변경 요청 처리 완료 · 정책 확인과 실제 적용의 구분은 처리 내역을 확인하세요.');});}
function sendAudioAction(action){guarded(()=>send(['music.stop','music.start','music.next'][action]));}
function resetAllConfigurations(){dirty=new Map([['power','ac'],['sleep','off'],['led','basic'],['projector','off'],['volume','20'],['music.mode','sequential'],['detection','radar']]);syncPendingSettings();toggleSleepStateUI(false,false);switchCategoryTabUI('basic',0,false);$('piVolume').value=20;updateVolUI(20,false);$('piPlayMode').value=0;toast('기본 옵션 준비됨 · 전체 적용을 눌러 요청하세요. 예약·위치·연락망은 각 저장 버튼으로 관리합니다.');}
async function saveTimeReservation(){await guarded(async()=>{for(const r of requireSelection())await api(`/api/portal/rails/${r.id}/schedule`,'PUT',{start_time:$('startTime').value,end_time:$('endTime').value,enabled:true});toast('예약 저장됨 · 한국 시간에 시작/종료 전원 명령을 요청합니다.');await poll();});}
async function updateMapLocationFromInput(){await guarded(async()=>{const latitude=Number($('inputLat').value),longitude=Number($('inputLng').value);if(!$('inputLat').value||!$('inputLng').value||!Number.isFinite(latitude)||!Number.isFinite(longitude))throw Error('위도와 경도를 입력하세요.');for(const r of requireSelection())await api(`/api/portal/rails/${r.id}/location`,'PUT',{latitude,longitude,address:$('inputAddress').value});toast('위치 저장됨');await poll();renderMap();});}
function renderMap(){
 if(!window.L){$('mapViewport').replaceChildren();const p=document.createElement('p');p.className='map-empty';p.textContent='지도 라이브러리를 불러오지 못했습니다. 설치 좌표는 아래에서 관리할 수 있습니다.';$('mapViewport').append(p);return;}
 if(!map){map=L.map('mapViewport').setView([36.5,127.8],6);L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{attribution:'© OpenStreetMap contributors',maxZoom:19}).addTo(map);}
 for(const marker of markers.values())map.removeLayer(marker);markers.clear();let coords=[];
 for(const r of view.rails){if(r.latitude==null||r.longitude==null)continue;const pos=[r.latitude,r.longitude],m=L.marker(pos,{draggable:view.role!=='VIEWER'}).addTo(map);const label=document.createElement('span');label.textContent=r.name;m.bindTooltip(label);m.on('click',()=>choose(r.id));m.on('dragend',()=>{choose(r.id);const p=m.getLatLng();$('inputLat').value=p.lat.toFixed(6);$('inputLng').value=p.lng.toFixed(6);toast('좌표 이동됨 · 좌표 변경 및 지도 저장을 누르세요.');});markers.set(r.id,m);coords.push(pos);}
 if(coords.length && !map._portalFitted){map.fitBounds(coords,{padding:[30,30],maxZoom:16});map._portalFitted=true;}map.invalidateSize();
}
function musicTime(ms){if(ms===null||ms===undefined)return '--:--';const sec=Math.floor(ms/1000);return `${Math.floor(sec/60)}:${String(sec%60).padStart(2,'0')}`;}
function showSeekTarget(){text('musicSeekTarget',musicTime(Number($('musicSeek').value)*1000));}
async function seekMusic(){
 const r=requireSelection(true)[0],d=musicDisplay(r.music_status,r.online,performance.now()-musicReceivedAt);
 if(musicBusy||!d.fresh||!d.seekable||d.state!=='playing'||!d.durationMs)throw Error('재생 중인 곡의 최신 시간 정보가 필요합니다.');
 const target=Number($('musicSeek').value)*1000;
 if(!Number.isInteger(target)||target<0||target>=d.durationMs)throw Error('곡 길이 안의 위치를 선택하세요.');
 musicBusy=true;renderMusicStatus();
 try{const result=await musicRequest(r,'music.seek',`${d.playbackId}:${target}`);toast(`${r.name}: ${musicTime(result.position_ms)} 이동 확인`);await poll();}
 finally{musicBusy=false;musicSeekEditing=false;renderMusicStatus();}
}
function renderMusicStatus(){
 renderMusicCatalog();
 const items=rails();
 if(items.length!==1){$('musicSeek').disabled=true;$('musicSeekApply').disabled=true;text('musicNowTitle','난간 하나를 선택하세요');text('musicNowState','--');text('musicNowTime','--:-- / --:--');return;}
 const r=items[0], d=musicDisplay(r.music_status,r.online,performance.now()-musicReceivedAt);
 text('musicNowTitle',d.filename);
 text('musicNowState',d.fresh?({playing:'재생 중 · 추정 경과 시간',paused:'일시정지 / 재생 대기',idle:'정지 · 마지막 곡'})[d.state]:'상태 확인 대기 · 마지막 수신값');
 text('musicNowTime',`${musicTime(d.positionMs)} / ${musicTime(d.durationMs)}`);
 const key=`${r.id}:${d.playbackId}`;
 if(key!==musicSeekKey){musicSeekKey=key;musicSeekEditing=false;}
 const enabled=d.fresh && d.seekable && d.state==='playing' && !!d.durationMs && view.role!=='VIEWER' && !musicBusy;
 $('musicSeek').disabled=!enabled;$('musicSeekApply').disabled=!enabled;
 $('musicSeek').max=Math.max(0,Math.floor(((d.durationMs||1)-1)/1000));
 if(!musicSeekEditing)$('musicSeek').value=Math.min(Number($('musicSeek').max),Math.floor((d.positionMs||0)/1000));
 if(d.durationMs)showSeekTarget();else text('musicSeekTarget','--:--');
}
function renderEnergy(s){
 const percent=Number.isFinite(s.battery_percent)&&s.battery_percent>=0&&s.battery_percent<=100?s.battery_percent:undefined;
 const voltage=Number.isFinite(s.battery_voltage)?s.battery_voltage:undefined;
 text('chargeWattsLeft',Number.isFinite(s.left_watt)?s.left_watt.toFixed(1):'--');
 text('chargeWattsRight',Number.isFinite(s.right_watt)?s.right_watt.toFixed(1):'--');
 text('batPercentTotal',percent===undefined?'미확인':(s.battery_estimated?'약 ':'')+percent.toFixed(0)+'%');
 $('barTotal').style.width=(percent??0)+'%';
 text('batteryVoltage',voltage===undefined?'미확인':voltage.toFixed(2)+' V');
 text('solarCurrentLeft',Number.isFinite(s.left_current)?s.left_current.toFixed(2):'--');
 text('solarCurrentRight',Number.isFinite(s.right_current)?s.right_current.toFixed(2):'--');
}
function renderLive(){
 if(typeof EmergencyAudio!=='undefined')alarmAudio().sync(view?.rails||[],view?.calls||[]);
 renderMusicStatus();
 const r=rails().length===1?rails()[0]:null,check=statusCheck(r),fresh=check.fresh,s=displayedStatus(r,check);
 renderEnergy(s);
 text('envWeather',({clear:'맑음',cloudy:'흐림',rain:'비',snow:'눈'})[s.weather]||'미수신');text('envWind',s.wind===undefined?'-- m/s':s.wind+' m/s');text('envPm10',s.pm10??'미수신');text('systemCommState',r?(r.online?`Pi 연결됨 · 난간 ${fresh?'응답 확인':check.waiting?(check.applying?'적용 후 상태 확인 중':'상태 확인 중'):'최신 응답 미확인'}`:'Pi 연결 끊김 · 난간 상태 미확인'):'난간 하나를 선택하세요');DetectionCounts.ingest(view?.commands);const countRail=rails().length===1?rails()[0]:null;text('radarDetectedCount',countRail?(DetectionCounts.get(countRail.id)?.count??'--'):'--');text('detectionCountSummary',countRail?'누적 감지: '+DetectionCounts.describe(countRail.id):'카운트 조회는 난간 하나를 선택하세요.');for(const id of ['detectionCountRead','detectionCountReset'])$(id).disabled=!countRail||view?.role==='VIEWER'||!countRail.online||controlBusy;
 const age=r?.seen_at?Math.max(0,Math.floor((Date.now()-r.seen_at)/1000)):null;
 const reported=r?.reported||{};
 const summary=`전원 ${reported.power??'미확인'} / ${reported.power_on===undefined?'미확인':reported.power_on?'ON':'OFF'} · LED ${reported.led??'미확인'} / ${reported.led_enabled===undefined?'미확인':reported.led_enabled?'ON':'OFF'} · 프로젝터 ${reported.projector===undefined?'미확인':reported.projector?'ON':'OFF'} · 슬립 ${reported.sleep===undefined?'미확인':reported.sleep?'사용':'해제'}${reported.sleep_active?' (잠든 상태)':''} · 감지 ${reported.detection??'미확인'} · 음악 모드 ${reported.music_mode??'미확인'} · 누적 ${reported.detection_count??'--'}`;
 text('deviceStateSummary',!r?'난간 하나를 선택하세요':
  `${fresh?'장치 응답 확인':check.waiting?`${check.applying?'적용 후 상태 확인 중':'새 응답 대기'} · 마지막 수신값`:'최신 상태 미확인 · 마지막 수신값'} · ${summary} · ${age===null?'수신 시각 없음':age+'초 전'}`);

 syncReportedControls(r?.reported||{});renderProjector(r?.reported||{},fresh);
 if(check.waiting&&typeof r?.reported?.projector==='boolean')text('projectorStateText',`${r.reported.projector?'ON · 릴레이 켜짐':'OFF · 릴레이 꺼짐'} · ${check.applying?'적용 후 상태 확인 중':'새 응답 대기'} · 마지막 수신값`);
 activeCall=view.calls.find(c=>rails().some(r=>r.id===c.RAIL_ID));const callText=activeCall?`${activeCall.STATUS} · ${activeCall.DIRECTION} · ${activeCall.OWNER_NAME}`:r?.reported?.emergency?'🚨 비상 호출':fresh?'🟢 수신대기':'상태 미수신';text('sosBigText',callText);text('sosSubDesc',activeCall?(activeCall.OWNED?'내 통화 · 적용 확인 후 송수신':'다른 운영자의 통화'):view.voice_available?'통화 시작 후 음성 연결':'통화 제어 가능 · Codec2 라이브러리 로드 실패');
 $('btnPttTalk').disabled=!activeCall?.OWNED||activeCall.STATUS!=='ACTIVE'||!view.voice_available;$('btnPttTalk').classList.toggle('active',activeCall?.DIRECTION==='CONTROL_TX');
 if(!activeCall?.OWNED || !['ACTIVE','SWITCHING','ENDING'].includes(activeCall.STATUS))closeVoice();
 else if(activeCall.STATUS!=='ACTIVE')portalVoice?.pause();
 renderEmergencyQueue();
 for(const item of view.rails){if(item.reported.emergency && (item.reported.emergency_at||item.seen_at) && !lastEmergency.has(item.id) && !emergencyModalOpen && !emergencyAccepting){emergencyModalOpen=true;lastEmergency.add(item.id);modalRail=item.id;text('modalDeviceNum',item.name+' 비상 호출');$('emergencyModal').classList.add('show');$('emergencyModal').style.display='flex';}if(item.reported.emergency===false)lastEmergency.delete(item.id);}
 radarView.select(rails().length===1 && $('viewRadarContainer').style.display!=='none' ? r.id : null);
}
async function poll(){if(polling||!site)return;polling=true;const requestedSite=site;try{const [next,incidents]=await Promise.all([api(`/api/portal/sites/${requestedSite}/state`),api(`/api/portal/sites/${requestedSite}/incidents`)]);next.incidents=incidents;if(requestedSite!==site)return;stateFetchFailed=false;view=next;musicReceivedAt=performance.now();selected=new Set([...selected].filter(id=>view.rails.some(r=>r.id===id)));if(!selected.size&&view.rails.length&&!statusBaselines.size){selected.add(view.rails[0].id);awaitStatus(selected);}renderLive();if(!document.querySelector('#idBadgeGrid button')||Number($('inputTotalDevices').value)!==view.rails.length)renderSelection();await renewStatusDemand();}catch(e){if(requestedSite!==site)return;stateFetchFailed=true;toast(e.message);musicReceivedAt=-Infinity;if(view)renderLive();text('systemCommState','서버 연결 실패');renderMusicStatus();closeVoice();}finally{polling=false;}}
async function changeSite(){if(emergencyAccepting)return toast('비상통화 수락 처리 중입니다.');if(activeCall)return toast('통화 종료 후 현장을 변경하세요.');if(emergencyAudio)emergencyAudio.sync([],[]);site=$('siteSelect').value;selected.clear();statusBaselines.clear();dirty.clear();syncPendingSettings();lastEmergency.clear();view=null;if(map)map._portalFitted=false;await poll();if(view){renderSelection();loadContacts();}}
async function logout(){await guarded(async()=>{if(view?.calls.some(c=>c.OWNED))throw Error('통화를 종료한 뒤 로그아웃하세요.');closeVoice();await api('/api/auth/logout','POST');location.href='/login.html';});}
function dialog(title){text('dialogTitle',title);$('dialogBody').replaceChildren();$('portalDialog').showModal();return $('dialogBody');}
function table(parent,headers,rows){const t=document.createElement('table');let tr=document.createElement('tr');for(const h of headers){const th=document.createElement('th');th.textContent=h;tr.append(th);}t.append(tr);for(const row of rows){tr=document.createElement('tr');for(const val of row){const td=document.createElement('td');td.textContent=val??'--';tr.append(td);}t.append(tr);}parent.append(t);}
function showResults(){const body=dialog('요청 처리 내역');for(const node of ['p4','wroom','s3']){const b=document.createElement('button');b.textContent=`${node.toUpperCase()} 응답 조회`;b.disabled=view?.role==='VIEWER';b.onclick=()=>guarded(async()=>{await send('query',node);$('portalDialog').close();showResults();});body.append(b);}const p=document.createElement('p');p.textContent='APPLIED: 장치 적용 확인 · COMPLETED: 조회 응답 또는 P4 정책 확인(재생 확인 아님) · PLC_SENT: PLC로 송신 · UNKNOWN: 적용 여부 불명 (자동 재전송하지 않음)';body.append(p);table(body,['시간','난간','요청','상태'],(view?.commands||[]).map(c=>[new Date(c.created_at).toLocaleTimeString('ko-KR'),view.rails.find(r=>r.id===c.rail_id)?.name||c.rail_id,c.operation,c.status+(c.detail?' · '+c.detail:'')+(c.operation==='query'&&c.result?.steps?' · '+c.result.steps.map(s=>`${({2:'P4',3:'WROOM',4:'S3'})[s.node]||s.node}: ${s.data}`).join(', '):'')]));if(view?.schedules.length){const title=document.createElement('h3');title.textContent='저장된 예약 (Asia/Seoul)';body.append(title);for(const schedule of view.schedules){const line=document.createElement('p');line.textContent=`${view.rails.find(r=>r.id===schedule.RAIL_ID)?.name||schedule.RAIL_ID}: ${schedule.START_TIME} ~ ${schedule.END_TIME} · ${schedule.ENABLED?'활성':'비활성'} `;const b=document.createElement('button');b.textContent='예약 해제';b.onclick=()=>guarded(async()=>{requireSelection();await api(`/api/portal/rails/${schedule.RAIL_ID}/schedule`,'PUT',{start_time:schedule.START_TIME,end_time:schedule.END_TIME,enabled:false});await poll();$('portalDialog').close();showResults();});line.append(b);body.append(line);}}}
function toggleStatsMenu(event){event.stopPropagation();$('statsMenuDropdown').classList.toggle('show');$('statsMenuDropdown').style.display=$('statsMenuDropdown').classList.contains('show')?'block':'none';}
function openStatsDetail(label){guarded(async()=>{$('statsMenuDropdown').style.display='none';const s=await api(`/api/portal/sites/${site}/statistics?period=${({일일:'daily',주간:'weekly',월간:'monthly',연간:'yearly'})[label]}`);const body=dialog(label+' 통계');const p=document.createElement('p');p.textContent=`충전량 ${s.watt_hours.toFixed(2)} Wh · 유효 난간 측정 시간 ${s.coverage_rail_seconds}초 · 비상 발생 ${s.emergency_starts}회 · 표본 ${s.samples}개. 실제 수신 데이터만 집계하며 보존 기간은 ${s.retained_days}일입니다.`;body.append(p);table(body,['측정 시간','난간','배터리 (%)'],s.points.map(p=>[new Date(p.time).toLocaleString('ko-KR'),view.rails.find(r=>r.id===p.rail)?.name||p.rail,p.battery]));});}
async function sendEmergencySms(label,input){await guarded(async()=>{const r=requireSelection(true)[0];const phone=$(input).value;if(!confirm(`${label}의 저장된 연락처로 ${r.name} 비상 확인 문자를 발송할까요?`))return;await api(`/api/portal/sites/${site}/contacts/${encodeURIComponent(label)}`,'PUT',{phone});const result=await api(`/api/portal/sites/${site}/sms`,'POST',{request_id:newId(),label,rail_id:r.id});toast(`문자 요청 ${result.status} · 수신자 도착 여부는 별도 확인이 필요합니다.`);});}
function dismissEmergencyModal(){emergencyModalOpen=false;$('emergencyModal').style.display='none';$('emergencyModal').classList.remove('show');}
function acceptEmergencyCallFromModal(){return guarded(async()=>{
 if(emergencyAccepting||controlBusy||pttChanging||musicBusy)throw Error('이전 작업이 끝난 뒤 비상통화를 수락하세요.');
 if(view?.calls?.some(c=>c.OWNED))throw Error('진행 중인 내 통화를 종료한 뒤 수락하세요.');
 const target=modalRail,targetSite=site;
 const check=()=>{const r=view?.rails.find(r=>r.id===target);if(site!==targetSite||!r||!r.reported?.emergency)throw Error('해당 비상 호출이 해제되었거나 현재 현장에서 확인되지 않습니다.');if(view.role==='VIEWER')throw Error('조회 계정은 통화를 수락할 수 없습니다.');};
 check();emergencyAccepting=true;
 try{
  await ensureAudio();await voiceClient().prepare();check();
  selected=new Set([target]);dirty.clear();syncPendingSettings();awaitStatus(selected);renewStatusDemand().catch(()=>{});renderSelection();
  await send('call.accept',undefined,[target]);await openVoice();
  if(modalRail===target)dismissEmergencyModal();
 }finally{emergencyAccepting=false;}
});}
function triggerMp3Alarm(){if(!audioContext)audioContext=new AudioContext();audioContext.resume();const o=audioContext.createOscillator(),g=audioContext.createGain();o.frequency.value=660;g.gain.value=.05;o.connect(g).connect(audioContext.destination);o.start();o.stop(audioContext.currentTime+.3);}
function drawRadar(targets){
 const c=$('ld2450RadarCanvas'),ctx=c.getContext('2d'),dpr=window.devicePixelRatio||1,w=c.clientWidth||400,h=c.clientHeight||250;
 c.width=w*dpr;c.height=h*dpr;ctx.scale(dpr,dpr);ctx.clearRect(0,0,w,h);
 const ox=w/2,oy=12,scale=Math.min((w-30)/12,(h-30)/6);
 ctx.strokeStyle='#284558';ctx.fillStyle='#73929e';ctx.font='11px system-ui';
 for(let i=1;i<=6;i++){ctx.beginPath();ctx.arc(ox,oy,scale*i,0,Math.PI);ctx.stroke();ctx.fillText(i+'m',ox+5,oy+scale*i);}
 for(const t of targets){if(!Number.isFinite(t.x)||!Number.isFinite(t.y))continue;ctx.fillStyle='#00f2fe';ctx.beginPath();ctx.arc(ox+t.x*scale,oy+t.y*scale,6,0,Math.PI*2);ctx.fill();}
}
const radarView=new RadarView(drawRadar,message=>text('radarLiveStatus',message));

async function ensureAudio(){if(!audioContext)audioContext=new AudioContext();await audioContext.resume();}
let portalVoice;
function voiceClient(){return portalVoice??=new WebVoice(toast);}
async function openVoice(force=false){if(pttChanging&&!force)return;await voiceClient().sync(activeCall,view?.voice_available);}
function stopPlayback(){portalVoice?.silence();}
function closeVoice(){portalVoice?.close();}
async function microphone(){await voiceClient().mic();}
function sendVoiceCallControl(start){guarded(async()=>{if(start){await ensureAudio();await voiceClient().prepare();await send('call.start');await openVoice();}else{pttPressed=false;closeVoice();await send('call.end');}});}
function startPttTalk(event){
 event?.preventDefault();if($('btnPttTalk').disabled||pttPressed||pttChanging)return;
 event?.currentTarget?.setPointerCapture(event.pointerId);pttPressed=true;pttChanging=true;voiceClient().pause();
 guarded(async()=>{try{await microphone();if(pttPressed){await send('ptt.on');if(!pttPressed)await send('ptt.off');}}
 catch(e){pttPressed=false;throw e;}finally{pttChanging=false;await openVoice();}});
}
function stopPttTalk(){
 if(!pttPressed)return;pttPressed=false;voiceClient().pause();if(pttChanging)return;
 pttChanging=true;guarded(async()=>{try{await send('ptt.off');}finally{pttChanging=false;await openVoice();}});
}
window.addEventListener('blur',stopPttTalk);document.addEventListener('visibilitychange',()=>{if(document.hidden)stopPttTalk();renewStatusDemand().catch(()=>{});});
function updateTotalDevicesCount(){if(me?.user.ADMIN)openAdmin('rail');else toast('등록된 난간만 표시합니다. 난간 추가는 관리자에게 요청하세요.');}
const adminForms={
 user:{name:'사용자 등록',path:'users',method:'POST',fields:[['username','계정'],['name','표시 이름'],['password','비밀번호 (12자 이상)','password']]},
 site:{name:'현장 등록',path:'sites',method:'POST',fields:[['id','현장 ID'],['name','현장 이름']]},
 gateway:{name:'난간 Pi 등록',path:'gateways',method:'POST',fields:[['id','Pi ID'],['site_id','현장 ID'],['name','Pi 이름'],['token','장치 전용 토큰 (32자 이상)','password']]},
 rail:{name:'난간 등록',path:'rails',method:'POST',fields:[['gateway_id','Pi ID'],['number','Pi 내부 난간 번호 (1..255)','number'],['name','난간 이름']]},
 camera:{name:'카메라 등록',path:'cameras',method:'POST',fields:[['id','카메라 ID'],['rail_id','등록 난간 ID'],['stream_path','영상 경로 (/cctv/이름/)']]},
 membership:{name:'현장 권한 부여',path:'memberships',method:'PUT',fields:[['user_id','사용자 ID'],['site_id','현장 ID'],['role','역할','role']]}
};
function openAdmin(initial='user'){guarded(async()=>{if(!me.user.ADMIN)throw Error('관리자 전용입니다.');const body=dialog('사용자 · 현장 · 장치 관리'),select=document.createElement('select');for(const [key,v]of Object.entries(adminForms)){const o=document.createElement('option');o.value=key;o.textContent=v.name;select.append(o);}select.value=initial;body.append(select);const form=document.createElement('form');body.append(form);const info=document.createElement('div');body.append(info);
 const build=()=>{form.replaceChildren();const conf=adminForms[select.value];for(const [key,label,type]of conf.fields){const l=document.createElement('label');l.textContent=label;let input;if(type==='role'){input=document.createElement('select');for(const role of ['VIEWER','OPERATOR','NONE']){const o=document.createElement('option');o.value=role;o.textContent=role==='VIEWER'?'조회자':role==='OPERATOR'?'운영자':'권한 해제';input.append(o);}}else{input=document.createElement('input');input.type=type||'text';input.maxLength=type==='password'?128:200;if(type==='number'){input.min=1;input.max=255;}}input.name=key;input.required=key!=='stream_path';input.autocomplete=type==='password'?'new-password':'off';l.append(input);form.append(l);}const button=document.createElement('button');button.textContent='저장';form.append(button);};select.onchange=build;build();
 form.onsubmit=e=>{e.preventDefault();guarded(async()=>{const conf=adminForms[select.value],value=Object.fromEntries(new FormData(form));if(value.number)value.number=Number(value.number);const result=await api('/api/portal/admin/'+conf.path,conf.method,value);toast('저장 완료'+(result?.id?' · 사용자 ID '+result.id:''));form.reset();me=await api('/api/portal/me');fillSites();await poll();await infoLoad();});};
 const infoLoad=async()=>{info.replaceChildren();const users=await api('/api/portal/admin/users'),gateways=await api('/api/portal/admin/gateways');const heading=document.createElement('h3');heading.textContent='등록 정보';info.append(heading);table(info,['사용자','ID'],users.map(u=>[u.NAME+' ('+u.USERNAME+')',u.ID]));table(info,['현장','ID'],me.sites.map(s=>[s.NAME,s.ID]));table(info,['Pi','현장 ID'],gateways.map(g=>[g.ID,g.SITE_ID]));table(info,['현재 현장 난간','ID'],(view?.rails||[]).map(r=>[r.name,r.id]));};await infoLoad();});}
function loadContacts(){for(const [label,id]of [['주민센터','telGov'],['소방서','telFire'],['경찰서','telPolice']])$(id).value=view.contacts.find(c=>c.LABEL===label)?.PHONE||'';}
function fillSites(){$('siteSelect').replaceChildren();for(const s of me.sites){const o=document.createElement('option');o.value=s.ID;o.textContent=s.NAME+' · '+s.ROLE;$('siteSelect').append(o);}if(me.sites.some(s=>s.ID===site))$('siteSelect').value=site;else site=$('siteSelect').value;}
async function init(){try{csrf=await fetch('/api/auth/csrf').then(r=>r.json());me=await api('/api/portal/me');text('userName',me.user.NAME);$('adminButton').hidden=!me.user.ADMIN;fillSites();$('siteSelect').onchange=()=>guarded(changeSite);document.querySelectorAll('input[name="pwrSupplyMode"]').forEach(i=>i.addEventListener('change',()=>mark('power',i.value==='1'?'battery':'ac')));fillMusicTracks();const clock=()=>text('realtimeClock',new Date().toLocaleString('ko-KR',{timeZone:'Asia/Seoul'}));clock();setInterval(clock,1000);setInterval(renderMusicStatus,1000);await poll();if(view){renderSelection();for(const [label,id]of [['주민센터','telGov'],['소방서','telFire'],['경찰서','telPolice']])$(id).value=view.contacts.find(c=>c.LABEL===label)?.PHONE||'';}else toast('할당된 현장이 없습니다. 관리자에게 현장 권한을 요청하세요.');setInterval(async()=>{await poll();if(activeCall?.OWNED&&activeCall.STATUS==='ACTIVE'&&audioContext&&!pttChanging)await guarded(openVoice);},2000);}catch(e){toast(e.message);}}
init();

function detectionCountAction(reset){guarded(async()=>{const r=requireSelection(true)[0];if(reset&&!confirm(r.name+'의 누적 감지 횟수만 0으로 초기화할까요? 연령대 통계는 유지됩니다.'))return;await send(reset?'detection.reset':'detection.count',null,[r.id]);});}
