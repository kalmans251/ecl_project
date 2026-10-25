package com.ecl.monitoring;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.*;
import org.springframework.web.socket.handler.*;
import tools.jackson.databind.json.JsonMapper;

@Component
public class CameraSocket extends TextWebSocketHandler {
 private static class Connection {
  final WebSocketSession socket;final String revision=UUID.randomUUID().toString(),token;
  volatile long lastSeen=System.currentTimeMillis();volatile String state="connected";long reportSecond;int reportCount;
  Connection(WebSocketSession s,String t){socket=new ConcurrentWebSocketSessionDecorator(s,1000,4096);token=t;}
 }
 private final Map<String,Connection> connections=new ConcurrentHashMap<>();private final Cctv cctv;
 private final JsonMapper json=JsonMapper.builder().build();
 public CameraSocket(Cctv cctv){this.cctv=cctv;}
 private String id(WebSocketSession s){return s.getUri().getPath().substring("/ws/cameras/".length());}
 @Override public void afterConnectionEstablished(WebSocketSession s)throws Exception{
  s.setTextMessageSizeLimit(1024);String h=s.getHandshakeHeaders().getFirst("Authorization");String token=h==null?"":h.substring(7);
  if(!cctv.auth(id(s),"control",token)){s.close(CloseStatus.POLICY_VIOLATION);return;}
  var c=new Connection(s,token);var old=connections.put(id(s),c);if(old!=null)old.socket.close();send(id(s),c);
 }
 private void send(String id,Connection c)throws Exception{
  if(!cctv.auth(id,"control",c.token)||System.currentTimeMillis()-c.lastSeen>25000){c.socket.close(CloseStatus.POLICY_VIOLATION);return;}
  c.socket.sendMessage(new TextMessage(json.writeValueAsString(Map.of("version",1,"type","desired","camera_id",id,"revision",c.revision,"stream",cctv.wanted(id),"lease_seconds",15))));
 }
 @Override protected void handleTextMessage(WebSocketSession s,TextMessage m)throws Exception{
  var c=connections.get(id(s));if(c==null||!c.socket.getId().equals(s.getId())){s.close();return;}
  try{var n=json.readTree(m.getPayload());long now=System.currentTimeMillis();
   if(now/1000!=c.reportSecond){c.reportSecond=now/1000;c.reportCount=0;}
   if(++c.reportCount>20||n.size()!=4||n.path("version").asInt()!=1||!n.path("type").asText().equals("status")||!n.path("revision").asText().equals(c.revision)||!Set.of("stopped","starting","streaming","error").contains(n.path("state").asText()))throw Accounts.bad("Invalid camera status");
   c.state=n.path("state").asText();c.lastSeen=now;
  }catch(Exception e){s.close(CloseStatus.BAD_DATA);}
 }
 @Override public void afterConnectionClosed(WebSocketSession s,CloseStatus status){connections.computeIfPresent(id(s),(k,c)->c.socket.getId().equals(s.getId())?null:c);}
 @org.springframework.scheduling.annotation.Scheduled(fixedDelay=5000) public void refresh(){connections.forEach((id,c)->{try{send(id,c);}catch(Exception e){try{c.socket.close();}catch(Exception ignored){}connections.remove(id,c);}});}
 public Map<String,Object> status(String id){var c=connections.get(id);boolean online=c!=null&&c.socket.isOpen()&&System.currentTimeMillis()-c.lastSeen<25000;return Map.of("connected",online,"state",online?c.state:"offline");}
}
