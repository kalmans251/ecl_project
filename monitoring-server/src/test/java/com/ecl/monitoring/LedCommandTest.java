package com.ecl.monitoring;
import static org.junit.jupiter.api.Assertions.*;
import org.junit.jupiter.api.Test;
import org.springframework.web.server.ResponseStatusException;
class LedCommandTest {
    @Test void patternNumbersUseZeroBasedWireContract() {
        for(int i=0;i<6;i++) Commands.validate("led.basic_pattern",Integer.toString(i));
        for(int i=0;i<3;i++) Commands.validate("led.music_pattern",Integer.toString(i));
        for(String invalid:new String[]{null,"-1","6","01","1.0",""})
            assertThrows(ResponseStatusException.class,()->Commands.validate("led.basic_pattern",invalid));
        assertThrows(ResponseStatusException.class,()->Commands.validate("led.music_pattern","3"));
        Commands.validate("led","basic");
        Commands.validate("led","music");
        Commands.validate("weather","clear");
    }
}
