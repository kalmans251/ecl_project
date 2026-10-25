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
 "portal.bootstrap-password=integration-test-password","spring.datasource.url=jdbc:h2:mem:portal-test;DB_CLOSE_DELAY=-1",
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
 void awaitVoice(String callId,String epoch)throws Exception{
  long until=System.nanoTime()+3_000_000_000L;
  while(System.nanoTime()<until){
   var peers=(Map<?,?>)org.springframework.test.util.ReflectionTestUtils.getField(voice,"peers");var peer=peers.get(callId);
   if(peer!=null && epoch.equals(org.springframework.test.util.ReflectionTestUtils.getField(peer,"epoch")))return;
   Thread.sleep(10);
  }fail("Server voice peer not registered");
 }
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
  final BlockingQueue<String> messages=new LinkedBlockingQueue<>();final WebSocket ws;final String gateway;
  Device()throws Exception{this("gateway-01","gateway-012345678901234567890123456789");}
  Device(String gateway,String token)throws Exception{this.gateway=gateway;ws=HttpClient.newHttpClient().newWebSocketBuilder().header("Authorization","Bearer "+token).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/gateways/"+gateway),new WebSocket.Listener(){StringBuilder data=new StringBuilder();public void onOpen(WebSocket s){s.request(1);}public CompletionStage<?> onText(WebSocket s,CharSequence t,boolean last){data.append(t);if(last){messages.add(data.toString());data.setLength(0);}s.request(1);return null;}}).join();assertEquals("welcome",json.readTree(messages.poll(3,TimeUnit.SECONDS)).path("type").asText());}
  String next(){try{return messages.poll(3,TimeUnit.SECONDS);}catch(Exception e){throw new RuntimeException(e);}}
  void ack(String id,String status)throws Exception{ws.sendText(json.writeValueAsString(Map.of("version",1,"type","ack","message_id",id,"status",status)),true).join();long until=System.nanoTime()+2_000_000_000L;while(System.nanoTime()<until){if(status.equals(db.queryForObject("SELECT status FROM commands WHERE id=?",String.class,id)))return;Thread.sleep(10);}fail("ACK not received");}
  void callAck(tools.jackson.databind.JsonNode message)throws Exception{
   String id=message.path("message_id").asText(),op=message.path("operation").asText();
   var data=Map.of("call_id",message.path("call_id").asText(),"railing_id",1,"session_id",123,"epoch",id,"direction",op.equals("call.end")?"IDLE":op.equals("ptt.on")?"CONTROL_TX":"FIELD_TX");
   assertThrows(RuntimeException.class,()->commands.ack(gateway,id,"APPLIED"));
   var wrong=new HashMap<String,Object>(data);wrong.put("call_id",UUID.randomUUID().toString());
   assertThrows(RuntimeException.class,()->commands.callResult(gateway,json.valueToTree(Map.of("version",1,"type","call_result","message_id",id,"status","APPLIED","data",wrong))));
   ws.sendText(json.writeValueAsString(Map.of("version",1,"type","call_result","message_id",id,"status","APPLIED","data",data)),true).join();
   long until=System.nanoTime()+2_000_000_000L;while(System.nanoTime()<until){if("APPLIED".equals(db.queryForObject("SELECT status FROM commands WHERE id=?",String.class,id)))return;Thread.sleep(10);}fail("Call result not received");
  }
  public void close(){ws.sendClose(1000,"done").join();}
 }
 @Test void rejectedStartReleasesReservationButUnknownKeepsHangup()throws Exception{
  var b=new Browser("admin");String rail=rail();
  try(var device=new Device()){
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());
   var start=json.readTree(device.next());
   var proof=Map.of("call_id",start.path("call_id").asText(),"railing_id",1,"epoch",start.path("message_id").asText());
   var reply=Map.of("version",1,"type","call_result","message_id",start.path("message_id").asText(),"status","NOT_STARTED","data",proof);
   var wrong=new HashMap<String,Object>(proof);wrong.put("epoch",UUID.randomUUID().toString());
   var invalid=new HashMap<String,Object>(reply);invalid.put("data",wrong);
   assertThrows(RuntimeException.class,()->commands.callResult("gateway-01",json.valueToTree(invalid)));
   assertEquals(1,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
   commands.callResult("gateway-01",json.valueToTree(reply));
   assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.start",null),true).statusCode());
   var next=json.readTree(device.next());
   var unknown=new HashMap<String,Object>();unknown.put("version",1);unknown.put("type","call_result");unknown.put("message_id",next.path("message_id").asText());unknown.put("status","UNKNOWN");unknown.put("data",null);
   commands.callResult("gateway-01",json.valueToTree(unknown));
   assertEquals("UNKNOWN",db.queryForObject("SELECT status FROM calls",String.class));
   assertEquals(409,b.request("/api/portal/commands","POST",command(rail,"volume","20"),true).statusCode());
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.end",null),true).statusCode());
   var end=json.readTree(device.next());assertTrue(end.path("recover").asBoolean());assertFalse(end.has("session_id"));
   assertEquals(1,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
   device.callAck(end);
   assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"query","p4"),true).statusCode());
   var query=json.readTree(device.next());device.ack(query.path("message_id").asText(),"FAILED");
  }
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
   var ownerVoice=b.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){public void onOpen(WebSocket w){w.request(1);}public CompletionStage<?> onClose(WebSocket w,int status,String reason){ownerClosed.complete(status);return null;}public CompletionStage<?> onText(WebSocket w,CharSequence text,boolean last){w.request(1);return null;}public CompletionStage<?> onBinary(WebSocket w,java.nio.ByteBuffer data,boolean last){byte[] bytes=new byte[data.remaining()];data.get(bytes);pcmReceived.add(bytes);w.request(1);return null;}}).join();
   assertTrue(voice.available(),"Browser Codec2 must be bundled");assertFalse(ownerClosed.isDone());ownerVoice.sendText(json.writeValueAsString(Map.of("type","bind","codec","codec2-2400-v1","epoch",start.path("message_id").asText(),"direction","FIELD_TX")),true).join();awaitVoice(callId,start.path("message_id").asText());
   var field=new HashMap<String,Object>(Map.of("version",1,"type","voice","call_id",callId,"railing_id",1,"direction","FIELD_TX","epoch",start.path("message_id").asText(),"sequence",0,"codec2",Base64.getEncoder().encodeToString(new byte[48])));
   voice.receive("gateway-01",json.valueToTree(field));var pcm=pcmReceived.poll(3,TimeUnit.SECONDS);assertNotNull(pcm);assertEquals(84,pcm.length);assertArrayEquals(new byte[48],Arrays.copyOfRange(pcm,36,84));assertEquals(start.path("message_id").asText(),new String(pcm,0,36,java.nio.charset.StandardCharsets.US_ASCII));
   voice.receive("gateway-01",json.valueToTree(field));assertNull(pcmReceived.poll(100,TimeUnit.MILLISECONDS));
   field.put("sequence",1);field.put("epoch",UUID.randomUUID().toString());voice.receive("gateway-01",json.valueToTree(field));assertNull(pcmReceived.poll(100,TimeUnit.MILLISECONDS));
   assertThrows(CompletionException.class,()->b.http.newWebSocketBuilder().header("Origin","https://attacker.example").buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+callId),new WebSocket.Listener(){}).join());
   assertEquals(403,o.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"ptt.on",null),true).statusCode());var ptt=json.readTree(device.next());
   voice.clean();assertFalse(ownerClosed.isDone(),"SWITCHING must preserve owner socket");
   device.callAck(ptt);assertEquals("CONTROL_TX",db.queryForObject("SELECT direction FROM calls WHERE gateway_id='gateway-01'",String.class));
   ownerVoice.sendText(json.writeValueAsString(Map.of("type","bind","codec","codec2-2400-v1","epoch",ptt.path("message_id").asText(),"direction","CONTROL_TX")),true).join();
   awaitVoice(callId,ptt.path("message_id").asText());
   // The previous epoch is rejected even on the same transport after rebind.
   ownerVoice.sendBinary(java.nio.ByteBuffer.allocate(84).put(start.path("message_id").asText().getBytes(java.nio.charset.StandardCharsets.US_ASCII)).put(new byte[48]).flip(),true).join();
   assertNull(device.messages.poll(100,TimeUnit.MILLISECONDS));
   ownerVoice.sendBinary(java.nio.ByteBuffer.allocate(84).put(ptt.path("message_id").asText().getBytes(java.nio.charset.StandardCharsets.US_ASCII)).put(new byte[48]).flip(),true).join();
   var sent=json.readTree(device.next());assertEquals("voice",sent.path("type").asText());assertEquals(ptt.path("message_id").asText(),sent.path("epoch").asText());assertEquals(callId,sent.path("call_id").asText());assertArrayEquals(new byte[48],Base64.getDecoder().decode(sent.path("codec2").asText()));
   // Short arrival gaps (including back-to-back packets) must not terminate speech.
   for(int burst=0;burst<2;burst++)ownerVoice.sendBinary(java.nio.ByteBuffer.allocate(84).put(ptt.path("message_id").asText().getBytes(java.nio.charset.StandardCharsets.US_ASCII)).put(new byte[48]).flip(),true).join();
   for(int burst=0;burst<2;burst++)assertEquals("voice",json.readTree(device.next()).path("type").asText());
   assertFalse(ownerClosed.isDone(),"Jitter must not close the voice socket");
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"ptt.off",null),true).statusCode());var listen=json.readTree(device.next());device.callAck(listen);
   ownerVoice.sendText(json.writeValueAsString(Map.of("type","bind","codec","codec2-2400-v1","epoch",listen.path("message_id").asText(),"direction","FIELD_TX")),true).join();awaitVoice(callId,listen.path("message_id").asText());
   field.put("epoch",listen.path("message_id").asText());field.put("sequence",0);voice.receive("gateway-01",json.valueToTree(field));
   var resumed=pcmReceived.poll(3,TimeUnit.SECONDS);assertNotNull(resumed);assertEquals(84,resumed.length);assertFalse(ownerClosed.isDone(),"PTT round trip uses original socket");
   assertEquals(200,b.request("/api/portal/commands","POST",command(rail,"call.end",null),true).statusCode());var end=json.readTree(device.next());assertTrue(end.path("recover").asBoolean());assertEquals(123,end.path("session_id").asLong());device.callAck(end);assertEquals(0,db.queryForObject("SELECT COUNT(*) FROM calls",Integer.class));voice.clean();assertEquals(1008,ownerClosed.get(3,TimeUnit.SECONDS));
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
 class Media implements AutoCloseable {
  final BlockingQueue<byte[]> audio=new LinkedBlockingQueue<>();
  final CompletableFuture<Integer> closed=new CompletableFuture<>();final WebSocket ws;
  Media(Browser b,String call)throws Exception{
   ws=b.http.newWebSocketBuilder().header("Origin","http://127.0.0.1:"+port).buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/operator/voice/"+call),new WebSocket.Listener(){
    final java.io.ByteArrayOutputStream bytes=new java.io.ByteArrayOutputStream();
    public void onOpen(WebSocket w){w.request(1);}
    public CompletionStage<?> onText(WebSocket w,CharSequence text,boolean last){w.request(1);return null;}
    public CompletionStage<?> onBinary(WebSocket w,java.nio.ByteBuffer data,boolean last){byte[] part=new byte[data.remaining()];data.get(part);bytes.writeBytes(part);if(last){audio.add(bytes.toByteArray());bytes.reset();}w.request(1);return null;}
    public CompletionStage<?> onClose(WebSocket w,int status,String reason){closed.complete(status);return null;}
   }).join();
  }
  void bind(tools.jackson.databind.JsonNode command,String direction)throws Exception{
   ws.sendText(json.writeValueAsString(Map.of("type","bind","codec","codec2-2400-v1","epoch",command.path("message_id").asText(),"direction",direction)),true).join();
   awaitVoice(command.path("call_id").asText(),command.path("message_id").asText());
  }
  void send(String epoch,byte[] bits){ws.sendBinary(java.nio.ByteBuffer.allocate(84).put(epoch.getBytes(java.nio.charset.StandardCharsets.US_ASCII)).put(bits).flip(),true).join();}
  public void close(){ws.sendClose(1000,"done").join();}
 }
 tools.jackson.databind.JsonNode callCommand(Browser b,Device d,String rail,String op)throws Exception{
  var response=b.request("/api/portal/commands","POST",command(rail,op,null),true);assertEquals(200,response.statusCode(),response.body());
  var outgoing=json.readTree(d.next());assertEquals(op,outgoing.path("operation").asText());d.callAck(outgoing);return outgoing;
 }
 Map<String,Object> fieldVoice(tools.jackson.databind.JsonNode c,byte[] bits,int seq){return Map.of("version",1,"type","voice","call_id",c.path("call_id").asText(),"railing_id",1,"direction","FIELD_TX","epoch",c.path("message_id").asText(),"sequence",seq,"codec2",Base64.getEncoder().encodeToString(bits));}
 void assertAudio(Media m,byte[] expected)throws Exception{var packet=m.audio.poll(3,TimeUnit.SECONDS);assertNotNull(packet);assertEquals(84,packet.length);assertArrayEquals(expected,Arrays.copyOfRange(packet,36,84));}
 void awaitCallStatus(String gateway,String status)throws Exception{
  long until=System.nanoTime()+3_000_000_000L;while(System.nanoTime()<until){if(status.equals(db.queryForObject("SELECT status FROM calls WHERE gateway_id=?",String.class,gateway)))return;Thread.sleep(10);}fail("Expected call status "+status);
 }
 @Test void twoSitesKeepVoiceAndRecoveryIndependent()throws Exception{
  String suffix=UUID.randomUUID().toString().substring(0,8),site="site-"+suffix,gateway="gateway-"+suffix,token="isolated-gateway-012345678901234567890";
  registry.site("admin",site,"Second independent system");registry.gateway("admin",gateway,site,"Second gateway",token);
  String aName=newUser("isolation-a","OPERATOR"),bName="isolation-b"+suffix;
  String bId=(String)accounts.create(bName,bName,"integration-test-password",false).get("id");accounts.membership("admin",bId,site,"OPERATOR");
  var a=new Browser(aName);var b=new Browser(bName);String railA=rail(),railB=registry.ensureRail(gateway,1);
  byte[] bitsA=new byte[48],bitsB=new byte[48];Arrays.fill(bitsA,(byte)0x35);Arrays.fill(bitsB,(byte)0x6a);
  try(var da=new Device();var dbDevice=new Device(gateway,token)){
   assertEquals(403,a.request("/api/portal/sites/"+site+"/state","GET",null,false).statusCode());
   assertEquals(403,b.request("/api/portal/sites/site-01/state","GET",null,false).statusCode());
   assertEquals(403,a.request("/api/portal/commands","POST",command(railB,"call.start",null),true).statusCode());
   var ca=callCommand(a,da,railA,"call.start");var cb=callCommand(b,dbDevice,railB,"call.start");
   try(var ma=new Media(a,ca.path("call_id").asText());var mb=new Media(b,cb.path("call_id").asText());var foreign=new Media(a,cb.path("call_id").asText())){
    assertEquals(1008,foreign.closed.get(3,TimeUnit.SECONDS));ma.bind(ca,"FIELD_TX");mb.bind(cb,"FIELD_TX");
    da.ws.sendText(json.writeValueAsString(fieldVoice(ca,bitsA,0)),true).join();dbDevice.ws.sendText(json.writeValueAsString(fieldVoice(cb,bitsB,0)),true).join();
    assertAudio(ma,bitsA);assertAudio(mb,bitsB);assertTrue(ma.audio.isEmpty());assertTrue(mb.audio.isEmpty());
    // Both independent gateways may talk, even with the same local rail number.
    var pa=callCommand(a,da,railA,"ptt.on");var pb=callCommand(b,dbDevice,railB,"ptt.on");ma.bind(pa,"CONTROL_TX");mb.bind(pb,"CONTROL_TX");
    ma.send(pa.path("message_id").asText(),bitsA);mb.send(pb.path("message_id").asText(),bitsB);
    var va=json.readTree(da.next());var vb=json.readTree(dbDevice.next());
    assertEquals(ca.path("call_id").asText(),va.path("call_id").asText());assertArrayEquals(bitsA,Base64.getDecoder().decode(va.path("codec2").asText()));
    assertEquals(cb.path("call_id").asText(),vb.path("call_id").asText());assertArrayEquals(bitsB,Base64.getDecoder().decode(vb.path("codec2").asText()));
    cb=callCommand(b,dbDevice,railB,"ptt.off");mb.bind(cb,"FIELD_TX");
    // Gateway A sends B's valid epoch/call ID: reject A, preserve B's media.
    da.ws.sendText(json.writeValueAsString(fieldVoice(cb,bitsA,1)),true).join();awaitCallStatus("gateway-01","UNKNOWN");
    assertFalse(mb.closed.isDone());assertEquals("ACTIVE",this.db.queryForObject("SELECT status FROM calls WHERE gateway_id=?",String.class,gateway));
    dbDevice.ws.sendText(json.writeValueAsString(fieldVoice(cb,bitsB,1)),true).join();assertAudio(mb,bitsB);
    // A reconnect is uncertain until a correlated physical END, not automatically idle.
    try(var recovered=new Device()){
     assertEquals(409,a.request("/api/portal/commands","POST",command(railA,"query","p4"),true).statusCode());
     callCommand(a,recovered,railA,"call.end");
     assertEquals(0,this.db.queryForObject("SELECT COUNT(*) FROM calls WHERE gateway_id='gateway-01'",Integer.class));
     assertFalse(mb.closed.isDone());
     // Losing B's browser stops only B's renewal after the existing grace interval.
     mb.close();mb.closed.get(3,TimeUnit.SECONDS);
     long closedUntil=System.nanoTime()+3_000_000_000L;
     while(((Map<?,?>)org.springframework.test.util.ReflectionTestUtils.getField(voice,"peers")).containsKey(cb.path("call_id").asText()) && System.nanoTime()<closedUntil)Thread.sleep(10);
     assertFalse(((Map<?,?>)org.springframework.test.util.ReflectionTestUtils.getField(voice,"peers")).containsKey(cb.path("call_id").asText()));
     this.db.update("UPDATE calls SET touched_at=? WHERE gateway_id=?",System.currentTimeMillis()-16000,gateway);voice.clean();
     awaitCallStatus(gateway,"UNKNOWN");assertEquals("voice.pause",json.readTree(dbDevice.next()).path("type").asText());
     callCommand(b,dbDevice,railB,"call.end");
    }
   }
  }finally{this.db.update("DELETE FROM calls WHERE gateway_id IN (?,?)","gateway-01",gateway);}
 }
}
