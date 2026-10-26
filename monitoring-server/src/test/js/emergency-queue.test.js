const {test}=require('node:test'),assert=require('node:assert/strict');
const {EmergencyQueue}=require('../../main/resources/static/emergency-queue.js');
const rail=(active=true)=>({id:'r',name:'난간',reported:{emergency:active,emergency_at:10}});
test('dismissal does not remove a pending call; physical clear does',()=>{const q=new EmergencyQueue();assert.equal(q.rows('s',[rail()],[]).length,1);assert.equal(q.rows('s',[rail()],[]).length,1);assert.equal(q.rows('s',[rail(false)],[]).length,0);});
test('accepted alarm remains while call end is unconfirmed',()=>{const q=new EmergencyQueue();q.rows('s',[rail()],[]);const rows=q.rows('s',[rail(false)],[{RAIL_ID:'r',STATUS:'UNKNOWN',OWNER_NAME:'운영자'}]);assert.equal(rows.length,1);assert.match(rows[0].status,/미확정/);assert.equal(q.rows('s',[rail(false)],[]).length,0);});
test('another site cannot inherit previous incident',()=>{const q=new EmergencyQueue();q.rows('s',[rail()],[]);assert.equal(q.rows('other',[rail(false)],[{RAIL_ID:'r',STATUS:'ACTIVE'}]).length,0);});
