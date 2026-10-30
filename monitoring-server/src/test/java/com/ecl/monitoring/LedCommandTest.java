package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
class LedCommandTest {
    @Test void patternNumbersUseZeroBasedWireContract() {
        for(int i=0;i<9;i++) Commands.validate("led.basic_pattern",Integer.toString(i));
        for(int i=0;i<3;i++) Commands.validate("led.music_pattern",Integer.toString(i));
        for(String invalid:new String[]{null,"-1","9","01","1.0",""})
            assertThrows(ResponseStatusException.class,()->Commands.validate("led.basic_pattern",invalid));
        assertThrows(ResponseStatusException.class,()->Commands.validate("led.music_pattern","3"));
        Commands.validate("led.sequence","1");Commands.validate("led.sequence","120");
        for(String value:new String[]{"0","121","1.5"})assertThrows(ResponseStatusException.class,()->Commands.validate("led.sequence",value));
        Commands.validate("led","basic");
        Commands.validate("led","music");
        Commands.validate("weather","clear");
    }
}
