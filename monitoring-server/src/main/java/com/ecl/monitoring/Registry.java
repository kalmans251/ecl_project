package com.ecl.monitoring;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
@Service
public class Registry {
    private final JdbcTemplate db;
    private final Settings settings;
    private final Accounts accounts;
    public Registry(JdbcTemplate db,Settings settings,Accounts accounts) { this.db=db; this.settings=settings; this.accounts=accounts; }
    @jakarta.annotation.PostConstruct public void seed() {
        if(db.queryForList("SELECT id FROM sites WHERE id='site-01'").isEmpty()) db.update("INSERT INTO sites VALUES('site-01','기본 현장')");
        for(var gateway:settings.gateways()) if(db.queryForList("SELECT id FROM portal_gateways WHERE id=?",gateway.id()).isEmpty())
            db.update("INSERT INTO portal_gateways VALUES(?,?,?,?)",gateway.id(),"site-01",gateway.id(),accounts.passwordEncoder().encode(gateway.token()));
        for(var camera:settings.cameras()) {
            String rail=ensureRail(camera.gatewayId(),camera.railingId());
            if(db.queryForList("SELECT id FROM cameras WHERE id=?",camera.id()).isEmpty())
                db.update("INSERT INTO cameras VALUES(?,?,?)",camera.id(),rail,"/cctv/"+camera.id()+"/");
        }
    }
    public boolean authenticateGateway(String id,String token) {
        var rows=db.queryForList("SELECT token_hash FROM portal_gateways WHERE id=?",id);
        return token!=null && token.getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=72 && !rows.isEmpty() && accounts.passwordEncoder().matches(token,(String)rows.get(0).get("TOKEN_HASH"));
    }
    public String ensureRail(String gateway,int number) {
        var rows=db.queryForList("SELECT id FROM rails WHERE gateway_id=? AND number=?",gateway,number);
        if(!rows.isEmpty()) return (String)rows.get(0).get("ID");
        String id=UUID.randomUUID().toString();
        db.update("INSERT INTO rails(id,gateway_id,number,name) VALUES(?,?,?,?)",id,gateway,number,"난간 "+number);
        return id;
    }
    public Map<String,Object> rail(String id) {
        var rows=db.queryForList("SELECT r.*,g.site_id FROM rails r JOIN portal_gateways g ON g.id=r.gateway_id WHERE r.id=?",id);
        if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        return rows.get(0);
    }
    public Map<String,Object> deviceRail(String gateway,int number) {
        var rows=db.queryForList("SELECT id FROM rails WHERE gateway_id=? AND number=?",gateway,number);
        if(rows.isEmpty()) throw Accounts.bad("미등록 난간입니다");
        return rail((String)rows.get(0).get("ID"));
    }
    public Settings.Camera camera(String id) {
        var rows=db.queryForList("SELECT c.id,r.gateway_id,r.number FROM cameras c JOIN rails r ON c.rail_id=r.id WHERE c.id=?",id);
        if(rows.isEmpty()) throw Accounts.bad("Unknown camera");
        var c=rows.get(0); return new Settings.Camera((String)c.get("ID"),(String)c.get("GATEWAY_ID"),((Number)c.get("NUMBER")).intValue());
    }
    public String siteForGateway(String id) {
        var rows=db.queryForList("SELECT site_id FROM portal_gateways WHERE id=?",id);
        if(rows.isEmpty()) throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        return (String)rows.get(0).get("SITE_ID");
    }
    public List<Map<String,Object>> sites(String username) {
        var u=accounts.user(username);
        if(Boolean.TRUE.equals(u.get("ADMIN"))) return db.queryForList("SELECT id,name,'ADMIN' AS role FROM sites ORDER BY name");
        return db.queryForList("SELECT s.*,m.role FROM sites s JOIN memberships m ON s.id=m.site_id WHERE m.user_id=? ORDER BY s.name",u.get("ID"));
    }
    public synchronized void site(String username,String id,String name) {
        accounts.requireAdmin(username); validId(id); validName(name);
        if(!db.queryForList("SELECT id FROM sites WHERE id=?",id).isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT);
        db.update("INSERT INTO sites VALUES(?,?)",id,name);
    }
    public synchronized void gateway(String username,String id,String site,String name,String token) {
        accounts.requireAdmin(username); validId(id); validName(name);
        if(token==null || token.length()<32 || token.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>72 || token.equals(settings.adminToken()) || token.equals(settings.analyticsToken())) throw Accounts.bad("장치 전용 토큰을 설정하세요");
        if(db.queryForList("SELECT id FROM sites WHERE id=?",site).isEmpty()) throw Accounts.bad("Unknown site");
        if(!db.queryForList("SELECT id FROM portal_gateways WHERE id=?",id).isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT);
        db.update("INSERT INTO portal_gateways VALUES(?,?,?,?)",id,site,name,accounts.passwordEncoder().encode(token));
    }
    public synchronized String addRail(String username,String gateway,int number,String name) {
        accounts.requireAdmin(username); validName(name); siteForGateway(gateway);
        if(number<1 || number>255) throw Accounts.bad("난간 번호는 1..255입니다");
        if(!db.queryForList("SELECT id FROM rails WHERE gateway_id=? AND number=?",gateway,number).isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT);
        String id=ensureRail(gateway,number); db.update("UPDATE rails SET name=? WHERE id=?",name,id); return id;
    }
    public synchronized void camera(String username,String id,String railId,String path) {
        accounts.requireAdmin(username); validId(id); rail(railId);
        if(path==null || !(path.isEmpty() || path.equals("/cctv/"+id+"/"))) throw Accounts.bad("영상 경로는 /cctv/<stream>/ 형식입니다");
        if(!db.queryForList("SELECT id FROM cameras WHERE id=? OR rail_id=?",id,railId).isEmpty()) throw new ResponseStatusException(HttpStatus.CONFLICT);
        db.update("INSERT INTO cameras VALUES(?,?,?)",id,railId,path);
    }
    public void location(String username,String railId,Double lat,Double lng,String address) {
        var rail=rail(railId); accounts.permit(username,(String)rail.get("SITE_ID"),true);
        if(lat==null || lng==null || !Double.isFinite(lat) || !Double.isFinite(lng) || lat < -90 || lat >90 || lng< -180 || lng>180 || address==null || address.length()>200) throw Accounts.bad("좌표/주소가 올바르지 않습니다");
        db.update("UPDATE rails SET latitude=?,longitude=?,address=? WHERE id=?",lat,lng,address,railId);
        audit(username,(String)rail.get("SITE_ID"),"location",railId);
    }
    public void audit(String username,String site,String action,String detail) {
        String user=(String)accounts.user(username).get("ID");
        db.update("INSERT INTO audit_log VALUES(?,?,?,?,?,?)",UUID.randomUUID().toString(),user,site,action,detail,System.currentTimeMillis());
    }
    public List<Map<String,Object>> gateways(String username) {
        accounts.requireAdmin(username); return db.queryForList("SELECT id,site_id,name FROM portal_gateways ORDER BY id");
    }
    static void validId(String s) { if(s==null || !s.matches("[a-zA-Z0-9_-]{1,80}")) throw Accounts.bad("Invalid ID"); }
    static void validName(String s) { if(s==null || s.isBlank() || s.length()>100) throw Accounts.bad("Invalid name"); }
}
