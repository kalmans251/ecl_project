'use strict';
let webVoice;
const $=id=>document.getElementById(id), pending=new Set(['QUEUED','SENT','RECEIVED']);
let csrf, me, view=null, site='', selected=new Set(), busy=false, loading=false, epoch=0, page=null, received=-Infinity;
const sections=[
 ['장치 조회','query',[['p4','P4 조회'],['wroom','WROOM 조회'],['s3','S3 조회']]],
 ['전원','power',[['ac','AC 선택 + 켜기'],['battery','배터리 선택 + 켜기'],['on','켜기'],['off','끄기']]],
 ['프로젝터','projector',[['on','켜기'],['off','끄기']]],
 ['LED','led',[['on','켜기'],['off','끄기'],['basic','기본 모드'],['music','음악 모드']]],
 ['날씨 LED','weather',[['clear','맑음'],['cloudy','흐림'],['rain','비'],['snow','눈']]],
 ['기본 LED 패턴','led.basic_pattern',Array.from({length:6},(_,i)=>[String(i),`패턴 ${i+1}`])],
 ['음악 LED 패턴','led.music_pattern',Array.from({length:3},(_,i)=>[String(i),`패턴 ${i+1}`])],
 ['음악 제어',null,[['music.start','시작'],['music.stop','정지'],['music.pause','일시정지'],['music.resume','재개'],['music.next','다음 곡']]],
 ['음악 모드','music.mode',[['sequential','순차'],['shuffle','셔플'],['age','연령별']]],
 ['슬립','sleep',[['on','사용'],['off','해제']]],
 ['감지 모드','detection',[['radar','레이더'],['cctv','CCTV']]]
];
function notice(s){$('notice').textContent=s;}
function items(){return (view?.rails||[]).filter(r=>selected.has(r.id));}
function writable(){return !!view && view.role!=='VIEWER' && items().length>0 && items().every(r=>r.online) && !busy;}
function one(){const rows=items();if(rows.length!==1)throw Error('난간 하나만 선택하세요.');return rows[0];}
async function api(path,method='GET',data){
 const headers={};if(method!=='GET'){headers[csrf.header]=csrf.token;headers['Content-Type']='application/json';}
 const r=await fetch(path,{method,headers,body:data===undefined?undefined:JSON.stringify(data),signal:AbortSignal.timeout(10000)});
 if(r.status===401){location.href='/login.html?next=function-test';throw Error('로그인이 필요합니다.');}
 if(!r.ok){let msg;try{msg=(await r.json()).message;}catch(_){}throw Error(msg||`요청 실패 (${r.status})`);}
 return r.status===204?null:r.json();
}
async function guarded(fn){try{await fn();}catch(e){notice(e.message);}}
function build(){
 for(const [name,op,options] of sections){const section=document.createElement('section'),h=document.createElement('h2'),row=document.createElement('div');h.textContent=name;row.className='row';section.append(h,row);
  for(const [value,label]of options){const b=document.createElement('button');b.textContent=label;b.dataset.write='';b.onclick=()=>guarded(()=>send(op||value,op?value:null));row.append(b);} $('controls').append(section);
 }
 const s=document.createElement('section');s.innerHTML='<h2>공용 볼륨</h2><div class="row"><label>볼륨 (%) <input id="volume" type="number" min="0" max="100" step="1" value="10"></label><button id="volumeSend" data-write>볼륨 적용</button></div>'; $('controls').append(s);
 $('volumeSend').onclick=()=>guarded(()=>{const v=$('volume').value;if(!/^(?:[0-9]|[1-9][0-9]|100)$/.test(v))throw Error('볼륨은 0~100 정수로 입력하세요.');return send('volume',v);});
}
function resetPage(){page=null;$('track').replaceChildren();$('page').textContent='목록 미조회';}
function render(){
 $('site').disabled=busy; $('rails').replaceChildren();
 for(const r of view?.rails||[]){const b=document.createElement('button');b.textContent=`${r.name} · ${r.gateway_id}/${r.number} · ${r.online?'Pi 연결':'오프라인'}`;b.setAttribute('aria-pressed',String(selected.has(r.id)));b.disabled=busy;b.onclick=()=>{if(selected.has(r.id))selected.delete(r.id);else selected.add(r.id);resetPage();render();};$('rails').append(b);}
 $('target').textContent=items().length?'선택: '+items().map(r=>r.name).join(', '):'난간을 선택하세요.';
 $('connection').textContent=view?`권한: ${view.role} · 상태 조회: ${new Date().toLocaleTimeString()}`:'상태 조회 실패 또는 현장 없음';
 $('raw').textContent=JSON.stringify(items().map(r=>({name:r.name,gateway_online:r.online,seen_at:r.seen_at,reported:r.reported,music_status:r.music_status})),null,2);
 document.querySelectorAll('[data-write]').forEach(b=>b.disabled=!writable());
 const single=writable()&&items().length===1;
 $('group').disabled=busy; $('list').disabled=!single; $('prev').disabled=!single||!page||page.offset===0;$('next').disabled=!single||!page||page.offset+8>=page.total;
 $('track').disabled=!single||!page;$('play').disabled=!single||!page||$('track').value==='';renderMusic();renderCall();
}
function renderMusic(){
 const r=items().length===1?items()[0]:null,d=musicDisplay(r?.music_status,r?.online,performance.now()-received);
 $('musicNow').textContent=r?`${d.filename} · ${d.state} · ${Math.floor((d.positionMs||0)/1000)}초 / ${d.durationMs?Math.floor(d.durationMs/1000)+'초':'길이 미확인'} · ${d.fresh?'최신 수신':'오래된 정보 / 미수신'}`:'난간 하나를 선택하세요.';
 $('seek').disabled=!(writable()&&r&&d.fresh&&d.seekable&&d.state==='playing'&&d.durationMs);
}
function renderResults(rows){
 $('results').replaceChildren();for(const c of rows){const tr=document.createElement('tr');for(const v of [new Date(c.created_at).toLocaleTimeString(),view?.rails.find(r=>r.id===c.rail_id)?.name||c.rail_id,c.operation+(c.value?' '+c.value:''),c.status,(c.detail||'')+'\n'+(c.result?JSON.stringify(c.result,null,2):'')]){const td=document.createElement('td');td.textContent=v;tr.append(td);}$('results').append(tr);}
}
async function refresh(){
 if(loading||!site)return;loading=true;const token=epoch,requested=site;
 try{const next=await api(`/api/portal/sites/${encodeURIComponent(requested)}/state`);if(token!==epoch)return;view=next;received=performance.now();selected=new Set([...selected].filter(id=>view.rails.some(r=>r.id===id)));render();if(!busy)renderResults(view.commands||[]);}
 catch(e){if(token===epoch){view=null;received=-Infinity;resetPage();render();notice('상태 조회 실패: '+e.message);}throw e;}finally{loading=false;}
}
async function waitResults(rows,limit){
 const deadline=performance.now()+limit;let latest=rows;
 while(true){latest=await Promise.all(latest.map(r=>pending.has(r.status)?api('/api/portal/commands/'+encodeURIComponent(r.id)):r));renderResults(latest);
 if(latest.every(r=>!pending.has(r.status)))return latest;
 if(performance.now()>=deadline)throw Error('응답 대기 종료 · 적용 여부 불명. 상태 새로고침으로 결과를 확인하세요.');
 await new Promise(resolve=>setTimeout(resolve,500));}
}
async function send(operation,value=null){
 if(!writable())throw Error(busy?'이전 명령 응답을 기다리는 중입니다.':'난간 선택·연결·제어 권한을 확인하세요.');
 const targets=items().map(r=>r.id);busy=true;render();notice(`${operation} 전송 중…`);
 try{const rows=await api('/api/portal/commands','POST',{request_id:crypto.randomUUID(),rail_ids:targets,operation,value});
 notice(`${operation} 접수 · 장치 응답 대기`);const results=await waitResults(rows,operation==='music.list'?55000:operation.startsWith('call.')||operation.startsWith('ptt.')?65000:22000);
 const fail=results.filter(r=>!['APPLIED','COMPLETED'].includes(r.status));
 if(fail.length)throw Error(fail.map(r=>`${view?.rails.find(x=>x.id===r.rail_id)?.name||r.rail_id}: ${r.status}${r.detail?' · '+r.detail:''}`).join(' / '));
 notice(results.map(r=>`${view?.rails.find(x=>x.id===r.rail_id)?.name||r.rail_id}: ${r.status==='APPLIED'?'장치 적용 확인':r.detail||'응답 확인'}`).join(' / '));return results;
 }catch(e){resetPage();throw Error(e.message+' · 자동 재전송하지 않습니다.');}finally{busy=false;render();}
}
async function list(offset=0){const r=one(),group=$('group').value,token=epoch;resetPage();const results=await send('music.list',`${group}:${offset}`);if(epoch!==token||items().length!==1||items()[0].id!==r.id||$('group').value!==group)return;
 page=results[0].result;$('track').append(new Option('곡을 선택하세요',''));for(const t of page.tracks)$('track').append(new Option(`${t.index+1}. ${t.filename}`,String(t.index)));$('page').textContent=`총 ${page.total}곡 · ${page.offset+1}~${page.offset+page.tracks.length}`;render();}
