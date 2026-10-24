class MonitorMic extends AudioWorkletProcessor {
 constructor(){super();this.phase=0;this.sum=0;this.count=0;this.samples=[];this.epoch=null;this.port.onmessage=e=>{this.epoch=e.data?.epoch||null;this.samples=[];this.phase=0;this.sum=0;this.count=0;};}
 process(inputs){const channel=inputs[0]?.[0];if(channel)for(const sample of channel){this.sum+=sample;this.count++;this.phase+=8000;if(this.phase>=sampleRate){this.phase-=sampleRate;this.samples.push(Math.max(-32768,Math.min(32767,Math.round(this.sum/this.count*32767))));this.sum=0;this.count=0;if(this.samples.length===1280){const buffer=new ArrayBuffer(2560),view=new DataView(buffer);this.samples.forEach((s,i)=>view.setInt16(i*2,s,true));if(this.epoch)this.port.postMessage({epoch:this.epoch,data:buffer},[buffer]);this.samples=[];}}}return true;}
}
registerProcessor('monitor-mic',MonitorMic);
