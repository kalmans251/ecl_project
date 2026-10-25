package com.ecl.monitoring;
import java.net.URI;
import java.net.http.*;
import java.time.Duration;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;
import org.springframework.stereotype.Component;
import tools.jackson.databind.json.JsonMapper;

/** MediaMTX v1.21.2 does not enforce HTTP auth response expiry on live sessions.
 * Reap revoked/expired readers using the loopback-only administration API.
 * Network I/O runs outside the Spring scheduler used by PLC/voice control. */
@Component
public class MediaSessions {
 private final Cctv cctv;
 private final HttpClient client=HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(1)).build();
 private final ExecutorService worker=Executors.newSingleThreadExecutor(r->{var t=new Thread(r,"cctv-media-reaper");t.setDaemon(true);return t;});
 private final AtomicBoolean busy=new AtomicBoolean();
 private final Map<String,Long> unknown=new ConcurrentHashMap<>();
 private final JsonMapper json=JsonMapper.builder().build();
 public MediaSessions(Cctv cctv){this.cctv=cctv;}
 @org.springframework.scheduling.annotation.Scheduled(fixedDelay=5000) public void tick(){
  if(busy.compareAndSet(false,true))worker.submit(()->{try{sweep();}catch(Exception e){cctv.mediaControlFailed();}finally{busy.set(false);}});
 }
 private void sweep()throws Exception{
  Set<String> present=new HashSet<>();
  for(int page=0;page<20;page++){
   var response=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:9997/v3/webrtcsessions/list?itemsPerPage=100&page="+page)).timeout(Duration.ofSeconds(1)).GET().build(),HttpResponse.BodyHandlers.ofString());
   if(response.statusCode()!=200||response.body().length()>500000)throw new IllegalStateException("Media control unavailable");
   var body=json.readTree(response.body());if(!body.path("items").isArray())throw new IllegalStateException("Invalid media inventory");
   for(var item:body.path("items")){
    String id=item.path("id").asText();UUID.fromString(id);present.add(id);
    boolean known=cctv.mediaKnown(id),valid=cctv.mediaValid(id);
    if(valid){unknown.remove(id);continue;}
    // A new session may appear just before its authentication callback arrives.
    long first=unknown.computeIfAbsent(id,k->System.currentTimeMillis());
    if(known||System.currentTimeMillis()-first>10000){
     var kicked=client.send(HttpRequest.newBuilder(URI.create("http://127.0.0.1:9997/v3/webrtcsessions/kick/"+id)).timeout(Duration.ofSeconds(1)).POST(HttpRequest.BodyPublishers.noBody()).build(),HttpResponse.BodyHandlers.discarding());
     if(kicked.statusCode()!=200&&kicked.statusCode()!=404)throw new IllegalStateException("Media termination failed");
     cctv.forgetMedia(id);unknown.remove(id);
    }
   }
   if(page+1>=body.path("pageCount").asInt(1)){cctv.mediaControlReady();break;}
   if(page==19)throw new IllegalStateException("Media inventory limit");
  }
  unknown.keySet().retainAll(present);cctv.pruneMedia(present);
 }
 @jakarta.annotation.PreDestroy public void close(){worker.shutdownNow();}
}
