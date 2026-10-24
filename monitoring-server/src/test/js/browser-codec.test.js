const {test}=require('node:test'),assert=require('node:assert/strict');
const create=require('../../main/resources/static/codec2/codec2.js');
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
test('real WASM Codec2 geometry, encode/decode and independent instances',async()=>{
 const a=await create(),b=await create();
 const enc=a._codec2_create(1),dec=b._codec2_create(1);assert.ok(enc&&dec);
 assert.equal(a._codec2_samples_per_frame(enc),160);assert.equal(a._codec2_bits_per_frame(enc),48);
 const input=a._malloc(2560),bits=a._malloc(48),incoming=b._malloc(48),output=b._malloc(2560);
 for(let i=0;i<1280;i++)a.HEAP16[input/2+i]=Math.round(10000*Math.sin(i*2*Math.PI*220/8000));
 for(let i=0;i<8;i++)a._codec2_encode(enc,bits+i*6,input+i*320);
 const encoded=a.HEAPU8.slice(bits,bits+48);assert.ok(encoded.some(x=>x));b.HEAPU8.set(encoded,incoming);
 for(let i=0;i<8;i++)b._codec2_decode(dec,output+i*320,incoming+i*6);
 assert.ok(b.HEAP16.subarray(output/2,output/2+1280).some(x=>Math.abs(x)>100));
 a._codec2_destroy(enc);b._codec2_destroy(dec);a._free(input);a._free(bits);b._free(incoming);b._free(output);
});
test('real codec worker rejects stale epochs and survives reset',async()=>{
 const messages=[];const context=vm.createContext({ArrayBuffer,Uint8Array,Error,importScripts(){},Codec2Wasm:create,postMessage:m=>messages.push(m)});
 vm.runInContext(fs.readFileSync(path.join(__dirname,'../../main/resources/static/codec2-worker.js'),'utf8'),context);
 async function take(predicate){for(let i=0;i<500;i++){const m=messages.find(predicate);if(m)return m;await new Promise(r=>setTimeout(r,5));}assert.fail('worker timeout');}
 await take(m=>m.type==='ready');context.onmessage({data:{id:1,type:'reset',epoch:'A'}});await take(m=>m.id===1);
 const pcm=new Int16Array(1280);for(let i=0;i<1280;i++)pcm[i]=10000*Math.sin(i*.2);
 context.onmessage({data:{id:2,type:'encode',epoch:'A',data:pcm.buffer}});const encoded=await take(m=>m.id===2);assert.equal(encoded.data.byteLength,48);
 context.onmessage({data:{id:3,type:'reset',epoch:'B'}});await take(m=>m.id===3);
 context.onmessage({data:{id:4,type:'decode',epoch:'A',data:encoded.data}});assert.match((await take(m=>m.id===4)).error,/Stale/);
 context.onmessage({data:{id:5,type:'decode',epoch:'B',data:encoded.data}});assert.equal((await take(m=>m.id===5)).data.byteLength,2560);
 context.onmessage({data:{id:6,type:'decode',epoch:'B',data:new ArrayBuffer(47)}});assert.match((await take(m=>m.id===6)).error,/size/);
});

test('WASM interoperates with firmware-pinned native Codec2 vector',async()=>{
 const v=require('./codec2-native-vector.json'),m=await create(),e=m._codec2_create(1),d=m._codec2_create(1),p=m._malloc(2560),b=m._malloc(48);
 m.HEAP16.set(v.input,p/2);for(let i=0;i<8;i++)m._codec2_encode(e,b+i*6,p+i*320);
 assert.deepEqual(Array.from(m.HEAPU8.slice(b,b+48)),v.bits);
 m.HEAPU8.set(v.bits,b);for(let i=0;i<8;i++)m._codec2_decode(d,p+i*320,b+i*6);
 assert.ok(Math.max(...v.decoded.map((x,i)=>Math.abs(x-m.HEAP16[p/2+i])))<=8);
 m._codec2_destroy(e);m._codec2_destroy(d);m._free(p);m._free(b);
});
