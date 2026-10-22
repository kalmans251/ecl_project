package com.ecl.monitoring;

import static org.junit.jupiter.api.Assertions.*;
import java.time.Instant;
import java.util.Map;
import org.junit.jupiter.api.Test;
import tools.jackson.databind.json.JsonMapper;

class MusicTelemetryTest {
    boolean current=true;
    final Registry registry=new Registry(null,null,null) {
        @Override public Map<String,Object> deviceRail(String gateway,int rail) {
            if(!gateway.equals("g1") || rail<1 || rail>2) throw new IllegalArgumentException("foreign rail");
            return Map.of("ID",rail==1?"rail-a":"rail-b");
        }
    };
    final Gateways gateways=new Gateways() {
        @Override public boolean isCurrent(String gateway,String session) {
            return gateway.equals("g2") || (current && gateway.equals("g1") && session.equals("s1"));
        }
    };
    final MusicTelemetry music=new MusicTelemetry(registry,gateways);
    final JsonMapper json=JsonMapper.builder().build();
    tools.jackson.databind.JsonNode sample(int rail, Instant time, Object state) {
        return json.valueToTree(Map.of("version",1,"type","music_state","railing_id",rail,
            "observed_at",time.toString(),"fresh_ms",10000,"state",state));
    }
    Map<String,Object> playing(String file) { return Map.of("available",true,"state","playing","filename",file,"position_ms",3000); }
    @Test void isolatesRailsAndRejectsOldAndReplacedSamples() {
        Instant now=Instant.now();
        music.accept("g1","s1",sample(1,now,playing("a.mp3")));
        music.accept("g1","s1",sample(2,now,playing("b.mp3")));
        music.accept("g1","s1",sample(1,now.minusMillis(1),playing("old.mp3")));
        assertEquals("a.mp3",music.view("rail-a","g1").get("filename"));
        assertEquals("b.mp3",music.view("rail-b","g1").get("filename"));
        assertEquals(true,music.view("rail-a","g1").get("fresh"));
        current=false;
        assertEquals(false,music.view("rail-a","g1").get("fresh"));
        assertThrows(RuntimeException.class,()->music.accept("g1","s1",sample(1,now,playing("bad"))));
        assertThrows(RuntimeException.class,()->music.accept("g2","s2",sample(1,now,playing("bad"))));
    }
    @Test void unavailableAndStaleSamplesCannotClaimPlaying() {
        music.accept("g1","s1",sample(1,Instant.now().minusSeconds(11),playing("a.mp3")));
        assertEquals(false,music.view("rail-a","g1").get("fresh"));
        music.accept("g1","s1",sample(1,Instant.now(),Map.of("available",false)));
        assertEquals(false,music.view("rail-a","g1").get("available"));
        assertFalse(music.view("rail-a","g1").containsKey("position_ms"));
        assertThrows(RuntimeException.class,()->music.accept("g1","s1",sample(1,Instant.now(),Map.of("available",false,"state","playing"))));
        assertThrows(RuntimeException.class,()->music.accept("g1","s1",sample(1,Instant.now().minusSeconds(61),playing("a"))));
    }
}
