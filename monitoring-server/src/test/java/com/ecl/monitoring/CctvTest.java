package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import java.net.*;
import java.net.http.*;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.*;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.*;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
 "portal.bootstrap-password=integration-test-password","spring.datasource.url=jdbc:h2:mem:cctv-test;DB_CLOSE_DELAY=-1",
 "monitoring.admin-token=admin-012345678901234567890123456789","monitoring.analytics-token=analytics-012345678901234567890123456789",
 "monitoring.gateways[0].id=gateway-01","monitoring.gateways[0].token=gateway-012345678901234567890123456789"})
class CctvTest {
 @Value("${local.server.port}")int port;
 @Autowired Cctv cctv;@Autowired Registry registry;@Autowired Accounts accounts;@Autowired JdbcTemplate db;
 final JsonMapper json=JsonMapper.builder().build();final String control="a".repeat(43),publish="b".repeat(43),analysis="c".repeat(43);
 String url(String path){return "http://127.0.0.1:"+port+path;}
 HttpResponse<String> request(HttpClient http,String path,String method,Object body,Map<String,String> headers)throws Exception{
  var b=HttpRequest.newBuilder(URI.create(url(path)));headers.forEach(b::header);if(body!=null)b.header("Content-Type","application/json");
  return http.send(b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());
 }
 @Test void authenticatedCameraDemandMediaAndAnalysisReachOnlyRegisteredRail()throws Exception{
  String rail=registry.ensureRail("gateway-01",1);
  if(db.queryForList("SELECT id FROM cameras WHERE id='cctv01'").isEmpty())registry.camera("admin","cctv01",rail,"");
  var browser=HttpClient.newBuilder().cookieHandler(new CookieManager(null,CookiePolicy.ACCEPT_ALL)).build();
  var csrf=json.readTree(request(browser,"/api/auth/csrf","GET",null,Map.of()).body());
  var login=browser.send(HttpRequest.newBuilder(URI.create(url("/api/auth/login"))).header(csrf.path("header").asText(),csrf.path("token").asText()).header("Content-Type","application/x-www-form-urlencoded").POST(HttpRequest.BodyPublishers.ofString("username=admin&password=integration-test-password")).build(),HttpResponse.BodyHandlers.ofString());assertEquals(200,login.statusCode());
  csrf=json.readTree(request(browser,"/api/auth/csrf","GET",null,Map.of()).body());var headers=Map.of(csrf.path("header").asText(),csrf.path("token").asText());
  assertEquals(200,request(browser,"/api/portal/admin/cctv/cctv01","PUT",Map.of("control_token",control,"publish_token",publish,"analysis_token",analysis),headers).statusCode());
  assertFalse(cctv.enabled("cctv01"));
  assertEquals(200,request(browser,"/api/portal/cctv/cctv01/enabled","PUT",Map.of("enabled",true),headers).statusCode());
  assertFalse(cctv.wanted("cctv01"));
  var nativeClient=HttpClient.newHttpClient();
  assertEquals(401,request(nativeClient,"/api/cctv/analysis/cctv01/state","GET",null,Map.of("Authorization","Bearer "+control)).statusCode());
  assertEquals(401,request(nativeClient,"/api/cctv/analysis/foreign/state","GET",null,Map.of("Authorization","Bearer "+analysis)).statusCode());
  var messages=new LinkedBlockingQueue<String>();var device=socket(nativeClient,"/ws/cameras/cctv01",control,messages);
  try{
   var initial=json.readTree(messages.poll(3,TimeUnit.SECONDS));assertEquals("desired",initial.path("type").asText());assertFalse(initial.path("stream").asBoolean());
   var viewResponse=request(browser,"/api/portal/cctv/cctv01/view","POST",Collections.singletonMap("lease",null),headers);assertEquals(200,viewResponse.statusCode(),viewResponse.body());var view=json.readTree(viewResponse.body());
   assertTrue(cctv.wanted("cctv01"));var desired=json.readTree(messages.poll(3,TimeUnit.SECONDS));assertTrue(desired.path("stream").asBoolean());assertEquals(15,desired.path("lease_seconds").asInt());
   assertEquals(200,media(nativeClient,"publish","cctv01_raw","srt",publish).statusCode());
   assertEquals(401,media(nativeClient,"publish","other_raw","srt",publish).statusCode());
   assertEquals(401,media(nativeClient,"read","cctv01_raw","webrtc",publish).statusCode());
   assertEquals(200,media(nativeClient,"read","cctv01_raw","webrtc",view.path("token").asText()).statusCode());
   var anonymous=request(nativeClient,"/api/portal/cctv/cctv01","GET",null,Map.of());assertEquals(401,anonymous.statusCode());
   String outsider=(String)accounts.create("outsider","outsider","integration-test-password",false).get("id");
   assertThrows(Exception.class,()->cctv.view("outsider","session","cctv01",null));
   assertThrows(Exception.class,()->cctv.enable("outsider","cctv01",true));
   // Confirmed CCTV mode keeps analysis streaming with no browser lease.
   db.update("UPDATE rails SET snapshot=?,seen_at=? WHERE id=?","{\"detection\":\"cctv\"}",System.currentTimeMillis(),rail);
   request(browser,"/api/portal/cctv/view/"+view.path("lease").asText(),"DELETE",null,headers);
   assertTrue(cctv.analysis("cctv01"));assertTrue(cctv.wanted("cctv01"));
   assertEquals(401,media(nativeClient,"read","cctv01_raw","webrtc",view.path("token").asText()).statusCode());
   assertEquals(200,media(nativeClient,"read","cctv01_raw","rtsp",analysis).statusCode());
   var gatewayMessages=new LinkedBlockingQueue<String>();var gateway=socket(nativeClient,"/ws/gateways/gateway-01","gateway-012345678901234567890123456789",gatewayMessages);
   try{
    assertEquals("welcome",json.readTree(gatewayMessages.poll(3,TimeUnit.SECONDS)).path("type").asText());
    var event=Map.of("camera_id","cctv01","event_id",UUID.randomUUID().toString(),"type","enter","observed_at",Instant.now().toString());
    var auth=Map.of("Authorization","Bearer "+analysis);
    assertEquals(200,request(nativeClient,"/api/cctv/analysis/cctv01/events","POST",event,auth).statusCode());
    var delivered=json.readTree(gatewayMessages.poll(3,TimeUnit.SECONDS));assertEquals("cctv.enter",delivered.path("type").asText());assertEquals(1,delivered.path("railing_id").asInt());
    assertEquals(200,request(nativeClient,"/api/cctv/analysis/cctv01/events","POST",event,auth).statusCode());assertNull(gatewayMessages.poll(100,TimeUnit.MILLISECONDS));
    var foreign=new HashMap<String,Object>(event);foreign.put("camera_id","foreign");assertEquals(400,request(nativeClient,"/api/cctv/analysis/cctv01/events","POST",foreign,auth).statusCode());
    cctv.enable("admin","cctv01",false);assertFalse(cctv.wanted("cctv01"));
    assertEquals(400,request(nativeClient,"/api/cctv/analysis/cctv01/events","POST",event,auth).statusCode());
    assertEquals(401,media(nativeClient,"publish","cctv01_raw","srt",publish).statusCode());
   }finally{gateway.sendClose(1000,"done").join();}
  }finally{device.sendClose(1000,"done").join();}
 }
 HttpResponse<String> media(HttpClient h,String action,String path,String protocol,String token)throws Exception{return request(h,"/api/cctv/media-auth","POST",Map.of("action",action,"path",path,"protocol",protocol,"password",token),Map.of());}
 WebSocket socket(HttpClient h,String path,String token,BlockingQueue<String> messages){return h.newWebSocketBuilder().header("Authorization","Bearer "+token).buildAsync(URI.create("ws://127.0.0.1:"+port+path),new WebSocket.Listener(){StringBuilder b=new StringBuilder();public void onOpen(WebSocket s){s.request(1);}public CompletionStage<?> onText(WebSocket s,CharSequence t,boolean last){b.append(t);if(last){messages.add(b.toString());b.setLength(0);}s.request(1);return null;}}).join();}
}
