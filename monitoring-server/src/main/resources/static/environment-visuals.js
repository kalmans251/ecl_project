/* Decorative connection state follows the existing displayed status. */
(() => {
 const value=document.getElementById('systemCommState');
 const visual=document.getElementById('connectionVisual');
 if(!value||!visual)return;
 function sync(){
  const text=value.textContent.trim();
  visual.dataset.state=text==='정상상태'?'connected':/끊김|실패/.test(text)?'disconnected':'pending';
 }
 sync();
 new MutationObserver(sync).observe(value,{childList:true,characterData:true,subtree:true});
})();
