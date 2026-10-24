package com.ecl.monitoring;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;
class VoiceRateLimitTest {
    @Test void recorded91msGapAndCompensatingDelayRemainValid() {
        var rate=new VoiceRateLimit();long now=0;
        assertTrue(rate.allow(now));
        for(int i=0;i<1000;i++){
            now+=229_000_000L;assertTrue(rate.allow(now));
            now+=91_000_000L;assertTrue(rate.allow(now));
        }
    }
    @Test void boundedBurstRecoversWithoutResetOrSleep() {
        var rate=new VoiceRateLimit();
        for(int i=0;i<3;i++)assertTrue(rate.allow(0));
        for(int i=0;i<1000;i++)assertFalse(rate.allow(0));
        assertFalse(rate.allow(159_999_999));assertTrue(rate.allow(160_000_000));
        assertFalse(rate.allow(160_000_000));
    }
    @Test void idleDoesNotCreateUnlimitedCredit() {
        var rate=new VoiceRateLimit();assertTrue(rate.allow(-1_000_000_000L));
        for(int i=0;i<3;i++)assertTrue(rate.allow(10_000_000_000L));
        assertFalse(rate.allow(10_000_000_000L));
    }
    @Test void sustainedFloodCannotExceedBoundedRate() {
        var rate=new VoiceRateLimit();int accepted=0;
        for(int i=0;i<=10000;i++)if(rate.allow(i*1_000_000L))accepted++;
        assertEquals(3+10000/160,accepted);
    }
}
