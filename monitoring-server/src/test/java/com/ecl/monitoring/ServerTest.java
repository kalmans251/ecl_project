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
import tools.jackson.databind.json.JsonMapper;
@SpringBootTest(webEnvironment=SpringBootTest.WebEnvironment.RANDOM_PORT,properties={
    "spring.datasource.url=jdbc:h2:mem:monitor-test;DB_CLOSE_DELAY=-1",
    "monitoring.admin-token=admin-012345678901234567890123456789",
    "monitoring.analytics-token=analytics-012345678901234567890123456789",
    "monitoring.gateways[0].id=gateway-01", "monitoring.gateways[0].token=gateway-012345678901234567890123456789",
    "monitoring.gateways[1].id=gateway-02", "monitoring.gateways[1].token=other-012345678901234567890123456789"})
class ServerTest {
    @Value("${local.server.port}") int port;
    @Autowired Events events;
    @Autowired Settings settings;
    @Autowired org.springframework.jdbc.core.JdbcTemplate database;
    final JsonMapper json=JsonMapper.builder().build();
    final HttpClient http=HttpClient.newHttpClient();
    final String admin="admin-012345678901234567890123456789";
    final String analytics="analytics-012345678901234567890123456789";
    final String gateway="gateway-012345678901234567890123456789";
    HttpResponse<String> request(String path,String token,String body) throws Exception {
        var builder=HttpRequest.newBuilder(URI.create("http://127.0.0.1:"+port+path));
        if (token!=null) builder.header("Authorization","Bearer "+token);
        if (body!=null) builder.header("Content-Type","application/json").POST(HttpRequest.BodyPublishers.ofString(body));
        return http.send(builder.build(),HttpResponse.BodyHandlers.ofString());
    }
    String body(UUID id,String type,String age,Instant time) {
        Map<String,Object> m=new HashMap<>(Map.of("camera_id","cctv01","event_id",id.toString(),"type",type,"observed_at",time.toString()));
        if (age!=null) m.put("age_group",age);
        return json.writeValueAsString(m);
    }
    @Test void authenticationAndValidation() throws Exception {
        assertEquals(401,request("/api/gateways",null,null).statusCode());
        assertEquals(401,request("/api/gateways",analytics,null).statusCode());
        assertEquals(200,request("/api/gateways",admin,null).statusCode());
        assertEquals(401,request("/api/analytics/events",admin,"{}").statusCode());
        assertEquals(400,request("/api/analytics/events",analytics,"{}").statusCode());
        String extra=body(UUID.randomUUID(),"enter",null,Instant.now());
        extra=extra.substring(0,extra.length()-1)+",\"railing_id\":2}";
        assertEquals(400,request("/api/analytics/events",analytics,extra).statusCode());
        assertEquals(400,request("/api/analytics/events",analytics,body(UUID.randomUUID(),"enter",null,Instant.now().minusSeconds(10))).statusCode());
        assertEquals(400,request("/api/analytics/events",analytics,body(UUID.randomUUID(),"age","50",Instant.now())).statusCode());
        assertEquals(409,request("/api/analytics/events",analytics,body(UUID.randomUUID(),"age","20",Instant.now())).statusCode());
        assertEquals(413,request("/api/analytics/events",analytics," ".repeat(5000)).statusCode());
        assertThrows(CompletionException.class,() -> http.newWebSocketBuilder().buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/gateways/gateway-01"),new WebSocket.Listener() {}).join());
        assertThrows(CompletionException.class,() -> http.newWebSocketBuilder().header("Authorization","Bearer "+gateway)
            .header("Origin","https://attacker.example").buildAsync(URI.create("ws://127.0.0.1:"+port+"/ws/gateways/gateway-01"),new WebSocket.Listener() {}).join());
    }
    @Test void routingCorrelationDeduplicationAndAcknowledgment() throws Exception {
        BlockingQueue<String> messages=new LinkedBlockingQueue<>();
        WebSocket ws=http.newWebSocketBuilder().header("Authorization","Bearer "+gateway).buildAsync(
            URI.create("ws://127.0.0.1:"+port+"/ws/gateways/gateway-01"),new WebSocket.Listener() {
                StringBuilder buffer=new StringBuilder();
                @Override public void onOpen(WebSocket socket) { socket.request(1); }
                @Override public CompletionStage<?> onText(WebSocket socket,CharSequence text,boolean last) {
                    buffer.append(text); if(last) { messages.add(buffer.toString()); buffer.setLength(0); }
                    socket.request(1); return null;
                }
            }).join();
        assertEquals("welcome",json.readTree(messages.poll(3,TimeUnit.SECONDS)).path("type").asText());
        UUID id=UUID.randomUUID(); Instant at=Instant.now(); String enter=body(id,"enter",null,at);
        var response=request("/api/analytics/events",analytics,enter);
        assertEquals(200,response.statusCode(),response.body());
        var result=json.readTree(response.body());
        String messageId=result.path("message_id").asText(); long seq=result.path("event_seq").longValue();
        var delivery=json.readTree(messages.poll(3,TimeUnit.SECONDS));
        assertEquals("cctv.enter",delivery.path("type").asText());
        assertEquals(1,delivery.path("railing_id").intValue());
        assertEquals(seq,delivery.path("event_seq").longValue());
        assertFalse(result.path("device_application_confirmed").booleanValue());
        assertEquals(messageId,json.readTree(request("/api/analytics/events",analytics,enter).body()).path("message_id").asText());
        assertNull(messages.poll(100,TimeUnit.MILLISECONDS));
        assertEquals(409,request("/api/analytics/events",analytics,body(id,"enter",null,at.plusMillis(1))).statusCode());
        assertThrows(Exception.class,() -> events.ack("gateway-02",messageId,"PLC_SENT"));
        ws.sendText(json.writeValueAsString(Map.of("version",1,"type","ack","message_id",messageId,"status","PLC_SENT")),true).join();
        long deadline=System.nanoTime()+TimeUnit.SECONDS.toNanos(2);
        while(!events.find(messageId).get("status").equals("PLC_SENT") && System.nanoTime()<deadline) Thread.sleep(10);
        assertEquals("PLC_SENT",events.find(messageId).get("status"));
        var age=request("/api/analytics/events",analytics,body(id,"age","20",Instant.now()));
        assertEquals(200,age.statusCode(),age.body());
        var ageDelivery=json.readTree(messages.poll(3,TimeUnit.SECONDS));
        assertEquals(seq,ageDelivery.path("event_seq").longValue());
        assertEquals("20",ageDelivery.path("age_group").asText());
        String ageId=json.readTree(age.body()).path("message_id").asText();
        events.recover();
        assertEquals("UNKNOWN",events.find(ageId).get("status"));
        assertEquals("PLC_SENT",events.find(messageId).get("status"));
        ws.sendClose(1000,"done").join();
    }
    @Test void offlineDoesNotClaimSuccessOrReplay() {
        var offline=new Gateways();
        var service=new Events(database,settings,offline);
        UUID id=UUID.randomUUID();
        var input=new Events.Input("cctv01",id,"enter",null,Instant.now());
        var result=service.submit(input);
        assertEquals("UNKNOWN",result.get("status"));
        assertEquals(false,result.get("device_application_confirmed"));
        assertEquals(result,service.submit(input));
        assertThrows(Exception.class,() -> service.submit(new Events.Input("cctv01",id,"age","20",Instant.now())));
        var second=service.submit(new Events.Input("cctv01",UUID.randomUUID(),"enter",null,Instant.now()));
        assertNotEquals(result.get("event_seq"),second.get("event_seq"));
    }
    @Test void secretsMustBeDistinctAndConfigured() {
        assertThrows(IllegalArgumentException.class,() -> new Settings("","",List.of(),List.of()));
        assertThrows(IllegalArgumentException.class,() -> new Settings(admin,admin,List.of(),List.of()));
    }
}
