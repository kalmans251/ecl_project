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

/** Live radar only: bounded memory, no per-coordinate database writes. */
@Component
public class RadarSocket extends TextWebSocketHandler {
    private record Peer(WebSocketSession socket,String username,String rail,String gateway,int number) {}
    private record Sample(String gateway,String session,long observed,Map<String,Object> state) {}
    private final Map<String,Peer> peers=new ConcurrentHashMap<>();
    private final Map<String,Long> heartbeats=new ConcurrentHashMap<>();
    private final Map<String,Sample> samples=new ConcurrentHashMap<>();
    private final Set<String> demanded=new HashSet<>();
    private final Map<String,Sample> delivered=new ConcurrentHashMap<>();
    private final Registry registry; private final Accounts accounts; private final Gateways gateways;
    private final JsonMapper json=JsonMapper.builder().build();
    public RadarSocket(Registry registry,Accounts accounts,Gateways gateways){this.registry=registry;this.accounts=accounts;this.gateways=gateways;}
    private static int port(URI u){return u.getPort()!=-1?u.getPort():(Set.of("https","wss").contains(u.getScheme())?443:80);}
    static boolean sameOrigin(URI origin,URI socket){return origin!=null && Objects.equals(origin.getHost(),socket.getHost()) && port(origin)==port(socket) && (origin.getScheme().equals("https")?socket.getScheme().equals("wss"):origin.getScheme().equals("http")&&socket.getScheme().equals("ws"));}
    private void permit(Peer p){accounts.permit(p.username(),(String)registry.rail(p.rail()).get("SITE_ID"),false);}
    @Override public void afterConnectionEstablished(WebSocketSession socket)throws Exception{
        try{
            String origin=socket.getHandshakeHeaders().getOrigin();
            if(!sameOrigin(origin==null?null:URI.create(origin),socket.getUri()) || socket.getPrincipal()==null)throw Accounts.bad("Same origin login required");
            String user=socket.getPrincipal().getName();
            if(peers.size()>=256 || peers.values().stream().filter(p->p.username().equals(user)).count()>=4)throw Accounts.bad("Too many radar views");
            String id=socket.getUri().getPath().substring("/ws/operator/radar/".length());var rail=registry.rail(id);
            var peer=new Peer(new ConcurrentWebSocketSessionDecorator(socket,500,4096),user,id,(String)rail.get("GATEWAY_ID"),((Number)rail.get("NUMBER")).intValue());
            permit(peer);socket.setTextMessageSizeLimit(128);
            peers.put(socket.getId(),peer);heartbeats.put(socket.getId(),System.currentTimeMillis());
            send(peer);refresh();
        }catch(Exception e){socket.close(CloseStatus.POLICY_VIOLATION);}
    }
    @Override protected void handleTextMessage(WebSocketSession socket,TextMessage message)throws Exception{
        if(!message.getPayload().equals("ping") || !peers.containsKey(socket.getId())){socket.close(CloseStatus.BAD_DATA);return;}
        long now=System.currentTimeMillis(),previous=heartbeats.getOrDefault(socket.getId(),0L);
        if(now-previous<500){socket.close(CloseStatus.POLICY_VIOLATION);return;}
        heartbeats.put(socket.getId(),now);
    }
    @Override public void afterConnectionClosed(WebSocketSession socket,CloseStatus status){peers.remove(socket.getId());heartbeats.remove(socket.getId());delivered.remove(socket.getId());}
    @org.springframework.context.event.EventListener
    public void sessionEnded(org.springframework.security.core.session.SessionDestroyedEvent event){
        for(var p:peers.values())if(event.getId().equals(p.socket().getAttributes().get("HTTP.SESSION.ID")))close(p);
    }
    private void close(Peer p){delivered.remove(p.socket().getId());peers.remove(p.socket().getId());heartbeats.remove(p.socket().getId());try{p.socket().close();}catch(Exception ignored){}}
    private void send(Peer p)throws Exception{permit(p);p.socket().sendMessage(new TextMessage(json.writeValueAsString(view(p.rail(),p.gateway()))));}

