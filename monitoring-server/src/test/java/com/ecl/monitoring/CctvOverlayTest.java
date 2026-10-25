package com.ecl.monitoring;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
import tools.jackson.databind.json.JsonMapper;
class CctvOverlayTest {
 final JsonMapper json=JsonMapper.builder().build();
 final String frame="{\"frame_id\":\"1:2\",\"age_ms\":0,\"people\":[{\"id\":\"1\",\"box\":[0.1,0.2,0.4,0.9],\"age\":28,\"state\":\"estimated\"}]}";
 @Test void expiresAndIsolates() throws Exception{
  var service=new CctvOverlay();service.accept("a",json.readTree(frame));
  assertEquals(true,service.latest("a").get("fresh"));assertEquals(false,service.latest("b").get("fresh"));
  Thread.sleep(1050);assertEquals(false,service.latest("a").get("fresh"));
 }
 @Test void rejectsBadCoordinatesAgesAndOldFrames(){
  var service=new CctvOverlay();
  for(String bad:new String[]{frame.replace("0.1","1.1"),frame.replace("0.4","0.0"),frame.replace("\"age\":28","\"age\":128"),frame.replace("\"age_ms\":0","\"age_ms\":801"),frame.replace("estimated","pending")})
   assertThrows(Exception.class,()->service.accept("a",json.readTree(bad)));
  service.accept("a",json.readTree(frame.replace("\"age\":28","\"age\":null").replace("estimated","pending")));
  assertEquals(true,service.latest("a").get("fresh"));
 }
}
