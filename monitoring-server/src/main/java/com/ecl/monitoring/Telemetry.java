package com.ecl.monitoring;
import java.time.Instant;
import java.util.*;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
@Service
public class Telemetry {
    private final JdbcTemplate db; private final Registry registry; private final JsonMapper json=JsonMapper.builder().build();
    private static final Set<String> NUMERIC=Set.of("left_watt","right_watt","battery_percent","volume","wind","pm10");
    private static final Set<String> FLAGS=Set.of("emergency","projector","led_enabled","sleep","power_on");
    private static final Map<String,Set<String>> ENUMS=Map.of("power",Set.of("ac","battery"),"led",Set.of("basic","music","weather"),"weather",Set.of("clear","cloudy","rain","snow"),"music",Set.of("playing","paused","stopped"),"music_mode",Set.of("sequential","shuffle","age"),"detection",Set.of("radar","cctv"));
    public Telemetry(JdbcTemplate db,Registry registry){this.db=db;this.registry=registry;}
    public synchronized void accept(String gateway,JsonNode node) {
        if(node.size()!=5 || !node.path("railing_id").isInt() || !node.path("state").isObject())throw Accounts.bad("Invalid telemetry envelope");
        long observed;try{observed=Instant.parse(node.path("observed_at").asText()).toEpochMilli();}catch(Exception e){throw Accounts.bad("Invalid timestamp");}
        long now=System.currentTimeMillis();if(observed>now+2000 || observed<now-60000)throw Accounts.bad("Stale telemetry");
        var rail=registry.deviceRail(gateway,node.path("railing_id").intValue());String id=(String)rail.get("ID");
        if(rail.get("SEEN_AT")!=null && ((Number)rail.get("SEEN_AT")).longValue()>=observed)return;
        JsonNode state=node.path("state");if(state.size()>30)throw Accounts.bad("Too many state fields");
        for(String key:state.propertyNames()) {
            JsonNode value=state.get(key);
            if(NUMERIC.contains(key)) {
                double n=value.asDouble();double max=key.equals("battery_percent")||key.equals("volume")?100:100000;
                if(!value.isNumber()||!Double.isFinite(n)||n<0||n>max)throw Accounts.bad("Invalid numeric state");
            } else if(FLAGS.contains(key)) {if(!value.isBoolean())throw Accounts.bad("Invalid state flag");}
            else if(ENUMS.containsKey(key)){if(!value.isString()||!ENUMS.get(key).contains(value.asText()))throw Accounts.bad("Invalid state enum");}
            else if(key.equals("radar")) {
                if(!value.isArray()||value.size()>3)throw Accounts.bad("Invalid radar targets");
                for(var target:value)if(target.size()!=2 || !target.path("x").isNumber() || !target.path("y").isNumber() || !Double.isFinite(target.path("x").asDouble()) || !Double.isFinite(target.path("y").asDouble()) || Math.abs(target.path("x").asDouble())>10 || target.path("y").asDouble()<0 || target.path("y").asDouble()>10)throw Accounts.bad("Invalid radar coordinates");
            } else if(key.equals("detection_count")){if(!value.isIntegralNumber()||value.asLong()<0)throw Accounts.bad("Invalid count");}
            else throw Accounts.bad("Unknown state field");
        }
        db.update("UPDATE rails SET snapshot=?,seen_at=? WHERE id=?",json.writeValueAsString(state),observed,id);
        db.update("INSERT INTO telemetry_samples(id,rail_id,observed_at,left_watt,right_watt,battery_percent,emergency) VALUES(?,?,?,?,?,?,?)",UUID.randomUUID().toString(),id,observed,number(state,"left_watt"),number(state,"right_watt"),number(state,"battery_percent"),state.has("emergency")?state.get("emergency").booleanValue():null);
    }
    private Double number(JsonNode node,String key){return node.has(key)?node.get(key).asDouble():null;}
    @org.springframework.scheduling.annotation.Scheduled(fixedDelay=3600000) public void prune(){db.update("DELETE FROM telemetry_samples WHERE observed_at<?",System.currentTimeMillis()-90L*86400000);}
}
