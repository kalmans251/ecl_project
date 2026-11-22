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
class DetectionSocketTest {
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
 final DetectionSocket detection=new DetectionSocket(registry,accounts,gateways);
 WebSocketSession socket(String id,String user,String rail,List<String> events){
  var attrs=new HashMap<String,Object>();var headers=new HttpHeaders();headers.setOrigin("https://example.test");var open=new boolean[]{true};
  return (WebSocketSession)Proxy.newProxyInstance(getClass().getClassLoader(),new Class[]{WebSocketSession.class},(p,m,a)->switch(m.getName()){
   case "getId"->id;case "getPrincipal"->(Principal)()->user;case "getUri"->URI.create("wss://example.test/ws/operator/detection/"+rail);
   case "getHandshakeHeaders"->headers;case "getAttributes"->attrs;case "isOpen"->open[0];
   case "close"->{open[0]=false;yield null;}case "sendMessage"->{events.add(((TextMessage)a[0]).getPayload());yield null;}
   default->null;
  });
 }

 tools.jackson.databind.JsonNode envelope(String rail,long count,int source,Instant time){return json.valueToTree(Map.of("version",1,"type","detection_state","railing_id",Integer.parseInt(rail),"observed_at",time.toString(),"source",source,"count",count));}
 @Test void pushesLatestAuthoritativeCountAndChecksPermissions()throws Exception{
  var events=new ArrayList<String>();var one=socket("one","site1","a",events);var denied=socket("denied","site1","b",events);
  detection.afterConnectionEstablished(one);detection.afterConnectionEstablished(denied);
  assertTrue(one.isOpen());assertFalse(denied.isOpen());
  Instant at=Instant.now().minusMillis(100);
  detection.accept("g1","session",envelope("1",4,0,at));detection.push();assertEquals(1,events.size());
  assertTrue(events.get(0).contains("\"count\":4"));assertTrue(events.get(0).contains("\"rail_id\":\"a\""));
  detection.push();assertEquals(1,events.size());
  detection.accept("g1","session",envelope("1",2,0,at.minusMillis(1)));detection.push();assertEquals(1,events.size());
  detection.accept("g1","session",envelope("1",0,1,at.plusMillis(1)));detection.push();assertEquals(2,events.size());assertTrue(events.get(1).contains("\"count\":0"));
  current=false;detection.push();assertEquals(2,events.size());
 }
 @Test void rejectsBadRangesStaleMessagesAndForeignRails(){
  assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("1",-1,0,Instant.now())));
  assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("1",0x100000000L,0,Instant.now())));
  assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("1",1,2,Instant.now())));
  assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("1",1,0,Instant.now().minusSeconds(6))));
  assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("2",1,0,Instant.now())));
  current=false;assertThrows(RuntimeException.class,()->detection.accept("g1","session",envelope("1",1,0,Instant.now())));
 }
 @Test void gatewayCountsCannotLeakToAnotherSite()throws Exception{
  var events=new ArrayList<String>();var one=socket("one","site1","a",events);detection.afterConnectionEstablished(one);
  detection.accept("g2","session",envelope("1",9,1,Instant.now()));detection.push();assertTrue(events.isEmpty());
 }
}
