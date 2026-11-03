const vm=require('node:vm'),fs=require('node:fs'),assert=require('node:assert/strict');
async function scenario(mode){
 const nodes={};function el(){return {children:[],dataset:{},append(...x){this.children.push(...x)},replaceChildren(){this.children=[]},showModal(){this.open=true}};}
 const get=id=>nodes[id]??=el();let requests=[];
 const target={id:'r1',name:'난간 <1>',gateway_id:'g1',number:1,online:true};
 const ctx={console,document:{createElement:el},$:get,text:(id,v)=>get(id).textContent=v,requireSelection:()=>[target],site:'s1',settingsApplying:false,controlBusy:false,pttChanging:false,emergencyAccepting:false,musicBusy:false,toast:()=>{},csrf:{header:'X-CSRF',token:'t'},performance:{now:()=>0},AbortSignal,crypto:require('node:crypto').webcrypto,setTimeout,
 fetch:async(path,opt)=>{requests.push({path,opt});if(opt.method==='GET')return {ok:true,json:async()=>({rails:[{...target,online:mode!=='offline',reported:{}}],calls:mode==='call'?[{GATEWAY_ID:'g1'}]:[]})};const data=JSON.parse(opt.body);return {ok:true,json:async()=>[{id:'cmd',rail_id:'r1',status:mode==='fail'&&data.value==='wroom'?'FAILED':'COMPLETED',result:{steps:[{node:{p4:2,wroom:3,s3:4}[data.value],status:0,data:'01'}]}}]}}};
 vm.createContext(ctx);vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../../main/resources/static/system-diagnosis.js'),'utf8'),ctx);await ctx.startSystemDiagnosis();
 assert.equal(ctx.controlBusy,false);assert.equal(get('systemDiagnosisClose').disabled,false);
 const queries=requests.filter(r=>r.opt.method==='POST').map(r=>JSON.parse(r.opt.body));assert.ok(queries.every(q=>q.operation==='query'));
 assert.equal(queries.length,['offline','call'].includes(mode)?0:3);
 const text=get('systemDiagnosisSummary').textContent;assert.match(text,/진단 완료/);if(mode==='fail')assert.match(text,/실패 1/);
}
(async()=>{for(const m of ['pass','fail','offline','call'])await scenario(m);console.log('PASS: success, device failure, offline, call skip; query-only, lock cleanup');})().catch(e=>{console.error(e);process.exit(1)});
