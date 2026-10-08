package com.ecl.monitoring;
import java.security.Principal;
import java.time.*;
import java.util.*;
import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.json.JsonMapper;
@RestController
@RequestMapping("/api/portal")
public class Operations {
    private final JdbcTemplate db;private final Accounts accounts;private final Registry registry;private final Commands commands;private final PortalSettings settings;
    private final JsonMapper json=JsonMapper.builder().build();
    public Operations(JdbcTemplate db,Accounts accounts,Registry registry,Commands commands,PortalSettings settings){this.db=db;this.accounts=accounts;this.registry=registry;this.commands=commands;this.settings=settings;}
    public record Schedule(String start_time,String end_time,boolean enabled){}
    @org.springframework.transaction.annotation.Transactional
    @PutMapping("/rails/{rail}/schedule") public synchronized void schedule(Principal p,@PathVariable String rail,@RequestBody Schedule v){
        var r=registry.rail(rail);accounts.permit(p.getName(),(String)r.get("SITE_ID"),true);
        try{if(!v.start_time().matches("[0-9]{2}:[0-9]{2}") || !v.end_time().matches("[0-9]{2}:[0-9]{2}") || LocalTime.parse(v.start_time()).equals(LocalTime.parse(v.end_time())))throw new IllegalArgumentException();}catch(Exception e){throw Accounts.bad("Different HH:mm start/end times required");}
        db.update("DELETE FROM schedules WHERE rail_id=?",rail);db.update("INSERT INTO schedules(rail_id,user_id,start_time,end_time,enabled,last_boundary) VALUES(?,?,?,?,?,?)",rail,accounts.user(p.getName()).get("ID"),v.start_time(),v.end_time(),v.enabled(),LocalDate.now(ZoneId.of("Asia/Seoul"))+" "+LocalTime.now(ZoneId.of("Asia/Seoul")).withSecond(0).withNano(0));
        registry.audit(p.getName(),(String)r.get("SITE_ID"),"schedule.save",rail);
    }
    @Scheduled(fixedDelay=10000) public synchronized void boundaries(){
        var now=ZonedDateTime.now(ZoneId.of("Asia/Seoul"));String time=now.toLocalTime().withSecond(0).withNano(0).toString();String boundary=now.toLocalDate()+" "+time;
        for(var s:db.queryForList("SELECT * FROM schedules WHERE enabled=TRUE AND (start_time=? OR end_time=?)",time,time)){
            if(boundary.equals(s.get("LAST_BOUNDARY")))continue;
            db.update("UPDATE schedules SET last_boundary=? WHERE rail_id=?",boundary,s.get("RAIL_ID"));
            String username=db.queryForObject("SELECT username FROM portal_users WHERE id=?",String.class,s.get("USER_ID"));
            try{commands.submit(username,new Commands.Input(UUID.randomUUID(),List.of((String)s.get("RAIL_ID")),"power",time.equals(s.get("START_TIME"))?"on":"off"));}
            catch(ResponseStatusException e){var rail=registry.rail((String)s.get("RAIL_ID"));registry.audit(username,(String)rail.get("SITE_ID"),"schedule.skipped",s.get("RAIL_ID")+" "+e.getStatusCode());}
        }
    }
    public record Contact(String phone){}
    @org.springframework.transaction.annotation.Transactional
    @PutMapping("/sites/{site}/contacts/{label}") public synchronized void contact(Principal p,@PathVariable String site,@PathVariable String label,@RequestBody Contact v){
        accounts.permit(p.getName(),site,true);validLabel(label);String phone=v.phone()==null?"":v.phone().replace("-","");
        if(!phone.matches("0[0-9]{8,10}"))throw Accounts.bad("Invalid phone number");
        db.update("DELETE FROM contacts WHERE site_id=? AND label=?",site,label);db.update("INSERT INTO contacts VALUES(?,?,?)",site,label,phone);registry.audit(p.getName(),site,"contact.save",label);
    }
    public record Sms(UUID request_id,String label,String rail_id){}
    @PostMapping("/sites/{site}/sms") public synchronized Map<String,Object> sms(Principal p,@PathVariable String site,@RequestBody Sms v) throws Exception {
        accounts.permit(p.getName(),site,true);if(v.request_id()==null)throw Accounts.bad("request_id required");validLabel(v.label());
        var rail=registry.rail(v.rail_id());if(!rail.get("SITE_ID").equals(site))throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        String user=(String)accounts.user(p.getName()).get("ID");var existing=db.queryForList("SELECT * FROM sms_requests WHERE id=?",v.request_id().toString());
        if(!existing.isEmpty()){var old=existing.get(0);if(!old.get("USER_ID").equals(user)||!old.get("SITE_ID").equals(site)||!old.get("LABEL").equals(v.label())||!old.get("RAIL_ID").equals(v.rail_id()))throw new ResponseStatusException(HttpStatus.CONFLICT);return Map.of("status",old.get("STATUS"),"delivery_confirmed",false);}
        if(settings.smsKey().isBlank()||settings.smsSecret().isBlank()||!settings.smsFrom().matches("0[0-9]{8,10}"))throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE,"SMS provider not configured");
        var contacts=db.queryForList("SELECT phone FROM contacts WHERE site_id=? AND label=?",site,v.label());if(contacts.isEmpty())throw Accounts.bad("Save a contact first");
        if(db.queryForObject("SELECT COUNT(*) FROM sms_requests WHERE site_id=? AND created_at>?",Integer.class,site,System.currentTimeMillis()-60000)>=3)throw new ResponseStatusException(HttpStatus.TOO_MANY_REQUESTS);
        String id=v.request_id().toString();db.update("INSERT INTO sms_requests VALUES(?,?,?,?,?,?,?)",id,user,site,v.label(),v.rail_id(),"UNKNOWN",System.currentTimeMillis());
        String date=Instant.now().toString(),salt=UUID.randomUUID().toString().replace("-","");Mac mac=Mac.getInstance("HmacSHA256");mac.init(new SecretKeySpec(settings.smsSecret().getBytes(StandardCharsets.UTF_8),"HmacSHA256"));String signature=HexFormat.of().formatHex(mac.doFinal((date+salt).getBytes(StandardCharsets.UTF_8)));
        String text="[Eco Luminous] "+rail.get("NAME")+" 비상 확인 요청. "+Objects.toString(rail.get("ADDRESS"),"");
        var request=HttpRequest.newBuilder(URI.create("https://api.solapi.com/messages/v4/send-many/detail")).timeout(Duration.ofSeconds(5)).header("Content-Type","application/json").header("Authorization","HMAC-SHA256 apiKey="+settings.smsKey()+", date="+date+", salt="+salt+", signature="+signature).POST(HttpRequest.BodyPublishers.ofString(json.writeValueAsString(Map.of("messages",List.of(Map.of("to",contacts.get(0).get("PHONE"),"from",settings.smsFrom(),"text",text)))))).build();
        String status="UNKNOWN";
        try{var response=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build().send(request,HttpResponse.BodyHandlers.ofString());if(response.statusCode()/100==2){var body=json.readTree(response.body());status=body.path("failedMessageList").isArray() && body.path("failedMessageList").size()>0?"REJECTED":"ACCEPTED";}else status="REJECTED";}catch(java.io.IOException e){/* No resend: provider may have accepted it. */}
        db.update("UPDATE sms_requests SET status=? WHERE id=?",status,id);registry.audit(p.getName(),site,"sms."+status.toLowerCase(),id);
        return Map.of("status",status,"delivery_confirmed",false);
    }
    private static void validLabel(String label){if(!Set.of("주민센터","소방서","경찰서").contains(label==null?"":label))throw Accounts.bad("Unknown contact label");}
}
