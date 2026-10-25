/* Camera-scoped, short-lived WHEP authorization; no credentials in video URLs. */
(async()=>{
 const camera=new URLSearchParams(location.search).get('camera'),status=document.getElementById('status'),video=document.getElementById('video');
 if(!/^[A-Za-z0-9_-]{1,80}$/.test(camera||'')){status.textContent='잘못된 카메라 ID';return;}
 let lease=null,pc=null,resource=null,mediaToken=null,closed=false,generation=0,csrf;
 const pause=ms=>new Promise(r=>setTimeout(r,ms));
 async function api(path,method,body){const r=await fetch(path,{method,headers:{'Content-Type':'application/json',[csrf.header]:csrf.token},body:body===undefined?undefined:JSON.stringify(body)});if(!r.ok){const error=Error('권한 또는 카메라 상태 확인 필요 ('+r.status+')');error.status=r.status;throw error;}return r.status===204||method==='DELETE'?null:r.json();}
 async function disconnect(){generation++;pc?.close();pc=null;video.srcObject=null;const old=resource,token=mediaToken;resource=null;if(old)fetch(old,{method:'DELETE',headers:{Authorization:'Bearer '+token},keepalive:true}).catch(()=>{});}
 function sessionUrl(value){const u=new URL(value,location.origin);if(u.origin!==location.origin)throw Error('잘못된 미디어 주소');const prefix='/'+camera+'_raw/whep/';if(u.pathname.startsWith(prefix))u.pathname='/cctv-media'+u.pathname;if(!u.pathname.startsWith('/cctv-media'+prefix)||u.search||u.hash)throw Error('잘못된 미디어 세션');return u.href;}
 async function connect(access){
  await disconnect();const version=generation;const peer=pc=new RTCPeerConnection();mediaToken=access.token;
  peer.addTransceiver('video',{direction:'recvonly'});peer.ontrack=e=>{if(version===generation)video.srcObject=new MediaStream([e.track]);};
  await peer.setLocalDescription(await peer.createOffer());
  for(let i=0;i<50&&peer.iceGatheringState!=='complete';i++)await pause(100);
  if(version!==generation||closed)return;
  const r=await fetch(access.whep,{method:'POST',headers:{'Content-Type':'application/sdp',Authorization:'Bearer '+access.token},body:peer.localDescription.sdp});
  if(r.status!==201)throw Error('영상 대기 중 ('+r.status+')');
  const url=sessionUrl(r.headers.get('Location')||'');
  if(version!==generation||closed){fetch(url,{method:'DELETE',headers:{Authorization:'Bearer '+access.token}}).catch(()=>{});return;}
  resource=url;await peer.setRemoteDescription({type:'answer',sdp:await r.text()});status.textContent='영상 연결됨';
 }
 const release=()=>{closed=true;disconnect();if(lease&&csrf)fetch('/api/portal/cctv/view/'+lease,{method:'DELETE',headers:{[csrf.header]:csrf.token},keepalive:true}).catch(()=>{});};
 addEventListener('pagehide',release);
 try{
  const r=await fetch('/api/auth/csrf');csrf=await r.json();let connectedAt=0;
  while(!closed){
   try{
    const access=await api('/api/portal/cctv/'+camera+'/view','POST',{lease});lease=access.lease;
    if(!pc||['failed','disconnected','closed'].includes(pc.connectionState)||Date.now()-connectedAt>240000){await connect(access);connectedAt=Date.now();}
   }catch(e){await disconnect();status.textContent=e.message;if(e.status===400)lease=null;if(e.status===401||e.status===403){release();break;}}
   await pause(10000);
  }
 }catch(e){status.textContent=e.message;release();}
})();
