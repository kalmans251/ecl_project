package com.ecl.monitoring;

import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

@Service
public class CctvOverlay {
 private record Frame(Map<String,Object> data,long received,int age){}
 private final Map<String,Frame> frames=new ConcurrentHashMap<>();
 public void accept(String camera,JsonNode n){
  if(n.size()!=3 || !n.path("frame_id").isString() || !n.path("frame_id").asText().matches("[0-9]{1,20}:[0-9]{1,20}") ||
     !n.path("age_ms").isInt() || n.path("age_ms").asInt()<0 || n.path("age_ms").asInt()>800 ||
     !n.path("people").isArray() || n.path("people").size()>20)throw Accounts.bad("Invalid overlay");
  var people=new ArrayList<Map<String,Object>>();
  var ids=new HashSet<String>();
  for(var p:n.path("people")){
   String id=p.path("id").asText(),state=p.path("state").asText();var box=p.path("box");var age=p.path("age");
   if(p.size()!=4 || !p.path("id").isString() || !id.matches("[0-9]{1,20}") || !ids.add(id) ||
      !Set.of("estimated","pending","unknown","disabled","unavailable").contains(state) ||
      !box.isArray() || box.size()!=4 || !(age.isNull() || age.isNumber()))throw Accounts.bad("Invalid person");
   var coords=new ArrayList<Double>();
   for(var v:box){double d=v.asDouble();if(!v.isNumber()||!Double.isFinite(d)||d<0||d>1)throw Accounts.bad("Invalid box");coords.add(d);}
   if(coords.get(0)>=coords.get(2)||coords.get(1)>=coords.get(3))throw Accounts.bad("Invalid box");
   if(state.equals("estimated")!=age.isNumber() || (age.isNumber()&&(!Double.isFinite(age.asDouble())||age.asDouble()<0||age.asDouble()>100)))throw Accounts.bad("Invalid age");
   var person=new LinkedHashMap<String,Object>();person.put("id",id);person.put("box",List.copyOf(coords));person.put("age",age.isNull()?null:age.asDouble());person.put("state",state);people.add(Collections.unmodifiableMap(person));
  }
  frames.put(camera,new Frame(Map.of("frame_id",n.path("frame_id").asText(),"people",List.copyOf(people)),System.nanoTime(),n.path("age_ms").asInt()));
 }
 public Map<String,Object> latest(String camera){
  var f=frames.get(camera);if(f==null)return Map.of("fresh",false,"people",List.of());
  long age=f.age()+(System.nanoTime()-f.received())/1_000_000;
  if(age>1000){frames.remove(camera,f);return Map.of("fresh",false,"people",List.of());}
  var result=new LinkedHashMap<String,Object>(f.data());result.put("fresh",true);result.put("age_ms",age);return result;
 }
 @org.springframework.scheduling.annotation.Scheduled(fixedDelay=5000)
 public void prune(){frames.entrySet().removeIf(e->System.nanoTime()-e.getValue().received()>2_000_000_000L);}
}
