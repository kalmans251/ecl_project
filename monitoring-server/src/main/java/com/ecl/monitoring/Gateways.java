package com.ecl.monitoring;
import java.io.IOException;
import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.ConcurrentWebSocketSessionDecorator;
@Component
public class Gateways {
    private record Connection(WebSocketSession session, Instant connectedAt, java.util.concurrent.atomic.AtomicLong lastPong) {}
    private final Map<String,Connection> connections=new ConcurrentHashMap<>();
    public void connect(String id, WebSocketSession session) throws IOException {
        Connection old=connections.put(id,new Connection(new ConcurrentWebSocketSessionDecorator(session,1000,32768),Instant.now(),new java.util.concurrent.atomic.AtomicLong(System.nanoTime())));
        if (old != null) old.session().close(CloseStatus.POLICY_VIOLATION);
    }
    public void disconnect(String id, String sessionId) {
        connections.computeIfPresent(id,(key,value) -> value.session().getId().equals(sessionId) ? null : value);
    }
    public void pong(String id, String sessionId) {
        Connection c=connections.get(id);
        if (c != null && c.session().getId().equals(sessionId)) c.lastPong().set(System.nanoTime());
    }
    public void send(String id, String json) throws IOException {
        Connection c=connections.get(id);
        if (c == null || !c.session().isOpen()) throw new IOException("Gateway offline");
        c.session().sendMessage(new TextMessage(json));
    }
    public boolean online(String id) { Connection c=connections.get(id); return c!=null && c.session().isOpen(); }
    public List<Map<String,Object>> status(Settings settings) {
        return settings.gateways().stream().map(g -> {
            Connection c=connections.get(g.id());
            return Map.<String,Object>of("gateway_id",g.id(),"connected",c != null && c.session().isOpen(),
                "connected_at",c == null ? "" : c.connectedAt().toString());
        }).toList();
    }
    @Scheduled(fixedDelay=20000) public void ping() {
        connections.forEach((id,c) -> { try {
            if (System.nanoTime()-c.lastPong().get()>60_000_000_000L) {
                disconnect(id,c.session().getId()); c.session().close(CloseStatus.GOING_AWAY);
            } else if (c.session().isOpen()) c.session().sendMessage(new PingMessage());
        } catch (Exception e) { disconnect(id,c.session().getId()); try { c.session().close(); } catch (IOException ignored) {} } });
    }
}
