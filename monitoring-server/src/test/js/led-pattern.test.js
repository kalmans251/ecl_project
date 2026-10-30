const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm'),path=require('node:path');
const source=fs.readFileSync(path.join(__dirname,'../../main/resources/static/portal.js'),'utf8');
test('all twelve patterns share one group and only reported pattern is marked running',()=>{
 const html=fs.readFileSync(path.join(__dirname,'../../main/resources/static/index.html'),'utf8');
 assert.equal((html.match(/name="ledPattern"/g)||[]).length,12);assert.ok(!/name="ledGroup[012]"/.test(html));
 const nodes=[];for(const [group,count]of [[0,6],[1,3],[2,3]])for(let value=0;value<count;value++){const classes=new Set(),row={classList:{toggle(k,on){on?classes.add(k):classes.delete(k)}},classes};nodes.push({dataset:{category:String(group)},value:String(value),checked:false,closest:()=>row,row});}
 const dirty=new Map(),ctx=vm.createContext({dirty,document:{querySelectorAll:()=>nodes}});
 vm.runInContext(source.slice(source.indexOf('function syncLedPatterns('),source.indexOf('\nfunction ',source.indexOf('function syncLedPatterns(')+1)),ctx);
 ctx.syncLedPatterns({led:'music',led_music_pattern:2,power_on:true,led_enabled:true});
 assert.equal(nodes.filter(i=>i.checked).length,1);assert.equal(nodes.filter(i=>i.row.classes.has('is-running')).length,1);assert.equal(nodes.find(i=>i.checked).dataset.category,'2');
 ctx.syncLedPatterns({led:'basic',led_basic_pattern:4,power_on:true,led_enabled:true});assert.equal(nodes.filter(i=>i.checked).length,1);assert.equal(nodes.find(i=>i.checked).value,'4');
 ctx.syncLedPatterns({});assert.equal(nodes.filter(i=>i.checked).length,0);assert.equal(nodes.filter(i=>i.row.classes.has('is-running')).length,0);
});
