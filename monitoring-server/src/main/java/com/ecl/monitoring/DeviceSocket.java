package com.ecl.monitoring;
import java.util.Map;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.TextWebSocketHandler;
import tools.jackson.databind.json.JsonMapper;
@Component
public class DeviceSocket extends TextWebSocketHandler {
    private final Gateways gateways;
    private final Events events;
    private final Commands commands; private final Telemetry telemetry;private final Voice voice;
    private final JsonMapper json=JsonMapper.builder().build();
    public DeviceSocket(Gateways gateways, Events events, Commands commands, Telemetry telemetry,Voice voice) { this.gateways=gateways; this.events=events; this.commands=commands;this.telemetry=telemetry;this.voice=voice; }
    private String id(WebSocketSession session) { return session.getUri().getPath().substring("/ws/gateways/".length()); }
    @Override public void afterConnectionEstablished(WebSocketSession session) throws Exception {
        session.setTextMessageSizeLimit(4096);
        session.setBinaryMessageSizeLimit(4096);
        gateways.connect(id(session),session);
        gateways.send(id(session),json.writeValueAsString(Map.of("version",1,"type","welcome","gateway_id",id(session))));
    }
    @Override protected void handleTextMessage(WebSocketSession session, TextMessage message) throws Exception {
        try {
            // Bound acknowledgments independently from REST rate limits.
            synchronized (session) {
                long second=System.nanoTime()/1_000_000_000L;
                Map<String,Object> attrs=session.getAttributes();
                if (!Long.valueOf(second).equals(attrs.get("ack_second"))) { attrs.put("ack_second",second); attrs.put("ack_count",0); }
                int count=(Integer)attrs.get("ack_count")+1;
                attrs.put("ack_count",count);
                if (count>30) throw new IllegalArgumentException("Too many acknowledgments");
            }
            var node=json.readTree(message.getPayload());
            if(node.isObject() && node.path("version").isInt() && node.path("version").intValue()==1 && node.path("type").asText().equals("voice")){voice.receive(id(session),node);return;}
            if(node.isObject() && node.path("version").isInt() && node.path("version").intValue()==1 && node.path("type").asText().equals("telemetry")){telemetry.accept(id(session),node);return;}
            if (!node.isObject() || node.size()!=4 || !node.path("version").isInt() || node.path("version").intValue()!=1
                    || !node.path("type").asText().equals("ack") || !node.path("message_id").isString()
                    || !node.path("status").isString()) throw new IllegalArgumentException("Invalid acknowledgment");
            if(!commands.ack(id(session),node.path("message_id").asText(),node.path("status").asText())) events.ack(id(session),node.path("message_id").asText(),node.path("status").asText());
        } catch (Exception e) { session.close(CloseStatus.BAD_DATA); }
    }
    @Override protected void handlePongMessage(WebSocketSession session, PongMessage message) {
        gateways.pong(id(session),session.getId());
    }
    @Override public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        gateways.disconnect(id(session),session.getId());
    }
    @Override public void handleTransportError(WebSocketSession session, Throwable exception) throws Exception {
        gateways.disconnect(id(session),session.getId()); session.close(CloseStatus.SERVER_ERROR);
    }
}
