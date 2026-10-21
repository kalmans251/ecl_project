const {test}=require('node:test'),assert=require('node:assert/strict');
const {callView}=require('../../main/resources/static/call-view.js');
const rail={online:true,gateway_id:'g'},call={OWNED:true,STATUS:'ACTIVE',DIRECTION:'FIELD_TX',GATEWAY_ID:'g'};
test('ready, pending, fault, offline, other owner and shared gateway',()=>{
 assert.equal(callView(call,rail,[call],'OPERATOR').ptt,true);
 for(const STATUS of ['PENDING','SWITCHING','ENDING','UNKNOWN'])assert.equal(callView({...call,STATUS},rail,[call],'OPERATOR').ptt,false);
 const fault=callView({...call,STATUS:'UNKNOWN',DETAIL:'S3_TIMEOUT'},rail,[call],'OPERATOR');
 assert.equal(fault.end,true);assert.equal(fault.retry,true);assert.match(fault.detail,/S3/);
 assert.equal(callView(call,{...rail,online:false},[call],'OPERATOR').ptt,false);
 assert.equal(callView({...call,OWNED:false},rail,[call],'OPERATOR').end,false);
 assert.equal(callView(null,rail,[call],'OPERATOR').start,false);
 assert.equal(callView(call,rail,[call],'VIEWER').ptt,false);
});
