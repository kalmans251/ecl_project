package com.ecl.monitoring;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
/** Operations participate in the caller's transaction. Rail lock orders events and acceptance. */
@org.springframework.stereotype.Component
public class Incidents {
 private final JdbcTemplate database;
 public Incidents(JdbcTemplate db){this.database=db;}
 @org.springframework.context.event.EventListener(org.springframework.boot.context.event.ApplicationReadyEvent.class)
 @org.springframework.transaction.annotation.Transactional
 public void recover(){
  var json=tools.jackson.databind.json.JsonMapper.builder().build();
  for(var rail:database.queryForList("SELECT id,snapshot FROM rails WHERE snapshot IS NOT NULL")){
   var state=json.readTree((String)rail.get("SNAPSHOT"));
   if(state.path("emergency").asBoolean() && state.path("emergency_at").asLong()>0)
    event(database,(String)rail.get("ID"),state.path("emergency_at").asLong(),true);
  }
 }
 public static void event(JdbcTemplate db,String rail,long at,boolean active){
  db.queryForList("SELECT id FROM rails WHERE id=? FOR UPDATE",rail);
  if(active){
   if(db.queryForList("SELECT id FROM emergency_incidents WHERE rail_id=? AND started_at=?",rail,at).isEmpty())
    db.update("INSERT INTO emergency_incidents(id,rail_id,started_at) VALUES(?,?,?)",UUID.randomUUID().toString(),rail,at);
  }else db.update("UPDATE emergency_incidents SET cleared_at=? WHERE rail_id=? AND cleared_at IS NULL AND started_at<=?",at,rail,at);
 }
 public static void reserve(JdbcTemplate db,String rail,String call,String user){
  db.queryForList("SELECT id FROM rails WHERE id=? FOR UPDATE",rail);
  var rows=db.queryForList("SELECT id FROM emergency_incidents WHERE rail_id=? AND cleared_at IS NULL ORDER BY started_at DESC LIMIT 1",rail);
  if(rows.isEmpty())return; // older gateways may not publish emergency events
  db.update("INSERT INTO emergency_incident_calls(call_id,incident_id,user_id,requested_at) VALUES(?,?,?,?)",call,rows.get(0).get("ID"),user,System.currentTimeMillis());
 }
 public static void connected(JdbcTemplate db,String call){db.update("UPDATE emergency_incident_calls SET connected_at=COALESCE(connected_at,?) WHERE call_id=?",System.currentTimeMillis(),call);}
 public static void ended(JdbcTemplate db,String call){db.update("UPDATE emergency_incident_calls SET ended_at=COALESCE(ended_at,?) WHERE call_id=?",System.currentTimeMillis(),call);}
 public static void notStarted(JdbcTemplate db,String call){db.update("UPDATE emergency_incident_calls SET not_started_at=COALESCE(not_started_at,?) WHERE call_id=?",System.currentTimeMillis(),call);}
 public static List<Map<String,Object>> list(JdbcTemplate db,String site,boolean history){
  String pending="(e.cleared_at IS NULL OR EXISTS(SELECT 1 FROM emergency_incident_calls a WHERE a.incident_id=e.id AND a.ended_at IS NULL AND a.not_started_at IS NULL))";
  var rows=db.queryForList("SELECT e.* FROM emergency_incidents e JOIN rails r ON r.id=e.rail_id JOIN portal_gateways g ON g.id=r.gateway_id WHERE g.site_id=? AND "+(history?"NOT ":"")+pending+" ORDER BY e.started_at "+(history?"DESC LIMIT 100":"ASC"),site);
  var result=new ArrayList<Map<String,Object>>();
  for(var row:rows){
   var attempts=db.queryForList("SELECT a.*,u.name AS owner_name,c.status AS call_status FROM emergency_incident_calls a LEFT JOIN portal_users u ON u.id=a.user_id LEFT JOIN calls c ON c.id=a.call_id WHERE a.incident_id=? ORDER BY a.requested_at",row.get("ID"));
   var out=new LinkedHashMap<String,Object>();out.put("id",row.get("ID"));out.put("rail_id",row.get("RAIL_ID"));out.put("started_at",row.get("STARTED_AT"));out.put("cleared_at",row.get("CLEARED_AT"));out.put("closed",history);out.put("attempts",attempts);result.add(out);
  }return result;
 }
}
