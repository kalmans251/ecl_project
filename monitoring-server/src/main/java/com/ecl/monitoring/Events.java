package com.ecl.monitoring;
import java.time.*;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.json.JsonMapper;
@Service
public class Events {
    public record Input(String camera_id, UUID event_id, String type, String age_group, Instant observed_at) {}
    private final JdbcTemplate db;
    private final Settings settings;
    private final Gateways gateways;
    private final JsonMapper json=JsonMapper.builder().build();
    public Events(JdbcTemplate db, Settings settings, Gateways gateways) {
        this.db=db; this.settings=settings; this.gateways=gateways;
    }
    @jakarta.annotation.PostConstruct public void recover() {
        db.update("UPDATE deliveries SET status='UNKNOWN' WHERE status IN ('SENT','RECEIVED')");
    }
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=1000)
    public synchronized void expireUnconfirmed() {
        for (Map<String,Object> row : db.queryForList("SELECT message_id, expires_at FROM deliveries WHERE status IN ('SENT','RECEIVED')")) {
            if (!Instant.parse((String)row.get("EXPIRES_AT")).isAfter(Instant.now()))
                db.update("UPDATE deliveries SET status='UNKNOWN' WHERE message_id=?",row.get("MESSAGE_ID"));
        }
    }
    public synchronized Map<String,Object> submit(Input input) {
        if (input == null || input.event_id()==null || input.observed_at()==null
                || !Set.of("enter","age").contains(input.type()==null ? "" : input.type())) bad("Invalid event fields");
        Settings.Camera camera=settings.cameras().stream().filter(c -> c.id().equals(input.camera_id())).findFirst()
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.BAD_REQUEST,"Unknown camera"));
        if (input.type().equals("enter") && input.age_group()!=null) bad("enter cannot contain age_group");
        if (input.type().equals("age") && !Set.of("10","20","30","40","keep").contains(input.age_group()==null ? "" : input.age_group())) bad("Invalid age_group");
        List<Map<String,Object>> duplicates=db.queryForList("SELECT * FROM deliveries WHERE camera_id=? AND event_id=? AND event_type=?",
            camera.id(),input.event_id().toString(),input.type());
        if (!duplicates.isEmpty()) {
            Map<String,Object> prior=duplicates.get(0);
            if (!Objects.equals(prior.get("AGE_GROUP"),input.age_group()) || !prior.get("OBSERVED_AT").equals(input.observed_at().toString()))
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Event ID already used with different content");
            return result(prior);
        }
        Instant now=Instant.now(), expiry=input.observed_at().plusSeconds(5);
        if (!expiry.isAfter(now) || input.observed_at().isAfter(now.plusSeconds(2))) bad("Event stale or future timestamp");
        long seq;
        if (input.type().equals("enter")) {
            seq=db.queryForObject("SELECT NEXT VALUE FOR event_seq",Long.class);
        } else {
            List<Map<String,Object>> parents=db.queryForList("SELECT * FROM deliveries WHERE camera_id=? AND event_id=? AND event_type='enter'",
                camera.id(),input.event_id().toString());
            if (parents.isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT,"Send enter before age");
            Map<String,Object> parent=parents.get(0);
            if (!Set.of("SENT","RECEIVED","PLC_SENT").contains(parent.get("STATUS")))
                throw new ResponseStatusException(HttpStatus.CONFLICT,"Parent delivery not successful or unresolved");
            Instant detected=Instant.parse((String)parent.get("OBSERVED_AT"));
            Instant parentExpiry=detected.plusSeconds(5);
            if (!parentExpiry.isAfter(now) || input.observed_at().isBefore(detected)) bad("Age result outside detection window");
            if (parentExpiry.isBefore(expiry)) expiry=parentExpiry;
            seq=((Number)parent.get("SEQ")).longValue();
        }
        if (db.queryForObject("SELECT COUNT(*) FROM deliveries",Long.class) >= 100000)
            throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"Event journal full");
        String id=UUID.randomUUID().toString();
        db.update("INSERT INTO deliveries (message_id,camera_id,event_id,event_type,age_group,seq,gateway_id,railing_id,observed_at,expires_at,status) VALUES (?,?,?,?,?,?,?,?,?,?,?)",id,camera.id(),input.event_id().toString(),input.type(),
            input.age_group(),seq,camera.gatewayId(),camera.railingId(),input.observed_at().toString(),expiry.toString(),"SENT");
        Map<String,Object> message=new LinkedHashMap<>();
        message.put("version",1); message.put("message_id",id); message.put("type","cctv."+input.type());
        message.put("camera_id",camera.id()); message.put("railing_id",camera.railingId()); message.put("event_seq",seq);
        message.put("observed_at",input.observed_at().toString()); message.put("expires_at",expiry.toString());
        if (input.age_group()!=null) message.put("age_group",input.age_group());
        try { gateways.send(camera.gatewayId(),json.writeValueAsString(message)); }
        catch (Exception e) { db.update("UPDATE deliveries SET status='UNKNOWN' WHERE message_id=?",id); }
        return find(id);
    }
    public synchronized void ack(String gateway, String id, String status) {
        if (!Set.of("RECEIVED","PLC_SENT","BUSY","FAILED","EXPIRED").contains(status)) bad("Invalid acknowledgment status");
        List<Map<String,Object>> rows=db.queryForList("SELECT * FROM deliveries WHERE message_id=? AND gateway_id=?",id,gateway);
        if (rows.isEmpty()) bad("Unknown message for gateway");
        String current=(String)rows.get(0).get("STATUS");
        if (current.equals(status)) return;
        if (!Set.of("SENT","RECEIVED").contains(current) || (current.equals("RECEIVED") && status.equals("RECEIVED"))) bad("Invalid acknowledgment transition");
        if (Set.of("RECEIVED","PLC_SENT").contains(status) && !Instant.parse((String)rows.get(0).get("EXPIRES_AT")).isAfter(Instant.now())) status="EXPIRED";
        db.update("UPDATE deliveries SET status=? WHERE message_id=?",status,id);
    }
    public Map<String,Object> find(String id) {
        List<Map<String,Object>> rows=db.queryForList("SELECT * FROM deliveries WHERE message_id=?",id);
        if (rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        return result(rows.get(0));
    }
    private Map<String,Object> result(Map<String,Object> row) {
        return Map.of("message_id",row.get("MESSAGE_ID"),"event_seq",row.get("SEQ"),"status",row.get("STATUS"),
                "device_application_confirmed",false);
    }
    private static void bad(String message) { throw new ResponseStatusException(HttpStatus.BAD_REQUEST,message); }
}
