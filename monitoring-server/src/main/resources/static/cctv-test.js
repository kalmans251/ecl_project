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
 action('refresh',()=>request('/api/portal/cctv/'+camera()));
 action('watch',()=>{el('view').src='/camera-view.html?camera='+encodeURIComponent(camera());});
 action('stop',()=>{el('view').src='about:blank';});
})();
