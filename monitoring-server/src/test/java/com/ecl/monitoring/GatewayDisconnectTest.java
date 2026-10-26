package com.ecl.monitoring;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import java.net.URI;
import java.util.concurrent.ConcurrentHashMap;
import org.junit.jupiter.api.Test;
import org.springframework.web.socket.*;

class GatewayDisconnectTest {
 WebSocketSession session(String id)throws Exception{
  var s=mock(WebSocketSession.class);when(s.getId()).thenReturn(id);
  when(s.getUri()).thenReturn(URI.create("ws://localhost/ws/gateways/gateway-a"));
  when(s.getAttributes()).thenReturn(new ConcurrentHashMap<>());when(s.isOpen()).thenReturn(true);return s;
 }
 @Test void alreadyClosedCurrentSocketMarksUnknownButOldSocketCannotInvalidateReplacement()throws Exception{
  var gateways=new Gateways();var commands=mock(Commands.class);
  var handler=new DeviceSocket(gateways,null,commands,null,null,null,null);
  var old=session("old");var replacement=session("new");gateways.connect("gateway-a",old);
  when(old.isOpen()).thenReturn(false);
  handler.afterConnectionClosed(old,CloseStatus.NORMAL);
  verify(commands).disconnected("gateway-a");assertFalse(gateways.online("gateway-a"));
  clearInvocations(commands);gateways.connect("gateway-a",replacement);
  handler.afterConnectionClosed(old,CloseStatus.NORMAL);
  verifyNoInteractions(commands);assertTrue(gateways.online("gateway-a"));
  when(replacement.isOpen()).thenReturn(false);
  handler.handleTransportError(replacement,new RuntimeException("network lost"));
  verify(commands).disconnected("gateway-a");assertFalse(gateways.online("gateway-a"));
 }
}
