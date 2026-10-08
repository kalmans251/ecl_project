package com.ecl.monitoring;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
@Component
public class Voice extends BinaryWebSocketHandler {
    private record Peer(WebSocketSession session,String username,String callId){}
    private final Map<String,Peer> peers=new ConcurrentHashMap<>();
    private final JdbcTemplate db;private final Accounts accounts;private final Registry registry;private final Gateways gateways;private final PortalSettings settings;
    private final JsonMapper json=JsonMapper.builder().build();private final HttpClient http=HttpClient.newBuilder().connectTimeout(Duration.ofMillis(300)).build();
    public Voice(JdbcTemplate db,Accounts accounts,Registry registry,Gateways gateways,PortalSettings settings){this.db=db;this.accounts=accounts;this.registry=registry;this.gateways=gateways;this.settings=settings;}
    public boolean available(){return settings.codecToken()!=null && settings.codecToken().length()>=32;}
    private Map<String,Object> owned(String username,String id){
        var rows=db.queryForList("SELECT c.*,g.site_id,r.number FROM calls c JOIN portal_gateways g ON g.id=c.gateway_id JOIN rails r ON r.id=c.rail_id WHERE c.id=?",id);
        if(rows.isEmpty())throw Accounts.bad("No call");var call=rows.get(0);accounts.permit(username,(String)call.get("SITE_ID"),true);
        if(!call.get("USER_ID").equals(accounts.user(username).get("ID"))||!call.get("STATUS").equals("ACTIVE"))throw Accounts.bad("Not the active call owner");return call;
    }
    @Override public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        try{
            if(!available())throw new IllegalArgumentException("Codec adapter not configured");
            var uri=URI.create(settings.codecUrl());if(!Set.of("127.0.0.1","localhost","::1","[::1]").contains(uri.getHost()) || !uri.getScheme().equals("http"))throw new IllegalArgumentException("Codec adapter must be loopback HTTP");
            String origin=session.getHandshakeHeaders().getOrigin();URI o=origin==null?null:URI.create(origin);URI s=session.getUri();
            if(o==null||!o.getHost().equals(s.getHost())||port(o)!=port(s)||!(o.getScheme().equals("https")?s.getScheme().equals("wss"):s.getScheme().equals("ws")))throw new IllegalArgumentException("Same origin required");
            String id=s.getPath().substring("/ws/operator/voice/".length()),username=session.getPrincipal().getName();owned(username,id);
            var peer=new Peer(new ConcurrentWebSocketSessionDecorator(session,500,8192),username,id);var old=peers.put(id,peer);if(old!=null)old.session().close(CloseStatus.POLICY_VIOLATION);
        }catch(Exception e){session.close(CloseStatus.POLICY_VIOLATION);}
    }
    private int port(URI uri){return uri.getPort()!=-1?uri.getPort():Set.of("https","wss").contains(uri.getScheme())?443:80;}
    private byte[] codec(String call,String action,byte[] data) throws Exception {
        var request=HttpRequest.newBuilder(URI.create(settings.codecUrl()+"/"+action+"/"+call)).timeout(Duration.ofMillis(500)).header("Authorization","Bearer "+settings.codecToken()).POST(HttpRequest.BodyPublishers.ofByteArray(data)).build();
        var response=http.send(request,HttpResponse.BodyHandlers.ofByteArray());if(response.statusCode()!=200)throw new IllegalStateException("Codec adapter failure");return response.body();
    }
    @Override protected void handleBinaryMessage(WebSocketSession session,BinaryMessage message) throws Exception {
        var peer=peers.values().stream().filter(p->p.session().getId().equals(session.getId())).findFirst().orElse(null);if(peer==null){session.close();return;}
        try{
            var call=owned(peer.username(),peer.callId());if(!call.get("DIRECTION").equals("CONTROL_TX") || message.getPayloadLength()!=2560)throw new IllegalArgumentException();
            long now=System.nanoTime();synchronized(session){var last=(Long)session.getAttributes().get("last_pcm");if(last!=null&&now-last<100_000_000L)throw new IllegalArgumentException("Voice rate exceeded");session.getAttributes().put("last_pcm",now);}
            byte[] pcm=new byte[2560];message.getPayload().get(pcm);byte[] encoded=codec(peer.callId(),"encode",pcm);if(encoded.length!=48)throw new IllegalArgumentException();
            int seq=(Integer)session.getAttributes().getOrDefault("sequence",0);session.getAttributes().put("sequence",(seq+1)&65535);
            gateways.send((String)call.get("GATEWAY_ID"),json.writeValueAsString(Map.of("version",1,"type","voice","call_id",peer.callId(),"railing_id",call.get("NUMBER"),"direction","CONTROL_TX","sequence",seq,"codec2",Base64.getEncoder().encodeToString(encoded))));
        }catch(Exception e){session.close(CloseStatus.SERVER_ERROR);}
    }
    public void receive(String gateway,JsonNode node) throws Exception {
        if(node.size()!=7 || !node.path("sequence").isInt() || node.path("sequence").asInt()<0 || node.path("sequence").asInt()>65535 || !node.path("railing_id").isInt() || !node.path("direction").asText().equals("FIELD_TX"))throw Accounts.bad("Invalid voice envelope");
        Peer peer=peers.get(node.path("call_id").asText());if(peer==null)return;
        try{
            var call=owned(peer.username(),peer.callId());if(!call.get("GATEWAY_ID").equals(gateway)||((Number)call.get("NUMBER")).intValue()!=node.path("railing_id").intValue()||!call.get("DIRECTION").equals("FIELD_TX"))throw new IllegalArgumentException();
            byte[] bits=Base64.getDecoder().decode(node.path("codec2").asText());if(bits.length!=48)throw new IllegalArgumentException();byte[] pcm=codec(peer.callId(),"decode",bits);if(pcm.length!=2560)throw new IllegalArgumentException();
            peer.session().sendMessage(new BinaryMessage(pcm));
        }catch(Exception e){peer.session().close(CloseStatus.SERVER_ERROR);}
    }
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=1000) public void clean(){for(var peer:peers.values())try{owned(peer.username(),peer.callId());}catch(Exception e){try{peer.session().close(CloseStatus.POLICY_VIOLATION);}catch(Exception ignored){}}}
    @org.springframework.context.event.EventListener public void loggedOut(org.springframework.security.web.session.HttpSessionDestroyedEvent event){
        for(var peer:peers.values())if(event.getId().equals(peer.session().getAttributes().get(org.springframework.web.socket.server.support.HttpSessionHandshakeInterceptor.HTTP_SESSION_ID_ATTR_NAME)))try{peer.session().close(CloseStatus.POLICY_VIOLATION);}catch(Exception ignored){}
    }
    @Override public void afterConnectionClosed(WebSocketSession session,CloseStatus status){peers.entrySet().removeIf(e->e.getValue().session().getId().equals(session.getId()));}
}
