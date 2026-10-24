/* Firmware-pinned Codec2 2400: eight 160-sample frames per packet. */
importScripts('/codec2/codec2.js');
let module,encoder=0,decoder=0,pcm=0,bits=0,epoch=null;
const ready=Codec2Wasm().then(m=>{
 module=m;pcm=m._malloc(2560);bits=m._malloc(48);if(!pcm||!bits)throw Error('Codec2 buffers unavailable');
 postMessage({type:'ready'});
}).catch(e=>{postMessage({type:'fatal',error:String(e)});throw e;});
let queue=ready;
onmessage=({data:r})=>{queue=queue.then(()=>{
 if(r.type==='reset'){
  if(epoch!==r.epoch){
   if(encoder)module._codec2_destroy(encoder);if(decoder)module._codec2_destroy(decoder);
   encoder=decoder=0;epoch=r.epoch;
  }
  postMessage({id:r.id});return;
 }
 if(r.epoch!==epoch||!epoch)throw Error('Stale Codec2 epoch');
 const encoding=r.type==='encode';
 if(!encoding&&r.type!=='decode')throw Error('Unknown Codec2 operation');
 if(!(r.data instanceof ArrayBuffer)||r.data.byteLength!==(encoding?2560:48))throw Error('Invalid Codec2 packet size');
 let state=encoding?encoder:decoder;
 if(!state){
  state=module._codec2_create(1);
  if(!state)throw Error('Codec2 allocation failed');
  if(module._codec2_samples_per_frame(state)!==160||module._codec2_bits_per_frame(state)!==48){module._codec2_destroy(state);throw Error('Codec2 geometry mismatch');}
  if(encoding)encoder=state;else decoder=state;
 }
 module.HEAPU8.set(new Uint8Array(r.data),encoding?pcm:bits);
 for(let i=0;i<8;i++){
  if(encoding)module._codec2_encode(state,bits+i*6,pcm+i*320);
  else module._codec2_decode(state,pcm+i*320,bits+i*6);
 }
 const out=module.HEAPU8.slice(encoding?bits:pcm,(encoding?bits:pcm)+(encoding?48:2560)).buffer;
 postMessage({id:r.id,data:out},[out]);
 }).catch(e=>{postMessage({id:r.id,error:String(e)});});};
