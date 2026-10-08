package com.ecl.monitoring;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.scheduling.annotation.Scheduled;
import tools.jackson.databind.json.JsonMapper;
@Service
public class Commands {
    public record Input(UUID request_id, List<String> rail_ids, String operation, String value) {}
    private final JdbcTemplate db; private final Accounts accounts; private final Registry registry; private final Gateways gateways;
    private final org.springframework.transaction.support.TransactionTemplate transaction;
    private final JsonMapper json=JsonMapper.builder().build();
    private static final Set<String> CONFIRMABLE=Set.of("volume","music.stop","call.start","call.end","ptt.on","ptt.off");
    private static final Map<String,Set<String>> VALUES=Map.ofEntries(
        Map.entry("power",Set.of("ac","battery","on","off")),Map.entry("projector",Set.of("on","off")),
        Map.entry("led",Set.of("on","off","basic","music")),Map.entry("weather",Set.of("clear","cloudy","rain","snow")),
        Map.entry("music.mode",Set.of("sequential","shuffle","age")),Map.entry("sleep",Set.of("on","off")),
        Map.entry("detection",Set.of("radar","cctv")),Map.entry("query",Set.of("p4","wroom","s3")));
    private static final Set<String> ACTIONS=Set.of("music.start","music.stop","music.pause","music.resume","music.next","call.start","call.end","ptt.on","ptt.off","emergency.ack");
    public Commands(JdbcTemplate db, Accounts accounts, Registry registry, Gateways gateways) {
        this.db=db;this.accounts=accounts;this.registry=registry;this.gateways=gateways;
        this.transaction=new org.springframework.transaction.support.TransactionTemplate(new org.springframework.jdbc.datasource.DataSourceTransactionManager(db.getDataSource()));
    }
    @jakarta.annotation.PostConstruct public void recover() {
        db.update("UPDATE commands SET status='UNKNOWN',detail='Server restarted; application unknown' WHERE status IN ('SENT','RECEIVED')");
        db.update("UPDATE commands SET status='EXPIRED',detail='Server restarted; request discarded' WHERE status='QUEUED'");
        db.update("UPDATE calls SET status='UNKNOWN'");
    }
    public static void validate(String operation,String value) {
        if(operation==null) throw Accounts.bad("Operation required");
        if(operation.equals("volume")) {
            if(value==null || !value.matches("(?:[0-9]|[1-9][0-9]|100)")) throw Accounts.bad("Volume must be 0..100");
        } else if(VALUES.containsKey(operation)) {
            if(!VALUES.get(operation).contains(value==null?"":value)) throw Accounts.bad("Unsupported value");
        } else if(!ACTIONS.contains(operation) || value!=null) throw Accounts.bad("Unsupported operation or value");
    }
    public synchronized List<Map<String,Object>> submit(String username,Input input) {
        if(input==null || input.request_id()==null || input.rail_ids()==null || input.rail_ids().isEmpty() || input.rail_ids().size()>50
            || new HashSet<>(input.rail_ids()).size()!=input.rail_ids().size()) throw Accounts.bad("Select 1..50 unique rails");
        validate(input.operation(),input.value());
        String user=(String)accounts.user(username).get("ID");
        List<Map<String,Object>> rails=input.rail_ids().stream().map(registry::rail).toList();
        for(var rail:rails) accounts.permit(username,(String)rail.get("SITE_ID"),true);
        List<Map<String,Object>> prior=db.queryForList("SELECT * FROM commands WHERE user_id=? AND batch_id=? ORDER BY rail_id",user,input.request_id().toString());
        if(!prior.isEmpty()) {
            if(prior.size()!=rails.size() || prior.stream().anyMatch(r -> !input.rail_ids().contains(r.get("RAIL_ID")) || !input.operation().equals(r.get("OPERATION")) || !Objects.equals(input.value(),r.get("ARGS"))))
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Request ID already used");
            return prior.stream().map(this::result).toList();
        }
        boolean call=input.operation().startsWith("call.") || input.operation().startsWith("ptt.");
        if(call && rails.size()!=1) throw Accounts.bad("Calls require one rail");
        for(var rail:rails) {
            String gateway=(String)rail.get("GATEWAY_ID");
            if(!gateways.online(gateway)) throw new ResponseStatusException(HttpStatus.CONFLICT,"Gateway offline");
            if(db.queryForObject("SELECT COUNT(*) FROM commands WHERE gateway_id=? AND status IN ('QUEUED','SENT','RECEIVED')",Integer.class,gateway)>=100)
                throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS,"Gateway queue full");
            if(!call && !db.queryForList("SELECT id FROM calls WHERE gateway_id=?",gateway).isEmpty())
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Gateway is in a call; only call controls are available");
        }
        List<Map<String,Object>> result=new ArrayList<>();
        transaction.executeWithoutResult(tx -> {
        if(call) reserve(username,user,rails.get(0),input.operation());
        long now=System.currentTimeMillis();
        for(var rail:rails) {
            String id=UUID.randomUUID().toString();
            db.update("INSERT INTO commands(id,batch_id,user_id,gateway_id,rail_id,operation,args,created_at,expires_at,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
                id,input.request_id().toString(),user,rail.get("GATEWAY_ID"),rail.get("ID"),input.operation(),input.value(),now,now+15000,"QUEUED");
            registry.audit(username,(String)rail.get("SITE_ID"),input.operation(),id);
            result.add(result(db.queryForMap("SELECT * FROM commands WHERE id=?",id)));
        }
        });
        dispatch(); return result;
    }
    private void reserve(String username,String user,Map<String,Object> rail,String operation) {
        String gateway=(String)rail.get("GATEWAY_ID"); List<Map<String,Object>> calls=db.queryForList("SELECT * FROM calls WHERE gateway_id=?",gateway);
        if(operation.equals("call.start")) {
            if(!calls.isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT,"Gateway call already reserved");
            db.update("INSERT INTO calls(gateway_id,id,rail_id,user_id,status,touched_at) VALUES(?,?,?,?,?,?)",gateway,UUID.randomUUID().toString(),rail.get("ID"),user,"PENDING",System.currentTimeMillis());
        } else {
            if(calls.isEmpty() || !calls.get(0).get("RAIL_ID").equals(rail.get("ID"))) throw new ResponseStatusException(HttpStatus.CONFLICT,"No matching call");
            var c=calls.get(0);
            if(!c.get("USER_ID").equals(user) && !Boolean.TRUE.equals(accounts.user(username).get("ADMIN"))) throw new ResponseStatusException(HttpStatus.FORBIDDEN,"Call belongs to another operator");
            if(operation.startsWith("ptt.") && !c.get("STATUS").equals("ACTIVE")) throw new ResponseStatusException(HttpStatus.CONFLICT,"Call is not confirmed; retry hangup");
            if(operation.equals("call.end")) db.update("UPDATE calls SET status='ENDING',touched_at=? WHERE gateway_id=?",System.currentTimeMillis(),gateway);
        }
    }
    @Scheduled(fixedDelay=200) public synchronized void dispatch() {
        long now=System.currentTimeMillis();
        for(var row:db.queryForList("SELECT * FROM commands WHERE status IN ('QUEUED','SENT','RECEIVED') AND expires_at<=?",now)) {
            String status=row.get("STATUS").equals("QUEUED")?"EXPIRED":"UNKNOWN";
            db.update("UPDATE commands SET status=?,detail='No device confirmation within deadline' WHERE id=?",status,row.get("ID"));
            uncertain(row);
        }
        for(var row:db.queryForList("SELECT * FROM commands WHERE status='QUEUED' ORDER BY created_at,id")) {
            String gateway=(String)row.get("GATEWAY_ID");
            if(!gateways.online(gateway) || db.queryForObject("SELECT COUNT(*) FROM commands WHERE gateway_id=? AND status IN ('SENT','RECEIVED')",Integer.class,gateway)>0) continue;
            var rail=registry.rail((String)row.get("RAIL_ID"));
            String username=db.queryForObject("SELECT username FROM portal_users WHERE id=?",String.class,row.get("USER_ID"));
            try { accounts.permit(username,(String)rail.get("SITE_ID"),true); }
            catch(ResponseStatusException e) {db.update("UPDATE commands SET status='FAILED',detail='Permission revoked' WHERE id=?",row.get("ID"));uncertain(row);continue;}
            var message=new LinkedHashMap<String,Object>();message.put("version",1);message.put("type","command");message.put("message_id",row.get("ID"));
            message.put("railing_id",rail.get("NUMBER"));message.put("operation",row.get("OPERATION"));
            if(((String)row.get("OPERATION")).startsWith("call.") || ((String)row.get("OPERATION")).startsWith("ptt.")){var calls=db.queryForList("SELECT id FROM calls WHERE gateway_id=?",gateway);if(!calls.isEmpty())message.put("call_id",calls.get(0).get("ID"));}
            if(row.get("ARGS")!=null)message.put("value",row.get("ARGS"));
            message.put("expires_at",Instant.ofEpochMilli(((Number)row.get("EXPIRES_AT")).longValue()).toString());
            db.update("UPDATE commands SET status='SENT' WHERE id=?",row.get("ID"));
            try {gateways.send(gateway,json.writeValueAsString(message));}
            catch(Exception e) {db.update("UPDATE commands SET status='UNKNOWN',detail='Transport interrupted' WHERE id=?",row.get("ID"));uncertain(row);}
        }
    }
    public synchronized boolean ack(String gateway,String id,String status) {
        var rows=db.queryForList("SELECT * FROM commands WHERE id=? AND gateway_id=?",id,gateway);
        if(rows.isEmpty()) return false;
        if(!Set.of("RECEIVED","PLC_SENT","APPLIED","BUSY","FAILED","EXPIRED").contains(status))throw Accounts.bad("Invalid command acknowledgment");
        var row=rows.get(0);String current=(String)row.get("STATUS");if(current.equals(status))return true;
        if(!Set.of("SENT","RECEIVED").contains(current))throw Accounts.bad("Invalid command transition");
        if(status.equals("APPLIED") && !CONFIRMABLE.contains(row.get("OPERATION")))throw Accounts.bad("Firmware has no application confirmation for this operation");
        if(status.equals("PLC_SENT") && CONFIRMABLE.contains(row.get("OPERATION")))throw Accounts.bad("Await actual application confirmation for this operation");
        if(((Number)row.get("EXPIRES_AT")).longValue()<=System.currentTimeMillis())status="UNKNOWN";
        db.update("UPDATE commands SET status=? WHERE id=?",status,id);
        if(status.equals("APPLIED")) {
            String operation=(String)row.get("OPERATION");
            if(operation.equals("call.end"))db.update("DELETE FROM calls WHERE gateway_id=? AND rail_id=?",gateway,row.get("RAIL_ID"));
            else if(operation.equals("call.start"))db.update("UPDATE calls SET status='ACTIVE',touched_at=? WHERE gateway_id=? AND status='PENDING'",System.currentTimeMillis(),gateway);
            else if(operation.startsWith("ptt."))db.update("UPDATE calls SET direction=?,touched_at=? WHERE gateway_id=?",operation.equals("ptt.on")?"CONTROL_TX":"FIELD_TX",System.currentTimeMillis(),gateway);
        } else if(!status.equals("RECEIVED")) uncertain(row);
        return true;
    }
    private void uncertain(Map<String,Object> row) {
        if(((String)row.get("OPERATION")).startsWith("call.") || ((String)row.get("OPERATION")).startsWith("ptt."))
            db.update("UPDATE calls SET status='UNKNOWN' WHERE gateway_id=?",row.get("GATEWAY_ID"));
    }
    public List<Map<String,Object>> list(String username,String site) {
        accounts.permit(username,site,false);
        return db.queryForList("SELECT c.* FROM commands c JOIN portal_gateways g ON g.id=c.gateway_id WHERE g.site_id=? ORDER BY c.created_at DESC LIMIT 100",site).stream().map(this::result).toList();
    }
    private Map<String,Object> result(Map<String,Object> row) {
        var r=new LinkedHashMap<String,Object>();for(String k:List.of("ID","RAIL_ID","OPERATION","STATUS","DETAIL","CREATED_AT"))r.put(k.toLowerCase(),row.get(k));
        r.put("device_application_confirmed",row.get("STATUS").equals("APPLIED"));return r;
    }
}
