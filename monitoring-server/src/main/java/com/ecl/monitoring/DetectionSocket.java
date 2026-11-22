package com.ecl.monitoring;

import java.net.URI;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.*;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Latest P4-confirmed cumulative count; never changes general telemetry freshness. */
@Component
public class DetectionSocket extends TextWebSocketHandler {
    private record Peer(WebSocketSession socket,String username,String rail,String gateway) {}
    private record Sample(String gateway,String session,long at,long count,int source) {}
    private final Map<String,Peer> peers=new ConcurrentHashMap<>();
    private final Map<String,Long> beats=new ConcurrentHashMap<>();
    private final Map<String,Sample> samples=new ConcurrentHashMap<>();
    private final Map<String,Sample> delivered=new ConcurrentHashMap<>();
    private final Registry registry; private final Accounts accounts; private final Gateways gateways;
    private final JsonMapper json=JsonMapper.builder().build();
    public DetectionSocket(Registry registry,Accounts accounts,Gateways gateways){this.registry=registry;this.accounts=accounts;this.gateways=gateways;}
    private void permit(Peer p){accounts.permit(p.username(),(String)registry.rail(p.rail()).get("SITE_ID"),false);}
    @Override public void afterConnectionEstablished(WebSocketSession socket)throws Exception{
        try{
            String origin=socket.getHandshakeHeaders().getOrigin();
            if(!RadarSocket.sameOrigin(origin==null?null:URI.create(origin),socket.getUri()) || socket.getPrincipal()==null)throw Accounts.bad("Same origin login required");
            String user=socket.getPrincipal().getName();
            if(peers.size()>=256 || peers.values().stream().filter(p->p.username().equals(user)).count()>=4)throw Accounts.bad("Too many count views");
            String id=socket.getUri().getPath().substring("/ws/operator/detection/".length());var rail=registry.rail(id);
            var peer=new Peer(new ConcurrentWebSocketSessionDecorator(socket,500,2048),user,id,(String)rail.get("GATEWAY_ID"));
            permit(peer);socket.setTextMessageSizeLimit(128);peers.put(socket.getId(),peer);beats.put(socket.getId(),System.currentTimeMillis());
        }catch(Exception e){socket.close(CloseStatus.POLICY_VIOLATION);}
    }
    @Override protected void handleTextMessage(WebSocketSession socket,TextMessage message)throws Exception{
        long now=System.currentTimeMillis();
        if(!message.getPayload().equals("ping") || !peers.containsKey(socket.getId()) || now-beats.getOrDefault(socket.getId(),0L)<500){socket.close(CloseStatus.POLICY_VIOLATION);return;}
        beats.put(socket.getId(),now);
    }
    @Override public void afterConnectionClosed(WebSocketSession socket,CloseStatus status){peers.remove(socket.getId());beats.remove(socket.getId());delivered.remove(socket.getId());}
    @org.springframework.context.event.EventListener
    public void sessionEnded(org.springframework.security.core.session.SessionDestroyedEvent event){
        for(var p:peers.values())if(event.getId().equals(p.socket().getAttributes().get("HTTP.SESSION.ID")))close(p);
    }
    private void close(Peer p){afterConnectionClosed(p.socket(),CloseStatus.NORMAL);try{p.socket().close();}catch(Exception ignored){}}
    public synchronized void accept(String gateway,String session,JsonNode node){
        if(!gateways.isCurrent(gateway,session) || !node.isObject() || node.size()!=6
                || !node.path("version").isInt() || node.path("version").asInt()!=1
                || !node.path("type").asText().equals("detection_state") || !node.path("railing_id").isInt()
                || !MusicCommands.uint(node.path("count"),0xffffffffL)
                || !node.path("source").isInt() || node.path("source").asInt()<0 || node.path("source").asInt()>1)throw Accounts.bad("Invalid count message");
        long at;try{at=Instant.parse(node.path("observed_at").asText()).toEpochMilli();}catch(Exception e){throw Accounts.bad("Invalid count timestamp");}
        long now=System.currentTimeMillis();if(at>now+2000 || at<now-5000)throw Accounts.bad("Expired count message");
        String rail=(String)registry.deviceRail(gateway,node.path("railing_id").asInt()).get("ID");
        var old=samples.get(rail);if(old!=null && old.session().equals(session) && old.at()>=at)return;
        samples.put(rail,new Sample(gateway,session,at,node.path("count").asLong(),node.path("source").asInt()));
    }
    // Keep slow browsers off the PLC/voice receive thread; bounded latest-only cache.
    @Scheduled(fixedDelay=100) public void push(){
        long now=System.currentTimeMillis();
        for(var p:peers.values())try{
            if(!p.socket().isOpen() || now-beats.getOrDefault(p.socket().getId(),0L)>15000){close(p);continue;}
            var s=samples.get(p.rail());
            if(s==null || delivered.get(p.socket().getId())==s || !s.gateway().equals(p.gateway())
                    || !gateways.isCurrent(s.gateway(),s.session()) || now-s.at()>10000)continue;
            permit(p);p.socket().sendMessage(new TextMessage(json.writeValueAsString(Map.of("type","detection_count","rail_id",p.rail(),
                "count",s.count(),"source",s.source(),"observed_at",s.at()))));
            delivered.put(p.socket().getId(),s);
        }catch(Exception e){close(p);}
        samples.entrySet().removeIf(e->now-e.getValue().at()>30000);
    }
}
