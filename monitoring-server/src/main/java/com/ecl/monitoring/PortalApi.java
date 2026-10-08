package com.ecl.monitoring;
import java.security.Principal;
import java.util.*;
import java.time.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.web.csrf.CsrfToken;
import tools.jackson.databind.json.JsonMapper;
@RestController
public class PortalApi {
    private final Accounts accounts;private final Registry registry;private final JdbcTemplate db;private final Gateways gateways;private final Commands commands;private final Voice voice;
    private final JsonMapper json=JsonMapper.builder().build();
    public PortalApi(Accounts accounts,Registry registry,JdbcTemplate db,Gateways gateways,Commands commands,Voice voice){this.accounts=accounts;this.registry=registry;this.db=db;this.gateways=gateways;this.commands=commands;this.voice=voice;}
    @GetMapping("/api/auth/csrf") public Map<String,String> csrf(CsrfToken token){return Map.of("token",token.getToken(),"header",token.getHeaderName());}
    @GetMapping("/api/portal/me") public Map<String,Object> me(Principal p){return Map.of("user",accounts.user(p.getName()),"sites",registry.sites(p.getName()));}
    @GetMapping("/api/portal/sites/{site}/state") public Map<String,Object> state(Principal p,@PathVariable String site){
        String role=accounts.permit(p.getName(),site,false);List<Map<String,Object>> rails=new ArrayList<>();
        for(var row:db.queryForList("SELECT r.*,g.site_id,c.id AS camera_id,c.stream_path FROM rails r JOIN portal_gateways g ON g.id=r.gateway_id LEFT JOIN cameras c ON c.rail_id=r.id WHERE g.site_id=? ORDER BY g.id,r.number",site)){
            var out=new LinkedHashMap<String,Object>();for(String k:List.of("ID","GATEWAY_ID","NUMBER","NAME","LATITUDE","LONGITUDE","ADDRESS","SEEN_AT","CAMERA_ID","STREAM_PATH"))out.put(k.toLowerCase(),row.get(k));
            out.put("online",gateways.online((String)row.get("GATEWAY_ID")));out.put("reported",row.get("SNAPSHOT")==null?Map.of():json.readTree((String)row.get("SNAPSHOT")));rails.add(out);
        }
        var calls=db.queryForList("SELECT c.id,c.rail_id,c.status,c.direction,u.name AS owner_name,c.user_id FROM calls c JOIN portal_gateways g ON g.id=c.gateway_id JOIN portal_users u ON u.id=c.user_id WHERE g.site_id=?",site);
        String user=(String)accounts.user(p.getName()).get("ID");
        for(var call:calls){call.put("OWNED",call.remove("USER_ID").equals(user));}
        return Map.of("role",role,"rails",rails,"calls",calls,"commands",commands.list(p.getName(),site),"voice_available",voice.available(),"contacts",db.queryForList("SELECT label,phone FROM contacts WHERE site_id=?",site),"schedules",db.queryForList("SELECT s.rail_id,s.start_time,s.end_time,s.enabled FROM schedules s JOIN rails r ON r.id=s.rail_id JOIN portal_gateways g ON g.id=r.gateway_id WHERE g.site_id=?",site));
    }
    @PostMapping("/api/portal/commands") public List<Map<String,Object>> command(Principal p,@RequestBody Commands.Input input){return commands.submit(p.getName(),input);}
    public record Location(Double latitude,Double longitude,String address){}
    @PutMapping("/api/portal/rails/{id}/location") public void location(Principal p,@PathVariable String id,@RequestBody Location value){registry.location(p.getName(),id,value.latitude(),value.longitude(),value.address());}
    public record NewUser(String username,String name,String password){}
    @PostMapping("/api/portal/admin/users") public Map<String,String> user(Principal p,@RequestBody NewUser value){accounts.requireAdmin(p.getName());return Map.of("id",(String)accounts.create(value.username(),value.name(),value.password(),false).get("id"));}
    @GetMapping("/api/portal/admin/users") public List<Map<String,Object>> users(Principal p){return accounts.list(p.getName());}
    public record Membership(String user_id,String site_id,String role){}
    @PutMapping("/api/portal/admin/memberships") public void membership(Principal p,@RequestBody Membership v){accounts.membership(p.getName(),v.user_id(),v.site_id(),v.role());}
    public record Site(String id,String name){}
    @PostMapping("/api/portal/admin/sites") public void site(Principal p,@RequestBody Site v){registry.site(p.getName(),v.id(),v.name());}
    public record Gateway(String id,String site_id,String name,String token){}
    @PostMapping("/api/portal/admin/gateways") public void gateway(Principal p,@RequestBody Gateway v){registry.gateway(p.getName(),v.id(),v.site_id(),v.name(),v.token());}
    @GetMapping("/api/portal/admin/gateways") public List<Map<String,Object>> gatewayList(Principal p){return registry.gateways(p.getName());}
    public record Rail(String gateway_id,int number,String name){}
    @PostMapping("/api/portal/admin/rails") public void rail(Principal p,@RequestBody Rail v){registry.addRail(p.getName(),v.gateway_id(),v.number(),v.name());}
    public record Camera(String id,String rail_id,String stream_path){}
    @PostMapping("/api/portal/admin/cameras") public void camera(Principal p,@RequestBody Camera v){registry.camera(p.getName(),v.id(),v.rail_id(),v.stream_path());}
    @GetMapping("/api/portal/sites/{site}/statistics") public Map<String,Object> statistics(Principal p,@PathVariable String site,@RequestParam(defaultValue="daily")String period){
        accounts.permit(p.getName(),site,false);int days=switch(period){case "daily"->1;case "weekly"->7;case "monthly"->30;case "yearly"->365;default->throw Accounts.bad("Invalid period");};
        long from=System.currentTimeMillis()-days*86400000L;double wh=0;long coverage=0;int alarms=0,samples=0;
        Map<String,Map<String,Object>> previous=new HashMap<>();List<Map<String,Object>> points=new ArrayList<>();
        for(var row:db.queryForList("SELECT t.* FROM telemetry_samples t JOIN rails r ON r.id=t.rail_id JOIN portal_gateways g ON g.id=r.gateway_id WHERE g.site_id=? AND t.observed_at>=? ORDER BY t.observed_at",site,from)){
            samples++;String rail=(String)row.get("RAIL_ID");var last=previous.put(rail,row);
            if(Boolean.TRUE.equals(row.get("EMERGENCY")) && (last==null || !Boolean.TRUE.equals(last.get("EMERGENCY"))))alarms++;
            if(last!=null && last.get("LEFT_WATT")!=null && last.get("RIGHT_WATT")!=null && row.get("LEFT_WATT")!=null && row.get("RIGHT_WATT")!=null){
                long dt=((Number)row.get("OBSERVED_AT")).longValue()-((Number)last.get("OBSERVED_AT")).longValue();
                if(dt>0 && dt<=600000){double watt=(((Number)last.get("LEFT_WATT")).doubleValue()+((Number)last.get("RIGHT_WATT")).doubleValue()+((Number)row.get("LEFT_WATT")).doubleValue()+((Number)row.get("RIGHT_WATT")).doubleValue())/2;wh+=watt*dt/3600000;coverage+=dt;}
            }
            if(points.size()<500)points.add(Map.of("time",row.get("OBSERVED_AT"),"rail",rail,"battery",row.get("BATTERY_PERCENT")==null?"":row.get("BATTERY_PERCENT")));
        }
        return Map.of("period",period,"watt_hours",wh,"coverage_rail_seconds",coverage/1000,"emergency_starts",alarms,"samples",samples,"retained_days",90,"points",points);
    }
    @GetMapping("/api/portal/cameras/{camera}/authorize") @ResponseStatus(org.springframework.http.HttpStatus.NO_CONTENT)
    public void cameraAccess(Principal p,@PathVariable String camera){var c=registry.camera(camera);accounts.permit(p.getName(),registry.siteForGateway(c.gatewayId()),false);}
    @GetMapping("/api/portal/sites/{site}/audit") public List<Map<String,Object>> audit(Principal p,@PathVariable String site){accounts.permit(p.getName(),site,true);return db.queryForList("SELECT a.action,a.detail,a.created_at,u.name FROM audit_log a LEFT JOIN portal_users u ON u.id=a.user_id WHERE a.site_id=? ORDER BY a.created_at DESC LIMIT 100",site);}
}
