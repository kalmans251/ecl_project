package com.ecl.monitoring;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.core.userdetails.*;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.http.HttpStatus;
import org.springframework.web.server.ResponseStatusException;
@Service
public class Accounts implements UserDetailsService {
    private final JdbcTemplate db;
    private final PortalSettings settings;
    private final BCryptPasswordEncoder passwords=new BCryptPasswordEncoder(12);
    public BCryptPasswordEncoder passwordEncoder(){return passwords;}
    public Accounts(JdbcTemplate db, PortalSettings settings) { this.db=db; this.settings=settings; }
    @jakarta.annotation.PostConstruct public void bootstrap() {
        if (db.queryForObject("SELECT COUNT(*) FROM portal_users",Long.class)==0) {
            create(settings.bootstrapUser(),"관리자",settings.bootstrapPassword(),true);
        }
    }
    public synchronized Map<String,Object> create(String username,String name,String password,boolean admin) {
        if (username==null || !username.matches("[a-zA-Z0-9_.@-]{3,100}") || name==null || name.isBlank() || name.length()>100)
            throw bad("사용자 이름 또는 계정 형식이 올바르지 않습니다");
        if(password==null || password.length()<12 || password.getBytes(java.nio.charset.StandardCharsets.UTF_8).length>72)
            throw bad("비밀번호는 12자 이상, UTF-8 72바이트 이하여야 합니다. 최초 실행은 MONITOR_BOOTSTRAP_PASSWORD를 설정하세요");
        username=username.toLowerCase(Locale.ROOT);
        if (!db.queryForList("SELECT id FROM portal_users WHERE username=?",username).isEmpty())
            throw new ResponseStatusException(HttpStatus.CONFLICT,"이미 등록된 계정입니다");
        String id=UUID.randomUUID().toString();
        db.update("INSERT INTO portal_users(id,username,name,password_hash,admin,enabled) VALUES(?,?,?,?,?,TRUE)",id,username,name,passwords.encode(password),admin);
        return Map.of("id",id,"username",username,"name",name,"admin",admin);
    }
    public Map<String,Object> user(String username) {
        if(username==null) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        var rows=db.queryForList("SELECT id,username,name,admin,enabled FROM portal_users WHERE username=?",username.toLowerCase(Locale.ROOT));
        if(rows.isEmpty() || !Boolean.TRUE.equals(rows.get(0).get("ENABLED"))) throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        return rows.get(0);
    }
    public Map<String,Object> requireAdmin(String username) {
        var u=user(username);
        if(!Boolean.TRUE.equals(u.get("ADMIN"))) throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        return u;
    }
    public String permit(String username,String site,boolean write) {
        var user=user(username);
        if(Boolean.TRUE.equals(user.get("ADMIN"))) return "ADMIN";
        var roles=db.queryForList("SELECT role FROM memberships WHERE user_id=? AND site_id=?",user.get("ID"),site);
        if(roles.isEmpty() || (write && !roles.get(0).get("ROLE").equals("OPERATOR"))) throw new ResponseStatusException(HttpStatus.FORBIDDEN);
        return (String)roles.get(0).get("ROLE");
    }
    public List<Map<String,Object>> list(String username) {
        requireAdmin(username);
        return db.queryForList("SELECT id,username,name,admin,enabled FROM portal_users ORDER BY username");
    }
    @org.springframework.transaction.annotation.Transactional
    public synchronized void membership(String username,String userId,String siteId,String role) {
        requireAdmin(username);
        if(!Set.of("VIEWER","OPERATOR","NONE").contains(role==null?"":role)) throw bad("권한은 VIEWER 또는 OPERATOR입니다");
        if(db.queryForList("SELECT id FROM portal_users WHERE id=?",userId).isEmpty()
                || db.queryForList("SELECT id FROM sites WHERE id=?",siteId).isEmpty()) throw bad("계정 또는 현장이 없습니다");
        db.update("DELETE FROM memberships WHERE user_id=? AND site_id=?",userId,siteId);
        if(!role.equals("NONE")) db.update("INSERT INTO memberships VALUES(?,?,?)",userId,siteId,role);
    }
    @Override public UserDetails loadUserByUsername(String username) throws UsernameNotFoundException {
        var rows=db.queryForList("SELECT * FROM portal_users WHERE username=?",username.toLowerCase(Locale.ROOT));
        if(rows.isEmpty()) throw new UsernameNotFoundException("Invalid login");
        var u=rows.get(0);
        return org.springframework.security.core.userdetails.User.withUsername((String)u.get("USERNAME"))
            .password((String)u.get("PASSWORD_HASH")).roles(Boolean.TRUE.equals(u.get("ADMIN"))?"ADMIN":"USER")
            .disabled(!Boolean.TRUE.equals(u.get("ENABLED"))).build();
    }
    static ResponseStatusException bad(String message) { return new ResponseStatusException(HttpStatus.BAD_REQUEST,message); }
}
