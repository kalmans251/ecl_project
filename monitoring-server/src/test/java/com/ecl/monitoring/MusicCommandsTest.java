package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
class MusicCommandsTest {
 final JsonMapper json=JsonMapper.builder().build();
 @Test void validatesBoundedPagesAndIdentity(){
  for(String v:List.of("default:1","default:32","bad:0","default:0:extra"))assertThrows(RuntimeException.class,()->MusicCommands.parse("music.list",v));
  for(String v:List.of("4294967296:default:0","5:default:32","-1:default:0"))assertThrows(RuntimeException.class,()->MusicCommands.parse("music.play",v));
  var result=json.valueToTree(Map.of("railing_id",1,"catalog_version",5,"group","default","index",0,"filename","a.mp3","state","playing","device_application_confirmed",true));
  MusicCommands.validateResult("music.play","5:default:0",1,"APPLIED",result);
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.play","6:default:0",1,"APPLIED",result));
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.play","5:default:0",2,"APPLIED",result));
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.play","5:default:0",1,"COMPLETED",result));
 }
 @Test void rejectsIncompleteOrWrongGroupPage(){
  var page=json.valueToTree(Map.of("railing_id",1,"catalog_version",5,"group","default","offset",0,"total",1,"tracks",List.of(Map.of("group","default","index",0,"filename","a.mp3"))));
  MusicCommands.validateResult("music.list","default:0",1,"COMPLETED",page);
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.list","10:0",1,"COMPLETED",page));
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.list","default:8",1,"COMPLETED",page));
  assertThrows(RuntimeException.class,()->MusicCommands.validateResult("music.list","default:0",1,"APPLIED",page));
 }
}
