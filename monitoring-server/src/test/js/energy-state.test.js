const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
test('energy displays estimated SOC, signed input and clears missing observations',()=>{
 const e={};const el=id=>e[id]??={style:{},textContent:''};
 const ctx=vm.createContext({$:el,text:(id,v)=>el(id).textContent=v});
 vm.runInContext(source.slice(source.indexOf('function renderEnergy('),source.indexOf('function renderLive(')),ctx);
 vm.runInContext('renderEnergy({battery_voltage:13.2,battery_percent:70,battery_estimated:true,left_current:-0.1,left_watt:-1.32})',ctx);
 assert.equal(e.batPercentTotal.textContent,'약 70%');assert.equal(e.batteryVoltage.textContent,'13.20 V');assert.equal(e.solarCurrentLeft.textContent,'-0.10');assert.equal(e.chargeWattsRight.textContent,'--');
 vm.runInContext('renderEnergy({})',ctx);assert.equal(e.batteryVoltage.textContent,'미확인');assert.equal(e.batPercentTotal.textContent,'미수신');assert.equal(e.barTotal.style.width,'0%');
 assert.match(source,/s=fresh\?r.reported:\{\}/);assert.ok(source.includes('renderEnergy(s);'));
});
