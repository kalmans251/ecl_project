package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import java.util.*;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;
class ControlCommandsTest {
 final JsonMapper json=JsonMapper.builder().build();
 Map<String,Object> step(int node,int service,int command,int status,String data){return Map.of("node",node,"service",service,"command",command,"status",status,"data",data);}
 tools.jackson.databind.JsonNode data(String op,String value,boolean applied,List<?> steps){
  var d=new LinkedHashMap<String,Object>();d.put("railing_id",1);d.put("operation",op);d.put("value",value);d.put("device_application_confirmed",applied);d.put("steps",steps);return json.valueToTree(d);
 }
 @Test void requiresAllPowerStepsAndExactRail(){
  var d=data("power","ac",true,List.of(step(2,7,34,0,"01"),step(2,7,32,0,"01")));
  ControlCommands.validate("power","ac",1,"APPLIED",d);
  assertThrows(RuntimeException.class,()->ControlCommands.validate("power","ac",2,"APPLIED",d));
  assertThrows(RuntimeException.class,()->ControlCommands.validate("power","battery",1,"APPLIED",d));
  assertThrows(RuntimeException.class,()->ControlCommands.validate("power","ac",1,"APPLIED",data("power","ac",true,List.of(step(2,7,34,0,"01")))));
 }
 @Test void policyAndQueryCannotClaimApplication(){
  var policy=data("music.start",null,false,List.of(step(2,2,32,3,"00")));
  ControlCommands.validate("music.start",null,1,"COMPLETED",policy);
  assertThrows(RuntimeException.class,()->ControlCommands.validate("music.start",null,1,"APPLIED",policy));
  ControlCommands.validate("query","s3",1,"COMPLETED",data("query","s3",false,List.of(step(4,0,16,0,"01"))));
  assertThrows(RuntimeException.class,()->ControlCommands.validate("query","s3",1,"COMPLETED",data("query","s3",false,List.of(step(2,0,16,0,"01")))));
 }
 @Test void volumeMustMatchAndStopNeedsWroom(){
  ControlCommands.validate("volume","20",1,"APPLIED",data("volume","20",true,List.of(step(3,2,34,0,"14"))));
  assertThrows(RuntimeException.class,()->ControlCommands.validate("volume","20",1,"APPLIED",data("volume","20",true,List.of(step(3,2,34,0,"15")))));
  assertThrows(RuntimeException.class,()->ControlCommands.validate("music.stop",null,1,"APPLIED",data("music.stop",null,true,List.of(step(2,2,33,0,"00")))));
  ControlCommands.validate("music.stop",null,1,"APPLIED",data("music.stop",null,true,List.of(step(3,2,33,0,"00"))));
 }
}
