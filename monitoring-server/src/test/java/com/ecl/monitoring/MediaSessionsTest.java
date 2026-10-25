package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.*;
import org.junit.jupiter.api.Test;

class MediaSessionsTest {
 @Test void revokedSessionIsKickedAndHealthySessionIsPreserved()throws Exception{
  String revoked=UUID.randomUUID().toString(),active=UUID.randomUUID().toString();
  var kicked=new ArrayList<String>();var server=HttpServer.create(new InetSocketAddress("127.0.0.1",0),0);
  server.createContext("/v3/webrtcsessions/list",q->{byte[] body=("{\"pageCount\":1,\"items\":[{\"id\":\""+revoked+"\"},{\"id\":\""+active+"\"}]}").getBytes(StandardCharsets.UTF_8);q.sendResponseHeaders(200,body.length);q.getResponseBody().write(body);q.close();});
  server.createContext("/v3/webrtcsessions/kick/",q->{assertEquals("POST",q.getRequestMethod());kicked.add(q.getRequestURI().getPath().substring("/v3/webrtcsessions/kick/".length()));q.sendResponseHeaders(200,-1);q.close();});
  server.start();var cctv=mock(Cctv.class);when(cctv.mediaKnown(revoked)).thenReturn(true);when(cctv.mediaValid(active)).thenReturn(true);
  var reaper=new MediaSessions(cctv,"http://127.0.0.1:"+server.getAddress().getPort());
  try{reaper.sweep();assertEquals(List.of(revoked),kicked);verify(cctv).forgetMedia(revoked);verify(cctv).mediaControlReady();verify(cctv,never()).forgetMedia(active);}
  finally{reaper.close();server.stop(0);}
 }
}
