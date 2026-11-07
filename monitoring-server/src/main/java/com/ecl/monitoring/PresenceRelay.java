package com.ecl.monitoring;
import java.time.Instant;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;
import tools.jackson.databind.json.JsonMapper;

/** Positive, short-lived occupancy hints; no count events or durable replay. */
@Service
public class PresenceRelay {
 private final Registry registry;private final Gateways gateways;
 private final JsonMapper json=JsonMapper.builder().build();
 private final Map<String,Long> last=new ConcurrentHashMap<>();
 public PresenceRelay(Registry registry,Gateways gateways){this.registry=registry;this.gateways=gateways;}
 public synchronized void observe(String camera,boolean occupied){
  if(!occupied)return;
  long now=System.nanoTime();
  if(now-last.getOrDefault(camera,now-2_000_000_000L)<2_000_000_000L)return;
  last.put(camera,now);
  var target=registry.camera(camera);var at=Instant.now();
  try{gateways.send(target.gatewayId(),json.writeValueAsString(Map.of(
   "version",1,"type","cctv.presence","railing_id",target.railingId(),
   "observed_at",at.toString(),"expires_at",at.plusSeconds(3).toString())));}
  catch(Exception ignored){/* Next fresh observation may retry; never retain old occupancy. */}
 }
 @org.springframework.scheduling.annotation.Scheduled(fixedDelay=60000)
 public void prune(){long now=System.nanoTime();last.entrySet().removeIf(v->now-v.getValue()>60_000_000_000L);}
}
