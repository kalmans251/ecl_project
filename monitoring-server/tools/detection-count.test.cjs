const {test}=require('node:test'),assert=require('node:assert/strict');
const counts=require('../src/main/resources/static/detection-count.js');
function result(rail,count,reset=false,at=1000){const operation=reset?'detection.reset':'detection.count';return {rail_id:rail,created_at:at,operation,status:reset?'APPLIED':'COMPLETED',result:{operation,device_application_confirmed:reset,steps:[{node:2,service:9,command:reset?54:16,status:0,data:'0101'+count.toString(16).padStart(8,'0')}]}};}
test('per-rail count, unsigned range and reset confirmation',()=>{
 counts.ingest([result('one',4294967295),result('two',17)]);
 assert.equal(counts.get('one').count,4294967295);assert.equal(counts.get('two').count,17);
 counts.ingest([result('one',0,true,2000),result('one',100,false,500)]);
 assert.equal(counts.get('one').count,0);assert.equal(counts.get('two').count,17);
});
test('unknown or invalid reset cannot replace confirmed count',()=>{
 counts.ingest([result('safe',9)]);
 const unknown=result('safe',0,true,3000);unknown.status='UNKNOWN';counts.ingest([unknown,result('safe',1,true,4000)]);
 assert.equal(counts.get('safe').count,9);
 const wrong=result('safe',0,true);wrong.result.steps[0].node=3;assert.equal(counts.decode(wrong),null);
});
