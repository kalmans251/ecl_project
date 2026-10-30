package com.ecl.monitoring;

import java.util.*;
import tools.jackson.databind.JsonNode;

/** Results from Pi's token-correlated device controls, not transport acknowledgments. */
final class ControlCommands {
    static final Set<String> OPERATIONS=Set.of("power","projector","led","weather","led.basic_pattern","led.music_pattern","led.sequence",
        "music.mode","music.start","music.stop","music.pause","music.resume","music.next","volume","sleep","detection","query","detection.count","detection.reset");
    static boolean supports(String op){return OPERATIONS.contains(op);}
    static void validate(String op,String value,int rail,String status,JsonNode data){
        if(Set.of("FAILED","UNKNOWN","EXPIRED").contains(status)){
            if(!data.isNull())throw Accounts.bad("Failure cannot claim applied data");return;
        }
        if(!Set.of("APPLIED","COMPLETED").contains(status) || !data.isObject() || data.size()!=5
            || !data.path("railing_id").isInt() || data.path("railing_id").asInt()!=rail
            || !data.path("operation").asText().equals(op) || !data.has("value")
            || !(value==null?data.get("value").isNull():data.get("value").isString() && value.equals(data.get("value").asText()))
            || !data.path("device_application_confirmed").isBoolean() || !data.path("steps").isArray())throw Accounts.bad("Control identity mismatch");
        int service=switch(op){case "power"->7;case "projector"->8;case "led","weather","led.basic_pattern","led.music_pattern","led.sequence"->1;
            case "sleep"->10;case "detection","detection.count","detection.reset"->9;case "query"->0;default->2;};
        List<Integer> expected;
        if(op.equals("power") && Set.of("ac","battery").contains(value))expected=List.of(0x22,0x20);
        else expected=List.of(switch(op){case "query","detection.count"->0x10;case "detection.reset"->0x36;case "weather","led.basic_pattern","led.music_pattern","led.sequence","volume","music.mode","detection"->0x22;
            case "music.start"->0x20;case "music.stop"->0x21;case "music.pause"->0x24;case "music.resume"->0x25;case "music.next"->0x26;
            default->"on".equals(value)?0x20:"off".equals(value)?0x21:0x22;});
        var steps=data.path("steps");if(steps.size()!=expected.size())throw Accounts.bad("Incomplete control result");
        boolean applied=service!=0 && !op.equals("detection.count");
        for(int i=0;i<steps.size();i++){
            var s=steps.get(i);
            if(!s.isObject() || s.size()!=5 || !s.path("service").isInt() || s.path("service").asInt()!=service
                || !s.path("command").isInt() || s.path("command").asInt()!=expected.get(i)
                || !s.path("status").isInt() || !s.path("node").isInt() || !s.path("data").isString()
                || !s.path("data").asText().matches("(?:[0-9a-f]{2}){1,122}"))throw Accounts.bad("Invalid control step");
            int node=s.path("node").asInt(),code=s.path("status").asInt();
            int target=service==2?3:op.equals("query")?switch(value){case "wroom"->3;case "s3"->4;default->2;}:2;
            if(code==3 && node==2 && service==2 && !Set.of("volume","music.stop").contains(op))applied=false;
            else if(code!=0 || node!=target)throw Accounts.bad("Wrong confirming device");
            if(op.equals("detection.count") || op.equals("detection.reset")) {
                String detail=s.path("data").asText();
                if(!detail.matches("01(?:00|01)[0-9a-f]{8}") || (op.equals("detection.reset")&&!detail.substring(4).equals("00000000")))throw Accounts.bad("Invalid detection count confirmation");
            }
            if(op.equals("volume") && !s.path("data").asText().equals(String.format("%02x",Integer.parseInt(value))))throw Accounts.bad("Wrong volume confirmation");
            if(op.equals("music.stop") && !s.path("data").asText().equals("00"))throw Accounts.bad("Wrong stopped state");
        }
        if(data.path("device_application_confirmed").booleanValue()!=applied || !status.equals(applied?"APPLIED":"COMPLETED"))throw Accounts.bad("Wrong confirmation scope");
    }
}
