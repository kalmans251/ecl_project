package com.ecl.monitoring;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import java.net.URI;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
@Component
public class Voice extends AbstractWebSocketHandler {
    private static final org.slf4j.Logger LOG=org.slf4j.LoggerFactory.getLogger(Voice.class);
    private record Peer(WebSocketSession session,String username,String callId,String epoch){}
    private final Map<String,Peer> peers=new ConcurrentHashMap<>();
    private final JdbcTemplate db;private final Accounts accounts;private final Registry registry;private final Gateways gateways;
    private final JsonMapper json=JsonMapper.builder().build();
    public Voice(JdbcTemplate db,Accounts accounts,Registry registry,Gateways gateways){this.db=db;this.accounts=accounts;this.registry=registry;this.gateways=gateways;}
    public boolean available(){return Voice.class.getResource("/static/codec2/codec2.js")!=null;}
    private Map<String,Object> owned(String username,String id){
        var rows=db.queryForList("SELECT c.*,g.site_id,r.number FROM calls c JOIN portal_gateways g ON g.id=c.gateway_id JOIN rails r ON r.id=c.rail_id WHERE c.id=?",id);
        if(rows.isEmpty())throw Accounts.bad("No call");var call=rows.get(0);accounts.permit(username,(String)call.get("SITE_ID"),true);
        if(!call.get("USER_ID").equals(accounts.user(username).get("ID"))||!Set.of("ACTIVE","SWITCHING","ENDING").contains(call.get("STATUS")))throw Accounts.bad("Not the active call owner");return call;
    }
    @Override public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        try{
            if(!available())throw new IllegalArgumentException("Browser Codec2 asset unavailable");
            String origin=session.getHandshakeHeaders().getOrigin();URI o=origin==null?null:URI.create(origin);URI s=session.getUri();
            if(o==null||!o.getHost().equals(s.getHost())||port(o)!=port(s)||!(o.getScheme().equals("https")?s.getScheme().equals("wss"):s.getScheme().equals("ws")))throw new IllegalArgumentException("Same origin required");
            String id=s.getPath().substring("/ws/operator/voice/".length()),username=session.getPrincipal().getName();var call=owned(username,id);
            var peer=new Peer(new ConcurrentWebSocketSessionDecorator(session,500,8192),username,id,null);var old=peers.put(id,peer);if(old!=null)old.session().close(CloseStatus.POLICY_VIOLATION);
            LOG.info("VOICE connected call={} socket={} direction={} epoch={}",id,session.getId(),call.get("DIRECTION"),peer.epoch());
        }catch(Exception e){LOG.warn("VOICE connection rejected socket={} error={}",session.getId(),e.toString());session.close(CloseStatus.POLICY_VIOLATION);}
    }
    private Peer peer(WebSocketSession session){return peers.values().stream().filter(p->p.session().getId().equals(session.getId())).findFirst().orElse(null);}
    @Override protected void handleTextMessage(WebSocketSession session,TextMessage message) throws Exception {
        var peer=peer(session);if(peer==null){session.close();return;}
        try{
            var request=json.readTree(message.getPayload());
            if(request.size()!=4||!request.path("type").asText().equals("bind"))throw new IllegalArgumentException("Expected bind");
            if(!request.path("codec").asText().equals("codec2-2400-v1"))throw new IllegalArgumentException("Refresh browser: Codec2 transport required");
            var call=owned(peer.username(),peer.callId());
            String epoch=request.path("epoch").asText(),direction=request.path("direction").asText();
            if(!call.get("STATUS").equals("ACTIVE")||!epoch.equals(call.get("VOICE_EPOCH"))||!direction.equals(call.get("DIRECTION")))return;
            if(!UUID.fromString(epoch).toString().equals(epoch))throw new IllegalArgumentException("Invalid epoch");
            synchronized(peer.session()){
                if(peers.get(peer.callId())!=peer)return;
                if(!epoch.equals(peer.epoch())){
                    for(String key:List.of("field_sequence","voice_rate","rate_dropped","rate_log_at","sequence"))peer.session().getAttributes().remove(key);
                    peers.put(peer.callId(),new Peer(peer.session(),peer.username(),peer.callId(),epoch));
                }
                peer.session().sendMessage(new TextMessage(json.writeValueAsString(Map.of("type","ready","epoch",epoch,"direction",direction,"codec","codec2-2400-v1"))));
            }
            LOG.info("VOICE bound call={} socket={} epoch={} direction={}",peer.callId(),session.getId(),epoch,direction);
        }catch(Exception e){LOG.warn("VOICE bind rejected socket={} error={}",session.getId(),e.toString());session.close(CloseStatus.POLICY_VIOLATION);}
    }
    private boolean active(Peer peer,Map<String,Object> call){return call.get("STATUS").equals("ACTIVE")&&peer.epoch()!=null&&peer.epoch().equals(call.get("VOICE_EPOCH"))&&peers.get(peer.callId())==peer;}
    private byte[] packet(String epoch,byte[] pcm){return java.nio.ByteBuffer.allocate(36+pcm.length).put(epoch.getBytes(java.nio.charset.StandardCharsets.US_ASCII)).put(pcm).array();}
    @Override public void handleTransportError(WebSocketSession session,Throwable error){LOG.warn("VOICE transport failed socket={} error={}",session.getId(),error.toString());try{session.close(CloseStatus.SERVER_ERROR);}catch(Exception ignored){}finally{afterConnectionClosed(session,CloseStatus.SERVER_ERROR);}}
    private int port(URI uri){return uri.getPort()!=-1?uri.getPort():Set.of("https","wss").contains(uri.getScheme())?443:80;}
    @Override protected void handleBinaryMessage(WebSocketSession session,BinaryMessage message) throws Exception {
        var peer=peer(session);if(peer==null){session.close();return;}
        String stage="validate";
        try{
            var call=owned(peer.username(),peer.callId());if(!active(peer,call))return;if(message.getPayloadLength()!=84)throw new IllegalArgumentException("Expected epoch + 48 Codec2 bytes");
            byte[] tag=new byte[36];message.getPayload().get(tag);if(!peer.epoch().equals(new String(tag,java.nio.charset.StandardCharsets.US_ASCII)))return;
            if(!call.get("DIRECTION").equals("CONTROL_TX"))throw new IllegalArgumentException("Not speaking");
            long now=System.nanoTime();
            synchronized(session){
                var limiter=(VoiceRateLimit)session.getAttributes().computeIfAbsent("voice_rate",key->new VoiceRateLimit());
                if(!limiter.allow(now)){
                    long dropped=((Number)session.getAttributes().getOrDefault("rate_dropped",0L)).longValue()+1;
                    session.getAttributes().put("rate_dropped",dropped);
                    var logged=(Long)session.getAttributes().get("rate_log_at");
                    if(logged==null||now-logged>=5_000_000_000L){
                        LOG.warn("VOICE excess Codec2 dropped call={} packets={}; connection retained",peer.callId(),dropped);
                        session.getAttributes().put("rate_log_at",now);
                    }
                    return;
                }
            }
            byte[] encoded=new byte[48];message.getPayload().get(encoded);
            long count=((Number)session.getAttributes().getOrDefault("pcm_count",0L)).longValue()+1;session.getAttributes().put("pcm_count",count);
            int seq=(Integer)session.getAttributes().getOrDefault("sequence",0);session.getAttributes().put("sequence",(seq+1)&65535);
            if(!active(peer,owned(peer.username(),peer.callId())))return;
            stage="gateway-send";
            gateways.send((String)call.get("GATEWAY_ID"),json.writeValueAsString(Map.of("version",1,"type","voice","call_id",peer.callId(),"railing_id",call.get("NUMBER"),"direction","CONTROL_TX","epoch",call.get("VOICE_EPOCH"),"sequence",seq,"codec2",Base64.getEncoder().encodeToString(encoded))));
            if(count==1||count%25==0)LOG.info("VOICE Codec2 sent to gateway call={} gateway={} seq={} bytes={}",peer.callId(),call.get("GATEWAY_ID"),seq,encoded.length);
        }catch(Exception e){LOG.warn("VOICE uplink failed call={} socket={} stage={} error={}",peer.callId(),session.getId(),stage,e.toString(),e);session.close(CloseStatus.SERVER_ERROR);}
    }
    public void receive(String gateway,JsonNode node) throws Exception {
        if(node.size()!=8 || !node.path("epoch").isString() || !node.path("sequence").isInt() || node.path("sequence").asInt()<0 || node.path("sequence").asInt()>65535 || !node.path("railing_id").isInt() || !node.path("direction").asText().equals("FIELD_TX"))throw Accounts.bad("Invalid voice envelope");
        Peer peer=peers.get(node.path("call_id").asText());if(peer==null)return;
        // Reject a foreign producer before entering the target peer's error path.
        // A bad gateway must never be able to close another gateway's operator socket.
        var routes=db.queryForList("SELECT gateway_id FROM calls WHERE id=?",peer.callId());
        if(routes.isEmpty())return;
        if(!gateway.equals(routes.get(0).get("GATEWAY_ID")))throw Accounts.bad("Voice gateway does not own call");
        try{
            var call=owned(peer.username(),peer.callId());if(!active(peer,call))return;if(!node.path("epoch").asText().equals(peer.epoch()))return;if(!call.get("GATEWAY_ID").equals(gateway)||((Number)call.get("NUMBER")).intValue()!=node.path("railing_id").intValue()||!call.get("DIRECTION").equals("FIELD_TX"))throw new IllegalArgumentException();
            if(!node.path("epoch").asText().equals(call.get("VOICE_EPOCH")))return;
            int seq=node.path("sequence").asInt();
            synchronized(peer.session()){
                if(peers.get(peer.callId())!=peer)return;
                var last=(Integer)peer.session().getAttributes().get("field_sequence");
                int delta=last==null?1:(seq-last)&65535;
                if(delta==0 || delta>=32768)return;
                peer.session().getAttributes().put("field_sequence",seq);
            }
            byte[] bits=Base64.getDecoder().decode(node.path("codec2").asText());if(bits.length!=48)throw new IllegalArgumentException();
            if(!active(peer,owned(peer.username(),peer.callId())))return;
            peer.session().sendMessage(new BinaryMessage(packet(peer.epoch(),bits)));
        }catch(Exception e){LOG.warn("VOICE downlink failed call={} error={}",peer.callId(),e.toString(),e);peer.session().close(CloseStatus.SERVER_ERROR);}
    }
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=1000) public void clean(){
        for(var call:db.queryForList("SELECT * FROM calls WHERE status='ACTIVE'"))if(!gateways.online((String)call.get("GATEWAY_ID")))db.update("UPDATE calls SET status='UNKNOWN',voice_epoch=NULL WHERE id=?",call.get("ID"));
        for(var call:db.queryForList("SELECT * FROM calls WHERE status='ACTIVE' AND touched_at<?",System.currentTimeMillis()-15000)){
            var bound=peers.get((String)call.get("ID"));if(bound!=null&&bound.epoch()!=null&&bound.epoch().equals(call.get("VOICE_EPOCH")))continue;
            LOG.warn("VOICE media absent for 15s call={}; pausing gateway renewal",call.get("ID"));
            db.update("UPDATE calls SET status='UNKNOWN',voice_epoch=NULL WHERE id=? AND status='ACTIVE'",call.get("ID"));
            try{gateways.send((String)call.get("GATEWAY_ID"),json.writeValueAsString(Map.of("version",1,"type","voice.pause","call_id",call.get("ID"))));}catch(Exception ignored){}
        }
        for(var peer:peers.values())try{owned(peer.username(),peer.callId());}catch(Exception e){try{peer.session().close(CloseStatus.POLICY_VIOLATION);}catch(Exception ignored){}}}
    @org.springframework.context.event.EventListener public void loggedOut(org.springframework.security.web.session.HttpSessionDestroyedEvent event){
        for(var peer:peers.values())if(event.getId().equals(peer.session().getAttributes().get(org.springframework.web.socket.server.support.HttpSessionHandshakeInterceptor.HTTP_SESSION_ID_ATTR_NAME)))try{peer.session().close(CloseStatus.POLICY_VIOLATION);}catch(Exception ignored){}
    }
    @Override public void afterConnectionClosed(WebSocketSession session,CloseStatus status){LOG.info("VOICE closed socket={} code={} reason={} pcm_packets={}",session.getId(),status.getCode(),status.getReason(),session.getAttributes().getOrDefault("pcm_count",0L));peers.entrySet().removeIf(e->{if(!e.getValue().session().getId().equals(session.getId()))return false;
            // Start the reconnect grace at the loss of the currently bound socket.
            // A replaced socket must not extend the new owner's lease.
            db.update("UPDATE calls SET touched_at=? WHERE id=? AND status='ACTIVE' AND voice_epoch=?",System.currentTimeMillis(),e.getKey(),e.getValue().epoch());
            return true;});}
}
