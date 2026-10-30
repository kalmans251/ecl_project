package com.ecl.monitoring;

import java.net.URI;
import java.net.http.*;
import java.security.Principal;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.bind.annotation.*;
import tools.jackson.databind.json.JsonMapper;

/** Persisted, permission-scoped weather selection; runs without an open browser. */
@RestController
public class WeatherAutomation {
 private final Map<String,Object> locks=new ConcurrentHashMap<>();
 private final java.util.concurrent.ExecutorService worker=java.util.concurrent.Executors.newSingleThreadExecutor(r->{Thread t=new Thread(r,"weather-auto");t.setDaemon(true);return t;});
 private final java.util.concurrent.atomic.AtomicBoolean refreshing=new java.util.concurrent.atomic.AtomicBoolean();
 private volatile boolean stopped;
 private Object lock(String id){return locks.computeIfAbsent(id,key->new Object());}
 @jakarta.annotation.PreDestroy public void close(){stopped=true;worker.shutdownNow();}
 private final JdbcTemplate db;private final Accounts accounts;private final Registry registry;private final Commands commands;
 private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build();
 private final JsonMapper json=JsonMapper.builder().build();
 private record Weather(String value,long expires){}
 private final Map<String,Weather> cache=new ConcurrentHashMap<>();
 public WeatherAutomation(JdbcTemplate db,Accounts accounts,Registry registry,Commands commands){this.db=db;this.accounts=accounts;this.registry=registry;this.commands=commands;}
 public record Mode(boolean enabled){}
 @PutMapping("/api/portal/rails/{id}/weather-auto")
 public List<Map<String,Object>> set(Principal p,@PathVariable String id,@RequestBody Mode mode) throws Exception {
  synchronized(lock(id)){
  var rail=registry.rail(id);accounts.permit(p.getName(),(String)rail.get("SITE_ID"),true);
  if(!mode.enabled()){db.update("UPDATE weather_auto SET enabled=FALSE WHERE rail_id=?",id);return List.of();}
  String weather=lookup(rail);
  var result=commands.submit(p.getName(),new Commands.Input(UUID.randomUUID(),List.of(id),"weather",weather));
  db.update("MERGE INTO weather_auto(rail_id,username,enabled,last_sent) KEY(rail_id) VALUES(?,?,TRUE,?)",id,p.getName(),System.currentTimeMillis());
  return result;
  }
 }
 static String category(int code){if(Set.of(71,73,75,77,85,86).contains(code))return "snow";if(code<=2)return "clear";if(Set.of(3,45,48).contains(code))return "cloudy";return "rain";}
 private String lookup(Map<String,Object> rail) throws Exception{
  if(!(rail.get("LATITUDE") instanceof Number lat)||!(rail.get("LONGITUDE") instanceof Number lng))throw Accounts.bad("날씨 자동 연동은 설치 좌표가 필요합니다.");
  String key=lat.doubleValue()+","+lng.doubleValue();Weather prior=cache.get(key);if(prior!=null&&prior.expires()>System.currentTimeMillis())return prior.value();
  var request=HttpRequest.newBuilder(URI.create("https://api.open-meteo.com/v1/forecast?latitude="+lat.doubleValue()+"&longitude="+lng.doubleValue()+"&current=weather_code")).timeout(Duration.ofSeconds(8)).GET().build();
  var response=http.send(request,HttpResponse.BodyHandlers.ofString());
  if(response.statusCode()!=200)throw Accounts.bad("현재 날씨 조회 실패 · 잠시 후 다시 시도하세요.");
  var code=json.readTree(response.body()).path("current").path("weather_code");if(!code.isInt()||code.intValue()<0||code.intValue()>99)throw Accounts.bad("올바른 날씨 응답이 없습니다.");
  String value=category(code.intValue());if(cache.size()>256)cache.clear();cache.put(key,new Weather(value,System.currentTimeMillis()+600000));return value;
 }
 @Scheduled(fixedDelay=60000)
 public void refresh(){
  if(stopped||!refreshing.compareAndSet(false,true))return;
  try{worker.execute(()->{try{refreshAll();}finally{refreshing.set(false);}});}catch(java.util.concurrent.RejectedExecutionException ignored){refreshing.set(false);}
 }
 private void refreshAll(){
  for(var setting:db.queryForList("SELECT rail_id,username,last_sent FROM weather_auto WHERE enabled=TRUE")){
   if(stopped)return;
   synchronized(lock((String)setting.get("RAIL_ID"))){
   try{
    if(setting.get("LAST_SENT") instanceof Number n && System.currentTimeMillis()-n.longValue()<600000)continue;
    String id=(String)setting.get("RAIL_ID"),user=(String)setting.get("USERNAME");
    if(db.queryForList("SELECT rail_id FROM weather_auto WHERE rail_id=? AND enabled=TRUE",id).isEmpty())continue;
    var rail=registry.rail(id);
    accounts.permit(user,(String)rail.get("SITE_ID"),true);
    String weather=lookup(rail);
    commands.submit(user,new Commands.Input(UUID.randomUUID(),List.of(id),"weather",weather));
    db.update("UPDATE weather_auto SET last_sent=? WHERE rail_id=?",System.currentTimeMillis(),id);
   }catch(Exception ignored){/* Offline/busy/API failure: preserve the last actual state; retry next minute. */}
   }
  }
 }
}
