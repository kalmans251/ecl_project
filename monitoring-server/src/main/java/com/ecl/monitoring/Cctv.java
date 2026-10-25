package com.ecl.monitoring;

import java.nio.charset.StandardCharsets;
import java.security.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;
import tools.jackson.databind.json.JsonMapper;

@Service
public class Cctv {
 private final JdbcTemplate db;private final Accounts accounts;private final Registry registry;
 private final JsonMapper json=JsonMapper.builder().build();
 private record Lease(String camera,String user,String session,long expires){}
 private record Ticket(String lease,long expires){}
 private record Observation(Map<String,Object> state,long at){}
 private final Map<String,Lease> leases=new ConcurrentHashMap<>();
 private volatile long mediaControlAt;
 private final Map<String,String> mediaReaders=new ConcurrentHashMap<>();
 private final Map<String,Ticket> tickets=new ConcurrentHashMap<>();
 private final Map<String,Long> demandUntil=new ConcurrentHashMap<>();
 private final Map<String,Observation> observations=new ConcurrentHashMap<>();
 public Cctv(JdbcTemplate db,Accounts accounts,Registry registry){this.db=db;this.accounts=accounts;this.registry=registry;}
 static String digest(String token){try{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(token.getBytes(StandardCharsets.UTF_8)));}catch(Exception e){throw new IllegalStateException(e);}}
 private String random(){byte[] b=new byte[32];new SecureRandom().nextBytes(b);return Base64.getUrlEncoder().withoutPadding().encodeToString(b);}
 public void permit(String user,String camera,boolean write){var c=registry.camera(camera);accounts.permit(user,registry.siteForGateway(c.gatewayId()),write);}
 public synchronized void provision(String user,String camera,String control,String publish,String analysis){
  accounts.requireAdmin(user);registry.camera(camera);
  for(String token:Arrays.asList(control,publish,analysis))if(token==null||!token.matches("[A-Za-z0-9_-]{43}"))throw Accounts.bad("Use separate 32-byte base64url tokens");
  if(new HashSet<>(Arrays.asList(control,publish,analysis)).size()!=3)throw Accounts.bad("Tokens must differ");
  for(String token:List.of(control,publish,analysis))if(db.queryForObject("SELECT COUNT(*) FROM cctv_devices WHERE camera_id<>? AND (control_hash=? OR publish_hash=? OR analysis_hash=?)",Integer.class,camera,digest(token),digest(token),digest(token))>0)throw Accounts.bad("Do not reuse another camera token");
  db.update("MERGE INTO cctv_devices(camera_id,control_hash,publish_hash,analysis_hash,enabled) KEY(camera_id) VALUES(?,?,?,?,FALSE)",camera,digest(control),digest(publish),digest(analysis));
  leases.entrySet().removeIf(e->e.getValue().camera().equals(camera));
  registry.audit(user,registry.siteForGateway(registry.camera(camera).gatewayId()),"cctv.credentials.rotate",camera);
 }
 public boolean auth(String camera,String purpose,String token){
  if(token==null||token.length()>128||!Set.of("control","publish","analysis").contains(purpose))return false;
  var rows=db.queryForList("SELECT "+purpose+"_hash AS secret FROM cctv_devices WHERE camera_id=?",camera);
  return !rows.isEmpty()&&MessageDigest.isEqual(digest(token).getBytes(StandardCharsets.US_ASCII),((String)rows.get(0).get("SECRET")).getBytes(StandardCharsets.US_ASCII));
 }
 public boolean enabled(String camera){var rows=db.queryForList("SELECT enabled FROM cctv_devices WHERE camera_id=?",camera);return !rows.isEmpty()&&Boolean.TRUE.equals(rows.get(0).get("ENABLED"));}
 public void enable(String user,String camera,boolean enabled){permit(user,camera,true);if(db.update("UPDATE cctv_devices SET enabled=? WHERE camera_id=?",enabled,camera)!=1)throw Accounts.bad("Provision camera first");if(!enabled)leases.entrySet().removeIf(e->e.getValue().camera().equals(camera));}
 public boolean analysis(String camera){
  if(!enabled(camera))return false;
  var rows=db.queryForList("SELECT r.id,r.snapshot,r.seen_at FROM rails r JOIN cameras c ON c.rail_id=r.id WHERE c.id=?",camera);if(rows.isEmpty())return false;
  var rail=rows.get(0);var modes=db.queryForList("SELECT args,created_at FROM commands WHERE rail_id=? AND operation='detection' AND status IN ('APPLIED','COMPLETED') ORDER BY created_at DESC LIMIT 1",rail.get("ID"));
  // Prefer an explicitly confirmed command; telemetry can merge old fields into newer snapshots.
  if(!modes.isEmpty())return modes.get(0).get("ARGS").equals("cctv");
  if(rail.get("SNAPSHOT")!=null){var state=json.readTree((String)rail.get("SNAPSHOT"));if(state.has("detection")&&(modes.isEmpty()||((Number)rail.get("SEEN_AT")).longValue()>((Number)modes.get(0).get("CREATED_AT")).longValue()))return state.path("detection").asText().equals("cctv");}
  return !modes.isEmpty()&&modes.get(0).get("ARGS").equals("cctv");
 }
 private boolean valid(Lease l){if(l==null||l.expires()<System.currentTimeMillis()||!enabled(l.camera()))return false;try{permit(l.user(),l.camera(),false);return true;}catch(Exception e){return false;}}
 public boolean wanted(String camera){
  if(!enabled(camera)){demandUntil.remove(camera);return false;}
  if(analysis(camera)||leases.values().stream().anyMatch(l->l.camera().equals(camera)&&valid(l)))demandUntil.put(camera,System.currentTimeMillis()+10000);
  return demandUntil.getOrDefault(camera,0L)>System.currentTimeMillis();
 }
 public synchronized Map<String,Object> view(String user,String session,String camera,String lease){
  permit(user,camera,false);if(!enabled(camera))throw Accounts.bad("Camera disabled or not provisioned");
  prune();
  if(lease==null){if(leases.size()>=1000||leases.values().stream().filter(l->l.user().equals(user)).count()>=10)throw Accounts.bad("Too many viewers");lease=UUID.randomUUID().toString();}
  else{var prior=leases.get(lease);if(!valid(prior)||!prior.camera().equals(camera)||!prior.user().equals(user)||!prior.session().equals(session))throw Accounts.bad("Unknown viewer lease");}
  leases.put(lease,new Lease(camera,user,session,System.currentTimeMillis()+45000));
  String ticket=random();tickets.put(digest(ticket),new Ticket(lease,System.currentTimeMillis()+300000));
  return Map.of("lease",lease,"token",ticket,"whep","/cctv-media/"+camera+"_raw/whep","expires_in",300);
 }
 public void release(String user,String session,String lease){var l=leases.get(lease);if(l!=null&&l.user().equals(user)&&l.session().equals(session))leases.remove(lease,l);}
 @org.springframework.context.event.EventListener public void logout(org.springframework.security.web.session.HttpSessionDestroyedEvent e){leases.entrySet().removeIf(x->x.getValue().session().equals(e.getId()));}
 @org.springframework.scheduling.annotation.Scheduled(fixedDelay=10000) public void prune(){leases.entrySet().removeIf(e->!valid(e.getValue()));tickets.entrySet().removeIf(e->e.getValue().expires()<System.currentTimeMillis()||!leases.containsKey(e.getValue().lease()));}
 public void mediaControlReady(){mediaControlAt=System.currentTimeMillis();}
 public void mediaControlFailed(){mediaControlAt=0;}
 public boolean mediaControlHealthy(){return System.currentTimeMillis()-mediaControlAt<15000;}
 public boolean mediaKnown(String id){return mediaReaders.containsKey(id);}
 public boolean mediaValid(String id){var hash=mediaReaders.get(id);var t=hash==null?null:tickets.get(hash);return t!=null&&t.expires()>System.currentTimeMillis()&&valid(leases.get(t.lease()));}
 public void forgetMedia(String id){mediaReaders.remove(id);}
 public void pruneMedia(Set<String> ids){mediaReaders.entrySet().removeIf(e->!ids.contains(e.getKey())&&!tickets.containsKey(e.getValue()));}
 public Map<String,Object> media(String action,String path,String protocol,String token,String id){
  if(path==null||!path.matches("[A-Za-z0-9_-]{1,80}_raw")||token==null||token.length()>128)throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
  String camera=path.substring(0,path.length()-4);
  if(action.equals("publish")&&protocol.equals("srt")&&wanted(camera)&&auth(camera,"publish",token))return Map.of();
  if(action.equals("read")&&protocol.equals("rtsp")&&analysis(camera)&&auth(camera,"analysis",token))return Map.of();
  var ticket=tickets.get(digest(token));var lease=ticket==null?null:leases.get(ticket.lease());
  if(action.equals("read")&&protocol.equals("webrtc")&&mediaControlHealthy()&&ticket!=null&&ticket.expires()>System.currentTimeMillis()&&valid(lease)&&lease.camera().equals(camera)){
   try{UUID.fromString(id);}catch(Exception e){throw Accounts.bad("Missing media session identity");}
   mediaReaders.put(id,digest(token));return Map.of();
  }
  throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
 }
 public void observe(String camera,Map<String,Object> state){observations.put(camera,new Observation(Map.copyOf(state),System.currentTimeMillis()));}
 public Map<String,Object> latestDetection(String camera){
  var mapped=registry.camera(camera);
  var rows=db.queryForList("SELECT event_id,seq,observed_at,status FROM deliveries WHERE camera_id=? AND gateway_id=? AND railing_id=? AND event_type='enter' ORDER BY seq DESC LIMIT 1",camera,mapped.gatewayId(),mapped.railingId());
  if(rows.isEmpty())return Map.of();
  var enter=rows.get(0);
  var ages=db.queryForList("SELECT age_group,status FROM deliveries WHERE camera_id=? AND event_id=? AND event_type='age' ORDER BY seq DESC LIMIT 1",camera,enter.get("EVENT_ID"));
  var result=new LinkedHashMap<String,Object>();
  result.put("event_seq",enter.get("SEQ"));result.put("observed_at",enter.get("OBSERVED_AT"));
  result.put("enter_status",enter.get("STATUS"));
  result.put("age_group",ages.isEmpty()?"pending":ages.get(0).get("AGE_GROUP"));
  result.put("age_status",ages.isEmpty()?"NOT_RECEIVED":ages.get(0).get("STATUS"));
  return result;
 }
 public Map<String,Object> status(String camera){var o=observations.get(camera);return Map.of("camera_id",camera,"enabled",enabled(camera),"analysis",analysis(camera),"wanted",wanted(camera),"analysis_fresh",o!=null&&System.currentTimeMillis()-o.at()<5000,"analysis_state",o==null?Map.of():o.state(),"media_control_ready",mediaControlHealthy(),"latest_detection",latestDetection(camera));}
}