    @Scheduled(fixedDelay=2000) public synchronized void refresh(){
        Map<String,Set<Integer>> demand=new HashMap<>();long now=System.currentTimeMillis();
        for(var p:peers.values())try{
            if(!p.socket().isOpen() || now-heartbeats.getOrDefault(p.socket().getId(),0L)>15000){close(p);continue;}
            permit(p);demand.computeIfAbsent(p.gateway(),k->new TreeSet<>()).add(p.number());
        }catch(Exception e){close(p);}
        Set<String> all=new HashSet<>(demanded);all.addAll(demand.keySet());
        for(String gateway:all)try{gateways.send(gateway,json.writeValueAsString(Map.of("version",1,"type","radar.demand","rails",demand.getOrDefault(gateway,Set.of()))));}catch(Exception ignored){}
        demanded.clear();demanded.addAll(demand.keySet());
        samples.entrySet().removeIf(e->now-e.getValue().observed()>30000);
    }
    static Map<String,Object> validate(JsonNode s){
        if(!s.isObject() || !s.path("available").isBoolean())throw Accounts.bad("Invalid radar state");
        if(s.size()==2 && !s.path("available").booleanValue() && Set.of("timeout","transport","call_or_emergency").contains(s.path("reason").asText()))
            return Map.of("available",false,"reason",s.path("reason").asText(),"targets",List.of());
        if(s.size()!=7 || !s.path("source").isInt() || s.path("source").asInt()<0 || s.path("source").asInt()>2
                || !s.path("count").isInt() || s.path("count").asInt()<0 || s.path("count").asInt()>3
                || !MusicCommands.uint(s.path("sequence"),0xffffffffL) || !MusicCommands.uint(s.path("age_ms"),65535)
                || !s.path("detail").isBoolean() || !s.path("targets").isArray())throw Accounts.bad("Invalid radar fields");
        boolean valid=s.path("available").booleanValue(),detail=s.path("detail").booleanValue();int count=s.path("count").asInt();
        if(valid && (s.path("source").asInt()==0 || s.path("age_ms").asInt()>1500) || !valid && count!=0
                || s.path("targets").size()!=(valid&&detail?count:0))throw Accounts.bad("Invalid radar sample");
        List<Map<String,Double>> points=new ArrayList<>();
        for(var t:s.path("targets")){
            double x=t.path("x").asDouble(),y=t.path("y").asDouble();
            if(t.size()!=2 || !t.path("x").isNumber() || !t.path("y").isNumber() || !Double.isFinite(x) || !Double.isFinite(y) || Math.abs(x)>10 || y<0 || y>10)throw Accounts.bad("Invalid radar coordinate");
            points.add(Map.of("x",x,"y",y));
        }
        return Map.of("available",valid,"source",s.path("source").asInt(),"count",count,"sequence",s.path("sequence").asLong(),"age_ms",s.path("age_ms").asInt(),"detail",detail,"targets",points);
    }
    public synchronized void accept(String gateway,String session,JsonNode node){
        if(!gateways.isCurrent(gateway,session) || node.size()!=5 || !node.path("version").isInt() || node.path("version").asInt()!=1
                || !node.path("type").asText().equals("radar_state") || !node.path("railing_id").isInt())throw Accounts.bad("Invalid radar envelope");
        long observed;try{observed=Instant.parse(node.path("observed_at").asText()).toEpochMilli();}catch(Exception e){throw Accounts.bad("Invalid radar timestamp");}
        long now=System.currentTimeMillis();if(observed>now+2000 || observed<now-3000)throw Accounts.bad("Expired radar message");
        String rail=(String)registry.deviceRail(gateway,node.path("railing_id").asInt()).get("ID");
        var state=validate(node.path("state"));var old=samples.get(rail);
        if(old!=null && old.session().equals(session) && old.observed()>=observed)return;
        samples.put(rail,new Sample(gateway,session,observed,state));

    }
    // Browser backpressure must never block the gateway's voice/ACK receive thread.
    @Scheduled(fixedDelay=100) public void push(){
        for(var p:peers.values()){
            var sample=samples.get(p.rail());
            if(sample==null || delivered.get(p.socket().getId())==sample)continue;
            try{send(p);delivered.put(p.socket().getId(),sample);}catch(Exception e){close(p);}
        }
    }
    public Map<String,Object> view(String rail,String gateway){
        var s=samples.get(rail);
        if(s==null || !s.gateway().equals(gateway) || !gateways.isCurrent(gateway,s.session()))return Map.of("type","radar","rail_id",rail,"fresh",false,"available",false,"targets",List.of());
        long elapsed=Math.max(0,System.currentTimeMillis()-s.observed());
        var out=new LinkedHashMap<String,Object>(s.state());out.put("type","radar");out.put("rail_id",rail);
        long age=elapsed+((Number)s.state().getOrDefault("age_ms",0)).longValue();
        out.put("fresh",age<2500);out.put("expires_in_ms",Math.max(0,2500-age));
        if(age>=2500)out.put("targets",List.of());
        return out;
    }
}
