package com.ecl.monitoring;
import java.util.*;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
class StatusDemandTest {
 @Test void scopesAndDeduplicatesViewerDemand() throws Exception {
  Registry r=mock(Registry.class);Accounts a=mock(Accounts.class);Gateways g=mock(Gateways.class);
  when(r.rail("one")).thenReturn(Map.of("SITE_ID","site","GATEWAY_ID","g1","NUMBER",1));
  when(r.rail("two")).thenReturn(Map.of("SITE_ID","site2","GATEWAY_ID","g2","NUMBER",2));
  when(a.permit("blocked","site",false)).thenThrow(new IllegalArgumentException());
  StatusDemand d=new StatusDemand(r,a,g);
  d.refresh();verifyNoInteractions(g);
  assertThrows(IllegalArgumentException.class,()->d.demand(()->"blocked",new StatusDemand.Input("x",List.of("one"))));
  d.demand(()->"u",new StatusDemand.Input("a",List.of("one")));
  d.demand(()->"v",new StatusDemand.Input("b",List.of("one")));
  d.demand(()->"w",new StatusDemand.Input("c",List.of("two")));
  d.refresh();verify(g,times(1)).send(eq("g1"),contains("[1]"));verify(g,times(1)).send(eq("g2"),contains("[2]"));
  reset(g);d.demand(()->"u",new StatusDemand.Input("a",List.of()));d.refresh();verify(g).send(eq("g1"),contains("[1]"));
  reset(g);d.demand(()->"v",new StatusDemand.Input("b",List.of()));d.refresh();verify(g).send(eq("g1"),contains("[]"));
 }
}
