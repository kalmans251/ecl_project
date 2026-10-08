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
 "portal.codec-token=codec-012345678901234567890123456789","portal.bootstrap-password=integration-test-password","spring.datasource.url=jdbc:h2:mem:portal-test;DB_CLOSE_DELAY=-1",
 "monitoring.admin-token=admin-012345678901234567890123456789","monitoring.analytics-token=analytics-012345678901234567890123456789",
 "monitoring.gateways[0].id=gateway-01","monitoring.gateways[0].token=gateway-012345678901234567890123456789"})
class PortalTest {
 @Value("${local.server.port}")int port;@Autowired Accounts accounts;@Autowired Registry registry;@Autowired Commands commands;@Autowired JdbcTemplate db;@Autowired Telemetry telemetry;@Autowired Voice voice;
 final JsonMapper json=JsonMapper.builder().build();
 class Browser {
  final HttpClient http=HttpClient.newBuilder().cookieHandler(new CookieManager(null,CookiePolicy.ACCEPT_ALL)).build();String token,header;
  HttpResponse<String> request(String path,String method,Object body,boolean csrf)throws Exception{var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));if(csrf)b.header(header,token);if(body!=null)b.header("Content-Type","application/json");return http.send(b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());}
  Browser(String username)throws Exception{var c=json.readTree(request("/api/auth/csrf","GET",null,false).body());token=c.path("token").asText();header=c.path("header").asText();var r=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/auth/login")).header(header,token).header("Content-Type","application/x-www-form-urlencoded").POST(HttpRequest.BodyPublishers.ofString("username="+username+"&password=integration-test-password")).build(),HttpResponse.BodyHandlers.ofString());assertEquals(200,r.statusCode(),r.body());c=json.readTree(request("/api/auth/csrf","GET",null,false).body());token=c.path("token").asText();header=c.path("header").asText();}
 }
 String newUser(String prefix,String role){String name=prefix+UUID.randomUUID().toString().substring(0,8);String id=(String)accounts.create(name,name,"integration-test-password",false).get("id");accounts.membership("admin",id,"site-01",role);return name;}
 Map<String,Object> command(String rail,String operation,String value){var b=new HashMap<String,Object>();b.put("request_id",UUID.randomUUID().toString());b.put("rail_ids",List.of(rail));b.put("operation",operation);b.put("value",value);return b;}
 String rail(){return registry.ensureRail("gateway-01",1);}
 @Test void sessionCsrfAndSiteIsolation()throws Exception{
  var anonymous=HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/portal/me")).GET().build(),HttpResponse.BodyHandlers.ofString());assertEquals(401,anonymous.statusCode());
  String viewer=newUser("viewer","VIEWER");var b=new Browser(viewer);assertEquals(200,b.request("/api/portal/sites/site-01/state","GET",null,false).statusCode());assertEquals(403,b.request("/api/portal/sites/foreign/state","GET",null,false).statusCode());assertEquals(403,b.request("/api/portal/commands","POST",command(rail(),"volume","20"),true).statusCode());assertEquals(403,b.request("/api/portal/admin/users","GET",null,false).statusCode());assertEquals(403,b.request("/api/portal/commands","POST",command(rail(),"volume","20"),false).statusCode());
  String operator=newUser("operator","OPERATOR");var op=new Browser(operator);assertEquals(403,op.request("/api/portal/sites/foreign/sms","POST",Map.of("request_id",UUID.randomUUID(),"label","경찰서","rail_id",rail()),true).statusCode());
  assertEquals(400,op.request("/api/portal/commands","POST",command(rail(),"power","auto"),true).statusCode());
  accounts.membership("admin",(String)accounts.user(operator).get("ID"),"site-01","NONE");assertEquals(403,op.request("/api/portal/sites/site-01/state","GET",null,false).statusCode());
 }
 class Device implements AutoCloseable {
  final BlockingQueue<String> messages=new LinkedBlockingQueue<>();final WebSocket ws;
  Device()throws Exception{ws=HttpClient.newHttpClient().newWebSocketBuilder().header("Authorization","Bearer gateway-012345678901234567890123456789").buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/gateways/gateway-01"),new WebSocket.Listener(){StringBuilder data=new StringBuilder();public void onOpen(WebSocket s){s.request(1);}public CompletionStage<?> onText(WebSocket s,CharSequence t,boolean last){data.append(t);if(last){messages.add(data.toString());data.setLength(0);}s.request(1);return null;}}).join();assertEquals("welcome",json.readTree(messages.poll(3,TimeUnit.SECONDS)).path("type").asText());}
  String next(){try{return messages.poll(3,TimeUnit.SECONDS);}catch(Exception e){throw new RuntimeException(e);}}
  void ack(String id,String status)throws Exception{ws.sendText(json.writeValueAsString(Map.of("version",1,"type","ack","message_id",id,"status",status)),true).join();long until=System.nanoTime()+2_000_000_000L;while(System.nanoTime()<until){if(status.equals(db.queryForObject("SELECT status FROM commands WHERE id=?",String.class,id)))return;Thread.sleep(10);}fail("ACK not received");}
  public void close(){ws.sendClose(1000,"done").join();}
 }
 @Test void commandDedupQueueAndCallOwnership()throws Exception{
  String owner=newUser("owner","OPERATOR"),other=newUser("other","OPERATOR");var b=new Browser(owner);var o=new Browser(other);String rail=rail();
  try(var device=new Device()){
   var body=command(rail,"volume","20");var response=b.request("/api/portal/commands","POST",body,true);assertEquals(200,response.statusCode(),response.body());String id=json.readTree(device.next()).path("message_id").asText();assertFalse(json.readTree(response.body()).get(0).path("device_application_confirmed").asBoolean());
   assertEquals(id,json.readTree(b.request("/api/portal/commands","POST",body,true).body()).get(0).path("id").asText());assertNull(device.messages.poll(100,TimeUnit.MILLISECONDS));body.put("value","30");assertEquals(409,b.request("/api/portal/commands","POST",body,true).statusCode());
   assertFalse(commands.ack("wrong-gateway",id,"APPLIED")); // cannot confirm another gateway
   device.ack(id,"APPLIED");assertTrue(commands.list(owner,"site-01").stream().filter(c->c.get("id").equals(id)).findFirst().get().get("device_application_confirmed").equals(true));
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());var start=json.readTree(device.next());assertTrue(start.has("call_id"));assertEquals(409,o.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());device.ack(start.path("message_id").asText(),"APPLIED");
   String callId=start.path("call_id").asText();
   CompletableFuture<Integer> rejected=new CompletableFuture<>();
   var wrongVoice=o.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}public CompletionStage<?> onClose(WebSocket w,int status,String reason){rejected.complete(status);return null;}}).join();
   assertEquals(1008,rejected.get(3,TimeUnit.SECONDS));
   CompletableFuture<Integer> ownerClosed=new CompletableFuture<>();
   var ownerVoice=b.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}public CompletionStage<?> onClose(WebSocket w,int status,String reason){ownerClosed.complete(status);return null;}}).join();
   assertFalse(ownerClosed.isDone());
   assertThrows(CompletionException.class,()->b.http.newWebSocketBuilder().header("Origin","https://attacker.example").buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){}).join());
   ownerVoice.sendClose(1000,"done").join();
   assertEquals(403,o.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());device.ack(json.readTree(device.next()).path("message_id").asText(),"APPLIED");assertEquals("CONTROL_TX",db.queryForObject("SELECT direction FROM calls WHERE gateway_id='gateway-01'",String.class));
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.end",null),true).statusCode());device.ack(json.readTree(device.next()).path("message_id").asText(),"APPLIED");assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
  }
 }
 @Test void voiceEnvelopeValidation()throws Exception{
  var v=new HashMap<String,Object>(Map.of("version",1,"type","voice","call_id",UUID.randomUUID().toString(),"railing_id",1,"direction","FIELD_TX","sequence",0,"codec2",Base64.getEncoder().encodeToString(new byte[48])));
  assertDoesNotThrow(()->voice.receive("gateway-01",json.valueToTree(v)));
  v.put("extra",true);assertThrows(Exception.class,()->voice.receive("gateway-01",json.valueToTree(v)));
 }
 @Test void telemetryIsBoundAndDoesNotInventState(){
  String id=rail();var data=Map.of("version",1,"type","telemetry","railing_id",1,"observed_at",Instant.now().toString(),"state",Map.of("volume",13,"left_watt",1.5,"right_watt",2.5,"battery_percent",70,"emergency",false,"radar",List.of(Map.of("x",.3,"y",2.0))));
  telemetry.accept("gateway-01",json.valueToTree(data));assertTrue(db.queryForObject("SELECT snapshot FROM rails WHERE id=?",String.class,id).contains("13"));
  assertThrows(Exception.class,()->telemetry.accept("wrong-gateway",json.valueToTree(data)));
  var bad=new HashMap<String,Object>(data);bad.put("state",Map.of("volume",101));bad.put("observed_at",Instant.now().plusMillis(10).toString());assertThrows(Exception.class,()->telemetry.accept("gateway-01",json.valueToTree(bad)));
 }
 @Test void scheduleContactsAndSmsRequireOperator()throws Exception{
  String operator=newUser("schedule","OPERATOR");var b=new Browser(operator);String rail=rail();
  assertEquals(400,b.request("/api/portal/rails/"+rail+"/schedule","PUT",Map.of("start_time","12:00","end_time","12:00","enabled",true),true).statusCode());
  assertEquals(200,b.request("/api/portal/rails/"+rail+"/schedule","PUT",Map.of("start_time","01:00","end_time","13:00","enabled",true),true).statusCode());
  assertEquals(200,b.request("/api/portal/sites/site-01/contacts/"+URLEncoder.encode("경찰서",java.nio.charset.StandardCharsets.UTF_8),"PUT",Map.of("phone","01000000000"),true).statusCode());
  assertEquals(503,b.request("/api/portal/sites/site-01/sms","POST",Map.of("request_id",UUID.randomUUID(),"label","경찰서","rail_id",rail),true).statusCode());assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM sms_requests",Integer.class));
 }
}
