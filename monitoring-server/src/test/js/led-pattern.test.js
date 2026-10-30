const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
test('tab browsing never queues a pattern and only one explicit choice stays pending',()=>{
 const nodes=[];for(const [group,count]of [[0,6],[1,3],[2,3]])for(let value=0;value<count;value++){const classes=new Set(),row={classList:{toggle(k,on){on?classes.add(k):classes.delete(k)}},classes};nodes.push({dataset:{category:String(group)},value:String(value),checked:false,closest:()=>row,row});}
 const dirty=new Map(),tabs=[0,1,2].map(()=>({classList:{toggle(){}}})),panels={};
 const reported={led:'basic',led_basic_pattern:4,power_on:true,led_enabled:true};
 const ctx=vm.createContext({currentCategory:0,dirty,rails:()=>[{reported}],mark:(k,v)=>dirty.set(k,v),$:id=>panels[id]??={style:{}},document:{querySelectorAll:q=>q==='.category-tab-btn'?tabs:nodes}});
 for(const name of ['switchCategoryTabUI','setSubModeUI','syncLedPatterns']){
  const start=source.indexOf('function '+name+'('),end=source.indexOf('\nfunction ',start+1);
  vm.runInContext(source.slice(start,end),ctx);
 }
 const count=kind=>nodes.filter(n=>n.row.classes.has(kind)).length;
 ctx.switchCategoryTabUI('weather',1);ctx.switchCategoryTabUI('music',2);assert.equal(dirty.size,0);
 ctx.setSubModeUI(2);assert.equal(count('is-pending'),1);assert.equal(count('is-running'),1);assert.equal(nodes.filter(n=>n.checked).length,1);
 ctx.switchCategoryTabUI('weather',1);assert.equal(dirty.get('led'),'music');assert.equal(count('is-pending'),1);
 ctx.setSubModeUI(1);assert.equal(dirty.has('led.music_pattern'),false);assert.equal(count('is-pending'),1);assert.equal(nodes.find(n=>n.checked).dataset.category,'1');
 ctx.switchCategoryTabUI('basic',0);ctx.setSubModeUI(3);assert.equal(count('is-pending'),1);assert.equal(nodes.find(n=>n.checked).value,'3');
 dirty.clear();ctx.syncLedPatterns(reported);assert.equal(count('is-pending'),0);assert.equal(count('is-running'),1);assert.equal(nodes.filter(n=>n.checked).length,0);
});
