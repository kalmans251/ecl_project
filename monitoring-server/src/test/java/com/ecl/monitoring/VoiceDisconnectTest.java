package com.ecl.monitoring;
import java.util.*;
import java.lang.reflect.*;
import org.junit.jupiter.api.Test;
import static org.mockito.Mockito.*;
import static org.junit.jupiter.api.Assertions.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.socket.*;
class VoiceDisconnectTest {
 @Test void onlyCurrentSocketStartsGraceAndErrorsCloseIt()throws Exception{
  JdbcTemplate db=mock(JdbcTemplate.class);
  Voice voice=new Voice(db,mock(Accounts.class),mock(Registry.class),mock(Gateways.class));
  WebSocketSession socket=mock(WebSocketSession.class);when(socket.getId()).thenReturn("new");when(socket.getAttributes()).thenReturn(new HashMap<>());
  Class<?> type=Class.forName("com.ecl.monitoring.Voice$Peer");var ctor=type.getDeclaredConstructors()[0];ctor.setAccessible(true);
  var field=Voice.class.getDeclaredField("peers");field.setAccessible(true);
  @SuppressWarnings("unchecked") Map<String,Object> peers=(Map<String,Object>)field.get(voice);
  peers.put("call",ctor.newInstance(socket,"user","call","epoch"));
  WebSocketSession old=mock(WebSocketSession.class);when(old.getId()).thenReturn("old");when(old.getAttributes()).thenReturn(new HashMap<>());
  voice.afterConnectionClosed(old,CloseStatus.NORMAL);verifyNoInteractions(db);assertEquals(1,peers.size());
  voice.handleTransportError(socket,new RuntimeException("lost"));verify(socket).close(CloseStatus.SERVER_ERROR);
  verify(db).update(contains("touched_at"),any(Long.class),eq("call"),eq("epoch"));assertTrue(peers.isEmpty());
  voice.afterConnectionClosed(socket,CloseStatus.NORMAL);verifyNoMoreInteractions(db);
 }
}
