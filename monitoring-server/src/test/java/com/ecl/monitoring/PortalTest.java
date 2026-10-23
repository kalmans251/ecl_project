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
 static final com.sun.net.httpserver.HttpServer codecServer;
 static {
  try {
   codecServer=com.sun.net.httpserver.HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
   codecServer.createContext("/",exchange->{
    byte[] input=exchange.getRequestBody().readAllBytes();boolean encode=exchange.getRequestURI().getPath().startsWith("/encode/");
    if(!"Bearer codec-012345678901234567890123456789".equals(exchange.getRequestHeaders().getFirst("Authorization")) || input.length!=(encode?2560:48)){exchange.sendResponseHeaders(400,-1);exchange.close();return;}
    byte[] output=new byte[encode?48:2560];Arrays.fill(output,(byte)7);exchange.sendResponseHeaders(200,output.length);exchange.getResponseBody().write(output);exchange.close();
   });codecServer.start();
  }catch(Exception e){throw new ExceptionInInitializerError(e);}
 }
 @org.springframework.test.context.DynamicPropertySource static void codecAddress(org.springframework.test.context.DynamicPropertyRegistry properties){properties.add("portal.codec-url",()->"http://127.0.0.1:"+codecServer.getAddress().getPort());}
 @org.junit.jupiter.api.AfterAll static void stopCodec(){codecServer.stop(0);}
 final JsonMapper json=JsonMapper.builder().build();
 class Browser {
  final HttpClient http=HttpClient.newBuilder().cookieHandler(new CookieManager(null,CookiePolicy.ACCEPT_ALL)).build();String token,header;
  HttpResponse<String> request(String path,String method,Object body,boolean csrf)throws Exception{var b=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));if(csrf)b.header(header,token);if(body!=null)b.header("Content-Type","application/json");return http.send(b.method(method,body==null?HttpRequest.BodyPublishers.noBody():HttpRequest.BodyPublishers.ofString(json.writeValueAsString(body))).build(),HttpResponse.BodyHandlers.ofString());}
  Browser(String username)throws Exception{var c=json.readTree(request("/api/auth/csrf","GET",null,false).body());token=c.path("token").asText();header=c.path("header").asText();var r=http.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/api/auth/login")).header(header,token).header("Content-Type","application/x-www-form-urlencoded").POST(HttpRequest.BodyPublishers.ofString("username="+username+"&password=integration-test-password")).build(),HttpResponse.BodyHandlers.ofString());assertEquals(200,r.statusCode(),r.body());c=json.readTree(request("/api/auth/csrf","GET",null,false).body());token=c.path("token").asText();header=c.path("header").asText();}
 }
 String newUser(String prefix,String role){String name=prefix+UUID.randomUUID().toString().substring(0,8);String id=(String)accounts.create(name,name,"integration-test-password",false).get("id");accounts.membership("admin",id,"site-01",role);return name;}
 Map<String,Object> command(String rail,String operation,String value){var b=new HashMap<String,Object>();b.put("request_id",UUID.randomUUID().toString());b.put("rail_ids",List.of(rail));b.put("operation",operation);b.put("value",value);return b;}
 String rail(){return registry.ensureRail("gateway-01",1);}
 @Test void functionTestPageRequiresLoginAndReturnsToTestPage()throws Exception{
  var response=HttpClient.newHttpClient().send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+"/function-test.html")).GET().build(),HttpResponse.BodyHandlers.ofString());
  assertEquals(302,response.statusCode());assertTrue(response.headers().firstValue("location").orElse("").endsWith("/login.html?next=function-test"));
  var browser=new Browser("admin");var page=browser.request("/function-test.html","GET",null,false);
  assertEquals(200,page.statusCode());assertTrue(page.body().contains("/function-test.js"));
  assertEquals(200,browser.request("/function-test.js","GET",null,false).statusCode());
 }
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
  void callAck(tools.jackson.databind.JsonNode message)throws Exception{
   String id=message.path("message_id").asText(),op=message.path("operation").asText();
   var data=Map.of("call_id",message.path("call_id").asText(),"railing_id",1,"session_id",123,"epoch",id,"direction",op.equals("call.end")?"IDLE":op.equals("ptt.on")?"CONTROL_TX":"FIELD_TX");
   assertThrows(RuntimeException.class,()->commands.ack("gateway-01",id,"APPLIED"));
   var wrong=new HashMap<String,Object>(data);wrong.put("call_id",UUID.randomUUID().toString());
   assertThrows(RuntimeException.class,()->commands.callResult("gateway-01",json.valueToTree(Map.of("version",1,"type","call_result","message_id",id,"status","APPLIED","data",wrong))));
   ws.sendText(json.writeValueAsString(Map.of("version",1,"type","call_result","message_id",id,"status","APPLIED","data",data)),true).join();
   long until=System.nanoTime()+2_000_000_000L;while(System.nanoTime()<until){if("APPLIED".equals(db.queryForObject("SELECT status FROM commands WHERE id=?",String.class,id)))return;Thread.sleep(10);}fail("Call result not received");
  }
  public void close(){ws.sendClose(1000,"done").join();}
 }
 @Test void commandDedupQueueAndCallOwnership()throws Exception{
  String owner=newUser("owner","OPERATOR"),other=newUser("other","OPERATOR");var b=new Browser(owner);var o=new Browser(other);String rail=rail();
  try(var device=new Device()){
   var body=command(rail,"volume","20");var response=b.request("/api/portal/commands","POST",body,true);assertEquals(200,response.statusCode(),response.body());String id=json.readTree(device.next()).path("message_id").asText();assertFalse(json.readTree(response.body()).get(0).path("device_application_confirmed").asBoolean());
   assertEquals(id,json.readTree(b.request("/api/portal/commands","POST",body,true).body()).get(0).path("id").asText());assertNull(device.messages.poll(100,TimeUnit.MILLISECONDS));body.put("value","30");assertEquals(409,b.request("/api/portal/commands","POST",body,true).statusCode());
   assertFalse(commands.ack("wrong-gateway",id,"APPLIED")); // cannot confirm another gateway
   assertThrows(RuntimeException.class,()->commands.ack("gateway-01",id,"APPLIED"));
   var applied=Map.of("railing_id",1,"operation","volume","value","20","device_application_confirmed",true,
       "steps",List.of(Map.of("node",3,"service",2,"command",34,"status",0,"data","14")));
   device.ws.sendText(json.writeValueAsString(Map.of("version",1,"type","control_result","message_id",id,"status","APPLIED","data",applied)),true).join();
   waitMusic(b,id,"APPLIED");assertTrue(commands.list(owner,"site-01").stream().filter(c->c.get("id").equals(id)).findFirst().get().get("device_application_confirmed").equals(true));
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());var start=json.readTree(device.next());assertTrue(start.has("call_id"));assertEquals(409,o.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());device.callAck(start);
   String callId=start.path("call_id").asText();
   CompletableFuture<Integer> rejected=new CompletableFuture<>();
   var wrongVoice=o.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}public CompletionStage<?> onClose(WebSocket w,int status,String reason){rejected.complete(status);return null;}}).join();
   assertEquals(1008,rejected.get(3,TimeUnit.SECONDS));
   CompletableFuture<Integer> ownerClosed=new CompletableFuture<>();BlockingQueue<byte[]> pcmReceived=new LinkedBlockingQueue<>();
   var ownerVoice=b.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}public CompletionStage<?> onClose(WebSocket w,int status,String reason){ownerClosed.complete(status);return null;}public CompletionStage<?> onBinary(WebSocket w,java.nio.ByteBuffer data,boolean last){byte[] bytes=new byte[data.remaining()];data.get(bytes);pcmReceived.add(bytes);w.request(1);return null;}}).join();
   assertFalse(ownerClosed.isDone());
   var field=new HashMap<String,Object>(Map.of("version",1,"type","voice","call_id",callId,"railing_id",1,"direction","FIELD_TX","epoch",start.path("message_id").asText(),"sequence",0,"codec2",Base64.getEncoder().encodeToString(new byte[48])));
   voice.receive("gateway-01",json.valueToTree(field));var pcm=pcmReceived.poll(3,TimeUnit.SECONDS);assertNotNull(pcm);assertEquals(2560,pcm.length);assertEquals(7,pcm[0]);
   voice.receive("gateway-01",json.valueToTree(field));assertNull(pcmReceived.poll(100,TimeUnit.MILLISECONDS));
   field.put("sequence",1);field.put("epoch",UUID.randomUUID().toString());voice.receive("gateway-01",json.valueToTree(field));assertNull(pcmReceived.poll(100,TimeUnit.MILLISECONDS));
   assertThrows(CompletionException.class,()->b.http.newWebSocketBuilder().header("Origin","https://attacker.example").buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){}).join());
   ownerVoice.sendClose(1000,"done").join();
   assertEquals(403,o.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());var ptt=json.readTree(device.next());device.callAck(ptt);assertEquals("CONTROL_TX",db.queryForObject("SELECT direction FROM calls WHERE gateway_id='gateway-01'",String.class));
   var talk=b.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}}).join();
   talk.sendBinary(java.nio.ByteBuffer.wrap(new byte[2560]),true).join();var sent=json.readTree(device.next());assertEquals("voice",sent.path("type").asText());assertEquals(ptt.path("message_id").asText(),sent.path("epoch").asText());assertEquals(callId,sent.path("call_id").asText());assertEquals(48,Base64.getDecoder().decode(sent.path("codec2").asText()).length);talk.sendClose(1000,"done").join();
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.end",null),true).statusCode());device.callAck(json.readTree(device.next()));assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
  }
 }
 @Test void voiceEnvelopeValidation()throws Exception{
  var v=new HashMap<String,Object>(Map.of("version",1,"type","voice","call_id",UUID.randomUUID().toString(),"railing_id",1,"direction","FIELD_TX","epoch",UUID.randomUUID().toString(),"sequence",0,"codec2",Base64.getEncoder().encodeToString(new byte[48])));
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
 @Test void musicSocketUpdatesAuthorizedPortalWithoutReplacingOtherState()throws Exception{
  String rail=rail();telemetry.accept("gateway-01",json.valueToTree(Map.of("version",1,"type","telemetry","railing_id",1,"observed_at",Instant.now().toString(),"state",Map.of("volume",20))));
  var browser=new Browser(newUser("music-viewer","VIEWER"));
  try(var device=new Device()){
   device.ws.sendText(json.writeValueAsString(Map.of("version",1,"type","music_state","railing_id",1,"observed_at",Instant.now().toString(),"fresh_ms",10000,"state",Map.of("available",true,"state","playing","filename","actual.mp3","position_ms",12345))),true).join();
   long until=System.nanoTime()+3_000_000_000L;
   while(System.nanoTime()<until){
    var response=browser.request("/api/portal/sites/site-01/state","GET",null,false);
    assertEquals(200,response.statusCode());
    for(var r:json.readTree(response.body()).path("rails"))if(r.path("id").asText().equals(rail) && r.path("music_status").path("available").asBoolean()){
     assertEquals("actual.mp3",r.path("music_status").path("filename").asText());
     assertEquals(12345,r.path("music_status").path("position_ms").asLong());
     assertEquals(20,r.path("reported").path("volume").asInt());return;
    }
    Thread.sleep(20);
   }
   fail("Music state did not reach portal");
  }
 }
 @Test void catalogAndSelectedPlaybackUseDurableCorrelatedResults()throws Exception{
  String rail=rail(),owner=newUser("music-owner","OPERATOR");var browser=new Browser(owner);
  try(var device=new Device()){
   var request=command(rail,"music.list","default:0");
   var posted=browser.request("/api/portal/commands","POST",request,true);assertEquals(200,posted.statusCode(),posted.body());
   var outgoing=json.readTree(device.next());String id=outgoing.path("message_id").asText();
   var data=Map.of("railing_id",1,"catalog_version",5,"group","default","offset",0,"total",1,"tracks",List.of(Map.of("group","default","index",0,"filename","a.mp3")));
   assertThrows(RuntimeException.class,()->commands.musicResult("foreign",json.valueToTree(Map.of("version",1,"type","music_result","message_id",id,"status","COMPLETED","data",data))));
   device.ws.sendText(json.writeValueAsString(Map.of("version",1,"type","music_result","message_id",id,"status","COMPLETED","data",data)),true).join();
   waitMusic(browser,id,"COMPLETED");
   assertEquals("a.mp3",json.readTree(browser.request("/api/portal/commands/"+id,"GET",null,false).body()).path("result").path("tracks").get(0).path("filename").asText());
   assertEquals(200,browser.request("/api/portal/commands","POST",request,true).statusCode());assertNull(device.messages.poll(100,TimeUnit.MILLISECONDS));
   posted=browser.request("/api/portal/commands","POST",command(rail,"music.play","5:default:0"),true);assertEquals(200,posted.statusCode());
   outgoing=json.readTree(device.next());String playId=outgoing.path("message_id").asText();
   assertThrows(RuntimeException.class,()->commands.ack("gateway-01",playId,"APPLIED"));
   var played=Map.of("railing_id",1,"catalog_version",5,"group","default","index",0,"filename","a.mp3","state","playing","device_application_confirmed",true);
   device.ws.sendText(json.writeValueAsString(Map.of("version",1,"type","music_result","message_id",playId,"status","APPLIED","data",played)),true).join();
   waitMusic(browser,playId,"APPLIED");
   assertTrue(commands.find(owner,playId).get("device_application_confirmed").equals(true));
   accounts.membership("admin",(String)accounts.user(owner).get("ID"),"site-01","NONE");
   assertEquals(403,browser.request("/api/portal/commands/"+id,"GET",null,false).statusCode());
  }
 }
 void waitMusic(Browser browser,String id,String expected)throws Exception{
  long until=System.nanoTime()+3_000_000_000L;
  while(System.nanoTime()<until){var response=browser.request("/api/portal/commands/"+id,"GET",null,false);if(json.readTree(response.body()).path("status").asText().equals(expected))return;Thread.sleep(20);}
  fail("Music result not confirmed");
 }
}