async function play(){one();const index=$('track').value;if(!page||index===''||!page.tracks.some(t=>String(t.index)===index))throw Error('목록에서 곡을 선택하세요.');await send('music.play',`${page.catalog_version}:${page.group}:${index}`);await refresh();}
async function seek(){const r=one(),d=musicDisplay(r.music_status,r.online,performance.now()-received),v=$('seconds').value,n=Number(v);if(!d.fresh||!d.seekable||d.state!=='playing'||!d.durationMs||v===''||!Number.isInteger(n)||n<0||n*1000>=d.durationMs)throw Error('최신 재생 상태가 필요합니다. 곡 길이 안의 초 단위 위치를 입력하세요.');await send('music.seek',`${d.playbackId}:${n*1000}`);await refresh();}
function selectedCall(){return (view?.calls||[]).find(c=>items().some(r=>r.id===c.RAIL_ID));}
function renderCall(){
 const call=selectedCall(),single=writable()&&items().length===1;
 $('callState').textContent=call?`${call.STATUS} · ${call.DIRECTION} · ${call.OWNED?'내 통화':'다른 운영자 통화'}`:view?.voice_available?'통화 없음':'서버 Codec2 라이브러리 로드 실패';
 $('callStart').disabled=!single||!!call||!view.voice_available;
 $('callEnd').disabled=!single||!call?.OWNED;
 $('pttOn').disabled=!single||!call?.OWNED||call.STATUS!=='ACTIVE'||!view.voice_available;
 $('pttOff').disabled=!single||!call?.OWNED||call.STATUS!=='ACTIVE';
 if(webVoice && !busy)guarded(()=>webVoice.sync(call,view?.voice_available));
}
async function callControl(op){
 one();webVoice.close();
 if(op!=='call.end')await webVoice.prepare();
 if(op==='ptt.on')await webVoice.mic();
 try{await send(op);}finally{await refresh();}
}
async function changeSite(){epoch++;site=$('site').value;view=null;selected.clear();resetPage();render();await refresh();}
async function init(){webVoice=new WebVoice(notice);build();render();csrf=await api('/api/auth/csrf');me=await api('/api/portal/me');$('account').textContent=`${me.user.NAME} (${me.user.USERNAME})`;
 for(const s of me.sites)$('site').append(new Option(s.NAME+' · '+s.ROLE,s.ID));site=$('site').value;
 $('site').onchange=()=>guarded(changeSite);$('refresh').onclick=()=>guarded(refresh);$('group').onchange=()=>{resetPage();render();};$('track').onchange=render;
 for(const [id,op] of [['callStart','call.start'],['callEnd','call.end'],['pttOn','ptt.on'],['pttOff','ptt.off']])$(id).onclick=()=>guarded(()=>callControl(op));
 window.addEventListener('pagehide',()=>webVoice.close());
 $('list').onclick=()=>guarded(()=>list());$('prev').onclick=()=>guarded(()=>list(page.offset-8));$('next').onclick=()=>guarded(()=>list(page.offset+8));$('play').onclick=()=>guarded(play);$('seek').onclick=()=>guarded(seek);
 await refresh();notice(site?'난간을 선택한 뒤 테스트할 버튼을 누르세요.':'등록된 현장이 없습니다. 기존 모니터링의 관리 메뉴에서 현장·난간을 등록하세요.');
 setInterval(()=>{if($('auto').checked&&!busy)guarded(refresh);},2000);setInterval(renderMusic,1000);
}
if(typeof module!=='undefined')module.exports={sections};else guarded(init);
