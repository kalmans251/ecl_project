package com.ecl.monitoring;

import java.util.Set;
import tools.jackson.databind.JsonNode;

/** Strict, bounded music command/result protocol. Names are never executable paths. */
final class MusicCommands {
    static final Set<String> GROUPS=Set.of("default","10","20","30","40");
    record Selection(long version,String group,int index) {}
    static boolean supports(String operation) { return "music.list".equals(operation)||"music.play".equals(operation); }
    static Selection parse(String operation,String value) {
        if(value==null) throw Accounts.bad("Music selection required");
        String[] p=value.split(":",-1);
        try {
            if(operation.equals("music.list") && p.length==2 && GROUPS.contains(p[0]) && Set.of("0","8","16","24").contains(p[1]))
                return new Selection(0,p[0],Integer.parseInt(p[1]));
            if(operation.equals("music.play") && p.length==3 && p[0].matches("[0-9]{1,10}") && GROUPS.contains(p[1]) && p[2].matches("[0-9]{1,2}")) {
                long version=Long.parseLong(p[0]);int index=Integer.parseInt(p[2]);
                if(version<=0xffffffffL && index<32) return new Selection(version,p[1],index);
            }
        } catch(NumberFormatException ignored) {}
        throw Accounts.bad("Invalid music selection");
    }
    static boolean uint(JsonNode n,long max) { return (n.isInt() || n.isLong()) && n.asLong()>=0 && n.asLong()<=max; }
    static boolean filename(JsonNode n) { return n.isString() && !n.asText().isEmpty() && n.asText().length()<=95; }
    static void validateResult(String operation,String value,int rail,String status,JsonNode data) {
        if(Set.of("FAILED","UNKNOWN","EXPIRED").contains(status)) {
            if(!data.isNull()) throw Accounts.bad("Failure cannot claim music result");return;
        }
        Selection choice=parse(operation,value);
        if(!data.isObject() || !data.path("railing_id").isInt() || data.path("railing_id").intValue()!=rail
            || !uint(data.path("catalog_version"),0xffffffffL) || !choice.group().equals(data.path("group").asText())) throw Accounts.bad("Music result mismatch");
        if(operation.equals("music.list")) {
            if(!status.equals("COMPLETED") || data.size()!=6 || !data.path("offset").isInt() || data.path("offset").intValue()!=choice.index()
                || !uint(data.path("total"),32) || !data.path("tracks").isArray()) throw Accounts.bad("Invalid catalog page");
            int count=Math.max(0,Math.min(8,data.path("total").intValue()-choice.index()));
            if(data.path("tracks").size()!=count) throw Accounts.bad("Incomplete catalog page");
            int index=choice.index();
            for(var track:data.path("tracks")) {
                if(!track.isObject() || track.size()!=3 || !choice.group().equals(track.path("group").asText())
                    || !track.path("index").isInt() || track.path("index").intValue()!=index++ || !filename(track.path("filename"))) throw Accounts.bad("Invalid track");
            }
        } else if(!status.equals("APPLIED") || data.size()!=7 || data.path("catalog_version").asLong()!=choice.version()
            || !data.path("index").isInt() || data.path("index").intValue()!=choice.index() || !data.path("state").asText().equals("playing")
            || !data.path("device_application_confirmed").isBoolean() || !data.path("device_application_confirmed").booleanValue()
            || !filename(data.path("filename"))) throw Accounts.bad("Selected track not confirmed");
    }
}
