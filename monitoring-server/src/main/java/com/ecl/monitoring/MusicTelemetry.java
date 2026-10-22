package com.ecl.monitoring;

import java.time.Instant;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;

/** Current music snapshots only; never replaces the general device snapshot. */
@Service
public class MusicTelemetry {
    private record Sample(String session, long observed, long freshMs, Map<String,Object> state) {}
    private final Map<String,Sample> samples=new ConcurrentHashMap<>();
    private final Registry registry;
    private final Gateways gateways;
    public MusicTelemetry(Registry registry, Gateways gateways) { this.registry=registry; this.gateways=gateways; }

    public synchronized void accept(String gateway, String session, JsonNode node) {
        if (!gateways.isCurrent(gateway,session)) throw Accounts.bad("Replaced connection");
        if (!node.isObject() || node.size()!=6 || node.path("version").asInt()!=1
                || !node.path("type").asText().equals("music_state")
                || !node.path("railing_id").isInt() || !node.path("fresh_ms").isIntegralNumber())
            throw Accounts.bad("Invalid music envelope");
        long fresh=node.path("fresh_ms").asLong();
        if(fresh<1000 || fresh>120000) throw Accounts.bad("Invalid freshness limit");
        long observed;
        try { observed=Instant.parse(node.path("observed_at").asText()).toEpochMilli(); }
        catch(Exception e) { throw Accounts.bad("Invalid music timestamp"); }
        long now=System.currentTimeMillis();
        if(observed>now+2000 || observed<now-60000) throw Accounts.bad("Stale music snapshot");
        String id=(String)registry.deviceRail(gateway,node.path("railing_id").intValue()).get("ID");
        var s=node.path("state");
        if(!s.isObject() || !s.path("available").isBoolean()) throw Accounts.bad("Invalid music state");
        var state=new LinkedHashMap<String,Object>();
        boolean available=s.path("available").booleanValue();state.put("available",available);
        if(available) {
            if((s.size()!=4 && s.size()!=7) || !Set.of("idle","playing","paused").contains(s.path("state").asText())
                    || !s.path("position_ms").isIntegralNumber() || s.path("position_ms").asLong()<0
                    || s.path("position_ms").asLong()>0xffffffffL || !s.has("filename")
                    || !(s.get("filename").isNull() || s.get("filename").isString())
                    || s.path("filename").asText("").length()>128) throw Accounts.bad("Invalid music fields");
            if(s.size()==7) {
                if(!s.has("duration_ms") || !(s.path("duration_ms").isNull() || MusicCommands.uint(s.path("duration_ms"),0xffffffffL))
                    || !MusicCommands.uint(s.path("playback_id"),0xffffffffL) || !s.path("seekable").isBoolean())throw Accounts.bad("Invalid timeline");
                if(s.path("seekable").booleanValue() && (s.path("duration_ms").asLong()<=0 || s.path("playback_id").asLong()==0 || !s.path("state").asText().equals("playing")))throw Accounts.bad("Invalid seek capability");
                state.put("duration_ms",s.path("duration_ms").isNull()?null:s.path("duration_ms").asLong());
                state.put("playback_id",s.path("playback_id").asLong());state.put("seekable",s.path("seekable").booleanValue());
            }
            state.put("state",s.path("state").asText());
            state.put("filename",s.get("filename").isNull()?null:s.get("filename").asText());
            state.put("position_ms",s.path("position_ms").asLong());
        } else if(s.size()!=1) throw Accounts.bad("Unavailable snapshot must not claim playback");
        Sample old=samples.get(id);
        if(old!=null && old.session().equals(session) && observed<=old.observed()) return;
        samples.put(id,new Sample(session,observed,fresh,Collections.unmodifiableMap(state)));
    }
    public Map<String,Object> view(String rail, String gateway) {
        Sample s=samples.get(rail);if(s==null) return Map.of();
        long age=Math.max(0,System.currentTimeMillis()-s.observed());
        var result=new LinkedHashMap<String,Object>(s.state());
        result.put("observed_at",Instant.ofEpochMilli(s.observed()).toString());
        result.put("age_ms",age);result.put("fresh_ms",s.freshMs());
        result.put("fresh",gateways.isCurrent(gateway,s.session()) && age<s.freshMs());
        return result;
    }
}
