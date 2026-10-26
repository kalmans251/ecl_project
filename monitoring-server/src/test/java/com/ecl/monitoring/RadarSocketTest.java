package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
import java.net.URI;
import java.util.*;
import java.lang.reflect.Proxy;
import java.security.Principal;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpHeaders;
import org.springframework.web.socket.*;
import tools.jackson.databind.json.JsonMapper;
class RadarSocketTest {
 final JsonMapper json=JsonMapper.builder().build();
 boolean current=true;
 final List<String> sent=new ArrayList<>();
 final Registry registry=new Registry(null,null,null){
  @Override public Map<String,Object> rail(String id){return Map.of("ID",id,"GATEWAY_ID",id.equals("a")?"g1":"g2","NUMBER",1,"SITE_ID",id.equals("a")?"site1":"site2");}
  @Override public Map<String,Object> deviceRail(String g,int n){if(n!=1 || !Set.of("g1","g2").contains(g))throw Accounts.bad("foreign");return rail(g.equals("g1")?"a":"b");}
 };
 final Accounts accounts=new Accounts(null,null){@Override public String permit(String user,String site,boolean write){if(!user.equals(site))throw Accounts.bad("denied");return "VIEWER";}};
 final Gateways gateways=new Gateways(){
  @Override public boolean isCurrent(String g,String s){return current && s.equals("session");}
  @Override public void send(String g,String data){sent.add(g+":"+data);}
 };
 final RadarSocket radar=new RadarSocket(registry,accounts,gateways);
 Map<String,Object> state(){return Map.of("available",true,"source",2,"count",1,"sequence",1,"age_ms",0,"detail",true,"targets",List.of(Map.of("x",-1,"y",2)));}
 tools.jackson.databind.JsonNode envelope(int rail,Instant time,Object state){return json.valueToTree(Map.of("version",1,"type","radar_state","railing_id",rail,"observed_at",time.toString(),"state",state));}
 @Test void validatesAndIsolatesGateways(){
  radar.accept("g1","session",envelope(1,Instant.now(),state()));
  assertEquals(true,radar.view("a","g1").get("available"));
  assertEquals(false,radar.view("a","g2").get("available"));
  assertEquals(false,radar.view("b","g2").get("available"));
  assertThrows(RuntimeException.class,()->radar.accept("g1","session",envelope(2,Instant.now(),state())));
  current=false;assertEquals(false,radar.view("a","g1").get("fresh"));
  assertThrows(RuntimeException.class,()->radar.accept("g1","session",envelope(1,Instant.now(),state())));
 }
 @Test void rejectsMalformedAndStale(){
  var s=new HashMap<>(state());s.put("count",0);
  assertThrows(RuntimeException.class,()->RadarSocket.validate(json.valueToTree(s)));
  s.put("count",1);s.put("age_ms",1501);assertThrows(RuntimeException.class,()->RadarSocket.validate(json.valueToTree(s)));
  assertThrows(RuntimeException.class,()->radar.accept("g1","session",envelope(1,Instant.now().minusSeconds(5),state())));
  assertEquals(false,RadarSocket.validate(json.valueToTree(Map.of("available",false,"reason","timeout"))).get("available"));
 }
 @Test void originChecks(){
  assertTrue(RadarSocket.sameOrigin(URI.create("https://example.test"),URI.create("wss://example.test/ws/operator/radar/a")));
  assertFalse(RadarSocket.sameOrigin(URI.create("https://other.test"),URI.create("wss://example.test/ws/operator/radar/a")));
  assertFalse(RadarSocket.sameOrigin(null,URI.create("wss://example.test/ws/operator/radar/a")));
 }
 WebSocketSession socket(String id,String user,String rail,List<String> events){
  var attrs=new HashMap<String,Object>();var headers=new HttpHeaders();headers.setOrigin("https://example.test");var open=new boolean[]{true};
  return (WebSocketSession)Proxy.newProxyInstance(getClass().getClassLoader(),new Class[]{WebSocketSession.class},(p,m,a)->switch(m.getName()){
   case "getId"->id;case "getPrincipal"->(Principal)()->user;case "getUri"->URI.create("wss://example.test/ws/operator/radar/"+rail);
   case "getHandshakeHeaders"->headers;case "getAttributes"->attrs;case "isOpen"->open[0];
   case "close"->{open[0]=false;yield null;}case "sendMessage"->{events.add(((TextMessage)a[0]).getPayload());yield null;}
   default->null;
  });
 }
 @Test void subscriptionPermissionAndSharedDemand()throws Exception{
  var e=new ArrayList<String>();var a=socket("one","site1","a",e);var b=socket("two","site1","a",e);
  radar.afterConnectionEstablished(a);radar.afterConnectionEstablished(b);
  assertTrue(a.isOpen());assertTrue(b.isOpen());
  assertTrue(sent.get(sent.size()-1).contains("\"rails\":[1]"));
  var foreign=socket("foreign","site1","b",e);radar.afterConnectionEstablished(foreign);assertFalse(foreign.isOpen());
  radar.accept("g1","session",envelope(1,Instant.now(),state()));int before=e.size();radar.push();assertEquals(before+2,e.size());radar.push();assertEquals(before+2,e.size());
  radar.afterConnectionClosed(a,CloseStatus.NORMAL);radar.afterConnectionClosed(b,CloseStatus.NORMAL);radar.refresh();
  assertTrue(sent.get(sent.size()-1).contains("\"rails\":[]"));
 }
}
