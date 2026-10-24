package com.ecl.monitoring;

import static org.junit.jupiter.api.Assertions.*;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.UUID;
import java.util.concurrent.Executors;
import org.junit.jupiter.api.Test;

@org.junit.jupiter.api.condition.EnabledIfSystemProperty(named="codec.native.tests",matches="true")
class Codec2Test {
    private Codec2 codec(String library) {
        return new Codec2(new PortalSettings(null,null,null,null,null,library));
    }
    private String id() { return UUID.randomUUID().toString(); }
    @Test void realNativeRoundTripAndRelease() {
        try (var codec=codec(System.getenv().getOrDefault("CODEC2_LIBRARY","codec2"))) {
            assertTrue(codec.available(),codec.unavailableReason());
            String call=id(),epoch=id();
            var pcm=ByteBuffer.allocate(2560).order(ByteOrder.LITTLE_ENDIAN);
            for(int i=0;i<1280;i++)pcm.putShort((short)(10000*Math.sin(2*Math.PI*220*i/8000)));
            byte[] bits=codec.convert(call,epoch,true,pcm.array());assertEquals(48,bits.length);
            byte[] output=codec.convert(call,epoch,false,bits);assertEquals(2560,output.length);
            int peak=0;var decoded=ByteBuffer.wrap(output).order(ByteOrder.LITTLE_ENDIAN);
            while(decoded.hasRemaining())peak=Math.max(peak,Math.abs((int)decoded.getShort()));
            assertTrue(peak>0,"Decoder must produce nonzero PCM");assertEquals(2,codec.streamCount());
            codec.convert(call,id(),true,pcm.array());assertEquals(1,codec.streamCount());
            codec.release(call);assertEquals(0,codec.streamCount());
            codec.close();codec.close();assertFalse(codec.available());
            assertThrows(IllegalStateException.class,()->codec.convert(call,epoch,true,pcm.array()));
        }
    }
    @Test void badLengthsAndIdsNeverAllocate() {
        try(var codec=codec(System.getenv().getOrDefault("CODEC2_LIBRARY","codec2"))){
            assertTrue(codec.available(),codec.unavailableReason());
            assertThrows(IllegalArgumentException.class,()->codec.convert(id(),id(),true,new byte[2]));
            assertThrows(IllegalArgumentException.class,()->codec.convert(id(),id(),false,new byte[47]));
            assertThrows(IllegalArgumentException.class,()->codec.convert("bad",id(),true,new byte[2560]));
            assertEquals(0,codec.streamCount());
        }
    }
    @Test void streamsAreIsolatedUnderConcurrentConversion() throws Exception {
        try(var codec=codec(System.getenv().getOrDefault("CODEC2_LIBRARY","codec2"))){
            assertTrue(codec.available(),codec.unavailableReason());
            var pool=Executors.newFixedThreadPool(4);
            try {
                var tasks=new java.util.ArrayList<java.util.concurrent.Future<byte[]>>();
                for(int i=0;i<12;i++)tasks.add(pool.submit(()->codec.convert(id(),id(),true,new byte[2560])));
                for(var task:tasks)assertEquals(48,task.get().length);
                assertEquals(12,codec.streamCount());
            }finally{pool.shutdownNow();}
        }
    }
    @Test void streamLimitAndIdleCleanupFreeNativeStates() {
        try(var codec=codec(System.getenv().getOrDefault("CODEC2_LIBRARY","codec2"))){
            assertTrue(codec.available(),codec.unavailableReason());
            for(int i=0;i<128;i++)codec.convert(id(),id(),true,new byte[2560]);
            assertThrows(IllegalStateException.class,()->codec.convert(id(),id(),true,new byte[2560]));
            var states=(java.util.Map<?,?>)org.springframework.test.util.ReflectionTestUtils.getField(codec,"states");
            var first=states.values().iterator().next();
            org.springframework.test.util.ReflectionTestUtils.setField(first,"touched",System.nanoTime()-61_000_000_000L);
            codec.clean();assertEquals(127,codec.streamCount());
            codec.convert(id(),id(),true,new byte[2560]);assertEquals(128,codec.streamCount());
        }
    }
    @Test void missingLibraryDisablesVoiceWithoutCrashingServer() {
        try(var codec=codec("/no-such-codec2/"+id()+".dll")){
            assertFalse(codec.available());assertNotNull(codec.unavailableReason());
            codec.release(id());codec.clean();assertEquals(0,codec.streamCount());
        }
    }
}
